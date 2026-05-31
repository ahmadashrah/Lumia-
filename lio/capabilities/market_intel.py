"""Market Intel — recon brief on a named GC / PM / developer / hotel.

Now uses Opus 4.7 + web_search + task_budget (beta) so the brief is built
on actual public-web evidence (About pages, MERX postings, LinkedIn
signals, permit data) instead of generic "go verify this" placeholders.

Cost stack (target: $0.30-0.55 per run, ceiling $1.50):
- Opus 4.7 at $5/$25 per MTok
- task_budget: 50k tokens (advisory; model self-moderates the loop)
- max_tokens output: 4000 (hard ceiling)
- web_search max_uses: 5
- Post-call cost measurement + $1.50 circuit breaker
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

import anthropic as _anthropic

from ..core import engine, logger, crm
from ..core.prompts import system_for
from ._runner import run as _basic_run


_CRM_DATA_RE = re.compile(r"<crm-data>\s*(\{.*?\})\s*</crm-data>", re.DOTALL)


def _split_crm_and_brief(raw: str) -> tuple[dict | None, str]:
    """Pull the <crm-data>{...}</crm-data> block out of the model's response.
    Returns (parsed_json_or_None, brief_with_block_stripped).
    Robust to:
    - Missing block (e.g. fallback path that didn't ask for one) → (None, raw)
    - Malformed JSON inside the block → logs and returns (None, raw_minus_block)
    - Code-fenced JSON (```json {...} ```) inside the block
    """
    if not raw:
        return None, ""
    m = _CRM_DATA_RE.search(raw)
    if not m:
        return None, raw.strip()
    block = m.group(1).strip()
    # Strip ```json fences if the model wrapped them inside the tags
    if block.startswith("```"):
        block = block.split("\n", 1)[1] if "\n" in block else block[3:]
        if block.rstrip().endswith("```"):
            block = block.rstrip()[:-3].rstrip()
    try:
        parsed = json.loads(block)
    except Exception as exc:
        print(f"[MarketIntel] crm-data JSON parse failed: {exc}; raw block: {block[:300]}")
        parsed = None
    brief_stripped = (raw[:m.start()] + raw[m.end():]).strip()
    return parsed, brief_stripped


# ---- Cost guardrails (mirrors the Capability Scout pattern) ----
_MI_PRICING = {
    "claude-opus-4-7":            {"in":  5.0, "out": 25.0},
    "claude-sonnet-4-5":          {"in":  3.0, "out": 15.0},
    "claude-sonnet-4-5-20250929": {"in":  3.0, "out": 15.0},
}
_MI_WEB_SEARCH_USD_PER_CALL = 0.010   # $10 / 1k searches
MI_CIRCUIT_BREAKER_USD = 1.50

# Sticky kill state — if any single run blows past the ceiling, every
# subsequent invocation is refused until the process restarts or the
# breaker is cleared from code.
_MI_KILLED_REASON: str | None = None


def _compute_cost(model: str, usage, num_web_searches: int) -> float:
    p = _MI_PRICING.get(model, {"in": 5.0, "out": 25.0})
    in_tokens  = getattr(usage, "input_tokens", 0) or 0
    out_tokens = getattr(usage, "output_tokens", 0) or 0
    in_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
    in_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
    cost = (in_tokens / 1_000_000) * p["in"] + (out_tokens / 1_000_000) * p["out"]
    cost += num_web_searches * _MI_WEB_SEARCH_USD_PER_CALL
    return round(cost, 4)


def _build_user_prompt(payload: dict) -> str:
    """Synthesize the user message Lio receives into a research brief.
    The web_search tool will then ground the response in actual pages."""
    company = (payload.get("company") or "").strip()
    ctype   = (payload.get("type") or "").strip()
    city    = (payload.get("city") or "").strip()
    website = (payload.get("website") or "").strip()
    context = (payload.get("context") or "").strip()

    bits: list[str] = []
    bits.append(f"Run a recon brief on **{company or 'this target'}**.")
    if ctype:   bits.append(f"Segment: {ctype}.")
    if city:    bits.append(f"Location: {city}.")
    if website: bits.append(f"Website: {website}.")
    if context: bits.append(f"Known context from operator: {context}.")

    bits.append(
        "Use web_search to ground every claim. Search the company's "
        "website, LinkedIn, Manitoba tender postings (MERX, Bids&Tenders), "
        "Winnipeg permit data, and recent press. Pull leadership names, "
        "active or recent projects, segment mix, and any hiring or "
        "tender signals from the last 60-90 days."
    )
    bits.append(
        "Then write the brief in the Market Intel format. Anything you "
        "cannot ground in a search result, prefix with `⚠` and move on. "
        "Do not pad with generic frameworks. If a section has no "
        "real evidence, write one honest sentence saying so and stop — "
        "do not invent."
    )
    return " ".join(bits)


def run_market_intel(payload: dict) -> dict:
    """Full pipeline: web_search recon + Opus 4.7 synthesis with task_budget."""
    global _MI_KILLED_REASON
    if _MI_KILLED_REASON:
        raise RuntimeError(f"Market Intel disabled by circuit breaker: {_MI_KILLED_REASON}")

    model           = os.getenv("MI_MODEL", "claude-opus-4-7")
    max_searches    = int(os.getenv("MI_MAX_SEARCHES", "5"))
    max_out_tokens  = int(os.getenv("MI_MAX_OUTPUT_TOKENS", "4000"))
    task_budget     = int(os.getenv("MI_TASK_BUDGET", "50000"))

    system = system_for("market_intel")
    user   = _build_user_prompt(payload)
    ai     = _anthropic.Anthropic()

    # Try the task_budget beta path first; fall back to standard call.
    resp = None
    try:
        resp = ai.beta.messages.create(
            model=model,
            max_tokens=max_out_tokens,
            system=system,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": max_searches,
            }],
            output_config={
                "effort": "high",
                "task_budget": {"type": "tokens", "total": task_budget},
            },
            betas=["task-budgets-2026-03-13"],
            messages=[{"role": "user", "content": user}],
        )
    except Exception as beta_exc:
        print(f"[MarketIntel] task_budget beta failed ({beta_exc}); falling back to standard call")
        resp = ai.messages.create(
            model=model,
            max_tokens=max_out_tokens,
            system=system,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": max_searches,
            }],
            messages=[{"role": "user", "content": user}],
        )

    # Stitch text blocks, count search invocations for billing
    text_parts: list[str] = []
    num_web_searches = 0
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "server_tool_use" and getattr(block, "name", "") == "web_search":
            num_web_searches += 1
            continue
        if btype == "web_search_tool_result":
            continue
        if hasattr(block, "text") and block.text:
            text_parts.append(block.text)
    raw_output = "\n".join(text_parts).strip()

    # Split the <crm-data> JSON from the human-readable brief.
    structured, brief = _split_crm_and_brief(raw_output)
    # The UI renders `output` as markdown — only show the brief portion,
    # not the raw JSON block.
    output = brief

    # Ingest into CRM. Tagged with date + company slug so we can trace it.
    crm_summary: dict = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    brief_path: str | None = None
    if structured and isinstance(structured, dict):
        try:
            company_slug = crm.slug(structured.get("company") or payload.get("company") or "")
            source_tag = f"market_intel_{datetime.now().strftime('%Y-%m-%d')}_{company_slug}"
            crm_summary = crm.upsert_from_research(structured, source_tag=source_tag)
            brief_path  = crm.save_research_brief(company_slug, structured, brief)
        except Exception as exc:
            print(f"[MarketIntel] CRM ingest failed: {exc}")
            crm_summary["error"] = str(exc)

    # Measure actual cost
    cost_usd = _compute_cost(model, getattr(resp, "usage", None), num_web_searches)
    in_t  = getattr(resp.usage, "input_tokens",  0) if resp.usage else 0
    out_t = getattr(resp.usage, "output_tokens", 0) if resp.usage else 0
    print(f"[MarketIntel] cost=${cost_usd}  in={in_t}t  out={out_t}t  web_searches={num_web_searches}  model={model}")

    if cost_usd > MI_CIRCUIT_BREAKER_USD:
        _MI_KILLED_REASON = (
            f"Last run cost ${cost_usd:.2f}, exceeding the ${MI_CIRCUIT_BREAKER_USD:.2f} "
            f"circuit-breaker ceiling. Disabled to prevent further spend."
        )
        print(f"[MarketIntel] CIRCUIT BREAKER TRIPPED: {_MI_KILLED_REASON}")

    return {
        "output":         output,
        "cost_usd":       cost_usd,
        "input_tokens":   in_t,
        "output_tokens":  out_t,
        "web_searches":   num_web_searches,
        "model":          model,
        "crm_summary":    crm_summary,
        "brief_path":     brief_path,
        "structured":     structured,
    }


def run(payload: dict) -> dict:
    """Capability entry point. Matches the shape of other capabilities
    (output, capability, timestamp, log_path) while adding cost telemetry."""
    try:
        result = run_market_intel(payload)
    except Exception as exc:
        # Last-resort fallback: if anything in the web_search path explodes,
        # fall back to the plain LLM-only brief so the user gets *something*.
        print(f"[MarketIntel] full pipeline failed ({exc}); falling back to standard capability")
        return _basic_run("market_intel", payload, max_tokens=2500)

    record = {
        "capability": "market_intel",
        "timestamp":  datetime.now().isoformat(),
        "input":      payload,
        "output":     result["output"],
        "cost_usd":   result["cost_usd"],
        "usage": {
            "input_tokens":  result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "web_searches":  result["web_searches"],
            "model":         result["model"],
        },
        "crm_summary": result.get("crm_summary"),
        "brief_path":  result.get("brief_path"),
    }
    try:
        log_path = logger.log_run("market_intel", record)
        record["log_path"] = str(log_path)
    except Exception:
        record["log_path"] = None
    return record
