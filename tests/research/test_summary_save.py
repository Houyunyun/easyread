"""Manual saved-summary editing and atomic model/manual stale-write protection."""
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from easyread.library import planning_store
from easyread.research import store, workspace


@patch.dict(os.environ, {"EASYREAD_LANG": "zh"})
class SummarySaveTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = SimpleNamespace(lib=SimpleNamespace(root=self.root))
        self.key = "doi:10.1234/manual-summary"
        self.paper = {"title": "Original paper", "doi": "10.1234/manual-summary", "abstract": "Original source", "year": 2024}
        planning_store.candidate_add(self.root, self.key, self.paper)
        self.original = planning_store.candidate_save_summary(self.root, self.key, "Original summary\n", "AI model", target="zh-Hant")
        patcher = patch.object(store, "settings", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def save(self, markdown, **options):
        return workspace.post(self.app, "/summary/save", {"paper_key": self.key, "summary_markdown": markdown, **options})["summary"]

    def test_no_vault_manual_edit_survives_candidate_removal_and_reload_preserving_metadata(self):
        # The source metadata may have changed in the candidate list; manual edits
        # must preserve the saved summary's original paper metadata, not re-import it.
        planning_store.candidate_add(self.root, self.key, {**self.paper, "title": "Changed candidate"})
        planning_store.candidate_remove(self.root, self.key)
        edited = "  ## My Markdown\n\nOriginal evidence.\n"
        saved = self.save(edited, expected_updated=self.original["updated"], expected_markdown=self.original["summary_markdown"],
                          paper={"title": "Client override"}, model="False model", target="en")
        self.assertEqual(saved["summary_markdown"], edited)
        self.assertEqual(saved["paper"], self.original["paper"])
        self.assertEqual(saved["created"], self.original["created"])
        self.assertEqual(saved["summary_target"], "")
        self.assertEqual(saved["summary_model"], "")
        self.assertEqual(planning_store.summary(Path(str(self.root)), self.key), saved)
        self.assertEqual(planning_store.candidates(self.root), [])
        self.assertFalse((self.root / "Research").exists())
        self.assertNotEqual(saved["updated"], self.original["updated"])

    def test_same_timestamp_stale_text_and_timestamp_only_edits_are_rejected(self):
        planning_store.candidate_save_summary(self.root, self.key, "New generated text", "AI model", target="en")
        # Generation timestamps historically have second precision; force that
        # collision to prove expected_markdown is compared atomically as well.
        with planning_store._db(self.root) as db:
            db.execute("UPDATE paper_summaries SET updated=? WHERE paper_key=?", (self.original["updated"], self.key))
            db.commit()
        with self.assertRaisesRegex(ValueError, "摘要已变更"):
            self.save("Stale edit", expected_updated=self.original["updated"], expected_markdown=self.original["summary_markdown"])
        with self.assertRaisesRegex(ValueError, "摘要已变更"):
            self.save("Stale edit", expected_updated="old timestamp")
        self.assertEqual(planning_store.summary(self.root, self.key)["summary_markdown"], "New generated text")

    def test_concurrent_edits_compare_and_write_in_one_transaction(self):
        ready = threading.Barrier(2)
        def edit(markdown):
            ready.wait(timeout=3)
            try:
                return self.save(markdown, expected_markdown=self.original["summary_markdown"])
            except ValueError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(edit, ["Edit A", "Edit B"]))
        self.assertEqual(sum(isinstance(value, dict) for value in results), 1)
        self.assertEqual(sum(isinstance(value, str) and "摘要已变更" in value for value in results), 1)

    def test_manual_edit_invalidates_inflight_worker_claim(self):
        planning_store.candidate_summary_status(self.root, self.key, "queued")
        model_started, release_model = threading.Event(), threading.Event()
        def model(*args):
            model_started.set()
            if not release_model.wait(3):
                raise TimeoutError("test did not release model")
            return json.dumps([{"paper_key": self.key, "summary_markdown": "Late model result"}])
        # An explicit retry may already have claimed a job over an existing summary.
        claimed = planning_store.candidate_summary_claim(self.root, [self.key])[0]
        def finish_generation():
            answer = json.loads(model())[0]
            return planning_store.candidate_save_summary(self.root, self.key, answer["summary_markdown"], "Model",
                                                        expected_claim=claimed["summary_claim"], target="en")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(finish_generation)
            self.assertTrue(model_started.wait(1))
            try:
                edited = self.save("Manual wins", expected_markdown=self.original["summary_markdown"])
            finally:
                release_model.set()
            self.assertIsNone(future.result(timeout=3))
        self.assertEqual(planning_store.summary(self.root, self.key), edited)
        self.assertFalse(planning_store.candidate_summary_status(self.root, self.key, "failed", "late failure", expected_claim=claimed["summary_claim"]))
        candidate = planning_store.candidates(self.root)[0]
        self.assertEqual(candidate["summary_status"], "ready")
        self.assertEqual(candidate["summary_claim"], "")
        self.assertEqual(candidate["summary_model"], "")
        self.assertEqual(candidate["summary_updated"], edited["updated"])

    def test_generation_finishing_first_rejects_stale_manual_edit_without_clearing_attribution(self):
        planning_store.candidate_summary_status(self.root, self.key, "queued")
        claim = planning_store.candidate_summary_claim(self.root, [self.key])[0]["summary_claim"]
        generated = planning_store.candidate_save_summary(self.root, self.key, "Model wins", "Model", expected_claim=claim, target="en")
        with self.assertRaisesRegex(ValueError, "摘要已变更"):
            self.save("Stale manual", expected_markdown=self.original["summary_markdown"])
        self.assertEqual(planning_store.summary(self.root, self.key), generated)

    def test_manual_edit_never_recreates_trashed_deleted_missing_or_other_library_summary(self):
        moved = planning_store.summary_move_to_trash(self.root, self.key)
        with self.assertRaisesRegex(ValueError, "找不到"):
            self.save("Resurrection", expected_markdown=self.original["summary_markdown"])
        planning_store.summary_trash_purge(self.root, moved["trash_id"])
        with self.assertRaisesRegex(ValueError, "找不到"):
            self.save("Resurrection")
        self.assertIsNone(planning_store.summary(self.root, self.key))
        self.assertEqual(planning_store.candidates(self.root)[0]["summary_status"], "")
        planning_store.candidate_save_summary(self.root, self.key, "Explicit new summary")
        other = self.root / "other-library"
        with self.assertRaisesRegex(ValueError, "找不到"):
            workspace.post(SimpleNamespace(lib=SimpleNamespace(root=other)), "/summary/save", {"paper_key": self.key, "summary_markdown": "Wrong scope"})
        self.assertEqual(planning_store.summary(self.root, self.key)["summary_markdown"], "Explicit new summary")

    def test_invalid_payloads_do_not_mutate_saved_summary(self):
        for body in ({"summary_markdown": " "}, {"summary_markdown": "x" * 100001}, {"summary_markdown": []},
                     {"paper_key": ""}, {"paper_key": {}}, {"expected_updated": None}, {"expected_markdown": 1}):
            with self.subTest(body=str(body)[:100]), self.assertRaises(ValueError):
                workspace.post(self.app, "/summary/save", {"paper_key": self.key, "summary_markdown": "Edit", **body})
        self.assertEqual(planning_store.summary(self.root, self.key), self.original)
