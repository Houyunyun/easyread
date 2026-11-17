"""Regressions for review findings on delayed writes and stale reading-path edges."""
from __future__ import annotations

import json
from unittest.mock import patch

from easyread.chat import chat_models, smart_annotations
from easyread.engines import engines
from easyread.library import paperdata, planning_store
from easyread.library.store import Workspace, now_iso
from easyread.research import deep_analysis, workspace
from tests.research.test_port_safety import PortFixture


class ReviewDataPreservationTest(PortFixture):
    def seed_annotation(self):
        self.ws.update("paper", lambda p: p.update(blocks=[{
            "id": "p1", "type": "para", "page": 1, "en": "A durable finding about spectrometry."
        }]))
        raw = {"anchor": "p1", "quote": "durable finding", "side": "en", "type": "highlight", "color": "yellow", "note": "AI explanation"}
        candidate = smart_annotations._candidate(self.ws.id, raw, smart_annotations._sources(self.ws.load("paper")), "test", "", "2020-01-01")
        self.assertTrue(candidate["locatable"])
        self.ws.apply_reader_ops([{"op": "ai_annotation", "annotation": candidate}])
        return raw, candidate["annotation_id"]

    def test_translation_writes_survive_annotation_repair_errors(self):
        with patch.object(smart_annotations, "refresh_after_translation", side_effect=RuntimeError("repair failed")), patch.object(paperdata.log, "exception") as logged:
            result = paperdata.merge_blocks(self.ws, {"blocks": [{"id": "p1", "type": "para", "page": 1, "en": "Original", "zh": "Merged"}]}, done=[1])
            self.assertIn(1, result["done_pages"])
            self.assertEqual(self.ws.load("paper")["blocks"][0]["zh"], "Merged")
            self.assertEqual(paperdata.fill_zh(self.ws, {"zh": {"p1": "Filled"}}, [1], {"p1"}), [])
            self.assertEqual(self.ws.load("paper")["blocks"][0]["zh"], "Filled")
            paperdata.set_block_text(self.ws, "p1", "Edited")
            self.assertEqual(self.ws.load("paper")["blocks"][0]["zh"], "Edited")
            self.assertEqual(logged.call_count, 3)

    def test_generation_cas_preserves_accept_reject_and_edit_during_model_call(self):
        for action in ("accept", "reject", "edit"):
            with self.subTest(action=action):
                self.ws.update("reader", lambda r: r.update(ai_annotations={}, notes={}))
                raw, aid = self.seed_annotation()
                committed = {}

                def model(*args, **kwargs):
                    smart_annotations.apply_action(self.ws, {"action": action, "id": aid, "patch": {"note": "User explanation"}})
                    committed.update(self.ws.load("reader")["ai_annotations"][aid])
                    return json.dumps({"annotations": [raw]})

                with patch.object(chat_models, "engine_cfg", return_value=({"engine": "test"}, {"id": "test"})), patch.object(engines, "run", side_effect=model):
                    result = smart_annotations.generate(self.ws)
                self.assertEqual(result["count"], 0)
                self.assertEqual(self.ws.load("reader")["ai_annotations"][aid], committed)
                if action == "accept":
                    self.assertEqual(len(self.ws.load("reader")["notes"]), 1)

    def test_source_refresh_uses_locked_current_note_body_and_deletion_state(self):
        _, aid = self.seed_annotation()
        smart_annotations.apply_action(self.ws, {"action": "accept", "id": aid})
        note = next(iter(self.ws.load("reader")["notes"].values()))
        # Force a source relocation independently of text similarity heuristics.
        original_refresh = smart_annotations._refresh_annotation
        def relocate(annotation, sources):
            return {**original_refresh(annotation, sources), "anchor": "p2", "page": 2}
        original_update = self.ws.update_reader_ops
        for deleted in (False, True):
            with self.subTest(deleted=deleted):
                user_note = {**note, "body": "Newest manual body", "deleted": deleted, "updated": now_iso()}
                injected = False
                def before_lock(make_ops, client=""):
                    nonlocal injected
                    if not injected:
                        injected = True
                        original_update(lambda reader: [{"op": "note", "note": user_note}], "manual")
                    return original_update(make_ops, client)
                with patch.object(self.ws, "update_reader_ops", side_effect=before_lock), patch.object(smart_annotations, "_refresh_annotation", side_effect=relocate):
                    smart_annotations.refresh_after_translation(self.ws)
                stored = self.ws.load("reader")["notes"][note["id"]]
                self.assertEqual(stored["body"], user_note["body"])
                self.assertEqual(stored.get("deleted"), deleted)
                self.assertEqual(stored["updated"], user_note["updated"])
                if not deleted:
                    self.assertEqual(stored["anchor"], "p2")

    def test_source_refresh_does_not_supersede_an_already_queued_user_edit(self):
        _, aid = self.seed_annotation()
        smart_annotations.apply_action(self.ws, {"action": "accept", "id": aid})
        note = next(iter(self.ws.load("reader")["notes"].values()))
        queued_edit = {**note, "body": "Queued manual body", "updated": now_iso()}
        old = smart_annotations._refresh_annotation
        with patch.object(smart_annotations, "_refresh_annotation", side_effect=lambda a, s: {**old(a, s), "page": 10}), patch.object(smart_annotations, "now_iso", return_value="2099-01-01T00:00:00Z"):
            smart_annotations.refresh_after_translation(self.ws)
        self.ws.apply_reader_ops([{"op": "note", "note": queued_edit}])
        self.assertEqual(self.ws.load("reader")["notes"][note["id"]]["body"], "Queued manual body")

    def test_deep_analysis_append_reads_current_note_under_journal_lock(self):
        self.ws.apply_reader_ops([{"op": "paper_note", "body": "Old note"}])
        original_update = self.ws.update_reader_ops
        def before_lock(make_ops, client=""):
            original_update(lambda r: [{"op": "paper_note", "body": "Concurrent editor save"}], "editor")
            return original_update(make_ops, client)
        with patch.object(self.ws, "update_reader_ops", side_effect=before_lock):
            result = deep_analysis.apply_to_paper_note(self.ws, "Deep report")
        reader = Workspace(self.ws.root).load("reader")
        self.assertIn("Concurrent editor save", reader["paper_note"]["body"])
        self.assertIn("Deep report", reader["paper_note"]["body"])
        self.assertEqual(result["rev"], reader["rev"])
        journal = [json.loads(line) for line in self.ws.journal_path.read_text().splitlines()]
        self.assertEqual(journal[-1]["client"], "deep-analysis")
        self.assertEqual(journal[-1]["body"], reader["paper_note"]["body"])

    def test_summary_worker_cas_preserves_manual_save_and_ready_state(self):
        for model_fails in (False, True):
            with self.subTest(model_fails=model_fails):
                paper = {"title": "Candidate", "abstract": "Original abstract", "doi": "10.1000/" + str(model_fails)}
                key = workspace._key(paper)
                planning_store.candidate_add(self.lib.root, key, paper)
                def model(*args, **kwargs):
                    workspace.post(self.app, "/candidate", {"paper": paper, "action": "save-summary", "summary_markdown": "Manually edited summary"})
                    if model_fails:
                        raise RuntimeError("late model failure")
                    return json.dumps([{"paper_key": key, "summary_markdown": "Delayed model result"}])
                with patch.object(workspace._time, "sleep"), patch.object(chat_models, "engine_cfg", return_value=({"engine": "test"}, {"id": "test"})), patch.object(engines, "run", side_effect=model):
                    workspace._summary_worker(self.app)
                record = planning_store.summary(self.lib.root, key)
                self.assertEqual(record["summary_markdown"], "Manually edited summary")
                candidate = next(row for row in planning_store.candidates(self.lib.root) if row["paper_key"] == key)
                self.assertEqual(candidate["summary_status"], "ready")
                self.assertEqual(candidate["summary_error"], "")

    def test_summary_claim_retries_have_distinct_tokens_and_cannot_reclaim_running(self):
        key = "doi:10.1000/claim"
        planning_store.candidate_add(self.lib.root, key, {"title": "Paper"})
        first = planning_store.candidate_summary_claim(self.lib.root, [key])[0]
        self.assertEqual(planning_store.candidate_summary_claim(self.lib.root, [key]), [])
        planning_store.candidate_summary_status(self.lib.root, key, "queued")
        second = planning_store.candidate_summary_claim(self.lib.root, [key])[0]
        self.assertNotEqual(first["summary_claim"], second["summary_claim"])
        self.assertIsNone(planning_store.candidate_save_summary(self.lib.root, key, "Old job", expected_claim=first["summary_claim"]))
        saved = planning_store.candidate_save_summary(self.lib.root, key, "New job", expected_claim=second["summary_claim"])
        self.assertEqual(saved["summary_markdown"], "New job")

    def test_save_paper_omitted_plan_and_star_preserve_existing_items(self):
        plan = {"deadline": "2027-03-04", "reminders": {"due_enabled": True}, "custom": "keep"}
        self.ws.patch_item({"starred": True, "interested": True, "reading_plan": plan, "tags": ["keep"]})
        self.ws.update("paper", lambda p: p["meta"].update(doi="10.1000/existing"))
        paper = {"title": "Existing paper", "doi": "10.1000/existing"}
        result = workspace.post(self.app, "/save-paper", {"paper": paper})
        self.assertTrue(result["existing"])
        current = self.ws.load("item")
        self.assertTrue(current["starred"])
        self.assertTrue(current["interested"])
        self.assertEqual(current["reading_plan"], plan)
        self.assertEqual(current["tags"], ["keep"])
        workspace.post(self.app, "/save-paper", {"paper": paper, "interested": False, "plan": {}})
        self.assertFalse(self.ws.load("item")["starred"])
        self.assertNotEqual(self.ws.load("item")["reading_plan"], plan)
        pending = {"title": "Pending paper", "doi": "10.1000/pending"}
        key = workspace._key(pending)
        planning_store.upsert_saved(self.lib.root, key, pending, plan=plan, interested=True)
        with patch.object(workspace.background, "start"):
            workspace.post(self.app, "/save-paper", {"paper": pending})
        self.assertEqual(planning_store.saved(self.lib.root, key)["plan"], plan)
        self.assertTrue(planning_store.saved(self.lib.root, key)["interested"])

    def test_relation_refresh_replaces_only_successful_source_edges(self):
        keys = ["doi:10.1000/one", "openalex:W2", "doi:10.1000/three"]
        snapshot = planning_store.replace_reading_path(self.lib.root, {"results": [
            {"paper_key": key, "paper": {"title": key, "openalex_id": f"W{n}"}} for n, key in enumerate(keys, 1)
        ]})
        snapshot = planning_store.save_reading_path_relations(self.lib.root, snapshot["path_id"], snapshot["revision"], [
            {"source": keys[0], "target": keys[1]}, {"source": keys[1], "target": keys[0]}, {"source": keys[2], "target": keys[0]}
        ])
        with patch.object(workspace, "_openalex", return_value={"results": [
            {"id": "https://openalex.org/W1", "referenced_works": ["https://openalex.org/W3"]},
            {"id": "https://openalex.org/W2", "referenced_works": []}
        ]}):
            result = workspace.post(self.app, "/reading-path/relations", {"path_id": snapshot["path_id"], "revision": snapshot["revision"], "force": True})
        edges = {(edge["source"], edge["target"]) for edge in result["path"]["relations"]}
        self.assertEqual(edges, {(keys[0], keys[2]), (keys[2], keys[0])})
        self.assertTrue(result["partial"])
