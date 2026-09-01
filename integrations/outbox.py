"""Delivery of check-ins to construction platforms.

Two entry points:
  submit_checkin(row)  — called from the check-in path. Only enqueues; it
                         never calls a platform inline, so a slow or broken
                         GC API can't slow down or fail a crew's submission.
  process(limit)       — drains due work. Wire to the scheduler.

Backoff is capped and gives up rather than retrying forever, so a genuinely
bad mapping surfaces as a failed row instead of hammering a GC's API.
"""
from __future__ import annotations

from .base import ConnectorError
from .models import DailyLog
from . import registry, store

BACKOFF_MINUTES = {1: 5, 2: 15, 3: 60, 4: 240}
MAX_ATTEMPTS = 5


def submit_checkin(checkin_row: dict, platforms: list[str] | None = None) -> list[dict]:
    """Queue a saved check-in for every platform this job is mapped to.

    Returns one status dict per platform considered. Never raises — a
    delivery problem must not fail the check-in that triggered it.
    """
    out: list[dict] = []
    try:
        log = DailyLog.from_checkin(checkin_row)
    except Exception as exc:
        return [{"platform": "-", "queued": False, "reason": f"unreadable check-in: {exc}"}]

    names = platforms or list(registry.all_connectors())
    for name in names:
        conn = registry.get(name)
        if conn is None:
            out.append({"platform": name, "queued": False, "reason": "unknown connector"})
            continue
        if not conn.is_configured():
            out.append({"platform": name, "queued": False, "reason": "not configured"})
            continue
        mapping = store.mapping_for(log.job_ref, name)
        if not mapping:
            out.append({"platform": name, "queued": False, "reason": "job not mapped"})
            continue
        if log.source_id and store.already_sent(name, log.source_id):
            out.append({"platform": name, "queued": False, "reason": "already sent"})
            continue
        queued = store.enqueue(
            name, log.job_ref, str(mapping.get("project_ref") or ""),
            log.source_id, {"checkin": checkin_row, "dry_run": bool(mapping.get("dry_run", True))},
        )
        out.append({"platform": name, "queued": queued,
                    "reason": "" if queued else "outbox unavailable"})
    return out


def process(limit: int = 25) -> dict:
    """Attempt every due outbox row. Safe to call on a schedule."""
    rows = store.due(limit)
    sent = failed = retried = 0

    for row in rows:
        attempts = int(row.get("attempts") or 0) + 1
        name = row.get("platform") or ""
        conn = registry.get(name)
        if conn is None:
            store.mark(row["id"], "failed", error=f"unknown connector {name}", attempts=attempts)
            failed += 1
            continue

        payload = row.get("payload") or {}
        try:
            log = DailyLog.from_checkin(payload.get("checkin") or {})
            result = conn.push_daily_log(
                log, str(row.get("project_ref") or ""),
                dry_run=bool(payload.get("dry_run", True)),
            )
            store.mark(row["id"], "sent", attempts=attempts,
                       remote_id=result.remote_id or "", error=result.detail)
            sent += 1
        except ConnectorError as exc:
            if exc.retryable and attempts < MAX_ATTEMPTS:
                store.mark(row["id"], "pending", error=str(exc), attempts=attempts,
                           backoff_minutes=BACKOFF_MINUTES.get(attempts, 240))
                retried += 1
            else:
                store.mark(row["id"], "failed", error=str(exc), attempts=attempts)
                failed += 1
        except Exception as exc:                       # never let one bad row stop the drain
            store.mark(row["id"], "failed", error=f"unexpected: {exc}", attempts=attempts)
            failed += 1

    return {"considered": len(rows), "sent": sent, "retried": retried, "failed": failed}
