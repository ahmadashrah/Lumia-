"""Lio inbox reader — IMAP wrapper for replies and bounces.

Reads mail from `lio.ashrah@ashrahpainting.ca` so Lio can detect when a
prospect replies (auto-update CRM status) or when a send bounces (flag the
contact + suggest email-pattern variants).

Environment variables (most reuse SMTP config; Zoho's app password works for both):
    LIO_IMAP_HOST       (default "imap.zoho.com")
    LIO_IMAP_PORT       (default "993")  — IMAPS port
    LIO_IMAP_USER       (default LIO_SMTP_USER, then "lio.ashrah@ashrahpainting.ca")
    LIO_IMAP_PASSWORD   (default LIO_SMTP_PASSWORD)  — Zoho app password
    LIO_IMAP_FOLDER     (default "INBOX")
"""

import email
import imaplib
import os
import re
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime
from typing import Optional


def _cfg() -> dict:
    user = (
        os.getenv("LIO_IMAP_USER")
        or os.getenv("LIO_SMTP_USER")
        or "lio.ashrah@ashrahpainting.ca"
    )
    password = os.getenv("LIO_IMAP_PASSWORD") or os.getenv("LIO_SMTP_PASSWORD") or ""
    return {
        "host": os.getenv("LIO_IMAP_HOST", "imap.zoho.com"),
        "port": int(os.getenv("LIO_IMAP_PORT", "993")),
        "user": user,
        "password": password,
        "folder": os.getenv("LIO_IMAP_FOLDER", "INBOX"),
    }


def is_configured() -> tuple[bool, Optional[str]]:
    cfg = _cfg()
    if not cfg["password"]:
        return False, "LIO_IMAP_PASSWORD (or LIO_SMTP_PASSWORD) not set"
    if "@" not in cfg["user"]:
        return False, f"LIO_IMAP_USER invalid: {cfg['user']!r}"
    return True, None


def status() -> dict:
    cfg = _cfg()
    ok, err = is_configured()
    return {
        "configured": ok,
        "error": err,
        "host": cfg["host"],
        "port": cfg["port"],
        "user": cfg["user"],
        "folder": cfg["folder"],
    }


def _decode(s) -> str:
    if not s:
        return ""
    try:
        return str(make_header(decode_header(s)))
    except Exception:
        return str(s)


def _extract_text_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if ctype == "text/plain" and "attachment" not in disp:
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                except Exception:
                    continue
        # Fallback to first text/* payload
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype.startswith("text/"):
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(
            msg.get_content_charset() or "utf-8", errors="replace"
        )
    except Exception:
        return msg.get_payload() or ""


_BOUNCE_FROM = re.compile(
    r"(mailer-daemon|postmaster|noreply|no-reply|bounce)@", re.IGNORECASE
)
_BOUNCE_SUBJECT = re.compile(
    r"(undeliverable|undelivered|delivery (status notification|failed|failure)|returned to sender|"
    r"mail delivery failed|address rejected|recipient rejected|user unknown)",
    re.IGNORECASE,
)


def _classify(headers: dict, body: str) -> str:
    from_addr = (headers.get("from_email") or "").lower()
    subject = headers.get("subject") or ""
    if _BOUNCE_FROM.search(from_addr) or _BOUNCE_SUBJECT.search(subject):
        return "bounce"
    return "reply"  # everything else default — caller refines


def _parse_message(raw_bytes: bytes, uid: str) -> dict:
    msg = email.message_from_bytes(raw_bytes)
    headers = {
        "uid": uid,
        "message_id": _decode(msg.get("Message-ID") or "").strip(),
        "in_reply_to": _decode(msg.get("In-Reply-To") or "").strip(),
        "references": _decode(msg.get("References") or "").strip(),
        "subject": _decode(msg.get("Subject") or "").strip(),
        "from_raw": _decode(msg.get("From") or ""),
        "to_raw": _decode(msg.get("To") or ""),
    }
    addrs = getaddresses([msg.get("From") or ""])
    if addrs:
        headers["from_name"], headers["from_email"] = addrs[0]
    else:
        headers["from_name"], headers["from_email"] = "", ""
    headers["from_email"] = (headers["from_email"] or "").lower()

    date_hdr = msg.get("Date")
    if date_hdr:
        try:
            headers["date"] = parsedate_to_datetime(date_hdr).isoformat()
        except Exception:
            headers["date"] = date_hdr
    else:
        headers["date"] = ""

    body = _extract_text_body(msg)
    return {
        **headers,
        "body": body[:8000],  # cap body length
        "body_truncated": len(body) > 8000,
        "kind": _classify(headers, body),
    }


def fetch_recent(limit: int = 25, only_unseen: bool = True) -> dict:
    """Fetch the most recent messages. Returns {ok, messages, error}.

    Does NOT mark messages as read (uses BODY.PEEK).
    """
    cfg = _cfg()
    ok, err = is_configured()
    if not ok:
        return {"ok": False, "error": err, "messages": []}

    try:
        with imaplib.IMAP4_SSL(cfg["host"], cfg["port"]) as conn:
            conn.login(cfg["user"], cfg["password"])
            typ, _ = conn.select(cfg["folder"], readonly=True)
            if typ != "OK":
                return {"ok": False, "error": f"could not select {cfg['folder']!r}", "messages": []}
            criterion = "UNSEEN" if only_unseen else "ALL"
            typ, data = conn.search(None, criterion)
            if typ != "OK":
                return {"ok": False, "error": "search failed", "messages": []}
            ids = (data[0] or b"").split()
            ids = ids[-limit:]  # most recent N
            messages = []
            for uid_bytes in ids:
                uid = uid_bytes.decode("ascii")
                typ, parts = conn.fetch(uid_bytes, "(BODY.PEEK[])")
                if typ != "OK" or not parts or not parts[0]:
                    continue
                # parts is a list of tuples; the bytes payload is parts[0][1]
                raw = parts[0][1] if isinstance(parts[0], tuple) else parts[0]
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                messages.append(_parse_message(bytes(raw), uid))
            return {"ok": True, "messages": messages, "count": len(messages)}
    except imaplib.IMAP4.error as exc:
        return {"ok": False, "error": f"IMAP login/select error: {exc}", "messages": []}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "messages": []}
