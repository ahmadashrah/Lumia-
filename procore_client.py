"""
procore_client.py — Minimal, dependency-light Procore API client for Lumia.

Handles the two OAuth 2.0 grant types Procore supports for server apps:

  * authorization_code  — an owner clicks "Connect Procore" and approves Lumia.
                          Access tokens last ~2 h and are rotated with a
                          single-use refresh token, so tokens are persisted
                          through a TokenStore.
  * client_credentials  — a Data Connection App with a Developer Managed
                          Service Account (DMSA). No user interaction; a fresh
                          token is minted whenever the cached one expires.

Everything network-facing goes through ProcoreClient.request(), which adds the
company header, retries on 429/5xx and refreshes an expired token once.
"""
from __future__ import annotations

import os
import threading
import time
import urllib.parse
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# ENVIRONMENTS
# ---------------------------------------------------------------------------
ENVIRONMENTS: dict[str, dict[str, str]] = {
    "production": {
        "auth": "https://login.procore.com",
        "api":  "https://api.procore.com",
    },
    # Procore's developer sandbox (a.k.a. "monthly sandbox").
    "sandbox": {
        "auth": "https://login-sandbox.procore.com",
        "api":  "https://sandbox.procore.com",
    },
}

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
# Refresh a little before the token actually dies so an in-flight call cannot
# land on the far side of the expiry.
EXPIRY_SKEW_SECONDS = 120


class ProcoreError(RuntimeError):
    """Any failure talking to Procore — auth, HTTP or payload."""

    def __init__(self, message: str, status_code: int | None = None,
                 payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload

    def as_dict(self) -> dict:
        return {"error": str(self), "status_code": self.status_code,
                "detail": self.payload}


class ProcoreNotConnected(ProcoreError):
    """Raised when no usable credentials are available yet."""


# ---------------------------------------------------------------------------
# TOKEN STORAGE
# ---------------------------------------------------------------------------
class TokenStore:
    """Where the OAuth token lives between requests (and between deploys)."""

    def load(self) -> dict | None:
        raise NotImplementedError

    def save(self, token: dict) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError


class MemoryTokenStore(TokenStore):
    """Process-local storage. Fine for local dev, lost on restart."""

    def __init__(self) -> None:
        self._token: dict | None = None
        self._lock = threading.Lock()

    def load(self) -> dict | None:
        with self._lock:
            return dict(self._token) if self._token else None

    def save(self, token: dict) -> None:
        with self._lock:
            self._token = dict(token)

    def clear(self) -> None:
        with self._lock:
            self._token = None


class SupabaseTokenStore(TokenStore):
    """
    Persists the token in a Supabase table so it survives dyno restarts.

    Expected table (see PROCORE_INTEGRATION.md for the DDL):
        procore_tokens(id text primary key, access_token text,
                       refresh_token text, expires_at bigint,
                       token_type text, scope text, updated_at timestamptz)
    """

    def __init__(self, supabase_client, table: str = "procore_tokens",
                 row_id: str = "default"):
        self._sb = supabase_client
        self._table = table
        self._row_id = row_id
        self._fallback = MemoryTokenStore()

    def load(self) -> dict | None:
        try:
            res = (self._sb.table(self._table).select("*")
                   .eq("id", self._row_id).limit(1).execute())
            rows = res.data or []
            if rows:
                return rows[0]
        except Exception as exc:  # table missing, network blip, ...
            print(f"[Procore] Token load failed, using memory store: {exc}")
        return self._fallback.load()

    def save(self, token: dict) -> None:
        self._fallback.save(token)
        payload = {
            "id":            self._row_id,
            "access_token":  token.get("access_token"),
            "refresh_token": token.get("refresh_token"),
            "expires_at":    int(token.get("expires_at") or 0),
            "token_type":    token.get("token_type") or "Bearer",
            "scope":         token.get("scope") or "",
        }
        try:
            self._sb.table(self._table).upsert(payload).execute()
        except Exception as exc:
            print(f"[Procore] Token save failed (kept in memory only): {exc}")

    def clear(self) -> None:
        self._fallback.clear()
        try:
            self._sb.table(self._table).delete().eq("id", self._row_id).execute()
        except Exception as exc:
            print(f"[Procore] Token clear failed: {exc}")


# ---------------------------------------------------------------------------
# CLIENT
# ---------------------------------------------------------------------------
class ProcoreClient:
    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        company_id: str | int | None = None,
        redirect_uri: str = "",
        environment: str = "production",
        auth_base_url: str = "",
        api_base_url: str = "",
        api_version: str = "v1.0",
        token_store: TokenStore | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        transport: Any = None,
    ):
        env = ENVIRONMENTS.get(environment, ENVIRONMENTS["production"])
        self.client_id = client_id
        self.client_secret = client_secret
        self.company_id = str(company_id) if company_id else ""
        self.redirect_uri = redirect_uri
        self.environment = environment if environment in ENVIRONMENTS else "production"
        self.auth_base_url = (auth_base_url or env["auth"]).rstrip("/")
        self.api_base_url = (api_base_url or env["api"]).rstrip("/")
        self.api_version = api_version
        self.token_store = token_store or MemoryTokenStore()
        self.timeout = timeout
        self.max_retries = max_retries
        self._transport = transport          # injected in tests
        self._token_lock = threading.Lock()

    # -- construction --------------------------------------------------------
    @classmethod
    def from_env(cls, token_store: TokenStore | None = None) -> "ProcoreClient":
        return cls(
            client_id=os.getenv("PROCORE_CLIENT_ID", ""),
            client_secret=os.getenv("PROCORE_CLIENT_SECRET", ""),
            company_id=os.getenv("PROCORE_COMPANY_ID", ""),
            redirect_uri=os.getenv("PROCORE_REDIRECT_URI", ""),
            environment=os.getenv("PROCORE_ENV", "production").strip().lower(),
            auth_base_url=os.getenv("PROCORE_AUTH_BASE_URL", ""),
            api_base_url=os.getenv("PROCORE_API_BASE_URL", ""),
            token_store=token_store,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def use_client_credentials(self) -> bool:
        """Service-account mode: no redirect URI configured for a user flow."""
        return os.getenv("PROCORE_GRANT_TYPE", "").strip().lower() == "client_credentials" \
            or (self.is_configured and not self.redirect_uri)

    # -- HTTP plumbing -------------------------------------------------------
    def _http(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout, transport=self._transport,
                            follow_redirects=False)

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    # -- OAuth ---------------------------------------------------------------
    def authorization_url(self, state: str = "", redirect_uri: str = "") -> str:
        """URL the owner is sent to in order to approve Lumia."""
        if not self.is_configured:
            raise ProcoreNotConnected("PROCORE_CLIENT_ID / PROCORE_CLIENT_SECRET are not set.")
        redirect = redirect_uri or self.redirect_uri
        if not redirect:
            raise ProcoreNotConnected("PROCORE_REDIRECT_URI is not set.")
        params = {
            "response_type": "code",
            "client_id":     self.client_id,
            "redirect_uri":  redirect,
        }
        if state:
            params["state"] = state
        return f"{self.auth_base_url}/oauth/authorize?{urllib.parse.urlencode(params)}"

    def _token_request(self, data: dict) -> dict:
        with self._http() as http:
            resp = http.post(f"{self.auth_base_url}/oauth/token", data=data)
        payload = self._parse(resp)
        if resp.status_code >= 400:
            raise ProcoreError(
                f"Procore token request failed ({resp.status_code}).",
                status_code=resp.status_code, payload=payload,
            )
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise ProcoreError("Procore token response contained no access_token.",
                               status_code=resp.status_code, payload=payload)
        token = dict(payload)
        # created_at + expires_in are both returned; normalise to an absolute
        # epoch second so expiry checks do not depend on when we parsed it.
        expires_in = int(token.get("expires_in") or 0)
        created_at = int(token.get("created_at") or time.time())
        token["expires_at"] = created_at + expires_in if expires_in else int(time.time()) + 3600
        return token

    def exchange_code(self, code: str, redirect_uri: str = "") -> dict:
        """Trade an authorization code for a token and persist it."""
        token = self._token_request({
            "grant_type":    "authorization_code",
            "code":          code,
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri":  redirect_uri or self.redirect_uri,
        })
        self.token_store.save(token)
        return token

    def _refresh_token(self, refresh_token: str) -> dict:
        token = self._token_request({
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
        })
        # Procore rotates refresh tokens; keep the new one or we lock ourselves out.
        self.token_store.save(token)
        return token

    def _client_credentials_token(self) -> dict:
        token = self._token_request({
            "grant_type":    "client_credentials",
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
        })
        self.token_store.save(token)
        return token

    @staticmethod
    def _is_expired(token: dict) -> bool:
        expires_at = int(token.get("expires_at") or 0)
        return expires_at - EXPIRY_SKEW_SECONDS <= time.time()

    def access_token(self, force_refresh: bool = False) -> str:
        """Return a valid access token, minting or refreshing as needed."""
        if not self.is_configured:
            raise ProcoreNotConnected("Procore is not configured on this server.")
        with self._token_lock:
            token = self.token_store.load()
            if token and not force_refresh and not self._is_expired(token):
                return token["access_token"]
            if token and token.get("refresh_token"):
                try:
                    return self._refresh_token(token["refresh_token"])["access_token"]
                except ProcoreError as exc:
                    # A revoked/replayed refresh token is unrecoverable for the
                    # user flow, but client-credentials can just mint a new one.
                    if not self.use_client_credentials:
                        self.token_store.clear()
                        raise ProcoreNotConnected(
                            "Procore session expired — reconnect from the owner dashboard."
                        ) from exc
            if self.use_client_credentials:
                return self._client_credentials_token()["access_token"]
            raise ProcoreNotConnected(
                "Procore is not connected yet — connect from the owner dashboard."
            )

    def disconnect(self) -> None:
        self.token_store.clear()

    def connection_status(self) -> dict:
        token = self.token_store.load()
        return {
            "configured":   self.is_configured,
            "connected":    bool(token and token.get("access_token")),
            "mode":         "client_credentials" if self.use_client_credentials else "authorization_code",
            "environment":  self.environment,
            "api_base_url": self.api_base_url,
            "company_id":   self.company_id,
            "expires_at":   int(token.get("expires_at") or 0) if token else 0,
            "expired":      bool(token and self._is_expired(token)),
        }

    # -- requests ------------------------------------------------------------
    def request(self, method: str, path: str, *, params: dict | None = None,
                json: Any = None, company_id: str | int | None = None,
                _retry_auth: bool = True) -> Any:
        """Call a Procore REST endpoint and return the decoded body."""
        url = path if path.startswith("http") else f"{self.api_base_url}{path}"
        company = str(company_id or self.company_id or "")
        headers = {
            "Authorization": f"Bearer {self.access_token()}",
            "Accept":        "application/json",
        }
        if company:
            headers["Procore-Company-Id"] = company

        attempt = 0
        while True:
            attempt += 1
            with self._http() as http:
                resp = http.request(method, url, params=params, json=json,
                                    headers=headers)

            if resp.status_code == 401 and _retry_auth:
                headers["Authorization"] = f"Bearer {self.access_token(force_refresh=True)}"
                _retry_auth = False
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt <= self.max_retries:
                    retry_after = resp.headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after else 2.0 ** attempt
                    except ValueError:
                        delay = 2.0 ** attempt
                    time.sleep(min(delay, 30.0))
                    continue

            payload = self._parse(resp)
            if resp.status_code >= 400:
                raise ProcoreError(
                    f"Procore {method.upper()} {path} failed ({resp.status_code}).",
                    status_code=resp.status_code, payload=payload,
                )
            return payload

    def get(self, path: str, **kw) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw) -> Any:
        return self.request("POST", path, **kw)

    def _v(self, path: str) -> str:
        return f"/rest/{self.api_version}{path}"

    # -- endpoints -----------------------------------------------------------
    def list_companies(self) -> list[dict]:
        data = self.get(self._v("/companies"))
        return data if isinstance(data, list) else []

    def list_projects(self, company_id: str | int | None = None,
                      page: int = 1, per_page: int = 100) -> list[dict]:
        company = str(company_id or self.company_id or "")
        if not company:
            raise ProcoreError("PROCORE_COMPANY_ID is not set — cannot list projects.")
        data = self.get(self._v("/projects"), company_id=company,
                        params={"company_id": company, "page": page,
                                "per_page": per_page})
        return data if isinstance(data, list) else []

    def get_project(self, project_id: str | int) -> dict:
        data = self.get(self._v(f"/projects/{project_id}"))
        return data if isinstance(data, dict) else {}

    def find_project(self, needle: str,
                     company_id: str | int | None = None) -> dict | None:
        """Best-effort lookup of a project by name or address substring."""
        needle_l = (needle or "").strip().lower()
        if not needle_l:
            return None
        for project in self.list_projects(company_id=company_id):
            haystack = " ".join(str(project.get(k) or "") for k in
                                ("name", "display_name", "address", "project_number"))
            if needle_l in haystack.lower():
                return project
        return None

    def create_manpower_log(self, project_id: str | int, *, log_date: str,
                            num_workers: int = 1, num_hours: float = 8.0,
                            notes: str = "", vendor_id: int | None = None,
                            location_id: int | None = None) -> dict:
        """Daily Log → Manpower entry (who was on site, for how long)."""
        manpower_log: dict[str, Any] = {
            "date":        log_date,
            "datetime":    log_date,
            "num_workers": int(num_workers),
            "num_hours":   float(num_hours),
            "notes":       notes,
        }
        if vendor_id:
            manpower_log["vendor_id"] = int(vendor_id)
        if location_id:
            manpower_log["location_id"] = int(location_id)
        data = self.post(self._v(f"/projects/{project_id}/manpower_logs"),
                         json={"project_id": int(project_id),
                               "manpower_log": manpower_log})
        return data if isinstance(data, dict) else {}

    def create_notes_log(self, project_id: str | int, *, log_date: str,
                         notes: str, location_id: int | None = None) -> dict:
        """Daily Log → Notes entry (the narrative of the day)."""
        notes_log: dict[str, Any] = {"date": log_date, "datetime": log_date,
                                     "notes": notes}
        if location_id:
            notes_log["location_id"] = int(location_id)
        data = self.post(self._v(f"/projects/{project_id}/notes_logs"),
                         json={"project_id": int(project_id),
                               "notes_log": notes_log})
        return data if isinstance(data, dict) else {}

    def list_manpower_logs(self, project_id: str | int,
                           log_date: str = "") -> list[dict]:
        params = {"log_date": log_date} if log_date else None
        data = self.get(self._v(f"/projects/{project_id}/manpower_logs"),
                        params=params)
        return data if isinstance(data, list) else []

    def list_notes_logs(self, project_id: str | int,
                        log_date: str = "") -> list[dict]:
        params = {"log_date": log_date} if log_date else None
        data = self.get(self._v(f"/projects/{project_id}/notes_logs"),
                        params=params)
        return data if isinstance(data, list) else []
