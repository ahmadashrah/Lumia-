"""
procore_integration.py — Wires Lumia into Procore.

Two directions of traffic:

  Lumia  →  Procore   Every employee check-in becomes a Daily Log entry
                      (a Manpower log for the crew hours + a Notes log with
                      the written summary, scores and tomorrow's plan) on the
                      Procore project linked to that site.

  Procore →  Lumia    Procore projects can be browsed from the owner
                      dashboard and imported as Lumia jobs, so the crew picks
                      sites that already exist in Procore.

A "link" ties a site-address keyword (the same matching Lumia already uses for
client reports) to a Procore project id.
"""
from __future__ import annotations

import os
import secrets
import threading
import uuid
from datetime import date, datetime, timezone

from flask import Blueprint, jsonify, redirect, request, session, url_for

from procore_client import (
    ProcoreClient,
    ProcoreError,
    ProcoreNotConnected,
    MemoryTokenStore,
    SupabaseTokenStore,
)

procore_bp = Blueprint("procore", __name__)

# Populated by init_procore().
_supabase = None
_client: ProcoreClient | None = None

# In-memory fallbacks so the feature is usable before the Supabase tables exist.
_mem_links: list[dict] = []
_mem_sync_log: list[dict] = []
_mem_lock = threading.Lock()

LINKS_TABLE = "procore_links"
SYNC_LOG_TABLE = "procore_sync_log"


# ---------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------
def init_procore(app, supabase_client=None) -> ProcoreClient:
    """Attach the Procore blueprint to a Flask app. Safe to call when unconfigured."""
    global _supabase, _client
    _supabase = supabase_client
    store = SupabaseTokenStore(supabase_client) if supabase_client else MemoryTokenStore()
    _client = ProcoreClient.from_env(token_store=store)
    app.register_blueprint(procore_bp)
    if _client.is_configured:
        print(f"[Procore] Integration ready ({_client.environment}, "
              f"{_client.connection_status()['mode']})")
    else:
        print("[Procore] PROCORE_CLIENT_ID/SECRET not set — integration idle")
    return _client


def get_client() -> ProcoreClient:
    global _client
    if _client is None:
        _client = ProcoreClient.from_env()
    return _client


def auto_sync_enabled() -> bool:
    return os.getenv("PROCORE_AUTO_SYNC", "true").strip().lower() not in ("0", "false", "no")


# ---------------------------------------------------------------------------
# AUTH GUARD
# Kept local rather than imported from lumia_app to avoid a circular import.
# ---------------------------------------------------------------------------
def _require_owner(view):
    import functools

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("role") != "owner":
            if request.path.startswith("/api/"):
                return jsonify({"error": "Owner login required."}), 403
            return redirect(url_for("login_page", next=request.path))
        return view(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# LINK STORAGE  (site keyword ↔ Procore project)
# ---------------------------------------------------------------------------
def list_links() -> list[dict]:
    if _supabase:
        try:
            return _supabase.table(LINKS_TABLE).select("*").execute().data or []
        except Exception as exc:
            print(f"[Procore] Link read failed, using memory: {exc}")
    with _mem_lock:
        return list(_mem_links)


def add_link(site_keyword: str, project_id: str | int, project_name: str = "",
             company_id: str | int = "") -> dict:
    row = {
        "id":                   str(uuid.uuid4()),
        "site_keyword":         (site_keyword or "").strip().lower(),
        "procore_project_id":   int(project_id),
        "procore_project_name": project_name,
        "procore_company_id":   str(company_id or get_client().company_id or ""),
    }
    if _supabase:
        try:
            _supabase.table(LINKS_TABLE).upsert(row, on_conflict="site_keyword").execute()
            return row
        except Exception as exc:
            print(f"[Procore] Link save failed, using memory: {exc}")
    with _mem_lock:
        _mem_links[:] = [l for l in _mem_links if l["site_keyword"] != row["site_keyword"]]
        _mem_links.append(row)
    return row


def remove_link(link_id: str) -> None:
    if _supabase:
        try:
            _supabase.table(LINKS_TABLE).delete().eq("id", link_id).execute()
            return
        except Exception as exc:
            print(f"[Procore] Link delete failed, using memory: {exc}")
    with _mem_lock:
        _mem_links[:] = [l for l in _mem_links if l["id"] != link_id]


def find_link_for_site(site_address: str) -> dict | None:
    """Longest matching keyword wins, so '23 falcon ridge' beats '23 falcon'."""
    site_lower = (site_address or "").lower()
    if not site_lower:
        return None
    matches = [l for l in list_links()
               if l.get("site_keyword") and l["site_keyword"] in site_lower]
    if not matches:
        return None
    return max(matches, key=lambda l: len(l["site_keyword"]))


# ---------------------------------------------------------------------------
# SYNC LOG
# ---------------------------------------------------------------------------
def _record_sync(checkin_id: str, project_id, status: str, detail: str = "",
                 manpower_log_id=None, notes_log_id=None) -> dict:
    row = {
        "id":                  str(uuid.uuid4()),
        "checkin_id":          str(checkin_id or ""),
        "procore_project_id":  int(project_id) if project_id else None,
        "status":              status,
        "detail":              (detail or "")[:2000],
        "manpower_log_id":     manpower_log_id,
        "notes_log_id":        notes_log_id,
        "created_at":          datetime.now(timezone.utc).isoformat(),
    }
    if _supabase:
        try:
            _supabase.table(SYNC_LOG_TABLE).insert(row).execute()
            return row
        except Exception as exc:
            print(f"[Procore] Sync-log write failed, using memory: {exc}")
    with _mem_lock:
        _mem_sync_log.insert(0, row)
        del _mem_sync_log[200:]
    return row


def list_sync_log(limit: int = 50) -> list[dict]:
    if _supabase:
        try:
            return (_supabase.table(SYNC_LOG_TABLE).select("*")
                    .order("created_at", desc=True).limit(limit)
                    .execute().data or [])
        except Exception as exc:
            print(f"[Procore] Sync-log read failed, using memory: {exc}")
    with _mem_lock:
        return list(_mem_sync_log[:limit])


def _already_synced(checkin_id: str) -> bool:
    if not checkin_id:
        return False
    if _supabase:
        try:
            rows = (_supabase.table(SYNC_LOG_TABLE).select("id")
                    .eq("checkin_id", str(checkin_id)).eq("status", "synced")
                    .limit(1).execute().data or [])
            return bool(rows)
        except Exception as exc:
            print(f"[Procore] Sync-log lookup failed: {exc}")
            return False
    with _mem_lock:
        return any(r["checkin_id"] == str(checkin_id) and r["status"] == "synced"
                   for r in _mem_sync_log)


# ---------------------------------------------------------------------------
# CHECK-IN → PROCORE DAILY LOG
# ---------------------------------------------------------------------------
SCORE_FIELDS = [
    ("tape_covering",     "Tape & Covering"),
    ("drop_sheets",       "Drop Sheets"),
    ("patching_process",  "Patching Process"),
    ("paint_execution",   "Paint Execution"),
    ("site_control",      "Site Control"),
    ("washing_tool_care", "Washing & Tool Care"),
]


def checkin_to_dict(entry) -> dict:
    """Accept either a Supabase check-in row or an EmployeeDailyEntry."""
    if isinstance(entry, dict):
        return entry
    return {
        "id":               getattr(entry, "id", ""),
        "entry_date":       entry.entry_date,
        "worker_name":      entry.worker_name,
        "site_address":     entry.site_address,
        "work_description": entry.work_description,
        "tomorrows_plan":   entry.tomorrows_plan,
        "notes":            entry.notes,
        "custom_scores":    entry.custom_scores,
        "avg_score":        entry.self_score,
        **{key: getattr(entry, key, 0) for key, _ in SCORE_FIELDS},
    }


def format_daily_note(checkin: dict) -> str:
    """The narrative Procore's Daily Log shows for this check-in."""
    lines = [
        f"Lumia check-in — {checkin.get('worker_name') or 'Unknown'}",
        f"Site: {checkin.get('site_address') or '—'}",
        "",
        "WORK COMPLETED",
        (checkin.get("work_description") or "—").strip(),
    ]
    plan = (checkin.get("tomorrows_plan") or "").strip()
    if plan:
        lines += ["", "PLANNED FOR TOMORROW", plan]

    scores = [f"{label}: {checkin.get(key)}/10" for key, label in SCORE_FIELDS
              if checkin.get(key)]
    if checkin.get("custom_scores"):
        scores.append(str(checkin["custom_scores"]))
    if scores:
        lines += ["", "QUALITY SELF-SCORES", " | ".join(scores)]
    if checkin.get("avg_score"):
        lines.append(f"Average: {checkin['avg_score']}/10")

    note = (checkin.get("notes") or "").strip()
    if note:
        lines += ["", "NOTES", note]

    photos = (checkin.get("photo_urls") or "").strip()
    if photos:
        lines += ["", "PHOTOS"] + [u.strip() for u in photos.split(",") if u.strip()]

    return "\n".join(lines)


def sync_checkin(entry, *, force: bool = False) -> dict:
    """
    Push one check-in to the Procore project linked to its site.

    Returns a result dict; never raises, so it is safe to call from a
    background thread or a request handler.
    """
    checkin = checkin_to_dict(entry)
    checkin_id = str(checkin.get("id") or "")
    site = checkin.get("site_address") or ""
    client = get_client()

    if not client.is_configured:
        return {"ok": False, "status": "skipped", "reason": "Procore is not configured."}

    if not force and _already_synced(checkin_id):
        return {"ok": True, "status": "duplicate",
                "reason": "This check-in was already pushed to Procore."}

    link = find_link_for_site(site)
    if not link:
        reason = f"No Procore project linked to a keyword in “{site}”."
        _record_sync(checkin_id, None, "unlinked", reason)
        return {"ok": False, "status": "unlinked", "reason": reason}

    project_id = link["procore_project_id"]
    log_date = checkin.get("entry_date") or date.today().isoformat()
    hours = float(os.getenv("PROCORE_DEFAULT_HOURS", "8"))

    manpower_id = notes_id = None
    errors: list[str] = []

    try:
        manpower = client.create_manpower_log(
            project_id,
            log_date=log_date,
            num_workers=1,
            num_hours=hours,
            notes=f"{checkin.get('worker_name') or 'Crew'} — "
                  f"{(checkin.get('work_description') or '').strip()[:240]}",
        )
        manpower_id = manpower.get("id")
    except ProcoreNotConnected as exc:
        _record_sync(checkin_id, project_id, "error", str(exc))
        return {"ok": False, "status": "not_connected", "reason": str(exc)}
    except ProcoreError as exc:
        errors.append(f"manpower log: {exc} {exc.payload or ''}".strip())

    try:
        notes = client.create_notes_log(project_id, log_date=log_date,
                                        notes=format_daily_note(checkin))
        notes_id = notes.get("id")
    except ProcoreError as exc:
        errors.append(f"notes log: {exc} {exc.payload or ''}".strip())

    if manpower_id is None and notes_id is None:
        detail = " | ".join(errors) or "Procore rejected both daily log entries."
        _record_sync(checkin_id, project_id, "error", detail)
        return {"ok": False, "status": "error", "reason": detail}

    status = "synced" if not errors else "partial"
    detail = " | ".join(errors)
    _record_sync(checkin_id, project_id, status, detail, manpower_id, notes_id)
    print(f"[Procore] Check-in {checkin_id or '(unsaved)'} → project {project_id} ({status})")
    return {
        "ok": True,
        "status": status,
        "project_id": project_id,
        "project_name": link.get("procore_project_name"),
        "manpower_log_id": manpower_id,
        "notes_log_id": notes_id,
        "reason": detail,
    }


def sync_checkin_async(entry) -> None:
    """Fire-and-forget push used by the check-in submit handler."""
    if not auto_sync_enabled() or not get_client().is_configured:
        return

    def _run():
        try:
            sync_checkin(entry)
        except Exception as exc:  # belt and braces — a thread must not die loudly
            print(f"[Procore] Background sync error: {exc}")

    threading.Thread(target=_run, daemon=True).start()


def sync_day(log_date: str = "") -> dict:
    """Push every check-in for a given date (default today). Used by the scheduler."""
    day = log_date or date.today().isoformat()
    client = get_client()
    if not client.is_configured:
        return {"ok": False, "reason": "Procore is not configured.", "results": []}
    if not _supabase:
        return {"ok": False, "reason": "No database configured.", "results": []}
    try:
        checkins = (_supabase.table("checkins").select("*")
                    .eq("entry_date", day).execute().data or [])
    except Exception as exc:
        return {"ok": False, "reason": f"Could not read check-ins: {exc}", "results": []}

    results = [dict(sync_checkin(c), checkin_id=c.get("id"),
                    worker_name=c.get("worker_name"),
                    site_address=c.get("site_address"))
               for c in checkins]
    synced = sum(1 for r in results if r.get("status") in ("synced", "partial"))
    return {"ok": True, "date": day, "total": len(results), "synced": synced,
            "results": results}


# ---------------------------------------------------------------------------
# ROUTES — OAUTH
# ---------------------------------------------------------------------------
@procore_bp.route("/procore/connect")
@_require_owner
def procore_connect():
    client = get_client()
    try:
        state = secrets.token_urlsafe(24)
        session["procore_oauth_state"] = state
        return redirect(client.authorization_url(state=state,
                                                 redirect_uri=_redirect_uri()))
    except ProcoreError as exc:
        return _html_message("Procore connection failed", str(exc)), 400


@procore_bp.route("/procore/callback")
def procore_callback():
    error = request.args.get("error")
    if error:
        return _html_message("Procore denied the connection",
                             request.args.get("error_description") or error), 400

    # The state is always set by /procore/connect, so a missing one means the
    # callback did not originate from a connection this browser started.
    expected = session.pop("procore_oauth_state", None)
    if not expected or request.args.get("state") != expected:
        return _html_message("Procore connection failed",
                             "This connection request could not be verified. "
                             "Start again from the owner dashboard."), 400

    code = request.args.get("code", "")
    if not code:
        return _html_message("Procore connection failed",
                             "Procore did not return an authorization code."), 400
    try:
        get_client().exchange_code(code, redirect_uri=_redirect_uri())
    except ProcoreError as exc:
        return _html_message("Procore connection failed",
                             f"{exc} {exc.payload or ''}"), 400
    return redirect("/owner?procore=connected")


def _redirect_uri() -> str:
    """Configured redirect URI, or one derived from the current request."""
    return os.getenv("PROCORE_REDIRECT_URI") or url_for("procore.procore_callback",
                                                        _external=True)


def _html_message(title: str, detail: str) -> str:
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title></head>"
        "<body style=\"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "background:#eef1f7;padding:40px\">"
        "<div style='max-width:560px;margin:0 auto;background:#fff;border-radius:12px;"
        "padding:28px;box-shadow:0 2px 12px rgba(0,0,0,.08)'>"
        f"<h1 style='color:#1F3864;font-size:20px;margin-bottom:12px'>{title}</h1>"
        f"<p style='color:#555;font-size:14px;line-height:1.6'>{detail}</p>"
        "<p style='margin-top:20px'><a href='/owner' style='color:#1F3864;font-weight:700'>"
        "&larr; Back to dashboard</a></p></div></body></html>"
    )


# ---------------------------------------------------------------------------
# ROUTES — API
# ---------------------------------------------------------------------------
def _error_response(exc: ProcoreError):
    status = 401 if isinstance(exc, ProcoreNotConnected) else 502
    return jsonify(exc.as_dict()), status


@procore_bp.route("/api/procore/status")
@_require_owner
def api_procore_status():
    client = get_client()
    status = client.connection_status()
    status["auto_sync"] = auto_sync_enabled()
    status["redirect_uri"] = _redirect_uri() if client.is_configured else ""
    status["linked_sites"] = len(list_links())
    if status["connected"] and not status["company_id"]:
        try:
            companies = client.list_companies()
            status["companies"] = [{"id": c.get("id"), "name": c.get("name")}
                                   for c in companies]
        except ProcoreError as exc:
            status["warning"] = str(exc)
    return jsonify(status)


@procore_bp.route("/api/procore/disconnect", methods=["POST"])
@_require_owner
def api_procore_disconnect():
    get_client().disconnect()
    return jsonify({"ok": True, "message": "Procore disconnected."})


@procore_bp.route("/api/procore/companies")
@_require_owner
def api_procore_companies():
    try:
        companies = get_client().list_companies()
    except ProcoreError as exc:
        return _error_response(exc)
    return jsonify([{"id": c.get("id"), "name": c.get("name"),
                     "is_active": c.get("is_active")} for c in companies])


@procore_bp.route("/api/procore/projects")
@_require_owner
def api_procore_projects():
    company_id = request.args.get("company_id") or None
    try:
        projects = get_client().list_projects(company_id=company_id)
    except ProcoreError as exc:
        return _error_response(exc)
    return jsonify([{
        "id":      p.get("id"),
        "name":    p.get("name") or p.get("display_name"),
        "number":  p.get("project_number"),
        "address": p.get("address"),
        "city":    p.get("city"),
        "stage":   (p.get("project_stage") or {}).get("name") if isinstance(p.get("project_stage"), dict) else p.get("stage"),
        "active":  p.get("active"),
    } for p in projects])


@procore_bp.route("/api/procore/links")
@_require_owner
def api_procore_links():
    return jsonify(list_links())


@procore_bp.route("/api/procore/link", methods=["POST"])
@_require_owner
def api_procore_link():
    d = request.get_json(silent=True) or {}
    keyword = (d.get("site_keyword") or "").strip()
    project_id = d.get("procore_project_id")
    if not keyword or not project_id:
        return jsonify({"ok": False,
                        "message": "Site keyword and Procore project are both required."}), 400
    try:
        link = add_link(keyword, project_id, d.get("procore_project_name") or "",
                        d.get("procore_company_id") or "")
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Invalid Procore project id."}), 400
    return jsonify({"ok": True, "link": link,
                    "message": f"“{keyword}” now syncs to {link['procore_project_name'] or link['procore_project_id']}."})


@procore_bp.route("/api/procore/unlink/<link_id>", methods=["POST"])
@_require_owner
def api_procore_unlink(link_id):
    remove_link(link_id)
    return jsonify({"ok": True})


@procore_bp.route("/api/procore/push-checkin", methods=["POST"])
@_require_owner
def api_procore_push_checkin():
    d = request.get_json(silent=True) or {}
    checkin_id = d.get("checkin_id")
    if not checkin_id:
        return jsonify({"ok": False, "message": "checkin_id is required."}), 400
    if not _supabase:
        return jsonify({"ok": False, "message": "No database configured."}), 400
    try:
        rows = (_supabase.table("checkins").select("*")
                .eq("id", checkin_id).limit(1).execute().data or [])
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Could not read check-in: {exc}"}), 500
    if not rows:
        return jsonify({"ok": False, "message": "Check-in not found."}), 404
    result = sync_checkin(rows[0], force=bool(d.get("force")))
    result["message"] = _sync_message(result)
    return jsonify(result)


@procore_bp.route("/api/procore/sync-day", methods=["POST"])
@_require_owner
def api_procore_sync_day():
    d = request.get_json(silent=True) or {}
    result = sync_day(d.get("date") or "")
    if result.get("ok"):
        result["message"] = (f"{result['synced']} of {result['total']} check-ins "
                             f"pushed to Procore for {result['date']}.")
    else:
        result["message"] = result.get("reason", "Sync failed.")
    return jsonify(result)


@procore_bp.route("/api/procore/sync-log")
@_require_owner
def api_procore_sync_log():
    return jsonify(list_sync_log(int(request.args.get("limit", 50))))


@procore_bp.route("/api/procore/import-projects", methods=["POST"])
@_require_owner
def api_procore_import_projects():
    """Create a Lumia job for each active Procore project we don't have yet."""
    if not _supabase:
        return jsonify({"ok": False, "message": "No database configured."}), 400
    try:
        projects = get_client().list_projects()
    except ProcoreError as exc:
        return _error_response(exc)
    try:
        existing = (_supabase.table("jobs").select("site_address")
                    .execute().data or [])
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Could not read jobs: {exc}"}), 500

    known = {(j.get("site_address") or "").strip().lower() for j in existing}
    imported = 0
    for p in projects:
        if p.get("active") is False:
            continue
        site = (p.get("address") or p.get("name") or "").strip()
        if not site or site.lower() in known:
            continue
        try:
            _supabase.table("jobs").insert({
                "client_name":      p.get("name") or "Procore project",
                "site_address":     site,
                "work_description": f"Imported from Procore project #{p.get('id')}.",
                "painters_needed":  2,
                "status":           "open",
            }).execute()
            known.add(site.lower())
            imported += 1
        except Exception as exc:
            print(f"[Procore] Job import failed for project {p.get('id')}: {exc}")
    return jsonify({"ok": True, "imported": imported,
                    "message": f"Imported {imported} Procore project(s) as Lumia jobs."})


def _sync_message(result: dict) -> str:
    status = result.get("status")
    if status == "synced":
        return f"Pushed to Procore project {result.get('project_name') or result.get('project_id')}."
    if status == "partial":
        return f"Partly pushed — {result.get('reason')}"
    if status == "duplicate":
        return "Already pushed to Procore."
    return result.get("reason") or "Sync failed."
