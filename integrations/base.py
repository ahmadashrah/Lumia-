"""The contract every platform connector implements."""
from __future__ import annotations

from abc import ABC, abstractmethod

from .models import DailyLog, PushResult


class Connector(ABC):
    """One construction platform.

    Connectors must be safe to construct without credentials — Lumia boots
    with an empty environment, so nothing here may raise at import or
    __init__ time. Report readiness through is_configured() instead.
    """

    name: str = "base"
    label: str = "Base"

    @abstractmethod
    def is_configured(self) -> bool:
        """True when credentials are present. Never raises."""

    @abstractmethod
    def push_daily_log(
        self, log: DailyLog, project_ref: str, *, dry_run: bool = False
    ) -> PushResult:
        """Send one crew-day to the platform.

        Must be idempotent on log.source_id where the platform allows it, so
        an outbox retry cannot create duplicate entries in a GC's system.

        dry_run must perform auth and payload construction but stop short of
        writing, so a mapping can be validated against a live account without
        putting anything in front of the GC.
        """

    def health(self) -> dict:
        return {"platform": self.name, "configured": self.is_configured()}


class ConnectorError(RuntimeError):
    """Connector failure. retryable=True for transient faults (5xx, rate
    limit, network); False for anything a retry cannot fix (bad mapping,
    revoked token, validation rejection)."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable
