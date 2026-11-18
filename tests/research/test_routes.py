"""HTTP and existing Jobs integration for the PaperRead backend port."""
from __future__ import annotations

import http.client
import json
import queue
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from easyread.chat import smart_annotations
from easyread.research import tasks
from easyread.server import server, small_jobs
from easyread.server.jobs import Jobs
from tests.research.test_port_safety import PortFixture


class ResearchRoutesTest(PortFixture):
    def test_original_http_routes_keep_auth_and_json_contracts(self):
        class Handler(server.Handler):
            app = self.app

            def log_message(self, *args):
                pass

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)

        def request(method, path, body=None, token="token"):
            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
            try:
                connection.request(method, path, body=json.dumps(body) if body is not None else None,
                                   headers={"X-Token": token, "Content-Type": "application/json"})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        status, response = request("GET", "/api/research/v1/monitor")
        self.assertEqual(status, 200)
        self.assertEqual(response["scope_id"], tasks.scope_id(self.lib.root))
        status, response = request("GET", "/api/research/v2/init")
        self.assertEqual(status, 200)
        self.assertEqual(response["items"][0]["id"], self.ws.id)
        self.assertIn("statuses", response)
        status, _ = request("POST", "/api/research/v2/milestones", {"title": "Blocked"}, token="wrong")
        self.assertEqual(status, 403)
        status, response = request("POST", "/api/research/v2/milestones", {"title": "Goal", "start_date": "2026-02-01"})
        self.assertEqual(status, 200)
        self.assertEqual(response["milestone"]["title"], "Goal")
        status, _ = request("POST", f"/api/p/{self.ws.id}/item", {"reading_plan": {"start_date": "2026-02-01"}, "paper_ref": "source", "manual_order": 2})
        self.assertEqual(status, 200)
        self.assertEqual(self.ws.load("item")["manual_order"], 2)
        status, response = request("GET", f"/api/p/{self.ws.id}/part/item")
        self.assertEqual(status, 200)
        self.assertEqual(response["data"]["manual_order"], 2)
        self.assertEqual(response["version"], self.ws.versions()["item"])
        status, identity = request("GET", f"/api/research/v2/paper/{self.ws.id}/mindmap")
        self.assertEqual(status, 200)
        status, response = request("POST", f"/api/research/v2/paper/{self.ws.id}/mindmap/save", {"target": identity["target"], "source_sha256": identity["source_sha256"], "mermaid": "mindmap\n  root((Saved over HTTP))", "revision": 0})
        self.assertEqual(status, 200)
        self.assertEqual(response["revision"], 1)
        status, response = request("GET", f"/api/research/v2/paper/{self.ws.id}/mindmap")
        self.assertEqual(status, 200)
        self.assertIn("Saved over HTTP", response["mermaid"])
        self.app.location.status = "restart_required"
        status, _ = request("GET", "/api/research/v2/init")
        self.assertEqual(status, 409)

    def test_smart_annotation_small_jobs_report_progress_and_cancel(self):
        jobs = object.__new__(Jobs)
        jobs.lib, jobs.small = self.lib, queue.Queue()
        jobs.lock, jobs.recent, jobs.small_cancels = threading.Lock(), [], {}
        tasks.recover(self.lib.root)
        job = jobs.submit_small("smart-annotate", self.ws.id, title="Paper")

        def generate(ws, **kwargs):
            kwargs["on_progress"](1, 1, 2)
            return {"count": 2}

        with patch.object(jobs.small, "get", side_effect=[job, StopIteration]), patch.object(smart_annotations, "generate", side_effect=generate):
            with self.assertRaises(StopIteration):
                small_jobs.run(jobs)
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["saved"], 2)
        self.assertEqual(tasks.get(job["id"])["state"], "completed")
        self.assertEqual(jobs.small_cancels, {})
        cancelled = jobs.submit_small("smart-annotate", self.ws.id)
        self.assertTrue(jobs.cancel_small(cancelled["id"]))
        with patch.object(jobs.small, "get", side_effect=[cancelled, StopIteration]), patch.object(smart_annotations, "generate") as model:
            with self.assertRaises(StopIteration):
                small_jobs.run(jobs)
            model.assert_not_called()
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(tasks.get(cancelled["id"])["state"], "cancelled")
        self.assertEqual(jobs.small_cancels, {})
