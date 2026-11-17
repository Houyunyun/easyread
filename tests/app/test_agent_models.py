import subprocess
import unittest
from unittest.mock import patch

from easyread.app import agent_models


class AgentModelsTest(unittest.TestCase):
    def setUp(self):
        agent_models._catalog.cache_clear()

    def test_deduplicates_effort_variants_and_caches_without_inference(self):
        result = subprocess.CompletedProcess([], 0, stdout="Fetching models\ngemini-test-high\tGemini Test (High)\ngemini-test-low\tGemini Test (Low)\n", stderr="")
        with patch.object(agent_models.agent_cli, "path", return_value="agy"), \
             patch.object(agent_models.subprocess, "run", return_value=result) as run:
            catalog = agent_models.antigravity({})
            self.assertEqual(catalog["models"], [{"id": "gemini-test", "name": "Gemini Test"}])
            self.assertEqual(agent_models.antigravity({}), catalog)
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0], ["agy", "models"])

    def test_missing_or_failed_cli_does_not_invent_available_models(self):
        with patch.object(agent_models.agent_cli, "path", return_value=None):
            self.assertEqual(agent_models.antigravity({})["models"], [])
        with patch.object(agent_models.agent_cli, "path", return_value="agy"), \
             patch.object(agent_models.subprocess, "run", side_effect=subprocess.TimeoutExpired("agy", 10)):
            self.assertEqual(agent_models.antigravity({"model": "chosen"})["default"], "chosen")
            self.assertEqual(agent_models.antigravity({})["models"], [])
