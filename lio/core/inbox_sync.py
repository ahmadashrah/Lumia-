"""Inbox sync — pull new mail via IMAP, match to CRM contacts, update state.

Behavior:
  - Replies from a known CRM contact: append to history, advance status if appropriate
    (Cold/Contacted -> Replied), surface in the "needs Ahmad's eyes" queue.
  - Bounces: extract the failed recipient, find matching contact, flag it for
    email-pattern retry.
  - Unmatched messages: returned but not auto-applied to CRM; they show in the
    Inbox view so Ahmad can decide.

This module is INTENTIONALLY non-destructive: it does not delete or move mail
on the IMAP server. It reads via BODY.PEEK and persists state in the JSON CRM
+ a side journal so the user can re-run sync safely without double-counting.

Side journal: lio/data/crm/inbox_seen.json  — list of UIDs we've already processed.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from . import crm, imap_client

DATA_DIR = Path(__file__).resolve().parents[2] / "lio" / "data" / "crm"
SEEN_FILE = DATA_DIR / "inbox_seen.json"


def _load_seen() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_seen(seen: set[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")


_BOUNCE_RECIP_PATTERNS = [
    re.compile(r"<([^<>@\s]+@[^<>\s]+)>:?", re.IGNORECASE),
    re.compile(r"^\s*Final-Recipient:\s*[^;]+;\s*([^\s]+)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Original-Recipient:\s*[^;]+;\s*([^\s]+)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"failed to deliver to\s+(?:'|\")?([^@\s'\"<>]+@[^@\s'\"<>]+)", re.IGNORECASE),
]


def _extract_bounced_recipient(body: str) -> str | None:
    for rx in _BOUNCE_RECIP_PATTERNS:
        m = rx.search(body or "")
        if m:
            cand = m.group(1).strip().rstrip(":>.,;'\"")
            if "@" in cand and not cand.lower().startswith(("mailer-daemon", "postmaster", "noreply")):
                return cand.lower()
    return None


def _find_contact_by_email(email_addr: str, contacts: list[dict]) -> dict | None:
    if not email_addr:
        return None
    e = email_addr.strip().lower()
    for c in contacts:
        if (c.get("email") or "").strip().lower() == e:
            return c
    return None


def sync(limit: int = 50, only_unseen: bool = False, mark_seen: bool = True) -> dict:
    fetch = imap_client.fetch_recent(limit=limit, only_unseen=only_unseen)
    if not fetch.get("ok"):
        return {"ok": False, "error": fetch.get("error"), "summary": {}, "events": []}

    seen = _load_seen()
    contacts = crm.load_all()
    events: list[dict] = []
    new_seen: set[str] = set()
    counts = {"replies_matched": 0, "bounces_matched": 0, "unmatched": 0, "skipped_seen": 0}

    for msg in fetch["messages"]:
        uid = msg.get("uid", "")
        msg_id = msg.get("message_id", "")
        seen_key = msg_id or f"uid:{uid}"
        if seen_key in seen:
            counts["skipped_seen"] += 1
            continue
        new_seen.add(seen_key)

        kind = msg.get("kind") or "reply"
        from_email = (msg.get("from_email") or "").lower()
        subject = msg.get("subject") or ""
        date = msg.get("date") or ""

        if kind == "bounce":
            bounced = _extract_bounced_recipient(msg.get("body") or "")
            contact = _find_contact_by_email(bounced or "", contacts) if bounced else None
            if contact:
                counts["bounces_matched"] += 1
                flag = f"BOUNCE on {bounced} from sent message — try email-pattern variants"
                cur_flags = contact.get("needs_review_flags") or []
                if flag not in cur_flags:
                    cur_flags.append(flag)
                    crm.update(contact["id"], {"tags": ["bounce"]} if False else {})  # noop, keep update path
                    # Direct write to attach flag (update() doesn't allow flags). Append manually.
                    contacts_all = crm.load_all()
                    for i, c in enumerate(contacts_all):
                        if c["id"] == contact["id"]:
                            c.setdefault("needs_review_flags", []).append(flag)
                            c.setdefault("history", []).append({
                                "date": datetime.now().isoformat(),
                                "event": "inbox.bounce",
                                "detail": f"From {from_email} — bounced recipient {bounced} — subject {subject!r}",
                            })
                            contacts_all[i] = c
                            crm.save_all(contacts_all)
                            break
                events.append({
                    "kind": "bounce",
                    "matched_contact_id": contact["id"],
                    "bounced_email": bounced,
                    "subject": subject,
                    "date": date,
                })
            else:
                counts["unmatched"] += 1
                events.append({
                    "kind": "bounce",
                    "matched_contact_id": None,
                    "bounced_email": bounced,
                    "subject": subject,
                    "from": from_email,
                    "date": date,
                    "note": "bounce — could not match a CRM contact (check sent log manually)",
                })
            continue

        # default: reply
        contact = _find_contact_by_email(from_email, contacts)
        if contact:
            counts["replies_matched"] += 1
            cur_status = (contact.get("status") or "").strip()
            patch = {}
            if cur_status in ("Cold", "Contacted", "Engaged", "Warm"):
                patch["status"] = "Replied"
            patch["last_contacted"] = (date.split("T")[0] if "T" in date else (date or "")) or contact.get("last_contacted")
            crm.update(contact["id"], patch)
            # Add a history note (status change is already auto-logged; add the reply note too)
            contacts_all = crm.load_all()
            for i, c in enumerate(contacts_all):
                if c["id"] == contact["id"]:
                    c.setdefault("history", []).append({
                        "date": datetime.now().isoformat(),
                        "event": "inbox.reply",
                        "detail": f"Reply received — subject {subject!r}",
                    })
                    contacts_all[i] = c
                    crm.save_all(contacts_all)
                    break
            events.append({
                "kind": "reply",
                "matched_contact_id": contact["id"],
                "contact_name": contact.get("name"),
                "from": from_email,
                "subject": subject,
                "date": date,
                "preview": (msg.get("body") or "")[:300],
                "old_status": cur_status,
                "new_status": patch.get("status", cur_status),
            })
        else:
            counts["unmatched"] += 1
            events.append({
                "kind": "unmatched",
                "from": from_email,
                "subject": subject,
                "date": date,
                "preview": (msg.get("body") or "")[:300],
            })

    if mark_seen and new_seen:
        seen.update(new_seen)
        _save_seen(seen)

    return {
        "ok": True,
        "summary": {
            "fetched": len(fetch["messages"]),
            **counts,
            "newly_processed": len(new_seen),
        },
        "events": events,
    }
