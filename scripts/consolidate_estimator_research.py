"""Consolidate per-company estimator research into a single readable report.

Reads every {slug}.json under lio/data/estimator_research/2026-04-28/
(excluding _summary / _REPORT files), then writes:
  - _REPORT.md   : human-readable top-level summary
  - _ALL.json    : single-file machine-readable consolidation
  - _ESTIMATORS.csv : flat row-per-estimator for the BD pipeline tracker

Run: ./bin/python scripts/consolidate_estimator_research.py [YYYY-MM-DD]
Defaults to today.
"""

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_ROOT = REPO_ROOT / "lio" / "data" / "estimator_research"


def load_company_files(folder: Path) -> list[dict]:
    out = []
    for fp in sorted(folder.glob("*.json")):
        if fp.name.startswith("_"):
            continue
        try:
            out.append(json.loads(fp.read_text(encoding="utf-8")))
        except Exception as exc:
            print(f"WARN: failed to read {fp.name}: {exc}", file=sys.stderr)
    return out


def confidence_rank(c: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get((c or "").lower(), 3)


def write_csv(records: list[dict], path: Path) -> None:
    rows = []
    for rec in records:
        company = rec.get("company", "")
        for est in rec.get("estimators") or []:
            rows.append({
                "company": company,
                "name": est.get("name", ""),
                "title": est.get("title", ""),
                "email": est.get("email") or "",
                "phone": est.get("phone") or "",
                "linkedin": est.get("linkedin") or "",
                "confidence": est.get("confidence", ""),
                "tenure_years": est.get("tenure_years_at_company") or "",
                "prior_firms": "; ".join(est.get("prior_firms") or []),
                "education": "; ".join(est.get("education") or []),
                "top_hook": (est.get("personalization_hooks") or [""])[0],
                "all_hooks": " | ".join(est.get("personalization_hooks") or []),
                "sources": " | ".join(s.get("url", "") for s in (est.get("sources") or [])),
            })
        if not rec.get("estimators"):
            fb = rec.get("fallback_contact") or {}
            rows.append({
                "company": company,
                "name": fb.get("name", "") or "(no estimator found)",
                "title": fb.get("title", "") or "fallback contact",
                "email": "",
                "phone": "",
                "linkedin": "",
                "confidence": "none",
                "tenure_years": "",
                "prior_firms": "",
                "education": "",
                "top_hook": fb.get("rationale", ""),
                "all_hooks": fb.get("rationale", ""),
                "sources": "",
            })

    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)


def render_markdown(records: list[dict], date_str: str) -> str:
    lines = []
    lines.append(f"# Winnipeg Commercial GC Estimator Research — {date_str}")
    lines.append("")
    lines.append("Built for the 60-day BD push. Goal: identify the estimator at every Winnipeg")
    lines.append("commercial GC and capture personalization hooks Ahmad can use to break in.")
    lines.append("")

    total = len(records)
    found = sum(1 for r in records if r.get("estimator_found"))
    dead_ends = total - found
    n_estimators = sum(len(r.get("estimators") or []) for r in records)

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Companies researched: **{total}**")
    lines.append(f"- Estimators identified: **{n_estimators}** across **{found}** companies")
    lines.append(f"- No public estimator (phone outreach required): **{dead_ends}**")
    lines.append("")

    # High-confidence section
    high = []
    for r in records:
        for e in r.get("estimators") or []:
            if (e.get("confidence") or "").lower() == "high":
                high.append((r["company"], e))
    if high:
        lines.append("## Highest-confidence finds")
        lines.append("")
        lines.append("| Company | Estimator | Title | Top hook |")
        lines.append("|---|---|---|---|")
        for company, e in high:
            hook = (e.get("personalization_hooks") or [""])[0].replace("|", "/").strip()
            lines.append(f"| {company} | {e.get('name','')} | {e.get('title','')} | {hook} |")
        lines.append("")

    # Phone-only list
    phone_only = [r for r in records if not r.get("estimator_found")]
    if phone_only:
        lines.append("## No public estimator — phone outreach to identify")
        lines.append("")
        for r in phone_only:
            company = r.get("company", "")
            fb = r.get("fallback_contact") or {}
            extra = f" — fallback: {fb.get('name','')} ({fb.get('title','')})" if fb.get("name") else ""
            lines.append(f"- {company}{extra}")
        lines.append("")

    # Per-company detail
    lines.append("## Per-company detail")
    lines.append("")
    for r in sorted(records, key=lambda x: x.get("company", "").lower()):
        company = r.get("company", "")
        lines.append(f"### {company}")
        if r.get("website"):
            lines.append(f"- Website: {r['website']}")
        ests = r.get("estimators") or []
        if not ests:
            lines.append(f"- _No public estimator identified._")
            fb = r.get("fallback_contact") or {}
            if fb.get("name"):
                lines.append(f"- Fallback contact: **{fb['name']}** — {fb.get('title','')}")
                if fb.get("rationale"):
                    lines.append(f"  - {fb['rationale']}")
        else:
            for e in sorted(ests, key=lambda x: confidence_rank(x.get("confidence", ""))):
                lines.append(f"- **{e.get('name','?')}** — {e.get('title','')} ({(e.get('confidence') or 'unknown').lower()} confidence)")
                if e.get("email"):  lines.append(f"  - Email: {e['email']}")
                if e.get("phone"):  lines.append(f"  - Phone: {e['phone']}")
                if e.get("linkedin"): lines.append(f"  - LinkedIn: {e['linkedin']}")
                if e.get("tenure_years_at_company"): lines.append(f"  - Tenure: {e['tenure_years_at_company']} years")
                if e.get("prior_firms"): lines.append(f"  - Prior firms: {', '.join(e['prior_firms'])}")
                if e.get("education"):   lines.append(f"  - Education: {', '.join(e['education'])}")
                hooks = e.get("personalization_hooks") or []
                if hooks:
                    lines.append("  - Hooks:")
                    for h in hooks:
                        lines.append(f"    - {h}")
                srcs = e.get("sources") or []
                if srcs:
                    lines.append("  - Sources:")
                    for s in srcs:
                        url = s.get("url", "")
                        claim = s.get("claim", "")
                        if url:
                            lines.append(f"    - {url}{(' — ' + claim) if claim else ''}")
        if r.get("needs_review_flags"):
            lines.append("- Flags:")
            for f in r["needs_review_flags"]:
                lines.append(f"  - {f}")
        lines.append("")

    return "\n".join(lines)


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    folder = RESEARCH_ROOT / date_str
    if not folder.exists():
        print(f"ERROR: research folder not found: {folder}", file=sys.stderr)
        sys.exit(1)

    records = load_company_files(folder)
    print(f"Loaded {len(records)} company JSONs from {folder}")

    # Single-file machine-readable
    (folder / "_ALL.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # CSV for the BD tracker
    write_csv(records, folder / "_ESTIMATORS.csv")

    # Markdown report
    md = render_markdown(records, date_str)
    (folder / "_REPORT.md").write_text(md, encoding="utf-8")

    print(f"Wrote: {folder / '_REPORT.md'}")
    print(f"Wrote: {folder / '_ALL.json'}")
    print(f"Wrote: {folder / '_ESTIMATORS.csv'}")


if __name__ == "__main__":
    main()
