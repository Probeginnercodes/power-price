"""Hosted API ownership, quota, restart and worker-boundary checks."""

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from build_pages import build_pages
from hosted_api import create_app
from hosted_settings import HostedSettings
from hosted_store import JobStore, QueueLimitError
from hosted_worker import execute_job, job_directory

OPTIONS = {"mode": "demo", "days": 1, "training_days": 90, "acknowledge": False}


class HostedTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = HostedSettings(
            root=Path(self.directory.name) / "state",
            seed_directory=Path(self.directory.name) / "seed",
        )
        self.app = create_app(self.settings)
        self.store = self.app.state.store
        self.client = TestClient(self.app)
        self.origin = {"Origin": "http://localhost:8000"}
        response = self.client.post("/api/session", json={}, headers=self.origin)
        self.assertEqual(response.status_code, 200)
        self.token = response.json()["token"]
        self.headers = dict(self.origin, Authorization="Bearer " + self.token)
        self.identity = self.store.owner(self.token)

    def test_api_requires_session_and_exact_origin(self):
        self.assertEqual(self.client.get("/api/status").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/session", json={}, headers={"Origin": "https://evil.example"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/session", content="x" * 2049, headers=self.origin).status_code,
            413,
        )

    def test_missing_worker_and_invalid_settings_fail(self):
        self.assertEqual(
            self.client.post("/api/run", json=OPTIONS, headers=self.headers).status_code, 503
        )
        for changed in (
            {"days": 30},
            {"days": True},
            {"training_days": 900},
            {"command": "anything"},
        ):
            response = self.client.post(
                "/api/run", json=dict(OPTIONS, **changed), headers=self.headers
            )
            self.assertEqual(response.status_code, 422)

    def test_cors_preflight_allows_only_configured_frontend(self):
        headers = {
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        }
        response = self.client.options("/api/run", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:8000")
        response = self.client.options(
            "/api/run", headers=dict(headers, Origin="https://evil.example")
        )
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_queue_persists_and_only_one_worker_can_claim(self):
        first = self.store.submit(self.identity, "first", OPTIONS)
        second_identity = self.store.owner(self.store.session("second"))
        self.store.submit(second_identity, "second", OPTIONS)
        restarted = JobStore(self.settings)
        self.assertEqual(restarted.claim()["id"], first)
        self.assertIsNone(self.store.claim())
        restarted.finish(first, "failed", error="test failure")
        self.assertIsNotNone(self.store.claim())

    def test_atomic_active_limit_and_client_quota(self):
        job_id = self.store.submit(self.identity, "same", OPTIONS)
        with self.assertRaises(QueueLimitError):
            self.store.submit(self.identity, "same", OPTIONS)
        self.store.claim()
        self.store.finish(job_id, "failed")
        for index in range(2):
            identity = self.store.owner(self.store.session(str(index)))
            job_id = self.store.submit(identity, "same", OPTIONS)
            self.store.claim()
            self.store.finish(job_id, "failed")
        identity = self.store.owner(self.store.session("third"))
        with self.assertRaises(QueueLimitError):
            self.store.submit(identity, "same", OPTIONS)

    def test_other_sessions_cannot_read_results_or_logs(self):
        job_id = self.store.submit(self.identity, "one", OPTIONS)
        self.store.claim()
        run_id = "private_result"
        folder = job_directory(self.settings, job_id) / "data/results" / run_id
        folder.mkdir(parents=True)
        (folder / "results.json").write_text(
            json.dumps({"source_file": "C:/private/name/hourly.csv"}), encoding="utf-8"
        )
        (folder / "metrics.csv").write_text("model,mae\nlear,1\n", encoding="utf-8")
        self.store.finish(job_id, "success", result_id=run_id)
        mine = self.client.get(
            "/api/download?run=private_result&file=results.json", headers=self.headers
        )
        self.assertEqual(mine.status_code, 200)
        self.assertNotIn("C:/private", mine.text)
        other = {"Authorization": "Bearer " + self.store.session("other")}
        self.assertEqual(
            self.client.get("/api/result/private_result", headers=other).status_code, 404
        )
        self.assertEqual(
            self.client.get(
                "/api/download?run=private_result&file=metrics.csv", headers=other
            ).status_code,
            404,
        )
        self.assertEqual(self.client.get("/api/status", headers=other).json()["runs"], [])
        self.assertEqual(self.client.get("/.env").status_code, 404)
        self.assertEqual(
            self.client.get(
                "/api/download?run=private_result&file=worker.log", headers=self.headers
            ).status_code,
            404,
        )

    def test_retention_and_expired_leases_are_explicit(self):
        job_id = self.store.submit(self.identity, "one", OPTIONS)
        self.store.claim()
        with self.store.connection() as connection:
            connection.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (job_id,))
        self.assertIsNone(self.store.claim())
        self.assertEqual(self.store.list_jobs(self.identity)[0]["status"], "interrupted")
        with self.store.connection() as connection:
            connection.execute("UPDATE jobs SET finished=0 WHERE id=?", (job_id,))
        self.assertEqual(self.store.expired(), [job_id])
        self.assertEqual(self.store.list_jobs(self.identity)[0]["status"], "expired")

    def test_subprocess_timeout_becomes_visible_job_failure(self):
        self.store.submit(self.identity, "one", OPTIONS)
        job = self.store.claim()
        with patch(
            "hosted_worker.subprocess.run", side_effect=subprocess.TimeoutExpired("model", 180)
        ):
            execute_job(self.store, job)
        self.assertEqual(self.store.list_jobs(self.identity)[0]["status"], "timed_out")

    def test_job_paths_and_pages_output_are_bounded(self):
        with self.assertRaises(ValueError):
            job_directory(self.settings, "../escape")
        for url in (
            "http://api.example.com",
            "https://user:password@api.example.com",
            "https://api.example.com/path",
        ):
            with self.assertRaises(ValueError):
                build_pages(url, Path(self.directory.name) / "pages")
        output = Path(self.directory.name) / "pages"
        build_pages("https://api.example.com", output)
        self.assertIn('"hosted": true', (output / "config.js").read_text())
        self.assertNotIn('src="/app.js"', (output / "index.html").read_text(encoding="utf-8"))

    def test_expired_session_is_not_reused(self):
        with self.store.connection() as connection:
            connection.execute("UPDATE sessions SET created=?", (time.time() - 8 * 86400,))
        self.assertIsNone(self.store.owner(self.token))


if __name__ == "__main__":
    unittest.main()
