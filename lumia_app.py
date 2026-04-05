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
        _notify_owner(entry)
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
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = ZOHO_EMAIL
        msg["To"]      = OWNER_EMAIL
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP_SSL(ZOHO_SMTP_HOST, int(ZOHO_SMTP_PORT)) as server:
            server.login(ZOHO_EMAIL, ZOHO_PASSWORD)
            server.sendmail(ZOHO_EMAIL, [OWNER_EMAIL], msg.as_string())
        print(f"[App] Owner email sent to {OWNER_EMAIL}")
    except Exception as exc:
        print(f"[App] Owner notify error: {exc}")


if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("LUMIA_PORT", "5000")))
    print(f"\n  Lumia Check-In App running at http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
