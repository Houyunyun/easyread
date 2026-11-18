"""Two-stage scheduling with isolated libraries and no real inference."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from easyread.library.library import Library
from easyread.library.store import Workspace, write_json_atomic
from easyread.server.jobs import Jobs
from easyread.translate import translate_api


class DualQueuesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lib = Library(Path(tmp.name))
        with patch("easyread.server.jobs.threading.Thread.start"):
            self.jobs = Jobs(self.lib)
        cfg = patch("easyread.server.jobs.config.load", return_value={"engine": "codex", "page_cap": 60})
        cfg.start()
        self.addCleanup(cfg.stop)

    def paper(self, name, prepared=False):
        root = self.lib.root / name.ljust(4, "0")
        root.mkdir()
        ws = Workspace(root)
        write_json_atomic(ws.paper_path, {"meta": {}, "translation": {}, "blocks": []})
        if prepared:
            self.prepared(ws)
        return ws

    def prepared(self, ws, count=2):
        ws.update("paper", lambda p: p["meta"].update(pages=[{"n": n} for n in range(1, count + 1)], page_count=count))

    def prepare_one(self):
        self.jobs._process_bulk(self.jobs.prepare.get_nowait(), "prepare")

    def model_one(self):
        self.jobs._process_bulk(self.jobs.bulk.get_nowait())

    def test_bulk_preparation_does_not_fill_model_queue(self):
        for n in range(120):
            self.jobs.enqueue(self.paper(f"queued{n:03}"), translate_after=False)
        ready = self.paper("ready", prepared=True)
        self.jobs.enqueue(ready)
        self.assertEqual(self.jobs.prepare.qsize(), 120)
        self.assertEqual(self.jobs.bulk.qsize(), 1)
        with patch("easyread.server.jobs.translate.translate_pages", return_value={}) as model:
            self.model_one()
        self.assertEqual(model.call_args.args[0].id, ready.id)
        self.assertEqual(ready.load("job")["state"], "done")

    def test_priority_reservations_are_fifo_and_deduplicated(self):
        a, b, c = [self.paper(n) for n in ("a", "b", "c")]
        for ws in (a, b, c):
            self.jobs.enqueue(ws, translate_after=False)
        translate_api.enqueue(self.jobs, c, {"scope": "first:1", "translation_extra": "Keep acronyms"})
        translate_api.enqueue(self.jobs, b, {})
        with self.assertRaises(ValueError):
            translate_api.enqueue(self.jobs, c, {})
        self.assertEqual(self.jobs.prepare.qsize(), 3)
        self.assertEqual([self.jobs.prepare.get_nowait() for _ in range(3)], [c.id, b.id, a.id])
        self.assertTrue(self.jobs.bulk.empty())
        self.assertEqual(c.load("job")["translation_extra"], "Keep acronyms")

    def test_prepared_translation_and_preprocessing_overlap_without_same_paper_overlap(self):
        preparing, ready = self.paper("preparing"), self.paper("ready", prepared=True)
        self.jobs.enqueue(preparing, translate_after=False, public_import=True)
        self.jobs.enqueue(ready)
        started, release = threading.Event(), threading.Event()
        observed = []

        def prepare(ws):
            # Page metadata alone does not release the running preparation stage.
            self.prepared(ws)
            started.set()
            if not release.wait(3):
                raise RuntimeError("test timed out")

        def model(ws, *args):
            observed.append(ws.id)
            self.assertFalse(release.is_set())
            return {}

        with patch("easyread.server.jobs.translate.prepare", side_effect=prepare), \
                patch("easyread.server.jobs.translate.translate_pages", side_effect=model):
            worker = threading.Thread(target=self.prepare_one)
            worker.start()
            try:
                self.assertTrue(started.wait(2))
                translate_api.enqueue(self.jobs, preparing, {"scope": "first:1", "model": "chosen", "read": True})
                job = preparing.load("job")
                self.assertEqual((job["phase"], job["state"], job["type"]), ("prepare", "running", "read"))
                self.assertTrue(job["public_import"])
                self.assertEqual(self.jobs.bulk.qsize(), 1)
                self.jobs._process_bulk(preparing.id)  # Wrong worker must not claim it.
                self.model_one()
                self.assertEqual(observed, [ready.id])
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(preparing.load("job")["phase"], "model")
        self.assertEqual(preparing.load("job")["state"], "queued")
        self.assertNotIn(preparing.id, self.jobs.cancels)
        with patch("easyread.server.jobs.translate.translate_pages", return_value={}) as model:
            self.model_one()
        self.assertEqual(model.call_args.args[2], [1])
        self.assertTrue(model.call_args.args[-1])
        self.assertEqual(preparing.load("job")["model"], "chosen")

    def test_cancel_reservation_while_queued_removes_both_stages(self):
        ws = self.paper("a")
        self.jobs.enqueue(ws)
        self.jobs.cancel(ws.id)
        self.assertFalse(self.jobs.busy())
        self.assertEqual(ws.load("job")["state"], "cancelled")
        self.jobs.enqueue(ws)
        self.assertEqual(self.jobs.prepare.qsize(), 1)

    def test_cancel_running_prepare_prevents_handoff(self):
        ws = self.paper("a")
        self.jobs.enqueue(ws)

        def prepare(ws):
            self.jobs.cancel(ws.id)
            self.prepared(ws)
        with patch("easyread.server.jobs.translate.prepare", side_effect=prepare):
            self.prepare_one()
        self.assertEqual(ws.load("job")["state"], "cancelled")
        self.assertFalse(self.jobs.busy())

    def test_stop_models_keeps_running_preparation_and_removes_reservation(self):
        ws = self.paper("a")
        self.jobs.enqueue(ws)

        def prepare(ws):
            self.prepared(ws)
            self.assertEqual(self.jobs.stop_model_work(), 1)
            self.assertFalse(self.jobs.cancels[ws.id].is_set())
            self.assertEqual(ws.load("job")["state"], "running")
        with patch("easyread.server.jobs.translate.prepare", side_effect=prepare):
            self.prepare_one()
        self.assertEqual(ws.load("job")["state"], "done")
        self.assertFalse(ws.load("job")["translate"])
        self.assertFalse(self.jobs.busy())

    def test_stop_queued_reservation_demotes_priority_without_duplicate(self):
        a, b = self.paper("a"), self.paper("b")
        self.jobs.enqueue(a, translate_after=False)
        self.jobs.enqueue(b)
        self.assertEqual(self.jobs.stop_model_work(), 1)
        self.assertEqual(self.jobs.prepare.qsize(), 2)
        self.assertEqual(self.jobs.prepare.get_nowait(), a.id)
        self.assertEqual(self.jobs.prepare.get_nowait(), b.id)
        self.assertTrue(self.jobs.bulk.empty())

    def test_prepare_failure_never_calls_model_and_retry_routes_correctly(self):
        ws = self.paper("a")
        self.jobs.enqueue(ws)
        with patch("easyread.server.jobs.translate.prepare", side_effect=ValueError("broken PDF")), \
                patch("easyread.server.jobs.translate.translate_pages") as model, \
                patch("easyread.server.jobs.log.exception"):
            self.prepare_one()
        self.assertEqual(ws.load("job")["state"], "error")
        model.assert_not_called()
        self.assertFalse(self.jobs.busy())
        self.prepared(ws)
        self.jobs.enqueue(ws)
        self.assertEqual(ws.load("job")["phase"], "model")
        self.assertEqual(self.jobs.bulk.qsize(), 1)

    def test_resume_legacy_and_reserved_jobs_without_enabling_auto_translation(self):
        fixtures = [
            ("plain", False, {"state": "queued", "type": "prepare", "translate": False}),
            ("reserved", False, {"state": "running", "phase": "prepare", "translate": True, "type": "translate"}),
            ("ready", True, {"state": "running", "translate": True, "pages": [1, 2]}),
            ("prepared", True, {"state": "running", "phase": "prepare", "translate": True}),
            ("images", True, {"state": "running", "type": "figure-images", "translate": True}),
        ]
        for name, prepared, job in fixtures:
            ws = self.paper(name, prepared)
            ws.update("job", lambda j, job=job: j.update(job))
        with patch("easyread.server.jobs.threading.Thread.start"):
            resumed = Jobs(self.lib)
        self.assertEqual(resumed.prepare.qsize(), 2)
        self.assertEqual(resumed.bulk.qsize(), 2)
        self.assertEqual(resumed.prepare.get_nowait(), "reserved")
        self.assertFalse(self.lib.ws("plain").load("job")["translate"])
        self.assertEqual(self.lib.ws("images").load("job")["state"], "cancelled")
        self.assertEqual(self.lib.ws("ready").load("job")["retranslate_revisions"], {})

    def test_confirm_after_handoff_without_inference(self):
        ws = self.paper("a")
        self.jobs.enqueue(ws)
        with patch("easyread.server.jobs.translate.prepare", side_effect=lambda ws: self.prepared(ws, 80)), \
                patch("easyread.server.jobs.translate.translate_pages") as model:
            self.prepare_one()
            self.model_one()
        self.assertEqual(ws.load("job")["state"], "confirm")
        self.assertFalse(self.jobs.busy())
        model.assert_not_called()

    def test_web_original_remains_model_free(self):
        ws = self.paper("web", True)
        ws.update("paper", lambda p: p["meta"].update(source_type="web"))
        self.jobs.enqueue(ws, read=True)
        with patch("easyread.server.jobs.translate.translate_pages") as model:
            self.model_one()
        model.assert_not_called()
        self.assertEqual(ws.load("job")["state"], "done")

    def test_summary_exposes_stage_and_reservation(self):
        ws = self.paper("a")
        self.jobs.enqueue(ws)
        job = self.lib.summary(ws)["job"]
        self.assertEqual(job["phase"], "prepare")
        self.assertTrue(job["translate"])


if __name__ == "__main__":
    unittest.main()
