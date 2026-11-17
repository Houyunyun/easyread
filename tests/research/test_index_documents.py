"""Incremental semantic backfill, personal-note retrieval and atomic replacements."""
from __future__ import annotations

import threading
from unittest.mock import patch

from easyread.research import api, index, tasks
from tests.research.test_port_safety import PortFixture


class FakeEmbedder:
    def embed(self, passages, **kwargs):
        for number, passage in enumerate(passages):
            if "BROKEN" in passage and number > 0:
                raise RuntimeError("encoder failed midway")
            yield [1.0] + [0.0] * 383

    def query_embed(self, query):
        yield [1.0] + [0.0] * 383


class IndexDocumentsTest(PortFixture):
    def setUp(self):
        super().setUp()
        state = self.root / "index-state"
        state.mkdir()
        self.encoder = FakeEmbedder()
        for patcher in (patch.object(index, "state_dir", return_value=state),
                        patch.object(index, "vault_path", return_value=None),
                        patch.object(index, "_embedder", return_value=self.encoder),
                        patch.object(index, "_MODEL", self.encoder),
                        patch.object(tasks, "list_tasks", return_value=[])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def another_paper(self, title, text):
        ws, _ = self.lib.create_from_pdf(b"%PDF-" + title.encode(), title + ".pdf", {"title_en": title})
        ws.update("paper", lambda paper: paper.update(blocks=[{"id": "b1", "type": "para", "page": 2, "en": text}]))
        return ws

    def test_existing_vectors_do_not_prevent_new_or_changed_paper_backfill(self):
        index.index_vault(library=self.lib, semantic=True)
        new_ws = self.another_paper("New paper", "Newquartzneedle text")
        for phase in ("new", "changed"):
            with self.subTest(phase=phase):
                if phase == "changed":
                    new_ws.update("paper", lambda paper: paper["blocks"][0].update(en="Changedquartzneedle text"))
                scheduled = []
                def submit(kind, runner, **kwargs):
                    scheduled.append(runner)
                    return {"id": "backfill", "state": "queued", "kind": kind, **kwargs}
                with patch.object(tasks, "submit", side_effect=submit):
                    result = api.post(self.app, "/query", {"query": "spectrometry"})
                self.assertEqual(result["index"]["errors"], [])
                self.assertEqual(result["index"]["semantic_task"]["id"], "backfill")
                self.assertEqual(len(scheduled), 1)
                rows = index.indexed_rows(library=self.lib)
                self.assertTrue(any(row["source_id"] == self.ws.id and row["embedding"] is not None for row in rows))
                self.assertTrue(any(row["source_id"] == new_ws.id and row["embedding"] is None for row in rows))
                scheduled[0](threading.Event(), lambda *args: None)
                self.assertTrue(all(row["embedding"] is not None for row in index.indexed_rows(library=self.lib)))

    def test_reader_notes_are_retrievable_separately_with_anchors_and_deletions(self):
        self.ws.apply_reader_ops([
            {"op": "paper_note", "body": "Personalpaperneedle conclusion"},
            {"op": "note", "note": {"id": "note-1", "anchor": "p1", "page": 3, "body": "Personalannotationneedle", "updated": "2020-01-01"}},
            {"op": "note", "note": {"id": "deleted", "anchor": "p1", "body": "Deletedneedle", "deleted": True, "updated": "2020-01-01"}}
        ])
        with patch.object(tasks, "submit", return_value={"state": "queued"}):
            note = api.post(self.app, "/query", {"query": "Personalannotationneedle", "kind": "reader-note"})["results"]
            self.assertEqual(len(note), 1)
            self.assertEqual(note[0]["source_id"], self.ws.id)
            self.assertEqual(note[0]["block"], "p1")
            self.assertEqual(note[0]["page"], 3)
            self.assertEqual(note[0]["kind"], "reader-note")
            self.assertEqual(api.post(self.app, "/query", {"query": "Personalannotationneedle", "kind": "paper"})["results"], [])
            self.assertTrue(api.post(self.app, "/query", {"query": "Personalpaperneedle", "kind": "reader-note"})["results"])
            self.assertEqual(api.post(self.app, "/query", {"query": "Deletedneedle"})["results"], [])
            self.ws.apply_reader_ops([{"op": "note_del", "id": "note-1"}, {"op": "paper_note", "body": "Replacementpaperneedle"}])
            self.assertEqual(api.post(self.app, "/query", {"query": "Personalannotationneedle"})["results"], [])
            self.assertEqual(api.post(self.app, "/query", {"query": "Personalpaperneedle"})["results"], [])
            self.assertTrue(api.post(self.app, "/query", {"query": "Replacementpaperneedle"})["results"])

    def document_snapshot(self, path, library):
        db = index._db(library)
        try:
            return {
                "chunks": [tuple(row) for row in db.execute("SELECT * FROM chunks WHERE path=? ORDER BY id", (path,))],
                "fts": [tuple(row) for row in db.execute("SELECT * FROM chunks_fts WHERE id IN (SELECT id FROM chunks WHERE path=?) ORDER BY id", (path,))],
                "file": tuple(db.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone())
            }
        finally:
            db.close()

    def test_failed_paper_replacement_rolls_back_before_other_paper_commits(self):
        index.index_vault(library=self.lib, semantic=True)
        path = "easyread/" + self.ws.id
        before = self.document_snapshot(path, self.lib)
        healthy = self.another_paper("Healthy", "Healthyneedle text")
        self.ws.update("paper", lambda paper: paper["blocks"][0].update(en="BROKEN " * 450, zh=""))
        result = index.index_vault(library=self.lib, semantic=True)
        self.assertTrue(any("encoder failed midway" in error for error in result["errors"]))
        self.assertEqual(self.document_snapshot(path, self.lib), before)
        self.assertTrue(any(row["source_id"] == healthy.id for row in index.indexed_rows(library=self.lib)))

    def test_failed_vault_replacement_rolls_back_before_other_note_commits(self):
        folder = self.vault / "Research" / "Topics"
        folder.mkdir(parents=True)
        old = folder / "a-broken.md"
        old.write_text("# Original\n\nOriginalvaultneedle", encoding="utf-8")
        with patch.object(index, "vault_path", return_value=self.vault):
            index.index_vault(semantic=True)
            relative = old.relative_to(self.vault).as_posix()
            before = self.document_snapshot(relative, None)
            old.write_text("# Changed\n\n" + "BROKEN " * 450, encoding="utf-8")
            (folder / "z-healthy.md").write_text("# Healthy\n\nHealthynoteneedle", encoding="utf-8")
            result = index.index_vault(semantic=True)
            self.assertTrue(any("encoder failed midway" in error for error in result["errors"]))
            self.assertEqual(self.document_snapshot(relative, None), before)
            self.assertTrue(any("Healthynoteneedle" in row["content"] for row in index.indexed_rows()))
