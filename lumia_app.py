"""
lumia_app.py — Lumia Employee Check-In Web App
"""
from __future__ import annotations

import json
import os
import smtplib
import threading
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import functools
import anthropic as _anthropic
from flask import (Flask, render_template_string, request, jsonify,
                   session, redirect, url_for)
from supabase import create_client

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

OWNER_PIN = os.getenv("OWNER_PIN", "")

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
        tracker.add_worker(Worker(worker_id=name, name=name, role="Painter", status="active"))

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
      background: #1F3864;
      color: #fff;
      text-align: center;
      padding: 28px 20px 20px;
    }
    .header h1 { font-size: 32px; font-weight: 800; letter-spacing: 3px; }
    .header p  { font-size: 13px; opacity: 0.8; margin-top: 4px; }

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
  </style>
</head>
<body>
<div class="card">
  <div class="header">
    <h1>LUMIA</h1>
    <p>Ashrah Painting &mdash; Daily Check-In</p>
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

      <div class="field">
        <label id="lbl_name">YOUR NAME</label>
        <select name="worker_name" required>
          <option value="" disabled selected id="lbl_selectName">Select your name</option>
          {% for emp in employees %}
          <option value="{{ emp }}">{{ emp }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="field">
        <label id="lbl_site">SITE ADDRESS</label>
        <input type="text" name="site_address" id="site_address_input"
               placeholder="e.g. 23 Falcon Rd, Winnipeg, MB" required>
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
        <textarea name="work_description" id="work_description_ta"
          placeholder="Write a brief summary of everything you did on site today..."
          required></textarea>
      </div>

      <!-- Tomorrow's Plan -->
      <div class="section-title" id="lbl_tomorrow">&#128203; Tomorrow's Plan</div>

      <div class="field">
        <textarea name="tomorrows_plan" id="tomorrows_plan_ta"
          placeholder="What is the plan for tomorrow at this site..."></textarea>
      </div>

      <div class="field">
        <label id="lbl_notes">NOTES (OPTIONAL)</label>
        <input type="text" name="notes" id="notes_input"
               placeholder="Any issues, delays, or extra info...">
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

<div class="footer">Lumia &mdash; Ashrah Painting Operations Agent</div>

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
    document.getElementById('site_address_input').placeholder = t.sitePh;
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

        entry = EmployeeDailyEntry(
            entry_date=date.today().isoformat(),
            worker_id="",
            worker_name=data.get("worker_name", "").strip(),
            site_address=data.get("site_address", "").strip(),
            job_id="",
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
                "from": "Lumia <onboarding@resend.dev>",
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
# LOGIN / LOGOUT
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
.header { background:#1F3864; color:#fff; text-align:center; padding:28px 20px; }
.header h1 { font-size:28px; font-weight:800; letter-spacing:3px; }
.header p  { font-size:12px; opacity:.8; margin-top:4px; }
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
  <div class="header"><h1>LUMIA</h1><p>Staff Login</p></div>
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

<div class="topbar">
  <h1>LUMIA &mdash; Owner</h1>
  <div style="display:flex;gap:20px;align-items:center">
    <span style="font-size:13px;opacity:.8">Welcome, {{ name }}</span>
    <a href="/logout">Logout</a>
  </div>
</div>

<div class="tabs">
  <div class="tab active" onclick="showTab('overview')">Overview</div>
  <div class="tab" onclick="showTab('checkins')">Check-Ins</div>
  <div class="tab" onclick="showTab('jobs')">Jobs</div>
  <div class="tab" onclick="showTab('managers')">Managers</div>
  <div class="tab" onclick="showTab('clients')">Clients</div>
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

<!-- JOBS -->
<div class="page" id="tab-jobs">
  <div class="card">
    <h2>New Job</h2>
    <form id="jobForm">
      <div class="form-row">
        <div class="field"><label>Client Name</label>
          <input type="text" name="client_name" required></div>
        <div class="field"><label>Site Address</label>
          <input type="text" name="site_address" required></div>
      </div>
      <div class="form-row">
        <div class="field"><label>Start Date</label>
          <input type="date" name="start_date"></div>
        <div class="field"><label>Painters Needed</label>
          <select name="painters_needed">
            <option value="1">1</option><option value="2" selected>2</option>
            <option value="3">3</option><option value="4">4</option>
          </select></div>
      </div>
      <div class="field"><label>Work Description</label>
        <textarea name="work_description" placeholder="Describe the job scope, type of work, any special requirements..."></textarea>
      </div>
      <button type="button" class="btn" id="matchBtn" onclick="matchCrew()">
        Get AI Crew Recommendation
      </button>
    </form>
    <div id="ai-result" style="display:none" class="ai-result"></div>
    <div id="assign-btns" style="display:none;margin-top:16px;gap:12px;display:none">
      <button class="btn btn-green" onclick="assignJob()">Confirm & Notify Employees</button>
    </div>
  </div>
  <div class="card">
    <h2>Active Jobs</h2>
    <div id="jobs-list"><p style="color:#999">Loading...</p></div>
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
        <div class="field"><label>Client Email</label>
          <input type="email" name="client_email" required></div>
      </div>
      <div class="field"><label>Site Address Keyword</label>
        <input type="text" name="site_keyword"
               placeholder="e.g. '23 falcon' — must appear in the site address"></div>
      <button type="button" class="btn" onclick="addClient()">Save Client</button>
    </form>
  </div>
  <div class="card">
    <h2>Registered Clients</h2>
    <div id="clients-list"><p style="color:#999">Loading...</p></div>
  </div>
</div>

<script>
let lastRecommendation = null;

function showTab(name) {
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.remove('active'));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  if (name === 'overview')  loadOverview();
  if (name === 'checkins')  loadCheckins();
  if (name === 'jobs')      loadJobs();
  if (name === 'managers')  loadManagers();
  if (name === 'clients')   loadClients();
}

function scoreColor(v) {
  if (v >= 8) return '#4CAF50'; if (v >= 5) return '#f0ad4e'; return '#d9534f';
}
function trustBadge(t) {
  if (t === 'trusted') return '<span class="badge badge-green">Trusted</span>';
  if (t === 'watch')   return '<span class="badge badge-yellow">Watch</span>';
  return '<span class="badge badge-red">Concern</span>';
}

async function loadOverview() {
  const r = await fetch('/api/checkins?limit=10'); const d = await r.json();
  const rows = d.map(c => `<tr>
    <td>${c.entry_date}</td><td><b>${c.worker_name}</b></td><td>${c.site_address}</td>
    <td><span style="font-weight:700;color:${scoreColor(c.avg_score)}">${c.avg_score}/10</span></td>
    <td>${(c.work_description||'').substring(0,60)}...</td></tr>`).join('');
  document.getElementById('overview-checkins').innerHTML =
    '<table><tr><th>Date</th><th>Employee</th><th>Site</th><th>Avg</th><th>Summary</th></tr>' + rows + '</table>';
  const today = d.filter(c => c.entry_date === new Date().toISOString().split('T')[0]);
  document.getElementById('stat-checkins').textContent = today.length;
  const avg = today.length ? (today.reduce((a,c) => a + (c.avg_score||0), 0) / today.length).toFixed(1) : '—';
  document.getElementById('stat-avg').textContent = avg;
  const jr = await fetch('/api/jobs'); const jd = await jr.json();
  document.getElementById('stat-jobs').textContent = jd.filter(j => j.status === 'open').length;
}

async function loadCheckins() {
  const dt = document.getElementById('filter-date').value;
  const emp = document.getElementById('filter-emp').value;
  let url = '/api/checkins?limit=50';
  if (dt) url += '&date=' + dt; if (emp) url += '&employee=' + encodeURIComponent(emp);
  const r = await fetch(url); const d = await r.json();
  const rows = d.map(c => `<tr>
    <td>${c.entry_date}</td><td><b>${c.worker_name}</b></td><td>${c.site_address}</td>
    <td style="color:${scoreColor(c.avg_score)};font-weight:700">${c.avg_score}/10</td>
    <td>${(c.work_description||'').substring(0,80)}</td>
    <td><button class="btn btn-sm" onclick="reviewCheckin('${c.id}','${c.worker_name}')">Review</button></td>
  </tr>`).join('');
  document.getElementById('all-checkins').innerHTML =
    '<table><tr><th>Date</th><th>Employee</th><th>Site</th><th>Score</th><th>Summary</th><th></th></tr>' + rows + '</table>';
}

function reviewCheckin(id, name) {
  window.location.href = '/review?checkin_id=' + id;
}

async function loadJobs() {
  const r = await fetch('/api/jobs'); const d = await r.json();
  if (!d.length) { document.getElementById('jobs-list').innerHTML = '<p style="color:#999">No jobs yet.</p>'; return; }
  const rows = d.map(j => `<tr>
    <td><b>${j.client_name}</b></td><td>${j.site_address}</td>
    <td>${j.start_date||'—'}</td>
    <td>${(j.assigned_employees||[]).join(', ')||'—'}</td>
    <td><span class="badge ${j.status==='open'?'badge-yellow':'badge-green'}">${j.status}</span></td>
  </tr>`).join('');
  document.getElementById('jobs-list').innerHTML =
    '<table><tr><th>Client</th><th>Site</th><th>Start</th><th>Assigned</th><th>Status</th></tr>' + rows + '</table>';
}

async function matchCrew() {
  const form = document.getElementById('jobForm');
  const data = Object.fromEntries(new FormData(form));
  const btn = document.getElementById('matchBtn');
  btn.innerHTML = '<span class="spinner"></span>Analysing...';
  btn.disabled = true;
  const r = await fetch('/api/match-crew', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify(data)});
  const d = await r.json();
  btn.innerHTML = 'Get AI Crew Recommendation'; btn.disabled = false;
  const el = document.getElementById('ai-result');
  el.style.display = 'block'; el.textContent = d.result;
  lastRecommendation = d;
  document.getElementById('assign-btns').style.display = 'flex';
}

async function assignJob() {
  if (!lastRecommendation) return;
  const form = document.getElementById('jobForm');
  const data = Object.fromEntries(new FormData(form));
  data.recommendation = lastRecommendation.result;
  const r = await fetch('/api/save-job', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify(data)});
  const d = await r.json();
  alert(d.message || 'Job saved and employees notified!');
  loadJobs();
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
    <td><b>${c.client_name}</b></td><td>${c.client_email}</td>
    <td><code>${c.site_keyword}</code></td>
    <td><button class="btn btn-sm btn-red" onclick="removeClient('${c.id}')">Remove</button></td>
  </tr>`).join('');
  document.getElementById('clients-list').innerHTML =
    '<table><tr><th>Name</th><th>Email</th><th>Keyword</th><th></th></tr>' + rows + '</table>';
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

loadOverview();
</script>
</body></html>"""


@app.route("/owner")
@require_role("owner")
def owner_dashboard():
    return render_template_string(OWNER_HTML, name=session.get("name","Ahmad"), employees=EMPLOYEES)


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
  <h1>LUMIA — Review</h1>
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
  const dt = document.getElementById('review-date').value;
  const urlParams = new URLSearchParams(window.location.search);
  const targetId  = urlParams.get('checkin_id');
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

async function _loadReviews(dt) {


@app.route("/review")
@require_role("manager", "owner")
def review_page():
    return render_template_string(REVIEW_HTML,
                                  name=session.get("name"), role=session.get("role"))


# ---------------------------------------------------------------------------
# API ENDPOINTS
# ---------------------------------------------------------------------------

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
    try:
        supabase_client.table("clients").insert({
            "client_name":  d["client_name"],
            "client_email": d["client_email"],
            "site_keyword": d["site_keyword"].lower().strip(),
        }).execute()
        return jsonify({"message": f"Client {d['client_name']} saved."})
    except Exception as exc:
        return jsonify({"message": f"Error: {exc}"})


@app.route("/api/remove-client/<cid>", methods=["POST"])
@require_role("owner")
def api_remove_client(cid):
    if not supabase_client:
        return jsonify({"ok": False})
    supabase_client.table("clients").delete().eq("id", cid).execute()
    return jsonify({"ok": True})


@app.route("/api/jobs")
@require_role("owner")
def api_jobs():
    if not supabase_client:
        return jsonify([])
    return jsonify(supabase_client.table("jobs").select("*").order("created_at", desc=True).limit(20).execute().data or [])


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
    if supabase_client:
        supabase_client.table("jobs").insert({
            "client_name":       d.get("client_name"),
            "site_address":      d.get("site_address"),
            "work_description":  d.get("work_description"),
            "start_date":        d.get("start_date") or None,
            "painters_needed":   int(d.get("painters_needed", 2)),
            "status":            "open",
        }).execute()
    # TODO: email assigned employees (can be added once employees have emails in DB)
    return jsonify({"message": "Job saved successfully. Employee notification coming soon."})


if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("LUMIA_PORT", "5000")))
    print(f"\n  Lumia Check-In App running at http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
