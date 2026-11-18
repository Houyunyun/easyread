"""Opt-in preparation completion policy; no production data or model calls."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from easyread.app import config
from easyread.library.library import Library
from easyread.library.store import Workspace, write_json_atomic
from easyread.server.jobs import Jobs
from easyread.server import jobs_api, paper_api, settings_api


class AutoPrepareTranslationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lib = Library(Path(tmp.name))
        self.cfg = {"engine": "codex", "page_cap": 60, "auto_translate_after_prepare": True}
        cfg = patch("easyread.server.paper_scheduling.config.load", side_effect=lambda: dict(self.cfg))
        cfg.start()
        self.addCleanup(cfg.stop)
        with patch("easyread.server.jobs.threading.Thread.start"):
            self.jobs = Jobs(self.lib)

    def paper(self, pid="paper1", legacy=False, **kwargs):
        root = self.lib.root / pid
        root.mkdir()
        ws = Workspace(root)
        write_json_atomic(ws.paper_path, {"meta": {}, "translation": {}, "blocks": []})
        if legacy:
            ws.update("job", lambda j: j.update(type="prepare", phase="prepare", state="queued", translate=False))
            self.jobs.prepare.schedule(ws.id)
        else:
            self.jobs.enqueue(ws, translate_after=False, allow_auto_translate=True, **kwargs)
        return ws

    def prepared(self, ws, count=2):
        ws.update("paper", lambda p: p["meta"].update(pages=[{"n": n} for n in range(1, count + 1)], page_count=count))

    def run_prepare(self, ws, action=None):
        pid = self.jobs.prepare.get_nowait()
        self.assertEqual(pid, ws.id)
        with patch("easyread.server.jobs.translate.prepare", side_effect=action or self.prepared):
            self.jobs._process_bulk(pid, "prepare")

    def test_auto_handoff_preserves_parameters_and_appends_once(self):
        ws = self.paper(scope="first:1", model="chosen", target="ja", translation_extra="Keep acronyms")
        self.jobs.bulk.schedule("existing")
        self.run_prepare(ws)
        job = ws.load("job")
        self.assertEqual((job["type"], job["phase"], job["state"], job["translate"]),
                         ("translate", "model", "queued", True))
        self.assertEqual([job[k] for k in ("scope", "model", "target", "translation_extra")],
                         ["first:1", "chosen", "ja", "Keep acronyms"])
        self.jobs._process_bulk(ws.id, "prepare")
        self.assertEqual([self.jobs.bulk.get_nowait(), self.jobs.bulk.get_nowait()], ["existing", ws.id])
        self.assertTrue(self.jobs.bulk.empty())

    def test_legacy_pending_jobs_follow_opt_in_but_done_jobs_are_not_backfilled(self):
        pending = self.paper(legacy=True)
        done = self.paper("done1", legacy=True)
        self.prepared(done)
        done.update("job", lambda j: j.update(state="done"))
        with patch("easyread.server.jobs.threading.Thread.start"):
            self.jobs = Jobs(self.lib)
        self.assertEqual(self.jobs.prepare.qsize(), 1)
        self.run_prepare(pending)
        self.assertEqual(self.jobs.bulk.get_nowait(), pending.id)
        self.assertEqual(done.load("job")["state"], "done")

    def test_explicit_prepare_only_and_public_import_do_not_translate(self):
        for i, fields in enumerate(({"allow_auto_translate": False}, {"public_import": True}, {"read": True})):
            ws = self.paper(f"only{i}")
            ws.update("job", lambda j: j.update(fields))
            self.run_prepare(ws)
            self.assertEqual(ws.load("job")["state"], "done")
        self.assertTrue(self.jobs.bulk.empty())

    def test_default_enqueue_is_explicit_prepare_only(self):
        ws = self.paper()
        self.jobs.cancel(ws.id)
        self.jobs.enqueue(ws, translate_after=False)
        self.run_prepare(ws)
        self.assertFalse(ws.load("job")["allow_auto_translate"])
        self.assertTrue(self.jobs.bulk.empty())

    def test_disabled_setting_or_engine_never_auto_starts_model(self):
        for i, cfg in enumerate(({"auto_translate_after_prepare": False}, {"engine": "none"})):
            self.cfg.update(engine="codex", auto_translate_after_prepare=True)
            self.cfg.update(cfg)
            ws = self.paper(f"off{i}")
            self.run_prepare(ws)
            self.assertEqual(ws.load("job")["state"], "done")
        self.assertTrue(self.jobs.bulk.empty())

    def test_setting_is_checked_at_completion(self):
        ws = self.paper()
        def prepare(paper):
            self.prepared(paper)
            self.cfg["auto_translate_after_prepare"] = False
        self.run_prepare(ws, prepare)
        self.assertTrue(self.jobs.bulk.empty())

    def test_explicit_translation_reservation_is_not_disabled_by_policy(self):
        ws = self.paper()
        self.jobs.enqueue(ws)
        self.cfg["auto_translate_after_prepare"] = False
        self.run_prepare(ws)
        self.assertEqual(self.jobs.bulk.get_nowait(), ws.id)

    def test_stop_during_prepare_persists_opt_out_across_restart(self):
        ws = self.paper()
        def prepare(paper):
            self.assertEqual(self.jobs.stop_model_work(), 1)
            self.prepared(paper)
        self.run_prepare(ws, prepare)
        self.assertFalse(ws.load("job")["allow_auto_translate"])
        self.assertEqual(ws.load("job")["state"], "done")
        with patch("easyread.server.jobs.threading.Thread.start"):
            resumed = Jobs(self.lib)
        self.assertTrue(resumed.bulk.empty())

    def test_stop_queued_automatic_job_keeps_preparation_only(self):
        ws = self.paper()
        self.assertEqual(self.jobs.stop_model_work([ws.id]), 1)
        self.run_prepare(ws)
        self.assertEqual(ws.load("job")["state"], "done")
        self.assertTrue(self.jobs.bulk.empty())

    def test_cancel_during_prepare_does_not_start_translation(self):
        ws = self.paper()
        def prepare(paper):
            self.jobs.cancel(paper.id)
            self.prepared(paper)
        self.run_prepare(ws, prepare)
        self.assertEqual(ws.load("job")["state"], "cancelled")
        self.assertTrue(self.jobs.bulk.empty())

    def test_failed_preparation_only_translates_after_successful_retry(self):
        ws = self.paper()
        def fail(_):
            raise ValueError("controlled preparation failure")
        self.run_prepare(ws, fail)
        self.assertEqual(ws.load("job")["state"], "error")
        self.assertTrue(self.jobs.bulk.empty())
        paper_api.post(SimpleNamespace(jobs=self.jobs), ws, ["", "api", "p", ws.id, "prepare"], {})
        self.run_prepare(ws)
        self.assertEqual(self.jobs.bulk.get_nowait(), ws.id)

    def test_automatic_handoff_keeps_page_cap_confirmation(self):
        ws = self.paper()
        self.run_prepare(ws, lambda p: self.prepared(p, 80))
        with patch("easyread.server.jobs.translate.translate_pages") as model:
            self.jobs._process_bulk(self.jobs.bulk.get_nowait())
        model.assert_not_called()
        self.assertEqual(ws.load("job")["state"], "confirm")

    def test_live_library_policy_does_not_mutate_cached_summaries(self):
        ws = self.paper()
        items = self.lib.list()
        app = SimpleNamespace(lib=self.lib, jobs=self.jobs, token="test",
                              location=SimpleNamespace(status="idle", marker=SimpleNamespace(other_device=lambda: False)))
        with patch.object(self.lib, "list", return_value=items), \
                patch("easyread.app.cli_models.engine_label", return_value="Codex"), \
                patch("easyread.server.research_api.statuses", return_value=[]), \
                patch("easyread.server.research_api.trash_count", return_value=0):
            self.assertTrue(jobs_api.library_state(app)["items"][0]["job"]["auto_translate_pending"])
            self.cfg["auto_translate_after_prepare"] = False
            self.assertFalse(jobs_api.library_state(app)["items"][0]["job"]["auto_translate_pending"])
        self.assertNotIn("auto_translate_pending", items[0]["job"])

    def test_config_requires_boolean_and_defaults_off(self):
        self.assertFalse(config.DEFAULTS["auto_translate_after_prepare"])
        for value in (1, "true", None, []):
            with self.assertRaises(ValueError):
                settings_api.save_config({"auto_translate_after_prepare": value})
        with patch("easyread.server.settings_api.config.save", return_value=config.DEFAULTS) as save:
            settings_api.save_config({"auto_translate_after_prepare": True})
        save.assert_called_once_with({"auto_translate_after_prepare": True})


if __name__ == "__main__":
    unittest.main()
