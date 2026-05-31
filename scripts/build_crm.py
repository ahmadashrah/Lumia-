"""Build (or rebuild) the Lio CRM from existing data sources.

Sources merged:
  - lio/data/targets.json                          (the BD tracker — 33 contacts)
  - lio/data/estimator_research/{date}/*.json      (estimator research — ~28 estimators)
  - lio/data/outreach_drafts/{date}/*.json         (linked as draft_email_path if present)

Dedupe key: (slug(company), slug(name)). Identical contacts merge — sources combined,
best email kept (real @-domain over guess), personalization fields union'd.

This script is **safe to re-run**. It rebuilds contacts.json from scratch each time —
do not edit contacts.json by hand expecting it to survive a rebuild. Edits should go
through Lio's CRM update flow, which writes back to contacts.json. Or, if you must
seed permanent overrides, add them to a separate file and merge them in here.

Run: ./bin/python scripts/build_crm.py [YYYY-MM-DD]
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGETS = REPO / "lio" / "data" / "targets.json"
RESEARCH = REPO / "lio" / "data" / "estimator_research"
MANUAL = REPO / "lio" / "data" / "manual_contacts.json"
DRAFTS = REPO / "lio" / "data" / "outreach_drafts"
OUT = REPO / "lio" / "data" / "crm" / "contacts.json"


_CORP_SUFFIX = re.compile(
    r"\s+(?:limited|ltd|incorporated|inc|corporation|corp|llc|llp)\.?\s*$",
    re.IGNORECASE,
)
_PAREN_TAIL = re.compile(r"\s*\([^)]*\)\s*$")


def slug(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    # Strip "(...)" tail like "Con-Pro Canada (Con-Pro Industries Canada Ltd.)"
    s = _PAREN_TAIL.sub("", s)
    # Strip corporate suffixes — "Construction Ltd." vs "Construction" should merge
    s = _CORP_SUFFIX.sub("", s).strip()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def split_name(n: str) -> tuple[str, str]:
    parts = (n or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def normalize_segment(raw: str) -> str:
    t = (raw or "").strip().lower()
    if "contractor" in t: return "GC"
    if "property" in t:   return "PM"
    if "developer" in t:  return "Developer"
    if "hotel" in t:      return "Hotel"
    if "public" in t:     return "Public"
    return "Unknown"


def clean_email(s: str) -> str:
    """Strip whitespace, parentheticals, and "***" patterns the research agent
    sometimes embedded in the email field."""
    if not s:
        return ""
    s = s.strip()
    # Cut off parenthetical notes like "andrew@x.com (likely ...)"
    for sep in ("(", " ", "\t", "\n", ","):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
    # Drop redacted patterns like "a***@..."
    if "*" in s:
        return ""
    return s


def is_real_email(s: str) -> bool:
    s = clean_email(s)
    return bool(s and "@" in s and "." in s.split("@", 1)[-1])


def merge_contact(into: dict, src: dict) -> dict:
    # Sources combine
    into.setdefault("sources", [])
    for s in src.get("sources") or []:
        if s not in into["sources"]:
            into["sources"].append(s)
    # Email — prefer real @-bearing
    if not is_real_email(into.get("email", "")) and is_real_email(src.get("email", "")):
        into["email"] = src["email"]
    # Other contact fields — fill in if empty
    for k in ("phone", "linkedin", "title", "city"):
        if not into.get(k) and src.get(k):
            into[k] = src[k]
    # Personalization — union of hooks, keep highest confidence, fill scalar fields
    pa = into.setdefault("personalization", {})
    pb = src.get("personalization") or {}
    if pb.get("hooks"):
        merged = list(dict.fromkeys((pa.get("hooks") or []) + pb["hooks"]))
        pa["hooks"] = merged
    if pb.get("prior_firms"):
        pa["prior_firms"] = list(dict.fromkeys((pa.get("prior_firms") or []) + pb["prior_firms"]))
    if pb.get("education"):
        pa["education"] = list(dict.fromkeys((pa.get("education") or []) + pb["education"]))
    if pb.get("tenure_years") and not pa.get("tenure_years"):
        pa["tenure_years"] = pb["tenure_years"]
    rank = {"high": 0, "medium": 1, "low": 2}
    cur = pa.get("confidence")
    new = pb.get("confidence")
    if new and (not cur or rank.get(new, 9) < rank.get(cur, 9)):
        pa["confidence"] = new
    # Flags
    if src.get("needs_review_flags"):
        into.setdefault("needs_review_flags", [])
        for f in src["needs_review_flags"]:
            if f not in into["needs_review_flags"]:
                into["needs_review_flags"].append(f)
    return into


def from_bd_row(row: dict) -> dict | None:
    name = (row.get("Contact Name") or "").strip()
    company = (row.get("Company") or "").strip()
    if not name and not company:
        return None
    fn, ln = split_name(name)
    return {
        "id": f"{slug(company)}::{slug(name)}",
        "name": name,
        "first_name": fn,
        "last_name": ln,
        "title": "",
        "company": company,
        "company_slug": slug(company),
        "segment": normalize_segment(row.get("Prospect Type", "")),
        "email": clean_email(row.get("Email", "")) if is_real_email(row.get("Email", "")) else "",
        "phone": row.get("Phone", "") or "",
        "linkedin": row.get("LinkedIn", "") or "",
        "city": (row.get("City / Area") or "").lower() if row.get("City / Area") else "",
        "tier": 2,
        "status": (row.get("Status") or "Cold").strip() or "Cold",
        "sources": ["bd_tracker_2026-04-28"],
        "first_added": "2026-04-28",
        "last_contacted": (row.get("Date Approached") or "") or None,
        "next_action": (row.get("Next Action") or "") or None,
        "next_action_date": (row.get("Follow-Up Date") or "") or None,
        "touches_sent": int(row.get("Follow-Up #") or 0) if str(row.get("Follow-Up #") or "").strip().isdigit() else 0,
        "draft_email_path": None,
        "personalization": {
            "tenure_years": None,
            "prior_firms": [],
            "education": [],
            "hooks": [],
            "confidence": None,
        },
        "notes": (row.get("Notes") or "") or "",
        "history": [],
        "needs_review_flags": [],
    }


def from_estimator(rec: dict, estimator: dict) -> dict | None:
    name = (estimator.get("name") or "").strip()
    company = (rec.get("company") or "").strip()
    if not name or not company:
        return None
    fn, ln = split_name(name)
    return {
        "id": f"{slug(company)}::{slug(name)}",
        "name": name,
        "first_name": fn,
        "last_name": ln,
        "title": estimator.get("title") or "",
        "company": company,
        "company_slug": slug(company),
        "segment": "GC",
        "email": clean_email(estimator.get("email") or "") if is_real_email(estimator.get("email") or "") else "",
        "phone": estimator.get("phone") or "",
        "linkedin": estimator.get("linkedin") or "",
        "city": "winnipeg",
        "tier": 1 if (estimator.get("confidence") or "").lower() == "high" else 2,
        "status": "Cold",
        "sources": ["estimator_research_2026-04-28"],
        "first_added": "2026-04-28",
        "last_contacted": None,
        "next_action": None,
        "next_action_date": None,
        "touches_sent": 0,
        "draft_email_path": None,
        "personalization": {
            "tenure_years": estimator.get("tenure_years_at_company"),
            "prior_firms": estimator.get("prior_firms") or [],
            "education": estimator.get("education") or [],
            "hooks": estimator.get("personalization_hooks") or [],
            "confidence": (estimator.get("confidence") or "").lower() or None,
        },
        "notes": "",
        "history": [],
        "needs_review_flags": rec.get("needs_review_flags") or [],
    }


def from_manual(rec: dict) -> dict | None:
    name = (rec.get("name") or "").strip()
    company = (rec.get("company") or "").strip()
    if not name or not company:
        return None
    fn, ln = split_name(name)
    return {
        "id": f"{slug(company)}::{slug(name)}",
        "name": name,
        "first_name": fn,
        "last_name": ln,
        "title": rec.get("title") or "",
        "company": company,
        "company_slug": slug(company),
        "segment": rec.get("segment") or "GC",
        "email": clean_email(rec.get("email") or "") if is_real_email(rec.get("email") or "") else "",
        "phone": rec.get("phone") or "",
        "linkedin": rec.get("linkedin") or "",
        "city": rec.get("city") or "winnipeg",
        "tier": rec.get("tier") or 2,
        "status": rec.get("status") or "Cold",
        "sources": ["manual_contacts_2026-04-29"],
        "first_added": "2026-04-29",
        "last_contacted": None,
        "next_action": None,
        "next_action_date": None,
        "touches_sent": 0,
        "draft_email_path": None,
        "personalization": {
            "tenure_years": None,
            "prior_firms": [],
            "education": [],
            "hooks": [rec.get("warm_context")] if rec.get("warm_context") else [],
            "confidence": "high",
            "tone": rec.get("tone") or "cold",
        },
        "notes": rec.get("notes") or "",
        "history": [],
        "needs_review_flags": [],
    }


def fallback_contact_from_research(rec: dict) -> dict | None:
    fb = rec.get("fallback_contact") or {}
    if not fb.get("name"):
        return None
    company = (rec.get("company") or "").strip()
    name = (fb.get("name") or "").strip()
    fn, ln = split_name(name)
    return {
        "id": f"{slug(company)}::{slug(name)}",
        "name": name,
        "first_name": fn,
        "last_name": ln,
        "title": fb.get("title") or "",
        "company": company,
        "company_slug": slug(company),
        "segment": "GC",
        "email": "",
        "phone": "",
        "linkedin": "",
        "city": "winnipeg",
        "tier": 3,
        "status": "Cold",
        "sources": ["estimator_research_2026-04-28_fallback"],
        "first_added": "2026-04-28",
        "last_contacted": None,
        "next_action": "Phone outreach to identify estimator",
        "next_action_date": None,
        "touches_sent": 0,
        "draft_email_path": None,
        "personalization": {
            "tenure_years": None,
            "prior_firms": [],
            "education": [],
            "hooks": [fb.get("rationale") or "Phone outreach — no public estimator surfaced"],
            "confidence": "low",
        },
        "notes": "",
        "history": [],
        "needs_review_flags": [],
    }


def attach_drafts(contacts: dict[str, dict], date_str: str) -> int:
    folder = DRAFTS / date_str
    if not folder.exists():
        return 0
    n = 0
    for fp in folder.glob("*.json"):
        if fp.name.startswith("_"):
            continue
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        company = d.get("company", "")
        name = d.get("to_name", "")
        if not company or not name:
            continue
        # Try the canonical slug; if not present, fall back to scanning for the
        # tracker company spelling we ingested earlier.
        cand = f"{slug(company)}::{slug(name)}"
        if cand in contacts:
            contacts[cand]["draft_email_path"] = str(fp.relative_to(REPO))
            n += 1
            continue
        # Fallback 1: full-name match anywhere
        slug_name = slug(name)
        slug_company = slug(company)
        matched = False
        for cid, c in contacts.items():
            if slug(c.get("name", "")) == slug_name:
                c["draft_email_path"] = str(fp.relative_to(REPO))
                n += 1
                matched = True
                break
        if matched:
            continue
        # Fallback 2: first-name match within same company (handles drafts where
        # to_name is "Craig" but the CRM has "Craig Hildebrandt")
        for cid, c in contacts.items():
            if c.get("company_slug") != slug_company:
                continue
            cname = slug(c.get("name", ""))
            if cname == slug_name or cname.startswith(slug_name + "-"):
                c["draft_email_path"] = str(fp.relative_to(REPO))
                n += 1
                break
    return n


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else "2026-04-28"

    contacts: dict[str, dict] = {}

    # 1. BD tracker
    if TARGETS.exists():
        bd = json.loads(TARGETS.read_text(encoding="utf-8"))
        for row in bd:
            c = from_bd_row(row)
            if not c:
                continue
            if c["id"] in contacts:
                contacts[c["id"]] = merge_contact(contacts[c["id"]], c)
            else:
                contacts[c["id"]] = c

    # 2. Estimator research
    research_folder = RESEARCH / date_str
    if research_folder.exists():
        for fp in research_folder.glob("*.json"):
            if fp.name.startswith("_"):
                continue
            try:
                rec = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                continue
            for est in rec.get("estimators") or []:
                c = from_estimator(rec, est)
                if not c:
                    continue
                if c["id"] in contacts:
                    contacts[c["id"]] = merge_contact(contacts[c["id"]], c)
                else:
                    contacts[c["id"]] = c
            # Add fallback contact only if no estimator was found
            if not (rec.get("estimators") or []):
                fb = fallback_contact_from_research(rec)
                if fb:
                    if fb["id"] in contacts:
                        contacts[fb["id"]] = merge_contact(contacts[fb["id"]], fb)
                    else:
                        contacts[fb["id"]] = fb

    # 3. Manual contacts (added later, not in BD tracker or estimator research)
    if MANUAL.exists():
        manual = json.loads(MANUAL.read_text(encoding="utf-8"))
        for rec in manual:
            c = from_manual(rec)
            if not c:
                continue
            if c["id"] in contacts:
                contacts[c["id"]] = merge_contact(contacts[c["id"]], c)
            else:
                contacts[c["id"]] = c

    # 4. Link drafts
    n_drafts = attach_drafts(contacts, date_str)

    out = list(contacts.values())
    out.sort(key=lambda c: ((c.get("tier") or 9), c.get("company") or "", c.get("name") or ""))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # Stats
    from collections import Counter
    by_seg = Counter(c.get("segment") for c in out)
    by_status = Counter(c.get("status") for c in out)
    by_tier = Counter(c.get("tier") for c in out)
    with_email = sum(1 for c in out if c.get("email"))
    with_linkedin = sum(1 for c in out if c.get("linkedin"))
    with_drafts = sum(1 for c in out if c.get("draft_email_path"))

    print(f"CRM written: {OUT}  ({len(out)} contacts)")
    print(f"  by segment: {dict(by_seg)}")
    print(f"  by tier:    {dict(by_tier)}")
    print(f"  by status:  {dict(by_status)}")
    print(f"  with email: {with_email} / {len(out)}")
    print(f"  with linkedin: {with_linkedin} / {len(out)}")
    print(f"  with draft attached: {with_drafts}")


if __name__ == "__main__":
    main()
