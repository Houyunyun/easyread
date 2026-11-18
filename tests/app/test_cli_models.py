"""Codex model catalogs are read locally; these tests never invoke a model."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from easyread.app import cli_models


class CodexCatalogTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        env = patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.write_catalog("models_cache.json", [self.model("cached-model")])

    @staticmethod
    def model(slug, **extra):
        return {"slug": slug, "visibility": "list", **extra}

    def write_catalog(self, filename, models):
        path = self.home / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"models": models}), encoding="utf-8")
        return path

    def use_catalog(self, path):
        # Literal TOML strings and comments must be parsed, not treated as path text.
        (self.home / "config.toml").write_text(
            "model = 'gateway-model'\nmodel_reasoning_effort = 'high'\n"
            f"model_catalog_json = '{path}' # local catalog\n", encoding="utf-8")

    def test_cache_without_custom_catalog(self):
        self.assertEqual([m["id"] for m in cli_models.codex()["models"]], ["cached-model"])

    def test_custom_catalog_replaces_cache_and_preserves_metadata(self):
        path = self.write_catalog("gateway-models.json", [
            self.model("later", priority=9),
            self.model("hidden", visibility="hide", priority=0),
            self.model("gateway-model", priority=1, display_name="Gateway Model",
                       description="Custom provider model", default_reasoning_level="high",
                       supported_reasoning_levels=[{"effort": "high"}, {"effort": "ultra"}]),
        ])
        self.use_catalog(path)
        original = (self.home / "config.toml").read_bytes()
        listing = cli_models.codex()
        self.assertEqual([m["id"] for m in listing["models"]], ["gateway-model", "later"])
        self.assertEqual(listing["default"], "gateway-model")
        self.assertEqual(listing["configured_reasoning"], "high")
        self.assertEqual(listing["models"][0], {
            "id": "gateway-model", "name": "Gateway Model", "desc": "Custom provider model",
            "reasoning_levels": ["high", "ultra"], "default_reasoning": "high",
        })
        self.assertEqual((self.home / "config.toml").read_bytes(), original)

    def test_relative_catalog_is_relative_to_config_directory(self):
        self.write_catalog("catalogs/models.json", [self.model("relative-model")])
        self.use_catalog("catalogs/models.json")
        self.assertEqual([m["id"] for m in cli_models.codex()["models"]], ["relative-model"])

    def test_empty_custom_catalog_does_not_restore_cached_models(self):
        self.use_catalog(self.write_catalog("empty.json", []))
        self.assertEqual(cli_models.codex()["models"], [])

    def test_missing_custom_catalog_does_not_restore_cached_models(self):
        self.use_catalog(self.home / "missing.json")
        self.assertEqual(cli_models.codex()["models"], [])

    def test_invalid_custom_catalog_is_safe(self):
        self.use_catalog(self.home / "invalid.json")
        for raw in ("not json", "null", "[]", '{"models": null}', '{"models": 1}'):
            with self.subTest(raw=raw):
                (self.home / "invalid.json").write_text(raw, encoding="utf-8")
                self.assertEqual(cli_models.codex()["models"], [])

    def test_invalid_entries_do_not_hide_valid_models(self):
        path = self.write_catalog("mixed.json", [None, 42, "bad", {},
            self.model(42), self.model("valid", supported_reasoning_levels=None)])
        self.use_catalog(path)
        self.assertEqual([m["id"] for m in cli_models.codex()["models"]], ["valid"])

    def test_rereads_catalog_without_restarting(self):
        path = self.write_catalog("gateway.json", [self.model("before")])
        self.use_catalog(path)
        self.assertEqual(cli_models.codex()["models"][0]["id"], "before")
        self.write_catalog("gateway.json", [self.model("after")])
        self.assertEqual(cli_models.codex()["models"][0]["id"], "after")

    def test_unreadable_config_does_not_break_model_settings(self):
        (self.home / "config.toml").write_text("model_catalog_json = [", encoding="utf-8")
        self.assertEqual(cli_models.codex()["models"], [])

    def test_full_listing_preserves_other_engines(self):
        self.use_catalog(self.write_catalog("gateway.json", [self.model("gateway-model")]))
        with patch.object(Path, "home", return_value=self.home), \
                patch("easyread.app.config.load", return_value={"agy": {}}), \
                patch("easyread.app.agent_models.antigravity", return_value={}), \
                patch.object(cli_models.chat_models, "actual_of", return_value=""), \
                patch.dict(os.environ, {"CLAUDE_CODE_EFFORT_LEVEL": "high"}):
            listing = cli_models.listing()
        self.assertEqual(listing["codex"]["models"][0]["id"], "gateway-model")
        self.assertEqual(listing["claude"]["configured_reasoning"], "high")
        self.assertEqual([m["id"] for m in listing["claude"]["models"]], ["opus", "sonnet", "haiku"])


if __name__ == "__main__":
    unittest.main()
