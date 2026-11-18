"""HTTP integration: live queue policy must preserve PWA and cached summaries."""
import json
import unittest
from unittest.mock import patch

from easyread.app import config
from easyread.library.store import Workspace, write_json_atomic
from tests.server import test_access


class QueuePolicyHTTPTest(unittest.TestCase):
    request = test_access.AccessHTTPTest.request
    login = test_access.AccessHTTPTest.login

    def setUp(self):
        test_access.AccessHTTPTest.setUp(self)
        self.cfg = {**config.load(), "engine": "codex", "auto_translate_after_prepare": True}
        self.policy = patch.object(config, "load", side_effect=lambda: dict(self.cfg))
        self.policy.start()
        root = self.app.lib.root / "policy-paper"
        root.mkdir()
        self.ws = Workspace(root)
        write_json_atomic(self.ws.paper_path, {"schema": 2, "meta": {"title_en": "Queue policy", "pages": [{"n": 1}], "page_count": 1},
                                              "translation": {"done_pages": [], "gaps_checked": True}, "blocks": []})
        # Persisted state only: do not enqueue it or invoke an actual model.
        self.ws.update("job", lambda job: job.update(type="prepare", phase="prepare", state="queued", translate=False, allow_auto_translate=True))
        self.cookie = self.login()

    def tearDown(self):
        self.policy.stop()
        test_access.AccessHTTPTest.tearDown(self)

    def get(self, path):
        status, _, body = self.request("GET", path, cookie=self.cookie)
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_policy_updates_without_file_changes_and_keeps_library_identity(self):
        library = self.get("/api/library")
        state = self.get("/api/p/policy-paper/state")
        versions = self.get("/api/p/policy-paper/versions")
        self.assertEqual(library["library_id"], state["library_id"])
        self.assertEqual(library["library_id"], versions["library_id"])
        self.assertTrue(library["items"][0]["job"]["auto_translate_pending"])
        self.assertTrue(state["job"]["auto_translate_pending"])
        self.assertTrue(versions["auto_translate_pending"])
        self.cfg["auto_translate_after_prepare"] = False
        changed = self.get("/api/p/policy-paper/versions")
        self.assertEqual(changed["job"], versions["job"])
        self.assertFalse(changed["auto_translate_pending"])
        self.assertFalse(self.get("/api/p/policy-paper/part/job")["data"]["auto_translate_pending"])
        self.assertFalse(self.get("/api/library")["items"][0]["job"]["auto_translate_pending"])
        self.assertNotIn("auto_translate_pending", self.ws.load("job"))


if __name__ == "__main__":
    unittest.main()
