import importlib.util
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

runtime = None
if os.name == 'posix':
    spec = importlib.util.spec_from_file_location('docker_runtime', Path(__file__).resolve().parents[2] / 'docker/runtime.py')
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)


class SeccompProfileTest(unittest.TestCase):
    def test_windows_collection_does_not_import_posix_runtime(self):
        spec = importlib.util.spec_from_file_location('runtime_windows_collection', __file__)
        module = importlib.util.module_from_spec(spec)
        with patch('os.name', 'nt'):
            spec.loader.exec_module(module)
        self.assertIsNone(module.runtime)
        self.assertTrue(module.RuntimeSeedTest.__unittest_skip__)
        self.assertFalse(getattr(module.SeccompProfileTest, '__unittest_skip__', False))

    def test_browser_profile_keeps_default_filter_and_only_adds_namespace_calls(self):
        profile = json.loads((Path(__file__).resolve().parents[2] / 'docker/seccomp-chromium.json').read_text())
        self.assertEqual(profile['defaultAction'], 'SCMP_ACT_ERRNO')
        extra = profile['syscalls'][-1]
        self.assertEqual(extra['names'], ['clone', 'setns', 'unshare'])
        self.assertEqual(extra['action'], 'SCMP_ACT_ALLOW')
        self.assertTrue(any(r['names'] == ['clone3'] and r.get('errnoRet') == 38 for r in profile['syscalls']))


@unittest.skipUnless(runtime is not None, 'Container HOME initialization requires POSIX flock')
class RuntimeSeedTest(unittest.TestCase):
    def test_existing_credentials_and_updates_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            home, seed = Path(root) / 'home', Path(root) / 'seed'
            home.mkdir(); seed.mkdir()
            (home / '.claude.json').write_text('existing-user-config')
            (seed / '.claude.json').write_text('image-config')
            (seed / '.local/bin').mkdir(parents=True)
            (seed / '.local/bin/claude').symlink_to('/home/easyread/.local/share/claude/version')
            runtime.initialize(home, seed)
            self.assertEqual((home / '.claude.json').read_text(), 'existing-user-config')
            self.assertTrue((home / '.local/bin/claude').is_symlink())
            (home / '.claude.json').write_text('updated-user-config')
            runtime.initialize(home, seed)
            self.assertEqual((home / '.claude.json').read_text(), 'updated-user-config')

    def test_app_and_terminal_can_initialize_the_same_home(self):
        with tempfile.TemporaryDirectory() as root:
            home, seed = Path(root) / 'home', Path(root) / 'seed'
            seed.mkdir(); (seed / 'binary').write_bytes(b'x' * 4096)
            with ThreadPoolExecutor(2) as pool:
                futures = [pool.submit(runtime.initialize, home, seed) for _ in range(2)]
                for result in futures:
                    result.result()
            self.assertEqual((home / 'binary').read_bytes(), b'x' * 4096)
            self.assertTrue((home / '.easyread-cli-initialized').exists())
