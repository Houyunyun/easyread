"""Local comparison persistence, API scope, and explicit safe Vault export."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from easyread.app import config
from easyread.research import api, comparison_store, obsidian_export, proposals, store


@patch.dict(os.environ, {"EASYREAD_LANG": "zh"})
class ComparisonStoreTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.library = self.root / "library"
        self.library.mkdir()
        self.other = self.root / "other-library"
        self.other.mkdir()
        self.app = SimpleNamespace(lib=SimpleNamespace(root=self.library, all=lambda: []))
        self.other_app = SimpleNamespace(lib=SimpleNamespace(root=self.other, all=lambda: []))
        for patcher in (patch.object(config, "HOME", self.root / "home"),
                        patch.object(config, "load", return_value={}),
                        patch.object(store, "settings", return_value={})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def create(self):
        return comparison_store.create(self.library, "Comparison", "## Evidence\n\n[Paper](easyread://open?sha256=" + "a" * 64 + ")",
                                       [{"title": "Paper", "sha256": "a" * 64}], "Test model", {"tokens": 12}, "zh-Hant")

    def test_report_survives_process_reload_and_api_is_scoped_without_vault(self):
        report = self.create()
        identity = report["id"]
        self.assertEqual(report["storage"], "library")
        self.assertNotIn("vault_root", report)
        self.assertEqual(json.loads((self.library / report["target"]).read_text())["output_target"], "zh-Hant")
        reloaded = json.loads(subprocess.check_output([
            sys.executable, "-c", "import json,sys; from pathlib import Path; from easyread.research.comparison_store import get; print(json.dumps(get(Path(sys.argv[1]), sys.argv[2])))",
            str(self.library), identity], text=True))
        self.assertEqual(report, reloaded)
        status = api.get(self.app, api.PREFIX + "/status")
        self.assertFalse(status["configured"])
        self.assertEqual(status["pending_comparison"]["id"], identity)
        self.assertEqual(status["latest_comparison"]["output_target"], "zh-Hant")
        cards = api.get(self.app, api.PREFIX + "/comparisons")["comparisons"]
        self.assertEqual(cards[0]["storage"], "library")
        self.assertNotIn("content", cards[0])
        self.assertEqual(api.get(self.app, api.PREFIX + "/proposals/" + identity), report)
        self.assertEqual(api.get(self.other_app, api.PREFIX + "/comparisons")["comparisons"], [])
        self.assertIsNone(api.get(self.other_app, api.PREFIX + "/status")["latest_comparison"])
        for action in (lambda: api.get(self.other_app, api.PREFIX + "/proposals/" + identity),
                       lambda: api.post(self.other_app, f"/proposals/{identity}/title", {"title": "Wrong library"}),
                       lambda: api.post(self.other_app, f"/proposals/{identity}/review", {"decision": "accept"}),
                       lambda: api.post(self.other_app, f"/comparisons/{identity}/export", {})):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(comparison_store.get(self.library, identity), report)
        self.assertEqual(list(self.other.iterdir()), [])

    def test_rename_and_decisions_are_durable_and_do_not_write_a_vault(self):
        report = self.create()
        identity = report["id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            rename = pool.submit(api.post, self.app, f"/proposals/{identity}/title", {"title": "New name"})
            accept = pool.submit(api.post, self.app, f"/proposals/{identity}/review", {"decision": "accept"})
            rename.result()
            accept.result()
        saved = comparison_store.get(self.library, identity)
        self.assertEqual(saved["status"], "accepted")
        self.assertEqual(saved["title"], "New name")
        self.assertIn("# New name", saved["content"])
        self.assertEqual(saved["output_target"], "zh-Hant")
        self.assertEqual(saved["usage"], {"tokens": 12})
        self.assertEqual(saved["target"], report["target"])
        self.assertEqual(list(self.library.iterdir()), [self.library / comparison_store.FOLDER])
        with self.assertRaisesRegex(ValueError, "Obsidian Vault"):
            api.post(self.app, f"/comparisons/{identity}/export", {})
        # A completed decision cannot be silently reversed.
        self.assertEqual(comparison_store.decide(self.library, identity, False)["status"], "accepted")
        rejected = self.create()["id"]
        self.assertEqual(comparison_store.decide(self.library, rejected, False)["status"], "rejected")
        with self.assertRaisesRegex(ValueError, "先接受"):
            comparison_store.export(self.library, rejected)

    def test_explicit_export_requires_acceptance_and_preserves_user_vault_content(self):
        report = self.create()
        identity = report["id"]
        vault = self.root / "vault"
        vault.mkdir()
        endpoint = f"/comparisons/{identity}/export"
        with patch.object(obsidian_export, "vault_path", return_value=vault):
            with self.assertRaisesRegex(ValueError, "先接受"):
                api.post(self.app, endpoint, {})
            self.assertEqual(list(vault.iterdir()), [])
            comparison_store.decide(self.library, identity, True)
            unrelated = vault / "Research" / "05-跨论文比较" / "Comparison.md"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text("My unrelated note", encoding="utf-8")
            exported = api.post(self.app, endpoint, {"body": "Untrusted override is ignored"})
            self.assertEqual(exported["conflicts"], [])
            self.assertEqual(len(exported["written"]), 1)
            destination = vault / exported["written"][0]
            content = destination.read_text(encoding="utf-8")
            self.assertIn("easyread://open", content)
            self.assertEqual(content.count("# Comparison"), 1)
            self.assertNotIn("Untrusted override", content)
            destination.write_text(content + "\nMy personal tail\n", encoding="utf-8")
            comparison_store.rename(self.library, identity, "Renamed")
            updated = api.post(self.app, endpoint, {})
            self.assertEqual(updated["updated"], exported["written"])
            self.assertIn("My personal tail", destination.read_text(encoding="utf-8"))
            self.assertIn("# Renamed", destination.read_text(encoding="utf-8"))
            self.assertEqual(unrelated.read_text(), "My unrelated note")
            index = json.loads((vault / exported["index"]).read_text())
            self.assertEqual(index["documents"]["comparison:" + identity]["path"], exported["written"][0])

    def test_export_rejects_vault_symlink_escape_without_modifying_local_report(self):
        report = self.create()
        accepted = comparison_store.decide(self.library, report["id"], True)
        vault, outside = self.root / "vault", self.root / "outside"
        vault.mkdir()
        outside.mkdir()
        (vault / "Research").symlink_to(outside, target_is_directory=True)
        with patch.object(obsidian_export, "vault_path", return_value=vault), self.assertRaises(ValueError):
            comparison_store.export(self.library, report["id"])
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(comparison_store.get(self.library, report["id"]), accepted)

    def test_safe_uuid_paths_and_local_symlinks_fail_closed(self):
        for identity in ("../outside", "a" * 36, str(uuid4()).upper(), "/tmp/test", ""):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                comparison_store.get(self.library, identity)
        report = self.create()
        original_path = self.library / report["target"]
        original = original_path.read_bytes()
        other_id = str(uuid4())
        (original_path.parent / f"{other_id}.json").symlink_to(original_path)
        with self.assertRaises(ValueError):
            comparison_store.get(self.library, other_id)
        # A storage folder alias into another library must not expose that library.
        (self.other / comparison_store.FOLDER).symlink_to(original_path.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            comparison_store.get(self.other, report["id"])
        with self.assertRaises(ValueError):
            comparison_store.list_comparisons(self.other)
        self.assertEqual(original_path.read_bytes(), original)

    def test_atomic_failure_preserves_report_and_legacy_proposals_stay_vault_bound(self):
        report = self.create()
        path = self.library / report["target"]
        original = path.read_bytes()
        with patch.object(comparison_store, "atomic_replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                comparison_store.rename(self.library, report["id"], "Failed rename")
        self.assertEqual(path.read_bytes(), original)
        vault = self.root / "vault"
        vault.mkdir()
        with patch.object(proposals, "vault_path", return_value=vault):
            legacy = proposals.from_comparison("Legacy", "Evidence", [], "model", {})
            self.assertEqual(api.get(self.app, api.PREFIX + "/proposals/" + legacy["id"])["id"], legacy["id"])
            self.assertEqual(len(api.get(self.app, api.PREFIX + "/comparisons")["comparisons"]), 2)
        with self.assertRaisesRegex(ValueError, "其他 Vault"):
            api.post(self.app, f"/proposals/{legacy['id']}/review", {"decision": "accept"})
        self.assertEqual(list(vault.iterdir()), [])
