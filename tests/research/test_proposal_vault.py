"""Proposal origin binding, including fail-closed handling of legacy records."""
from __future__ import annotations

import json
import os
from unittest.mock import patch
from uuid import uuid4

from easyread.app import i18n
from easyread.library.store import read_json, write_json_atomic
from easyread.research import index, obsidian_export, proposals
from tests.research.test_port_safety import PortFixture


@patch.dict(os.environ, {"EASYREAD_LANG": "zh"})
class ProposalVaultTest(PortFixture):
    def setUp(self):
        super().setUp()
        self.state = self.root / "state"
        (self.state / "proposals").mkdir(parents=True)
        for patcher in (patch.object(proposals, "state_dir", return_value=self.state),
                        patch.object(proposals, "vault_path", return_value=self.vault),
                        patch.object(index, "index_vault", return_value={})):
            mocked = patcher.start()
            if patcher.attribute == "vault_path":
                self.vault_setting = mocked
            self.addCleanup(patcher.stop)

    def test_origin_binding_prevents_cross_vault_list_read_rename_and_accept(self):
        staged = proposals.from_comparison("Comparison", "Evidence", [], "test", {})
        path = self.state / "proposals" / (staged["id"] + ".json")
        original = path.read_bytes()
        self.assertEqual(read_json(path)["vault_root"], str(self.vault.resolve()))
        self.assertEqual(len(proposals.list_comparisons()), 1)
        other = self.root / "vault-b"
        other.mkdir()
        self.vault_setting.return_value = other
        self.assertEqual(proposals.list_comparisons(), [])
        self.assertIsNone(proposals.latest_comparison())
        self.assertIsNone(proposals.latest_pending_comparison())
        for action in (lambda: proposals.get(staged["id"]), lambda: proposals.rename(staged["id"], "Wrong vault"), lambda: proposals.decide(staged["id"], True)):
            with self.assertRaisesRegex(ValueError, "其他 Vault"):
                action()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(other.iterdir()), [])
        self.vault_setting.return_value = self.vault
        accepted = proposals.decide(staged["id"], True)
        self.assertEqual(accepted["status"], "accepted")
        self.assertTrue((self.vault / staged["target"]).is_file())
        self.assertEqual(list(other.iterdir()), [])

    def test_legacy_unbound_proposal_requires_regeneration_but_can_be_discarded(self):
        identity = str(uuid4())
        path = self.state / "proposals" / (identity + ".json")
        write_json_atomic(path, {"id": identity, "kind": "comparison", "title": "Legacy", "status": "pending", "target": "Research/Legacy.md", "after": "Keep this original draft", "before": "", "base_hash": "", "created": 1})
        before = path.read_bytes()
        self.assertEqual(proposals.list_comparisons(), [])
        self.assertIsNone(proposals.latest_comparison())
        for action in (lambda: proposals.get(identity), lambda: proposals.rename(identity, "New"), lambda: proposals.decide(identity, True)):
            with self.assertRaisesRegex(ValueError, "旧提案.*重新生成"):
                action()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.vault.iterdir()), [])
        self.assertEqual(proposals.decide(identity, False)["status"], "rejected")
        self.assertEqual(read_json(path)["after"], "Keep this original draft")
        self.assertEqual(list(self.vault.iterdir()), [])

    def test_canonical_alias_is_same_vault_but_replaced_origin_symlink_is_not(self):
        staged = proposals.from_comparison("Comparison", "Evidence", [], "test", {})
        alias = self.root / "alias"
        alias.symlink_to(self.vault, target_is_directory=True)
        self.vault_setting.return_value = alias
        self.assertEqual(proposals.get(staged["id"])["id"], staged["id"])
        other = self.root / "replacement-vault"
        other.mkdir()
        # Retargeting the canonical path must not mutate the proposal identity.
        self.vault.rmdir()
        self.vault.symlink_to(other, target_is_directory=True)
        self.vault_setting.return_value = other
        self.assertEqual(proposals.list_comparisons(), [])
        with self.assertRaisesRegex(ValueError, "其他 Vault"):
            proposals.decide(staged["id"], True)
        self.assertEqual(list(other.iterdir()), [])

    def test_comparison_links_exported_english_note_after_switching_to_simplified(self):
        doc = {"id": "paper:p1:analysis", "kind": "analysis", "paper_id": "p1", "title": "My renamed paper note", "body": "Original notes"}
        with patch.object(obsidian_export, "vault_path", return_value=self.vault), \
                patch.object(i18n, "lang", return_value="en"), \
                patch.object(i18n, "ui_dict", return_value={"01-论文分析": "01-Paper Analysis"}):
            exported = obsidian_export.export_to_vault([doc])
        note = self.vault / exported["written"][0]
        before = note.read_bytes()
        self.assertIn("01-Paper Analysis", exported["written"][0])
        # Index lookup must work even if historical folder translations are unavailable.
        with patch.object(i18n, "lang", return_value="zh"), patch.object(i18n, "ui_dict", return_value={}):
            staged = proposals.from_comparison("Comparison", "Evidence", [{"id": "p1", "title": "Original paper title"}], "test", {})
        self.assertEqual(staged["linked_paper_count"], 1)
        self.assertIn("[[Research/01-Paper Analysis/My renamed paper note]]", staged["content"])
        self.assertEqual(note.read_bytes(), before)

    def test_comparison_links_unindexed_paper_notes_in_all_known_locale_folders_once(self):
        names = ("01-论文分析", "01-Paper Analysis", "01-論文分析")
        for name in names:
            folder = self.vault / "Research" / name
            folder.mkdir(parents=True)
            (folder / "Paper.md").write_text('---\ntype: "paper"\n---\n# Paper\nUser notes', encoding="utf-8")
        dictionaries = {"zh": {}, "en": {"01-论文分析": names[1]}, "zh-Hant": {"01-论文分析": names[2]}}
        with patch.object(i18n, "lang", return_value="zh"), patch.object(i18n, "ui_dict", side_effect=lambda language: dictionaries[language]):
            staged = proposals.from_comparison("Comparison", "Evidence", [{"title": "Paper"}], "test", {})
        self.assertEqual(staged["linked_paper_count"], 3)
        for name in names:
            self.assertEqual(staged["content"].count(f"[[Research/{name}/Paper]]"), 1)

    def test_index_and_legacy_folder_links_cannot_escape_the_vault_or_rebind_identity(self):
        outside = self.root / "outside.md"
        outside.write_text('---\nresearch_id: "paper:outside"\ntype: "analysis"\npaper_id: "p1"\n---\n# Paper\nPrivate', encoding="utf-8")
        research = self.vault / "Research"
        research.mkdir()
        (research / "Papers").symlink_to(self.root, target_is_directory=True)
        inside = self.vault / "Unrelated.md"
        inside.write_text('---\nresearch_id: "unrelated-id"\n---\n# Paper\nKeep', encoding="utf-8")
        (research / obsidian_export.INDEX_NAME).write_text(json.dumps({"version": 1, "documents": {
            "paper:outside": {"kind": "analysis", "path": "../outside.md"},
            "paper:rebound": {"kind": "analysis", "path": "Unrelated.md"},
        }}), encoding="utf-8")
        staged = proposals.from_comparison("Comparison", "Evidence", [{"id": "p1", "title": "Paper"}], "test", {})
        self.assertEqual(staged["linked_paper_count"], 0)
        self.assertNotIn("Private", staged["content"])
        self.assertNotIn("Unrelated", staged["content"])
        self.assertTrue(outside.read_text().endswith("Private"))

    def test_every_staging_path_records_origin(self):
        topic = proposals.create_topic("Topic")
        record = read_json(self.state / "proposals" / (topic["id"] + ".json"))
        self.assertEqual(record["vault_root"], str(self.vault.resolve()))
        proposals.decide(topic["id"], True)
        matrix = proposals.from_topic_matrix(topic["target"], {"sha256": "a" * 64, "title": "Paper", "cells": {"title": "Paper"}}, "test", {})
        record = read_json(self.state / "proposals" / (matrix["id"] + ".json"))
        self.assertEqual(record["vault_root"], str(self.vault.resolve()))
        with patch.object(proposals.workflows, "gather", return_value={"sources": []}), patch("easyread.chat.chat_models.engine_cfg", return_value=({"engine": "test"}, {"id": "test"})), patch.object(proposals.engines, "run", return_value="Question draft"):
            question = proposals.create("Question", "question", "Investigate", self.lib)
        self.assertEqual(read_json(self.state / "proposals" / (question["id"] + ".json"))["vault_root"], str(self.vault.resolve()))
