"""Integration-layer tests.

Procore is unreachable from CI and from the dev container, so every network
call is mocked. These pin down the behaviour we actually depend on: auth
caching, the retryable/terminal split, idempotency, and backoff.
"""
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from integrations import registry, outbox, store            # noqa: E402
from integrations.base import ConnectorError                 # noqa: E402
from integrations.models import DailyLog                     # noqa: E402
from integrations.procore import ProcoreConnector            # noqa: E402


def resp(status, payload=None, text=""):
    m = mock.Mock()
    m.status_code = status
    m.json.return_value = payload if payload is not None else {}
    m.text = text
    return m


CHECKIN = {
    "id": 7, "entry_date": "2026-09-01", "job_id": 42, "worker_name": "Sam",
    "site_address": "12 Elm St", "work_description": "Primed east wall",
    "hours_worked": 7.5, "start_time": "08:00", "end_time": "16:00",
    "plan_completion_percent": 80, "tomorrows_plan": "Second coat",
    "notes": "Low on primer", "paint_execution": 9, "avg_score": 8.5,
    "photo_urls": ["a.jpg"],
}

CREDS = {"PROCORE_CLIENT_ID": "cid", "PROCORE_CLIENT_SECRET": "secret",
         "PROCORE_COMPANY_ID": "1234"}


class TestDailyLog(unittest.TestCase):
    def test_maps_checkin_fields(self):
        d = DailyLog.from_checkin(CHECKIN)
        self.assertEqual(d.entry_date, date(2026, 9, 1))
        self.assertEqual(d.job_ref, "42")
        self.assertEqual(d.source_id, "7")
        self.assertEqual(d.quality_scores["paint_execution"], 9)

    def test_narrative_includes_the_operational_facts(self):
        n = DailyLog.from_checkin(CHECKIN).as_narrative()
        for expected in ("Sam", "12 Elm St", "Primed east wall", "7.5", "80%", "Second coat"):
            self.assertIn(expected, n)

    def test_survives_a_sparse_row(self):
        d = DailyLog.from_checkin({"worker_name": "Jo"})
        self.assertEqual(d.worker_name, "Jo")
        self.assertIsInstance(d.entry_date, date)


class TestProcoreAuth(unittest.TestCase):
    def setUp(self):
        self.c = ProcoreConnector()

    def test_unconfigured_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ProcoreConnector().is_configured())

    def test_token_is_cached_between_calls(self):
        with mock.patch.dict(os.environ, CREDS), \
             mock.patch("integrations.procore.httpx.post",
                        return_value=resp(200, {"access_token": "t1", "expires_in": 3600})) as p:
            self.assertEqual(self.c._access_token(), "t1")
            self.assertEqual(self.c._access_token(), "t1")
            self.assertEqual(p.call_count, 1, "token should be cached, not re-fetched")

    def test_server_error_is_retryable(self):
        with mock.patch.dict(os.environ, CREDS), \
             mock.patch("integrations.procore.httpx.post", return_value=resp(503)):
            with self.assertRaises(ConnectorError) as ctx:
                self.c._access_token()
            self.assertTrue(ctx.exception.retryable)

    def test_bad_credentials_are_not_retryable(self):
        with mock.patch.dict(os.environ, CREDS), \
             mock.patch("integrations.procore.httpx.post", return_value=resp(401, text="bad creds")):
            with self.assertRaises(ConnectorError) as ctx:
                self.c._access_token()
            self.assertFalse(ctx.exception.retryable)


class TestProcorePush(unittest.TestCase):
    def setUp(self):
        self.c = ProcoreConnector()
        self.c._token, self.c._token_expires_at = "tok", 9e18   # pre-authenticated
        self.log = DailyLog.from_checkin(CHECKIN)

    def test_successful_push_returns_remote_id(self):
        with mock.patch.dict(os.environ, CREDS), \
             mock.patch("integrations.procore.httpx.post", return_value=resp(201, {"id": 99})):
            r = self.c.push_daily_log(self.log, "555")
            self.assertTrue(r.ok)
            self.assertEqual(r.remote_id, "99")

    def test_rate_limit_and_5xx_are_retryable(self):
        for status in (429, 500, 502):
            with mock.patch.dict(os.environ, CREDS), \
                 mock.patch("integrations.procore.httpx.post", return_value=resp(status)):
                with self.assertRaises(ConnectorError) as ctx:
                    self.c.push_daily_log(self.log, "555")
                self.assertTrue(ctx.exception.retryable, f"{status} should retry")

    def test_validation_rejection_is_terminal(self):
        with mock.patch.dict(os.environ, CREDS), \
             mock.patch("integrations.procore.httpx.post", return_value=resp(422, text="bad field")):
            with self.assertRaises(ConnectorError) as ctx:
                self.c.push_daily_log(self.log, "555")
            self.assertFalse(ctx.exception.retryable)

    def test_missing_project_mapping_is_terminal(self):
        with mock.patch.dict(os.environ, CREDS):
            with self.assertRaises(ConnectorError) as ctx:
                self.c.push_daily_log(self.log, "")
            self.assertFalse(ctx.exception.retryable)

    def test_dry_run_never_writes(self):
        with mock.patch.dict(os.environ, CREDS), \
             mock.patch("integrations.procore.httpx.post") as p:
            r = self.c.push_daily_log(self.log, "555", dry_run=True)
            self.assertTrue(r.ok and r.dry_run)
            p.assert_not_called()

    def test_payload_carries_the_idempotency_marker(self):
        body = self.c._build_payload(self.log)["notes_log"]["notes"]
        self.assertIn("[lumia:checkin:7]", body)


class TestOutbox(unittest.TestCase):
    def test_submit_is_a_noop_when_nothing_is_configured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            res = outbox.submit_checkin(CHECKIN)
            self.assertTrue(res, "should report per-platform status")
            self.assertFalse(any(r["queued"] for r in res))

    def test_submit_skips_an_unmapped_job(self):
        with mock.patch.dict(os.environ, CREDS), \
             mock.patch.object(store, "mapping_for", return_value=None):
            res = outbox.submit_checkin(CHECKIN, ["procore"])
            self.assertEqual(res[0]["reason"], "job not mapped")

    def test_submit_will_not_resend_a_checkin(self):
        with mock.patch.dict(os.environ, CREDS), \
             mock.patch.object(store, "mapping_for", return_value={"project_ref": "555", "enabled": True}), \
             mock.patch.object(store, "already_sent", return_value=True), \
             mock.patch.object(store, "enqueue") as enq:
            res = outbox.submit_checkin(CHECKIN, ["procore"])
            self.assertEqual(res[0]["reason"], "already sent")
            enq.assert_not_called()

    def test_submit_never_raises_on_a_malformed_row(self):
        self.assertTrue(outbox.submit_checkin({"entry_date": object()}))

    def _row(self, attempts=0):
        return {"id": 1, "platform": "procore", "project_ref": "555", "attempts": attempts,
                "payload": {"checkin": CHECKIN, "dry_run": False}}

    def test_retryable_failure_backs_off_and_stays_pending(self):
        conn = mock.Mock()
        conn.push_daily_log.side_effect = ConnectorError("503", retryable=True)
        with mock.patch.object(store, "due", return_value=[self._row()]), \
             mock.patch.object(registry, "get", return_value=conn), \
             mock.patch.object(store, "mark") as mk:
            stats = outbox.process()
            self.assertEqual(stats["retried"], 1)
            self.assertEqual(mk.call_args.args[1], "pending")
            self.assertEqual(mk.call_args.kwargs["backoff_minutes"], 5)

    def test_gives_up_at_the_attempt_ceiling(self):
        conn = mock.Mock()
        conn.push_daily_log.side_effect = ConnectorError("503", retryable=True)
        with mock.patch.object(store, "due", return_value=[self._row(attempts=outbox.MAX_ATTEMPTS - 1)]), \
             mock.patch.object(registry, "get", return_value=conn), \
             mock.patch.object(store, "mark") as mk:
            stats = outbox.process()
            self.assertEqual(stats["failed"], 1)
            self.assertEqual(mk.call_args.args[1], "failed")

    def test_terminal_failure_is_not_retried(self):
        conn = mock.Mock()
        conn.push_daily_log.side_effect = ConnectorError("422", retryable=False)
        with mock.patch.object(store, "due", return_value=[self._row()]), \
             mock.patch.object(registry, "get", return_value=conn), \
             mock.patch.object(store, "mark") as mk:
            self.assertEqual(outbox.process()["failed"], 1)
            self.assertEqual(mk.call_args.args[1], "failed")

    def test_one_bad_row_does_not_stop_the_drain(self):
        boom, good = mock.Mock(), mock.Mock()
        boom.push_daily_log.side_effect = RuntimeError("kaboom")
        good.push_daily_log.return_value = mock.Mock(remote_id="99", detail="ok")
        rows = [dict(self._row(), id=1), dict(self._row(), id=2)]
        with mock.patch.object(store, "due", return_value=rows), \
             mock.patch.object(registry, "get", side_effect=[boom, good]), \
             mock.patch.object(store, "mark"):
            stats = outbox.process()
            self.assertEqual((stats["failed"], stats["sent"]), (1, 1))


class TestRegistry(unittest.TestCase):
    def test_discovers_procore_without_central_registration(self):
        self.assertIn("procore", registry.all_connectors(refresh=True))

    def test_configured_is_empty_without_credentials(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(list(registry.configured()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
