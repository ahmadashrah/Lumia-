"""
test_procore.py — Offline tests for the Procore integration.

Every Procore call is answered by an httpx MockTransport, so the suite runs
without network access or credentials:

    python -m unittest test_procore -v
"""
from __future__ import annotations

import json
import time
import unittest

import httpx
from flask import Flask

import procore_integration as pi
from procore_client import (
    MemoryTokenStore,
    ProcoreClient,
    ProcoreError,
    ProcoreNotConnected,
)


class FakeProcore:
    """A tiny stand-in for the Procore REST API."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.manpower_logs: list[dict] = []
        self.notes_logs: list[dict] = []
        self.token_calls: list[dict] = []
        self.fail_next_notes = False
        self.rate_limit_once = False
        self._rate_limited = False
        self._next_id = 100

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if path == "/oauth/token":
            form = dict(httpx.QueryParams(request.content.decode()))
            self.token_calls.append(form)
            if form.get("refresh_token") == "revoked":
                return httpx.Response(401, json={"error": "invalid_grant"})
            return httpx.Response(200, json={
                "access_token":  f"tok-{form.get('grant_type')}-{len(self.token_calls)}",
                "refresh_token": "refresh-new",
                "token_type":    "Bearer",
                "expires_in":    7200,
                "created_at":    int(time.time()),
            })

        if request.headers.get("Authorization", "") == "Bearer expired":
            return httpx.Response(401, json={"errors": "unauthorized"})

        if self.rate_limit_once and not self._rate_limited:
            self._rate_limited = True
            return httpx.Response(429, headers={"Retry-After": "0"},
                                  json={"errors": "rate limited"})

        if path == "/rest/v1.0/companies":
            return httpx.Response(200, json=[{"id": 7, "name": "Ashrah Painting"}])

        if path == "/rest/v1.0/projects":
            return httpx.Response(200, json=[
                {"id": 42, "name": "23 Falcon Ridge", "address": "23 Falcon Ridge Dr",
                 "active": True},
                {"id": 43, "name": "Old Job", "address": "9 Elm St", "active": False},
            ])

        if path.endswith("/manpower_logs") and request.method == "POST":
            body = json.loads(request.content)
            entry = dict(body["manpower_log"], id=self._id())
            self.manpower_logs.append(entry)
            return httpx.Response(201, json=entry)

        if path.endswith("/notes_logs") and request.method == "POST":
            if self.fail_next_notes:
                self.fail_next_notes = False
                return httpx.Response(422, json={"errors": {"notes": ["is invalid"]}})
            body = json.loads(request.content)
            entry = dict(body["notes_log"], id=self._id())
            self.notes_logs.append(entry)
            return httpx.Response(201, json=entry)

        return httpx.Response(404, json={"errors": f"no stub for {path}"})


def make_client(fake: FakeProcore, **kw) -> ProcoreClient:
    defaults = dict(
        client_id="cid", client_secret="secret", company_id="7",
        redirect_uri="https://lumia.example.com/procore/callback",
        auth_base_url="https://login.procore.test",
        api_base_url="https://api.procore.test",
        token_store=MemoryTokenStore(), transport=fake.transport(),
        max_retries=2,
    )
    defaults.update(kw)
    return ProcoreClient(**defaults)


class TestAuth(unittest.TestCase):
    def setUp(self):
        self.fake = FakeProcore()

    def test_authorization_url(self):
        url = make_client(self.fake).authorization_url(state="xyz")
        self.assertTrue(url.startswith("https://login.procore.test/oauth/authorize?"))
        self.assertIn("response_type=code", url)
        self.assertIn("client_id=cid", url)
        self.assertIn("state=xyz", url)

    def test_exchange_code_persists_token(self):
        client = make_client(self.fake)
        token = client.exchange_code("the-code")
        self.assertEqual(self.fake.token_calls[0]["grant_type"], "authorization_code")
        self.assertGreater(token["expires_at"], time.time())
        self.assertEqual(client.token_store.load()["access_token"], token["access_token"])
        self.assertTrue(client.connection_status()["connected"])

    def test_expired_token_is_refreshed(self):
        client = make_client(self.fake)
        client.token_store.save({"access_token": "old", "refresh_token": "r1",
                                 "expires_at": int(time.time()) - 10})
        self.assertNotEqual(client.access_token(), "old")
        self.assertEqual(self.fake.token_calls[-1]["grant_type"], "refresh_token")
        # The rotated refresh token replaces the used one.
        self.assertEqual(client.token_store.load()["refresh_token"], "refresh-new")

    def test_revoked_refresh_token_requires_reconnect(self):
        client = make_client(self.fake)
        client.token_store.save({"access_token": "old", "refresh_token": "revoked",
                                 "expires_at": int(time.time()) - 10})
        with self.assertRaises(ProcoreNotConnected):
            client.access_token()
        self.assertIsNone(client.token_store.load())

    def test_client_credentials_mode_mints_its_own_token(self):
        client = make_client(self.fake, redirect_uri="")
        self.assertTrue(client.use_client_credentials)
        self.assertTrue(client.access_token().startswith("tok-client_credentials"))

    def test_unconfigured_client_raises(self):
        client = make_client(self.fake, client_id="", client_secret="")
        self.assertFalse(client.is_configured)
        with self.assertRaises(ProcoreNotConnected):
            client.access_token()


class TestRequests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeProcore()
        self.client = make_client(self.fake)
        self.client.token_store.save({"access_token": "good", "refresh_token": "r1",
                                      "expires_at": int(time.time()) + 3600})

    def test_company_header_is_sent(self):
        self.assertEqual(self.client.list_companies()[0]["name"], "Ashrah Painting")
        self.assertEqual(self.fake.requests[-1].headers["Procore-Company-Id"], "7")

    def test_401_triggers_one_refresh_and_retry(self):
        self.client.token_store.save({"access_token": "expired", "refresh_token": "r1",
                                      "expires_at": int(time.time()) + 3600})
        projects = self.client.list_projects()
        self.assertEqual(projects[0]["id"], 42)
        self.assertEqual(self.fake.token_calls[-1]["grant_type"], "refresh_token")

    def test_429_is_retried(self):
        self.fake.rate_limit_once = True
        self.assertEqual(self.client.list_companies()[0]["id"], 7)

    def test_http_error_carries_payload(self):
        with self.assertRaises(ProcoreError) as ctx:
            self.client.get("/rest/v1.0/nonexistent")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("no stub", str(ctx.exception.payload))

    def test_find_project_matches_address(self):
        project = self.client.find_project("falcon ridge")
        self.assertEqual(project["id"], 42)

    def test_create_daily_log_entries(self):
        self.client.create_manpower_log(42, log_date="2026-08-31", num_workers=2,
                                        num_hours=7.5, notes="Ammar — primed hallway")
        self.client.create_notes_log(42, log_date="2026-08-31", notes="All good")
        self.assertEqual(self.fake.manpower_logs[0]["num_workers"], 2)
        self.assertEqual(self.fake.manpower_logs[0]["num_hours"], 7.5)
        self.assertEqual(self.fake.notes_logs[0]["date"], "2026-08-31")


CHECKIN = {
    "id": "checkin-1",
    "entry_date": "2026-08-31",
    "worker_name": "Ammar",
    "site_address": "23 Falcon Ridge Dr, Winnipeg",
    "work_description": "Primed and painted the upstairs hallway.",
    "tomorrows_plan": "Second coat on the trim.",
    "notes": "Client asked about the ceiling.",
    "custom_scores": "Primer: 9/10",
    "avg_score": 8,
    "tape_covering": 9, "drop_sheets": 8, "patching_process": 7,
    "paint_execution": 9, "site_control": 8, "washing_tool_care": 8,
    "photo_urls": "https://cdn.example.com/a.jpg,https://cdn.example.com/b.jpg",
}


class TestSync(unittest.TestCase):
    def setUp(self):
        self.fake = FakeProcore()
        pi._supabase = None
        pi._mem_links.clear()
        pi._mem_sync_log.clear()
        pi._client = make_client(self.fake)
        pi._client.token_store.save({"access_token": "good", "refresh_token": "r1",
                                     "expires_at": int(time.time()) + 3600})

    def test_note_contains_the_days_detail(self):
        note = pi.format_daily_note(CHECKIN)
        self.assertIn("Ammar", note)
        self.assertIn("Primed and painted the upstairs hallway.", note)
        self.assertIn("Second coat on the trim.", note)
        self.assertIn("Paint Execution: 9/10", note)
        self.assertIn("Primer: 9/10", note)
        self.assertIn("https://cdn.example.com/b.jpg", note)

    def test_unlinked_site_is_reported_not_pushed(self):
        result = pi.sync_checkin(CHECKIN)
        self.assertEqual(result["status"], "unlinked")
        self.assertFalse(self.fake.manpower_logs)
        self.assertEqual(pi.list_sync_log()[0]["status"], "unlinked")

    def test_linked_site_creates_both_log_entries(self):
        pi.add_link("23 falcon", 42, "23 Falcon Ridge")
        result = pi.sync_checkin(CHECKIN)
        self.assertEqual(result["status"], "synced")
        self.assertEqual(result["project_id"], 42)
        self.assertEqual(len(self.fake.manpower_logs), 1)
        self.assertEqual(len(self.fake.notes_logs), 1)
        self.assertIn("Ammar", self.fake.manpower_logs[0]["notes"])

    def test_longest_matching_keyword_wins(self):
        pi.add_link("23 falcon", 42, "Generic")
        pi.add_link("23 falcon ridge", 99, "Specific")
        self.assertEqual(pi.find_link_for_site(CHECKIN["site_address"])["procore_project_id"], 99)

    def test_second_push_is_deduplicated(self):
        pi.add_link("23 falcon", 42, "23 Falcon Ridge")
        pi.sync_checkin(CHECKIN)
        again = pi.sync_checkin(CHECKIN)
        self.assertEqual(again["status"], "duplicate")
        self.assertEqual(len(self.fake.manpower_logs), 1)
        forced = pi.sync_checkin(CHECKIN, force=True)
        self.assertEqual(forced["status"], "synced")
        self.assertEqual(len(self.fake.manpower_logs), 2)

    def test_partial_failure_keeps_the_half_that_worked(self):
        pi.add_link("23 falcon", 42, "23 Falcon Ridge")
        self.fake.fail_next_notes = True
        result = pi.sync_checkin(CHECKIN)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(self.fake.manpower_logs), 1)
        self.assertIn("notes log", result["reason"])

    def test_sync_never_raises_when_procore_is_unconfigured(self):
        pi._client = make_client(self.fake, client_id="", client_secret="")
        pi.add_link("23 falcon", 42, "23 Falcon Ridge")
        self.assertEqual(pi.sync_checkin(CHECKIN)["status"], "skipped")


class TestRoutes(unittest.TestCase):
    def setUp(self):
        self.fake = FakeProcore()
        app = Flask(__name__)
        app.secret_key = "test"
        app.add_url_rule("/login", "login_page", lambda: "login")
        pi._supabase = None
        pi._mem_links.clear()
        pi._mem_sync_log.clear()
        app.register_blueprint(pi.procore_bp)
        pi._client = make_client(self.fake)
        pi._client.token_store.save({"access_token": "good", "refresh_token": "r1",
                                     "expires_at": int(time.time()) + 3600})
        self.app = app
        self.c = app.test_client()

    def _login_owner(self):
        with self.c.session_transaction() as sess:
            sess["role"] = "owner"

    def test_api_requires_owner(self):
        self.assertEqual(self.c.get("/api/procore/status").status_code, 403)
        with self.c.session_transaction() as sess:
            sess["role"] = "manager"
        self.assertEqual(self.c.get("/api/procore/status").status_code, 403)

    def test_status_and_projects(self):
        self._login_owner()
        status = self.c.get("/api/procore/status").get_json()
        self.assertTrue(status["configured"])
        self.assertTrue(status["connected"])
        self.assertEqual(status["mode"], "authorization_code")
        projects = self.c.get("/api/procore/projects").get_json()
        self.assertEqual(projects[0]["name"], "23 Falcon Ridge")

    def test_link_lifecycle(self):
        self._login_owner()
        created = self.c.post("/api/procore/link", json={
            "site_keyword": "23 Falcon", "procore_project_id": 42,
            "procore_project_name": "23 Falcon Ridge"}).get_json()
        self.assertTrue(created["ok"])
        self.assertEqual(created["link"]["site_keyword"], "23 falcon")
        links = self.c.get("/api/procore/links").get_json()
        self.assertEqual(len(links), 1)
        self.c.post(f"/api/procore/unlink/{links[0]['id']}")
        self.assertEqual(self.c.get("/api/procore/links").get_json(), [])

    def test_link_validates_input(self):
        self._login_owner()
        r = self.c.post("/api/procore/link", json={"site_keyword": "x"})
        self.assertEqual(r.status_code, 400)

    def test_connect_redirects_to_procore(self):
        self._login_owner()
        r = self.c.get("/procore/connect")
        self.assertEqual(r.status_code, 302)
        self.assertIn("login.procore.test/oauth/authorize", r.headers["Location"])

    def test_callback_rejects_a_mismatched_state(self):
        r = self.c.get("/procore/callback?code=abc&state=forged")
        self.assertEqual(r.status_code, 400)

    def test_callback_exchanges_the_code(self):
        self._login_owner()
        self.c.get("/procore/connect")          # seeds the state in the session
        with self.c.session_transaction() as sess:
            state = sess["procore_oauth_state"]
        r = self.c.get(f"/procore/callback?code=abc&state={state}")
        self.assertEqual(r.status_code, 302)
        self.assertIn("procore=connected", r.headers["Location"])
        self.assertEqual(self.fake.token_calls[-1]["grant_type"], "authorization_code")

    def test_disconnect_clears_the_token(self):
        self._login_owner()
        self.assertTrue(self.c.post("/api/procore/disconnect").get_json()["ok"])
        self.assertFalse(self.c.get("/api/procore/status").get_json()["connected"])


if __name__ == "__main__":
    unittest.main()
