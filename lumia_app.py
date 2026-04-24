"""
lumia_app.py — Lumia Employee Check-In Web App
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import secrets
import smtplib
import threading
import uuid
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import functools
import anthropic as _anthropic
from apscheduler.schedulers.background import BackgroundScheduler
from flask import (Flask, render_template_string, request, jsonify,
                   session, redirect, url_for, make_response, send_from_directory)
from supabase import create_client
from werkzeug.security import generate_password_hash, check_password_hash

import lumia_estimates

from ashrah_backfill import (
    DailyReport,
    DailyReportSender,
    EmployeeDailyEntry,
    EmployeeLogSheet,
    Worker,
    WorkforceTracker,
    EXCEL_LOG_PATH,
    MODEL,
    ZOHO_EMAIL,
    ZOHO_PASSWORD,
    ZOHO_SMTP_HOST,
    ZOHO_SMTP_PORT,
    OWNER_EMAIL,
)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "lumia-ashrah-secret-2026")

# Explicit static route using absolute path — some deploy environments
# don't pick up Flask's default static handling reliably.
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@app.route("/static/<path:filename>")
def _serve_static(filename):
    return send_from_directory(_STATIC_DIR, filename)

OWNER_PIN = os.getenv("OWNER_PIN", "")

# Machine-to-machine API key (for the estimating agent and any future integrations).
# Set LUMIA_API_KEY in Railway env vars.  Requests pass it as:
#   Header:  X-Lumia-Key: <key>
#   OR query: ?api_key=<key>
LUMIA_API_KEY = os.getenv("LUMIA_API_KEY", "")

# Supabase client
_sb_url = os.getenv("SUPABASE_URL", "")
_sb_key = os.getenv("SUPABASE_KEY", "")
supabase_client = create_client(_sb_url, _sb_key) if _sb_url and _sb_key else None


def require_role(*roles):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if session.get("role") not in roles:
                return redirect(url_for("login_page", next=request.path))
            return f(*args, **kwargs)
        return wrapper
    return decorator

def require_employee(f):
    """Redirect to employee login if no employee session."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("employee_name"):
            return redirect(url_for("employee_login_page", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def require_api_key(f):
    """M2M auth decorator.  Accepts key via X-Lumia-Key header OR ?api_key= query param.
    Also passes if the caller has an active owner/manager session (browser use)."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") in ("owner", "manager"):
            return f(*args, **kwargs)
        provided = (
            request.headers.get("X-Lumia-Key")
            or request.args.get("api_key")
            or (request.get_json(silent=True) or {}).get("api_key")
        )
        if not LUMIA_API_KEY:
            # Key not configured — reject to prevent accidental open access
            return jsonify({"ok": False, "error": "LUMIA_API_KEY not configured on server."}), 403
        if not provided or provided != LUMIA_API_KEY:
            return jsonify({"ok": False, "error": "Invalid or missing API key."}), 401
        return f(*args, **kwargs)
    return wrapper


EMPLOYEES = ["Abdelhadi", "Ammar", "Weas", "Ismael", "Ermias", "Maria"]

CATEGORIES = [
    ("tape_covering",     "Tape & Covering"),
    ("drop_sheets",       "Use of Drop Sheets"),
    ("patching_process",  "Patching Process"),
    ("paint_execution",   "Paint Execution"),
    ("site_control",      "Site Control"),
    ("washing_tool_care", "Washing & Tool Care"),
]

# ---------------------------------------------------------------------------
# CLIENT REGISTRY
# Map a lowercase keyword from the site address to the client's name + email.
# Ahmad: add one entry per active job below.
# ---------------------------------------------------------------------------
CLIENTS: dict[str, dict] = {
    "23 falcon": {
        "client_name":  "Khadija Jarkess",
        "client_email": "kayjarkess@gmail.com",
    },
    # "keyword from site address": {"client_name": "...", "client_email": "..."},
}


def _lookup_client(site_address: str) -> dict | None:
    site_lower = site_address.lower()
    for keyword, info in CLIENTS.items():
        if keyword in site_lower:
            return info
    return None


# ---------------------------------------------------------------------------
# CLIENT-FACING LUMIA CHAT  — tokenized access for clients via their report email
# ---------------------------------------------------------------------------
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://lumia.ashrah.ai").rstrip("/")
CLIENT_CHAT_MODEL = "claude-sonnet-4-6"
CLIENT_RATE_LIMIT_PER_DAY = 30

# Feature is in limited beta — only these client emails see the button / can chat.
# Expand by setting CLIENT_CHAT_ALLOWED_EMAILS env var (comma-separated) without a redeploy.
_DEFAULT_CLIENT_CHAT_ALLOWLIST = {"kayjarkess@gmail.com"}
CLIENT_CHAT_ALLOWLIST = {
    e.strip().lower() for e in
    (os.getenv("CLIENT_CHAT_ALLOWED_EMAILS", "") or "").split(",")
    if e.strip()
} or _DEFAULT_CLIENT_CHAT_ALLOWLIST


def _client_chat_enabled_for(email: str | None) -> bool:
    return bool(email) and email.strip().lower() in CLIENT_CHAT_ALLOWLIST

CLIENT_LUMIA_SYSTEM_PROMPT = """You are Lumia, the client communication assistant for Ashrah Painting — a Winnipeg-based painting contractor that runs like a tech company and paints like tradespeople.

You are speaking directly with a client about THEIR project only. You have access to their check-ins, daily reports, and project details below. You do not have access to other clients' projects, internal crew notes, self-scores, or business operations data.

## YOUR ROLE

You are a calm, professional, on-top-of-it point of contact. Clients should finish every conversation with you feeling that their project is in competent, organized hands — because it is.

## TONE

- Professional, confident, unhurried. Never defensive, never over-apologetic, never salesy.
- Plain language. No construction jargon unless the client uses it first.
- Short answers by default. Expand only when the client asks for detail.
- Think "senior project manager giving a status update," not "customer service rep reading a script."

## HOW TO ANSWER

**Default structure: what's done -> what's next -> timing.**
Lead with progress and forward motion. This is the frame for almost every answer.

**On status questions** ("how's it going?", "where are we at?"):
Give a clear, specific answer grounded in the actual reports. Name the work completed, the work in progress, and the next milestone with a date if one exists in the reports.

**On delays, issues, or anything that went wrong:**
Own it briefly and accurately, then pivot to resolution. One sentence of ownership, then the plan.
- Good: "Prep took an extra day because the wall condition needed more patching than the original scope anticipated. We absorbed that time and we're back on schedule for topcoat Thursday."
- Not good: "We've identified some items that are being addressed." (vague, evasive — clients see through this)
- Not good: "Yeah the crew messed up and we're behind." (unnecessarily self-flagellating — not your job to editorialize)

**On questions you don't have the answer to:**
Do not guess. Do not invent dates, prices, product names, or crew details that aren't in the reports. Say: "Ahmad will be in touch in about 5 minutes — please keep your phone close." The system will alert him instantly.

**On scope/pricing/contract questions:**
These go to Ahmad. Say: "Pricing and scope decisions come from Ahmad directly — he'll be in touch in about 5 minutes, please keep your phone close."

**On off-topic questions** (anything unrelated to their painting project):
Politely redirect. "I'm here to help with your Ashrah Painting project — for anything else, you'll want a different resource. Anything I can help with on the job?"

## FRAMING RULES

- Accurate about status, generous about framing. You can choose which true things to emphasize, but you cannot misrepresent what happened.
- Never surface internal data: self-scores, crew performance notes, internal concerns, scheduling stress, margin, other clients' projects. If it's not appropriate for a client to see, it doesn't exist as far as you're concerned.
- Never reframe genuine fault as external. If the reports indicate Ashrah caused an issue, acknowledge it cleanly and move to the fix. Don't blame weather, suppliers, or the client unless the reports specifically document that cause.
- Do not fabricate. Every factual claim — dates, work completed, products used, crew members, next steps — must come from the project data provided. If it's not in the data, you don't know it.

## WHAT YOU NEVER DO

- Never invent facts not present in the project data.
- Never discuss other clients, other projects, or Ashrah's internal operations.
- Never make commitments on Ashrah's behalf (new timelines, discounts, scope additions, warranties). Route to Ahmad.
- Never disparage the crew, subcontractors, suppliers, or the client.
- Never upsell, cross-sell, or pitch additional services unprompted.
- Never claim to be human. If asked, you are Lumia, Ashrah Painting's AI assistant.

## CLOSING

End answers cleanly. No forced sign-offs, no "is there anything else?" on every message. Match the client's energy — if they're brief, be brief.

---

Project data for this client follows below. Use only this data. Anything outside it, route to Ahmad.
"""

ESCALATION_PHRASES = (
    "ahmad will follow up",
    "have ahmad follow up",
    "let me have ahmad",
    "i'll flag it",
    "i'll let him know you asked",
    "pricing and scope changes go through ahmad",
    "ahmad will be in touch",
    "he'll be in touch",
)


_LAST_ENSURE_CLIENT_ERROR: str = ""


def _ensure_client_row(site_keyword_hint: str, client_name: str, client_email: str) -> dict | None:
    """Idempotent upsert of the client row by email. Ensures access_token exists. Returns the row."""
    global _LAST_ENSURE_CLIENT_ERROR
    _LAST_ENSURE_CLIENT_ERROR = ""
    if not supabase_client:
        _LAST_ENSURE_CLIENT_ERROR = "Supabase client not configured"
        return None
    if not client_email:
        _LAST_ENSURE_CLIENT_ERROR = "Missing client_email"
        return None
    try:
        existing = supabase_client.table("clients").select("*") \
            .eq("client_email", client_email).limit(1).execute().data or []
        if existing:
            row = existing[0]
            if not row.get("access_token"):
                token = secrets.token_urlsafe(24)
                supabase_client.table("clients").update({"access_token": token}) \
                    .eq("id", row["id"]).execute()
                row["access_token"] = token
            return row
        token = secrets.token_urlsafe(24)
        inserted = supabase_client.table("clients").insert({
            "client_name":  client_name,
            "client_email": client_email,
            "site_keyword": (site_keyword_hint or "").lower().strip(),
            "access_token": token,
        }).execute().data or []
        if not inserted:
            _LAST_ENSURE_CLIENT_ERROR = "Insert returned no rows"
            return None
        return inserted[0]
    except Exception as exc:
        _LAST_ENSURE_CLIENT_ERROR = str(exc)
        print(f"[ClientChat] _ensure_client_row error: {exc}")
        return None


def _client_ask_url(client_row: dict | None) -> str | None:
    if not client_row or not client_row.get("access_token"):
        return None
    return f"{APP_BASE_URL}/client/{client_row['access_token']}/ask"


def _inject_ask_lumia_button(html_body: str, plain_body: str, client_row: dict | None) -> tuple[str, str]:
    """Append an 'Ask Lumia about your project' button to the email bodies."""
    url = _client_ask_url(client_row)
    if not url:
        return html_body, plain_body
    button_html = (
        '<div style="margin:28px 0;text-align:center;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;">'
        f'<a href="{url}" '
        'style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;'
        'font-weight:600;padding:14px 28px;border-radius:8px;font-size:15px;">'
        'Ask Lumia about your project</a>'
        '<div style="margin-top:10px;color:#666;font-size:12px;">'
        'Questions about your project? Chat with Lumia — our AI assistant — anytime.'
        '</div></div>'
    )
    low = (html_body or "").lower()
    if "</body>" in low:
        idx = low.rfind("</body>")
        new_html = html_body[:idx] + button_html + html_body[idx:]
    else:
        new_html = (html_body or "") + button_html
    plain_addendum = f"\n\nAsk Lumia about your project: {url}\n"
    return new_html, (plain_body or "") + plain_addendum


def _augment_report_with_ask_lumia(content: dict, site_keyword: str,
                                    client_name: str, client_email: str) -> None:
    """Mutates content dict in place, appending the Ask Lumia button + URL.
    No-op for clients not on the beta allowlist."""
    if not _client_chat_enabled_for(client_email):
        return
    row = _ensure_client_row(site_keyword, client_name, client_email)
    if not row:
        return
    html, plain = _inject_ask_lumia_button(
        content.get("html_body", ""), content.get("plain_body", ""), row,
    )
    content["html_body"] = html
    content["plain_body"] = plain


def _translate_fields(fields: dict[str, str], source_lang: str) -> dict[str, str]:
    """Use Claude to translate a dict of text fields from source_lang to English."""
    if source_lang == "en" or not any(fields.values()):
        return fields
    try:
        client = _anthropic.Anthropic()
        payload = json.dumps(fields, ensure_ascii=False)
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": (
                    f"Translate each value in this JSON from {source_lang} to English. "
                    "Keep the keys exactly the same. Return only valid JSON, nothing else.\n\n"
                    f"{payload}"
                ),
            }],
        )
        raw = response.content[0].text.strip().strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
        return json.loads(raw)
    except Exception as exc:
        print(f"[App] Translation error: {exc}")
        return fields  # fall back to original if translation fails


def _send_client_report(entry: EmployeeDailyEntry) -> None:
    """Generate and email a professional site report to the client for this site/date."""
    if not ZOHO_PASSWORD:
        print("[App] Skipping client report — ZOHO_PASSWORD not set")
        return
    client_info = _lookup_client(entry.site_address)
    if not client_info:
        return

    log     = EmployeeLogSheet(EXCEL_LOG_PATH)
    entries = log.get_today_entries_for_site(entry.site_address, entry.entry_date)
    if not entries:
        entries = [entry]

    work_completed = "\n\n".join(
        f"{e.worker_name}: {e.work_description}"
        for e in entries if e.work_description
    )
    crew_names = [e.worker_name for e in entries]

    dr = DailyReport(
        report_date=entry.entry_date,
        job_id=entry.job_id or "",
        site_address=entry.site_address,
        client_name=client_info["client_name"],
        client_email=client_info["client_email"],
        crew_present=crew_names,
        work_completed=work_completed,
        work_planned=entry.tomorrows_plan or "",
        issues="",
        overall_status="On Schedule",
    )

    tracker = WorkforceTracker()
    for name in crew_names:
        tracker.add_worker(Worker(worker_id=name, name=name))

    reporter = DailyReportSender(
        client=_anthropic.Anthropic(),
        smtp_host=ZOHO_SMTP_HOST,
        smtp_port=ZOHO_SMTP_PORT,
        user=ZOHO_EMAIL,
        password=ZOHO_PASSWORD,
        from_email=ZOHO_EMAIL,
    )
    try:
        content = reporter.generate(dr, tracker)
        keyword_hint = next(
            (k for k, v in CLIENTS.items() if v.get("client_email") == client_info["client_email"]),
            entry.site_address.lower()[:40],
        )
        _augment_report_with_ask_lumia(content, keyword_hint,
                                       client_info["client_name"], client_info["client_email"])
        sent    = reporter.send(content, to_email=dr.client_email, cc_emails=[OWNER_EMAIL])
        print(f"[App] Client report {'sent' if sent else 'FAILED'} → {dr.client_email}")
    except Exception as exc:
        print(f"[App] Client report error: {exc}")


# ---------------------------------------------------------------------------
# HTML TEMPLATE
# ---------------------------------------------------------------------------
HTML = """<!DOCTYPE html>
<html lang="en" id="htmlRoot">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Lumia — Daily Check-In</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #eef1f7;
      min-height: 100vh;
      padding: 20px 16px 40px;
    }
    .card {
      max-width: 520px;
      margin: 0 auto;
      background: #fff;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 4px 24px rgba(0,0,0,0.10);
    }
    .header {
      background: #fff;
      text-align: center;
      padding: 24px 20px 16px;
      border-bottom: 3px solid #1F3864;
    }
    .header img { width: 150px; display: block; margin: 0 auto 10px; }
    .header p  { font-size: 13px; color: #1F3864; font-weight: 600; margin-top: 2px; }

    /* Language selector */
    .lang-bar {
      background: #f4f6fb;
      border-bottom: 1px solid #e0e4ed;
      padding: 10px 20px;
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .lang-bar span { font-size: 12px; color: #666; }
    .lang-btn {
      border: 1.5px solid #1F3864;
      background: #fff;
      color: #1F3864;
      border-radius: 20px;
      padding: 4px 14px;
      font-size: 13px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .lang-btn.active { background: #1F3864; color: #fff; }

    .form-body { padding: 24px 20px 8px; }
    .field { margin-bottom: 18px; }
    .field label {
      display: block;
      font-size: 11px;
      font-weight: 700;
      color: #1F3864;
      letter-spacing: 0.8px;
      text-transform: uppercase;
      margin-bottom: 6px;
    }
    .field input[type="text"],
    .field select,
    .field textarea {
      width: 100%;
      padding: 12px 14px;
      border: 1.5px solid #dce2ef;
      border-radius: 10px;
      font-size: 15px;
      color: #222;
      background: #fafbfd;
      outline: none;
      transition: border 0.2s;
    }
    .field input[type="text"]:focus,
    .field select:focus,
    .field textarea:focus { border-color: #1F3864; }
    .field textarea { min-height: 90px; resize: vertical; }

    .section-title {
      font-size: 13px;
      font-weight: 700;
      color: #fff;
      background: #1F3864;
      padding: 10px 14px;
      border-radius: 8px;
      margin: 22px 0 14px;
      letter-spacing: 0.4px;
    }

    /* Score rows */
    .score-row { margin-bottom: 20px; }
    .score-row-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 6px;
    }
    .score-label { font-size: 14px; font-weight: 600; color: #333; }
    .score-badge {
      min-width: 44px; height: 44px;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 20px; font-weight: bold; color: #fff;
      transition: background 0.3s;
      flex-shrink: 0;
      box-shadow: 0 2px 6px rgba(0,0,0,0.18);
    }
    input[type="range"] {
      width: 100%; height: 6px;
      accent-color: #1F3864; cursor: pointer;
    }
    .slider-minmax {
      display: flex; justify-content: space-between;
      font-size: 11px; color: #999; margin-top: 2px;
    }

    /* Custom score rows */
    .custom-score-row { margin-bottom: 16px; }
    .custom-score-inner {
      display: flex; gap: 10px; align-items: flex-end;
    }
    .custom-label-input {
      flex: 1;
      padding: 8px 10px;
      border: 1.5px solid #dce2ef;
      border-radius: 8px;
      font-size: 14px;
      background: #fafbfd;
      outline: none;
    }
    .custom-label-input:focus { border-color: #1F3864; }
    .custom-slider-wrap { flex: 2; }

    .submit-btn {
      width: 100%;
      padding: 14px;
      background: #1F3864;
      color: #fff;
      border: none;
      border-radius: 10px;
      font-size: 16px;
      font-weight: 700;
      cursor: pointer;
      margin-top: 8px;
      margin-bottom: 8px;
      letter-spacing: 0.5px;
      transition: opacity 0.2s;
    }
    .submit-btn:disabled { opacity: 0.6; cursor: not-allowed; }

    .success {
      display: none;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 48px 24px;
      text-align: center;
    }
    .checkmark {
      width: 72px; height: 72px;
      background: #d4edda;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 36px; color: #2e7d32;
      margin-bottom: 20px;
    }
    .success h2 { font-size: 24px; color: #1F3864; margin-bottom: 10px; }
    .success p  { color: #666; font-size: 15px; margin-bottom: 24px; }
    .new-entry-btn {
      padding: 12px 32px;
      background: #1F3864;
      color: #fff;
      border: none;
      border-radius: 10px;
      font-size: 15px;
      cursor: pointer;
      font-weight: 600;
    }
    .footer {
      text-align: center;
      color: #aaa;
      font-size: 11px;
      margin-top: 16px;
      padding-bottom: 4px;
    }
    .spinner {
      display: inline-block;
      width: 16px; height: 16px;
      border: 2px solid rgba(255,255,255,0.4);
      border-top-color: #fff;
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
      vertical-align: middle;
      margin-right: 8px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .lang-note {
      font-size: 12px; color: #888; font-style: italic;
      margin-bottom: 6px; margin-top: -10px;
    }

    /* Voice button */
    .voice-btn {
      background: none; border: none; cursor: pointer;
      color: #1F3864; font-size: 18px; padding: 4px 6px;
      border-radius: 6px; transition: background 0.2s;
      vertical-align: middle;
    }
    .voice-btn:hover { background: #eef1f7; }
    .voice-btn.recording { color: #d9534f; animation: pulse 1s infinite; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
    .field-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; }
    .field-header label { margin-bottom:0; }

    /* Photo upload */
    .photo-upload-area {
      border: 2px dashed #dce2ef; border-radius: 10px;
      padding: 16px; text-align: center; cursor: pointer;
      background: #fafbfd; transition: border-color 0.2s;
    }
    .photo-upload-area:hover { border-color: #1F3864; }
    .photo-upload-area input[type="file"] { display:none; }
    .photo-previews { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
    .photo-thumb { width:72px; height:72px; object-fit:cover; border-radius:8px;
                   border:2px solid #dce2ef; }
    .photo-remove { position:relative; display:inline-block; }
    .photo-remove-btn { position:absolute; top:-4px; right:-4px; width:18px; height:18px;
      background:#d9534f; color:#fff; border:none; border-radius:50%; font-size:11px;
      cursor:pointer; display:flex; align-items:center; justify-content:center; line-height:1; }

    /* Lumia voice chat */
    .lumia-fab {
      position: fixed; bottom: 28px; right: 20px;
      width: 56px; height: 56px;
      background: #1F3864; color: #fff;
      border: none; border-radius: 50%;
      font-size: 24px; cursor: pointer;
      box-shadow: 0 4px 16px rgba(31,56,100,0.35);
      display: flex; align-items: center; justify-content: center;
      z-index: 1000; transition: transform 0.2s;
    }
    .lumia-fab:hover { transform: scale(1.1); }
    .lumia-panel {
      position: fixed; bottom: 96px; right: 16px;
      width: min(360px, calc(100vw - 32px));
      background: #fff; border-radius: 16px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.18);
      z-index: 999; overflow: hidden;
      display: none; flex-direction: column;
    }
    .lumia-panel.open { display: flex; }
    .lumia-panel-header {
      background: #1F3864; color: #fff;
      padding: 14px 16px; display:flex; align-items:center; justify-content:space-between;
    }
    .lumia-panel-header h3 { font-size:15px; font-weight:700; letter-spacing:1px; }
    .lumia-panel-close { background:none; border:none; color:#fff; font-size:20px; cursor:pointer; }
    .lumia-messages { flex:1; max-height:260px; overflow-y:auto; padding:12px; }
    .lumia-msg { margin-bottom:10px; }
    .lumia-msg .bubble {
      display:inline-block; padding:9px 13px; border-radius:12px;
      font-size:13px; line-height:1.5; max-width:90%;
    }
    .lumia-msg.user .bubble { background:#1F3864; color:#fff; float:right; border-radius:12px 12px 2px 12px; }
    .lumia-msg.lumia .bubble { background:#f4f6fb; color:#333; border-radius:12px 12px 12px 2px; }
    .lumia-msg::after { content:''; display:block; clear:both; }
    .lumia-input-row {
      padding:10px 12px; border-top:1px solid #eee;
      display:flex; gap:8px; align-items:center;
    }
    .lumia-input-row input {
      flex:1; padding:9px 12px; border:1.5px solid #dce2ef;
      border-radius:20px; font-size:14px; outline:none;
    }
    .lumia-input-row input:focus { border-color:#1F3864; }
    .lumia-send-btn {
      background:#1F3864; color:#fff; border:none; border-radius:50%;
      width:36px; height:36px; font-size:16px; cursor:pointer;
      display:flex; align-items:center; justify-content:center;
    }
    .lumia-mic-btn {
      background:none; border:none; font-size:20px; cursor:pointer;
      color:#1F3864; padding:4px;
    }
    .lumia-mic-btn.recording { color:#d9534f; animation:pulse 1s infinite; }
    .lumia-status { font-size:11px; color:#999; text-align:center; padding:4px 12px; }

    /* Employee auth bar */
    .emp-bar {
      background:#f4f6fb; border-bottom:1px solid #e0e4ed;
      padding:8px 20px; display:flex; align-items:center;
      justify-content:space-between; font-size:12px; color:#666;
    }
    .emp-bar a { color:#1F3864; font-weight:700; text-decoration:none; font-size:12px; }
  </style>
</head>
<body>
<div class="card">
  <div class="header">
    <img src="/static/logo.png" alt="Ashrah Painting">
    <p>Daily Check-In</p>
  </div>

  <!-- EMPLOYEE AUTH BAR -->
  <div class="emp-bar">
    <span>&#128100; Signed in as <strong>{{ employee_name }}</strong></span>
    <a href="/employee-logout">Sign out</a>
  </div>

  <!-- LANGUAGE BAR -->
  <div class="lang-bar">
    <span>🌐</span>
    <button class="lang-btn active" onclick="setLang('en')">English</button>
    <button class="lang-btn" onclick="setLang('ar')">العربية</button>
    <button class="lang-btn" onclick="setLang('fr')">Français</button>
    <button class="lang-btn" onclick="setLang('es')">Español</button>
    <button class="lang-btn" onclick="setLang('tg')">ትግርኛ</button>
  </div>

  <!-- FORM -->
  <div class="form-body" id="formSection">
    <form id="checkinForm">
      <input type="hidden" name="language" id="langField" value="en">
      <input type="hidden" name="worker_name" value="{{ employee_name }}">

      <div class="field">
        <label id="lbl_name">YOUR NAME</label>
        <div style="padding:12px 14px;border:1.5px solid #dce2ef;border-radius:10px;background:#f4f6fb;font-size:15px;color:#1F3864;font-weight:600;">{{ employee_name }}</div>
      </div>

      <div class="field">
        <label id="lbl_site">JOB SITE</label>
        <select name="site_address" id="site_address_input" required
                style="width:100%;padding:12px 14px;border:1.5px solid #dce2ef;border-radius:10px;font-size:15px;color:#222;background:#fafbfd;">
          <option value="">Loading jobs...</option>
        </select>
        <input type="hidden" name="job_id" id="job_id_input">
      </div>

      <!-- Category Scores -->
      <div class="section-title" id="lbl_rateWork">&#9733; Rate Your Work Today</div>

      {% for field_name, label_text in categories %}
      <div class="score-row">
        <div class="score-row-header">
          <span class="score-label cat-label" data-en="{{ label_text }}">{{ label_text }}</span>
          <div class="score-badge" id="{{ field_name }}_val" style="background:#f0ad4e">5</div>
        </div>
        <div class="slider-wrap">
          <input type="range" name="{{ field_name }}" min="1" max="10" value="5"
                 oninput="updateScore(this)" data-label="{{ field_name }}_val">
          <div class="slider-minmax"><span>1</span><span>10</span></div>
        </div>
      </div>
      {% endfor %}

      <!-- Custom optional score fields -->
      <div class="section-title" id="lbl_addOwn">&#43; Add Your Own (Optional)</div>
      <p class="lang-note" id="lbl_addOwnNote">Leave blank to skip</p>

      {% for i in range(1, 5) %}
      <div class="custom-score-row">
        <div class="custom-score-inner">
          <input type="text" class="custom-label-input" name="custom_label_{{ i }}"
                 id="custom_label_{{ i }}_input" placeholder="Category name">
          <div class="custom-slider-wrap">
            <div class="score-row-header">
              <span style="font-size:12px;color:#999" id="custom_{{ i }}_hint">Score</span>
              <div class="score-badge" id="custom_{{ i }}_val"
                   style="background:#ddd;color:#999;font-size:16px">5</div>
            </div>
            <input type="range" name="custom_score_{{ i }}" min="1" max="10" value="5"
                   oninput="updateScore(this)" data-label="custom_{{ i }}_val">
            <div class="slider-minmax"><span>1</span><span>10</span></div>
          </div>
        </div>
      </div>
      {% endfor %}

      <!-- Daily Summary -->
      <div class="section-title" id="lbl_summary">&#9998; Daily Summary</div>
      <p class="lang-note" id="lbl_langNote">You can write in any language</p>

      <div class="field">
        <div class="field-header">
          <label style="font-size:11px;font-weight:700;color:#1F3864;letter-spacing:.8px;text-transform:uppercase;">Summary</label>
          <button type="button" class="voice-btn" onclick="startVoice('work_description_ta')" title="Speak your summary">&#127908;</button>
        </div>
        <textarea name="work_description" id="work_description_ta"
          placeholder="Write a brief summary of everything you did on site today..."
          required></textarea>
      </div>

      <!-- Tomorrow's Plan -->
      <div class="section-title" id="lbl_tomorrow">&#128203; Tomorrow's Plan</div>

      <div class="field">
        <div class="field-header">
          <label style="font-size:11px;font-weight:700;color:#1F3864;letter-spacing:.8px;text-transform:uppercase;">Plan</label>
          <button type="button" class="voice-btn" onclick="startVoice('tomorrows_plan_ta')" title="Speak tomorrow's plan">&#127908;</button>
        </div>
        <textarea name="tomorrows_plan" id="tomorrows_plan_ta"
          placeholder="What is the plan for tomorrow at this site..."></textarea>
      </div>

      <div class="field">
        <div class="field-header">
          <label id="lbl_notes">NOTES (OPTIONAL)</label>
          <button type="button" class="voice-btn" onclick="startVoice('notes_input')" title="Speak your notes">&#127908;</button>
        </div>
        <input type="text" name="notes" id="notes_input"
               placeholder="Any issues, delays, or extra info...">
      </div>

      <!-- Photo Upload -->
      <div class="section-title">&#128247; Site Photos (Optional)</div>
      <div class="field">
        <div class="photo-upload-area" onclick="document.getElementById('photoInput').click()">
          <input type="file" id="photoInput" accept="image/*" multiple onchange="handlePhotos(this)">
          <div id="photoUploadLabel">&#128247; Tap to add photos from your site</div>
          <div class="photo-previews" id="photoPreviews"></div>
        </div>
        <div id="photoStatus" style="font-size:12px;color:#888;margin-top:6px;"></div>
      </div>

      <button type="submit" class="submit-btn" id="submitBtn" data-en="Submit Check-In">
        Submit Check-In
      </button>
    </form>
  </div>

  <!-- SUCCESS -->
  <div class="success" id="successSection">
    <div class="checkmark">&#10003;</div>
    <h2 id="lbl_successTitle">Check-In Submitted!</h2>
    <p id="successMsg">Your entry has been logged. Good work today!</p>
    <button class="new-entry-btn" onclick="resetForm()" id="lbl_submitAnother">
      Submit Another
    </button>
  </div>
</div>

<!-- MY JOBS -->
<div style="max-width:520px;margin:16px auto 0;padding:0 16px 40px;">
  <div style="background:#fff;border-radius:16px;overflow:hidden;
              box-shadow:0 4px 24px rgba(0,0,0,.10);">
    <div style="background:#1F3864;color:#fff;padding:16px 20px;
                font-size:15px;font-weight:800;letter-spacing:1px;">
      MY ACTIVE JOBS
    </div>
    <div id="my-jobs-list" style="padding:16px 20px;">
      <p style="color:#999;font-size:13px;">Loading your jobs...</p>
    </div>
  </div>
</div>

<div class="footer">Lumia &mdash; Ashrah Painting Operations Agent</div>

<!-- LUMIA VOICE CHAT FAB -->
<button class="lumia-fab" onclick="toggleLumiaPanel()" title="Talk to Lumia">&#129302;</button>
<div class="lumia-panel" id="lumiaPanel">
  <div class="lumia-panel-header">
    <h3>&#129302; LUMIA</h3>
    <button class="lumia-panel-close" onclick="toggleLumiaPanel()">&#10005;</button>
  </div>
  <div class="lumia-messages" id="lumiaMessages">
    <div class="lumia-msg lumia">
      <div class="bubble">Hi! I'm Lumia. Ask me anything about your job, site, or how to fill in your check-in. You can type or tap the mic to speak.</div>
    </div>
  </div>
  <div class="lumia-status" id="lumiaStatus"></div>
  <div class="lumia-input-row">
    <button class="lumia-mic-btn" id="lumiaMicBtn" onclick="toggleLumiaMic()" title="Speak">&#127908;</button>
    <input type="text" id="lumiaInput" placeholder="Ask Lumia anything..." onkeydown="if(event.key==='Enter')sendLumiaMsg()">
    <button class="lumia-send-btn" onclick="sendLumiaMsg()">&#10148;</button>
  </div>
</div>

<script>
  // -----------------------------------------------------------------------
  // Translations
  // -----------------------------------------------------------------------
  const T = {
    en: {
      name: "YOUR NAME", selectName: "Select your name",
      site: "SITE ADDRESS", sitePh: "e.g. 23 Falcon Rd, Winnipeg, MB",
      rateWork: "★ Rate Your Work Today",
      cats: ["Tape & Covering","Use of Drop Sheets","Patching Process","Paint Execution","Site Control","Washing & Tool Care"],
      addOwn: "+ Add Your Own (Optional)", addOwnNote: "Leave blank to skip",
      labelPh: "Category name",
      summary: "✏ Daily Summary", langNote: "You can write in any language",
      summaryPh: "Write a brief summary of everything you did on site today...",
      tomorrow: "📋 Tomorrow's Plan",
      tomorrowPh: "What is the plan for tomorrow at this site...",
      notes: "NOTES (OPTIONAL)", notesPh: "Any issues, delays, or extra info...",
      submit: "Submit Check-In", submitting: "Submitting...",
      successTitle: "Check-In Submitted!", submitAnother: "Submit Another",
      dir: "ltr"
    },
    ar: {
      name: "الاسم", selectName: "اختر اسمك",
      site: "عنوان الموقع", sitePh: "مثال: 23 Falcon Rd, Winnipeg, MB",
      rateWork: "★ قيّم عملك اليوم",
      cats: ["اللاصق والتغطية","الأغطية الواقية","عملية الترقيع","تنفيذ الطلاء","التحكم في الموقع","غسيل الأدوات"],
      addOwn: "+ أضف تقييمك الخاص (اختياري)", addOwnNote: "اتركه فارغاً للتخطي",
      labelPh: "اسم الفئة",
      summary: "✏ ملخص اليوم", langNote: "يمكنك الكتابة بأي لغة",
      summaryPh: "اكتب ملخصاً موجزاً لكل ما قمت به في الموقع اليوم...",
      tomorrow: "📋 خطة الغد",
      tomorrowPh: "ما هي الخطة لغد في هذا الموقع...",
      notes: "ملاحظات (اختياري)", notesPh: "أي مشاكل أو تأخيرات أو معلومات إضافية...",
      submit: "إرسال تسجيل الحضور", submitting: "جارٍ الإرسال...",
      successTitle: "تم تسجيل الحضور!", submitAnother: "إرسال آخر",
      dir: "rtl"
    },
    fr: {
      name: "VOTRE NOM", selectName: "Choisissez votre nom",
      site: "ADRESSE DU CHANTIER", sitePh: "ex. 23 Falcon Rd, Winnipeg, MB",
      rateWork: "★ Évaluez votre travail aujourd'hui",
      cats: ["Ruban & couverture","Toiles de protection","Processus de ragréage","Exécution de la peinture","Contrôle du site","Nettoyage & entretien"],
      addOwn: "+ Ajoutez les vôtres (optionnel)", addOwnNote: "Laisser vide pour passer",
      labelPh: "Nom de la catégorie",
      summary: "✏ Résumé du jour", langNote: "Vous pouvez écrire dans n'importe quelle langue",
      summaryPh: "Rédigez un bref résumé de tout ce que vous avez fait aujourd'hui...",
      tomorrow: "📋 Plan pour demain",
      tomorrowPh: "Quel est le plan pour demain sur ce chantier...",
      notes: "NOTES (OPTIONNEL)", notesPh: "Problèmes, retards ou infos supplémentaires...",
      submit: "Soumettre le pointage", submitting: "Envoi en cours...",
      successTitle: "Pointage soumis!", submitAnother: "Soumettre un autre",
      dir: "ltr"
    },
    es: {
      name: "TU NOMBRE", selectName: "Selecciona tu nombre",
      site: "DIRECCIÓN DEL SITIO", sitePh: "ej. 23 Falcon Rd, Winnipeg, MB",
      rateWork: "★ Califica tu trabajo hoy",
      cats: ["Cinta & cobertura","Uso de lonas","Proceso de reparación","Ejecución de pintura","Control del sitio","Limpieza & herramientas"],
      addOwn: "+ Agrega las tuyas (opcional)", addOwnNote: "Dejar en blanco para omitir",
      labelPh: "Nombre de categoría",
      summary: "✏ Resumen del día", langNote: "Puedes escribir en cualquier idioma",
      summaryPh: "Escribe un breve resumen de todo lo que hiciste hoy en el sitio...",
      tomorrow: "📋 Plan para mañana",
      tomorrowPh: "¿Cuál es el plan para mañana en este sitio?",
      notes: "NOTAS (OPCIONAL)", notesPh: "Problemas, retrasos o información extra...",
      submit: "Enviar registro", submitting: "Enviando...",
      successTitle: "¡Registro enviado!", submitAnother: "Enviar otro",
      dir: "ltr"
    },
    tg: {
      name: "ስምካ", selectName: "ስምካ ምረጽ",
      site: "ኣድራሻ መስርሒ", sitePh: "ንኣብነት 23 Falcon Rd, Winnipeg, MB",
      rateWork: "★ ናይ ሎሚ ስራሕካ ግምት ሃብ",
      cats: ["ቴፕ & ሽፋን","ናይ ስራሕ ኩፈት","ናይ ጥርሖ ሂደት","ናይ ቀለም ስራሕ","ናይ ቦታ ቁጽጽር","ምሕጻብ & ቁሳቁስ"],
      addOwn: "+ ናትካ ወስኽ (ምርጫ)", addOwnNote: "ባዶ ግደፍ ክትሰጥፎ",
      labelPh: "ስም መምዘኒ",
      summary: "✏ ናይ ሎሚ ጸብጻብ", langNote: "ብዝኾነ ቋንቋ ክትጽሕፍ ትኽእል",
      summaryPh: "ሎሚ ኣብ ስራሕ ቦታ ዝገበርካዮ ብሓጺር ጸብጻብ...",
      tomorrow: "📋 ናይ ጽባሕ መደብ",
      tomorrowPh: "ጽባሕ ኣብዚ ቦታ ዘሎ መደብ...",
      notes: "ናይ ተወሳኺ ሓሳብ (ምርጫ)", notesPh: "ዝኾነ ጸገም ወይ ተወሳኺ ሓሳብ...",
      submit: "ጸብጻብ ስደድ", submitting: "እናለኣኸ ኣሎ...",
      successTitle: "ጸብጻብ ተለኢኹ!", submitAnother: "ካልእ ስደድ",
      dir: "ltr"
    }
  };

  let currentLang = 'en';

  function setLang(lang) {
    if (!T[lang]) return;
    currentLang = lang;
    const t = T[lang];
    document.getElementById('htmlRoot').setAttribute('dir', t.dir);
    document.getElementById('langField').value = lang;

    document.getElementById('lbl_name').textContent      = t.name;
    document.getElementById('lbl_selectName').textContent = t.selectName;
    document.getElementById('lbl_site').textContent      = t.site;
    // site is now a dropdown, no placeholder needed
    document.getElementById('lbl_rateWork').textContent  = t.rateWork;
    document.getElementById('lbl_addOwn').textContent    = t.addOwn;
    document.getElementById('lbl_addOwnNote').textContent= t.addOwnNote;
    document.getElementById('lbl_summary').textContent   = t.summary;
    document.getElementById('lbl_langNote').textContent  = t.langNote;
    document.getElementById('lbl_tomorrow').textContent  = t.tomorrow;
    document.getElementById('lbl_notes').textContent     = t.notes;
    document.getElementById('lbl_successTitle').textContent = t.successTitle;
    document.getElementById('lbl_submitAnother').textContent = t.submitAnother;
    document.getElementById('submitBtn').textContent     = t.submit;
    document.getElementById('submitBtn').dataset.en      = t.submit;
    document.getElementById('work_description_ta').placeholder = t.summaryPh;
    document.getElementById('tomorrows_plan_ta').placeholder   = t.tomorrowPh;
    document.getElementById('notes_input').placeholder         = t.notesPh;

    // Category labels
    const catLabels = document.querySelectorAll('.cat-label');
    catLabels.forEach((el, i) => {
      el.textContent = t.cats[i] || el.dataset.en;
    });

    // Custom field placeholders
    for (let i = 1; i <= 4; i++) {
      const el = document.getElementById('custom_label_' + i + '_input');
      if (el) el.placeholder = t.labelPh;
    }

    // Active button
    document.querySelectorAll('.lang-btn').forEach(btn => btn.classList.remove('active'));
    event.target.classList.add('active');
  }

  // -----------------------------------------------------------------------
  // Sliders
  // -----------------------------------------------------------------------
  function scoreColor(val) {
    if (val >= 8) return '#4CAF50';
    if (val >= 5) return '#f0ad4e';
    return '#d9534f';
  }

  function updateScore(slider) {
    const badge = document.getElementById(slider.dataset.label);
    if (!badge) return;
    badge.textContent      = slider.value;
    badge.style.background = scoreColor(parseInt(slider.value));
    badge.style.color      = '#fff';
  }

  document.querySelectorAll('input[type="range"]').forEach(s => updateScore(s));

  // -----------------------------------------------------------------------
  // Submit
  // -----------------------------------------------------------------------
  document.getElementById('checkinForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('submitBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>' + (T[currentLang].submitting);

    const data = Object.fromEntries(new FormData(e.target));
    data.photo_urls = uploadedPhotoUrls.join(',');

    try {
      const res  = await fetch('/submit', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
      });
      const json = await res.json();

      if (json.ok) {
        const t = T[currentLang];
        document.getElementById('successMsg').textContent =
          data.worker_name + ' @ ' + data.site_address;
        document.getElementById('lbl_successTitle').textContent = t.successTitle;
        document.getElementById('lbl_submitAnother').textContent = t.submitAnother;
        document.getElementById('formSection').style.display    = 'none';
        document.getElementById('successSection').style.display = 'flex';
      } else {
        alert('Something went wrong: ' + (json.error || 'Unknown error'));
        btn.disabled = false;
        btn.innerHTML = T[currentLang].submit;
      }
    } catch (err) {
      alert('Network error — please try again.');
      btn.disabled = false;
      btn.innerHTML = T[currentLang].submit;
    }
  });

  function resetForm() {
    document.getElementById('checkinForm').reset();
    document.querySelectorAll('input[type="range"]').forEach(s => updateScore(s));
    document.getElementById('submitBtn').disabled = false;
    document.getElementById('submitBtn').innerHTML = T[currentLang].submit;
    document.getElementById('successSection').style.display = 'none';
    document.getElementById('formSection').style.display    = 'block';
    uploadedPhotoUrls = [];
    document.getElementById('photoPreviews').innerHTML = '';
    document.getElementById('photoUploadLabel').style.display = '';
  }

  // -----------------------------------------------------------------------
  // Voice Input (Speech-to-Text for form fields)
  // -----------------------------------------------------------------------
  const LANG_CODES = { en:'en-US', ar:'ar-SA', fr:'fr-FR', es:'es-ES', tg:'ti' };
  let activeVoiceBtn = null;
  let activeRecognition = null;

  function startVoice(targetId) {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) { alert('Voice input is not supported in this browser. Try Chrome or Edge.'); return; }
    if (activeRecognition) { activeRecognition.stop(); return; }

    const recognition = new SpeechRec();
    recognition.lang = LANG_CODES[currentLang] || 'en-US';
    recognition.continuous = false;
    recognition.interimResults = false;

    const btn = event.currentTarget;
    btn.classList.add('recording');
    activeVoiceBtn = btn;
    activeRecognition = recognition;

    recognition.onresult = (e) => {
      const transcript = e.results[0][0].transcript;
      const el = document.getElementById(targetId);
      if (!el) return;
      if (el.tagName === 'TEXTAREA') {
        el.value = (el.value ? el.value + ' ' : '') + transcript;
      } else {
        el.value = (el.value ? el.value + ' ' : '') + transcript;
      }
    };
    recognition.onend = () => {
      btn.classList.remove('recording');
      activeVoiceBtn = null;
      activeRecognition = null;
    };
    recognition.onerror = (e) => {
      btn.classList.remove('recording');
      activeVoiceBtn = null;
      activeRecognition = null;
      if (e.error !== 'no-speech') alert('Voice error: ' + e.error);
    };
    recognition.start();
  }

  // -----------------------------------------------------------------------
  // Photo Upload
  // -----------------------------------------------------------------------
  let uploadedPhotoUrls = [];

  async function handlePhotos(input) {
    const files = Array.from(input.files);
    if (!files.length) return;
    const status = document.getElementById('photoStatus');
    const previews = document.getElementById('photoPreviews');
    document.getElementById('photoUploadLabel').style.display = 'none';
    status.textContent = 'Uploading photos...';

    for (const file of files) {
      const formData = new FormData();
      formData.append('photo', file);
      try {
        const res = await fetch('/api/upload-photo', { method:'POST', body: formData });
        const d = await res.json();
        if (d.url) {
          uploadedPhotoUrls.push(d.url);
          const wrap = document.createElement('div');
          wrap.className = 'photo-remove';
          const img = document.createElement('img');
          img.src = d.url; img.className = 'photo-thumb';
          const rmBtn = document.createElement('button');
          rmBtn.type = 'button'; rmBtn.className = 'photo-remove-btn';
          rmBtn.textContent = '×';
          rmBtn.onclick = () => {
            uploadedPhotoUrls = uploadedPhotoUrls.filter(u => u !== d.url);
            wrap.remove();
            if (!uploadedPhotoUrls.length) document.getElementById('photoUploadLabel').style.display = '';
          };
          wrap.appendChild(img); wrap.appendChild(rmBtn);
          previews.appendChild(wrap);
        }
      } catch(e) { status.textContent = 'Upload failed for ' + file.name; }
    }
    status.textContent = uploadedPhotoUrls.length + ' photo(s) ready';
    input.value = '';
  }

  // -----------------------------------------------------------------------
  // Load active jobs into site dropdown
  // -----------------------------------------------------------------------
  // Load My Jobs with Mark Done button
  (async function loadMyJobs() {
    try {
      const jobs = await fetch('/api/active-jobs').then(r => r.json());
      const el = document.getElementById('my-jobs-list');
      if (!jobs.length) {
        el.innerHTML = '<p style="color:#999;font-size:13px;">No active jobs assigned to you.</p>';
        return;
      }
      el.innerHTML = jobs.map(j => `
        <div style="padding:12px 0;border-bottom:1px solid #eee;display:flex;
                    align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
          <div>
            <div style="font-weight:700;font-size:14px;color:#1F3864;">${j.client_name}</div>
            <div style="font-size:12px;color:#666;">${j.site_address}</div>
          </div>
          <button id="done-btn-${j.id}"
            style="padding:8px 18px;background:#d9534f;color:#fff;border:none;
                   border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;"
            onclick="markMyJobDone('${j.id}', '${j.site_address.replace(/'/g,"\\'")}')">
            ✅ Mark Done
          </button>
        </div>`).join('');
    } catch(e) {}
  })();

  async function markMyJobDone(jobId, site) {
    if (!confirm('Mark "' + site + '" as completed?')) return;
    const btn = document.getElementById('done-btn-' + jobId);
    if (btn) { btn.disabled = true; btn.textContent = '⏳...'; }
    try {
      const r = await fetch('/api/mark-job-done', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({job_id: jobId})
      });
      const d = await r.json();
      if (d.ok && btn) {
        btn.textContent = '✓ Marked Done';
        btn.style.background = '#388e3c';
        btn.disabled = true;
      } else if (btn) { btn.disabled = false; btn.textContent = '✅ Mark Done'; }
    } catch(e) { if (btn) { btn.disabled = false; btn.textContent = '✅ Mark Done'; } }
  }

  (async function loadJobSites() {
    try {
      const r = await fetch('/api/active-jobs');
      const jobs = await r.json();
      const sel = document.getElementById('site_address_input');
      const jobIdInput = document.getElementById('job_id_input');
      sel.innerHTML = '<option value="">-- Select a job site --</option>';
      jobs.forEach(j => {
        const opt = document.createElement('option');
        opt.value = j.site_address;
        opt.dataset.jobId = j.id || '';
        opt.textContent = j.site_address + ' (' + j.client_name + ')';
        sel.appendChild(opt);
      });
      sel.addEventListener('change', function() {
        const selected = sel.options[sel.selectedIndex];
        jobIdInput.value = selected ? (selected.dataset.jobId || '') : '';
      });
    } catch(e) {
      console.error('Failed to load jobs:', e);
    }
  })();

  // -----------------------------------------------------------------------
  // Lumia Voice Chat
  // -----------------------------------------------------------------------
  let lumiaPanelOpen = false;
  let lumiaMicRec = null;

  function toggleLumiaPanel() {
    lumiaPanelOpen = !lumiaPanelOpen;
    document.getElementById('lumiaPanel').classList.toggle('open', lumiaPanelOpen);
    if (lumiaPanelOpen) document.getElementById('lumiaInput').focus();
  }

  function appendLumiaMsg(role, text) {
    const msgs = document.getElementById('lumiaMessages');
    const div = document.createElement('div');
    div.className = 'lumia-msg ' + role;
    var safe = text; try { safe = text.replace(new RegExp(String.fromCharCode(60),'g'),'&lt;').replace(new RegExp(String.fromCharCode(10),'g'),'<br>'); } catch(e){}
    div.innerHTML = '<div class="bubble">' + safe + '<'+'/div>';
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  }

  async function sendLumiaMsg() {
    const input = document.getElementById('lumiaInput');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    appendLumiaMsg('user', text);
    document.getElementById('lumiaStatus').textContent = 'Lumia is thinking...';
    try {
      const res = await fetch('/api/lumia-chat', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ message: text })
      });
      const d = await res.json();
      appendLumiaMsg('lumia', d.reply || 'Sorry, I could not respond right now.');
    } catch(e) {
      appendLumiaMsg('lumia', 'Connection error. Please try again.');
    }
    document.getElementById('lumiaStatus').textContent = '';
  }

  function toggleLumiaMic() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) { alert('Voice not supported in this browser.'); return; }
    const btn = document.getElementById('lumiaMicBtn');
    if (lumiaMicRec) { lumiaMicRec.stop(); return; }
    const rec = new SpeechRec();
    rec.lang = LANG_CODES[currentLang] || 'en-US';
    rec.continuous = false;
    rec.interimResults = false;
    btn.classList.add('recording');
    lumiaMicRec = rec;
    rec.onresult = (e) => {
      document.getElementById('lumiaInput').value = e.results[0][0].transcript;
      sendLumiaMsg();
    };
    rec.onend = () => { btn.classList.remove('recording'); lumiaMicRec = null; };
    rec.onerror = () => { btn.classList.remove('recording'); lumiaMicRec = null; };
    rec.start();
  }
</script>
</body>
</html>"""


@app.route("/")
@require_employee
def index():
    return render_template_string(HTML, employees=EMPLOYEES, categories=CATEGORIES,
                                  employee_name=session.get("employee_name", ""))


@app.route("/submit", methods=["POST"])
def submit():
    try:
        data = request.get_json()
        lang = data.get("language", "en")

        # Build custom scores string from optional fields
        custom_parts = []
        for i in range(1, 5):
            label = (data.get(f"custom_label_{i}") or "").strip()
            score = data.get(f"custom_score_{i}", "5")
            if label:
                custom_parts.append(f"{label}: {score}/10")
        custom_scores_str = " | ".join(custom_parts)

        # Translate text fields to English if needed
        text_fields = {
            "work_description": (data.get("work_description") or "").strip(),
            "tomorrows_plan":   (data.get("tomorrows_plan")   or "").strip(),
            "notes":            (data.get("notes")            or "").strip(),
        }
        # Also translate custom labels
        for i in range(1, 5):
            lbl = (data.get(f"custom_label_{i}") or "").strip()
            if lbl:
                text_fields[f"custom_label_{i}"] = lbl

        if lang != "en":
            text_fields = _translate_fields(text_fields, lang)
            # Rebuild custom scores with translated labels
            custom_parts = []
            for i in range(1, 5):
                label = text_fields.get(f"custom_label_{i}", "").strip()
                score = data.get(f"custom_score_{i}", "5")
                if label:
                    custom_parts.append(f"{label}: {score}/10")
            custom_scores_str = " | ".join(custom_parts)

        scores = [
            int(data.get("tape_covering",    5)),
            int(data.get("drop_sheets",       5)),
            int(data.get("patching_process",  5)),
            int(data.get("paint_execution",   5)),
            int(data.get("site_control",      5)),
            int(data.get("washing_tool_care", 5)),
        ]
        avg_score = round(sum(scores) / len(scores))

        # Use session employee name (prevents spoofing)
        employee_name = session.get("employee_name") or data.get("worker_name", "").strip()
        photo_urls = (data.get("photo_urls") or "").strip()

        entry = EmployeeDailyEntry(
            entry_date=date.today().isoformat(),
            worker_id="",
            worker_name=employee_name,
            site_address=data.get("site_address", "").strip(),
            job_id=data.get("job_id", "").strip(),
            work_description=text_fields["work_description"],
            self_score=avg_score,
            notes=text_fields["notes"],
            tape_covering=scores[0],
            drop_sheets=scores[1],
            patching_process=scores[2],
            paint_execution=scores[3],
            site_control=scores[4],
            washing_tool_care=scores[5],
            custom_scores=custom_scores_str,
            tomorrows_plan=text_fields["tomorrows_plan"],
        )

        EmployeeLogSheet(EXCEL_LOG_PATH).append_entries([entry])

        # Save to Supabase
        if supabase_client:
            try:
                supabase_client.table("checkins").insert({
                    "entry_date":        entry.entry_date,
                    "worker_name":       entry.worker_name,
                    "site_address":      entry.site_address,
                    "job_id":            entry.job_id,
                    "tape_covering":     entry.tape_covering,
                    "drop_sheets":       entry.drop_sheets,
                    "patching_process":  entry.patching_process,
                    "paint_execution":   entry.paint_execution,
                    "site_control":      entry.site_control,
                    "washing_tool_care": entry.washing_tool_care,
                    "avg_score":         entry.self_score,
                    "work_description":  entry.work_description,
                    "custom_scores":     entry.custom_scores,
                    "tomorrows_plan":    entry.tomorrows_plan,
                    "notes":             entry.notes,
                    "photo_urls":        photo_urls,
                }).execute()
                print(f"[App] Saved to Supabase ✓")
            except Exception as exc:
                print(f"[App] Supabase error: {exc}")

        threading.Thread(target=_notify_owner,      args=(entry,), daemon=True).start()
        threading.Thread(target=_send_client_report, args=(entry,), daemon=True).start()

        return jsonify({"ok": True})

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


def _notify_owner(entry: EmployeeDailyEntry) -> None:
    if not ZOHO_PASSWORD:
        print("[App] Skipping owner email — ZOHO_PASSWORD not set")
        return
    try:
        subject = f"Lumia Check-In: {entry.worker_name} @ {entry.site_address}"
        body = (
            f"New check-in received.\n\n"
            f"Employee         : {entry.worker_name}\n"
            f"Site             : {entry.site_address}\n"
            f"Date             : {entry.entry_date}\n\n"
            f"--- SCORES ---\n"
            f"Tape & Covering  : {entry.tape_covering}/10\n"
            f"Drop Sheets      : {entry.drop_sheets}/10\n"
            f"Patching Process : {entry.patching_process}/10\n"
            f"Paint Execution  : {entry.paint_execution}/10\n"
            f"Site Control     : {entry.site_control}/10\n"
            f"Washing & Tools  : {entry.washing_tool_care}/10\n"
            f"Avg Score        : {entry.self_score}/10\n"
        )
        if entry.custom_scores:
            body += f"\nCustom Scores    : {entry.custom_scores}\n"
        body += (
            f"\n--- DAILY SUMMARY ---\n{entry.work_description}\n\n"
            f"--- TOMORROW'S PLAN ---\n{entry.tomorrows_plan or '—'}\n\n"
            f"Notes: {entry.notes or '—'}\n"
        )
        import httpx
        resend_key = os.getenv("RESEND_API_KEY", "")
        if not resend_key:
            print("[App] Skipping owner email — RESEND_API_KEY not set")
            return
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}"},
            json={
                "from": "Ashrah Painting <noreply@ashrah.ai>",
                "to":   [OWNER_EMAIL],
                "subject": subject,
                "text": body,
            },
            timeout=15,
        )
        if r.status_code == 200:
            print(f"[App] Owner email sent to {OWNER_EMAIL}")
        else:
            print(f"[App] Resend error: {r.status_code} {r.text}")
    except Exception as exc:
        print(f"[App] Owner notify error: {exc}")


# ---------------------------------------------------------------------------
# EMPLOYEE LOGIN / LOGOUT
# ---------------------------------------------------------------------------
EMPLOYEE_LOGIN_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lumia — Employee Login</title>
<style>
* { box-sizing:border-box; margin:0; padding:0; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#eef1f7; min-height:100vh; display:flex;
       align-items:center; justify-content:center; padding:20px; }
.card { background:#fff; border-radius:16px; overflow:hidden;
        box-shadow:0 4px 24px rgba(0,0,0,.10); width:100%; max-width:400px; }
.header { background:#fff; text-align:center; padding:24px 20px 14px;
          border-bottom:3px solid #1F3864; }
.header img { width:140px; display:block; margin:0 auto 8px; }
.header p  { font-size:12px; color:#1F3864; font-weight:600; }
.body { padding:28px 24px; }
.field { margin-bottom:18px; }
.field label { display:block; font-size:11px; font-weight:700; color:#1F3864;
               text-transform:uppercase; letter-spacing:.8px; margin-bottom:6px; }
.field input { width:100%; padding:12px 14px; border:1.5px solid #dce2ef;
  border-radius:10px; font-size:15px; background:#fafbfd; outline:none; }
.field input:focus { border-color:#1F3864; }
.btn { width:100%; padding:14px; background:#1F3864; color:#fff; border:none;
       border-radius:10px; font-size:16px; font-weight:700; cursor:pointer; margin-top:4px; }
.err { color:#d9534f; font-size:13px; margin-top:12px; text-align:center; }
.hint { font-size:12px; color:#999; text-align:center; margin-top:16px; }
.staff-link { font-size:12px; color:#1F3864; text-align:center; margin-top:12px; display:block; }
</style></head><body>
<div class="card">
  <div class="header"><img src="/static/logo.png" alt="Ashrah Painting"><p>Employee Login</p></div>
  <div class="body">
    <form method="POST" action="/employee-login">
      <div class="field">
        <label>Email Address</label>
        <input type="email" name="email" placeholder="your@email.com" required autocomplete="email">
      </div>
      <div class="field">
        <label>Password</label>
        <input type="password" name="password" placeholder="Enter your password" required>
      </div>
      <button class="btn" type="submit">Sign In</button>
      {% if error %}<p class="err">{{ error }}</p>{% endif %}
    </form>
    <p class="hint">Contact Ahmad if you need access or forgot your password</p>
    <a class="staff-link" href="/login">Staff / Manager Login &rarr;</a>
  </div>
</div>
</body></html>"""


@app.route("/employee-login", methods=["GET", "POST"])
def employee_login_page():
    next_url = request.args.get("next", "/")
    if request.method == "GET":
        return render_template_string(EMPLOYEE_LOGIN_HTML, error="")
    email    = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    if supabase_client:
        try:
            res = supabase_client.table("employees").select("*").eq("email", email).eq("active", True).execute()
            employees = res.data or []
            if employees:
                emp = employees[0]
                if check_password_hash(emp["password_hash"], password):
                    session["employee_name"] = emp["name"]
                    session["employee_email"] = emp["email"]
                    return redirect(next_url or "/")
        except Exception as exc:
            print(f"[Employee Login] Supabase error: {exc}")
    return render_template_string(EMPLOYEE_LOGIN_HTML, error="Incorrect email or password.")


@app.route("/employee-logout")
def employee_logout():
    session.pop("employee_name", None)
    session.pop("employee_email", None)
    return redirect("/employee-login")


# ---------------------------------------------------------------------------
# SET PASSWORD (via emailed link)
# ---------------------------------------------------------------------------
SET_PASSWORD_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lumia — Set Your Password</title>
<style>
* { box-sizing:border-box; margin:0; padding:0; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#eef1f7; min-height:100vh; display:flex;
       align-items:center; justify-content:center; padding:20px; }
.card { background:#fff; border-radius:16px; overflow:hidden;
        box-shadow:0 4px 24px rgba(0,0,0,.10); width:100%; max-width:400px; }
.header { background:#fff; text-align:center; padding:24px 20px 14px;
          border-bottom:3px solid #1F3864; }
.header img { width:140px; display:block; margin:0 auto 8px; }
.header p  { font-size:12px; color:#1F3864; font-weight:600; }
.body { padding:28px 24px; }
.welcome { font-size:15px; color:#333; margin-bottom:20px; text-align:center; }
.welcome strong { color:#1F3864; }
.field { margin-bottom:18px; }
.field label { display:block; font-size:11px; font-weight:700; color:#1F3864;
               text-transform:uppercase; letter-spacing:.8px; margin-bottom:6px; }
.field input { width:100%; padding:12px 14px; border:1.5px solid #dce2ef;
  border-radius:10px; font-size:15px; background:#fafbfd; outline:none; }
.field input:focus { border-color:#1F3864; }
.btn { width:100%; padding:14px; background:#1F3864; color:#fff; border:none;
       border-radius:10px; font-size:16px; font-weight:700; cursor:pointer; margin-top:4px; }
.err { color:#d9534f; font-size:13px; margin-top:12px; text-align:center; }
.ok  { color:#2e7d32; font-size:13px; margin-top:12px; text-align:center; }
</style></head><body>
<div class="card">
  <div class="header"><img src="/static/logo.png" alt="Ashrah Painting"><p>Set Your Password</p></div>
  <div class="body">
    {% if expired %}
      <p class="err" style="font-size:15px;margin-top:8px">This link has expired or is invalid.<br>Please ask Ahmad to send a new one.</p>
    {% else %}
      <p class="welcome">Welcome, <strong>{{ name }}</strong>! Set a password to access your check-in.</p>
      <form method="POST">
        <input type="hidden" name="token" value="{{ token }}">
        <div class="field">
          <label>New Password</label>
          <input type="password" name="password" placeholder="At least 6 characters" required minlength="6">
        </div>
        <div class="field">
          <label>Confirm Password</label>
          <input type="password" name="confirm" placeholder="Type it again" required minlength="6">
        </div>
        <button class="btn" type="submit">Set Password & Sign In</button>
        {% if error %}<p class="err">{{ error }}</p>{% endif %}
      </form>
    {% endif %}
  </div>
</div>
</body></html>"""


def _send_setup_email(name: str, email: str, token: str) -> bool:
    """Send a password setup email to the employee via Resend (ashrah.ai domain)."""
    import httpx
    resend_key = os.getenv("RESEND_API_KEY", "")
    if not resend_key:
        print("[Setup Email] RESEND_API_KEY not set — skipping")
        return False
    base_url = os.getenv("APP_BASE_URL", "https://ashrah.ai")
    setup_link = f"{base_url}/set-password?token={token}"
    html_body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:24px">
      <div style="background:#1F3864;color:#fff;padding:24px;border-radius:12px 12px 0 0;text-align:center">
        <h1 style="margin:0;font-size:28px;letter-spacing:3px">LUMIA</h1>
        <p style="margin:4px 0 0;opacity:.8;font-size:13px">Ashrah Painting Operations</p>
      </div>
      <div style="background:#fff;border:1px solid #e0e4ed;border-radius:0 0 12px 12px;padding:28px">
        <p style="font-size:16px;color:#333">Hi <strong>{name}</strong>,</p>
        <p style="color:#555;margin-top:12px">You've been added to Lumia, the Ashrah Painting daily check-in system. Click the button below to set your password and get started.</p>
        <div style="text-align:center;margin:28px 0">
          <a href="{setup_link}" style="background:#1F3864;color:#fff;padding:14px 32px;border-radius:10px;text-decoration:none;font-weight:700;font-size:16px">Set My Password</a>
        </div>
        <p style="color:#999;font-size:12px;text-align:center">This link expires in 48 hours.<br>If you didn't expect this email, ignore it.</p>
      </div>
    </div>
    """
    text_body = f"Hi {name},\n\nYou've been added to Lumia. Set your password here:\n{setup_link}\n\nThis link expires in 48 hours."
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}"},
            json={
                "from": "Ashrah Painting <noreply@ashrah.ai>",
                "to":   [email],
                "cc":   [OWNER_EMAIL] if OWNER_EMAIL and OWNER_EMAIL != email else [],
                "subject": "Welcome to Lumia — Set Your Password",
                "html": html_body,
                "text": text_body,
            },
            timeout=15,
        )
        print(f"[Setup Email] Resend response {r.status_code}: {r.text}")
        return r.status_code == 200
    except Exception as exc:
        print(f"[Setup Email] Error: {exc}")
        return False


def _notify_assigned_employees(job_info: dict, employee_names: list) -> list:
    """Email each assigned employee about their new job. Returns list of names emailed."""
    import httpx
    resend_key = os.getenv("RESEND_API_KEY", "")
    if not resend_key:
        print("[Job Email] RESEND_API_KEY not set — skipping")
        return []
    if not employee_names:
        return []
    # Look up emails from DB
    email_map = {}
    if supabase_client:
        rows = supabase_client.table("employees").select("name,email").execute().data or []
        email_map = {r["name"]: r["email"] for r in rows if r.get("email")}
    emailed = []
    for name in employee_names:
        email = email_map.get(name)
        if not email:
            print(f"[Job Email] No email for {name} — skipping")
            continue
        subject = f"New Job Assignment — {job_info.get('client_name', 'Ashrah Painting')}"
        html = f"""
        <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:24px">
          <div style="background:#1F3864;color:#fff;padding:24px;border-radius:12px 12px 0 0;text-align:center">
            <h1 style="margin:0;font-size:28px;letter-spacing:3px">LUMIA</h1>
            <p style="margin:4px 0 0;opacity:.8;font-size:13px">Ashrah Painting</p>
          </div>
          <div style="background:#fff;border:1px solid #e0e4ed;border-radius:0 0 12px 12px;padding:28px">
            <p style="font-size:16px;color:#333">Hi <strong>{name}</strong>,</p>
            <p style="color:#555;margin:12px 0;">You have been assigned to a new job:</p>
            <table style="width:100%;font-size:14px;color:#333;border-collapse:collapse;">
              <tr><td style="padding:6px 0;font-weight:600;width:100px;">Client</td><td style="padding:6px 0;">{job_info.get('client_name','—')}</td></tr>
              <tr><td style="padding:6px 0;font-weight:600;">Site</td><td style="padding:6px 0;">{job_info.get('site_address','—')}</td></tr>
              <tr><td style="padding:6px 0;font-weight:600;">Start Date</td><td style="padding:6px 0;">{job_info.get('start_date') or 'TBD'}</td></tr>
              <tr><td style="padding:6px 0;font-weight:600;">Description</td><td style="padding:6px 0;">{job_info.get('work_description') or '—'}</td></tr>
            </table>
            <p style="color:#555;margin:16px 0 0;">Please check in daily using the Lumia app.</p>
          </div>
        </div>"""
        text = (
            f"Hi {name},\n\nYou have been assigned to a new job:\n\n"
            f"Client: {job_info.get('client_name','—')}\n"
            f"Site: {job_info.get('site_address','—')}\n"
            f"Start Date: {job_info.get('start_date') or 'TBD'}\n"
            f"Description: {job_info.get('work_description') or '—'}\n\n"
            f"Please check in daily using the Lumia app.\n\n— Ashrah Painting"
        )
        try:
            r = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_key}"},
                json={
                    "from": "Ashrah Painting <noreply@ashrah.ai>",
                    "to":   [email],
                    "cc":   [OWNER_EMAIL] if OWNER_EMAIL and OWNER_EMAIL != email else [],
                    "subject": subject,
                    "html": html,
                    "text": text,
                },
                timeout=15,
            )
            if r.status_code in (200, 201):
                emailed.append(name)
                print(f"[Job Email] Sent to {name} <{email}>")
            else:
                print(f"[Job Email] Resend error for {name}: {r.status_code} {r.text}")
        except Exception as exc:
            print(f"[Job Email] Error for {name}: {exc}")
    return emailed


def _lookup_client_for_job(job_info: dict) -> dict | None:
    """Find client email/name by matching job site_address against clients table + hardcoded CLIENTS."""
    site_lower = (job_info.get("site_address") or "").lower()
    # Check hardcoded CLIENTS first
    for keyword, info in CLIENTS.items():
        if keyword in site_lower:
            return info
    # Check Supabase clients table
    if supabase_client:
        try:
            rows = supabase_client.table("clients").select("client_name,client_email,site_keyword").execute().data or []
            for row in rows:
                kw = (row.get("site_keyword") or "").lower().strip()
                if kw and kw in site_lower:
                    return {"client_name": row["client_name"], "client_email": row["client_email"]}
        except Exception as exc:
            print(f"[Client Lookup] Error: {exc}")
    return None


def _notify_client_of_assignment(job_info: dict, employee_names: list) -> bool:
    """Email the client to let them know which painters are assigned to their project."""
    import httpx
    resend_key = os.getenv("RESEND_API_KEY", "")
    if not resend_key:
        print("[Client Assignment Email] RESEND_API_KEY not set — skipping")
        return False
    client = _lookup_client_for_job(job_info)
    if not client:
        print(f"[Client Assignment Email] No client found for site: {job_info.get('site_address')}")
        return False

    client_email = client["client_email"]
    client_name  = client["client_name"]
    names_list   = ", ".join(employee_names) if employee_names else "TBD"
    start_date   = job_info.get("start_date") or "TBD"
    site         = job_info.get("site_address") or "—"
    description  = job_info.get("work_description") or "—"

    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:24px">
      <div style="background:#1F3864;color:#fff;padding:24px;border-radius:12px 12px 0 0;text-align:center">
        <h1 style="margin:0;font-size:26px;letter-spacing:2px">Ashrah Painting</h1>
        <p style="margin:6px 0 0;opacity:.8;font-size:13px">Professional Painting Services</p>
      </div>
      <div style="background:#fff;border:1px solid #e0e4ed;border-radius:0 0 12px 12px;padding:28px">
        <p style="font-size:16px;color:#333;margin:0 0 16px">Dear <strong>{client_name}</strong>,</p>
        <p style="color:#555;margin:0 0 20px;">We're pleased to confirm your upcoming painting project. Here are the details:</p>
        <table style="width:100%;border-collapse:collapse;font-size:14px;color:#333;">
          <tr style="background:#f4f6fb;">
            <td style="padding:10px 14px;font-weight:600;width:140px;border-radius:6px 0 0 6px;">Site</td>
            <td style="padding:10px 14px;">{site}</td>
          </tr>
          <tr>
            <td style="padding:10px 14px;font-weight:600;">Start Date</td>
            <td style="padding:10px 14px;">{start_date}</td>
          </tr>
          <tr style="background:#f4f6fb;">
            <td style="padding:10px 14px;font-weight:600;">Assigned Crew</td>
            <td style="padding:10px 14px;"><strong>{names_list}</strong></td>
          </tr>
          <tr>
            <td style="padding:10px 14px;font-weight:600;">Scope of Work</td>
            <td style="padding:10px 14px;">{description}</td>
          </tr>
        </table>
        <p style="color:#555;margin:20px 0 0;">Our crew will check in daily and you will receive end-of-day progress reports. If you have any questions, please don't hesitate to reach out.</p>
        <p style="color:#555;margin:16px 0 0;">Thank you for choosing Ashrah Painting!</p>
      </div>
    </div>"""

    text = (
        f"Dear {client_name},\n\n"
        f"We're pleased to confirm your painting project:\n\n"
        f"Site: {site}\n"
        f"Start Date: {start_date}\n"
        f"Assigned Crew: {names_list}\n"
        f"Scope of Work: {description}\n\n"
        f"Our crew will check in daily and you will receive end-of-day progress reports.\n\n"
        f"Thank you for choosing Ashrah Painting!"
    )
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}"},
            json={
                "from":    "Ashrah Painting <noreply@ashrah.ai>",
                "to":      [client_email],
                "cc":      [OWNER_EMAIL],
                "subject": f"Your Painting Project — Crew Assignment Confirmed",
                "html":    html,
                "text":    text,
            },
            timeout=15,
        )
        success = r.status_code in (200, 201)
        print(f"[Client Assignment Email] {'Sent' if success else 'Failed'} → {client_email} ({r.status_code})")
        return success
    except Exception as exc:
        print(f"[Client Assignment Email] Error: {exc}")
        return False


def _log_assignment(job_info: dict, employee_names: list, client_notified: bool) -> None:
    """Record the crew assignment in job_notifications table."""
    if not supabase_client:
        return
    try:
        supabase_client.table("job_notifications").insert({
            "job_id":           job_info.get("id") or job_info.get("site_address"),
            "site_address":     job_info.get("site_address"),
            "client_name":      job_info.get("client_name"),
            "assigned_crew":    employee_names,
            "client_notified":  client_notified,
            "notified_at":      datetime.utcnow().isoformat() + "Z",
        }).execute()
    except Exception as exc:
        print(f"[Assignment Log] Error: {exc}")


@app.route("/set-password", methods=["GET", "POST"])
def set_password_page():
    token = request.args.get("token") or request.form.get("token", "")
    if not token or not supabase_client:
        return render_template_string(SET_PASSWORD_HTML, expired=True, name="", token="", error="")

    # Look up token
    try:
        res = supabase_client.table("employees").select("*").eq("setup_token", token).execute()
        employees = res.data or []
    except Exception:
        return render_template_string(SET_PASSWORD_HTML, expired=True, name="", token="", error="")

    if not employees:
        return render_template_string(SET_PASSWORD_HTML, expired=True, name="", token="", error="")

    emp = employees[0]

    # Check expiry
    expires_at = emp.get("setup_token_expires")
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if datetime.now(exp.tzinfo) > exp:
                return render_template_string(SET_PASSWORD_HTML, expired=True, name=emp["name"], token=token, error="")
        except Exception:
            pass

    if request.method == "GET":
        return render_template_string(SET_PASSWORD_HTML, expired=False, name=emp["name"], token=token, error="")

    # POST — set the password
    password = request.form.get("password", "").strip()
    confirm  = request.form.get("confirm", "").strip()
    if password != confirm:
        return render_template_string(SET_PASSWORD_HTML, expired=False, name=emp["name"], token=token, error="Passwords don't match.")
    if len(password) < 6:
        return render_template_string(SET_PASSWORD_HTML, expired=False, name=emp["name"], token=token, error="Password must be at least 6 characters.")

    supabase_client.table("employees").update({
        "password_hash":       generate_password_hash(password),
        "setup_token":         None,
        "setup_token_expires": None,
        "active":              True,
    }).eq("id", emp["id"]).execute()

    # Auto-login
    session["employee_name"]  = emp["name"]
    session["employee_email"] = emp["email"]
    return redirect("/")


# ---------------------------------------------------------------------------
# PHOTO UPLOAD
# ---------------------------------------------------------------------------
@app.route("/api/upload-photo", methods=["POST"])
def api_upload_photo():
    if not session.get("employee_name") and not session.get("role"):
        return jsonify({"error": "Not authenticated"}), 401
    if "photo" not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["photo"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    filename = f"{date.today().isoformat()}/{uuid.uuid4().hex}.{ext}"
    file_bytes = file.read()
    if supabase_client:
        try:
            supabase_client.storage.from_("checkin-photos").upload(
                filename, file_bytes,
                file_options={"content-type": file.content_type or "image/jpeg"}
            )
            public_url = supabase_client.storage.from_("checkin-photos").get_public_url(filename)
            return jsonify({"url": public_url})
        except Exception as exc:
            print(f"[Photo Upload] Error: {exc}")
            return jsonify({"error": str(exc)}), 500
    return jsonify({"error": "Storage not configured"}), 500


# ---------------------------------------------------------------------------
# LUMIA VOICE CHAT
# ---------------------------------------------------------------------------
@app.route("/api/lumia-chat", methods=["POST"])
def api_lumia_chat():
    # Allow employees, managers, and owners
    if not session.get("employee_name") and not session.get("role"):
        return jsonify({"reply": "Please log in first."}), 401
    d = request.get_json()
    message = (d.get("message") or "").strip()
    if not message:
        return jsonify({"reply": "I didn't catch that. Please try again."})

    role         = session.get("role") or "employee"
    person_name  = session.get("employee_name") or session.get("name") or "the team member"
    is_staff     = role in ("owner", "manager")
    today        = date.today().isoformat()

    # ── Build live data context for owners/managers ──────────────────────────
    data_context = ""
    if is_staff and supabase_client:
        parts = []
        try:
            checkins = supabase_client.table("checkins").select("*") \
                .order("entry_date", desc=True).limit(80).execute().data or []
            if checkins:
                rows = [
                    f"  [{c['entry_date']}] {c['worker_name']} @ {c['site_address']} | "
                    f"avg={c.get('avg_score','?')}/10 | "
                    f"work: {(c.get('work_description') or '')[:150]} | "
                    f"tomorrow: {(c.get('tomorrows_plan') or '')[:80]}"
                    for c in checkins
                ]
                parts.append("RECENT CHECK-INS (verbatim from crew):\n" + "\n".join(rows))

                # Build per-employee language profiles so Lumia understands how each person writes
                emp_profiles: dict[str, list[str]] = {}
                for c in checkins:
                    name = (c.get("worker_name") or "").strip()
                    desc = (c.get("work_description") or "").strip()
                    plan = (c.get("tomorrows_plan") or "").strip()
                    if name and (desc or plan):
                        emp_profiles.setdefault(name, [])
                        if desc:
                            emp_profiles[name].append(f'"{desc}"')
                        if plan and plan != desc:
                            emp_profiles[name].append(f'(plan: "{plan}")')
                if emp_profiles:
                    profile_rows = []
                    for emp, entries in emp_profiles.items():
                        sample = " | ".join(entries[:4])  # last 4 entries max
                        profile_rows.append(f"  {emp}: {sample}")
                    parts.append("EMPLOYEE LANGUAGE & WORK PATTERNS (how each person describes their work):\n" + "\n".join(profile_rows))
        except Exception:
            pass

        try:
            jobs = supabase_client.table("jobs").select("*") \
                .order("created_at", desc=True).limit(30).execute().data or []
            if jobs:
                rows = [
                    f"  [{j.get('status','?').upper()}] {j.get('client_name','?')} @ {j.get('site_address','?')} | "
                    f"start={j.get('start_date','TBD')} painters={j.get('painters_needed','?')} | "
                    f"{(j.get('work_description') or '')[:100]}"
                    for j in jobs
                ]
                parts.append("JOBS:\n" + "\n".join(rows))
        except Exception:
            pass

        try:
            reviews = supabase_client.table("reviews").select("*") \
                .order("created_at", desc=True).limit(50).execute().data or []
            if reviews:
                c_ids = [r["checkin_id"] for r in reviews]
                c_map_data = supabase_client.table("checkins") \
                    .select("id,worker_name,entry_date,site_address") \
                    .in_("id", c_ids).execute().data or []
                c_map = {c["id"]: c for c in c_map_data}
                rows = [
                    f"  {c_map.get(rv['checkin_id'],{}).get('entry_date','?')} | "
                    f"{c_map.get(rv['checkin_id'],{}).get('worker_name','?')} | "
                    f"accuracy={rv.get('accuracy_score','?')}/10 trust={rv.get('trust_level','?')} | "
                    f"{(rv.get('notes') or '')[:80]}"
                    for rv in reviews
                ]
                parts.append("MANAGER REVIEWS:\n" + "\n".join(rows))
        except Exception:
            pass

        try:
            db_clients = supabase_client.table("clients").select("*").execute().data or []
            all_client_rows = [
                f"  {c.get('client_name','?')} | {c.get('client_email','?')} | keyword: {c.get('site_keyword','?')}"
                for c in db_clients
            ]
            for kw, info in CLIENTS.items():
                all_client_rows.append(f"  {info['client_name']} | {info['client_email']} | keyword: {kw}")
            if all_client_rows:
                parts.append("CLIENTS:\n" + "\n".join(all_client_rows))
        except Exception:
            pass

        # Explicitly map jobs to their check-ins by site address keyword
        try:
            if jobs and checkins:
                mapping_rows = []
                for j in jobs:
                    site = (j.get("site_address") or "").lower()
                    matched = [
                        c for c in checkins
                        if site and (site[:12] in (c.get("site_address") or "").lower()
                                     or (c.get("site_address") or "").lower()[:12] in site)
                    ]
                    if matched:
                        dates = sorted({c["entry_date"] for c in matched}, reverse=True)[:5]
                        mapping_rows.append(
                            f"  Job '{j.get('client_name')} @ {j.get('site_address')}' "
                            f"has {len(matched)} check-in(s) on dates: {', '.join(dates)}"
                        )
                if mapping_rows:
                    parts.append("JOB → CHECK-IN MAPPING:\n" + "\n".join(mapping_rows))
        except Exception:
            pass

        # Report schedule
        sched_hour, sched_min = 18, 0
        try:
            row = supabase_client.table("settings").select("value") \
                .eq("key", "report_schedule_time").execute().data
            if row:
                sched_hour, sched_min = map(int, row[0]["value"].split(":"))
        except Exception:
            pass
        parts.append(f"AUTO REPORT SCHEDULE: daily reports sent at {sched_hour:02d}:{sched_min:02d} Winnipeg time (6:00 PM = 18:00).")

        data_context = "\n\n".join(parts)

    system_prompt = (
        "You are Lumia, the AI operations assistant for Ashrah Painting in Winnipeg, Canada. "
        f"You are speaking with {person_name}"
        f"{', the owner' if role == 'owner' else ', a manager' if role == 'manager' else ', a painter on the team'}. "
        f"Today's date: {today}.\n\n"
    )
    if data_context:
        system_prompt += (
            "You have full access to live company data below — check-ins, jobs, clients, manager reviews, "
            "and how each employee writes and describes their work.\n\n"
            "HOW TO USE THIS DATA:\n"
            "- Read the EMPLOYEE LANGUAGE & WORK PATTERNS section to understand how each person describes what they do. "
            "Use those same terms and phrases when talking about their work — don't paraphrase into generic language.\n"
            "- If someone says Abdelhadi 'knocked out the trim on the main floor', that's the language to use — not 'completed trim painting on level 1'.\n"
            "- Use check-in descriptions to infer progress, blockers, and what's coming next. "
            "If an employee mentioned needing materials, flag it. If they said something was done, confirm it.\n"
            "- Look at JOB → CHECK-IN MAPPING to answer whether a job has received check-ins.\n"
            "- Keep replies concise — 2-4 sentences unless detail is requested. Be direct and specific. "
            "No filler. No AI-sounding phrases.\n\n"
            f"--- LIVE COMPANY DATA ---\n{data_context}\n--- END DATA ---"
        )
    else:
        system_prompt += (
            "Help with questions about daily check-ins, job sites, reports, and crew. "
            "Keep replies concise — 1-3 sentences. Be direct."
        )

    try:
        ai_client = _anthropic.Anthropic()
        response = ai_client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": message}],
        )
        return jsonify({"reply": response.content[0].text})
    except Exception as exc:
        return jsonify({"reply": f"Sorry, I'm having trouble connecting. ({exc})"})


# ---------------------------------------------------------------------------
# CLIENT-FACING LUMIA — tokenized chat scoped to one client's project
# ---------------------------------------------------------------------------
CLIENT_SAFE_CHECKIN_FIELDS = "entry_date,worker_name,site_address,work_description,tomorrows_plan"


def _lookup_client_by_token(token: str) -> dict | None:
    if not token or not supabase_client:
        return None
    try:
        rows = supabase_client.table("clients").select("*") \
            .eq("access_token", token).limit(1).execute().data or []
        return rows[0] if rows else None
    except Exception:
        return None


def _load_client_project_context(client_row: dict) -> str:
    """Build structured context scoped strictly to this client. Strips internal fields."""
    if not supabase_client:
        return ""
    keyword = (client_row.get("site_keyword") or "").lower().strip()
    parts = [
        "## CLIENT",
        f"Name: {client_row.get('client_name','')}",
        f"Project keyword: {keyword}",
        "",
    ]

    try:
        cutoff = (date.today() - timedelta(days=14)).isoformat()
        checkins = supabase_client.table("checkins") \
            .select(CLIENT_SAFE_CHECKIN_FIELDS) \
            .gte("entry_date", cutoff) \
            .order("entry_date", desc=True) \
            .limit(80).execute().data or []
        scoped = [c for c in checkins
                  if keyword and keyword in (c.get("site_address") or "").lower()]
        if scoped:
            parts.append("## CHECK-INS (last 14 days, client-safe subset)")
            for c in scoped:
                worker = (c.get("worker_name") or "").split()[0] or "Crew"
                parts.append(f"- [{c.get('entry_date')}] {worker} @ {c.get('site_address')}")
                if c.get("work_description"):
                    parts.append(f"  Work: {c['work_description']}")
                if c.get("tomorrows_plan"):
                    parts.append(f"  Next: {c['tomorrows_plan']}")
            parts.append("")
    except Exception as exc:
        print(f"[ClientChat] checkin load error: {exc}")

    try:
        cutoff_ts = (datetime.utcnow() - timedelta(days=14)).isoformat()
        sent = supabase_client.table("sent_reports") \
            .select("subject,plain_body,created_at,site_address") \
            .eq("client_email", client_row.get("client_email")) \
            .gte("created_at", cutoff_ts) \
            .order("created_at", desc=True).limit(14).execute().data or []
        if sent:
            parts.append("## RECENT DAILY REPORTS (as previously sent to client)")
            for r in sent:
                parts.append(f"--- {r.get('subject','(daily report)')} ---")
                parts.append((r.get("plain_body") or "").strip())
                parts.append("")
    except Exception as exc:
        print(f"[ClientChat] sent_reports load error: {exc}")

    return "\n".join(parts)


def _client_messages_today(client_id: str) -> int:
    if not supabase_client:
        return 0
    try:
        since = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        res = supabase_client.table("client_conversations") \
            .select("id", count="exact") \
            .eq("client_id", client_id).eq("role", "user") \
            .gte("created_at", since).execute()
        return int(getattr(res, "count", None) or len(res.data or []))
    except Exception:
        return 0


def _log_client_conversation(client_id: str, role: str, content: str) -> None:
    if not supabase_client:
        return
    try:
        supabase_client.table("client_conversations").insert({
            "client_id": client_id, "role": role, "content": content,
        }).execute()
    except Exception as exc:
        print(f"[ClientChat] conversation log error: {exc}")


def _send_instant_escalation_email(client_row: dict, question: str, reply: str) -> bool:
    """Send Ahmad an immediate email when Lumia cannot answer a client question."""
    import httpx as _httpx
    resend_key = os.getenv("RESEND_API_KEY", "")
    if not resend_key or not OWNER_EMAIL:
        return False
    client_name  = client_row.get("client_name") or "Client"
    client_email = client_row.get("client_email") or ""
    site_keyword = client_row.get("site_keyword") or ""
    subject = f"Lumia needs you: {client_name} asked something"
    html = (
        f"<div style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;max-width:600px;'>"
        f"<h2 style='color:#1F3864;margin-bottom:4px;'>Client question flagged for you</h2>"
        f"<p style='color:#666;margin-top:0;'>Lumia told the client you'd follow up.</p>"
        f"<div style='background:#f4f6fb;border-radius:10px;padding:14px 18px;margin:18px 0;'>"
        f"<p style='margin:0 0 6px;'><b>Client:</b> {client_name} &lt;{client_email}&gt;</p>"
        f"<p style='margin:0;'><b>Site:</b> {site_keyword or '(unknown)'}</p>"
        f"</div>"
        f"<p style='font-weight:600;color:#1F3864;margin-bottom:4px;'>Their question:</p>"
        f"<div style='background:#fff;border-left:3px solid #2563eb;padding:10px 14px;margin-bottom:18px;'>"
        f"{question}</div>"
        f"<p style='font-weight:600;color:#1F3864;margin-bottom:4px;'>What Lumia told them:</p>"
        f"<div style='background:#fff;border-left:3px solid #94a3b8;padding:10px 14px;color:#333;'>"
        f"{reply}</div>"
        f"<p style='color:#888;font-size:12px;margin-top:20px;'>Reply directly to the client to close this out.</p>"
        f"</div>"
    )
    plain = (
        f"Lumia flagged a client question for you.\n\n"
        f"Client: {client_name} <{client_email}>\n"
        f"Site: {site_keyword or '(unknown)'}\n\n"
        f"Their question:\n{question}\n\n"
        f"What Lumia told them:\n{reply}\n"
    )
    try:
        r = _httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
            json={
                "from":    "Lumia — Ashrah Painting <noreply@ashrah.ai>",
                "to":      [OWNER_EMAIL],
                "reply_to": client_email or OWNER_EMAIL,
                "subject": subject,
                "html":    html,
                "text":    plain,
            },
            timeout=10,
        )
        return r.status_code in (200, 201)
    except Exception as exc:
        print(f"[ClientChat] instant escalation email error: {exc}")
        return False


def _maybe_log_escalation(client_row: dict, question: str, reply: str) -> None:
    """If Lumia punted ('Ahmad will follow up'), log it AND email Ahmad instantly."""
    low = reply.lower()
    if not any(p in low for p in ESCALATION_PHRASES):
        return
    if not supabase_client:
        return
    sent = _send_instant_escalation_email(client_row, question, reply)
    try:
        supabase_client.table("client_escalations").insert({
            "client_id":          client_row.get("id"),
            "question":           question,
            "assistant_response": reply,
            # If the instant email went out, mark notified so the nightly digest skips it.
            "notified_at":        datetime.utcnow().isoformat() if sent else None,
        }).execute()
    except Exception as exc:
        print(f"[ClientChat] escalation log error: {exc}")


CLIENT_CHAT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ask Lumia — Ashrah Painting</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { height: 100%; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f5f7fb; color: #1a1a2e;
      display: flex; flex-direction: column;
    }
    header {
      background: #fff; border-bottom: 1px solid #e5e7eb;
      padding: 14px 20px; display: flex; align-items: center; gap: 14px;
    }
    header img { height: 48px; }
    header .titles {}
    header h1 { font-size: 17px; font-weight: 700; line-height: 1.2; }
    header .sub { color: #6b7280; font-size: 12px; margin-top: 2px; }
    #chat {
      flex: 1; overflow-y: auto; padding: 20px;
      max-width: 760px; width: 100%; margin: 0 auto;
    }
    .msg {
      margin: 12px 0; padding: 12px 16px; border-radius: 14px;
      max-width: 85%; line-height: 1.55; white-space: pre-wrap;
    }
    .msg.user  { background: #2563eb; color: #fff; margin-left: auto;
                 border-bottom-right-radius: 4px; }
    .msg.lumia { background: #fff; color: #1a1a2e; border: 1px solid #e5e7eb;
                 margin-right: auto; border-bottom-left-radius: 4px; }
    footer { background: #fff; border-top: 1px solid #e5e7eb; padding: 14px 20px; }
    .composer { max-width: 760px; margin: 0 auto; display: flex; gap: 10px; }
    .composer textarea {
      flex: 1; padding: 12px 14px; border: 1px solid #d1d5db; border-radius: 10px;
      font-size: 15px; resize: none; min-height: 44px; font-family: inherit;
    }
    .composer button {
      background: #2563eb; color: #fff; border: 0; padding: 0 20px;
      border-radius: 10px; font-size: 15px; font-weight: 600; cursor: pointer;
    }
    .composer button:disabled { opacity: .5; cursor: not-allowed; }
    .foot-note {
      text-align: center; color: #9ca3af; font-size: 11px;
      max-width: 760px; margin: 8px auto 0;
    }
  </style>
</head>
<body>
  <header>
    <img src="/static/logo.png" alt="Ashrah Painting">
    <div class="titles">
      <h1>Ask Lumia</h1>
      <div class="sub">{{ client_name }} &middot; Ashrah Painting</div>
    </div>
  </header>
  <div id="chat">
    <div class="msg lumia">Hi {{ first_name }} — I can answer questions about your project{{ site_suffix }}. What would you like to know?</div>
  </div>
  <footer>
    <form class="composer" id="f">
      <textarea id="m" placeholder="Ask about progress, schedule, next steps…" rows="1" autofocus></textarea>
      <button id="b" type="submit">Send</button>
    </form>
    <div class="foot-note">Lumia is an AI assistant. For scope or pricing, Ahmad follows up directly.</div>
  </footer>
<script>
const chat = document.getElementById('chat');
const form = document.getElementById('f');
const input = document.getElementById('m');
const btn = document.getElementById('b');
const token = "{{ token }}";

function append(role, text) {
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  d.textContent = text;
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return d;
}

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 140) + 'px';
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const msg = input.value.trim();
  if (!msg) return;
  append('user', msg);
  input.value = ''; input.style.height = '44px';
  btn.disabled = true;
  const thinking = append('lumia', '…');
  try {
    const r = await fetch('/api/client-lumia-chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({token: token, message: msg})
    });
    const data = await r.json();
    thinking.textContent = data.reply || '(no response)';
  } catch (err) {
    thinking.textContent = 'Something went wrong. Please try again.';
  } finally {
    btn.disabled = false;
    input.focus();
  }
});
</script>
</body>
</html>"""


@app.route("/client/<token>/ask", methods=["GET"])
def client_ask_page(token):
    row = _lookup_client_by_token(token)
    if not row:
        return "<h2 style='font-family:sans-serif;padding:40px;'>Link not valid.</h2>", 404
    if not _client_chat_enabled_for(row.get("client_email")):
        return ("<h2 style='font-family:sans-serif;padding:40px;'>"
                "Ask Lumia isn't enabled for your project yet.</h2>"), 403
    first = (row.get("client_name") or "").split()[0] or "there"
    kw = (row.get("site_keyword") or "").strip()
    site_suffix = f" at {kw}" if kw else ""
    resp = make_response(render_template_string(
        CLIENT_CHAT_HTML,
        client_name=row.get("client_name") or "",
        first_name=first,
        site_suffix=site_suffix,
        token=token,
    ))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/client-lumia-chat", methods=["POST"])
def api_client_lumia_chat():
    d = request.get_json(silent=True) or {}
    token   = (d.get("token") or "").strip()
    message = (d.get("message") or "").strip()
    if not token or not message:
        return jsonify({"reply": "Missing message."}), 400

    row = _lookup_client_by_token(token)
    if not row:
        return jsonify({"reply": "This link is no longer valid. Please contact Ahmad."}), 403
    if not _client_chat_enabled_for(row.get("client_email")):
        return jsonify({"reply": "Ask Lumia isn't enabled for your project yet."}), 403

    if _client_messages_today(row["id"]) >= CLIENT_RATE_LIMIT_PER_DAY:
        return jsonify({"reply":
            f"You've reached today's message limit. Please email Ahmad at {OWNER_EMAIL} "
            "and he'll be in touch."})

    context = _load_client_project_context(row)
    system_prompt = CLIENT_LUMIA_SYSTEM_PROMPT + "\n" + context

    _log_client_conversation(row["id"], "user", message)

    try:
        ai_client = _anthropic.Anthropic()
        resp = ai_client.messages.create(
            model=CLIENT_CHAT_MODEL,
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": message}],
        )
        reply = resp.content[0].text.strip()
    except Exception as exc:
        print(f"[ClientChat] model error: {exc}")
        return jsonify({"reply": "Sorry — I'm having trouble right now. "
                                  "Please email Ahmad directly and he'll follow up."})

    _log_client_conversation(row["id"], "assistant", reply)
    _maybe_log_escalation(row, message, reply)
    return jsonify({"reply": reply})


# ---------------------------------------------------------------------------
# STAFF LOGIN / LOGOUT  (managers & owner)
# ---------------------------------------------------------------------------
LOGIN_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lumia — Login</title>
<style>
* { box-sizing:border-box; margin:0; padding:0; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#eef1f7; min-height:100vh; display:flex;
       align-items:center; justify-content:center; padding:20px; }
.card { background:#fff; border-radius:16px; overflow:hidden;
        box-shadow:0 4px 24px rgba(0,0,0,.10); width:100%; max-width:400px; }
.header { background:#fff; text-align:center; padding:24px 20px 14px;
          border-bottom:3px solid #1F3864; }
.header img { width:140px; display:block; margin:0 auto 8px; }
.header p  { font-size:12px; color:#1F3864; font-weight:600; }
.body { padding:28px 24px; }
.field { margin-bottom:18px; }
.field label { display:block; font-size:11px; font-weight:700; color:#1F3864;
               text-transform:uppercase; letter-spacing:.8px; margin-bottom:6px; }
.field input, .field select {
  width:100%; padding:12px 14px; border:1.5px solid #dce2ef;
  border-radius:10px; font-size:15px; background:#fafbfd; outline:none; }
.field input:focus { border-color:#1F3864; }
.btn { width:100%; padding:14px; background:#1F3864; color:#fff; border:none;
       border-radius:10px; font-size:16px; font-weight:700; cursor:pointer;
       letter-spacing:.5px; margin-top:4px; }
.err { color:#d9534f; font-size:13px; margin-top:12px; text-align:center; }
.hint { font-size:12px; color:#999; text-align:center; margin-top:16px; }
</style></head><body>
<div class="card">
  <div class="header"><img src="/static/logo.png" alt="Ashrah Painting"><p>Staff Login</p></div>
  <div class="body">
    <form method="POST" action="/login">
      <input type="hidden" name="next" value="{{ next }}">
      <div class="field">
        <label>Your Name</label>
        <input type="text" name="name" placeholder="Enter your name" required>
      </div>
      <div class="field">
        <label>PIN</label>
        <input type="password" name="pin" placeholder="Enter your PIN" required>
      </div>
      <button class="btn" type="submit">Login</button>
      {% if error %}<p class="err">{{ error }}</p>{% endif %}
    </form>
    <p class="hint">Contact Ahmad if you forgot your PIN</p>
  </div>
</div>
</body></html>"""


@app.route("/login", methods=["GET", "POST"])
def login_page():
    next_url = request.args.get("next", "/owner")
    if request.method == "GET":
        return render_template_string(LOGIN_HTML, next=next_url, error="")
    name = request.form.get("name", "").strip()
    pin  = request.form.get("pin", "").strip()
    next_url = request.form.get("next", "/owner")
    # Check owner PIN
    if OWNER_PIN and pin == OWNER_PIN:
        session["role"] = "owner"
        session["name"] = name or "Ahmad"
        return redirect("/owner")
    # Check manager PINs in Supabase
    if supabase_client:
        try:
            res = supabase_client.table("managers").select("*").eq("pin", pin).eq("active", True).execute()
            managers = res.data or []
            match = next((m for m in managers if m["name"].lower() == name.lower()), None)
            if match:
                session["role"] = match["role"]
                session["name"] = match["name"]
                return redirect("/review" if match["role"] == "manager" else "/owner")
        except Exception as exc:
            print(f"[Login] Supabase error: {exc}")
    return render_template_string(LOGIN_HTML, next=next_url, error="Incorrect name or PIN. Try again.")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ---------------------------------------------------------------------------
# OWNER DASHBOARD
# ---------------------------------------------------------------------------
OWNER_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lumia — Owner Dashboard</title>
<style>
* { box-sizing:border-box; margin:0; padding:0; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#eef1f7; min-height:100vh; }
.topbar { background:#1F3864; color:#fff; padding:14px 24px;
          display:flex; align-items:center; justify-content:space-between; }
.topbar h1 { font-size:22px; font-weight:800; letter-spacing:2px; }
.topbar a  { color:#aac4ff; font-size:13px; text-decoration:none; }
.tabs { display:flex; background:#162d50; padding:0 24px; gap:4px; flex-wrap:wrap; }
.tab { padding:12px 20px; color:#aac4ff; font-size:13px; font-weight:600;
       cursor:pointer; border-bottom:3px solid transparent; }
.tab.active { color:#fff; border-bottom-color:#fff; }
.page { display:none; padding:24px; max-width:1100px; margin:0 auto; }
.page.active { display:block; }
.card { background:#fff; border-radius:12px; padding:20px 24px;
        box-shadow:0 2px 12px rgba(0,0,0,.07); margin-bottom:20px; }
.card h2 { font-size:16px; font-weight:700; color:#1F3864; margin-bottom:16px; }
.stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:16px; margin-bottom:20px; }
.stat { background:#fff; border-radius:12px; padding:20px;
        box-shadow:0 2px 12px rgba(0,0,0,.07); text-align:center; }
.stat .num { font-size:36px; font-weight:800; color:#1F3864; }
.stat .lbl { font-size:12px; color:#888; margin-top:4px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th { background:#f4f6fb; color:#1F3864; font-weight:700; padding:10px 12px;
     text-align:left; border-bottom:2px solid #e0e4ed; }
td { padding:10px 12px; border-bottom:1px solid #f0f2f7; vertical-align:top; }
tr:hover td { background:#fafbfd; }
.badge { display:inline-block; padding:3px 10px; border-radius:20px;
         font-size:11px; font-weight:700; }
.badge-green  { background:#d4edda; color:#2e7d32; }
.badge-yellow { background:#fff3cd; color:#856404; }
.badge-red    { background:#f8d7da; color:#721c24; }
.form-row { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }
.field label { display:block; font-size:11px; font-weight:700; color:#1F3864;
               text-transform:uppercase; letter-spacing:.8px; margin-bottom:6px; }
.field input, .field select, .field textarea {
  width:100%; padding:10px 12px; border:1.5px solid #dce2ef;
  border-radius:8px; font-size:14px; background:#fafbfd; outline:none; }
.field textarea { min-height:80px; resize:vertical; }
.btn { padding:10px 24px; background:#1F3864; color:#fff; border:none;
       border-radius:8px; font-size:14px; font-weight:700; cursor:pointer; }
.btn-sm { padding:6px 14px; font-size:12px; border-radius:6px; }
.btn-red { background:#d9534f; }
.btn-green { background:#4CAF50; }
.ai-result { background:#f4f6fb; border-left:4px solid #1F3864;
             padding:16px; border-radius:8px; margin-top:16px; white-space:pre-wrap;
             font-size:14px; line-height:1.6; }
.spinner { display:inline-block; width:14px; height:14px;
           border:2px solid rgba(255,255,255,.4); border-top-color:#fff;
           border-radius:50%; animation:spin .7s linear infinite;
           vertical-align:middle; margin-right:6px; }
@keyframes spin { to { transform:rotate(360deg); } }
</style></head><body>

<!-- Session-expired banner — hidden until apiFetch detects a non-JSON response -->
<div id="session-expired-banner" style="display:none;position:fixed;top:0;left:0;right:0;z-index:99999;
  background:#d9534f;color:#fff;padding:14px 24px;align-items:center;justify-content:space-between;
  font-size:14px;font-weight:500;box-shadow:0 2px 8px rgba(0,0,0,.2);">
  <span>⚠️ Your session expired — please log back in to continue.</span>
  <a href="/logout" style="color:#fff;font-weight:700;text-decoration:underline;margin-left:24px;">Log In Again</a>
</div>

<div class="topbar">
  <div style="display:flex;align-items:center;gap:12px;">
    <img src="/static/logo.png" alt="Ashrah Painting" style="height:38px;border-radius:6px;">
    <span style="font-size:13px;font-weight:600;opacity:.9;letter-spacing:.5px;">Owner Dashboard</span>
  </div>
  <div style="display:flex;gap:20px;align-items:center">
    <span style="font-size:13px;opacity:.8">Welcome, {{ name }}</span>
    <a href="/logout">Logout</a>
  </div>
</div>

<div class="tabs">
  <div class="tab active" onclick="showTab('overview')">Overview</div>
  <div class="tab" onclick="showTab('checkins')">Check-Ins</div>
  <div class="tab" onclick="showTab('reviews')">Reviews</div>
  <div class="tab" onclick="showTab('jobs')">Jobs</div>
  <div class="tab" onclick="showTab('employees')">Employees</div>
  <div class="tab" onclick="showTab('managers')">Managers</div>
  <div class="tab" onclick="showTab('clients')">Clients</div>
  <div class="tab" onclick="showTab('reports')">Reports</div>
  <div class="tab" onclick="showTab('sitevisits')">📍 Site Visits</div>
  <div class="tab" onclick="showTab('estimates')">📐 Estimates</div>
</div>

<!-- OVERVIEW -->
<div class="page active" id="tab-overview">
  <div class="stats">
    <div class="stat"><div class="num" id="stat-checkins">—</div><div class="lbl">Today's Check-Ins</div></div>
    <div class="stat"><div class="num" id="stat-jobs">—</div><div class="lbl">Open Jobs</div></div>
    <div class="stat"><div class="num" id="stat-employees">{{ employees|length }}</div><div class="lbl">Employees</div></div>
    <div class="stat"><div class="num" id="stat-avg">—</div><div class="lbl">Avg Score Today</div></div>
  </div>
  <div class="card">
    <h2>Recent Check-Ins</h2>
    <div id="overview-checkins"><p style="color:#999">Loading...</p></div>
  </div>
</div>

<!-- CHECK-INS -->
<div class="page" id="tab-checkins">
  <div class="card">
    <h2>All Check-Ins</h2>
    <div style="margin-bottom:16px;display:flex;gap:12px;flex-wrap:wrap">
      <input type="date" id="filter-date" style="padding:8px 12px;border:1.5px solid #dce2ef;border-radius:8px;font-size:14px">
      <select id="filter-emp" style="padding:8px 12px;border:1.5px solid #dce2ef;border-radius:8px;font-size:14px">
        <option value="">All Employees</option>
        {% for emp in employees %}
        <option value="{{ emp }}">{{ emp }}</option>
        {% endfor %}
      </select>
      <button class="btn btn-sm" onclick="loadCheckins()">Filter</button>
    </div>
    <div id="all-checkins"><p style="color:#999">Loading...</p></div>
  </div>
</div>

<!-- REVIEWS -->
<div class="page" id="tab-reviews">
  <div class="card">
    <h2>Manager Reviews</h2>
    <div style="margin-bottom:16px;display:flex;gap:12px;flex-wrap:wrap">
      <input type="date" id="review-filter-date" style="padding:8px 12px;border:1.5px solid #dce2ef;border-radius:8px;font-size:14px">
      <select id="review-filter-emp" style="padding:8px 12px;border:1.5px solid #dce2ef;border-radius:8px;font-size:14px">
        <option value="">All Employees</option>
        {% for emp in employees %}
        <option value="{{ emp }}">{{ emp }}</option>
        {% endfor %}
      </select>
      <select id="review-filter-trust" style="padding:8px 12px;border:1.5px solid #dce2ef;border-radius:8px;font-size:14px">
        <option value="">All Trust Levels</option>
        <option value="trusted">Trusted</option>
        <option value="watch">Watch</option>
        <option value="concern">Concern</option>
      </select>
      <button class="btn btn-sm" onclick="loadAllReviews()">Filter</button>
    </div>
    <div id="all-reviews-container"><p style="color:#999">Loading...</p></div>
  </div>
</div>

<!-- JOBS -->
<div class="page" id="tab-jobs">
  <div class="card">
    <h2>Create Job</h2>

    <!-- Step 1: Pick client -->
    <div id="job-step-1">
      <div class="field">
        <label>Step 1 — Select Client</label>
        <select id="job-client-select"
                style="width:100%;padding:12px 14px;border:1.5px solid #dce2ef;border-radius:10px;font-size:15px;background:#fafbfd;outline:none;">
          <option value="">Loading clients...</option>
        </select>
      </div>
      <div id="job-client-preview"
           style="display:none;background:#f4f6fb;border-radius:10px;padding:14px 16px;margin-top:4px;font-size:13px;color:#444;border-left:4px solid #1F3864;">
      </div>
      <div style="margin-top:14px;">
        <button type="button" class="btn" id="job-next-btn" onclick="jobStep2()" disabled>
          Next — Set Job Details →
        </button>
        <span style="font-size:12px;color:#888;margin-left:12px;">Client not listed?
          <a href="#" onclick="showTab('clients');return false;" style="color:#1F3864;">Add them in Clients tab first</a>
        </span>
      </div>
    </div>

    <!-- Step 2: Job details (hidden until client picked) -->
    <div id="job-step-2" style="display:none;margin-top:20px;border-top:1px solid #eee;padding-top:20px;">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap;">
        <div style="background:#d4edda;color:#2e7d32;padding:6px 14px;border-radius:20px;font-size:13px;font-weight:700;"
             id="job-client-badge"></div>
        <button type="button" onclick="jobBackToStep1()"
                style="background:none;border:none;color:#888;font-size:12px;cursor:pointer;text-decoration:underline;">
          ← Change client
        </button>
      </div>
      <form id="jobForm" onsubmit="return false">
        <input type="hidden" name="client_name">
        <input type="hidden" name="client_email">
        <input type="hidden" name="client_id">
        <div class="field">
          <label>Site Address <span style="font-weight:400;color:#888;font-size:11px;">— enter any address, even a new one for this client</span></label>
          <input type="text" name="site_address" id="job-site-address"
                 placeholder="e.g. 1777 Pembina Hwy, Winnipeg" required
                 oninput="checkNewAddress(this.value)">
          <div id="save-address-row" style="display:none;margin-top:8px;background:#f0f7ff;
               border-radius:8px;padding:10px 14px;font-size:13px;color:#1F3864;">
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-weight:600;">
              <input type="checkbox" id="register-address-cb" style="width:16px;height:16px;">
              Register this address for <span id="save-address-client-name"></span> so daily reports go out automatically
            </label>
          </div>
        </div>
        <div class="field"><label>Start Date</label>
          <input type="date" name="start_date"></div>
        <div class="form-row">
          <div class="field"><label>Painters Needed</label>
            <select name="painters_needed">
              <option value="1">1</option><option value="2" selected>2</option>
              <option value="3">3</option><option value="4">4</option>
            </select></div>
        </div>
        <div class="field"><label>Work Description</label>
          <textarea name="work_description" rows="3" placeholder="Describe the job scope, type of work, special requirements..."></textarea>
        </div>
        <div class="field">
          <label>Assign Employees <span style="font-weight:400;color:#888;font-size:12px;">(they will be emailed)</span></label>
          <div id="job-emp-list" style="display:flex;flex-wrap:wrap;gap:10px;padding:8px 0;min-height:44px;">
            <span style="color:#999;font-size:13px;">Loading employees...</span>
          </div>
        </div>
        <div id="job-msg" style="display:none;font-size:13px;padding:8px 14px;border-radius:8px;margin-bottom:10px;"></div>
        <div style="display:flex;gap:12px;flex-wrap:wrap;">
          <button type="button" class="btn btn-green" id="saveJobBtn" onclick="saveJob()">
            Save Job &amp; Notify
          </button>
          <button type="button" class="btn" id="aiBtn" onclick="getAIRec()">
            AI Crew Suggestion
          </button>
        </div>
      </form>
      <div id="ai-box" style="display:none;margin-top:16px;padding:16px;background:#f4f6fb;border-radius:10px;border:1px solid #dce2ef;">
        <h4 style="margin:0 0 8px;font-size:14px;color:#1F3864;">AI Recommendation</h4>
        <pre id="ai-text" style="white-space:pre-wrap;font-size:13px;color:#333;margin:0;"></pre>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Active Jobs</h2>
    <div id="jobs-list"><p style="color:#999">Loading...</p></div>
  </div>

  <div class="card">
    <h2>Assignment Notifications Log</h2>
    <p style="font-size:13px;color:#666;margin-bottom:14px;">Record of every crew assignment — including whether the client was notified by email.</p>
    <div id="assignment-log"><p style="color:#999;font-size:13px;">Loading...</p></div>
  </div>
</div>

<!-- EMPLOYEES -->
<div class="page" id="tab-employees">
  <div class="card">
    <h2>Register Employee</h2>
    <form id="employeeForm">
      <div class="form-row">
        <div class="field"><label>Full Name</label>
          <input type="text" name="emp_name" placeholder="e.g. Abdelhadi" required></div>
        <div class="field"><label>Email Address</label>
          <input type="email" name="emp_email" placeholder="employee@email.com" required></div>
      </div>
      <p style="font-size:12px;color:#888;margin-bottom:14px;">A setup email will be sent to the employee so they can create their own password.</p>
      <button type="button" class="btn" onclick="addEmployee()">Register & Send Setup Email</button>
    </form>
    <div id="emp-form-msg" style="margin-top:12px;font-size:13px;color:#2e7d32;"></div>
  </div>
  <div class="card">
    <h2>Registered Employees</h2>
    <div id="employees-list"><p style="color:#999">Loading...</p></div>
  </div>
</div>

<!-- REPORTS -->
<div class="page" id="tab-reports">

  <div class="card">
    <h2>Compose Client Email</h2>
    <p style="font-size:13px;color:#666;margin-bottom:16px;">Write a custom email to any client — Lumia drafts it using your job data. You preview before it sends. You are always CC'd.</p>
    <div class="form-row">
      <div class="field"><label>Client Name</label>
        <input type="text" id="compose-name" placeholder="e.g. Lloyd"></div>
      <div class="field"><label>Client Email</label>
        <input type="email" id="compose-email" placeholder="lloyd@email.com"></div>
    </div>
    <div class="field"><label>Notes for Lumia <span style="font-weight:400;color:#888;">(optional — job details, crew, anything extra)</span></label>
      <textarea id="compose-context" rows="2" placeholder="e.g. Assigned Abdelhadi and Ammar, starting Monday at 55 Waterford Commons..."></textarea>
    </div>
    <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;">
      <button class="btn" id="compose-preview-btn" onclick="previewCompose()">👁 Preview Email</button>
      <span id="compose-status" style="font-size:13px;color:#888;"></span>
    </div>
  </div>

  <div class="card">
    <h2>Send All Client Reports Now</h2>
    <p style="font-size:13px;color:#666;margin-bottom:16px;">
      Sends a consolidated daily report to every client who has check-ins today.
    </p>
    <button class="btn btn-green" id="sendAllBtn" onclick="sendAllReports()">&#128229; Send All Reports Now</button>
    <div id="send-all-msg" style="margin-top:12px;font-size:13px;"></div>
  </div>

  <div class="card">
    <h2>Preview &amp; Send Report</h2>
    <p style="font-size:13px;color:#666;margin-bottom:16px;">
      Preview the report before sending it to the client.
    </p>
    <div id="client-report-list"><p style="color:#999;font-size:13px;">Loading clients...</p></div>
  </div>

  <!-- Report preview modal -->
  <div id="report-preview-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);
       z-index:9999;overflow-y:auto;padding:24px;">
    <div style="background:#fff;border-radius:14px;max-width:740px;margin:0 auto;
                box-shadow:0 8px 40px rgba(0,0,0,.18);overflow:hidden;">
      <div style="background:#1F3864;color:#fff;padding:18px 24px;display:flex;align-items:center;justify-content:space-between;">
        <div>
          <div style="font-size:16px;font-weight:800;letter-spacing:1px;">REPORT PREVIEW</div>
          <div id="preview-modal-meta" style="font-size:12px;opacity:.8;margin-top:3px;"></div>
        </div>
        <button onclick="closePreview()" style="background:none;border:none;color:#fff;font-size:22px;cursor:pointer;line-height:1;">&#x2715;</button>
      </div>
      <div style="padding:0;max-height:68vh;overflow-y:auto;">
        <div id="preview-subject" style="padding:14px 24px 10px;font-size:14px;font-weight:700;
             color:#1F3864;border-bottom:1px solid #e0e4ed;"></div>
        <div id="preview-body" style="padding:20px 24px;font-size:13px;line-height:1.7;color:#222;"></div>
      </div>
      <div style="padding:16px 24px;border-top:1px solid #e0e4ed;display:flex;gap:12px;align-items:center;">
        <button id="preview-send-btn" class="btn btn-green" onclick="sendFromPreview()">
          &#128229; Send to Client Now
        </button>
        <button class="btn" style="background:#888;" onclick="closePreview()">Cancel</button>
        <span id="preview-send-msg" style="font-size:13px;color:#2e7d32;"></span>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Sent Reports History</h2>
    <p style="font-size:13px;color:#666;margin-bottom:14px;">Every report sent to a client — click to view the full email.</p>
    <div id="sent-reports-list"><p style="color:#999;font-size:13px;">Loading...</p></div>
  </div>

  <div class="card">
    <h2>Auto-Send Schedule</h2>
    <p style="font-size:13px;color:#666;margin-bottom:16px;">
      Reports currently auto-send at <strong id="current-schedule-time">loading...</strong> (Winnipeg time). Change the time below.
    </p>
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
      <input type="time" id="schedule-time-input"
             style="padding:10px 14px;border:1.5px solid #dce2ef;border-radius:8px;font-size:15px;">
      <button class="btn btn-green" onclick="saveSchedule()">Save Schedule</button>
    </div>
    <div id="schedule-msg" style="margin-top:12px;font-size:13px;"></div>
  </div>

</div>

<!-- SITE VISITS -->
<div class="page" id="tab-sitevisits">
  <div class="card">
    <h2>Active Jobs by Employee</h2>
    <p style="font-size:13px;color:#666;margin-bottom:16px;">When you visit a site, tap <strong>✓ At Work</strong> to confirm the employee is on-site. Employees can also mark their job done from their app.</p>
    <div id="sitevisits-list"><p style="color:#999;font-size:13px;">Loading...</p></div>
  </div>
  <div class="card">
    <h2>Site Visit Log</h2>
    <div id="sitevisits-log"><p style="color:#999;font-size:13px;">Loading...</p></div>
  </div>
</div>

<!-- MANAGERS -->
<div class="page" id="tab-managers">
  <div class="card">
    <h2>Add Manager</h2>
    <form id="managerForm">
      <div class="form-row">
        <div class="field"><label>Name</label>
          <input type="text" name="mgr_name" placeholder="Full name" required></div>
        <div class="field"><label>PIN (4–6 digits)</label>
          <input type="text" name="mgr_pin" placeholder="e.g. 4821" required maxlength="6"></div>
      </div>
      <div class="field"><label>Role</label>
        <select name="mgr_role">
          <option value="manager">Manager (review only)</option>
          <option value="owner">Owner (full access)</option>
        </select>
      </div>
      <button type="button" class="btn" onclick="addManager()">Add Manager</button>
    </form>
  </div>
  <div class="card">
    <h2>Current Managers</h2>
    <div id="managers-list"><p style="color:#999">Loading...</p></div>
  </div>
</div>

<!-- CLIENTS -->
<div class="page" id="tab-clients">
  <div class="card">
    <h2>Add Client (for automatic reports)</h2>
    <form id="clientForm">
      <div class="form-row">
        <div class="field"><label>Client Name</label>
          <input type="text" name="client_name" required></div>
        <div class="field"><label>Primary Email</label>
          <input type="email" name="client_email" required></div>
      </div>
      <div class="form-row">
        <div class="field"><label>Second Email <span style="color:#999;font-size:12px;">(optional — reports go to both)</span></label>
          <input type="email" name="client_email_2" placeholder="second.person@company.com"></div>
        <div class="field"><label>Site Address Keyword</label>
          <input type="text" name="site_keyword"
                 placeholder="e.g. '303-1689 pembina' — must appear in the site address"></div>
      </div>
      <button type="button" class="btn" onclick="addClient()">Save Client</button>
    </form>
  </div>
  <div class="card">
    <h2>Registered Clients</h2>
    <div id="clients-list"><p style="color:#999">Loading...</p></div>
  </div>

  <div class="card" style="background:#f0f7ff;border:1px solid #bfdbfe;">
    <h2 style="color:#1F3864;">Send Ask Lumia Invite (test)</h2>
    <p style="font-size:13px;color:#555;margin-bottom:14px;">
      Send any client a welcome email with their private Ask Lumia link. Works without needing check-ins today.
      <br>Client must be on the Ask Lumia allowlist (set via <code>CLIENT_CHAT_ALLOWED_EMAILS</code> env var).
    </p>
    <div class="form-row">
      <div class="field"><label>Client Name</label>
        <input type="text" id="invite-name" value="Khadija Jarkess"></div>
      <div class="field"><label>Client Email</label>
        <input type="email" id="invite-email" value="kayjarkess@gmail.com"></div>
    </div>
    <div class="field"><label>Site Keyword</label>
      <input type="text" id="invite-keyword" value="23 falcon"></div>
    <button type="button" class="btn" onclick="sendInvite()">Send Ask Lumia Invite</button>
    <div id="invite-result" style="margin-top:12px;font-size:14px;"></div>
  </div>
</div>

<!-- ESTIMATES -->
<div class="page" id="tab-estimates">
  <div class="card">
    <h2 style="margin-bottom:4px;">📐 Estimates</h2>
    <p style="font-size:13px;color:#555;margin-bottom:18px;">Upload architectural PDF drawings. Lumia extracts measurements and generates a full painting estimate and work order.</p>

    <!-- Upload form -->
    <div id="est-upload-panel" style="background:#f8f9fc;border:2px dashed #d0d7e8;border-radius:12px;padding:28px;text-align:center;margin-bottom:20px;">
      <div style="font-size:38px;margin-bottom:10px;">📄</div>
      <div style="font-size:15px;font-weight:600;color:#1F3864;margin-bottom:6px;">Drop PDF drawings here or click to browse</div>
      <div style="font-size:12px;color:#888;margin-bottom:18px;">Architectural floor plans, elevation sheets — any PDF with measurements</div>
      <div class="form-row" style="justify-content:center;gap:14px;margin-bottom:16px;">
        <div class="field" style="max-width:240px;">
          <label>Client Name (optional)</label>
          <input type="text" id="est-client-name" placeholder="e.g. Perry Wellington" style="padding:8px 12px;border:1.5px solid #dce2ef;border-radius:8px;font-size:13px;width:100%;">
        </div>
        <div class="field" style="max-width:280px;">
          <label>Site Address (optional)</label>
          <input type="text" id="est-site-address" placeholder="e.g. 123 Main St, Winnipeg" style="padding:8px 12px;border:1.5px solid #dce2ef;border-radius:8px;font-size:13px;width:100%;">
        </div>
      </div>
      <input type="file" id="est-file-input" accept="application/pdf" style="display:none;" onchange="handleEstimateFile(this)">
      <button class="btn" onclick="document.getElementById('est-file-input').click()">Choose PDF File</button>
    </div>

    <!-- Progress panel (hidden until job starts) -->
    <div id="est-progress-panel" style="display:none;margin-bottom:20px;">
      <div style="display:flex;align-items:center;gap:12px;padding:16px;background:#eef2fb;border-radius:10px;">
        <div id="est-spinner" style="width:20px;height:20px;border:3px solid #d0d7e8;border-top-color:#1F3864;border-radius:50%;animation:spin 0.8s linear infinite;flex-shrink:0;"></div>
        <div>
          <div style="font-weight:600;font-size:14px;color:#1F3864;" id="est-progress-title">Processing…</div>
          <div style="font-size:12px;color:#666;margin-top:2px;" id="est-progress-msg">Starting up…</div>
        </div>
      </div>
      <style>@keyframes spin{to{transform:rotate(360deg)}}</style>
    </div>

    <!-- Results panel (hidden until done) -->
    <div id="est-results-panel" style="display:none;">

      <!-- Measurement summary -->
      <div class="card" style="margin-bottom:16px;border-left:4px solid #1F3864;">
        <h3 style="margin:0 0 10px;font-size:15px;color:#1F3864;">📊 Extracted Measurements</h3>
        <div id="est-measurements-summary" style="font-size:13px;color:#444;"></div>
      </div>

      <!-- Paint calc rooms table -->
      <div class="card" style="margin-bottom:16px;">
        <h3 style="margin:0 0 12px;font-size:15px;color:#1F3864;">🖌 Painting Estimate</h3>
        <div id="est-scope" style="font-size:13px;color:#444;margin-bottom:12px;font-style:italic;"></div>
        <div id="est-rooms-table"></div>
        <div id="est-materials" style="margin-top:14px;"></div>
        <div id="est-labor" style="margin-top:14px;"></div>
        <div id="est-assumptions" style="margin-top:10px;font-size:12px;color:#888;"></div>
      </div>

      <!-- Work order -->
      <div class="card" style="margin-bottom:16px;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
          <h3 style="margin:0;font-size:15px;color:#1F3864;">📋 Work Order</h3>
          <button class="btn btn-sm" onclick="copyWorkOrder()">Copy</button>
        </div>
        <div id="est-work-order" style="font-size:13px;color:#333;line-height:1.7;white-space:pre-wrap;background:#f8f9fc;padding:16px;border-radius:8px;"></div>
      </div>

      <!-- Actions -->
      <div style="display:flex;gap:12px;flex-wrap:wrap;">
        <button class="btn" onclick="createJobFromEstimate()" id="est-create-job-btn">➕ Create Job from This Estimate</button>
        <button class="btn btn-sm" style="background:#f1f5ff;color:#1F3864;border:1.5px solid #d0d7e8;" onclick="resetEstimatesTab()">Upload Another PDF</button>
      </div>
      <div id="est-create-job-result" style="margin-top:12px;font-size:13px;"></div>
    </div>

    <!-- Error panel -->
    <div id="est-error-panel" style="display:none;padding:14px;background:#fff0f0;border-radius:8px;color:#c0392b;font-size:13px;margin-bottom:12px;">
      <strong>Error:</strong> <span id="est-error-msg"></span>
      <br><button class="btn btn-sm" style="margin-top:10px;" onclick="resetEstimatesTab()">Try Again</button>
    </div>

  </div>
</div>

<script>
let lastRecommendation = null;

function showTab(name) {
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.remove('active'));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  if (name === 'overview')   loadOverview();
  if (name === 'checkins')   loadCheckins();
  if (name === 'reviews')    loadAllReviews();
  if (name === 'jobs')       initJobsTab();
  if (name === 'employees')  loadEmployees();
  if (name === 'managers')   loadManagers();
  if (name === 'clients')    loadClients();
  if (name === 'reports')    initReportsTab();
  if (name === 'sitevisits') initSiteVisits();
  if (name === 'estimates')  initEstimatesTab();
}

function scoreColor(v) {
  if (v >= 8) return '#4CAF50'; if (v >= 5) return '#f0ad4e'; return '#d9534f';
}
function trustBadge(t) {
  if (t === 'trusted') return '<span class="badge badge-green">Trusted</span>';
  if (t === 'watch')   return '<span class="badge badge-yellow">Watch</span>';
  return '<span class="badge badge-red">Concern</span>';
}

// Global fetch helper — 10s timeout + session-expiry detection
async function apiFetch(url, opts) {
  const ctrl = new AbortController();
  const tid   = setTimeout(() => ctrl.abort(), 10000);
  let r;
  try {
    r = await fetch(url, { signal: ctrl.signal, ...(opts||{}) });
  } catch(e) {
    clearTimeout(tid);
    if (e.name === 'AbortError') throw new Error('timeout');
    throw e;
  }
  clearTimeout(tid);
  const ct = r.headers.get('content-type') || '';
  if (!ct.includes('application/json')) {
    const banner = document.getElementById('session-expired-banner');
    if (banner) banner.style.display = 'flex';
    throw new Error('session_expired');
  }
  return r;
}

async function loadOverview() {
  try {
    const r = await apiFetch('/api/checkins?limit=10');
    const d = r.ok ? await r.json() : [];
    const rows = d.map(c => `<tr>
      <td>${c.entry_date}</td><td><b>${c.worker_name}</b></td><td>${c.site_address}</td>
      <td><span style="font-weight:700;color:${scoreColor(c.avg_score)}">${c.avg_score}/10</span></td>
      <td>${(c.work_description||'').substring(0,60)}...</td></tr>`).join('');
    document.getElementById('overview-checkins').innerHTML = rows
      ? '<table><tr><th>Date</th><th>Employee</th><th>Site</th><th>Avg</th><th>Summary</th></tr>' + rows + '</table>'
      : '<p style="color:#999">No check-ins yet.</p>';
    const today = d.filter(c => c.entry_date === new Date().toISOString().split('T')[0]);
    document.getElementById('stat-checkins').textContent = today.length || '0';
    const avg = today.length ? (today.reduce((a,c) => a + (c.avg_score||0), 0) / today.length).toFixed(1) : '—';
    document.getElementById('stat-avg').textContent = avg;
  } catch(e) {
    const msg = e.message === 'session_expired' ? 'Session expired — log out and back in.'
              : e.message === 'timeout'         ? 'Request timed out — check your connection.'
              : 'Could not load data (' + e.message + ')';
    document.getElementById('overview-checkins').innerHTML =
      '<div style="color:#d9534f;padding:12px;background:#fff8f8;border-radius:8px;display:flex;align-items:center;gap:16px;">' +
      '<span>⚠ ' + msg + '</span>' +
      '<button class="btn btn-sm" onclick="loadOverview()" style="flex-shrink:0;">Retry</button>' +
      '</div>';
    document.getElementById('stat-checkins').textContent = '—';
  }
  try {
    const jr = await apiFetch('/api/jobs');
    const jd = jr.ok ? await jr.json() : [];
    document.getElementById('stat-jobs').textContent = jd.filter(j => j.status === 'open').length;
  } catch(e) {
    if (e.message !== 'session_expired') document.getElementById('stat-jobs').textContent = '—';
  }
}

async function loadCheckins() {
  const dt = document.getElementById('filter-date').value;
  const emp = document.getElementById('filter-emp').value;
  let url = '/api/checkins?limit=50';
  if (dt) url += '&date=' + dt; if (emp) url += '&employee=' + encodeURIComponent(emp);
  const r = await fetch(url); const d = await r.json();
  const rows = d.map(c => {
    const photos = (c.photo_urls||'').split(',').filter(u=>u.trim());
    const photoHtml = photos.length ? '<div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:4px">' + photos.map(u=>'<a href="'+u.trim()+'" target="_blank"><img src="'+u.trim()+'" style="width:40px;height:40px;object-fit:cover;border-radius:4px"><'+'/a>').join('') + '<'+'/div>' : '';
    return `<tr>
    <td>${c.entry_date}</td><td><b>${c.worker_name}</b></td><td>${c.site_address}</td>
    <td style="color:${scoreColor(c.avg_score)};font-weight:700">${c.avg_score}/10</td>
    <td>${(c.work_description||'').substring(0,80)}${photoHtml}</td>
    <td><button class="btn btn-sm" onclick="reviewCheckin('${c.id}','${c.worker_name}')">Review</button></td>
  </tr>`;
  }).join('');
  document.getElementById('all-checkins').innerHTML =
    '<table><tr><th>Date</th><th>Employee</th><th>Site</th><th>Score</th><th>Summary</th><th></th></tr>' + rows + '</table>';
}

function reviewCheckin(id, name) {
  window.location.href = '/review?checkin_id=' + id;
}

// ── JOBS TAB ────────────────────────────────────────────────────────────
let _cachedEmps = [];
let _jobs = [];

let _selectedClient = null;

async function initJobsTab() {
  await Promise.all([loadJobs(), loadEmpCheckboxes(), loadAssignmentLog(), loadJobClientPicker()]);
}

async function loadJobClientPicker() {
  const sel = document.getElementById('job-client-select');
  if (!sel) return;
  try {
    const clients = await fetch('/api/clients').then(r => r.json());
    if (!clients.length) {
      sel.innerHTML = '<option value="">No clients yet — add one in the Clients tab first</option>';
      return;
    }
    sel.innerHTML = '<option value="">— Select a client —</option>' +
      clients.map(c =>
        `<option value="${c.id}" data-name="${c.client_name}" data-email="${c.client_email}" data-keyword="${c.site_keyword}">
          ${c.client_name} (${c.site_keyword})
        </option>`
      ).join('');
    sel.onchange = function() {
      const opt = sel.options[sel.selectedIndex];
      const nextBtn = document.getElementById('job-next-btn');
      const preview = document.getElementById('job-client-preview');
      if (!opt.value) {
        nextBtn.disabled = true;
        preview.style.display = 'none';
        _selectedClient = null;
        return;
      }
      _selectedClient = {
        id:      opt.value,
        name:    opt.dataset.name,
        email:   opt.dataset.email,
        keyword: opt.dataset.keyword,
      };
      preview.style.display = 'block';
      preview.innerHTML = `<b>${_selectedClient.name}</b> &nbsp;|&nbsp; ${_selectedClient.email} &nbsp;|&nbsp; Site keyword: <code>${_selectedClient.keyword}</code>`;
      nextBtn.disabled = false;
    };
  } catch(e) {
    sel.innerHTML = '<option value="">Error loading clients</option>';
  }
}

function jobStep2() {
  if (!_selectedClient) return;
  document.getElementById('job-step-1').style.display = 'none';
  document.getElementById('job-step-2').style.display = 'block';
  document.getElementById('job-client-badge').textContent = '👤 ' + _selectedClient.name;
  // Fill hidden fields
  const form = document.getElementById('jobForm');
  form.querySelector('[name=client_name]').value  = _selectedClient.name;
  form.querySelector('[name=client_email]').value = _selectedClient.email;
  form.querySelector('[name=client_id]').value    = _selectedClient.id;
  // Pre-fill site address with keyword as hint
  const siteInput = form.querySelector('[name=site_address]');
  if (!siteInput.value) siteInput.placeholder = 'e.g. ' + _selectedClient.keyword;
}

function jobBackToStep1() {
  document.getElementById('job-step-2').style.display = 'none';
  document.getElementById('job-step-1').style.display = 'block';
}

function checkNewAddress(val) {
  if (!_selectedClient || !val.trim()) {
    document.getElementById('save-address-row').style.display = 'none';
    return;
  }
  // Show the register checkbox if the address isn't the same as the registered keyword
  const typed = val.trim().toLowerCase();
  const keyword = (_selectedClient.keyword || '').toLowerCase();
  const isNew = !typed.includes(keyword) && !keyword.includes(typed);
  const row = document.getElementById('save-address-row');
  row.style.display = isNew ? 'block' : 'none';
  const nameSpan = document.getElementById('save-address-client-name');
  if (nameSpan) nameSpan.textContent = _selectedClient.name;
}

async function loadAssignmentLog() {
  const el = document.getElementById('assignment-log');
  if (!el) return;
  try {
    const logs = await fetch('/api/assignment-log').then(r => r.json());
    if (!logs.length) { el.innerHTML = '<p style="color:#999;font-size:13px;">No assignments logged yet.</p>'; return; }
    const table = document.createElement('table');
    table.innerHTML = '<thead><tr><th>Date</th><th>Client</th><th>Site</th><th>Crew Assigned</th><th>Client Emailed</th></tr></thead>';
    const tbody = document.createElement('tbody');
    logs.forEach(r => {
      const tr = document.createElement('tr');
      const notified = r.client_notified
        ? '<span class="badge badge-green">Yes</span>'
        : '<span class="badge badge-red">No</span>';
      const crew = (r.assigned_crew || []).join(', ') || '—';
      const dt = r.notified_at ? new Date(r.notified_at).toLocaleString() : '—';
      tr.innerHTML = '<td>' + dt + '</td><td><b>' + (r.client_name||'—') + '</b></td>' +
        '<td>' + (r.site_address||'—') + '</td><td>' + crew + '</td><td>' + notified + '</td>';
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    el.innerHTML = '';
    el.appendChild(table);
  } catch(e) {
    el.innerHTML = '<p style="color:#c62828;font-size:13px;">Error loading log.</p>';
  }
}

async function loadEmpCheckboxes() {
  const box = document.getElementById('job-emp-list');
  if (!box) return;
  try {
    _cachedEmps = await fetch('/api/employees').then(r => r.json());
    const active = _cachedEmps.filter(e => e.active);
    if (!active.length) {
      box.innerHTML = '<span style="color:#c00;font-size:13px;">No active employees — register them in the Employees tab first</span>';
      return;
    }
    box.innerHTML = active.map(e =>
      '<label style="display:flex;align-items:center;gap:8px;padding:8px 14px;' +
      'border:1.5px solid #dce2ef;border-radius:8px;cursor:pointer;font-size:14px;' +
      'user-select:none;white-space:nowrap;background:#fff;">' +
      '<input type="checkbox" name="emp_cb" value="' + e.name + '" style="width:16px;height:16px;flex-shrink:0;cursor:pointer;"> ' +
      '<span>' + e.name + '</span></label>'
    ).join('');
  } catch(err) {
    box.innerHTML = '<span style="color:#c00;font-size:13px;">Could not load employees</span>';
  }
}

function checkedEmps(container) {
  return Array.from((container || document).querySelectorAll('input[name=emp_cb]:checked')).map(c => c.value);
}

function showJobMsg(text, ok) {
  const el = document.getElementById('job-msg');
  el.textContent = text;
  el.style.display = 'block';
  el.style.background = ok ? '#e8f5e9' : '#fce4ec';
  el.style.color = ok ? '#2e7d32' : '#c62828';
  setTimeout(() => { el.style.display = 'none'; }, 5000);
}

async function saveJob() {
  const form = document.getElementById('jobForm');
  const fd = Object.fromEntries(new FormData(form));
  if (!fd.client_name || !fd.site_address) { showJobMsg('Client name and site address are required.', false); return; }
  fd.assigned_employees = checkedEmps(document.getElementById('job-emp-list'));
  if (!fd.assigned_employees.length) { showJobMsg('Select at least one employee to assign.', false); return; }
  const btn = document.getElementById('saveJobBtn');
  btn.disabled = true; btn.textContent = 'Saving...';
  try {
    const r = await fetch('/api/save-job', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify(fd)});
    const d = await r.json();

    // If checkbox checked, also register the new address as a client site
    const registerCb = document.getElementById('register-address-cb');
    if (registerCb && registerCb.checked && _selectedClient) {
      const siteAddress = fd.site_address.trim().toLowerCase();
      await fetch('/api/add-client', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          client_name:  _selectedClient.name,
          client_email: _selectedClient.email,
          site_keyword: siteAddress,
        })
      });
      showJobMsg((d.message || 'Job saved!') + ' — New site registered for auto-reports ✓', true);
    } else {
      showJobMsg(d.message || 'Job saved!', true);
    }

    form.reset();
    document.querySelectorAll('#job-emp-list input').forEach(c => c.checked = false);
    document.getElementById('ai-box').style.display = 'none';
    document.getElementById('save-address-row').style.display = 'none';
    jobBackToStep1();
    loadJobs();
  } catch(e) { showJobMsg('Network error', false); }
  btn.disabled = false; btn.innerHTML = 'Save Job &amp; Notify';
}

async function getAIRec() {
  const form = document.getElementById('jobForm');
  const fd = Object.fromEntries(new FormData(form));
  const btn = document.getElementById('aiBtn');
  btn.innerHTML = '<span class="spinner"></span> Analysing...'; btn.disabled = true;
  try {
    const r = await fetch('/api/match-crew', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify(fd)});
    const d = await r.json();
    document.getElementById('ai-text').textContent = d.result;
    document.getElementById('ai-box').style.display = 'block';
  } catch(e) { showJobMsg('AI error', false); }
  btn.textContent = 'AI Crew Suggestion'; btn.disabled = false;
}

async function loadJobs() {
  const el = document.getElementById('jobs-list');
  _jobs = await fetch('/api/jobs').then(r => r.json()).catch(() => []);
  if (!_jobs.length) { el.innerHTML = '<p style="color:#999">No jobs yet.</p>'; return; }
  const rows = _jobs.map((j, idx) => {
    const emps = (j.assigned_employees || []).join(', ') || '—';
    const badge = j.status === 'open' ? 'badge-yellow' : 'badge-green';
    const tr = document.createElement('tr');
    tr.innerHTML = '<td><b>' + j.client_name + '</b></td>' +
      '<td>' + j.site_address + '</td>' +
      '<td>' + (j.start_date || '—') + '</td>' +
      '<td><span id="asgn-' + idx + '">' + emps + '</span></td>' +
      '<td><span class="badge ' + badge + '">' + j.status + '</span></td>' +
      '<td style="display:flex;gap:6px;flex-wrap:wrap;"></td>';
    const actions = tr.lastElementChild;
    const openBtn = document.createElement('button');
    openBtn.className = 'btn btn-sm';
    openBtn.textContent = 'Open';
    openBtn.onclick = function() { openJob(idx); };
    const assignBtn = document.createElement('button');
    assignBtn.className = 'btn btn-sm';
    assignBtn.textContent = 'Assign';
    assignBtn.onclick = function() { openAssign(idx); };
    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-sm';
    delBtn.style.cssText = 'background:#fce4ec;color:#c62828;border-color:#f48fb1;';
    delBtn.textContent = 'Delete';
    delBtn.onclick = function() { deleteJob(j.id, idx); };
    actions.appendChild(openBtn);
    actions.appendChild(assignBtn);
    actions.appendChild(delBtn);
    return tr;
  });
  const table = document.createElement('table');
  table.innerHTML = '<thead><tr><th>Client</th><th>Site</th><th>Start</th><th>Assigned</th><th>Status</th><th>Actions</th></tr></thead>';
  const tbody = document.createElement('tbody');
  rows.forEach(r => tbody.appendChild(r));
  table.appendChild(tbody);
  el.innerHTML = '';
  el.appendChild(table);
}

async function deleteJob(jobId, idx) {
  if (!confirm('Delete this job? This cannot be undone.')) return;
  const r = await fetch('/api/delete-job/' + jobId, {method:'POST'});
  const d = await r.json();
  if (d.ok) { _jobs.splice(idx, 1); loadJobs(); }
  else alert('Failed to delete job.');
}

async function openJob(idx) {
  if (document.getElementById('job-detail-modal')) return;
  const j = _jobs[idx];
  if (!j) return;
  const modal = document.createElement('div');
  modal.id = 'job-detail-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:flex-start;justify-content:center;z-index:9999;padding:24px;overflow-y:auto;';
  const panel = document.createElement('div');
  panel.style.cssText = 'background:#fff;border-radius:16px;padding:32px;width:100%;max-width:780px;position:relative;';
  panel.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:24px;">' +
    '<div><h2 style="margin:0 0 4px;font-size:22px;color:#1F3864;">' + j.client_name + '</h2>' +
    '<p style="margin:0;color:#666;font-size:14px;">📍 ' + j.site_address + '</p></div>' +
    '<button id="jd-close-btn" style="background:none;border:none;font-size:22px;cursor:pointer;color:#888;padding:0;">✕</button></div>' +

    '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:24px;">' +
    '<div style="background:#f4f6fb;border-radius:10px;padding:14px;text-align:center;">' +
    '<div id="jd-checkins" style="font-size:28px;font-weight:700;color:#1F3864;">—</div><div style="font-size:12px;color:#888;margin-top:4px;">Total Check-Ins</div></div>' +
    '<div style="background:#f4f6fb;border-radius:10px;padding:14px;text-align:center;">' +
    '<div id="jd-days" style="font-size:28px;font-weight:700;color:#1F3864;">—</div><div style="font-size:12px;color:#888;margin-top:4px;">Days Worked</div></div>' +
    '<div style="background:#f4f6fb;border-radius:10px;padding:14px;text-align:center;">' +
    '<div id="jd-avg" style="font-size:28px;font-weight:700;color:#1F3864;">—</div><div style="font-size:12px;color:#888;margin-top:4px;">Avg Score</div></div></div>' +

    '<div style="margin-bottom:20px;">' +
    '<h4 style="margin:0 0 8px;color:#1F3864;font-size:14px;">ASSIGNED CREW</h4>' +
    '<p style="margin:0;font-size:14px;">' + ((j.assigned_employees||[]).join(', ') || '—') + '</p></div>' +

    (j.work_description ? '<div style="margin-bottom:20px;"><h4 style="margin:0 0 8px;color:#1F3864;font-size:14px;">SCOPE OF WORK</h4>' +
    '<pre style="white-space:pre-wrap;font-size:13px;color:#333;background:#f9f9f9;border-radius:8px;padding:14px;margin:0;max-height:160px;overflow-y:auto;">' + j.work_description + '</pre></div>' : '') +

    '<h4 style="margin:0 0 12px;color:#1F3864;font-size:14px;">DAILY CHECK-INS</h4>' +
    '<div id="jd-checkins-list" style="font-size:13px;color:#999;">Loading...</div>';

  modal.appendChild(panel);
  document.body.appendChild(modal);
  panel.querySelector('#jd-close-btn').onclick = function() { modal.remove(); };
  modal.addEventListener('click', function(e) { if (e.target === modal) modal.remove(); });

  try {
    const res = await fetch('/api/job-report/' + j.id);
    const data = await res.json();
    const s = data.stats || {};
    document.getElementById('jd-checkins').textContent = s.total_checkins ?? '0';
    document.getElementById('jd-days').textContent = s.days_worked ?? '0';
    document.getElementById('jd-avg').textContent = s.avg_score != null ? s.avg_score + '/10' : '—';
    const checkins = data.checkins || [];
    const listEl = document.getElementById('jd-checkins-list');
    if (!checkins.length) { listEl.textContent = 'No check-ins yet for this job.'; return; }
    const rows = checkins.map(c => {
      const photos = (c.photo_urls||'').split(',').filter(u=>u.trim());
      const photoHtml = photos.length ? photos.map(u => '<a href="'+u.trim()+'" target="_blank"><img src="'+u.trim()+'" style="width:48px;height:48px;object-fit:cover;border-radius:6px;"></a>').join('') : '';
      return '<div style="border:1px solid #e8ecf4;border-radius:10px;padding:14px;margin-bottom:10px;">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">' +
        '<div><b>' + c.worker_name + '</b> <span style="color:#888;font-size:12px;">— ' + c.entry_date + '</span></div>' +
        '<span style="font-weight:700;font-size:16px;color:' + (c.avg_score>=8?'#2e7d32':c.avg_score>=5?'#f57c00':'#c62828') + ';">' + (c.avg_score||'—') + '/10</span></div>' +
        (c.work_description ? '<p style="margin:0 0 6px;font-size:13px;color:#444;">' + c.work_description + '</p>' : '') +
        (c.tomorrows_plan ? '<p style="margin:0 0 6px;font-size:12px;color:#888;">Tomorrow: ' + c.tomorrows_plan + '</p>' : '') +
        (photoHtml ? '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;">' + photoHtml + '</div>' : '') +
        '</div>';
    }).join('');
    listEl.innerHTML = rows;
  } catch(e) {
    document.getElementById('jd-checkins-list').textContent = 'Error loading report.';
  }
}

async function openAssign(idx) {
  if (document.getElementById('assign-modal')) return;
  const j = _jobs[idx];
  if (!j) return;
  const emps = _cachedEmps.length ? _cachedEmps : await fetch('/api/employees').then(r=>r.json()).catch(()=>[]);
  const current = j.assigned_employees || [];
  const active = emps.filter(e => e.active);
  const modal = document.createElement('div');
  modal.id = 'assign-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:9999;padding:20px;';
  const inner = document.createElement('div');
  inner.style.cssText = 'background:#fff;border-radius:14px;padding:28px 32px;min-width:280px;max-width:380px;width:100%;';
  inner.innerHTML = '<h3 style="margin:0 0 4px;font-size:17px;">Assign Employees</h3>' +
    '<p style="margin:0 0 16px;color:#666;font-size:13px;">' + j.client_name + '</p>' +
    '<div id="modal-boxes" style="display:flex;flex-direction:column;gap:8px;max-height:260px;overflow-y:auto;"></div>' +
    '<label style="display:flex;align-items:center;gap:8px;margin-top:16px;font-size:13px;color:#555;cursor:pointer;">' +
    '<input type="checkbox" id="modal-notify-client" checked style="width:15px;height:15px;cursor:pointer;">' +
    'Notify client by email</label>' +
    '<div style="display:flex;gap:12px;margin-top:14px;">' +
    '<button class="btn btn-green" id="modal-save-btn">Save</button>' +
    '<button class="btn" id="modal-cancel-btn">Cancel</button></div>';
  const boxes = inner.querySelector('#modal-boxes');
  active.forEach(e => {
    const label = document.createElement('label');
    label.style.cssText = 'display:flex;align-items:center;gap:8px;padding:8px 12px;border:1.5px solid #dce2ef;border-radius:8px;cursor:pointer;white-space:nowrap;background:#fff;';
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.name = 'emp_cb'; cb.value = e.name;
    cb.style.cssText = 'width:16px;height:16px;flex-shrink:0;cursor:pointer;';
    if (current.includes(e.name)) cb.checked = true;
    label.appendChild(cb);
    const span = document.createElement('span');
    span.textContent = e.name;
    label.appendChild(span);
    boxes.appendChild(label);
  });
  inner.querySelector('#modal-save-btn').onclick = function() { doAssign(j.id, idx); };
  inner.querySelector('#modal-cancel-btn').onclick = function() { modal.remove(); };
  modal.appendChild(inner);
  document.body.appendChild(modal);
}

async function doAssign(jobId, idx) {
  const selected = checkedEmps(document.getElementById('modal-boxes'));
  const notifyClient = document.getElementById('modal-notify-client')?.checked ?? true;
  const btn = document.querySelector('#assign-modal .btn-green');
  btn.disabled = true; btn.textContent = 'Saving...';
  try {
    const r = await fetch('/api/assign-employees', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({job_id: jobId, assigned_employees: selected, notify_client: notifyClient})});
    const d = await r.json();
    if (d.ok) {
      const label = document.getElementById('asgn-' + idx);
      if (label) label.textContent = selected.join(', ') || '—';
      if (_jobs[idx]) _jobs[idx].assigned_employees = selected;
      document.getElementById('assign-modal').remove();
      loadAssignmentLog();
      if (d.silent) {
        // silent — no popup needed, just a quick toast
        const t = document.createElement('div');
        t.textContent = 'Crew updated silently (client not notified).';
        t.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 22px;border-radius:20px;font-size:13px;z-index:9999;';
        document.body.appendChild(t); setTimeout(()=>t.remove(), 3000);
      } else if (d.emailed && d.emailed.length) {
        alert('Crew notified: ' + d.emailed.join(', ') + (d.client_notified ? ' | Client email sent.' : ' | Client not found.'));
      }
    } else { alert('Error: ' + (d.error || 'Failed')); }
  } catch(e) { alert('Network error'); }
}

async function loadEmployees() {
  const r = await fetch('/api/employees'); const d = await r.json();
  const el = document.getElementById('employees-list');
  if (!d.length) { el.innerHTML = '<p style="color:#999">No employees registered yet.</p>'; return; }
  el.innerHTML = '<table><thead><tr><th>Name</th><th>Email</th><th>Status</th><th>Action</th></tr></thead><tbody>' +
    d.map(e => `<tr>
      <td><b>${e.name}</b></td>
      <td>${e.email}</td>
      <td>${e.active ? '<span class="badge badge-green">Active</span>' : '<span class="badge badge-red">Inactive</span>'}</td>
      <td style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn btn-sm" onclick="resendInvite('${e.id}','${e.name}')">Resend Invite</button>
        ${e.active ? `<button class="btn btn-sm btn-red" onclick="removeEmployee('${e.id}')">Deactivate</button>` : ''}
        <button class="btn btn-sm" style="background:#fff;border:1.5px solid #e53935;color:#e53935;" onclick="deleteEmployee('${e.id}','${e.name}')">Delete</button>
      </td>
    </tr>`).join('') + '</tbody></table>';
}

async function addEmployee() {
  const f = document.getElementById('employeeForm');
  const d = Object.fromEntries(new FormData(f));
  const r = await fetch('/api/add-employee', { method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ name:d.emp_name, email:d.emp_email }) });
  const j = await r.json();
  document.getElementById('emp-form-msg').textContent = j.message;
  f.reset();
  loadEmployees();
}

async function removeEmployee(id) {
  if (!confirm('Deactivate this employee? They will no longer be able to log in.')) return;
  await fetch('/api/remove-employee/'+id, { method:'POST' });
  loadEmployees();
}

async function deleteEmployee(id, name) {
  if (!confirm('Permanently DELETE ' + name + '? This cannot be undone.')) return;
  if (!confirm('Final confirm: permanently delete ' + name + ' and all their records?')) return;
  const r = await fetch('/api/delete-employee/'+id, { method:'POST' });
  const d = await r.json();
  if (d.ok) { loadEmployees(); }
  else { alert('Delete failed: ' + (d.error || 'Unknown error')); }
}

async function resendInvite(id, name) {
  if (!confirm('Resend setup email to ' + name + '?')) return;
  const r = await fetch('/api/resend-invite', { method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ id }) });
  const j = await r.json();
  alert(j.message);
}

// ── REPORTS TAB ─────────────────────────────────────────────────────────────
// ── SITE VISITS ──────────────────────────────────────────────────────────────
async function initSiteVisits() {
  loadSiteVisitJobs();
  loadSiteVisitLog();
}

async function loadSiteVisitJobs() {
  const el = document.getElementById('sitevisits-list');
  try {
    const jobs = await fetch('/api/jobs').then(r => r.json());
    const open = jobs.filter(j => j.status === 'open');
    if (!open.length) { el.innerHTML = '<p style="color:#999;font-size:13px;">No open jobs.</p>'; return; }

    // Group by employee
    const byEmp = {};
    open.forEach(j => {
      (j.assigned_employees || ['Unassigned']).forEach(emp => {
        // dedupe
        const key = emp.trim();
        if (!byEmp[key]) byEmp[key] = [];
        if (!byEmp[key].find(x => x.id === j.id)) byEmp[key].push(j);
      });
    });

    el.innerHTML = Object.entries(byEmp).map(([emp, empJobs]) => `
      <div style="margin-bottom:20px;">
        <div style="font-size:13px;font-weight:700;color:#1F3864;text-transform:uppercase;
                    letter-spacing:.8px;margin-bottom:10px;padding-bottom:6px;
                    border-bottom:2px solid #e0e4ed;">👷 ${emp}</div>
        ${empJobs.map(j => `
          <div style="display:flex;align-items:center;justify-content:space-between;
                      padding:10px 14px;background:#f9fafb;border-radius:10px;
                      margin-bottom:8px;gap:12px;flex-wrap:wrap;">
            <div>
              <div style="font-weight:600;font-size:14px;">${j.client_name}</div>
              <div style="font-size:12px;color:#666;">${j.site_address} &bull; Start: ${j.start_date || 'TBD'}</div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
              <span id="sv-msg-${j.id}-${emp.replace(/\s/g,'_')}" style="font-size:12px;color:#2e7d32;"></span>
              <button class="btn btn-sm btn-green"
                onclick="confirmAtWork('${j.id}','${j.site_address.replace(/'/g,"\\'")}','${emp.replace(/'/g,"\\'")}', this)">
                ✓ At Work
              </button>
              <button class="btn btn-sm" style="background:#d9534f;"
                onclick="markJobDone('${j.id}', this)">
                ✅ Mark Done
              </button>
            </div>
          </div>`).join('')}
      </div>`).join('');
  } catch(e) {
    el.innerHTML = '<p style="color:#c62828;font-size:13px;">Error loading jobs.</p>';
  }
}

async function confirmAtWork(jobId, site, empName, btn) {
  btn.disabled = true; btn.textContent = '⏳...';
  try {
    const r = await fetch('/api/site-visit', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({job_id: jobId, site_address: site, employee_name: empName})
    });
    const j = await r.json();
    btn.textContent = '✓ Confirmed';
    btn.style.background = '#388e3c';
    const key = jobId + '-' + empName.replace(/\s/g,'_');
    const msg = document.getElementById('sv-msg-' + key);
    if (msg) { msg.textContent = 'Logged ' + new Date().toLocaleTimeString('en-CA',{hour:'2-digit',minute:'2-digit'}); }
    loadSiteVisitLog();
  } catch(e) { btn.disabled = false; btn.textContent = '✓ At Work'; }
}

async function markJobDone(jobId, btn) {
  if (!confirm('Mark this job as completed?')) return;
  btn.disabled = true; btn.textContent = '⏳...';
  try {
    const r = await fetch('/api/mark-job-done', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({job_id: jobId})
    });
    const j = await r.json();
    if (j.ok) { btn.textContent = '✅ Done'; btn.style.background = '#388e3c'; loadSiteVisitJobs(); }
    else { btn.disabled = false; btn.textContent = '✅ Mark Done'; }
  } catch(e) { btn.disabled = false; btn.textContent = '✅ Mark Done'; }
}

async function loadSiteVisitLog() {
  const el = document.getElementById('sitevisits-log');
  try {
    const rows = await fetch('/api/site-visits').then(r => r.json());
    if (!rows.length) { el.innerHTML = '<p style="color:#999;font-size:13px;">No site visits logged yet.</p>'; return; }
    el.innerHTML = '<table><tr><th>When</th><th>Employee</th><th>Site</th><th>Confirmed By</th></tr>' +
      rows.map(v => {
        const dt = v.visited_at ? new Date(v.visited_at).toLocaleString('en-CA',
          {timeZone:'America/Winnipeg',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
        return `<tr><td>${dt}</td><td><b>${v.employee_name}</b></td><td>${v.site_address}</td><td>${v.confirmed_by || '—'}</td></tr>`;
      }).join('') + '</table>';
  } catch(e) {
    el.innerHTML = '<p style="color:#c62828;font-size:13px;">Error loading log.</p>';
  }
}

async function initReportsTab() {
  loadReportSchedule();
  loadClientReportList();
  loadSentReports();
}

async function previewCompose() {
  const name    = document.getElementById('compose-name').value.trim();
  const email   = document.getElementById('compose-email').value.trim();
  const context = document.getElementById('compose-context').value.trim();
  const status  = document.getElementById('compose-status');
  const btn     = document.getElementById('compose-preview-btn');
  if (!email) { status.textContent = 'Enter a client email first.'; status.style.color='#c62828'; return; }
  btn.disabled = true; btn.textContent = '⏳ Drafting...';
  status.textContent = 'Lumia is writing the email…'; status.style.color = '#888';
  try {
    const r = await fetch('/api/compose-email', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({to_name: name, to_email: email, context, send_now: false}),
      signal: AbortSignal.timeout(60000)
    });
    const j = await r.json();
    if (j.ok) {
      _previewClient = {to_name: name, to_email: email, context, _compose: true};
      openPreview(name || email, email, j.subject, j.plain_body);
      status.textContent = '';
    } else {
      status.textContent = j.message || 'Error.'; status.style.color = '#c62828';
    }
  } catch(e) { status.textContent = 'Request timed out.'; status.style.color = '#c62828'; }
  btn.disabled = false; btn.textContent = '👁 Preview Email';
}

async function loadSentReports() {
  const el = document.getElementById('sent-reports-list');
  try {
    const rows = await fetch('/api/sent-reports').then(r => r.json());
    window._sentReports = rows;
    if (!rows.length) {
      el.innerHTML = '<p style="color:#999;font-size:13px;">No reports sent yet.</p>';
      return;
    }

    // Group by client_name + site_address
    const groups = {};
    rows.forEach((r, i) => {
      const key = (r.client_name || '—') + '||' + (r.site_address || '—');
      if (!groups[key]) groups[key] = { client_name: r.client_name, site_address: r.site_address, reports: [] };
      groups[key].reports.push({...r, _idx: i});
    });

    el.innerHTML = Object.values(groups).map(g => {
      const count = g.reports.length;
      const latest = g.reports[0];
      const latestDt = latest.sent_at
        ? new Date(latest.sent_at).toLocaleString('en-CA', {timeZone:'America/Winnipeg', month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'})
        : '—';

      const reportRows = g.reports.map(r => {
        const dt = r.sent_at
          ? new Date(r.sent_at).toLocaleString('en-CA', {timeZone:'America/Winnipeg', month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'})
          : '—';
        return `<div style="display:flex;align-items:center;justify-content:space-between;
                            padding:9px 14px;background:#fafbfd;border-radius:8px;
                            margin-bottom:6px;gap:10px;flex-wrap:wrap;">
          <div>
            <span style="font-size:13px;font-weight:600;color:#333;">${dt}</span><br>
            <span style="font-size:12px;color:#888;">${r.subject || '—'}</span>
          </div>
          <button class="btn btn-sm" onclick="viewSentReport(${r._idx})"
                  style="background:#1F3864;flex-shrink:0;">View</button>
        </div>`;
      }).join('');

      const groupId = 'rg-' + Math.random().toString(36).slice(2,8);
      return `
        <div style="margin-bottom:16px;border:1.5px solid #e0e4ed;border-radius:12px;overflow:hidden;">
          <div style="display:flex;align-items:center;justify-content:space-between;
                      padding:13px 16px;background:#f4f6fb;cursor:pointer;gap:12px;flex-wrap:wrap;"
               onclick="toggleReportGroup('${groupId}')">
            <div>
              <span style="font-weight:700;font-size:15px;color:#1F3864;">${g.client_name}</span>
              <span style="font-size:12px;color:#666;margin-left:10px;">${g.site_address}</span>
            </div>
            <div style="display:flex;align-items:center;gap:10px;">
              <span style="font-size:12px;color:#888;">${count} report${count>1?'s':''} &bull; Last: ${latestDt}</span>
              <span id="arr-${groupId}" style="font-size:16px;color:#1F3864;">▼</span>
            </div>
          </div>
          <div id="${groupId}" style="padding:12px 14px 6px;">
            ${reportRows}
          </div>
        </div>`;
    }).join('');
  } catch(e) {
    el.innerHTML = '<p style="color:#c62828;font-size:13px;">Error loading history.</p>';
  }
}

function toggleReportGroup(id) {
  const el  = document.getElementById(id);
  const arr = document.getElementById('arr-' + id);
  const open = el.style.display !== 'none';
  el.style.display  = open ? 'none' : 'block';
  arr.textContent   = open ? '▶' : '▼';
}

function viewSentReport(i) {
  const r = (window._sentReports || [])[i];
  if (!r) return;
  const dt = r.sent_at ? new Date(r.sent_at).toLocaleString('en-CA', {timeZone:'America/Winnipeg'}) : '';
  openPreview(r.client_name + (dt ? '  •  ' + dt : ''), r.client_email, r.subject, r.plain_body);
  // Hide the send button — this is a view of an already-sent report
  document.getElementById('preview-send-btn').style.display = 'none';
  _previewClient = null;
}

async function sendAllReports() {
  const btn = document.getElementById('sendAllBtn');
  const msg = document.getElementById('send-all-msg');
  btn.disabled = true; btn.textContent = 'Sending...';
  msg.textContent = ''; msg.style.color = '#2e7d32';
  try {
    const r = await fetch('/api/send-daily-reports', { method: 'POST' });
    const j = await r.json();
    msg.textContent = j.message;
  } catch(e) { msg.textContent = 'Network error.'; msg.style.color = '#c62828'; }
  btn.disabled = false; btn.innerHTML = '&#128229; Send All Reports Now';
}

let _previewClient = null;

async function loadClientReportList() {
  const el = document.getElementById('client-report-list');
  try {
    const clients = await fetch('/api/clients').then(r => r.json());
    if (!clients.length) {
      el.innerHTML = '<p style="color:#999;font-size:13px;">No clients registered yet. Add them in the Clients tab.</p>';
      return;
    }
    el.innerHTML = '';
    clients.forEach(c => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:14px 0;border-bottom:1px solid #eee;gap:12px;flex-wrap:wrap;';
      row.innerHTML = '<div><b>' + c.client_name + '</b><br><span style="font-size:12px;color:#888;">' + c.client_email + ' &bull; ' + c.site_keyword + '</span></div>';
      const previewBtn = document.createElement('button');
      previewBtn.className = 'btn btn-sm';
      previewBtn.style.background = '#1F3864';
      previewBtn.textContent = '👁 Preview Report';
      const statusEl = document.createElement('span');
      statusEl.style.cssText = 'font-size:12px;color:#888;';
      previewBtn.onclick = async function() {
        previewBtn.disabled = true; previewBtn.textContent = '⏳ Generating...';
        statusEl.textContent = 'AI is writing the report…';
        try {
          const r = await fetch('/api/preview-report', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({client_name: c.client_name, client_email: c.client_email, site_keyword: c.site_keyword}),
            signal: AbortSignal.timeout(280000)
          });
          const j = await r.json();
          if (j.ok) {
            _previewClient = {client_name: c.client_name, client_email: c.client_email, site_keyword: c.site_keyword};
            openPreview(c.client_name, c.client_email, j.subject, j.plain_body);
            statusEl.textContent = '';
          } else {
            statusEl.textContent = j.message || 'Error generating preview.';
            statusEl.style.color = '#c62828';
          }
        } catch(e) { statusEl.textContent = 'Request timed out — try again.'; statusEl.style.color = '#c62828'; }
        previewBtn.disabled = false; previewBtn.textContent = '👁 Preview Report';
      };
      const right = document.createElement('div');
      right.style.cssText = 'display:flex;align-items:center;gap:10px;flex-wrap:wrap;';
      right.appendChild(previewBtn);
      right.appendChild(statusEl);
      row.appendChild(right);
      el.appendChild(row);
    });
  } catch(e) {
    el.innerHTML = '<p style="color:#c62828;font-size:13px;">Error loading clients.</p>';
  }
}

function openPreview(clientName, clientEmail, subject, body) {
  document.getElementById('preview-modal-meta').textContent = clientEmail ? 'To: ' + clientName + ' <' + clientEmail + '>' : clientName;
  document.getElementById('preview-subject').textContent = 'Subject: ' + subject;
  document.getElementById('preview-body').textContent = body;
  document.getElementById('preview-send-msg').textContent = '';
  const sendBtn = document.getElementById('preview-send-btn');
  sendBtn.style.display = '';
  sendBtn.disabled = false;
  sendBtn.textContent = '📨 Send to Client Now';
  document.getElementById('report-preview-modal').style.display = 'block';
  document.body.style.overflow = 'hidden';
}

function closePreview() {
  document.getElementById('report-preview-modal').style.display = 'none';
  document.body.style.overflow = '';
}

async function sendFromPreview() {
  if (!_previewClient) return;
  const btn = document.getElementById('preview-send-btn');
  const msg = document.getElementById('preview-send-msg');
  btn.disabled = true; btn.textContent = '⏳ Sending...';
  msg.textContent = '';
  try {
    const isCompose = _previewClient._compose;
    const url  = isCompose ? '/api/compose-email' : '/api/send-client-report';
    const body = isCompose
      ? {..._previewClient, send_now: true}
      : _previewClient;
    const r = await fetch(url, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(280000)
    });
    const j = await r.json();
    msg.textContent = j.message;
    msg.style.color = j.ok ? '#2e7d32' : '#c62828';
    if (j.ok) { btn.textContent = '✓ Sent'; loadSentReports(); }
    else { btn.disabled = false; btn.textContent = '📨 Send to Client Now'; }
  } catch(e) { msg.textContent = 'Request timed out.'; msg.style.color = '#c62828'; btn.disabled = false; btn.textContent = '📨 Send to Client Now'; }
}

async function loadReportSchedule() {
  try {
    const j = await fetch('/api/report-schedule').then(r => r.json());
    const display = document.getElementById('current-schedule-time');
    const input   = document.getElementById('schedule-time-input');
    if (display) display.textContent = j.time || '18:00';
    if (input)   input.value = j.time || '18:00';
  } catch(e) {}
}

async function saveSchedule() {
  const input = document.getElementById('schedule-time-input');
  const msg   = document.getElementById('schedule-msg');
  const time  = input.value;
  if (!time) { msg.textContent = 'Please pick a time.'; msg.style.color = '#c62828'; return; }
  msg.textContent = 'Saving...'; msg.style.color = '#666';
  try {
    const r = await fetch('/api/report-schedule', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ time })
    });
    const j = await r.json();
    msg.textContent = j.message;
    msg.style.color = j.ok ? '#2e7d32' : '#c62828';
    if (j.ok) document.getElementById('current-schedule-time').textContent = time;
  } catch(e) { msg.textContent = 'Network error.'; msg.style.color = '#c62828'; }
}

async function loadManagers() {
  const r = await fetch('/api/managers'); const d = await r.json();
  if (!d.length) { document.getElementById('managers-list').innerHTML = '<p style="color:#999">No managers added yet.</p>'; return; }
  const rows = d.map(m => `<tr>
    <td><b>${m.name}</b></td>
    <td><span class="badge ${m.role==='owner'?'badge-green':'badge-yellow'}">${m.role}</span></td>
    <td><span class="badge ${m.active?'badge-green':'badge-red'}">${m.active?'Active':'Inactive'}</span></td>
    <td><button class="btn btn-sm btn-red" onclick="removeManager('${m.id}')">Remove</button></td>
  </tr>`).join('');
  document.getElementById('managers-list').innerHTML =
    '<table><tr><th>Name</th><th>Role</th><th>Status</th><th></th></tr>' + rows + '</table>';
}

async function addManager() {
  const form = document.getElementById('managerForm');
  const data = Object.fromEntries(new FormData(form));
  const r = await fetch('/api/add-manager', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify(data)});
  const d = await r.json();
  alert(d.message); form.reset(); loadManagers();
}

async function removeManager(id) {
  if (!confirm('Remove this manager?')) return;
  await fetch('/api/remove-manager/' + id, {method:'POST'});
  loadManagers();
}

async function loadClients() {
  const r = await fetch('/api/clients'); const d = await r.json();
  if (!d.length) { document.getElementById('clients-list').innerHTML = '<p style="color:#999">No clients registered yet.</p>'; return; }
  const rows = d.map(c => `<tr>
    <td><b>${c.client_name}</b></td>
    <td>${c.client_email}${c.client_email_2 ? '<br><span style="color:#666;font-size:12px;">+ ' + c.client_email_2 + '</span>' : ''}</td>
    <td><code>${c.site_keyword}</code></td>
    <td><button class="btn btn-sm btn-red" onclick="removeClient('${c.id}')">Remove</button></td>
  </tr>`).join('');
  document.getElementById('clients-list').innerHTML =
    '<table><tr><th>Name</th><th>Email(s)</th><th>Keyword</th><th></th></tr>' + rows + '</table>';
}

async function addClient() {
  const form = document.getElementById('clientForm');
  const data = Object.fromEntries(new FormData(form));
  const r = await fetch('/api/add-client', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify(data)});
  const d = await r.json();
  alert(d.message); form.reset(); loadClients();
}

async function removeClient(id) {
  if (!confirm('Remove this client?')) return;
  await fetch('/api/remove-client/' + id, {method:'POST'});
  loadClients();
}

async function sendInvite() {
  const name  = document.getElementById('invite-name').value.trim();
  const email = document.getElementById('invite-email').value.trim();
  const kw    = document.getElementById('invite-keyword').value.trim();
  const out   = document.getElementById('invite-result');
  if (!email) { out.innerHTML = '<span style="color:#d9534f;">Client email required.</span>'; return; }
  out.innerHTML = '<span style="color:#666;">Sending…</span>';
  try {
    const r = await fetch('/api/send-client-test-invite', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({client_name: name, client_email: email, site_keyword: kw}),
    });
    const d = await r.json();
    out.innerHTML = d.ok
      ? '<span style="color:#2e7d32;">&#10003; ' + d.message + '</span>'
      : '<span style="color:#d9534f;">&#10005; ' + d.message + '</span>';
  } catch (e) {
    out.innerHTML = '<span style="color:#d9534f;">Error: ' + e + '</span>';
  }
}

async function loadAllReviews() {
  const dt    = document.getElementById('review-filter-date').value;
  const emp   = document.getElementById('review-filter-emp').value;
  const trust = document.getElementById('review-filter-trust').value;
  let url = '/api/all-reviews?limit=100';
  if (dt)    url += '&date=' + dt;
  if (emp)   url += '&employee=' + encodeURIComponent(emp);
  if (trust) url += '&trust=' + trust;
  const r = await fetch(url); const d = await r.json();
  if (!d.length) {
    document.getElementById('all-reviews-container').innerHTML =
      '<p style="color:#999;text-align:center;padding:30px">No reviews found.</p>';
    return;
  }
  function trustBadge(t) {
    if (t==='trusted') return '<span class="badge badge-green">✓ Trusted</span>';
    if (t==='watch')   return '<span class="badge badge-yellow">⚠ Watch</span>';
    return '<span class="badge badge-red">✗ Concern</span>';
  }
  const rows = d.map(r => `<tr>
    <td>${r.entry_date||'—'}</td>
    <td><b>${r.worker_name||'—'}</b></td>
    <td>${r.site_address||'—'}</td>
    <td style="font-weight:700;color:${scoreColor(r.avg_score)}">${r.avg_score||'—'}/10</td>
    <td style="font-weight:700;color:${scoreColor(r.accuracy_score)}">${r.accuracy_score||'—'}/10</td>
    <td>${trustBadge(r.trust_level)}</td>
    <td style="font-size:12px;color:#555">${r.reviewer_name||'—'}</td>
    <td style="font-size:13px">${r.notes||'—'}</td>
  </tr>`).join('');
  document.getElementById('all-reviews-container').innerHTML =
    `<table><tr>
      <th>Date</th><th>Employee</th><th>Site</th>
      <th>Self Score</th><th>Accuracy</th><th>Trust</th>
      <th>Reviewed By</th><th>Notes</th>
    </tr>${rows}</table>`;
}

loadOverview();
</script>

<style>
.lumia-fab { position:fixed; bottom:28px; right:20px; width:56px; height:56px;
  background:#1F3864; color:#fff; border:none; border-radius:50%;
  font-size:24px; cursor:pointer; box-shadow:0 4px 16px rgba(31,56,100,.35);
  display:flex; align-items:center; justify-content:center; z-index:1000; transition:transform .2s; }
.lumia-fab:hover { transform:scale(1.1); }
.lumia-panel { position:fixed; bottom:96px; right:16px; width:min(360px,calc(100vw - 32px));
  background:#fff; border-radius:16px; box-shadow:0 8px 32px rgba(0,0,0,.18);
  z-index:999; overflow:hidden; display:none; flex-direction:column; }
.lumia-panel.open { display:flex; }
.lumia-panel-header { background:#1F3864; color:#fff; padding:14px 16px;
  display:flex; align-items:center; justify-content:space-between; }
.lumia-panel-header h3 { font-size:15px; font-weight:700; letter-spacing:1px; }
.lumia-panel-close { background:none; border:none; color:#fff; font-size:20px; cursor:pointer; }
.lumia-messages { flex:1; max-height:260px; overflow-y:auto; padding:12px; }
.lumia-msg { margin-bottom:10px; }
.lumia-msg .bubble { display:inline-block; padding:9px 13px; border-radius:12px;
  font-size:13px; line-height:1.5; max-width:90%; }
.lumia-msg.user .bubble { background:#1F3864; color:#fff; float:right; border-radius:12px 12px 2px 12px; }
.lumia-msg.lumia .bubble { background:#f4f6fb; color:#333; border-radius:12px 12px 12px 2px; }
.lumia-msg::after { content:''; display:block; clear:both; }
.lumia-input-row { padding:10px 12px; border-top:1px solid #eee; display:flex; gap:8px; align-items:center; }
.lumia-input-row input { flex:1; padding:9px 12px; border:1.5px solid #dce2ef;
  border-radius:20px; font-size:14px; outline:none; }
.lumia-input-row input:focus { border-color:#1F3864; }
.lumia-send-btn { background:#1F3864; color:#fff; border:none; border-radius:50%;
  width:36px; height:36px; font-size:16px; cursor:pointer; display:flex; align-items:center; justify-content:center; }
.lumia-mic-btn { background:none; border:2px solid #1F3864; border-radius:50%;
  width:36px; height:36px; font-size:16px; cursor:pointer; display:flex; align-items:center; justify-content:center; }
.lumia-mic-btn.recording { background:#d9534f; border-color:#d9534f; color:#fff; }
.lumia-status { font-size:11px; color:#999; text-align:center; padding:4px; }
</style>

<button class="lumia-fab" onclick="toggleLumiaPanel()" title="Talk to Lumia">&#129302;</button>
<div class="lumia-panel" id="lumiaPanel">
  <div class="lumia-panel-header">
    <h3>&#129302; LUMIA</h3>
    <button class="lumia-panel-close" onclick="toggleLumiaPanel()">&#10005;</button>
  </div>
  <div class="lumia-messages" id="lumiaMessages">
    <div class="lumia-msg lumia">
      <div class="bubble">Hi! I'm Lumia, your operations assistant. Ask me about employees, jobs, reports, or anything work-related.</div>
    </div>
  </div>
  <div class="lumia-status" id="lumiaStatus"></div>
  <div class="lumia-input-row">
    <button class="lumia-mic-btn" id="lumiaMicBtn" onclick="toggleLumiaMic()" title="Speak">&#127908;</button>
    <input type="text" id="lumiaInput" placeholder="Ask Lumia anything..." onkeydown="if(event.key==='Enter')sendLumiaMsg()">
    <button class="lumia-send-btn" onclick="sendLumiaMsg()">&#10148;</button>
  </div>
</div>

<script>
let lumiaPanelOpen = false;
let lumiaMicRec = null;

function toggleLumiaPanel() {
  lumiaPanelOpen = !lumiaPanelOpen;
  document.getElementById('lumiaPanel').classList.toggle('open', lumiaPanelOpen);
  if (lumiaPanelOpen) document.getElementById('lumiaInput').focus();
}

function appendLumiaMsg(role, text) {
  var msgs = document.getElementById('lumiaMessages');
  var div = document.createElement('div');
  div.className = 'lumia-msg ' + role;
  var safe = text;
  try { safe = text.replace(new RegExp(String.fromCharCode(60),'g'),'&lt;').replace(new RegExp(String.fromCharCode(10),'g'),'<br>'); } catch(e){}
  div.innerHTML = '<div class="bubble">' + safe + '<'+'/div>';
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}

async function sendLumiaMsg() {
  var input = document.getElementById('lumiaInput');
  var text = input.value.trim();
  if (!text) return;
  input.value = '';
  appendLumiaMsg('user', text);
  document.getElementById('lumiaStatus').textContent = 'Lumia is thinking...';
  try {
    var res = await fetch('/api/lumia-chat', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ message: text })
    });
    var d = await res.json();
    appendLumiaMsg('lumia', d.reply || 'Sorry, I could not respond right now.');
  } catch(e) {
    appendLumiaMsg('lumia', 'Connection error. Please try again.');
  }
  document.getElementById('lumiaStatus').textContent = '';
}

function toggleLumiaMic() {
  var SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRec) { alert('Voice not supported in this browser.'); return; }
  var btn = document.getElementById('lumiaMicBtn');
  if (lumiaMicRec) { lumiaMicRec.stop(); return; }
  var rec = new SpeechRec();
  rec.lang = 'en-US';
  rec.continuous = false;
  rec.interimResults = false;
  btn.classList.add('recording');
  lumiaMicRec = rec;
  rec.onresult = function(e) {
    document.getElementById('lumiaInput').value = e.results[0][0].transcript;
    sendLumiaMsg();
  };
  rec.onend = function() { btn.classList.remove('recording'); lumiaMicRec = null; };
  rec.onerror = function() { btn.classList.remove('recording'); lumiaMicRec = null; };
  rec.start();
}
</script>
</body></html>"""


@app.route("/owner")
@require_role("owner")
def owner_dashboard():
    resp = make_response(render_template_string(OWNER_HTML, name=session.get("name","Ahmad"), employees=EMPLOYEES))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


# ---------------------------------------------------------------------------
# MANAGER REVIEW PAGE
# ---------------------------------------------------------------------------
REVIEW_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lumia — Review</title>
<style>
* { box-sizing:border-box; margin:0; padding:0; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#eef1f7; min-height:100vh; }
.topbar { background:#1F3864; color:#fff; padding:14px 24px;
          display:flex; align-items:center; justify-content:space-between; }
.topbar h1 { font-size:20px; font-weight:800; letter-spacing:2px; }
.topbar a  { color:#aac4ff; font-size:13px; text-decoration:none; }
.content { max-width:800px; margin:24px auto; padding:0 16px; }
.card { background:#fff; border-radius:12px; padding:20px 24px;
        box-shadow:0 2px 12px rgba(0,0,0,.07); margin-bottom:20px; }
.emp-name { font-size:18px; font-weight:700; color:#1F3864; }
.meta { font-size:12px; color:#888; margin-top:2px; }
.scores-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:14px 0; }
.score-item { background:#f4f6fb; border-radius:8px; padding:10px;
              text-align:center; }
.score-item .val { font-size:22px; font-weight:800; }
.score-item .lbl { font-size:10px; color:#666; margin-top:2px; }
.summary { background:#f9f9f9; border-left:3px solid #1F3864;
           padding:10px 14px; border-radius:4px; font-size:14px;
           line-height:1.5; margin:10px 0; }
.section-label { font-size:11px; font-weight:700; color:#1F3864;
                 text-transform:uppercase; letter-spacing:.8px; margin-bottom:8px; }
.slider-row { margin-bottom:14px; }
.slider-row .top { display:flex; justify-content:space-between; margin-bottom:4px; }
.slider-row input[type=range] { width:100%; accent-color:#1F3864; }
.badge-row { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
.trust-btn { padding:8px 20px; border:2px solid #ddd; border-radius:20px;
             background:#fff; font-size:13px; font-weight:600; cursor:pointer; }
.trust-btn.active-trusted { background:#d4edda; border-color:#4CAF50; color:#2e7d32; }
.trust-btn.active-watch   { background:#fff3cd; border-color:#f0ad4e; color:#856404; }
.trust-btn.active-concern { background:#f8d7da; border-color:#d9534f; color:#721c24; }
textarea { width:100%; padding:10px 12px; border:1.5px solid #dce2ef;
           border-radius:8px; font-size:14px; min-height:80px; resize:vertical;
           background:#fafbfd; outline:none; }
textarea:focus { border-color:#1F3864; }
.btn { padding:10px 28px; background:#1F3864; color:#fff; border:none;
       border-radius:8px; font-size:14px; font-weight:700; cursor:pointer; }
.reviewed-tag { display:inline-block; padding:4px 12px; background:#d4edda;
                color:#2e7d32; border-radius:20px; font-size:12px;
                font-weight:700; margin-left:10px; }
</style></head><body>

<div class="topbar">
  <div style="display:flex;align-items:center;gap:12px;">
    <img src="/static/logo.png" alt="Ashrah Painting" style="height:38px;border-radius:6px;">
    <span style="font-size:13px;font-weight:600;opacity:.9;letter-spacing:.5px;">Manager Review</span>
  </div>
  <div style="display:flex;gap:16px;align-items:center">
    <span style="font-size:13px;opacity:.8">{{ name }}</span>
    {% if role == 'owner' %}<a href="/owner">Dashboard</a>{% endif %}
    <a href="/logout">Logout</a>
  </div>
</div>

<div class="content">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
    <h2 style="font-size:18px;color:#1F3864">Today's Check-Ins</h2>
    <input type="date" id="review-date" onchange="_loadReviews(this.value)"
           style="padding:8px 12px;border:1.5px solid #dce2ef;border-radius:8px;font-size:14px">
  </div>
  <div id="checkins-container"><p style="color:#999">Loading...</p></div>
</div>

<script>
let reviewData = {};
document.getElementById('review-date').value = new Date().toISOString().split('T')[0];

function scoreColor(v) {
  if (v>=8) return '#4CAF50'; if (v>=5) return '#f0ad4e'; return '#d9534f';
}

async function _loadReviews(dt) {
  const r = await fetch('/api/checkins?date=' + dt + '&limit=50');
  const data = await r.json();
  if (!data.length) {
    document.getElementById('checkins-container').innerHTML =
      '<p style="color:#999;text-align:center;padding:40px">No check-ins for this date.</p>';
    return;
  }
  // Also load existing reviews
  const rv = await fetch('/api/reviews?date=' + dt);
  const reviews = await rv.json();
  const reviewMap = {};
  reviews.forEach(r => { reviewMap[r.checkin_id] = r; });

  document.getElementById('checkins-container').innerHTML = data.map(c => {
    const existing = reviewMap[c.id];
    return `<div class="card" id="card-${c.id}">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
        <div>
          <span class="emp-name">${c.worker_name}</span>
          ${existing ? '<span class="reviewed-tag">✓ Reviewed</span>' : ''}
          <div class="meta">${c.site_address} &bull; ${c.entry_date}</div>
        </div>
        <div style="font-size:28px;font-weight:800;color:${scoreColor(c.avg_score)}">${c.avg_score}/10</div>
      </div>

      <div class="scores-grid">
        <div class="score-item"><div class="val" style="color:${scoreColor(c.tape_covering)}">${c.tape_covering}</div><div class="lbl">Tape &amp; Cover</div></div>
        <div class="score-item"><div class="val" style="color:${scoreColor(c.drop_sheets)}">${c.drop_sheets}</div><div class="lbl">Drop Sheets</div></div>
        <div class="score-item"><div class="val" style="color:${scoreColor(c.patching_process)}">${c.patching_process}</div><div class="lbl">Patching</div></div>
        <div class="score-item"><div class="val" style="color:${scoreColor(c.paint_execution)}">${c.paint_execution}</div><div class="lbl">Paint Exec.</div></div>
        <div class="score-item"><div class="val" style="color:${scoreColor(c.site_control)}">${c.site_control}</div><div class="lbl">Site Control</div></div>
        <div class="score-item"><div class="val" style="color:${scoreColor(c.washing_tool_care)}">${c.washing_tool_care}</div><div class="lbl">Washing</div></div>
      </div>

      <div class="section-label">Daily Summary</div>
      <div class="summary">${c.work_description || '—'}</div>
      ${c.tomorrows_plan ? `<div class="section-label" style="margin-top:10px">Tomorrow's Plan</div><div class="summary">${c.tomorrows_plan}</div>` : ''}
      ${c.custom_scores ? `<div class="section-label" style="margin-top:10px">Custom Scores</div><div class="summary">${c.custom_scores}</div>` : ''}
      ${c.notes ? `<div class="meta" style="margin-top:8px">Notes: ${c.notes}</div>` : ''}

      ${c.photo_urls ? '<div class="section-label" style="margin-top:10px">Photos<'+'/div><div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px">' + c.photo_urls.split(',').filter(u=>u.trim()).map(u=>'<a href="'+u.trim()+'" target="_blank"><img src="'+u.trim()+'" style="width:80px;height:80px;object-fit:cover;border-radius:8px;border:1px solid #dce2ef"><'+'/a>').join('') + '<'+'/div>' : ''}

      <hr style="margin:16px 0;border:none;border-top:1px solid #f0f2f7">
      <div class="section-label">Manager Review</div>

      <div class="slider-row">
        <div class="top"><span style="font-size:13px;font-weight:600">Accuracy Score — how honest was this self-assessment?</span>
          <span id="acc-val-${c.id}" style="font-weight:800;font-size:18px;color:#1F3864">${existing?.accuracy_score||7}</span></div>
        <input type="range" min="1" max="10" value="${existing?.accuracy_score||7}"
               oninput="document.getElementById('acc-val-${c.id}').textContent=this.value"
               id="acc-${c.id}">
        <div style="display:flex;justify-content:space-between;font-size:11px;color:#999"><span>1 — Not honest</span><span>10 — Very honest</span></div>
      </div>

      <div class="section-label">Trust Level</div>
      <div class="badge-row" id="trust-${c.id}">
        <button class="trust-btn ${(existing?.trust_level||'trusted')==='trusted'?'active-trusted':''}"
                onclick="setTrust('${c.id}','trusted',this)">✓ Trusted</button>
        <button class="trust-btn ${(existing?.trust_level||'')==='watch'?'active-watch':''}"
                onclick="setTrust('${c.id}','watch',this)">⚠ Watch</button>
        <button class="trust-btn ${(existing?.trust_level||'')==='concern'?'active-concern':''}"
                onclick="setTrust('${c.id}','concern',this)">✗ Concern</button>
      </div>

      <div class="section-label">Your Notes</div>
      <textarea id="notes-${c.id}" placeholder="Write your assessment of this employee's report...">${existing?.notes||''}</textarea>

      <div style="margin-top:14px">
        <button class="btn" onclick="submitReview('${c.id}')">Save Review</button>
      </div>
    </div>`;
  }).join('');
}

function setTrust(id, level, btn) {
  reviewData[id] = reviewData[id] || {};
  reviewData[id].trust = level;
  const btns = document.getElementById('trust-'+id).querySelectorAll('.trust-btn');
  btns.forEach(b => b.className = 'trust-btn');
  btn.className = 'trust-btn active-' + level;
}

async function submitReview(checkinId) {
  const accuracy = document.getElementById('acc-'+checkinId).value;
  const notes    = document.getElementById('notes-'+checkinId).value;
  const trust    = reviewData[checkinId]?.trust ||
    document.querySelector('#trust-'+checkinId+' .trust-btn.active-trusted, #trust-'+checkinId+' .trust-btn.active-watch, #trust-'+checkinId+' .trust-btn.active-concern')?.textContent?.includes('Trusted') ? 'trusted' :
    document.querySelector('#trust-'+checkinId+' .trust-btn[class*=active]')?.classList.contains('active-watch') ? 'watch' : 'concern';
  const r = await fetch('/api/save-review', { method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ checkin_id: checkinId, accuracy_score: parseInt(accuracy),
                           trust_level: reviewData[checkinId]?.trust || 'trusted', notes }) });
  const d = await r.json();
  if (d.ok) {
    const card = document.getElementById('card-'+checkinId);
    card.style.borderLeft = '4px solid #4CAF50';
    const name = card.querySelector('.emp-name');
    if (!card.querySelector('.reviewed-tag')) {
      const tag = document.createElement('span');
      tag.className = 'reviewed-tag'; tag.textContent = '✓ Reviewed';
      name.after(tag);
    }
  }
}

async function loadReviews() {
  const urlParams = new URLSearchParams(window.location.search);
  const targetId  = urlParams.get('checkin_id');
  let dt = document.getElementById('review-date').value;

  // If we have a target check-in, fetch its date so we load the right day
  if (targetId) {
    try {
      const r = await fetch('/api/checkin/' + targetId);
      const ci = await r.json();
      if (ci && ci.entry_date) {
        dt = ci.entry_date;
        document.getElementById('review-date').value = dt;
      }
    } catch(e) {}
  }

  await _loadReviews(dt);
  if (targetId) {
    setTimeout(() => {
      const card = document.getElementById('card-' + targetId);
      if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'start' });
        card.style.boxShadow = '0 0 0 3px #1F3864';
      }
    }, 300);
  }
}

loadReviews();
</script>

<style>
.lumia-fab { position:fixed; bottom:28px; right:20px; width:56px; height:56px;
  background:#1F3864; color:#fff; border:none; border-radius:50%;
  font-size:24px; cursor:pointer; box-shadow:0 4px 16px rgba(31,56,100,.35);
  display:flex; align-items:center; justify-content:center; z-index:1000; transition:transform .2s; }
.lumia-fab:hover { transform:scale(1.1); }
.lumia-panel { position:fixed; bottom:96px; right:16px; width:min(360px,calc(100vw - 32px));
  background:#fff; border-radius:16px; box-shadow:0 8px 32px rgba(0,0,0,.18);
  z-index:999; overflow:hidden; display:none; flex-direction:column; }
.lumia-panel.open { display:flex; }
.lumia-panel-header { background:#1F3864; color:#fff; padding:14px 16px;
  display:flex; align-items:center; justify-content:space-between; }
.lumia-panel-header h3 { font-size:15px; font-weight:700; letter-spacing:1px; }
.lumia-panel-close { background:none; border:none; color:#fff; font-size:20px; cursor:pointer; }
.lumia-messages { flex:1; max-height:260px; overflow-y:auto; padding:12px; }
.lumia-msg { margin-bottom:10px; }
.lumia-msg .bubble { display:inline-block; padding:9px 13px; border-radius:12px;
  font-size:13px; line-height:1.5; max-width:90%; }
.lumia-msg.user .bubble { background:#1F3864; color:#fff; float:right; border-radius:12px 12px 2px 12px; }
.lumia-msg.lumia .bubble { background:#f4f6fb; color:#333; border-radius:12px 12px 12px 2px; }
.lumia-msg::after { content:''; display:block; clear:both; }
.lumia-input-row { padding:10px 12px; border-top:1px solid #eee; display:flex; gap:8px; align-items:center; }
.lumia-input-row input { flex:1; padding:9px 12px; border:1.5px solid #dce2ef;
  border-radius:20px; font-size:14px; outline:none; }
.lumia-input-row input:focus { border-color:#1F3864; }
.lumia-send-btn { background:#1F3864; color:#fff; border:none; border-radius:50%;
  width:36px; height:36px; font-size:16px; cursor:pointer; display:flex; align-items:center; justify-content:center; }
.lumia-mic-btn { background:none; border:2px solid #1F3864; border-radius:50%;
  width:36px; height:36px; font-size:16px; cursor:pointer; display:flex; align-items:center; justify-content:center; }
.lumia-mic-btn.recording { background:#d9534f; border-color:#d9534f; color:#fff; }
.lumia-status { font-size:11px; color:#999; text-align:center; padding:4px; }
</style>

<button class="lumia-fab" onclick="toggleLumiaPanel()" title="Talk to Lumia">&#129302;</button>
<div class="lumia-panel" id="lumiaPanel">
  <div class="lumia-panel-header">
    <h3>&#129302; LUMIA</h3>
    <button class="lumia-panel-close" onclick="toggleLumiaPanel()">&#10005;</button>
  </div>
  <div class="lumia-messages" id="lumiaMessages">
    <div class="lumia-msg lumia">
      <div class="bubble">Hi! I'm Lumia. Need help reviewing check-ins or writing notes? Just ask!</div>
    </div>
  </div>
  <div class="lumia-status" id="lumiaStatus"></div>
  <div class="lumia-input-row">
    <button class="lumia-mic-btn" id="lumiaMicBtn" onclick="toggleLumiaMic()" title="Speak">&#127908;</button>
    <input type="text" id="lumiaInput" placeholder="Ask Lumia anything..." onkeydown="if(event.key==='Enter')sendLumiaMsg()">
    <button class="lumia-send-btn" onclick="sendLumiaMsg()">&#10148;</button>
  </div>
</div>

<script>
let lumiaPanelOpen = false;
let lumiaMicRec = null;

function toggleLumiaPanel() {
  lumiaPanelOpen = !lumiaPanelOpen;
  document.getElementById('lumiaPanel').classList.toggle('open', lumiaPanelOpen);
  if (lumiaPanelOpen) document.getElementById('lumiaInput').focus();
}

function appendLumiaMsg(role, text) {
  var msgs = document.getElementById('lumiaMessages');
  var div = document.createElement('div');
  div.className = 'lumia-msg ' + role;
  var safe = text;
  try { safe = text.replace(new RegExp(String.fromCharCode(60),'g'),'&lt;').replace(new RegExp(String.fromCharCode(10),'g'),'<br>'); } catch(e){}
  div.innerHTML = '<div class="bubble">' + safe + '<'+'/div>';
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}

async function sendLumiaMsg() {
  var input = document.getElementById('lumiaInput');
  var text = input.value.trim();
  if (!text) return;
  input.value = '';
  appendLumiaMsg('user', text);
  document.getElementById('lumiaStatus').textContent = 'Lumia is thinking...';
  try {
    var res = await fetch('/api/lumia-chat', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ message: text })
    });
    var d = await res.json();
    appendLumiaMsg('lumia', d.reply || 'Sorry, I could not respond right now.');
  } catch(e) {
    appendLumiaMsg('lumia', 'Connection error. Please try again.');
  }
  document.getElementById('lumiaStatus').textContent = '';
}

function toggleLumiaMic() {
  var SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRec) { alert('Voice not supported in this browser.'); return; }
  var btn = document.getElementById('lumiaMicBtn');
  if (lumiaMicRec) { lumiaMicRec.stop(); return; }
  var rec = new SpeechRec();
  rec.lang = 'en-US';
  rec.continuous = false;
  rec.interimResults = false;
  btn.classList.add('recording');
  lumiaMicRec = rec;
  rec.onresult = function(e) {
    document.getElementById('lumiaInput').value = e.results[0][0].transcript;
    sendLumiaMsg();
  };
  rec.onend = function() { btn.classList.remove('recording'); lumiaMicRec = null; };
  rec.onerror = function() { btn.classList.remove('recording'); lumiaMicRec = null; };
  rec.start();
}

// ─── ESTIMATES TAB ──────────────────────────────────────────────────────────

let _estJobId = null;
let _estPollTimer = null;

function initEstimatesTab() {
  // Nothing to load on init — user drives via upload
}

function resetEstimatesTab() {
  _estJobId = null;
  if (_estPollTimer) { clearInterval(_estPollTimer); _estPollTimer = null; }
  document.getElementById('est-upload-panel').style.display = '';
  document.getElementById('est-progress-panel').style.display = 'none';
  document.getElementById('est-results-panel').style.display = 'none';
  document.getElementById('est-error-panel').style.display = 'none';
  document.getElementById('est-file-input').value = '';
  document.getElementById('est-create-job-result').textContent = '';
}

async function handleEstimateFile(input) {
  if (!input.files || !input.files[0]) return;
  const file = input.files[0];
  if (file.type !== 'application/pdf') {
    alert('Please choose a PDF file.');
    return;
  }
  const clientName  = document.getElementById('est-client-name').value.trim();
  const siteAddress = document.getElementById('est-site-address').value.trim();
  const fd = new FormData();
  fd.append('pdf', file);
  fd.append('client_name', clientName);
  fd.append('site_address', siteAddress);
  document.getElementById('est-upload-panel').style.display = 'none';
  document.getElementById('est-progress-panel').style.display = '';
  document.getElementById('est-progress-title').textContent = 'Uploading ' + file.name + '...';
  document.getElementById('est-progress-msg').textContent = 'Sending to Lumia...';
  try {
    const r = await fetch('/api/estimates/upload', { method: 'POST', body: fd });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || 'Upload failed');
    _estJobId = d.job_id;
    document.getElementById('est-progress-title').textContent = 'Extracting measurements...';
    document.getElementById('est-progress-msg').textContent = 'Queued...';
    _estPollTimer = setInterval(_pollEstimateStatus, 2500);
  } catch(e) {
    _showEstimateError(e.message);
  }
}

async function _pollEstimateStatus() {
  if (!_estJobId) return;
  try {
    const r = await fetch('/api/estimates/status/' + _estJobId);
    const d = await r.json();
    document.getElementById('est-progress-msg').textContent = d.progress || '...';
    if (d.status === 'processing' || d.status === 'queued') {
      document.getElementById('est-progress-title').textContent = 'Processing PDF...';
      return;
    }
    clearInterval(_estPollTimer); _estPollTimer = null;
    if (d.status === 'done') {
      _renderEstimateResults(d);
    } else {
      _showEstimateError(d.error || 'Unknown error during extraction.');
    }
  } catch(e) { /* network blip — keep polling */ }
}

function _showEstimateError(msg) {
  if (_estPollTimer) { clearInterval(_estPollTimer); _estPollTimer = null; }
  document.getElementById('est-progress-panel').style.display = 'none';
  document.getElementById('est-error-panel').style.display = '';
  document.getElementById('est-error-msg').textContent = msg;
}

async function _renderEstimateResults(job) {
  const r = await fetch('/api/estimates/' + _estJobId);
  const d = await r.json();
  document.getElementById('est-progress-panel').style.display = 'none';
  document.getElementById('est-results-panel').style.display = '';
  const raw = d.raw_json || {};
  const dt = raw.document_totals || {};
  document.getElementById('est-measurements-summary').innerHTML =
    '<b>' + (dt.pages_processed||0) + '</b> pages &nbsp;|&nbsp; ' +
    '<b>' + (dt.total_measurements||0) + '</b> measurements extracted &nbsp;|&nbsp; ' +
    '<span style="color:#888;">File: ' + (dt.file_name||'') + '</span>';
  const pc = d.paint_calc || {};
  document.getElementById('est-scope').textContent = pc.scope_summary || '';
  const rooms = pc.rooms || [];
  if (rooms.length > 0) {
    let tbl = '<table style="width:100%;border-collapse:collapse;font-size:13px;">' +
      '<thead><tr style="background:#f1f5ff;">' +
      '<th style="padding:8px 10px;text-align:left;border-bottom:1.5px solid #d0d7e8;">Room / Area</th>' +
      '<th style="padding:8px 10px;text-align:right;border-bottom:1.5px solid #d0d7e8;">Walls (sqft)</th>' +
      '<th style="padding:8px 10px;text-align:right;border-bottom:1.5px solid #d0d7e8;">Ceiling (sqft)</th>' +
      '<th style="padding:8px 10px;text-align:right;border-bottom:1.5px solid #d0d7e8;">Trim (lin ft)</th>' +
      '<th style="padding:8px 10px;text-align:left;border-bottom:1.5px solid #d0d7e8;">Notes</th>' +
      '</tr></thead><tbody>';
    rooms.forEach(function(rm, i) {
      const bg = i % 2 === 0 ? '#fff' : '#f8f9fc';
      tbl += '<tr style="background:' + bg + ';">' +
        '<td style="padding:7px 10px;border-bottom:1px solid #eee;">' + (rm.name||'') + '</td>' +
        '<td style="padding:7px 10px;border-bottom:1px solid #eee;text-align:right;">' + (rm.wall_area_sqft||0) + '</td>' +
        '<td style="padding:7px 10px;border-bottom:1px solid #eee;text-align:right;">' + (rm.ceiling_area_sqft||0) + '</td>' +
        '<td style="padding:7px 10px;border-bottom:1px solid #eee;text-align:right;">' + (rm.trim_linear_ft||0) + '</td>' +
        '<td style="padding:7px 10px;border-bottom:1px solid #eee;font-size:12px;color:#666;">' + (rm.notes||'') + '</td>' +
        '</tr>';
    });
    const t = pc.totals || {};
    tbl += '<tr style="background:#eef2fb;font-weight:600;">' +
      '<td style="padding:8px 10px;">Total</td>' +
      '<td style="padding:8px 10px;text-align:right;">' + (t.wall_area_sqft||0) + '</td>' +
      '<td style="padding:8px 10px;text-align:right;">' + (t.ceiling_area_sqft||0) + '</td>' +
      '<td style="padding:8px 10px;text-align:right;">' + (t.trim_linear_ft||0) + '</td>' +
      '<td style="padding:8px 10px;color:#555;font-size:12px;font-weight:400;">' + (t.total_paintable_sqft||0) + ' sqft total</td>' +
      '</tr></tbody></table>';
    document.getElementById('est-rooms-table').innerHTML = tbl;
  } else {
    document.getElementById('est-rooms-table').innerHTML = '<p style="color:#888;font-size:13px;">No room breakdown available.</p>';
  }
  const mat = pc.materials || {};
  document.getElementById('est-materials').innerHTML =
    '<div style="display:flex;gap:14px;flex-wrap:wrap;">' +
    _statPill('Wall Paint', (mat.wall_paint_gallons||0) + ' gal') +
    _statPill('Ceiling Paint', (mat.ceiling_paint_gallons||0) + ' gal') +
    _statPill('Primer', (mat.primer_gallons||0) + ' gal') + '</div>' +
    (mat.notes ? '<p style="font-size:12px;color:#888;margin-top:6px;">' + mat.notes + '</p>' : '');
  const lab = pc.labor || {};
  document.getElementById('est-labor').innerHTML =
    '<div style="display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;">' +
    _statPill('Est. Days', lab.estimated_days||0) +
    _statPill('Painters', lab.painters_recommended||0) +
    _statPill('Hours', lab.hours_estimate||0) + '</div>' +
    (lab.notes ? '<p style="font-size:12px;color:#888;margin-top:6px;">' + lab.notes + '</p>' : '');
  const asmpt = pc.assumptions || [];
  if (asmpt.length) {
    document.getElementById('est-assumptions').innerHTML = 'Assumptions: ' + asmpt.join(' &bull; ');
  }
  document.getElementById('est-work-order').textContent = d.work_order || 'Not available.';
}

function _statPill(label, val) {
  return '<div style="background:#eef2fb;border-radius:8px;padding:10px 16px;min-width:100px;">' +
    '<div style="font-size:18px;font-weight:700;color:#1F3864;">' + val + '</div>' +
    '<div style="font-size:11px;color:#666;margin-top:2px;">' + label + '</div></div>';
}

function copyWorkOrder() {
  const txt = document.getElementById('est-work-order').textContent;
  navigator.clipboard.writeText(txt).then(function() { alert('Work order copied.'); });
}

async function createJobFromEstimate() {
  if (!_estJobId) return;
  const btn = document.getElementById('est-create-job-btn');
  btn.disabled = true;
  btn.textContent = 'Creating...';
  try {
    const r = await fetch('/api/estimates/' + _estJobId + '/create-job', { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      document.getElementById('est-create-job-result').innerHTML =
        '<span style="color:#2e7d32;">Job created. Switch to the Jobs tab to assign crew.</span>';
      btn.textContent = 'Job Created';
    } else {
      document.getElementById('est-create-job-result').innerHTML =
        '<span style="color:#c0392b;">Failed: ' + (d.error||'Unknown error') + '</span>';
      btn.disabled = false;
      btn.textContent = 'Create Job from This Estimate';
    }
  } catch(e) {
    document.getElementById('est-create-job-result').innerHTML =
      '<span style="color:#c0392b;">Error: ' + e.message + '</span>';
    btn.disabled = false;
    btn.textContent = 'Create Job from This Estimate';
  }
}

// ─── END ESTIMATES TAB ──────────────────────────────────────────────────────
</script>
</body></html>"""


@app.route("/review")
@require_role("manager", "owner")
def review_page():
    return render_template_string(REVIEW_HTML,
                                  name=session.get("name"), role=session.get("role"))


# ---------------------------------------------------------------------------
# API ENDPOINTS
# ---------------------------------------------------------------------------

@app.route("/api/checkin/<checkin_id>")
@require_role("manager", "owner")
def api_single_checkin(checkin_id):
    if not supabase_client:
        return jsonify({})
    res = supabase_client.table("checkins").select("*").eq("id", checkin_id).execute()
    return jsonify((res.data or [{}])[0])


@app.route("/api/checkins")
@require_role("manager", "owner")
def api_checkins():
    if not supabase_client:
        return jsonify([])
    q = supabase_client.table("checkins").select("*").order("created_at", desc=True)
    dt  = request.args.get("date")
    emp = request.args.get("employee")
    lim = int(request.args.get("limit", 50))
    if dt:  q = q.eq("entry_date", dt)
    if emp: q = q.eq("worker_name", emp)
    q = q.limit(lim)
    return jsonify(q.execute().data or [])


@app.route("/api/all-reviews")
@require_role("owner")
def api_all_reviews():
    if not supabase_client:
        return jsonify([])
    dt    = request.args.get("date")
    emp   = request.args.get("employee")
    trust = request.args.get("trust")
    lim   = int(request.args.get("limit", 100))
    # Join reviews with checkins
    checkins_q = supabase_client.table("checkins").select("id,entry_date,worker_name,site_address,avg_score")
    if dt:  checkins_q = checkins_q.eq("entry_date", dt)
    if emp: checkins_q = checkins_q.eq("worker_name", emp)
    checkins = checkins_q.limit(lim).execute().data or []
    if not checkins:
        return jsonify([])
    c_map = {c["id"]: c for c in checkins}
    reviews_q = supabase_client.table("reviews").select("*").in_("checkin_id", list(c_map.keys()))
    if trust: reviews_q = reviews_q.eq("trust_level", trust)
    reviews = reviews_q.execute().data or []
    result = []
    for rv in reviews:
        c = c_map.get(rv["checkin_id"], {})
        result.append({**c, **rv})
    result.sort(key=lambda x: x.get("entry_date",""), reverse=True)
    return jsonify(result)


@app.route("/api/reviews")
@require_role("manager", "owner")
def api_reviews():
    if not supabase_client:
        return jsonify([])
    dt = request.args.get("date")
    q  = supabase_client.table("reviews").select("*")
    if dt:
        # get checkin IDs for this date
        c_ids = [c["id"] for c in (supabase_client.table("checkins")
                 .select("id").eq("entry_date", dt).execute().data or [])]
        if not c_ids:
            return jsonify([])
        q = q.in_("checkin_id", c_ids)
    return jsonify(q.execute().data or [])


@app.route("/api/save-review", methods=["POST"])
@require_role("manager", "owner")
def api_save_review():
    if not supabase_client:
        return jsonify({"ok": False})
    d = request.get_json()
    # upsert by checkin_id
    existing = supabase_client.table("reviews").select("id").eq("checkin_id", d["checkin_id"]).execute().data
    payload  = {
        "checkin_id":     d["checkin_id"],
        "reviewer_name":  session.get("name"),
        "accuracy_score": d.get("accuracy_score", 7),
        "trust_level":    d.get("trust_level", "trusted"),
        "notes":          d.get("notes", ""),
    }
    if existing:
        supabase_client.table("reviews").update(payload).eq("checkin_id", d["checkin_id"]).execute()
    else:
        supabase_client.table("reviews").insert(payload).execute()
    return jsonify({"ok": True})


@app.route("/api/managers")
@require_role("owner")
def api_managers():
    if not supabase_client:
        return jsonify([])
    return jsonify(supabase_client.table("managers").select("id,name,role,active").execute().data or [])


@app.route("/api/add-manager", methods=["POST"])
@require_role("owner")
def api_add_manager():
    if not supabase_client:
        return jsonify({"message": "No database"})
    d = request.get_json()
    supabase_client.table("managers").insert({
        "name": d["mgr_name"], "pin": d["mgr_pin"], "role": d["mgr_role"], "active": True
    }).execute()
    return jsonify({"message": f"{d['mgr_name']} added successfully."})


@app.route("/api/remove-manager/<mgr_id>", methods=["POST"])
@require_role("owner")
def api_remove_manager(mgr_id):
    if not supabase_client:
        return jsonify({"ok": False})
    supabase_client.table("managers").update({"active": False}).eq("id", mgr_id).execute()
    return jsonify({"ok": True})


@app.route("/api/clients")
@require_role("owner")
def api_clients():
    if not supabase_client:
        return jsonify([])
    try:
        return jsonify(supabase_client.table("clients").select("*").execute().data or [])
    except Exception:
        return jsonify([])


@app.route("/api/add-client", methods=["POST"])
@require_role("owner")
def api_add_client():
    if not supabase_client:
        return jsonify({"message": "No database"})
    d = request.get_json()
    email2 = (d.get("client_email_2") or "").strip().lower() or None
    try:
        supabase_client.table("clients").insert({
            "client_name":    d["client_name"],
            "client_email":   d["client_email"],
            "client_email_2": email2,
            "site_keyword":   d["site_keyword"].lower().strip(),
        }).execute()
        return jsonify({"message": f"Client {d['client_name']} saved."})
    except Exception as exc:
        return jsonify({"message": f"Error: {exc}"})


@app.route("/api/send-client-test-invite", methods=["POST"])
@require_role("owner")
def api_send_client_test_invite():
    """Send a client a branded welcome email with the Ask Lumia button.
    Useful to test / onboard — no check-ins required.
    Only works for clients whose email is on CLIENT_CHAT_ALLOWLIST."""
    d = request.get_json(silent=True) or {}
    client_name  = (d.get("client_name")  or "").strip()
    client_email = (d.get("client_email") or "").strip()
    site_keyword = (d.get("site_keyword") or "").strip().lower()

    if not client_email:
        return jsonify({"ok": False, "message": "Missing client email."})
    if not _client_chat_enabled_for(client_email):
        return jsonify({"ok": False,
            "message": f"{client_email} is not on the Ask Lumia allowlist. "
                       "Add it via CLIENT_CHAT_ALLOWED_EMAILS env var to enable."})

    row = _ensure_client_row(site_keyword, client_name, client_email)
    if not row:
        return jsonify({"ok": False, "message":
            f"Could not create client row: {_LAST_ENSURE_CLIENT_ERROR or 'unknown error'}"})

    url = _client_ask_url(row)
    if not url:
        return jsonify({"ok": False, "message": "Could not generate access URL."})

    first = (client_name or row.get("client_name") or "").split()[0] or "there"
    subject = "Try Ask Lumia — your new project assistant"
    html = (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;'
        'max-width:560px;margin:0 auto;color:#1a1a2e;">'
        f'<div style="text-align:center;padding:20px 0;border-bottom:3px solid #1F3864;margin-bottom:24px;">'
        f'<img src="{APP_BASE_URL}/static/logo.png" alt="Ashrah Painting" style="width:160px;">'
        f'</div>'
        f'<p style="font-size:16px;">Hi {first},</p>'
        '<p style="font-size:15px;line-height:1.6;">We\'ve added a new way for you to stay on top of your project. '
        'Any time you have a question — progress, schedule, what\'s next — you can now ask '
        '<b>Lumia</b>, our AI assistant, directly. Lumia has access to your daily reports and can give you '
        'an answer anytime, 24/7.</p>'
        '<p style="font-size:15px;line-height:1.6;">If Lumia can\'t answer, Ahmad will be in touch within about 5 minutes.</p>'
        f'<div style="text-align:center;margin:28px 0;">'
        f'<a href="{url}" style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;'
        f'font-weight:600;padding:14px 28px;border-radius:8px;font-size:15px;">'
        f'Ask Lumia about your project</a>'
        f'</div>'
        '<p style="font-size:13px;color:#666;">This link is private to you — please don\'t share it.</p>'
        '<p style="font-size:14px;margin-top:24px;">Thanks for your trust,<br>'
        '<b>Ahmad &mdash; Ashrah Painting</b></p>'
        '</div>'
    )
    plain = (
        f"Hi {first},\n\n"
        "We've added a new way for you to stay on top of your project. Any time you have a question — "
        "progress, schedule, what's next — you can now ask Lumia, our AI assistant, directly.\n\n"
        "If Lumia can't answer, Ahmad will be in touch within about 5 minutes.\n\n"
        f"Ask Lumia: {url}\n\n"
        "This link is private to you — please don't share it.\n\n"
        "Thanks for your trust,\nAhmad — Ashrah Painting\n"
    )

    try:
        import httpx as _httpx
        resend_key = os.getenv("RESEND_API_KEY", "")
        if not resend_key:
            return jsonify({"ok": False, "message": "RESEND_API_KEY not set."})
        recipients = [client_email]
        if OWNER_EMAIL and OWNER_EMAIL != client_email:
            recipients.append(OWNER_EMAIL)
        r = _httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
            json={
                "from":    "Ashrah Painting <noreply@ashrah.ai>",
                "to":      recipients,
                "subject": subject,
                "html":    html,
                "text":    plain,
            },
            timeout=15,
        )
        if r.status_code in (200, 201):
            return jsonify({"ok": True, "message": f"Ask Lumia invite sent to {client_email}."})
        return jsonify({"ok": False, "message": f"Email API error {r.status_code}: {r.text}"})
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Error: {exc}"})


@app.route("/api/remove-client/<cid>", methods=["POST"])
@require_role("owner")
def api_remove_client(cid):
    if not supabase_client:
        return jsonify({"ok": False})
    supabase_client.table("clients").delete().eq("id", cid).execute()
    return jsonify({"ok": True})


@app.route("/api/site-visit", methods=["POST"])
@require_role("owner")
def api_site_visit():
    """Owner confirms an employee is physically on site."""
    if not supabase_client:
        return jsonify({"ok": False})
    d = request.get_json()
    supabase_client.table("site_visits").insert({
        "job_id":        d.get("job_id", ""),
        "site_address":  d.get("site_address", ""),
        "employee_name": d.get("employee_name", ""),
        "confirmed_by":  session.get("name", "Owner"),
    }).execute()
    return jsonify({"ok": True})


@app.route("/api/site-visits")
@require_role("owner")
def api_site_visits():
    if not supabase_client:
        return jsonify([])
    try:
        return jsonify(
            supabase_client.table("site_visits").select("*")
            .order("visited_at", desc=True).limit(100).execute().data or []
        )
    except Exception:
        return jsonify([])


@app.route("/api/mark-job-done", methods=["POST"])
def api_mark_job_done():
    """Employee or owner marks a job as completed."""
    if not session.get("employee_name") and not session.get("role"):
        return jsonify({"ok": False}), 401
    if not supabase_client:
        return jsonify({"ok": False})
    d = request.get_json()
    job_id = d.get("job_id")
    if not job_id:
        return jsonify({"ok": False, "message": "No job ID"})
    supabase_client.table("jobs").update({"status": "completed"}).eq("id", job_id).execute()
    # Notify owner
    done_by = session.get("employee_name") or session.get("name") or "Someone"
    threading.Thread(target=_notify_owner_job_done, args=(job_id, done_by), daemon=True).start()
    return jsonify({"ok": True})


def _notify_owner_job_done(job_id: str, done_by: str) -> None:
    import httpx as _httpx
    resend_key = os.getenv("RESEND_API_KEY", "")
    if not resend_key or not OWNER_EMAIL:
        return
    try:
        job_row = (supabase_client.table("jobs").select("client_name,site_address")
                   .eq("id", job_id).execute().data or [{}])[0]
        subject = f"Job Marked Done — {job_row.get('site_address', job_id)}"
        body    = (f"{done_by} marked the job at {job_row.get('site_address','?')} "
                   f"({job_row.get('client_name','?')}) as completed.\n\n"
                   f"Review it in your Lumia dashboard.")
        _httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
            json={"from": "Ashrah Painting <noreply@ashrah.ai>",
                  "to": [OWNER_EMAIL], "subject": subject, "text": body},
            timeout=15,
        )
    except Exception as exc:
        print(f"[JobDone] Notify error: {exc}")


@app.route("/api/active-jobs")
@require_employee
def api_active_jobs():
    """Return open jobs assigned to the current employee (or all open jobs if none assigned)."""
    if not supabase_client:
        return jsonify([])
    employee_name = session.get("employee_name", "")
    all_jobs = (
        supabase_client.table("jobs").select("id,client_name,site_address,assigned_employees")
        .eq("status", "open").order("created_at", desc=True).execute().data or []
    )
    # Filter to jobs assigned to this employee; fall back to all if nothing assigned anywhere
    assigned = [j for j in all_jobs if employee_name in (j.get("assigned_employees") or [])]
    jobs = assigned if assigned else all_jobs
    # Strip assigned_employees from the response (internal field)
    return jsonify([{"id": j["id"], "client_name": j["client_name"], "site_address": j["site_address"]} for j in jobs])


@app.route("/api/jobs")
@require_role("owner")
def api_jobs():
    if not supabase_client:
        return jsonify([])
    return jsonify(supabase_client.table("jobs").select("*").order("created_at", desc=True).limit(100).execute().data or [])


@app.route("/api/delete-job/<job_id>", methods=["POST"])
@require_role("owner")
def api_delete_job(job_id):
    if not supabase_client:
        return jsonify({"ok": False, "error": "No DB"})
    supabase_client.table("jobs").delete().eq("id", job_id).execute()
    return jsonify({"ok": True})


@app.route("/api/job-report/<job_id>")
@require_role("owner")
def api_job_report(job_id):
    if not supabase_client:
        return jsonify({"job": {}, "checkins": []})
    job = supabase_client.table("jobs").select("*").eq("id", job_id).limit(1).execute().data
    job = job[0] if job else {}
    checkins = supabase_client.table("checkins").select("*").eq("job_id", job_id).order("entry_date", desc=True).execute().data or []
    total = len(checkins)
    avg = round(sum(c.get("avg_score", 0) or 0 for c in checkins) / total, 1) if total else None
    days = len(set(c["entry_date"] for c in checkins))
    return jsonify({"job": job, "checkins": checkins, "stats": {"total_checkins": total, "avg_score": avg, "days_worked": days}})


@app.route("/api/match-crew", methods=["POST"])
@require_role("owner")
def api_match_crew():
    d = request.get_json()
    # Gather employee history from Supabase
    profiles = {}
    if supabase_client:
        checkins = supabase_client.table("checkins").select("*").order("entry_date", desc=True).limit(200).execute().data or []
        reviews  = supabase_client.table("reviews").select("*").execute().data or []
        review_map = {r["checkin_id"]: r for r in reviews}
        for c in checkins:
            name = c["worker_name"]
            if name not in profiles:
                profiles[name] = {"checkins": [], "trust_scores": [], "avg_scores": []}
            profiles[name]["checkins"].append(c)
            if c["avg_score"]:
                profiles[name]["avg_scores"].append(c["avg_score"])
            rv = review_map.get(c["id"])
            if rv:
                profiles[name]["trust_scores"].append(rv.get("accuracy_score", 7))

    summary = {}
    for name, p in profiles.items():
        avgs = p["avg_scores"]
        trust = p["trust_scores"]
        summary[name] = {
            "total_checkins": len(p["checkins"]),
            "avg_self_score": round(sum(avgs)/len(avgs), 1) if avgs else "N/A",
            "avg_trust_score": round(sum(trust)/len(trust), 1) if trust else "N/A",
            "recent_work": [c.get("work_description","")[:100] for c in p["checkins"][:3]],
        }

    prompt = f"""You are Lumia, the operations AI for Ashrah Painting in Winnipeg, Canada.

Job Details:
- Client: {d.get('client_name')}
- Site: {d.get('site_address')}
- Work: {d.get('work_description')}
- Start Date: {d.get('start_date') or 'TBD'}
- Painters Needed: {d.get('painters_needed', 2)}

Employee Profiles (based on check-in history and manager reviews):
{json.dumps(summary, indent=2)}

Based on this data, provide:
1. Which {d.get('painters_needed', 2)} employee(s) you recommend for this job and why
2. Estimated duration in days
3. Any special considerations or warnings

Be specific and reference the data. If trust scores are low, flag it."""

    try:
        client = _anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL, max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        result = response.content[0].text
    except Exception as exc:
        result = f"AI error: {exc}"

    return jsonify({"result": result})


@app.route("/api/save-job", methods=["POST"])
@require_role("owner")
def api_save_job():
    d = request.get_json()
    assigned = d.get("assigned_employees") or []
    if isinstance(assigned, str):
        assigned = [assigned] if assigned else []
    # Deduplicate while preserving order
    seen: set[str] = set()
    assigned = [n for n in assigned if not (n in seen or seen.add(n))]
    job_info = {
        "client_name":        d.get("client_name"),
        "site_address":       d.get("site_address"),
        "work_description":   d.get("work_description"),
        "start_date":         d.get("start_date") or None,
        "painters_needed":    int(d.get("painters_needed", 2)),
        "status":             "open",
        "assigned_employees": assigned,
    }
    if supabase_client:
        supabase_client.table("jobs").insert(job_info).execute()

    def _send_all():
        _notify_assigned_employees(job_info, assigned)
        client_notified = _notify_client_of_assignment(job_info, assigned)
        _log_assignment(job_info, assigned, client_notified)

    if assigned:
        threading.Thread(target=_send_all, daemon=True).start()

    msg = f"Job saved! Crew ({', '.join(assigned)}) notified. Client email sent." if assigned else "Job saved (no employees assigned)."
    return jsonify({"message": msg})


@app.route("/api/assign-employees", methods=["POST"])
@require_role("owner")
def api_assign_employees():
    d = request.get_json()
    job_id       = d.get("job_id")
    assigned     = d.get("assigned_employees") or []
    notify_client = d.get("notify_client", True)   # pass False for silent assignment
    seen: set[str] = set()
    assigned = [n for n in assigned if not (n in seen or seen.add(n))]
    if not supabase_client or not job_id:
        return jsonify({"ok": False, "error": "Missing data"})
    supabase_client.table("jobs").update({"assigned_employees": assigned}).eq("id", job_id).execute()
    job_row = (supabase_client.table("jobs").select("*").eq("id", job_id).execute().data or [None])[0]
    emailed = []
    client_notified = False
    if assigned and job_row:
        emailed = _notify_assigned_employees(job_row, assigned)
        if notify_client:
            client_notified = _notify_client_of_assignment(job_row, assigned)
        _log_assignment(job_row, assigned, client_notified)
    return jsonify({"ok": True, "emailed": emailed, "client_notified": client_notified, "silent": not notify_client})


@app.route("/api/assignment-log")
@require_role("owner")
def api_assignment_log():
    """Return crew assignment notification history."""
    if not supabase_client:
        return jsonify([])
    try:
        rows = supabase_client.table("job_notifications") \
            .select("*").order("notified_at", desc=True).limit(50).execute().data or []
        return jsonify(rows)
    except Exception as exc:
        print(f"[Assignment Log] Fetch error: {exc}")
        return jsonify([])


# ---------------------------------------------------------------------------
# API: EMPLOYEE MANAGEMENT
# ---------------------------------------------------------------------------
@app.route("/api/employees")
@require_role("owner")
def api_employees():
    if not supabase_client:
        return jsonify([{"id": n, "name": n, "email": "", "active": True} for n in EMPLOYEES])
    db_emps = supabase_client.table("employees").select("id,name,email,active,created_at").execute().data or []
    if db_emps:
        # Deduplicate by name — keep the most recent entry per name
        seen: set[str] = set()
        unique = []
        for e in db_emps:
            key = (e.get("name") or "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(e)
        return jsonify(unique)
    return jsonify([{"id": n, "name": n, "email": "", "active": True} for n in EMPLOYEES])


@app.route("/api/add-employee", methods=["POST"])
@require_role("owner")
def api_add_employee():
    if not supabase_client:
        return jsonify({"message": "No database"})
    d = request.get_json()
    name  = (d.get("name") or "").strip()
    email = (d.get("email") or "").strip().lower()
    if not name or not email:
        return jsonify({"message": "Name and email are required."})
    token   = secrets.token_urlsafe(32)
    expires = (datetime.utcnow() + timedelta(hours=48)).isoformat() + "Z"
    try:
        supabase_client.table("employees").insert({
            "name":               name,
            "email":              email,
            "password_hash":      generate_password_hash(secrets.token_hex(16)),  # placeholder
            "active":             True,
            "setup_token":        token,
            "setup_token_expires": expires,
        }).execute()
        sent = _send_setup_email(name, email, token)
        msg = f"{name} added. Setup email {'sent to ' + email if sent else 'could not be sent — check RESEND_API_KEY'}."
        return jsonify({"message": msg})
    except Exception as exc:
        return jsonify({"message": f"Error: {exc}"})


@app.route("/api/remove-employee/<emp_id>", methods=["POST"])
@require_role("owner")
def api_remove_employee(emp_id):
    if not supabase_client:
        return jsonify({"ok": False})
    supabase_client.table("employees").update({"active": False}).eq("id", emp_id).execute()
    return jsonify({"ok": True})


@app.route("/api/delete-employee/<emp_id>", methods=["POST"])
@require_role("owner")
def api_delete_employee(emp_id):
    """Permanently delete an employee record from the database."""
    if not supabase_client:
        return jsonify({"ok": False, "error": "No DB"})
    supabase_client.table("employees").delete().eq("id", emp_id).execute()
    return jsonify({"ok": True})


@app.route("/api/resend-invite", methods=["POST"])
@require_role("owner")
def api_resend_invite():
    if not supabase_client:
        return jsonify({"message": "No database"})
    d = request.get_json()
    emp_id = d.get("id")
    if not emp_id:
        return jsonify({"message": "Employee ID is required."})
    try:
        res = supabase_client.table("employees").select("name,email").eq("id", emp_id).execute()
        emp = (res.data or [{}])[0]
        token   = secrets.token_urlsafe(32)
        expires = (datetime.utcnow() + timedelta(hours=48)).isoformat() + "Z"
        supabase_client.table("employees").update({
            "setup_token":         token,
            "setup_token_expires": expires,
        }).eq("id", emp_id).execute()
        sent = _send_setup_email(emp.get("name",""), emp.get("email",""), token)
        return jsonify({"message": f"Setup email {'sent to ' + emp.get('email','') if sent else 'failed — check RESEND_API_KEY'}."})
    except Exception as exc:
        return jsonify({"message": f"Error: {exc}"})


@app.route("/api/reset-employee-password", methods=["POST"])
@require_role("owner")
def api_reset_employee_password():
    if not supabase_client:
        return jsonify({"message": "No database"})
    d = request.get_json()
    emp_id = d.get("id")
    if not emp_id:
        return jsonify({"message": "Employee ID is required."})
    try:
        res = supabase_client.table("employees").select("name,email").eq("id", emp_id).execute()
        emp = (res.data or [{}])[0]
        token   = secrets.token_urlsafe(32)
        expires = (datetime.utcnow() + timedelta(hours=48)).isoformat() + "Z"
        supabase_client.table("employees").update({
            "setup_token":         token,
            "setup_token_expires": expires,
        }).eq("id", emp_id).execute()
        sent = _send_setup_email(emp.get("name",""), emp.get("email",""), token)
        return jsonify({"message": f"Password reset email {'sent' if sent else 'failed — check RESEND_API_KEY'}."})
    except Exception as exc:
        return jsonify({"message": f"Error: {exc}"})


# ---------------------------------------------------------------------------
# API: MANUAL DAILY REPORTS TRIGGER
# ---------------------------------------------------------------------------
@app.route("/api/send-daily-reports", methods=["POST"])
@require_role("owner")
def api_send_daily_reports():
    threading.Thread(target=_run_daily_reports, daemon=True).start()
    return jsonify({"message": "Reports are being sent to all clients with check-ins today."})


def _build_report_content(client_name: str, client_email: str, site_keyword: str):
    """Generate report content for a client without sending. Returns dict with ok/subject/plain_body/html_body/message."""
    today = date.today().isoformat()
    if not supabase_client:
        return {"ok": False, "message": "Database not connected."}
    checkins = supabase_client.table("checkins").select("*").eq("entry_date", today).execute().data or []
    entries = [c for c in checkins if site_keyword.lower() in (c.get("site_address") or "").lower()]
    if not entries:
        return {"ok": False, "message": f"No check-ins found today for site keyword '{site_keyword}'."}
    crew = [e["worker_name"] for e in entries]
    work_completed = "\n\n".join(
        f"{e['worker_name']}: {e.get('work_description','')}" for e in entries if e.get("work_description")
    )
    plans = [e.get("tomorrows_plan","") for e in entries if e.get("tomorrows_plan")]
    tracker = WorkforceTracker()
    for name in crew:
        tracker.add_worker(Worker(worker_id=name, name=name))
    dr = DailyReport(
        report_date=today, job_id="",
        site_address=entries[0].get("site_address",""),
        client_name=client_name, client_email=client_email,
        crew_present=crew, work_completed=work_completed,
        work_planned=" | ".join(plans), issues="", overall_status="On Schedule",
    )
    reporter = DailyReportSender(
        client=_anthropic.Anthropic(),
        smtp_host=ZOHO_SMTP_HOST, smtp_port=ZOHO_SMTP_PORT,
        user=ZOHO_EMAIL, password=ZOHO_PASSWORD, from_email=ZOHO_EMAIL,
    )
    content = reporter.generate(dr, tracker)
    _augment_report_with_ask_lumia(content, site_keyword, client_name, client_email)
    return {
        "ok": True,
        "subject":    content.get("subject", f"Daily Site Report — {dr.site_address} — {today}"),
        "html_body":  content.get("html_body", ""),
        "plain_body": content.get("plain_body", ""),
    }


@app.route("/api/preview-report", methods=["POST"])
@require_role("owner")
def api_preview_report():
    """Generate a report and return the content for preview — does NOT send email."""
    d = request.get_json()
    try:
        result = _build_report_content(
            client_name=d.get("client_name",""),
            client_email=d.get("client_email",""),
            site_keyword=d.get("site_keyword",""),
        )
        return jsonify(result)
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Error: {exc}"})


@app.route("/api/send-client-report", methods=["POST"])
@require_role("owner")
def api_send_client_report():
    """Send today's report to one specific client immediately."""
    d = request.get_json()
    client_email   = (d.get("client_email") or "").strip()
    client_name    = (d.get("client_name") or "").strip()
    site_keyword   = (d.get("site_keyword") or "").strip().lower()
    # Look up second email from clients table if not passed directly
    client_email_2 = (d.get("client_email_2") or "").strip()
    if not client_email_2 and supabase_client and site_keyword:
        try:
            rows = supabase_client.table("clients").select("client_email_2") \
                .ilike("site_keyword", f"%{site_keyword}%").limit(1).execute().data or []
            if rows:
                client_email_2 = (rows[0].get("client_email_2") or "").strip()
        except Exception:
            pass
    if not client_email or not site_keyword:
        return jsonify({"ok": False, "message": "Missing client email or site keyword."})

    today = date.today().isoformat()
    if not supabase_client:
        return jsonify({"ok": False, "message": "Database not connected."})

    checkins = supabase_client.table("checkins").select("*") \
        .eq("entry_date", today).execute().data or []
    # Filter to this client's site
    entries = [c for c in checkins if site_keyword in (c.get("site_address") or "").lower()]

    if not entries:
        return jsonify({"ok": False, "message": f"No check-ins found today for '{site_keyword}'."})

    crew = [e["worker_name"] for e in entries]
    work_completed = "\n\n".join(
        f"{e['worker_name']}: {e.get('work_description','')}" for e in entries if e.get("work_description")
    )
    plans = [e.get("tomorrows_plan","") for e in entries if e.get("tomorrows_plan")]

    tracker = WorkforceTracker()
    for name in crew:
        tracker.add_worker(Worker(worker_id=name, name=name))

    dr = DailyReport(
        report_date=today,
        job_id="",
        site_address=entries[0].get("site_address",""),
        client_name=client_name,
        client_email=client_email,
        crew_present=crew,
        work_completed=work_completed,
        work_planned=" | ".join(plans),
        issues="",
        overall_status="On Schedule",
    )

    try:
        reporter = DailyReportSender(
            client=_anthropic.Anthropic(),
            smtp_host=ZOHO_SMTP_HOST,
            smtp_port=ZOHO_SMTP_PORT,
            user=ZOHO_EMAIL,
            password=ZOHO_PASSWORD,
            from_email=ZOHO_EMAIL,
        )
        content = reporter.generate(dr, tracker)
        _augment_report_with_ask_lumia(content, site_keyword, client_name, client_email)
        subject   = content.get("subject", f"Daily Site Report — {entries[0].get('site_address','')} — {today}")
        html_body = content.get("html_body", "")
        plain_body = content.get("plain_body", "")
        # Send via Resend (SMTP is blocked on Railway)
        import httpx
        resend_key = os.getenv("RESEND_API_KEY", "")
        if not resend_key:
            return jsonify({"ok": False, "message": "RESEND_API_KEY not set."})
        recipients = [client_email]
        if client_email_2 and client_email_2 not in recipients:
            recipients.append(client_email_2)
        cc_list = [OWNER_EMAIL] if OWNER_EMAIL and OWNER_EMAIL not in recipients else []
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
            json={"from": "Ashrah Painting <noreply@ashrah.ai>", "to": recipients,
                  "cc": cc_list,
                  "subject": subject, "html": html_body, "text": plain_body},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            # Log the sent report so owner can review it later
            try:
                if supabase_client:
                    supabase_client.table("sent_reports").insert({
                        "client_name":  client_name,
                        "client_email": client_email,
                        "site_address": dr.site_address,
                        "subject":      subject,
                        "plain_body":   plain_body,
                        "html_body":    html_body,
                    }).execute()
            except Exception:
                pass
            return jsonify({"ok": True, "message": f"Report sent to {client_email}."})
        return jsonify({"ok": False, "message": f"Email API error {resp.status_code}: {resp.text}"})
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Error: {exc}"})


@app.route("/api/compose-email", methods=["POST"])
@require_role("owner")
def api_compose_email():
    """Generate a custom client intro/assignment email and optionally send it."""
    import httpx as _httpx
    d = request.get_json()
    to_name    = (d.get("to_name") or "").strip()
    to_email   = (d.get("to_email") or "").strip()
    context    = (d.get("context") or "").strip()   # freeform notes: job details, crew, etc.
    send_now   = d.get("send_now", False)

    if not to_email:
        return jsonify({"ok": False, "message": "Recipient email is required."})

    # Pull job data from Supabase to enrich the email
    job_context = ""
    if supabase_client:
        try:
            jobs = supabase_client.table("jobs").select("*") \
                .order("created_at", desc=True).limit(30).execute().data or []
            # Find jobs that match the recipient name or any keyword from context
            search = (to_name + " " + context).lower()
            matched = [
                j for j in jobs
                if to_name.lower() in (j.get("client_name") or "").lower()
                or any(w in (j.get("site_address") or "").lower() for w in search.split() if len(w) > 3)
            ]
            if matched:
                j = matched[0]
                crew = (j.get("assigned_employees") or [])
                job_context = (
                    f"Job: {j.get('client_name')} at {j.get('site_address')}\n"
                    f"Start Date: {j.get('start_date') or 'TBD'}\n"
                    f"Assigned Crew: {', '.join(crew) if crew else 'TBD'}\n"
                    f"Work: {(j.get('work_description') or '')[:300]}"
                )
        except Exception:
            pass

    ai_prompt = f"""Write an email from Ashrah Painting to {to_name}.

{f"Job details:{chr(10)}{job_context}" if job_context else ""}
{f"Additional context / purpose:{chr(10)}{context}" if context else ""}

WRITING RULES — follow these exactly:

Tone: direct, confident, professional. Like a senior contractor talking to a client — not a call centre agent.

BANNED — never use these phrases:
- "I hope this email finds you well"
- "Please don't hesitate to reach out"
- "Going forward" / "moving forward"
- "It's my pleasure" / "It was a pleasure"
- "I wanted to reach out" / "I wanted to touch base"
- "At your earliest convenience"
- "Please find attached"
- "Thank you for your continued support"
- "We appreciate your patience"
- Any filler that sounds like a template

FORMAT:
- Subject line on the first line: "Subject: ..."
- Blank line
- Email body (under 180 words — be concise, every sentence earns its place)
- Sign off: Ahmad Ashrah, CEO — Ashrah Painting
- Last line only: "For questions: ahmad@ashrahpainting.ca"

Write like a real person. Short sentences. Say what needs to be said, nothing more."""

    try:
        ai_client = _anthropic.Anthropic()
        resp = ai_client.messages.create(
            model=MODEL, max_tokens=800,
            messages=[{"role": "user", "content": ai_prompt}]
        )
        raw = resp.content[0].text.strip()
        # Parse subject vs body
        lines = raw.split("\n")
        subject = ""
        body_lines = []
        for i, line in enumerate(lines):
            if line.lower().startswith("subject:"):
                subject = line[8:].strip()
            else:
                body_lines.extend(lines[i:])
                break
        plain_body = "\n".join(body_lines).strip()
        html_body  = "<p>" + plain_body.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
        subject    = subject or f"Welcome — Ashrah Painting × Lumia"
    except Exception as exc:
        return jsonify({"ok": False, "message": f"AI error: {exc}"})

    if not send_now:
        return jsonify({"ok": True, "subject": subject, "plain_body": plain_body,
                        "html_body": html_body, "to_name": to_name, "to_email": to_email})

    # Send immediately
    resend_key = os.getenv("RESEND_API_KEY", "")
    if not resend_key:
        return jsonify({"ok": False, "message": "RESEND_API_KEY not set."})
    try:
        cc = [OWNER_EMAIL] if OWNER_EMAIL and OWNER_EMAIL != to_email else []
        r = _httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
            json={"from": "Ashrah Painting <noreply@ashrah.ai>",
                  "to": [to_email], "cc": cc,
                  "subject": subject, "html": html_body, "text": plain_body},
            timeout=20,
        )
        sent = r.status_code in (200, 201)
        if sent and supabase_client:
            try:
                supabase_client.table("sent_reports").insert({
                    "client_name": to_name, "client_email": to_email,
                    "site_address": "intro email",
                    "subject": subject, "plain_body": plain_body, "html_body": html_body,
                }).execute()
            except Exception:
                pass
        return jsonify({"ok": sent, "message": f"Email {'sent' if sent else 'failed'} → {to_email}" + (" (CC: you)" if cc else "")})
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Send error: {exc}"})


@app.route("/api/sent-reports")
@require_role("owner")
def api_sent_reports():
    if not supabase_client:
        return jsonify([])
    try:
        rows = supabase_client.table("sent_reports").select("*") \
            .order("sent_at", desc=True).limit(30).execute().data or []
        return jsonify(rows)
    except Exception as exc:
        return jsonify([])


@app.route("/api/report-schedule", methods=["GET"])
@require_role("owner")
def api_get_report_schedule():
    """Return the current auto-send time."""
    hour, minute = 18, 0
    if supabase_client:
        try:
            row = supabase_client.table("settings").select("value") \
                .eq("key", "report_schedule_time").execute().data
            if row:
                hour, minute = map(int, row[0]["value"].split(":"))
        except Exception:
            pass
    return jsonify({"ok": True, "time": f"{hour:02d}:{minute:02d}"})


@app.route("/api/report-schedule", methods=["POST"])
@require_role("owner")
def api_set_report_schedule():
    """Update the auto-send time and reschedule the job."""
    d = request.get_json()
    time_str = (d.get("time") or "").strip()
    try:
        hour, minute = map(int, time_str.split(":"))
        assert 0 <= hour <= 23 and 0 <= minute <= 59
    except Exception:
        return jsonify({"ok": False, "message": "Invalid time format. Use HH:MM."})

    # Persist to Supabase settings table
    if supabase_client:
        try:
            existing = supabase_client.table("settings").select("id") \
                .eq("key", "report_schedule_time").execute().data
            if existing:
                supabase_client.table("settings").update({"value": time_str}) \
                    .eq("key", "report_schedule_time").execute()
            else:
                supabase_client.table("settings").insert(
                    {"key": "report_schedule_time", "value": time_str}
                ).execute()
        except Exception as exc:
            print(f"[Schedule] Could not save to DB: {exc}")

    # Reschedule the APScheduler job
    try:
        _scheduler.reschedule_job(
            "daily_reports",
            trigger="cron",
            hour=hour,
            minute=minute,
        )
        print(f"[Scheduler] Rescheduled daily reports to {hour:02d}:{minute:02d} Winnipeg time")
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Saved but scheduler error: {exc}"})

    return jsonify({"ok": True, "message": f"Auto-send updated to {time_str} Winnipeg time."})


def _run_daily_reports() -> None:
    """Aggregate today's check-ins by site/client and send one consolidated report per client."""
    today = date.today().isoformat()
    print(f"[Scheduler] Running daily reports for {today}")
    if not supabase_client:
        print("[Scheduler] Supabase not configured — skipping")
        return
    try:
        checkins = supabase_client.table("checkins").select("*").eq("entry_date", today).execute().data or []
        # Also pull from Supabase clients table
        db_clients = supabase_client.table("clients").select("*").execute().data or []
    except Exception as exc:
        print(f"[Scheduler] Error fetching data: {exc}")
        return

    # Build combined client lookup: hardcoded CLIENTS + DB clients
    all_clients: dict[str, dict] = dict(CLIENTS)
    for c in db_clients:
        kw = (c.get("site_keyword") or "").lower().strip()
        if kw:
            all_clients[kw] = {
                "client_name":    c["client_name"],
                "client_email":   c["client_email"],
                "client_email_2": (c.get("client_email_2") or "").strip() or None,
            }

    # Group check-ins by matching client keyword
    client_checkins: dict[str, list] = {}
    for ci in checkins:
        site_lower = (ci.get("site_address") or "").lower()
        for keyword, info in all_clients.items():
            if keyword in site_lower:
                key = info["client_email"]
                client_checkins.setdefault(key, {"info": info, "keyword": keyword, "entries": []})
                client_checkins[key]["entries"].append(ci)
                break

    if not client_checkins:
        print(f"[Scheduler] No client check-ins found for {today}")
        return

    tracker = WorkforceTracker()
    reporter = DailyReportSender(
        client=_anthropic.Anthropic(),
        smtp_host=ZOHO_SMTP_HOST,
        smtp_port=ZOHO_SMTP_PORT,
        user=ZOHO_EMAIL,
        password=ZOHO_PASSWORD,
        from_email=ZOHO_EMAIL,
    )

    for email_key, bucket in client_checkins.items():
        info    = bucket["info"]
        keyword = bucket.get("keyword", "")
        entries = bucket["entries"]
        crew    = [e["worker_name"] for e in entries]
        for name in crew:
            tracker.add_worker(Worker(worker_id=name, name=name))
        work_completed = "\n\n".join(
            f"{e['worker_name']}: {e.get('work_description','')}" for e in entries if e.get("work_description")
        )
        plans = [e.get("tomorrows_plan","") for e in entries if e.get("tomorrows_plan")]
        dr = DailyReport(
            report_date=today,
            job_id="",
            site_address=(entries[0].get("site_address") or ""),
            client_name=info["client_name"],
            client_email=info["client_email"],
            crew_present=crew,
            work_completed=work_completed,
            work_planned=" | ".join(plans),
            issues="",
            overall_status="On Schedule",
        )
        try:
            import httpx as _httpx
            resend_key = os.getenv("RESEND_API_KEY", "")
            content = reporter.generate(dr, tracker)
            _augment_report_with_ask_lumia(content, keyword, dr.client_name, dr.client_email)
            subject   = content.get("subject", f"Daily Site Report — {dr.site_address} — {today}")
            html_body = content.get("html_body", "")
            plain_body = content.get("plain_body", "")
            recipients = [dr.client_email]
            email2 = info.get("client_email_2")
            if email2 and email2 not in recipients:
                recipients.append(email2)
            cc_list = [OWNER_EMAIL] if OWNER_EMAIL and OWNER_EMAIL not in recipients else []
            if resend_key:
                resp = _httpx.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
                    json={"from": "Ashrah Painting <noreply@ashrah.ai>", "to": recipients,
                          "cc": cc_list,
                          "subject": subject, "html": html_body, "text": plain_body},
                    timeout=15,
                )
                sent = resp.status_code in (200, 201)
                if sent:
                    try:
                        supabase_client.table("sent_reports").insert({
                            "client_name":  dr.client_name,
                            "client_email": dr.client_email,
                            "site_address": dr.site_address,
                            "subject":      subject,
                            "plain_body":   plain_body,
                            "html_body":    html_body,
                        }).execute()
                    except Exception:
                        pass
            else:
                sent = False
            print(f"[Scheduler] Report {'sent' if sent else 'FAILED'} → {dr.client_email}")
        except Exception as exc:
            print(f"[Scheduler] Report error for {dr.client_email}: {exc}")


# ---------------------------------------------------------------------------
# NIGHTLY CLIENT-ESCALATION DIGEST — emails Ahmad unresolved client questions
# ---------------------------------------------------------------------------
def _run_client_escalation_digest() -> None:
    if not supabase_client or not OWNER_EMAIL:
        return
    try:
        rows = supabase_client.table("client_escalations") \
            .select("id,client_id,question,assistant_response,created_at") \
            .is_("resolved_at", "null") \
            .is_("notified_at", "null") \
            .order("created_at").execute().data or []
    except Exception as exc:
        print(f"[Digest] fetch error: {exc}")
        return
    if not rows:
        return

    client_ids = list({r["client_id"] for r in rows if r.get("client_id")})
    name_by_id: dict[str, str] = {}
    try:
        crows = supabase_client.table("clients").select("id,client_name,client_email") \
            .in_("id", client_ids).execute().data or []
        name_by_id = {c["id"]: f"{c.get('client_name','')} ({c.get('client_email','')})" for c in crows}
    except Exception:
        pass

    blocks = []
    for r in rows:
        who = name_by_id.get(r.get("client_id"), "Client")
        blocks.append(
            f"<p><b>{who}</b> &mdash; <span style='color:#666'>{r.get('created_at','')}</span><br>"
            f"<b>Q:</b> {r.get('question','')}<br>"
            f"<b>Lumia reply:</b> {r.get('assistant_response','')}</p>"
        )
    html = "<h2>Lumia — pending client follow-ups</h2>" + "\n".join(blocks)
    plain = "\n\n".join(
        f"{name_by_id.get(r.get('client_id'),'Client')} ({r.get('created_at','')})\n"
        f"Q: {r.get('question','')}\nLumia reply: {r.get('assistant_response','')}"
        for r in rows
    )

    try:
        import httpx as _httpx
        resend_key = os.getenv("RESEND_API_KEY", "")
        if not resend_key:
            print("[Digest] No RESEND_API_KEY — skipping email")
            return
        resp = _httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
            json={
                "from":    "Lumia — Ashrah Painting <noreply@ashrah.ai>",
                "to":      [OWNER_EMAIL],
                "subject": f"Lumia: {len(rows)} client question(s) waiting on you",
                "html":    html,
                "text":    plain,
            },
            timeout=15,
        )
        if resp.status_code in (200, 201):
            now = datetime.utcnow().isoformat()
            for r in rows:
                try:
                    supabase_client.table("client_escalations") \
                        .update({"notified_at": now}).eq("id", r["id"]).execute()
                except Exception:
                    pass
            print(f"[Digest] Sent {len(rows)} escalation(s) to {OWNER_EMAIL}")
        else:
            print(f"[Digest] Email failed: {resp.status_code} {resp.text}")
    except Exception as exc:
        print(f"[Digest] send error: {exc}")


# ---------------------------------------------------------------------------
# BACKGROUND SCHEDULER — end-of-day client reports at 18:00 Winnipeg time
# ---------------------------------------------------------------------------
try:
    _scheduler = BackgroundScheduler(timezone="America/Winnipeg")
    _scheduler.add_job(_run_daily_reports, "cron", hour=18, minute=0,
                       id="daily_reports", replace_existing=True)
    _scheduler.add_job(_run_client_escalation_digest, "cron", hour=20, minute=0,
                       id="client_escalation_digest", replace_existing=True)
    _scheduler.start()
    print("[Scheduler] Daily reports at 18:00, client escalation digest at 20:00 Winnipeg time")
except Exception as _sched_exc:
    print(f"[Scheduler] Could not start scheduler: {_sched_exc}")


# ---------------------------------------------------------------------------
# INBOUND EMAIL WEBHOOK — lumia@ashrah.ai replies automatically
# ---------------------------------------------------------------------------
@app.route("/webhook/inbound-email", methods=["POST"])
def webhook_inbound_email():
    """Resend forwards inbound emails here. Lumia reads, thinks, and replies."""
    import httpx as _httpx

    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}

    sender      = data.get("from", "")
    sender_name = data.get("from_name", sender.split("<")[0].strip())
    subject     = data.get("subject", "")
    body_text   = data.get("text", "") or data.get("plain", "") or ""
    body_html   = data.get("html", "")

    # Strip HTML if only html available
    if not body_text and body_html:
        import re
        body_text = re.sub(r'<[^>]+>', ' ', body_html).strip()

    # Extract sender email
    import re as _re
    email_match = _re.search(r'[\w.+-]+@[\w.-]+\.\w+', sender)
    reply_to = email_match.group(0) if email_match else sender

    if not reply_to:
        return jsonify({"ok": False, "message": "No sender address"}), 200

    # Don't reply to ourselves or bounce loops
    if "noreply" in reply_to.lower() or "no-reply" in reply_to.lower():
        return jsonify({"ok": True, "message": "Ignored no-reply sender"}), 200

    print(f"[Inbound] Email from {reply_to} | Subject: {subject}")

    # ── Build context from Supabase ──────────────────────────────────────────
    context_parts = []
    if supabase_client:
        try:
            checkins = supabase_client.table("checkins").select("*") \
                .order("entry_date", desc=True).limit(60).execute().data or []
            if checkins:
                rows = [
                    f"  [{c['entry_date']}] {c['worker_name']} @ {c['site_address']} | "
                    f"avg={c.get('avg_score','?')}/10 | {(c.get('work_description') or '')[:100]}"
                    for c in checkins
                ]
                context_parts.append("RECENT CHECK-INS:\n" + "\n".join(rows))
        except Exception:
            pass
        try:
            jobs = supabase_client.table("jobs").select("*") \
                .order("created_at", desc=True).limit(20).execute().data or []
            if jobs:
                rows = [
                    f"  [{j.get('status','?').upper()}] {j.get('client_name','?')} @ {j.get('site_address','?')} | "
                    f"crew: {', '.join(j.get('assigned_employees') or [])} | start: {j.get('start_date','TBD')}"
                    for j in jobs
                ]
                context_parts.append("JOBS:\n" + "\n".join(rows))
        except Exception:
            pass
        try:
            clients = supabase_client.table("clients").select("*").execute().data or []
            if clients:
                rows = [f"  {c.get('client_name')} | {c.get('client_email')} | keyword: {c.get('site_keyword')}" for c in clients]
                context_parts.append("CLIENTS:\n" + "\n".join(rows))
        except Exception:
            pass

    data_context = "\n\n".join(context_parts) if context_parts else "(no data available)"
    today = date.today().isoformat()

    system_prompt = f"""You are Lumia, the operations assistant for Ashrah Painting in Winnipeg, Canada — owned by Ahmad Ashrah (CEO).

You are replying to an email sent to lumia@ashrah.ai. You have access to live company data below — use it to give specific, accurate answers.

Today's date: {today}

--- LIVE COMPANY DATA ---
{data_context}
--- END DATA ---

WRITING RULES:
- Write like a professional person, not a template. Direct and clear.
- BANNED phrases — never use: "I hope this email finds you well", "Please don't hesitate to reach out", "Going forward", "It was a pleasure", "I wanted to touch base", "At your earliest convenience", "Thank you for your continued support", or any filler language.
- Short answers. Say what needs to be said, nothing extra.
- Never invent facts. If you don't know, say: "Contact Ahmad directly at ahmad@ashrahpainting.ca."
- Sign off as: Lumia | Ashrah Painting | info@ashrahpainting.ca
- Add one final line: "Automated response — Lumia, Ashrah Painting operations system."
- Plain text only, no markdown."""

    try:
        ai_client = _anthropic.Anthropic()
        resp = ai_client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": f"Email from {sender_name} ({reply_to}):\nSubject: {subject}\n\n{body_text}"
            }]
        )
        reply_body = resp.content[0].text.strip()
    except Exception as exc:
        print(f"[Inbound] AI error: {exc}")
        return jsonify({"ok": False}), 200

    # Send the reply
    resend_key = os.getenv("RESEND_API_KEY", "")
    if not resend_key:
        print("[Inbound] No RESEND_API_KEY — cannot reply")
        return jsonify({"ok": False}), 200

    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    reply_html = "<p>" + reply_body.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"

    try:
        cc = [OWNER_EMAIL] if OWNER_EMAIL and OWNER_EMAIL != reply_to else []
        r = _httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
            json={
                "from":    "Lumia — Ashrah Painting <noreply@ashrah.ai>",
                "to":      [reply_to],
                "cc":      cc,
                "subject": reply_subject,
                "html":    reply_html,
                "text":    reply_body,
            },
            timeout=20,
        )
        print(f"[Inbound] Reply {'sent' if r.status_code in (200,201) else 'FAILED'} → {reply_to}")
    except Exception as exc:
        print(f"[Inbound] Reply error: {exc}")

    return jsonify({"ok": True}), 200


# ---------------------------------------------------------------------------
# ESTIMATES API
# ---------------------------------------------------------------------------

@app.route("/api/estimates/upload", methods=["POST"])
@require_role("owner")
def api_estimates_upload():
    """Receive a PDF, create a job, kick off background extraction."""
    if "pdf" not in request.files:
        return jsonify({"ok": False, "error": "No PDF file uploaded."})
    f = request.files["pdf"]
    if not f.filename or not f.filename.lower().endswith(".pdf"):
        return jsonify({"ok": False, "error": "File must be a PDF."})
    client_name  = (request.form.get("client_name") or "").strip()
    site_address = (request.form.get("site_address") or "").strip()
    pdf_bytes    = f.read()
    if len(pdf_bytes) == 0:
        return jsonify({"ok": False, "error": "Uploaded file is empty."})
    job_id = lumia_estimates.create_job(f.filename, client_name, site_address)
    lumia_estimates.start_extraction(job_id, pdf_bytes, f.filename,
                                     client_name, site_address)
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/estimates/status/<job_id>")
@require_role("owner")
def api_estimates_status(job_id):
    """Poll endpoint — returns status + progress message."""
    job = lumia_estimates.get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Job not found."}), 404
    return jsonify({
        "ok":       True,
        "status":   job.get("status"),
        "progress": job.get("progress"),
        "error":    job.get("error"),
    })


@app.route("/api/estimates/<job_id>")
@require_role("owner")
def api_estimates_result(job_id):
    """Return full job result (raw_json, paint_calc, work_order)."""
    job = lumia_estimates.get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Job not found."}), 404
    return jsonify({
        "ok":         True,
        "status":     job.get("status"),
        "raw_json":   job.get("raw_json"),
        "paint_calc": job.get("paint_calc"),
        "work_order": job.get("work_order"),
        "error":      job.get("error"),
    })


@app.route("/api/estimates/<job_id>/create-job", methods=["POST"])
@require_role("owner")
def api_estimates_create_job(job_id):
    """Create a Lumia job record from a completed estimate."""
    job = lumia_estimates.get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Estimate job not found."})
    if job.get("status") != "done":
        return jsonify({"ok": False, "error": "Estimate not complete yet."})
    pc           = job.get("paint_calc") or {}
    client_name  = job.get("client_name") or "Unknown"
    site_address = job.get("site_address") or "Unknown"
    scope        = pc.get("scope_summary") or f"Painting at {site_address}"
    lab          = pc.get("labor") or {}
    days         = lab.get("estimated_days", 1)
    painters     = lab.get("painters_recommended", 1)
    notes_parts  = [f"Generated from estimate — {job.get('file_name','')}"]
    if pc.get("assumptions"):
        notes_parts.append("Assumptions: " + "; ".join(pc["assumptions"]))
    notes = " | ".join(notes_parts)
    if not supabase_client:
        return jsonify({"ok": False, "error": "No database connection."})
    try:
        result = supabase_client.table("jobs").insert({
            "client_name":        client_name,
            "site_address":       site_address,
            "work_description":   scope,
            "status":             "open",
            "assigned_employees": [],
            "start_date":         datetime.utcnow().date().isoformat(),
            "painters_needed":    painters,
        }).execute()
        new_job = (result.data or [{}])[0]
        return jsonify({"ok": True, "job_id": new_job.get("id")})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("LUMIA_PORT", "5000")))
    print(f"\n  Lumia Check-In App running at http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
