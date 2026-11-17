"""Proposal origin binding, including fail-closed handling of legacy records."""
from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

from easyread.library.store import read_json, write_json_atomic
from easyread.research import index, proposals
from tests.research.test_port_safety import PortFixture


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
            with self.assertRaisesRegex(ValueError, "different Vault"):
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
            with self.assertRaisesRegex(ValueError, "legacy.*regenerate"):
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
        with self.assertRaisesRegex(ValueError, "different Vault"):
            proposals.decide(staged["id"], True)
        self.assertEqual(list(other.iterdir()), [])

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
