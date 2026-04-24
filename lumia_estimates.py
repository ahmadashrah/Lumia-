"""
lumia_estimates.py — Estimates tab backend for Lumia.

Receives a PDF drawing, runs it through the Gemini extraction pipeline,
then uses Claude to produce a painting-specific estimate + work order.
Jobs run in background threads; status is stored in-memory + Supabase.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import threading
import time
import uuid
from datetime import datetime
from typing import Optional

import anthropic as _anthropic

# ── In-memory job store (survives as long as the process is up) ───────────────
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL_CLAUDE   = os.getenv("MODEL", "claude-opus-4-5")


# ── Job helpers ───────────────────────────────────────────────────────────────

def create_job(file_name: str, client_name: str = "", site_address: str = "") -> str:
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
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
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    with _jobs_lock:
        return dict(_jobs.get(job_id, {}))


def _update_job(job_id: str, **kwargs):
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


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
            from prompts import SYSTEM_PROMPT, CRITIC_INSTRUCTIONS, RECROP_INSTRUCTIONS
            from extract_gemini import process_page, extract_json_and_summary

            client_gemini = genai.Client(api_key=GEMINI_API_KEY)
            total_pages = pdf_utils.page_count(tmp_path)

            pages_output = []
            for idx in range(total_pages):
                _update_job(job_id, progress=f"Extracting page {idx + 1} of {total_pages}…")
                result = process_page(
                    client_gemini,
                    tmp_path,
                    idx,
                    file_name,
                    dpi=200,
                    hi_dpi=220,
                    effort="high",
                    do_critic=True,
                    do_recrop=True,
                )
                pages_output.append(result)

            raw_json = {
                "document_totals": {
                    "file_name":          file_name,
                    "pages_processed":    len(pages_output),
                    "total_measurements": sum(
                        len((p.get("extraction") or {}).get("measurements") or [])
                        for p in pages_output
                    ),
                },
                "pages": pages_output,
            }

        finally:
            os.unlink(tmp_path)

        _update_job(job_id, progress="Generating painting estimate…", raw_json=raw_json)

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


def start_extraction(job_id: str, pdf_bytes: bytes, file_name: str,
                     client_name: str = "", site_address: str = ""):
    t = threading.Thread(
        target=_run_extraction,
        args=(job_id, pdf_bytes, file_name, client_name, site_address),
        daemon=True,
    )
    t.start()


# ── Claude helpers ────────────────────────────────────────────────────────────

def _all_measurements(raw_json: dict) -> list:
    """Flatten measurements from all pages."""
    out = []
    for page in raw_json.get("pages") or []:
        ext = page.get("extraction") or {}
        out.extend(ext.get("measurements") or [])
    return out


def _generate_paint_calc(raw_json: dict, client_name: str, site_address: str) -> dict:
    """Use Claude to interpret measurements and produce a painting estimate."""
    measurements = _all_measurements(raw_json)
    doc_totals = raw_json.get("document_totals", {})

    prompt = f"""You are a professional painting estimator for Ashrah Painting in Winnipeg, Canada.

You have received extracted measurements from architectural drawings for a project.

Client: {client_name or "Unknown"}
Site: {site_address or "Unknown"}
File: {doc_totals.get("file_name", "")}
Total measurements extracted: {doc_totals.get("total_measurements", 0)}

EXTRACTED MEASUREMENTS:
{json.dumps(measurements, indent=2)[:8000]}

Based on these measurements, produce a painting estimate as a JSON object with this exact structure:
{{
  "rooms": [
    {{
      "name": "room name",
      "wall_area_sqft": 0,
      "ceiling_area_sqft": 0,
      "trim_linear_ft": 0,
      "notes": ""
    }}
  ],
  "totals": {{
    "wall_area_sqft": 0,
    "ceiling_area_sqft": 0,
    "trim_linear_ft": 0,
    "total_paintable_sqft": 0
  }},
  "materials": {{
    "wall_paint_gallons": 0,
    "ceiling_paint_gallons": 0,
    "primer_gallons": 0,
    "notes": ""
  }},
  "labor": {{
    "estimated_days": 0,
    "painters_recommended": 0,
    "hours_estimate": 0,
    "notes": ""
  }},
  "scope_summary": "plain English summary of what needs to be painted",
  "confidence": "high|medium|low",
  "assumptions": ["list any assumptions made"]
}}

Use these rules:
- Wall paint coverage: 350 sqft/gallon per coat, 2 coats standard
- Ceiling paint coverage: 400 sqft/gallon per coat, 2 coats
- 1 painter does ~300 sqft of walls per day (cutting + rolling)
- If you cannot determine a value from the drawings, use 0 and note it in assumptions
- Return ONLY the JSON object, no markdown fences"""

    try:
        ai = _anthropic.Anthropic()
        resp = ai.messages.create(
            model=MODEL_CLAUDE,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # Strip fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        return json.loads(text)
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

Rules:
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
