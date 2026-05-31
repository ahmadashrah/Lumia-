"""Lio outbound mailer — SMTP wrapper for cold outreach.

Reads config from environment. Defaults are Zoho-friendly to match Lumia's
existing infra; override anything via env if Lio's mailbox is on a different
provider.

Environment variables:
    LIO_SMTP_HOST       (default "smtp.zoho.com")
    LIO_SMTP_PORT       (default "465")  — SSL port; use 587 for STARTTLS
    LIO_SMTP_USE_SSL    (default "true") — set "false" to use STARTTLS instead
    LIO_SMTP_USER       (default "lio.ashrah@ashrahpainting.ca")
    LIO_SMTP_PASSWORD   (REQUIRED — Zoho/Workspace app password, not real password)
    LIO_FROM_EMAIL      (default = LIO_SMTP_USER)
    LIO_FROM_NAME       (default "Lio Ashrah")
    LIO_TITLE           (default "Marketing Coordinator")
    LIO_COMPANY_DISPLAY (default "Ashrah Painting")
    LIO_WEBSITE         (default "ashrahpainting.ca")
    LIO_SIGNATURE       (optional — full override; if unset, auto-built from name/title/company/website)
    LIO_REPLY_TO        (optional — defaults to LIO_FROM_EMAIL)

Every send writes a JSON log to logs/lio/{date}/sends_{timestamp}.json so a
record exists even if the in-app history is corrupted.
"""

import json
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[2]
LOG_ROOT = REPO / "logs" / "lio"
SIGNATURE_FILE = REPO / "lio" / "data" / "signature.txt"


def _load_signature() -> str:
    """Signature precedence:
       1. LIO_SIGNATURE env var (verbatim, supports \\n escapes)
       2. lio/data/signature.txt (multi-line file)
       3. empty (no signature appended)
    """
    env_sig = os.getenv("LIO_SIGNATURE", "")
    if env_sig.strip():
        return env_sig.replace("\\n", "\n").strip()
    if SIGNATURE_FILE.exists():
        return SIGNATURE_FILE.read_text(encoding="utf-8").strip()
    return ""


def _cfg() -> dict:
    user = os.getenv("LIO_SMTP_USER", "lio.ashrah@ashrahpainting.ca")
    from_name = os.getenv("LIO_FROM_NAME", "Lio Ashrah")
    title = os.getenv("LIO_TITLE", "Marketing Coordinator")
    company = os.getenv("LIO_COMPANY_DISPLAY", "Ashrah Painting")
    website = os.getenv("LIO_WEBSITE", "ashrahpainting.ca")
    # Signature precedence: LIO_SIGNATURE env > lio/data/signature.txt > empty.
    signature = _load_signature()
    return {
        "host": os.getenv("LIO_SMTP_HOST", "smtp.zoho.com"),
        "port": int(os.getenv("LIO_SMTP_PORT", "465")),
        "use_ssl": os.getenv("LIO_SMTP_USE_SSL", "true").strip().lower() in ("1", "true", "yes"),
        "user": user,
        "password": os.getenv("LIO_SMTP_PASSWORD", ""),
        "from_email": os.getenv("LIO_FROM_EMAIL", user),
        "from_name": from_name,
        "title": title,
        "company": company,
        "website": website,
        "signature": signature,
        "reply_to": os.getenv("LIO_REPLY_TO", "") or os.getenv("LIO_FROM_EMAIL", user),
    }


def is_configured() -> tuple[bool, Optional[str]]:
    cfg = _cfg()
    if not cfg["password"]:
        return False, "LIO_SMTP_PASSWORD not set"
    if "@" not in cfg["from_email"]:
        return False, f"LIO_FROM_EMAIL invalid: {cfg['from_email']!r}"
    return True, None


def status() -> dict:
    cfg = _cfg()
    ok, err = is_configured()
    return {
        "configured": ok,
        "error": err,
        "host": cfg["host"],
        "port": cfg["port"],
        "use_ssl": cfg["use_ssl"],
        "from": formataddr((cfg["from_name"], cfg["from_email"])),
        "title": cfg["title"],
        "company": cfg["company"],
        "website": cfg["website"],
        "signature": cfg["signature"],
        "reply_to": cfg["reply_to"],
    }


def _log_send(record: dict) -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%H%M%S%f")
    folder = LOG_ROOT / today
    folder.mkdir(parents=True, exist_ok=True)
    fp = folder / f"sends_{ts}.json"
    fp.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return fp


def send(
    to_email: str,
    subject: str,
    body: str,
    *,
    to_name: str = "",
    contact_id: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Send a plain-text outbound email.

    Returns a dict: {ok, message_id, log_path, error?}.
    Logs the attempt regardless of outcome.
    """
    cfg = _cfg()
    ok, err = is_configured()
    record = {
        "timestamp": datetime.now().isoformat(),
        "contact_id": contact_id,
        "to": formataddr((to_name, to_email)) if to_name else to_email,
        "to_email": to_email,
        "to_name": to_name,
        "from": formataddr((cfg["from_name"], cfg["from_email"])),
        "subject": subject,
        "body": body,
        "host": cfg["host"],
        "port": cfg["port"],
        "use_ssl": cfg["use_ssl"],
        "dry_run": dry_run,
        "ok": False,
    }

    if not ok and not dry_run:
        record["error"] = err
        log_path = _log_send(record)
        return {"ok": False, "error": err, "log_path": str(log_path)}

    if not to_email or "@" not in to_email:
        record["error"] = f"invalid to_email: {to_email!r}"
        log_path = _log_send(record)
        return {"ok": False, "error": record["error"], "log_path": str(log_path)}

    # Append canonical signature. Drafts are stored without signatures by design
    # (per ashrah_facts.md), so the mailer always adds the env-driven sig at send.
    if cfg["signature"]:
        full_body = body.rstrip() + "\n\n" + cfg["signature"] + "\n"
    else:
        full_body = body
    record["body"] = full_body
    record["signature"] = cfg["signature"]

    msg = EmailMessage()
    msg["From"] = formataddr((cfg["from_name"], cfg["from_email"]))
    msg["To"] = formataddr((to_name, to_email)) if to_name else to_email
    msg["Subject"] = subject
    msg["Reply-To"] = cfg["reply_to"]
    message_id = make_msgid(domain=cfg["from_email"].split("@", 1)[-1])
    msg["Message-ID"] = message_id
    msg.set_content(full_body)
    record["message_id"] = message_id

    if dry_run:
        record["ok"] = True
        record["dry_run_note"] = "dry_run=True — message NOT sent"
        log_path = _log_send(record)
        return {"ok": True, "dry_run": True, "message_id": message_id, "log_path": str(log_path)}

    try:
        if cfg["use_ssl"]:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=30) as smtp:
                smtp.login(cfg["user"], cfg["password"])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as smtp:
                smtp.starttls()
                smtp.login(cfg["user"], cfg["password"])
                smtp.send_message(msg)
        record["ok"] = True
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        log_path = _log_send(record)
        return {"ok": False, "error": record["error"], "log_path": str(log_path)}

    log_path = _log_send(record)
    return {"ok": True, "message_id": message_id, "log_path": str(log_path)}
