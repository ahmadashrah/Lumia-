"""Procore connector — pushes Lumia check-ins into a project's Daily Log.

── API contract, and how sure we are of it ───────────────────────────────
Auth, host names and the company header below are stable, well-documented
Procore behaviour. The *daily log endpoint path and payload field names*
(DAILY_LOG_PATH / _build_payload) are the part to confirm against
https://developers.procore.com before going live — Procore exposes several
daily-log sub-resources and the right one depends on which log type you
want the entries to land in.

Everything uncertain is deliberately confined to those two places, so
correcting it is a small, local edit and not a rewrite.

Set PROCORE_SANDBOX=true to run against Procore's sandbox, which is the
right way to verify the above without touching a live GC's project.
"""
from __future__ import annotations

import os
import threading
import time

import httpx

from .base import Connector, ConnectorError
from .models import DailyLog, PushResult

# --- hosts ---------------------------------------------------------------
PROD = {"login": "https://login.procore.com", "api": "https://api.procore.com"}
SANDBOX = {"login": "https://login-sandbox.procore.com", "api": "https://sandbox.procore.com"}

# --- VERIFY THESE TWO AGAINST PROCORE'S DOCS BEFORE GO-LIVE --------------
DAILY_LOG_PATH = "/rest/v1.0/projects/{project_id}/daily_log/notes"
API_VERSION_HEADER = {"Procore-Api-Version": "v1.0"}


class ProcoreConnector(Connector):
    name = "procore"
    label = "Procore"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # -- config ----------------------------------------------------------
    @property
    def _hosts(self) -> dict:
        return SANDBOX if os.getenv("PROCORE_SANDBOX", "").lower() in ("1", "true", "yes") else PROD

    @property
    def _client_id(self) -> str:
        return os.getenv("PROCORE_CLIENT_ID", "")

    @property
    def _client_secret(self) -> str:
        return os.getenv("PROCORE_CLIENT_SECRET", "")

    @property
    def _company_id(self) -> str:
        return os.getenv("PROCORE_COMPANY_ID", "")

    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret and self._company_id)

    # -- auth ------------------------------------------------------------
    def _access_token(self) -> str:
        """Client-credentials token for a Procore service account, cached
        until 60s before expiry. Procore access tokens are short-lived, so
        this refreshes rather than storing one long-term."""
        with self._lock:
            if self._token and time.time() < self._token_expires_at - 60:
                return self._token
            if not self.is_configured():
                raise ConnectorError("Procore credentials not set", retryable=False)
            try:
                r = httpx.post(
                    f"{self._hosts['login']}/oauth/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                    timeout=20.0,
                )
            except httpx.HTTPError as exc:
                raise ConnectorError(f"Procore auth unreachable: {exc}", retryable=True) from exc
            if r.status_code >= 500:
                raise ConnectorError(f"Procore auth {r.status_code}", retryable=True)
            if r.status_code != 200:
                raise ConnectorError(
                    f"Procore auth rejected ({r.status_code}): {r.text[:200]}", retryable=False
                )
            body = r.json()
            self._token = body.get("access_token") or ""
            self._token_expires_at = time.time() + float(body.get("expires_in") or 3600)
            if not self._token:
                raise ConnectorError("Procore auth returned no access_token", retryable=False)
            return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._access_token()}",
            "Procore-Company-Id": self._company_id,
            "Content-Type": "application/json",
            **API_VERSION_HEADER,
        }

    # -- payload ---------------------------------------------------------
    @staticmethod
    def _build_payload(log: DailyLog) -> dict:
        """Map a DailyLog onto Procore's daily-log note shape.

        `source_id` is echoed into the note body so a duplicate push is
        visible to a human even where the API has no idempotency key."""
        body = log.as_narrative()
        if log.source_id:
            body += f"\n\n[lumia:checkin:{log.source_id}]"
        return {
            "notes_log": {
                "date": log.entry_date.isoformat(),
                "notes": body,
            }
        }

    # -- push ------------------------------------------------------------
    def push_daily_log(
        self, log: DailyLog, project_ref: str, *, dry_run: bool = False
    ) -> PushResult:
        if not project_ref:
            raise ConnectorError("no Procore project mapped for this job", retryable=False)

        payload = self._build_payload(log)
        headers = self._headers()          # authenticates even on a dry run
        url = self._hosts["api"] + DAILY_LOG_PATH.format(project_id=project_ref)

        if dry_run:
            return PushResult(
                ok=True, platform=self.name, dry_run=True,
                detail=f"would POST {url} ({len(payload['notes_log']['notes'])} chars)",
            )

        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=30.0)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Procore unreachable: {exc}", retryable=True) from exc

        if r.status_code in (200, 201):
            try:
                remote_id = str(r.json().get("id") or "")
            except Exception:
                remote_id = ""
            return PushResult(ok=True, platform=self.name, remote_id=remote_id,
                              detail=f"created ({r.status_code})")
        if r.status_code == 429 or r.status_code >= 500:
            raise ConnectorError(f"Procore {r.status_code} — will retry", retryable=True)
        raise ConnectorError(
            f"Procore rejected the push ({r.status_code}): {r.text[:300]}", retryable=False
        )
