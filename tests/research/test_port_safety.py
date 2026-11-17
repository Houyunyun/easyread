"""Research port invariants: canonical paths, scoped retrieval, reader compatibility."""
from __future__ import annotations

import base64
import io
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from tests.http_support import anonymous_access
from easyread.app import i18n
from easyread.library import planning_store
from easyread.library.library import Library
from easyread.library.store import Workspace, write_json_atomic
from easyread.research import deep_analysis, index, obsidian_export, proposals, store, tasks, workspace
from easyread.server import research_api, server
from easyread.server.library_api import LibraryLocation


class PortFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lib = Library(self.root / "library")
        self.ws, _ = self.lib.create_from_pdf(b"%PDF-port-fixture", "fixture.pdf")
        self.ws.update("paper", lambda p: p.update({"blocks": [{"id": "p1", "type": "para", "en": "Rare spectrometry evidence", "zh": "证据"}]}))
        self.app = SimpleNamespace(access=anonymous_access(self.root), lib=self.lib, token="token", presence=None,
                                   jobs=SimpleNamespace(busy=lambda: False))
        self.app.location = LibraryLocation(self.app)
        self.addCleanup(self.app.location.marker.close)
        self.vault = self.root / "vault"
        self.vault.mkdir()

    def doc(self, **fields):
        return {"id": "paper:p1:analysis", "kind": "analysis", "title": "Evidence", "body": "Generated evidence", **fields}


class ExportContainmentTest(PortFixture):
    def export(self, docs):
        with patch.object(obsidian_export, "vault_path", return_value=self.vault):
            return obsidian_export.export_to_vault(docs)

    def test_relative_symlink_escape_is_rejected_even_when_leaf_is_absent(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.vault / "escape").symlink_to(outside, target_is_directory=True)
        with patch.object(store, "vault_path", return_value=self.vault):
            for path in (Path("escape/new.md"), self.vault / "escape/new.md", Path("../outside/new.md")):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    store.validate_vault_path(path)
        self.assertEqual(list(outside.iterdir()), [])

    def test_export_rejects_symlinked_research_folder_and_index(self):
        outside = self.root / "outside"
        outside.mkdir()
        research = self.vault / "Research"
        research.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.export([self.doc()])
        research.unlink()
        research.mkdir()
        foreign_index = outside / "index.json"
        foreign_index.write_text("unrelated")
        (research / obsidian_export.INDEX_NAME).symlink_to(foreign_index)
        with self.assertRaises(ValueError):
            self.export([self.doc()])
        self.assertEqual(foreign_index.read_text(), "unrelated")
        self.assertEqual(list(outside.iterdir()), [foreign_index])

    def test_attachments_are_preflighted_and_do_not_overwrite_unrelated_files(self):
        folder = self.vault / "Research" / obsidian_export.EXPORT_FOLDERS["analysis"]
        folder.mkdir(parents=True)
        outside = self.root / "outside"
        outside.mkdir()
        (folder / "assets").symlink_to(outside, target_is_directory=True)
        doc = self.doc(attachments=[{"filename": "assets/figure.png", "content_base64": base64.b64encode(b"image").decode()}])
        with self.assertRaises(ValueError):
            self.export([doc])
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((folder / "Evidence.md").exists())
        (folder / "assets").unlink()
        (folder / "assets").mkdir()
        asset = folder / "assets/figure.png"
        asset.write_bytes(b"user-owned")
        result = self.export([doc])
        self.assertTrue(result["conflicts"])
        self.assertEqual(asset.read_bytes(), b"user-owned")
        self.assertFalse((folder / "Evidence.md").exists())

    def test_zip_rejects_unsafe_attachment_names_and_note_overwrites(self):
        for name in ("../outside.png", "/absolute.png", "C:\\outside.png", "Evidence.md"):
            with self.subTest(name=name), patch.object(obsidian_export, "vault_path", return_value=self.vault), self.assertRaises(ValueError):
                obsidian_export.export_zip([self.doc(attachment={"filename": name, "content_base64": "eA=="})])

    def test_collision_suffixes_and_managed_updates_preserve_unrelated_notes(self):
        folder = self.vault / "Research" / obsidian_export.EXPORT_FOLDERS["analysis"]
        folder.mkdir(parents=True)
        for name in ("Evidence.md", "Evidence--p1-analysis-1.md"):
            (folder / name).write_text("manual note")
        first = self.export([self.doc()])
        note = self.vault / first["written"][0]
        self.assertNotEqual(note.name, "Evidence.md")
        note.write_text(note.read_text() + "\nMy handwritten footer\n")
        second = self.export([self.doc(body="New evidence")])
        self.assertEqual(second["updated"], first["written"])
        self.assertIn("My handwritten footer", note.read_text())
        self.assertEqual((folder / "Evidence.md").read_text(), "manual note")

    def test_concurrent_exports_keep_index_entries_and_unique_atomic_temps(self):
        with patch.object(obsidian_export, "vault_path", return_value=self.vault):
            with ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(lambda n: obsidian_export.export_to_vault([self.doc(id=f"paper:{n}", title="Same title")]), range(6)))
        paths = [r["written"][0] for r in results]
        self.assertEqual(len(set(paths)), 6)
        saved = json.loads((self.vault / "Research" / obsidian_export.INDEX_NAME).read_text())
        self.assertEqual(len(saved["documents"]), 6)
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda n: store.atomic_replace(self.vault / "shared.bin", bytes([n]) * 400), range(6)))
        self.assertEqual(len((self.vault / "shared.bin").read_bytes()), 400)
        self.assertEqual(list(self.vault.rglob("*.tmp")), [])

    def test_proposal_acceptance_rejects_symlink_escape(self):
        state = self.root / "state"
        (state / "proposals").mkdir(parents=True)
        outside = self.root / "outside.md"
        outside.write_text("keep")
        (self.vault / "escape.md").symlink_to(outside)
        identity = str(uuid4())
        write_json_atomic(state / "proposals" / (identity + ".json"),
                          {"id": identity, "status": "pending", "target": "escape.md", "base_hash": "", "after": "replace"})
        with patch.object(proposals, "state_dir", return_value=state), patch.object(proposals, "vault_path", return_value=self.vault), patch.object(store, "vault_path", return_value=self.vault):
            with self.assertRaises(ValueError):
                proposals.decide(identity, True)
        self.assertEqual(outside.read_text(), "keep")


class WorkspacePersistenceTest(PortFixture):
    def test_mindmap_edits_revisions_and_offline_snapshot_do_not_generate(self):
        db_path = self.lib.root / ".paperread-planning.sqlite3"
        with patch.object(workspace, "_openalex", side_effect=AssertionError("network")):
            empty = workspace.offline_snapshot(self.ws)
            self.assertFalse(empty["mindmap"]["cached"])
            self.assertFalse(db_path.exists())
            saved = workspace.post(self.app, f"/paper/{self.ws.id}/mindmap/save", {"mermaid": "mindmap\n  root((Saved))", "revision": 0})
            self.assertEqual(saved["revision"], 1)
            with self.assertRaises(ValueError):
                workspace.post(self.app, f"/paper/{self.ws.id}/mindmap/save", {"mermaid": "mindmap\n  root((Stale))", "revision": 0})
            write_json_atomic(self.ws.root / "report.json", {"markdown": "Saved audit", "paper_id": self.ws.id})
            offline = workspace.offline_snapshot(self.ws)
            online = workspace.get(self.app, f"/api/research/v2/paper/{self.ws.id}/mindmap")
            self.assertEqual(offline["mindmap"], online)
            self.assertTrue(offline["mindmap"]["edited"])
            self.assertEqual(offline["deep_analysis"]["markdown"], "Saved audit")

    def test_keyword_map_revision_goals_follows_and_reminder_claim_contracts(self):
        created = workspace.post(self.app, "/keyword-maps", {"name": "Ideas", "data": {"nodes": [{"id": "n1", "label": "First"}], "edges": []}})["map"]
        self.assertEqual(created["revision"], 1)
        changed = workspace.post(self.app, "/keyword-maps", {**created, "name": "Edited"})["map"]
        self.assertEqual(changed["revision"], 2)
        with self.assertRaises(ValueError):
            workspace.post(self.app, "/keyword-maps", created)
        self.assertEqual(workspace.get(self.app, "/api/research/v2/keyword-maps")["maps"][0]["name"], "Edited")
        goal = workspace.post(self.app, "/milestones", {"title": "Read evidence", "start_date": "2026-01-02", "recurrence": "weekly", "linked": ["paper:" + self.ws.id]})["milestone"]
        self.assertEqual(workspace.get(self.app, "/api/research/v2/milestones")["milestones"][0]["id"], goal["id"])
        self.assertTrue(workspace.post(self.app, "/milestones/delete", {"id": goal["id"]})["deleted"])
        follow = workspace.post(self.app, "/follows", {"kind": "author", "value": "A123", "label": "Author"})["follow"]
        self.assertEqual(workspace.get(self.app, "/api/research/v2/follows")["follows"][0]["id"], follow["id"])
        self.assertTrue(workspace.post(self.app, "/follows/delete", {"id": follow["id"]})["deleted"])
        body = {"candidates": [{"key": "event-1", "title": "Start reading"}]}
        self.assertEqual(len(workspace.post(self.app, "/reminders/claim", body)["claimed"]), 1)
        self.assertEqual(workspace.post(self.app, "/reminders/claim", body)["claimed"], [])
        for endpoint, data in (("/reminders/claim", {"candidates": [{"key": "x" * 301}]}), ("/milestones", {"title": "Bad", "start_date": "2026-01-01", "linked": [{}]})):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                workspace.post(self.app, endpoint, data)

    def test_old_reader_unknown_fields_and_group_undo_survive_restart(self):
        original = {"schema": 2, "rev": 4, "edits": {"p1": {"zh": "manual"}}, "notes": {"old": {"id": "old", "body": "keep"}}, "future_field": {"nested": [1, 2]}, "paper_note": {"body": "private"}}
        write_json_atomic(self.ws.reader_path, original)
        sticker = {"id": "text1", "assetId": "paperread-text-box", "anchor": "p1", "textHash": "1234abcd", "ref": [200, 100], "x": 1, "y": 2, "width": 100, "height": 50, "rotation": 0, "opacity": 1, "z": 1, "locked": False, "text": "Research", "groupId": "g1"}
        stroke = {"id": "ink1", "anchor": "p1", "textHash": "1234abcd", "ref": [200, 100], "group": "p1", "groupId": "g1", "points": [[1, 2]], "color": "#112233", "width": 2}
        ops = [{"op": "sticker", "sticker": sticker}, {"op": "ink", "stroke": stroke}]
        self.ws.apply_reader_ops([{**op, "at": "2026-01-01T00:00:00Z"} for op in ops])
        self.ws.apply_reader_ops([{"op": "sticker_del", "id": "text1", "at": "2026-01-02T00:00:00Z"}, {"op": "ink_del", "id": "ink1", "at": "2026-01-02T00:00:00Z"}])
        self.ws.apply_reader_ops([{**op, "at": "2026-01-03T00:00:00Z"} for op in ops], client="undo")
        reader = Workspace(self.ws.root).load("reader")
        for field in ("future_field", "edits", "notes", "paper_note"):
            self.assertEqual(reader[field], original[field])
        self.assertFalse(reader["stickers"]["text1"].get("deleted"))
        self.assertFalse(reader["ink"]["ink1"].get("deleted"))
        self.assertIn('"client": "undo"', self.ws.journal_path.read_text())

    def test_task_recovery_is_library_scoped_and_marks_interrupted_work(self):
        identity = str(uuid4())
        folder = self.lib.root / ".research-tasks"
        folder.mkdir()
        scope = tasks.scope_id(self.lib.root)
        write_json_atomic(folder / (identity + ".json"), {"id": identity, "scope": scope, "kind": "mindmap", "state": "running", "created": time.time(), "updated": time.time()})
        tasks.recover(self.lib.root)
        task = tasks.get(identity, scope)
        self.assertEqual(task["state"], "failed")
        self.assertEqual(task["result_state"], "interrupted")
        self.assertIsNone(tasks.get(identity, tasks.scope_id(self.root)))
        self.assertEqual(json.loads((folder / (identity + ".json")).read_text())["state"], "failed")

    def test_retrieval_index_isolated_between_library_and_vault(self):
        state = self.root / "index"
        state.mkdir()
        other = Library(self.root / "other-library")
        other_vault = self.root / "other-vault"
        other_vault.mkdir()
        with patch.object(index, "state_dir", return_value=state), patch.object(index, "vault_path", return_value=self.vault), patch.object(tasks, "submit", return_value={"state": "queued"}):
            index.index_vault(library=self.lib, semantic=False)
            self.assertTrue(index.search("spectrometry", library=self.lib)["results"])
            self.assertEqual(index.search("spectrometry", library=other)["results"], [])
            with patch.object(index, "vault_path", return_value=other_vault):
                self.assertEqual(index.indexed_rows(library=self.lib), [])
        self.assertEqual(len(list(state.glob("index-*.sqlite3"))), 3)

    def test_host_token_and_library_location_guard_research_routes(self):
        handler = object.__new__(server.Handler)
        handler.app = self.app
        handler.connection = None
        handler.path, handler.command = "/api/research/v2/milestones", "POST"
        handler.headers = Message()
        handler.headers["Host"] = "evil.example"
        handler.headers["X-Token"] = "token"
        with patch.object(handler, "_post") as post, patch.object(handler, "_json") as response:
            handler.do_POST()
            self.assertEqual(response.call_args.args[0], 403)
            post.assert_not_called()
            handler.headers.replace_header("Host", "127.0.0.1")
            handler.headers.replace_header("X-Token", "wrong")
            handler.do_POST()
            self.assertEqual(response.call_args.args[0], 403)
            post.assert_not_called()
            handler.headers.replace_header("X-Token", "token")
            self.app.location.status = "restart_required"
            handler.do_POST()
            post.assert_not_called()
        for status in ("moving", "restart_required"):
            self.app.location.status = status
            with self.assertRaises(ValueError):
                with self.app.location.request("GET", "/api/research/v2/init"):
                    self.fail("Research GET may initialize state and must be guarded")
        with self.app.location.request("GET", f"/api/p/{self.ws.id}/state"):
            pass  # Existing read-only reader behavior remains available after migration.

    def test_language_rules_respect_paper_target_over_ui_language(self):
        with patch.object(i18n, "lang", return_value="en"):
            prompt = deep_analysis.build_audit_prompt({"target": "zh-Hant"}, "Evidence")
        self.assertIn("繁體中文", prompt)
        self.assertNotIn("Please output the entire report in English", prompt)
        self.assertEqual(workspace._mindmap_language_guide({"target": "zh-TW"})[0], "zh-Hant")
        self.assertNotIn("繁體中文", workspace._mindmap_language_guide({"target": "fr"})[1]["name"])

    def test_regeneration_does_not_overwrite_a_concurrent_manual_mindmap_edit(self):
        from easyread.chat import chat_models
        from easyread.engines import engines

        def model(*args, **kwargs):
            workspace.post(self.app, f"/paper/{self.ws.id}/mindmap/save", {"mermaid": "mindmap\n  root((Manual concurrent edit))", "revision": 0})
            return "mindmap\n  root((Generated))"

        with patch.object(chat_models, "engine_cfg", return_value=({"engine": "test"}, {"id": "test"})), patch.object(engines, "run", side_effect=model):
            with self.assertRaisesRegex(ValueError, "Mindmap changed"):
                workspace.post(self.app, f"/paper/{self.ws.id}/mindmap", {})
        self.assertIn("Manual concurrent edit", workspace.offline_snapshot(self.ws)["mindmap"]["mermaid"])
