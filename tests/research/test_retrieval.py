import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from easyread.app import config
from easyread.library.library import Library
from easyread.research import api, index


class RetrievalTest(unittest.TestCase):
    def test_retrieval_indexes_local_papers_without_requiring_an_obsidian_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lib = Library(root / "library")
            ws, _ = lib.create_from_pdf(b"%PDF-1.4\nretrieval fixture", "fixture.pdf")
            ws.update("paper", lambda p: p.update(meta={**p["meta"], "title_en": "Local method"}, blocks=[
                {"id": "p1", "type": "para", "page": 1, "en": "Masked segmentation improves the baseline."}]))
            with patch.object(config, "HOME", root), patch.object(index, "vault_path", return_value=None), \
                 patch("easyread.research.tasks.submit", return_value={"id": "fixture", "state": "queued"}):
                found = api.post(SimpleNamespace(lib=lib), "/query", {"query": "segmentation"})
                self.assertEqual(found["results"][0]["source_id"], ws.id)
                self.assertEqual(found["results"][0]["block"], "p1")
                self.assertIn("baseline", found["results"][0]["snippet"])
                other = Library(root / "other-library")
                self.assertEqual(api.post(SimpleNamespace(lib=other), "/query", {"query": "segmentation"})["results"], [])
                lib.trash(ws.id)
                self.assertEqual(api.post(SimpleNamespace(lib=lib), "/query", {"query": "segmentation"})["results"], [])

    def test_query_validates_input_before_indexing(self):
        with patch.object(index, "search") as search:
            for body in ({}, {"query": []}, {"query": "q", "limit": True},
                         {"query": "q", "limit": 31}, {"query": "q", "kind": "../paper"}):
                with self.assertRaises(ValueError):
                    api.post(SimpleNamespace(), "/query", body)
            search.assert_not_called()
