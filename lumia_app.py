"""
lumia_app.py — Lumia Employee Check-In Web App
"""
from __future__ import annotations

import os
import smtplib
import threading
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic as _anthropic
from flask import Flask, render_template_string, request, jsonify

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
        "client_name":  "Khadija Jarkass",
        "client_email": "Khadijajarkass@icloud.com",
    },
    # "keyword from site address": {"client_name": "...", "client_email": "..."},
}


def _lookup_client(site_address: str) -> dict | None:
    site_lower = site_address.lower()
    for keyword, info in CLIENTS.items():
        if keyword in site_lower:
            return info
    return None


def _send_client_report(entry: EmployeeDailyEntry) -> None:
    """Generate and email a professional site report to the client for this site/date."""
    if not ZOHO_PASSWORD:
        return
    client_info = _lookup_client(entry.site_address)
    if not client_info:
        return  # no client registered for this site yet

    # Collect all of today's check-ins for this site
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
        work_planned="",
        issues="",
        overall_status="On Schedule",
    )

    # Build a minimal tracker so DailyReportSender can resolve names
    tracker = WorkforceTracker()
    for name in crew_names:
        tracker.add_worker(Worker(
            worker_id=name, name=name, role="Painter", status="active"
        ))

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
        sent    = reporter.send(content, to_email=dr.client_email, cc_emails=[OWNER_EMAIL])
        status  = "sent" if sent else "FAILED"
        print(f"[App] Client report {status} → {dr.client_email} ({dr.site_address})")
    except Exception as exc:
        print(f"[App] Client report error: {exc}")

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Lumia — Daily Check-In</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: Arial, sans-serif;
      background: #f0f4f9;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 32px 16px 48px;
    }
    .card {
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 4px 24px rgba(31,56,100,0.12);
      width: 100%;
      max-width: 560px;
      overflow: hidden;
    }
    .header {
      background: #1F3864;
      padding: 28px 32px;
      text-align: center;
    }
    .header h1 { color: #fff; font-size: 28px; letter-spacing: 1px; }
    .header p  { color: #a8c4e0; font-size: 14px; margin-top: 6px; }

    .form-body { padding: 28px 32px 36px; }

    .field { margin-bottom: 22px; }
    label {
      display: block;
      font-size: 12px;
      font-weight: bold;
      color: #1F3864;
      margin-bottom: 7px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    select, input[type="text"], textarea {
      width: 100%;
      padding: 11px 14px;
      border: 1.5px solid #dce6f1;
      border-radius: 7px;
      font-size: 15px;
      color: #222;
      background: #f8fafc;
      transition: border-color 0.2s;
      appearance: none;
    }
    select:focus, input[type="text"]:focus, textarea:focus {
      outline: none;
      border-color: #1F3864;
      background: #fff;
    }
    textarea { min-height: 100px; resize: vertical; }

    /* Section divider */
    .section-title {
      font-size: 13px;
      font-weight: bold;
      color: #fff;
      background: #2a4d8a;
      padding: 8px 14px;
      border-radius: 6px;
      margin: 28px 0 18px;
      letter-spacing: 0.5px;
    }

    /* Score rows */
    .score-row {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 16px;
    }
    .score-label {
      font-size: 13px;
      color: #333;
      width: 160px;
      flex-shrink: 0;
    }
    input[type="range"] {
      flex: 1;
      accent-color: #1F3864;
      cursor: pointer;
    }
    .score-badge {
      min-width: 40px;
      height: 40px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
      font-weight: bold;
      color: #fff;
      transition: background 0.3s;
      flex-shrink: 0;
    }

    .submit-btn {
      width: 100%;
      padding: 14px;
      background: #1F3864;
      color: #fff;
      border: none;
      border-radius: 8px;
      font-size: 16px;
      font-weight: bold;
      cursor: pointer;
      margin-top: 8px;
      transition: background 0.2s, transform 0.1s;
    }
    .submit-btn:hover    { background: #2a4d8a; }
    .submit-btn:active   { transform: scale(0.98); }
    .submit-btn:disabled { background: #a0aec0; cursor: not-allowed; }

    /* Success */
    .success {
      display: none;
      flex-direction: column;
      align-items: center;
      padding: 48px 32px;
      text-align: center;
    }
    .checkmark {
      width: 72px; height: 72px;
      background: #C6EFCE;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 36px;
      margin-bottom: 20px;
    }
    .success h2 { color: #1F3864; font-size: 22px; margin-bottom: 10px; }
    .success p  { color: #666; font-size: 15px; }
    .new-entry-btn {
      margin-top: 28px;
      padding: 11px 28px;
      background: #1F3864;
      color: #fff;
      border: none;
      border-radius: 7px;
      font-size: 15px;
      cursor: pointer;
    }
    .footer {
      margin-top: 24px;
      color: #a0aec0;
      font-size: 12px;
      text-align: center;
    }
    .spinner {
      display: inline-block;
      width: 18px; height: 18px;
      border: 2px solid #fff;
      border-top-color: transparent;
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
      vertical-align: middle;
      margin-right: 8px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
<div class="card">
  <div class="header">
    <h1>LUMIA</h1>
    <p>Ashrah Painting — Daily Check-In</p>
  </div>

  <!-- FORM -->
  <div class="form-body" id="formSection">
    <form id="checkinForm">

      <div class="field">
        <label>Your Name</label>
        <select name="worker_name" required>
          <option value="" disabled selected>Select your name</option>
          {% for emp in employees %}
          <option value="{{ emp }}">{{ emp }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="field">
        <label>Site Address</label>
        <input type="text" name="site_address" placeholder="e.g. 23 Falcon Rd, Winnipeg, MB" required>
      </div>

      <!-- Category Scores -->
      <div class="section-title">&#9733; Rate Your Work Today</div>

      {% for field_name, label_text in categories %}
      <div class="score-row">
        <span class="score-label">{{ label_text }}</span>
        <input type="range" name="{{ field_name }}" min="1" max="10" value="5"
               oninput="updateScore(this)" data-label="{{ field_name }}_val">
        <div class="score-badge" id="{{ field_name }}_val" style="background:#f0ad4e">5</div>
      </div>
      {% endfor %}

      <!-- Daily Summary -->
      <div class="section-title">&#9998; Daily Summary</div>

      <div class="field">
        <textarea name="work_description"
          placeholder="Write a brief summary of everything you did on site today..."
          required></textarea>
      </div>

      <div class="field">
        <label>Notes (optional)</label>
        <input type="text" name="notes" placeholder="Any issues, delays, or extra info...">
      </div>

      <button type="submit" class="submit-btn" id="submitBtn">Submit Check-In</button>
    </form>
  </div>

  <!-- SUCCESS -->
  <div class="success" id="successSection">
    <div class="checkmark">&#10003;</div>
    <h2>Check-In Submitted!</h2>
    <p id="successMsg">Your entry has been logged. Good work today.</p>
    <button class="new-entry-btn" onclick="resetForm()">Submit Another</button>
  </div>
</div>

<div class="footer">Lumia &mdash; Ashrah Painting Operations Agent</div>

<script>
  function scoreColor(val) {
    if (val >= 8) return '#4CAF50';
    if (val >= 5) return '#f0ad4e';
    return '#d9534f';
  }

  function updateScore(slider) {
    const badge = document.getElementById(slider.dataset.label);
    badge.textContent       = slider.value;
    badge.style.background  = scoreColor(parseInt(slider.value));
  }

  // Init all badges
  document.querySelectorAll('input[type="range"]').forEach(s => updateScore(s));

  document.getElementById('checkinForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('submitBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>Submitting...';

    const data = Object.fromEntries(new FormData(e.target));

    try {
      const res  = await fetch('/submit', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
      });
      const json = await res.json();

      if (json.ok) {
        document.getElementById('successMsg').textContent =
          'Logged for ' + data.worker_name + ' at ' + data.site_address + '. Good work today!';
        document.getElementById('formSection').style.display   = 'none';
        document.getElementById('successSection').style.display = 'flex';
      } else {
        alert('Something went wrong: ' + json.error);
        btn.disabled = false;
        btn.innerHTML = 'Submit Check-In';
      }
    } catch (err) {
      alert('Network error — please try again.');
      btn.disabled = false;
      btn.innerHTML = 'Submit Check-In';
    }
  });

  function resetForm() {
    document.getElementById('checkinForm').reset();
    document.querySelectorAll('input[type="range"]').forEach(s => updateScore(s));
    document.getElementById('submitBtn').disabled = false;
    document.getElementById('submitBtn').innerHTML = 'Submit Check-In';
    document.getElementById('successSection').style.display = 'none';
    document.getElementById('formSection').style.display    = 'block';
  }
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML, employees=EMPLOYEES, categories=CATEGORIES)


@app.route("/submit", methods=["POST"])
def submit():
    try:
        data = request.get_json()

        scores = [
            int(data.get("tape_covering",     5)),
            int(data.get("drop_sheets",        5)),
            int(data.get("patching_process",   5)),
            int(data.get("paint_execution",    5)),
            int(data.get("site_control",       5)),
            int(data.get("washing_tool_care",  5)),
        ]
        avg_score = round(sum(scores) / len(scores))

        entry = EmployeeDailyEntry(
            entry_date=date.today().isoformat(),
            worker_id="",
            worker_name=data.get("worker_name", "").strip(),
            site_address=data.get("site_address", "").strip(),
            job_id="",
            work_description=data.get("work_description", "").strip(),
            self_score=avg_score,
            notes=data.get("notes", "").strip(),
            tape_covering=scores[0],
            drop_sheets=scores[1],
            patching_process=scores[2],
            paint_execution=scores[3],
            site_control=scores[4],
            washing_tool_care=scores[5],
        )

        EmployeeLogSheet(EXCEL_LOG_PATH).append_entries([entry])
        _notify_owner(entry)
        threading.Thread(target=_send_client_report, args=(entry,), daemon=True).start()

        return jsonify({"ok": True})

    except Exception as exc:
        print(f"[App] Submit error: {exc}")
        return jsonify({"ok": False, "error": str(exc)}), 500


def _notify_owner(entry: EmployeeDailyEntry) -> None:
    if not ZOHO_PASSWORD:
        return
    try:
        subject = f"Lumia Check-In: {entry.worker_name} @ {entry.site_address}"
        body = (
            f"New check-in received.\n\n"
            f"Employee         : {entry.worker_name}\n"
            f"Site             : {entry.site_address}\n"
            f"Date             : {entry.entry_date}\n\n"
            f"Tape & Covering  : {entry.tape_covering}/10\n"
            f"Drop Sheets      : {entry.drop_sheets}/10\n"
            f"Patching Process : {entry.patching_process}/10\n"
            f"Paint Execution  : {entry.paint_execution}/10\n"
            f"Site Control     : {entry.site_control}/10\n"
            f"Washing & Tools  : {entry.washing_tool_care}/10\n"
            f"Avg Score        : {entry.self_score}/10\n\n"
            f"Summary:\n{entry.work_description}\n\n"
            f"Notes: {entry.notes or '—'}\n"
        )
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = ZOHO_EMAIL
        msg["To"]      = OWNER_EMAIL
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP_SSL(ZOHO_SMTP_HOST, ZOHO_SMTP_PORT) as server:
            server.login(ZOHO_EMAIL, ZOHO_PASSWORD)
            server.sendmail(ZOHO_EMAIL, [OWNER_EMAIL], msg.as_string())
    except Exception as exc:
        print(f"[App] Owner notify error: {exc}")


if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("LUMIA_PORT", "5000")))
    print(f"\n  Lumia Check-In App running at http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
