"""Reader bundling tests; research storage itself is covered by the backend suite."""
import base64
import importlib
import json
import os
import re
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from easyread.library.store import Workspace

build_module = importlib.import_module("easyread.export.build")
ROOT = Path(__file__).resolve().parents[2]


class PaperReadOfflineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.web = self.root / "web"
        self.web.mkdir()
        (self.web / "stickers").symlink_to(ROOT / "easyread" / "web" / "stickers", target_is_directory=True)
        # An isolated port worktree can supply shell-owned assets during review.
        # Once integrated, every dependency comes from the checked-in web tree.
        roots = [ROOT / "easyread" / "web"]
        if os.environ.get("PAPERREAD_SHARED_WEB"):
            roots.append(Path(os.environ["PAPERREAD_SHARED_WEB"]).resolve())
        for root in roots:
            for source in root.rglob("*"):
                if source.is_file():
                    target = self.web / source.relative_to(root)
                    if not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.symlink_to(source)
        self.ws = Workspace(self.root / "paper")
        self.ws.root.mkdir()
        self.paper = {
            "meta": {"title_en": "Offline sample", "pages": [{"n": 1, "img": "pages/page-001.png"}]},
            "translation": {"done_pages": [1]},
            "blocks": [{"id": "p1", "type": "para", "zh": "测试正文", "en": "Source text", "page": 1},
                       {"id": "f1", "type": "figure", "page": 1, "src": "original.png", "caption_zh": "Figure",
                        "translated_image": {"src": "translated.png"}}],
        }
        pixel = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZlS8AAAAASUVORK5CYII=")
        for rel in ["pages/page-001.png", "original.png", "translated.png"]:
            target = self.ws.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(pixel)
        self.reader = {"ink": {"ink1": {"id": "ink1", "anchor": "p1", "points": [[1, 1]], "color": "#112233", "width": 2, "ref": [100, 100], "textHash": "unused"}},
                       "stickers": {"s1": {"id": "s1", "assetId": "atom", "anchor": "p1", "ref": [100, 100], "textHash": "unused",
                                            "x": 0, "y": 0, "width": 40, "height": 40, "rotation": 0, "opacity": 1, "z": 1}},
                       "paper_note": {"body": "# Saved note\n\n[Source](#b-p1)"}}
        self.snapshot = {"mindmap": {"mermaid": "mindmap\n  Saved map", "revision": 3},
                         "deep_analysis": {"report": {"markdown": "# Saved audit"}}}
        research = types.ModuleType("easyread.research")
        workspace = types.ModuleType("easyread.research.workspace")
        workspace.offline_snapshot = lambda ws: self.snapshot
        self.addCleanup(patch.stopall)
        patch.dict("sys.modules", {"easyread.research": research, "easyread.research.workspace": workspace}).start()
        patch.object(build_module, "WEB", self.web).start()

    def export(self, mobile=False):
        for name, data in {"paper": self.paper, "reader": self.reader}.items():
            (self.ws.root / (name + ".json")).write_text(json.dumps(data), encoding="utf-8")
        file = build_module.build(self.ws, out=self.root / "reader.html", lang="zh-CN", mobile=mobile)
        html = file.read_text(encoding="utf-8")
        data = json.loads(re.search(r'<script id="pr-data" type="application/json">(.*?)</script>', html, re.S)[1])
        if os.environ.get("PAPERREAD_OFFLINE_OUTPUT") and not mobile:
            Path(os.environ["PAPERREAD_OFFLINE_OUTPUT"]).write_text(html, encoding="utf-8")
        return html, data

    def test_assets_notes_research_and_generated_images_are_embedded(self):
        html, data = self.export()
        self.assertNotRegex(html, r'<(?:script src|link rel="stylesheet" href)="/web/')
        self.assertIn("PR.mindmapEdits", html)
        self.assertIn("PR.toggleStickerPanel", html)
        self.assertEqual(data["reader"], self.reader)
        self.assertEqual(data["mindmap"]["revision"], 3)
        self.assertEqual(data["deep_analysis"], self.snapshot["deep_analysis"])
        self.assertEqual(len(data["stickerAssets"]), 199)
        self.assertTrue(all(a["offlineData"].startswith("data:image/") for a in data["stickerAssets"]))
        self.assertEqual(set(data["stickerLicenses"]), {"LICENSE-LUCIDE.txt", "LICENSE-CC-BY-SA-4.0.txt"})
        self.assertTrue(data["images"]["translated.png"].startswith("data:image/png;base64,"))
        self.assertIn("pages/page-001.png", data["images"])

    def test_web_articles_keep_the_original_snapshot_and_notes(self):
        self.paper["meta"]["source_type"] = "web"
        original = '<!doctype html><article><h1>Web article</h1><p id="source">Original page</p></article>'
        (self.ws.root / "source.html").write_text(original, encoding="utf-8")
        _, data = self.export()
        self.assertEqual(data["web_snapshot"], original)
        self.assertEqual(data["reader"]["paper_note"], self.reader["paper_note"])

    def test_mobile_remains_read_only_and_excludes_completed_page_images(self):
        html, data = self.export(mobile=True)
        self.assertIn("body.mobile-read #inkTools", html)
        self.assertNotIn("pages/page-001.png", data["images"])
        self.assertEqual(data["reader"], self.reader)
        self.assertEqual(data["layout"], {})


if __name__ == "__main__":
    unittest.main()
