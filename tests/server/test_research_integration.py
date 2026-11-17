"""Seams between research features and Docker access/model configuration."""
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from easyread.app import config
from easyread.research import index
from easyread.server import activity, settings_api


class ResearchIntegrationTest(unittest.TestCase):
    def test_docker_shared_stage_supports_semantic_retrieval_and_slow_downloads(self):
        dockerfile = (Path(__file__).resolve().parents[2] / 'Dockerfile').read_text()
        shared = dockerfile.split('FROM python-deps AS lite', 1)[0]
        self.assertIn('libgomp1', shared)
        self.assertIn('ARG PIP_DEFAULT_TIMEOUT=120', shared)
        self.assertIn('ARG PIP_RETRIES=5', shared)
        self.assertIn('ARG PIP_INDEX_URL=https://pypi.org/simple', shared)
        for stage in ('FROM python-deps AS lite', 'FROM python-deps AS full-deps', 'FROM full-deps AS full'):
            header = dockerfile.split(stage, 1)[1].split('COPY', 1)[0]
            self.assertIn('ARG PIP_INDEX_URL=https://pypi.org/simple', header)
            self.assertIn('ARG PIP_DEFAULT_TIMEOUT=120', header)
            self.assertIn('ARG PIP_RETRIES=5', header)
        root = Path(__file__).resolve().parents[2]
        for name in ('docker-compose.yml', 'docker-compose.lite.yml'):
            compose = (root / name).read_text()
            self.assertIn('PIP_INDEX_URL: ${EASYREAD_PIP_INDEX_URL:', compose)
            self.assertIn('NO_PROXY: ${EASYREAD_BUILD_NO_PROXY:', compose)

    def test_research_and_summary_work_are_included_in_lifecycle_guard(self):
        app = SimpleNamespace(jobs=SimpleNamespace(busy=lambda: False),
                              babeldoc=SimpleNamespace(running={}), lib=SimpleNamespace(root=Path('/test-library')))
        with patch.object(activity.tasks, 'busy', return_value=False) as tasks, \
             patch.object(activity.background, 'busy', return_value=False) as background:
            self.assertFalse(activity.model_work(app))
            tasks.return_value = True
            self.assertTrue(activity.model_work(app))
            tasks.return_value = False
            background.return_value = True
            self.assertTrue(activity.model_work(app))
            background.assert_called_with(app.lib.root)

    def test_model_form_test_uses_overrides_without_saving_or_leaking_other_api_keys(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        cfg['openai'].update(preset='', base_url='https://old.example/v1', api_key='old-secret', model='old')
        original = copy.deepcopy(cfg)
        with patch.object(config, 'load', return_value=cfg), patch.object(config, 'save') as save, \
             patch.object(settings_api.engines, 'test', return_value={'ok': True}) as test:
            settings_api.test_engine({'engine': 'openai', 'model': 'new', 'openai': {
                'preset': '', 'base_url': 'https://new.example/v1', 'api': 'responses'}})
            tested = test.call_args.args[0]
            self.assertEqual(tested['openai']['model'], 'new')
            self.assertEqual(tested['openai']['api_key'], '')
            self.assertEqual(tested['openai']['base_url'], 'https://new.example/v1')
            self.assertEqual(tested['openai']['api'], 'responses')
            settings_api.test_engine({'engine': 'codex', 'model': 'chosen', 'reasoning_effort': 'high'})
            self.assertEqual(test.call_args.args[0]['codex']['model'], 'chosen')
            self.assertEqual(test.call_args.args[0]['codex']['reasoning_effort'], 'high')
            self.assertEqual(cfg, original)
            save.assert_not_called()

    def test_huggingface_retry_discards_cached_proxy_transport(self):
        import huggingface_hub
        from huggingface_hub import utils
        with patch.object(utils, 'close_session', create=True) as close:
            index._refresh_download_transport()
            close.assert_called_once()
        with patch.object(utils, 'close_session', None, create=True), \
             patch.object(huggingface_hub, 'configure_http_backend', create=True) as configure:
            index._refresh_download_transport()
            configure.assert_called_once_with()
