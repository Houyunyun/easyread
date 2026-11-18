"""Manual mindmap storage identity must survive locale/source changes and empty maps."""
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from easyread.app import i18n
from easyread.library import planning_store
from easyread.library.store import Workspace, write_json_atomic
from easyread.research import mindmaps, workspace


class MindmapIdentityTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ws = Workspace(self.root / "bilingual-paper")
        self.ws.root.mkdir()
        write_json_atomic(self.ws.root / "paper.json", {
            "meta": {"title_en": "Bilingual paper without a target"},
            "blocks": [{"id": "p1", "type": "para", "en": "Original evidence", "zh": "已有译文，但没有目标语言"}],
        })
        self.app = SimpleNamespace(lib=SimpleNamespace(root=self.root, ws=lambda pid: self.ws if pid == self.ws.id else None))
        self.path = f"/paper/{self.ws.id}/mindmap"
        locale_patch = patch.object(i18n, "lang", return_value="en")
        self.locale = locale_patch.start()
        self.addCleanup(locale_patch.stop)

    def get(self):
        return workspace.get(self.app, workspace.PREFIX + self.path)

    def save(self, identity, mermaid="mindmap\n  root((Manual))", revision=0):
        return workspace.post(self.app, self.path + "/save", {
            "target": identity["target"], "source_sha256": identity["source_sha256"],
            "mermaid": mermaid, "revision": revision,
        })

    def test_empty_online_and_offline_maps_expose_identity_for_manual_creation(self):
        offline = mindmaps.offline_snapshot(self.ws)["mindmap"]
        self.assertFalse((self.root / ".paperread-planning.sqlite3").exists())
        self.assertFalse(offline["cached"])
        self.assertEqual(offline["target"], "en")
        self.assertEqual(offline["paper_id"], self.ws.id)
        self.assertEqual(len(offline["source_sha256"]), 64)
        online = self.get()
        for field in ("target", "source_sha256", "paper_id", "cached"):
            self.assertEqual(online[field], offline[field])
        saved = self.save(offline)
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(saved["source_sha256"], offline["source_sha256"])
        self.assertEqual(self.get(), mindmaps.offline_snapshot(self.ws)["mindmap"])
        # Empty paper text still has a source identity for a user-created map.
        self.ws.update("paper", lambda p: p.update(blocks=[]))
        empty = self.get()
        self.assertEqual(empty["source_sha256"], sha256(b"").hexdigest())
        self.assertFalse(empty["cached"])

    def test_old_english_editor_cannot_overwrite_simplified_map_at_the_same_revision(self):
        english = self.save(self.get(), "mindmap\n  root((English))")
        self.locale.return_value = "zh"
        chinese = self.save(self.get(), "mindmap\n  root((简体内容))")
        self.assertEqual(english["source_sha256"], chinese["source_sha256"])
        self.assertEqual(english["revision"], chinese["revision"])
        with patch.object(planning_store, "save_mindmap") as write:
            with self.assertRaisesRegex(ValueError, "语言已变更"):
                self.save(english, "mindmap\n  root((Stale English draft))", revision=english["revision"])
            write.assert_not_called()
        self.assertEqual(self.get()["mermaid"], chinese["mermaid"])
        self.locale.return_value = "en"
        self.assertEqual(self.get()["mermaid"], english["mermaid"])

    def test_source_mismatch_is_rejected_before_revision_validation(self):
        original = self.save(self.get())
        self.ws.update("paper", lambda p: p["blocks"][0].update(en="New source evidence"))
        current = self.get()
        self.assertNotEqual(current["source_sha256"], original["source_sha256"])
        with patch.object(planning_store, "save_mindmap") as write:
            with self.assertRaisesRegex(ValueError, "source has changed"):
                self.save(original, revision="invalid revision")
            write.assert_not_called()
        self.assertFalse(self.get()["cached"])
        self.assertEqual(self.save(current)["revision"], 1)

    def test_identity_is_required_and_language_mismatch_precedes_revision_validation(self):
        identity = self.get()
        body = {"mermaid": "mindmap\n  root((Manual))", "revision": "invalid revision", **identity}
        for missing in ("target", "source_sha256"):
            for invalid in (None, "", 3):
                with self.subTest(field=missing, value=invalid), self.assertRaisesRegex(ValueError, "no language or source identity"):
                    workspace.post(self.app, self.path + "/save", {**body, missing: invalid})
            omitted = {k: v for k, v in body.items() if k != missing}
            with self.assertRaisesRegex(ValueError, "no language or source identity"):
                workspace.post(self.app, self.path + "/save", omitted)
        with self.assertRaisesRegex(ValueError, "language has changed"):
            workspace.post(self.app, self.path + "/save", {**body, "target": "zh"})
        with self.assertRaisesRegex(ValueError, "revision"):
            workspace.post(self.app, self.path + "/save", body)

    def test_explicit_paper_target_is_the_authority_not_ui_language(self):
        self.ws.update("paper", lambda p: p["meta"].update(target="zh-TW"))
        identity = self.get()
        self.assertEqual(identity["target"], "zh-Hant")
        self.locale.return_value = "zh"
        self.assertEqual(self.save(identity)["target"], "zh-Hant")
        with self.assertRaisesRegex(ValueError, "语言已变更"):
            self.save({**identity, "target": "zh-TW"}, revision=1)

    def test_cache_payload_cannot_masquerade_as_another_source(self):
        identity = self.get()
        key = "mindmap:en:" + sha256(identity["source_sha256"].encode()).hexdigest()
        for bad in ({"target": "zh"}, {"source_sha256": "b" * 64}):
            payload = {**identity, "mermaid": "mindmap\n  root((Wrong identity))", **bad}
            planning_store.cache_put(self.root, key, payload)
            for view in (self.get(), mindmaps.offline_snapshot(self.ws)["mindmap"]):
                self.assertFalse(view["cached"])
                self.assertNotIn("mermaid", view)
                self.assertEqual(view["source_sha256"], identity["source_sha256"])
            self.assertEqual(planning_store.cache_get(self.root, key)[0], payload)


if __name__ == "__main__":
    unittest.main()
