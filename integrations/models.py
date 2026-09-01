"""Platform-neutral shapes that every connector speaks.

A Lumia check-in is converted to a DailyLog once, then each connector maps
that to its own API. Adding a platform means writing one adapter, not
touching the check-in path.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any


@dataclass(frozen=True)
class DailyLog:
    """One crew-day on one site, as Lumia knows it."""
    entry_date: date
    job_ref: str                      # Lumia jobs.id
    worker_name: str
    site_address: str = ""
    work_description: str = ""
    notes: str = ""
    tomorrows_plan: str = ""
    hours_worked: float | None = None
    start_time: str | None = None
    end_time: str | None = None
    plan_completion_percent: int | None = None
    photo_urls: list[str] = field(default_factory=list)
    quality_scores: dict[str, Any] = field(default_factory=dict)
    source_id: str | None = None      # Lumia checkins.id — the idempotency key

    @classmethod
    def from_checkin(cls, row: dict) -> "DailyLog":
        """Build from a Supabase `checkins` row."""
        raw = row.get("entry_date")
        if isinstance(raw, str):
            entry_date = date.fromisoformat(raw[:10])
        elif isinstance(raw, date):
            entry_date = raw
        else:
            entry_date = date.today()

        scores = {
            k: row.get(k) for k in (
                "tape_covering", "drop_sheets", "patching_process",
                "paint_execution", "site_control", "washing_tool_care",
                "avg_score",
            ) if row.get(k) is not None
        }
        if row.get("custom_scores"):
            scores["custom"] = row["custom_scores"]

        return cls(
            entry_date=entry_date,
            job_ref=str(row.get("job_id") or ""),
            worker_name=row.get("worker_name") or "",
            site_address=row.get("site_address") or "",
            work_description=row.get("work_description") or "",
            notes=row.get("notes") or "",
            tomorrows_plan=row.get("tomorrows_plan") or "",
            hours_worked=row.get("hours_worked"),
            start_time=row.get("start_time"),
            end_time=row.get("end_time"),
            plan_completion_percent=row.get("plan_completion_percent"),
            photo_urls=list(row.get("photo_urls") or []),
            quality_scores=scores,
            source_id=str(row["id"]) if row.get("id") is not None else None,
        )

    def as_narrative(self) -> str:
        """Human-readable body — what most platforms want in a log note."""
        bits = [f"{self.worker_name} — {self.site_address}".strip(" —")]
        if self.work_description:
            bits.append(f"Work completed: {self.work_description}")
        if self.hours_worked is not None:
            span = ""
            if self.start_time and self.end_time:
                span = f" ({self.start_time}–{self.end_time})"
            bits.append(f"Hours: {self.hours_worked}{span}")
        if self.plan_completion_percent is not None:
            bits.append(f"Plan completion: {self.plan_completion_percent}%")
        if self.tomorrows_plan:
            bits.append(f"Tomorrow: {self.tomorrows_plan}")
        if self.notes:
            bits.append(f"Notes: {self.notes}")
        return "\n".join(b for b in bits if b)


@dataclass
class PushResult:
    ok: bool
    platform: str
    remote_id: str | None = None
    detail: str = ""
    retryable: bool = False
    dry_run: bool = False

    def to_dict(self) -> dict:
        return asdict(self)
