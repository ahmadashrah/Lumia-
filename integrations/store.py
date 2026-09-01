"""Persistence for integrations: job->project mapping and the push outbox.

Both degrade to no-ops when Supabase isn't configured, so Lumia still boots
and check-ins still save with an empty environment.

Expected tables (see docs/integrations.md for the DDL):
  integration_job_map(job_id, platform, project_ref, enabled, dry_run)
  integration_outbox(id, platform, job_ref, project_ref, source_id,
                     payload, status, attempts, last_error, next_attempt_at)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

MAP_TABLE = "integration_job_map"
OUTBOX_TABLE = "integration_outbox"

_client = None
_tried = False


def client():
    """Lazy Supabase client. Returns None when unconfigured."""
    global _client, _tried
    if _tried:
        return _client
    _tried = True
    url, key = os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_KEY", "")
    if not (url and key):
        return None
    try:
        from supabase import create_client
        _client = create_client(url, key)
    except Exception as exc:
        print(f"[integrations] Supabase unavailable: {exc}")
        _client = None
    return _client


# --- job -> project mapping ---------------------------------------------
def mapping_for(job_ref: str, platform: str) -> dict | None:
    """The platform project this Lumia job pushes to, if any is enabled."""
    sb = client()
    if not sb or not job_ref:
        return None
    try:
        rows = (sb.table(MAP_TABLE).select("*")
                .eq("job_id", job_ref).eq("platform", platform)
                .limit(1).execute().data or [])
    except Exception as exc:
        print(f"[integrations] mapping lookup failed: {exc}")
        return None
    if not rows:
        return None
    row = rows[0]
    return row if row.get("enabled") else None


def set_mapping(job_ref: str, platform: str, project_ref: str,
                *, enabled: bool = True, dry_run: bool = True) -> dict | None:
    sb = client()
    if not sb:
        return None
    payload = {"job_id": job_ref, "platform": platform, "project_ref": project_ref,
               "enabled": enabled, "dry_run": dry_run}
    try:
        return (sb.table(MAP_TABLE).upsert(payload, on_conflict="job_id,platform")
                .execute().data or [None])[0]
    except Exception as exc:
        print(f"[integrations] mapping upsert failed: {exc}")
        return None


# --- outbox --------------------------------------------------------------
def enqueue(platform: str, job_ref: str, project_ref: str,
            source_id: str | None, payload: dict) -> bool:
    sb = client()
    if not sb:
        return False
    try:
        sb.table(OUTBOX_TABLE).insert({
            "platform": platform, "job_ref": job_ref, "project_ref": project_ref,
            "source_id": source_id, "payload": payload,
            "status": "pending", "attempts": 0,
            "next_attempt_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True
    except Exception as exc:
        print(f"[integrations] enqueue failed: {exc}")
        return False


def already_sent(platform: str, source_id: str) -> bool:
    """Idempotency guard — a check-in must not reach a GC's project twice."""
    sb = client()
    if not sb or not source_id:
        return False
    try:
        rows = (sb.table(OUTBOX_TABLE).select("id")
                .eq("platform", platform).eq("source_id", source_id)
                .eq("status", "sent").limit(1).execute().data or [])
        return bool(rows)
    except Exception:
        return False


def due(limit: int = 25) -> list[dict]:
    sb = client()
    if not sb:
        return []
    try:
        now = datetime.now(timezone.utc).isoformat()
        return (sb.table(OUTBOX_TABLE).select("*")
                .eq("status", "pending").lte("next_attempt_at", now)
                .order("next_attempt_at").limit(limit).execute().data or [])
    except Exception as exc:
        print(f"[integrations] outbox read failed: {exc}")
        return []


def mark(row_id, status: str, *, error: str = "", attempts: int = 0,
         backoff_minutes: int | None = None, remote_id: str = "") -> None:
    sb = client()
    if not sb:
        return
    patch = {"status": status, "attempts": attempts, "last_error": error[:500]}
    if remote_id:
        patch["remote_id"] = remote_id
    if backoff_minutes is not None:
        patch["next_attempt_at"] = (
            datetime.now(timezone.utc) + timedelta(minutes=backoff_minutes)
        ).isoformat()
    try:
        sb.table(OUTBOX_TABLE).update(patch).eq("id", row_id).execute()
    except Exception as exc:
        print(f"[integrations] outbox update failed: {exc}")
