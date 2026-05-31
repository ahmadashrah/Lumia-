"""Lio CRM — file-backed contact store.

Single source of truth: lio/data/crm/contacts.json
Atomic writes via tempfile-rename so a crashed write can't corrupt the store.
"""

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parents[2] / "lio" / "data" / "crm"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONTACTS_FILE = DATA_DIR / "contacts.json"

VALID_STATUSES = [
    "Cold", "Contacted", "Engaged", "Warm", "Replied",
    "Active Conversation", "Quoted", "Site Walk", "Hot",
    "Proposal Sent", "Active Client", "Nurture",
    "Not Interested", "Closed Lost", "Closed",
]


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def load_all() -> list[dict]:
    if not CONTACTS_FILE.exists():
        return []
    return json.loads(CONTACTS_FILE.read_text(encoding="utf-8"))


def save_all(contacts: list[dict]) -> None:
    CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".contacts.", suffix=".json", dir=str(CONTACTS_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(contacts, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONTACTS_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def get(contact_id: str) -> Optional[dict]:
    for c in load_all():
        if c.get("id") == contact_id:
            return c
    return None


def upsert_from_research(payload: dict, source_tag: str) -> dict:
    """Ingest a Market Intel JSON payload into the CRM.

    Behavior:
    - One contact row per `leadership` entry, id = `<company-slug>::<name-slug>`.
    - **Never overwrites existing data with null.** If the existing row has a
      LinkedIn URL and the new payload doesn't, we keep the existing one.
    - Appends `source_tag` (e.g. "market_intel_2026-05-18_durango") to the
      contact's `sources` list so you can trace where a contact came from.
    - Adds an entry to the contact's `history` for each upsert event.
    - Returns a summary: counts of new vs updated vs unchanged contacts.

    The full research brief is saved separately via `save_research_brief()`
    so the CRM contacts.json doesn't bloat with every brief's prose.
    """
    company = (payload.get("company") or "").strip()
    if not company:
        return {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0,
                "error": "payload missing 'company'"}
    company_slug = slug(company)
    segment = (payload.get("segment") or "").strip()
    city    = (payload.get("city") or "").strip().lower()

    contacts = load_all()
    by_id    = {c.get("id"): (i, c) for i, c in enumerate(contacts)}
    today    = datetime.now().date().isoformat()
    now_iso  = datetime.now().isoformat()

    created = updated = unchanged = skipped = 0
    touched_ids: list[str] = []

    for lead in (payload.get("leadership") or []):
        name = (lead.get("name") or "").strip()
        if not name:
            skipped += 1
            continue
        # Filter obvious junk — Claude sometimes returns "Unknown" / "TBD"
        if name.lower() in {"unknown", "tbd", "n/a", "not listed", "various"}:
            skipped += 1
            continue
        cid = f"{company_slug}::{slug(name)}"
        parts = name.split()
        first = parts[0] if parts else ""
        last  = " ".join(parts[1:]) if len(parts) > 1 else ""

        new_fields = {
            "title":    (lead.get("title") or "").strip(),
            "linkedin": (lead.get("linkedin") or "").strip(),
            "email":    (lead.get("email") or "").strip(),
            "phone":    (lead.get("phone") or "").strip(),
        }

        if cid in by_id:
            i, existing = by_id[cid]
            changed_keys: list[str] = []
            for k, v in new_fields.items():
                # Only overwrite if we have a non-empty new value AND the
                # existing value is empty/missing. Conservative — research
                # signal doesn't trump operator-entered data.
                if v and not (existing.get(k) or "").strip():
                    existing[k] = v
                    changed_keys.append(k)
            srcs = existing.setdefault("sources", [])
            if source_tag not in srcs:
                srcs.append(source_tag)
                changed_keys.append("sources")
            if changed_keys:
                existing.setdefault("history", []).append({
                    "date":  now_iso,
                    "event": "market_intel.refresh",
                    "detail": f"Updated {', '.join(changed_keys)} from {source_tag}",
                })
                contacts[i] = existing
                updated += 1
                touched_ids.append(cid)
            else:
                unchanged += 1
                touched_ids.append(cid)
        else:
            new_row = {
                "id":              cid,
                "name":            name,
                "first_name":      first,
                "last_name":       last,
                "title":           new_fields["title"],
                "company":         company,
                "company_slug":    company_slug,
                "segment":         segment,
                "email":           new_fields["email"],
                "phone":           new_fields["phone"],
                "linkedin":        new_fields["linkedin"],
                "city":            city,
                "tier":            None,
                "status":          "Cold",
                "sources":         [source_tag],
                "first_added":     today,
                "last_contacted":  None,
                "next_action":     None,
                "next_action_date": None,
                "touches_sent":    0,
                "draft_email_path": None,
                "personalization": {
                    "research_confidence": (lead.get("confidence") or "verify"),
                    "research_source":     (lead.get("source") or ""),
                },
                "needs_review_flags": [],
                "history": [{
                    "date":  now_iso,
                    "event": "market_intel.created",
                    "detail": f"Added from {source_tag}",
                }],
            }
            contacts.append(new_row)
            created += 1
            touched_ids.append(cid)

    if created or updated:
        save_all(contacts)

    return {
        "company":     company,
        "company_slug": company_slug,
        "created":     created,
        "updated":     updated,
        "unchanged":   unchanged,
        "skipped":     skipped,
        "touched_ids": touched_ids,
    }


def save_research_brief(company_slug: str, payload: dict, brief_markdown: str) -> str:
    """Persist the full Market Intel output (structured + prose) so we can
    re-read it later without re-running the search. Returns the relative path."""
    brief_dir = DATA_DIR / "research"
    brief_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{company_slug}_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.json"
    fpath = brief_dir / fname
    rec = {
        "company_slug": company_slug,
        "generated_at": datetime.now().isoformat(),
        "structured":   payload,
        "brief":        brief_markdown,
    }
    fd, tmp = tempfile.mkstemp(prefix=".brief.", suffix=".json", dir=str(brief_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=2, ensure_ascii=False)
        os.replace(tmp, fpath)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return str(fpath.relative_to(fpath.parents[3]))  # path relative to repo root


def update(contact_id: str, patch: dict) -> Optional[dict]:
    contacts = load_all()
    for i, c in enumerate(contacts):
        if c.get("id") == contact_id:
            allowed = {
                "status", "tier", "notes", "next_action", "next_action_date",
                "last_contacted", "touches_sent", "email", "phone", "linkedin",
                "title", "tags",
            }
            for k, v in patch.items():
                if k not in allowed:
                    continue
                if k == "status" and v and v not in VALID_STATUSES:
                    raise ValueError(f"unknown status {v!r}")
                old = c.get(k)
                c[k] = v
                if old != v:
                    c.setdefault("history", []).append({
                        "date": datetime.now().isoformat(),
                        "event": f"updated.{k}",
                        "detail": f"{old!r} -> {v!r}",
                    })
            contacts[i] = c
            save_all(contacts)
            return c
    return None
