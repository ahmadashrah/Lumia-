"""Lio research capability — evidence-based B2B marketing & sales synthesis.

Pipeline:
  1. Search Semantic Scholar (free, no auth) for papers matching the query.
  2. Keep only papers with an `openAccessPdf` link.
  3. Download each PDF, extract first ~8000 chars of text with PyMuPDF.
  4. Hand the bundle to Claude with the `research` system prompt to synthesize
     proven strategies + concrete actions for Ashrah.

Tracker: every run is logged via lio.core.logger, same as other capabilities.
"""

from __future__ import annotations

import io
import json
import os
import time
from datetime import datetime
from typing import Any

import httpx

from ..core import engine, logger
from ..core.prompts import system_for


SEMANTIC_SCHOLAR_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_FIELDS = ",".join([
    "title", "authors", "year", "venue", "abstract",
    "openAccessPdf", "url", "externalIds", "citationCount",
])
OPENALEX_SEARCH = "https://api.openalex.org/works"
USER_AGENT = "AshrahLio/1.0 (research@ashrah.ai)"

# How many papers to fetch from Semantic Scholar before filtering for PDFs
SEARCH_LIMIT_DEFAULT = 25
# Max papers we actually download + analyze (PDF download is the slow part)
PDF_LIMIT_DEFAULT = 8
# Per-PDF character cap so the LLM context stays manageable
PDF_TEXT_CAP = 8000


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------
def _reconstruct_abstract(inverted: dict | None) -> str:
    """OpenAlex returns abstracts as an inverted index { word: [positions...] }.
    Reconstruct the original word order."""
    if not inverted or not isinstance(inverted, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        for i in idxs or []:
            positions.append((i, word))
    positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in positions)


def _search_openalex(query: str, limit: int) -> list[dict]:
    """Primary search backend: OpenAlex. Free, no auth, generous rate limit.
    Returns paper dicts normalized into the same shape as the SS results so
    the rest of the pipeline doesn't have to care which source they came from."""
    # Concept IDs that keep results inside marketing / sales / business
    #   C162853370 = Marketing
    #   C144133560 = Business
    #   C112698675 = Advertising
    #   C2778572836 = Sales (concept in OpenAlex)
    #   C29122968  = Marketing communications
    concept_filter = "concepts.id:C162853370|C144133560|C112698675|C29122968"
    params = {
        "search": query,
        # is_oa:true → open-access only; concept filter → marketing/business only
        "filter": f"is_oa:true,{concept_filter}",
        "per-page": str(min(limit, 25)),
        # Use OpenAlex's default relevance score, not citation-count.
        # Citation sort surfaces high-impact but off-topic papers for narrow
        # queries (we hit this on "cold email" — got Facebook ad transparency
        # back). Relevance + the concept filter is far more on-topic.
        "sort": "relevance_score:desc",
        # User-Agent or mailto query param puts us in OpenAlex's "polite pool"
        "mailto": "research@ashrah.ai",
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        r = httpx.get(OPENALEX_SEARCH, params=params, headers=headers, timeout=30.0)
        r.raise_for_status()
    except httpx.HTTPError:
        return []
    raw = (r.json() or {}).get("results") or []
    out: list[dict] = []
    for w in raw:
        authors = []
        for a in (w.get("authorships") or []):
            name = ((a.get("author") or {}).get("display_name") or "").strip()
            if name:
                authors.append({"name": name})
        pdf_url = None
        # Try several locations OpenAlex exposes
        for loc in [w.get("best_oa_location"), w.get("primary_location")]:
            if loc and loc.get("pdf_url"):
                pdf_url = loc["pdf_url"]
                break
        if not pdf_url:
            oa = w.get("open_access") or {}
            pdf_url = oa.get("oa_url")
        out.append({
            "title": w.get("title") or "",
            "authors": authors,
            "year": w.get("publication_year"),
            "venue": ((w.get("host_venue") or {}).get("display_name")
                      or ((w.get("primary_location") or {}).get("source") or {}).get("display_name")),
            "abstract": _reconstruct_abstract(w.get("abstract_inverted_index")),
            "openAccessPdf": {"url": pdf_url} if pdf_url else None,
            "url": w.get("doi") or w.get("id"),
            "citationCount": w.get("cited_by_count"),
        })
    return out


def _search_semantic_scholar(query: str, limit: int) -> list[dict]:
    """Secondary backend: Semantic Scholar. Rate-limited hard without an API
    key, so we only fall back to it if OpenAlex returned nothing."""
    params = {"query": query, "limit": str(limit), "fields": SEMANTIC_SCHOLAR_FIELDS}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    for attempt in range(2):
        try:
            r = httpx.get(SEMANTIC_SCHOLAR_SEARCH, params=params, headers=headers, timeout=30.0)
            if r.status_code in (429, 503):
                time.sleep(2 + attempt * 3)
                continue
            r.raise_for_status()
            return (r.json() or {}).get("data") or []
        except httpx.HTTPError:
            if attempt == 0:
                time.sleep(2)
                continue
            return []
    return []


def _search_papers(query: str, limit: int) -> list[dict]:
    """Try OpenAlex first (reliable, no rate limit hassles); fall back to
    Semantic Scholar only if OpenAlex came up empty."""
    papers = _search_openalex(query, limit=limit)
    if papers:
        return papers
    return _search_semantic_scholar(query, limit=limit)


def _has_pdf(paper: dict) -> bool:
    oa = paper.get("openAccessPdf") or {}
    return bool(oa.get("url"))


# ---------------------------------------------------------------------------
# PDF download + text extraction
# ---------------------------------------------------------------------------
def _download_pdf_bytes(url: str) -> bytes | None:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"}
    try:
        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            r = client.get(url, headers=headers)
            if r.status_code != 200:
                return None
            if not r.content or len(r.content) < 1024:
                return None
            return r.content
    except Exception:
        return None


def _extract_text(pdf_bytes: bytes, char_cap: int = PDF_TEXT_CAP) -> str:
    """Extract plain text from a PDF byte stream, capped at char_cap.
    Uses PyMuPDF (fitz) which is already in requirements.txt."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return ""
    pieces: list[str] = []
    total = 0
    try:
        for page in doc:
            t = page.get_text("text") or ""
            if not t.strip():
                continue
            pieces.append(t)
            total += len(t)
            if total >= char_cap:
                break
    finally:
        doc.close()
    return ("\n".join(pieces))[:char_cap]


def _authors_str(authors: list[dict] | None) -> str:
    if not authors:
        return ""
    names = [(a.get("name") or "").strip() for a in authors if a.get("name")]
    if len(names) <= 3:
        return ", ".join(names)
    return ", ".join(names[:3]) + f" et al. ({len(names)} authors)"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def _build_sources(query: str, search_limit: int, pdf_limit: int) -> tuple[list[dict], list[dict]]:
    """Returns (sources_for_llm, debug_meta).
    sources_for_llm: rich dicts containing extracted text.
    debug_meta:      every paper we *considered*, with a status."""
    papers = _search_papers(query, limit=search_limit)
    meta: list[dict] = []
    sources: list[dict] = []
    for p in papers:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        row = {
            "title": title,
            "authors": _authors_str(p.get("authors")),
            "year": p.get("year"),
            "venue": (p.get("venue") or "").strip() or None,
            "citations": p.get("citationCount"),
            "url": (p.get("openAccessPdf") or {}).get("url") or p.get("url"),
            "status": "skipped_no_pdf",
        }
        if len(sources) >= pdf_limit:
            row["status"] = "skipped_over_limit"
            meta.append(row)
            continue
        if not _has_pdf(p):
            meta.append(row)
            continue

        pdf_url = (p.get("openAccessPdf") or {}).get("url")
        pdf_bytes = _download_pdf_bytes(pdf_url) if pdf_url else None
        if not pdf_bytes:
            row["status"] = "download_failed"
            meta.append(row)
            continue

        text = _extract_text(pdf_bytes)
        if not text or len(text) < 500:
            row["status"] = "extract_failed"
            meta.append(row)
            continue

        row["status"] = "included"
        meta.append(row)
        sources.append({
            "title": title,
            "authors": row["authors"],
            "year": row["year"],
            "venue": row["venue"],
            "abstract": (p.get("abstract") or "").strip(),
            "pdf_excerpt": text,
        })
    return sources, meta


def _synthesize(query: str, sources: list[dict]) -> str:
    """Call Claude with the research system prompt + sources payload.

    Uses Opus 4.7's beta `task_budget` parameter (header `task-budgets-2026-03-13`).
    Synthesis input can balloon when 8 papers × 8k char excerpts hit context —
    task_budget tells Claude to scope its work to a token allowance and finish
    gracefully if the synthesis is getting long. Advisory only; `max_tokens`
    stays the hard ceiling. Falls back to plain messages.create on any error
    so a bad beta header never breaks the research feature."""
    if not sources:
        payload = {"query": query, "sources": [], "note": "No open-access PDFs were retrievable for this query."}
    else:
        payload = {"query": query, "sources": sources}
    system = system_for("research")
    user = json.dumps(payload, indent=2, ensure_ascii=False)

    # Try task_budget on Opus 4.7 first
    try:
        import anthropic as _anthropic
        client = _anthropic.Anthropic()
        msg = client.beta.messages.create(
            model="claude-opus-4-7",
            max_tokens=6000,
            system=system,
            output_config={
                "effort": "high",
                "task_budget": {"type": "tokens", "total": 30000},
            },
            betas=["task-budgets-2026-03-13"],
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if hasattr(b, "text") and b.text)
    except Exception as exc:
        print(f"[Research] task_budget call failed, falling back to plain call: {exc}")
        return engine.generate(system, user, max_tokens=6000)


def run_research(query: str, *, search_limit: int = SEARCH_LIMIT_DEFAULT,
                 pdf_limit: int = PDF_LIMIT_DEFAULT) -> dict:
    """Full pipeline. Returns a dict with the LLM output + source metadata."""
    sources, meta = _build_sources(query, search_limit, pdf_limit)
    raw = _synthesize(query, sources)
    parsed: Any
    # Strip markdown code fences if Claude wrapped the JSON despite our prompt
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Drop the opening fence (```json or ```) and the closing ```
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3].rstrip()
    try:
        parsed = json.loads(cleaned)
    except Exception as parse_exc:
        parsed = {"raw_text": raw, "parse_error": True, "parse_error_msg": str(parse_exc)}
    result = {
        "query": query,
        "papers_considered": len(meta),
        "papers_included": sum(1 for m in meta if m.get("status") == "included"),
        "sources_meta": meta,
        "findings": parsed,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
    # Persist a run record so we can audit / re-read past research later
    try:
        log_path = logger.log_run("research", {
            "capability": "research",
            "timestamp": datetime.now().isoformat(),
            "input": {"query": query, "search_limit": search_limit, "pdf_limit": pdf_limit},
            "output": result,
        })
        result["log_path"] = str(log_path)
    except Exception:
        result["log_path"] = None
    return result


# ---------------------------------------------------------------------------
# Capability entry point — matches other capabilities' `run(payload)` shape
# ---------------------------------------------------------------------------
def run(payload: dict) -> dict:
    query = (payload or {}).get("query") or (payload or {}).get("topic") or ""
    query = query.strip()
    if not query:
        raise ValueError("research capability needs a 'query' field")
    search_limit = int((payload or {}).get("search_limit") or SEARCH_LIMIT_DEFAULT)
    pdf_limit = int((payload or {}).get("pdf_limit") or PDF_LIMIT_DEFAULT)

    result = run_research(query, search_limit=search_limit, pdf_limit=pdf_limit)

    # Logger record — same convention as _runner.py
    record = {
        "capability": "research",
        "timestamp": datetime.now().isoformat(),
        "input": {"query": query, "search_limit": search_limit, "pdf_limit": pdf_limit},
        "output": result,
    }
    log_path = logger.log_run("research", record)
    result["log_path"] = str(log_path)
    return result
