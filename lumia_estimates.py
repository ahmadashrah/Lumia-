"""
lumia_estimates.py — Estimates tab backend for Lumia.

Receives a PDF drawing, runs it through the Gemini extraction pipeline,
then uses Claude to produce a painting-specific estimate + work order.
Jobs run in background threads; status is stored in-memory.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime
from typing import Optional

import anthropic as _anthropic

# ── Job store ─────────────────────────────────────────────────────────────────
# In-memory cache PLUS a write-through to Supabase Storage. With multiple
# Gunicorn workers, an in-memory-only store breaks: the worker that handles the
# upload isn't the one that handles the status poll, causing "Job not found".
# We persist each job as JSON in the estimates bucket so ANY worker can read it.
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

_supabase = None            # injected by lumia_app via set_supabase()
_JOB_BUCKET = "estimate-pdfs"
_JOB_PREFIX = "_jobstate/"  # JSON job-state files live here in the bucket


def set_supabase(client, bucket: str = "estimate-pdfs") -> None:
    """lumia_app injects its Supabase client so job state can be shared
    across worker processes."""
    global _supabase, _JOB_BUCKET
    _supabase = client
    _JOB_BUCKET = bucket


def _persist_job(job_id: str, job: dict) -> None:
    """Write-through the job dict to Supabase Storage as JSON. Best-effort."""
    if not _supabase:
        return
    try:
        payload = json.dumps(job, default=str).encode("utf-8")
        path = f"{_JOB_PREFIX}{job_id}.json"
        # upsert so progress updates overwrite the same file
        _supabase.storage.from_(_JOB_BUCKET).upload(
            path, payload,
            file_options={"content-type": "application/json", "upsert": "true"},
        )
    except Exception as exc:
        print(f"[Estimates] job persist failed for {job_id}: {exc}")


def _load_job_from_storage(job_id: str) -> Optional[dict]:
    if not _supabase:
        return None
    try:
        path = f"{_JOB_PREFIX}{job_id}.json"
        raw = _supabase.storage.from_(_JOB_BUCKET).download(path)
        if raw:
            return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except Exception:
        return None
    return None

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MODEL_CLAUDE   = os.getenv("CLAUDE_MODEL", os.getenv("MODEL", "claude-opus-4-7"))


PAINTING_PROMPT = """You are reading one page of an architectural drawing set. Extract painting takeoff data ONLY.

Return JSON in this exact shape (no markdown, no commentary):
{
  "sheet_title": "...",                    // e.g. "10TH FLOOR - FINISH PLAN"
  "scale": "...",                          // e.g. "3/16\\" = 1'-0\\""
  "rooms": [
    {"name": "...", "number": "...", "finish_codes_visible": ["PT-2"]}
  ],
  "finish_codes_legend": [
    {"code": "PT-1", "description": "..."},
    {"code": "PT-2", "description": "..."}
  ],
  "general_notes": [
    "Verbatim quote — e.g. 'ALL PERIMETER WALLS TO BE PAINTED PT-2'"
  ],
  "dimensions": [
    {"value": "29'-10 1/2\\"", "describes": "overall east-west wall length (north side)"}
  ],
  "wall_height_called_out": null,          // ft+inches if shown anywhere; null otherwise
  "ceiling_painting_called_out": false,    // true ONLY if a finish code is assigned to ceilings
  "trim_baseboard_painting_called_out": false,  // true ONLY if trim painting is explicit
  "exclusions_or_existing": ["e.g. 'EX.CPT-1 existing carpet to remain', 'N.F.C in mech zone'"]
}

RULES:
- Read the page carefully. Look at finish-code labels on walls (e.g. PT-1, PT-2), room tags, dimension strings, and the general-notes block.
- DO NOT calculate areas. Just report what is shown.
- DO NOT invent ceilings or trim if they are not on the page.
- If a code legend or finish schedule isn't on this page, leave finish_codes_legend empty — but still capture finish codes you see on walls in rooms[].finish_codes_visible.
- Use plain quotes verbatim from the drawing for general_notes.
- Return ONLY the JSON object."""


# ── Job helpers ───────────────────────────────────────────────────────────────

def create_job(file_name: str, client_name: str = "", site_address: str = "") -> str:
    job_id = str(uuid.uuid4())
    job = {
        "id":           job_id,
        "created_at":   datetime.utcnow().isoformat(),
        "file_name":    file_name,
        "client_name":  client_name,
        "site_address": site_address,
        "status":       "queued",   # queued → processing → done | error
        "progress":     "Queued…",
        "raw_json":     None,
        "paint_calc":   None,
        "work_order":   None,
        "error":        None,
    }
    with _jobs_lock:
        _jobs[job_id] = job
    _persist_job(job_id, job)   # write-through so other workers can see it
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    # Always prefer the SHARED storage copy — it's the authoritative state,
    # written by whichever worker is running the extraction. Local cache is
    # only a fallback for when storage is unavailable. (Reading cache-first
    # would return stale "processing" forever, since the extraction worker
    # and the polling worker are usually different processes.)
    remote = _load_job_from_storage(job_id)
    if remote is not None:
        with _jobs_lock:
            _jobs[job_id] = remote      # refresh local cache
        return dict(remote)
    with _jobs_lock:
        return dict(_jobs.get(job_id, {}))


def _update_job(job_id: str, **kwargs):
    with _jobs_lock:
        if job_id not in _jobs:
            # Pull from storage first so we don't clobber another worker's state
            remote = _load_job_from_storage(job_id)
            _jobs[job_id] = remote if remote is not None else {"id": job_id}
        _jobs[job_id].update(kwargs)
        snapshot = dict(_jobs[job_id])
    _persist_job(job_id, snapshot)   # write-through


# ── Extraction worker (background thread) ─────────────────────────────────────

def _run_extraction(job_id: str, pdf_bytes: bytes, file_name: str,
                    client_name: str, site_address: str):
    """Runs in a daemon thread. Calls Gemini, then Claude."""
    try:
        _update_job(job_id, status="processing", progress="Starting Gemini extraction…")

        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY not set in environment.")

        # Write PDF to a temp file — extract_gemini needs a path
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tf.write(pdf_bytes)
            tmp_path = tf.name

        try:
            _update_job(job_id, progress="Rendering PDF pages…")
            from google import genai
            from google.genai import types
            import pdf_utils

            client_gemini = genai.Client(api_key=GEMINI_API_KEY)
            total_pages = pdf_utils.page_count(tmp_path)

            pages_output = []
            failed_pages = []  # any page we couldn't extract — used to fail the job loudly
            for idx in range(total_pages):
                _update_job(job_id, progress=f"Extracting page {idx + 1} of {total_pages}…")
                # Render at high DPI so Flash can read room labels and finish codes
                img_bytes = pdf_utils.render_page_png_bytes(tmp_path, idx, 300)

                # Retry on transient errors (503 UNAVAILABLE, 429 RESOURCE_EXHAUSTED,
                # 500 INTERNAL, 504 DEADLINE). Wait 4s → 8s → 16s → 32s between tries.
                text = None
                last_exc = None
                for attempt in range(5):
                    try:
                        resp = client_gemini.models.generate_content(
                            model=GEMINI_MODEL,
                            contents=[
                                types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                                PAINTING_PROMPT,
                            ],
                            config=types.GenerateContentConfig(
                                max_output_tokens=8000,
                                thinking_config=types.ThinkingConfig(thinking_budget=4096),
                            ),
                        )
                        text = (resp.text or "").strip()
                        break
                    except Exception as exc:
                        last_exc = exc
                        msg = str(exc).upper()
                        transient = any(tok in msg for tok in (
                            "UNAVAILABLE","503","RESOURCE_EXHAUSTED","429",
                            "DEADLINE_EXCEEDED","504","INTERNAL","500",
                        ))
                        if not transient or attempt == 4:
                            break
                        wait_s = 4 * (2 ** attempt)
                        print(f"[Estimates] page {idx+1} attempt {attempt+1} transient ({msg[:60]}) — retry in {wait_s}s")
                        _update_job(job_id,
                            progress=f"Gemini overloaded — retry {attempt+1}/4 for page {idx+1} in {wait_s}s…")
                        import time as _time
                        _time.sleep(wait_s)
                if text is None:
                    err_str = str(last_exc) if last_exc else "no response"
                    print(f"[Estimates] page {idx+1}: Gemini failed after retries — {err_str[:120]}")
                    pages_output.append({"page_number": idx+1, "extraction": None,
                                         "raw_output": f"ERROR: {err_str[:300]}"})
                    failed_pages.append((idx+1, err_str[:200]))
                    continue
                # Parse JSON
                page_obj = None
                if text:
                    t = text
                    if t.startswith("```"):
                        try: t = t.split("\n", 1)[1].rsplit("```", 1)[0]
                        except Exception: pass
                    try:
                        page_obj = json.loads(t)
                    except json.JSONDecodeError:
                        # Try to find first {...}
                        s = t.find("{"); e = t.rfind("}")
                        if s >= 0 and e > s:
                            try: page_obj = json.loads(t[s:e+1])
                            except Exception: page_obj = None
                n_rooms = len((page_obj or {}).get("rooms") or [])
                n_notes = len((page_obj or {}).get("general_notes") or [])
                n_dims  = len((page_obj or {}).get("dimensions") or [])
                print(f"[Estimates] page {idx+1}/{total_pages}: rooms={n_rooms} notes={n_notes} dims={n_dims}" +
                      ("" if page_obj else f" | raw start: {text[:200]!r}"))
                pages_output.append({
                    "page_number": idx + 1,
                    "extraction":  page_obj,
                    "raw_output":  text if not page_obj else None,
                })

            total_rooms = sum(len((p.get("extraction") or {}).get("rooms") or []) for p in pages_output)
            total_notes = sum(len((p.get("extraction") or {}).get("general_notes") or []) for p in pages_output)
            total_dims  = sum(len((p.get("extraction") or {}).get("dimensions") or []) for p in pages_output)
            raw_json = {
                "document_totals": {
                    "file_name":          file_name,
                    "pages_processed":    len(pages_output),
                    "total_rooms":        total_rooms,
                    "total_notes":        total_notes,
                    "total_dimensions":   total_dims,
                    "total_measurements": total_rooms + total_dims,
                },
                "pages": pages_output,
            }
            print(f"[Estimates] EXTRACTION COMPLETE: {total_rooms} rooms · {total_notes} notes · {total_dims} dimensions across {len(pages_output)} page(s) · {len(failed_pages)} failed")

            # Fail loudly instead of producing a $0 estimate from empty extraction
            if failed_pages:
                page_list = ", ".join(f"page {p[0]} ({p[1][:60]})" for p in failed_pages[:5])
                more = f" and {len(failed_pages) - 5} more" if len(failed_pages) > 5 else ""
                raise RuntimeError(
                    f"Gemini extraction failed on {len(failed_pages)} of {total_pages} page(s) "
                    f"after retries: {page_list}{more}. This is usually a transient Google API "
                    f"outage. Try again in 1–2 minutes."
                )
            if total_rooms == 0 and total_dims == 0:
                raise RuntimeError(
                    "Gemini returned no rooms and no dimensions across all pages. "
                    "This usually means the PDF rendered as low-resolution / blank pages. "
                    "Try a different PDF or check that the file isn't password-protected."
                )

        finally:
            try: os.unlink(tmp_path)
            except Exception: pass

        _update_job(job_id, progress="Generating painting estimate…", raw_json=raw_json)

        # Persist the raw Gemini extraction to Supabase storage so we don't
        # have to re-pay for extraction on the same PDF later. Best-effort —
        # if it fails the run still continues.
        try:
            from supabase import create_client as _create_supabase
            _sb_url = os.getenv("SUPABASE_URL", "")
            _sb_key = os.getenv("SUPABASE_KEY", "") or os.getenv("SUPABASE_SERVICE_KEY", "")
            storage_path = (get_job(job_id) or {}).get("storage_path")
            if _sb_url and _sb_key and storage_path:
                _sb = _create_supabase(_sb_url, _sb_key)
                cache_key = "estimate-cache/" + storage_path.replace(".pdf", ".json")
                _sb.storage.from_("checkin-photos").upload(
                    cache_key, json.dumps(raw_json).encode("utf-8"),
                    file_options={"content-type": "application/json", "x-upsert": "true"},
                )
                _update_job(job_id, cache_path=cache_key)
                print(f"[Estimates] Cached extraction → {cache_key}")
        except Exception as exc:
            print(f"[Estimates] Cache save failed (non-fatal): {exc}")

        # ── Claude: convert measurements → painting estimate ──────────────────
        paint_calc = _generate_paint_calc(raw_json, client_name, site_address)
        _update_job(job_id, progress="Generating work order…", paint_calc=paint_calc)

        # ── Claude: write work order ──────────────────────────────────────────
        work_order = _generate_work_order(raw_json, paint_calc, client_name, site_address)

        _update_job(job_id,
                    status="done",
                    progress="Complete.",
                    paint_calc=paint_calc,
                    work_order=work_order)

    except Exception as exc:
        import traceback
        _update_job(job_id, status="error", progress="Failed.", error=str(exc))
        print(f"[Estimates] Job {job_id} error: {exc}")
        traceback.print_exc()


def regenerate_from_cache(job_id: str, raw_json: dict,
                          client_name: str = "", site_address: str = "") -> None:
    """Re-run only the Claude paint_calc + work_order steps against an
    already-extracted raw_json. No Gemini calls. Used by 'Re-run estimate'
    button and by 'Estimate from saved extraction' flow."""
    def _worker():
        try:
            _update_job(job_id, status="processing",
                        progress="Re-running estimate from saved extraction (no Gemini charge)…",
                        raw_json=raw_json)
            paint_calc = _generate_paint_calc(raw_json, client_name, site_address)
            _update_job(job_id, progress="Drafting work order…", paint_calc=paint_calc)
            work_order = _generate_work_order(raw_json, paint_calc, client_name, site_address)
            _update_job(job_id, status="done", progress="Complete.",
                        paint_calc=paint_calc, work_order=work_order)
        except Exception as exc:
            import traceback; traceback.print_exc()
            _update_job(job_id, status="error", progress="Failed.", error=str(exc))
    threading.Thread(target=_worker, daemon=True).start()


def start_extraction(job_id: str, pdf_bytes: bytes, file_name: str,
                     client_name: str = "", site_address: str = ""):
    t = threading.Thread(
        target=_run_extraction,
        args=(job_id, pdf_bytes, file_name, client_name, site_address),
        daemon=True,
    )
    t.start()


# ── Claude helpers ────────────────────────────────────────────────────────────

def _flatten_pages(raw_json: dict) -> dict:
    """Aggregate per-page painting-takeoff extractions, but ONLY include rooms
    from sheets that actually call out painting (Finish Plan / Elevation /
    similar). Life-safety, partition, furniture, RCP, and electrical sheets
    list rooms that are NOT in the painting scope and would otherwise get
    pulled into the estimate."""
    out = {"rooms": [], "finish_codes_legend": [], "general_notes": [],
           "dimensions": [], "wall_height_called_out": None,
           "ceiling_painting_called_out": False,
           "trim_baseboard_painting_called_out": False,
           "exclusions_or_existing": [],
           "sheets": [],
           "rooms_dropped": []}  # for diagnostics — rooms ignored because no finish codes

    # Track which rooms we've seen so we can de-dupe across sheets (a room
    # might appear on both the Finish Plan and the Elevation sheet)
    seen_keys: set = set()
    for page in raw_json.get("pages") or []:
        ext = page.get("extraction") or {}
        if not isinstance(ext, dict): continue
        sheet_title = (ext.get("sheet_title") or "").upper()
        out["sheets"].append({"page": page.get("page_number"),
                              "title": ext.get("sheet_title"),
                              "scale": ext.get("scale")})
        # Always merge non-room lists — notes/dimensions/legend/etc come from many sheets
        for k in ("finish_codes_legend","general_notes",
                  "dimensions","exclusions_or_existing"):
            v = ext.get(k) or []
            if isinstance(v, list): out[k].extend(v)
        if ext.get("wall_height_called_out") and not out["wall_height_called_out"]:
            out["wall_height_called_out"] = ext["wall_height_called_out"]
        if ext.get("ceiling_painting_called_out"):
            out["ceiling_painting_called_out"] = True
        if ext.get("trim_baseboard_painting_called_out"):
            out["trim_baseboard_painting_called_out"] = True

        # Filter rooms: keep ONLY those with explicit finish_codes_visible
        # OR rooms from sheets that are clearly painting-related
        is_painting_sheet = any(tok in sheet_title for tok in
            ("FINISH PLAN","FINISH SCHEDULE","ELEVATION","INTERIOR ELEVATION"))

        def _strip_elev_suffix(num: str) -> str:
            """Strip elevation-direction suffixes so 'MEETING ROOM 1023B - W'
            collapses with 'MEETING ROOM 1023B'."""
            import re as _re2
            if not num: return ""
            s = str(num).strip()
            # Remove patterns like " - W", "-E", " N", " S", " (W)", " - WEST"
            s = _re2.sub(r"\s*[-(]?\s*(north|south|east|west|n|s|e|w)\b\)?\s*$", "", s, flags=_re2.I)
            return s.strip()

        for r in (ext.get("rooms") or []):
            if not isinstance(r, dict): continue
            codes = r.get("finish_codes_visible") or []
            # Normalize the key so elevations collapse into the parent room
            base_num = _strip_elev_suffix(r.get("number") or "")
            base_name = (r.get("name") or "").strip().upper()
            # Also strip elevation suffix from the name itself
            base_name = _strip_elev_suffix(base_name)
            key = (base_name, base_num)
            if codes:
                # Real painting scope — include if new
                if key not in seen_keys:
                    seen_keys.add(key)
                    out["rooms"].append(r)
                else:
                    # Merge codes into the existing entry
                    for existing in out["rooms"]:
                        if (existing.get("name") or "").strip().upper() == key[0] and \
                           str(existing.get("number") or "") == key[1]:
                            existing.setdefault("finish_codes_visible", [])
                            for c in codes:
                                if c not in existing["finish_codes_visible"]:
                                    existing["finish_codes_visible"].append(c)
                            break
            elif is_painting_sheet:
                # On a Finish Plan but no codes — include with a note
                if key not in seen_keys:
                    seen_keys.add(key)
                    out["rooms"].append(r)
            else:
                # Drop it — it came from a Life Safety / Furniture / Partition sheet
                out["rooms_dropped"].append({
                    "name": r.get("name"), "number": r.get("number"),
                    "source_sheet": sheet_title,
                })
    return out


# Ashrah pricing rules
ESTIMATE_RATE_WITH_CEILINGS = float(os.getenv("ESTIMATE_RATE_CEILINGS", "4.0"))
ESTIMATE_RATE_NO_CEILINGS   = float(os.getenv("ESTIMATE_RATE_NO_CEILINGS", "3.5"))
ESTIMATE_DOOR_PRICE         = float(os.getenv("ESTIMATE_DOOR_PRICE", "50.0"))
ESTIMATE_EPOXY_PRICE        = float(os.getenv("ESTIMATE_EPOXY_PRICE", "4.0"))


def _apply_pricing(calc: dict) -> dict:
    """Apply Ashrah's pricing rules deterministically:
        floor_price = floor_sqft × $4 (ceilings) or × $3.50 (no ceilings)
        doors_price = door_count × $50 (frame included)
        epoxy_price = epoxy_area_sqft × $4
        total       = floor_price + doors_price + epoxy_price"""
    if not isinstance(calc, dict) or calc.get("error"):
        return calc
    totals = calc.get("totals") or {}

    def _num(field):
        try:
            v = float(totals.get(field) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v <= 0:
            try:
                v = sum(float((r or {}).get(field) or 0) for r in (calc.get("rooms") or []))
            except Exception:
                v = 0.0
        return v

    floor_sqft  = _num("floor_area_sqft")
    door_count  = int(_num("door_count"))
    epoxy_sqft  = _num("epoxy_area_sqft")

    ceilings    = bool(calc.get("ceilings_in_scope"))
    rate        = ESTIMATE_RATE_WITH_CEILINGS if ceilings else ESTIMATE_RATE_NO_CEILINGS
    floor_price = round(floor_sqft * rate, 2)
    doors_price = round(door_count * ESTIMATE_DOOR_PRICE, 2)
    epoxy_price = round(epoxy_sqft  * ESTIMATE_EPOXY_PRICE, 2)
    total_price = round(floor_price + doors_price + epoxy_price, 2)

    parts = [f"Floor: {round(floor_sqft,1):,} × ${rate:.2f} = ${floor_price:,.2f}"]
    if door_count: parts.append(f"Doors: {door_count} × ${ESTIMATE_DOOR_PRICE:.0f} = ${doors_price:,.2f}")
    if epoxy_sqft: parts.append(f"Epoxy: {round(epoxy_sqft,1):,} × ${ESTIMATE_EPOXY_PRICE:.2f} = ${epoxy_price:,.2f}")
    formula = "  +  ".join(parts) + f"  =  ${total_price:,.2f}"

    calc["pricing"] = {
        "floor_area_sqft":   round(floor_sqft, 1),
        "ceilings_included": ceilings,
        "rate_per_sqft":     rate,
        "floor_price":       floor_price,
        "door_count":        door_count,
        "door_rate":         ESTIMATE_DOOR_PRICE,
        "doors_price":       doors_price,
        "epoxy_area_sqft":   round(epoxy_sqft, 1),
        "epoxy_rate":        ESTIMATE_EPOXY_PRICE,
        "epoxy_price":       epoxy_price,
        "price":             total_price,
        "formula":           formula,
        "basis":             "Ashrah pricing: $4/sq ft (ceilings) or $3.50/sq ft (walls only) + $50/door + $4/sq ft epoxy.",
    }
    return calc


def _generate_paint_calc(raw_json: dict, client_name: str, site_address: str) -> dict:
    """Use Claude to interpret painting takeoff data and produce a scoped estimate."""
    takeoff = _flatten_pages(raw_json)
    doc_totals = raw_json.get("document_totals", {})

    prompt = f"""You are a senior painting estimator at Ashrah Painting in Winnipeg, Canada. Produce a painting estimate from the takeoff data below.

Client: {client_name or "TBD"}
Site: {site_address or "TBD"}
File: {doc_totals.get("file_name", "")}

PAINTING TAKEOFF FROM DRAWINGS:
{json.dumps(takeoff, indent=2)[:12000]}

Use your judgment. Compute every number an estimator would compute and put real values in the JSON. Don't dump your reasoning into the assumptions field with zeros everywhere — fill in rooms, materials, labor, and totals with numbers.

CRITICAL: Only include rooms that appear in the `rooms` array above. Every room in that array has an explicit `finish_codes_visible` list — assume painting is in scope for that room with those codes. Do NOT invent additional rooms, do NOT pull rooms from imagined "general notes" coverage, and do NOT add rooms just because they "might be" on the floor. If a room isn't in `rooms`, it's not in scope.

If wall heights aren't shown, assume 9'-0" commercial-office height and proceed. If only overall dimensions are given, compute perimeter from them, add ~30% for interior partitions, and apply ~10% opening deduction. Distribute wall area across the rooms listed by relative size. Exclude ceilings if no ceiling painting is called out. Exclude RB-x rubber base (flooring scope, not painting).

**FLOOR AREA IS REQUIRED.** Ashrah prices off FLOOR square footage. For every room, compute `floor_area_sqft` (the room's floor footprint — length × width). If only overall building dimensions are given, compute the total floor area from them and distribute across rooms by relative size. The `totals.floor_area_sqft` is the single most important number — get it as accurate as the drawings allow.

**DOORS:** Count every interior + exterior door (including frames) shown on the drawings. Set `totals.door_count` to that number. Ashrah charges $50 per door (frame included) as a separate line item on top of the floor-area price.

**EPOXY:** Scan the finish schedule for any epoxy paint codes (FT-53, IP, epoxy floor, urethane floor, stonekote, anti-corrosive, etc. — common in mechanical rooms, food prep curbs, warehouse, washroom walls, industrial floors). Sum the area called out for epoxy and set `totals.epoxy_area_sqft`. Ashrah charges $4.00 per sq ft of epoxy as a separate line on top of the floor + door price.

Set `ceilings_in_scope` to true ONLY if ceiling painting is actually called out in the finish schedule/notes; otherwise false.

**ASHRAH COATS STANDARD (new build):** 1 coat primer + 2 coats finish on ALL ceilings and walls = 3 total coats of material per surface. Doors are EXCLUDED (flat $50/door regardless of coats). Factor 3× coverage into paint quantities AND into labor hours (each coat is its own pass — multiply rolled/sprayed area by 3 when computing hours from the production rates below).

Coverage: walls 350 sqft/gal per coat; ceilings 400 sqft/gal per coat. Multiply by 3 coats for new build (primer + 2 finish).
For materials: primer_gallons = (wall_area + ceiling_area) ÷ ~350; wall_paint_gallons = wall_area × 2 ÷ 350; ceiling_paint_gallons = ceiling_area × 2 ÷ 400.

**ASHRAH PRODUCTION RATES** (per painter, per hour — use these to compute labor.estimated_days, painters_recommended, and hours_estimate):
- Spraying deck ceilings on a NEW BUILD (exposed deck/structure): 400 sqft/hr
- Rolling walls on a NEW BUILD (clean GWB, no patching): 200 sqft/hr
- Repaint with prep + patching (existing occupied space): ~150 sqft/hr

Choose the right rate based on whether this is a new build or a repaint, and whether ceilings are sprayed or walls are rolled. Compute hours = (area × number_of_coats) ÷ rate, then days = hours ÷ (painters × 8). For new build use 3 coats (primer + 2 finish); for straight repaint use 2 coats. Default to 1-3 painters for a typical commercial scope.

Return JSON only (no markdown fences) with this exact shape:
{{
  "rooms": [{{"name":"...","floor_area_sqft":0,"wall_area_sqft":0,"ceiling_area_sqft":0,"trim_linear_ft":0,"door_count":0,"epoxy_area_sqft":0,"notes":"..."}}],
  "totals": {{"floor_area_sqft":0,"wall_area_sqft":0,"ceiling_area_sqft":0,"trim_linear_ft":0,"door_count":0,"epoxy_area_sqft":0,"total_paintable_sqft":0}},
  "ceilings_in_scope": false,
  "materials": {{"wall_paint_gallons":0,"ceiling_paint_gallons":0,"primer_gallons":0,"notes":"..."}},
  "labor": {{"estimated_days":0,"painters_recommended":0,"hours_estimate":0,"notes":"..."}},
  "scope_summary": "One sentence: what's being painted, in plain English.",
  "confidence": "high | medium | low",
  "assumptions": ["Brief bulleted assumptions — what defaults you used."]
}}"""

    try:
        ai = _anthropic.Anthropic()
        resp = ai.messages.create(
            model=MODEL_CLAUDE,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        try:
            return _apply_pricing(json.loads(text))
        except json.JSONDecodeError:
            # Try to extract the first {...} block
            s = text.find("{"); e = text.rfind("}")
            if s >= 0 and e > s:
                try: return _apply_pricing(json.loads(text[s:e+1]))
                except Exception: pass
            print(f"[Estimates] paint_calc parse failed. Claude returned:\n{text[:1500]}")
            return {"error": "Claude returned unparseable JSON",
                    "scope_summary": "Could not parse estimate.",
                    "_raw": text[:2000]}
    except Exception as exc:
        return {"error": str(exc), "scope_summary": "Could not generate estimate."}


def _generate_work_order(raw_json: dict, paint_calc: dict,
                         client_name: str, site_address: str) -> str:
    """Use Claude to write a formal work order from the estimate."""
    prompt = f"""You are writing a formal work order for Ashrah Painting.

Client: {client_name or "Unknown"}
Site: {site_address or "Unknown"}

PAINTING ESTIMATE:
{json.dumps(paint_calc, indent=2)[:3000]}

Write a professional work order in plain text. Include:
1. Project Overview (one paragraph — what is being painted, where)
2. Scope of Work (specific rooms/areas, what gets painted in each)
3. Materials (paint quantities, primer, supplies)
4. Crew & Timeline (number of painters, estimated days)
5. Special Notes (any assumptions or conditions from the drawings)

HARD RULES — DO NOT VIOLATE:
- ONLY mention surfaces that have non-zero values in the estimate above.
  If ceiling_area_sqft = 0, the scope is walls only — DO NOT mention ceilings
  except in Special Notes as an exclusion.
- If trim_linear_ft = 0, do not mention trim painting.
- If primer_gallons = 0, do not mention priming work.
- Mirror the exact scope shown in the estimate. Do not invent or add scope items.
- Write in plain professional English — no bullet points, use paragraphs
- Do not use AI filler phrases
- Sign off as: Lumia | Ashrah Painting Operations
- Keep it under 400 words"""

    try:
        ai = _anthropic.Anthropic()
        resp = ai.messages.create(
            model=MODEL_CLAUDE,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as exc:
        return f"Could not generate work order: {exc}"
