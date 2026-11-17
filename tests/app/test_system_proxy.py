import copy
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from easyread.app import config, proxy
from easyread.server import settings_api


class SystemProxyTest(unittest.TestCase):
    def test_validate_urls_and_switch(self):
        valid = {"enabled": True, "http_proxy": "http://127.0.0.1:7890", "https_proxy": "http://proxy.lan:7890", "no_proxy": "localhost,host.docker.internal"}
        self.assertEqual(proxy.validate(valid), valid)
        for value in ("socks5://localhost:7890", "https://localhost:7890", "http://localhost:99999", "http://localhost/path", "http://中文:7890", "http://localhost:7890\nX:evil"):
            with self.assertRaises(ValueError):
                proxy.validate({**valid, "http_proxy": value})
        for enabled in ("true", 1, None):
            with self.assertRaises(ValueError):
                proxy.validate({**valid, "enabled": enabled})
        with self.assertRaises(ValueError):
            proxy.validate({"enabled": True})

    def test_credentials_are_hidden_and_preserved_when_unmodified(self):
        settings = {"enabled": True, "http_proxy": "http://user:secret@proxy.lan:7890", "https_proxy": "", "no_proxy": ""}
        public = proxy.public(settings)
        self.assertNotIn("secret", str(public))
        self.assertEqual(proxy.validate(public, settings), settings)
        cfg = {**config.DEFAULTS, "system_proxy": settings}
        self.assertNotIn("user:secret", str(config.public(cfg)))

    def test_applies_both_cases_and_keeps_internal_hosts_direct(self):
        settings = {"enabled": True, "http_proxy": "http://proxy.lan:7890", "https_proxy": "http://proxy.lan:7890", "no_proxy": "myhost"}
        with patch.dict(os.environ, {"ALL_PROXY": "socks5://old:1234"}), patch.object(proxy.urllib.request, "install_opener"):
            proxy.apply(settings)
            self.assertEqual(os.environ["http_proxy"], settings["http_proxy"])
            self.assertEqual(os.environ["HTTPS_PROXY"], os.environ["https_proxy"])
            for name in ("localhost", "127.0.0.1", "gateway", "host.docker.internal", "myhost"):
                self.assertIn(name, os.environ["NO_PROXY"].split(","))
            self.assertNotIn("ALL_PROXY", os.environ)
            proxy.apply({**settings, "enabled": False})
            for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
                self.assertNotIn(name, os.environ)
            from easyread.engines import netcheck
            with patch.object(netcheck.urllib.request, "getproxies", return_value={"https": "http://system:7890"}):
                self.assertIsNone(netcheck.proxy_env())

    def test_chromium_receives_proxy_flags_not_only_environment(self):
        with patch.dict(os.environ, {"http_proxy": "http://proxy:7890", "https_proxy": "http://proxy:7890", "no_proxy": "localhost,127.0.0.1"}, clear=True):
            flags = proxy.chromium_args()
            self.assertIn("--proxy-server=http=http://proxy:7890;https=http://proxy:7890", flags)
            self.assertIn("--proxy-bypass-list=localhost;127.0.0.1", flags)
            os.environ["http_proxy"] = "http://user:password@proxy:7890"
            with self.assertRaises(ValueError):
                proxy.chromium_args()
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(proxy.chromium_args(), [])
        with patch.dict(os.environ, {"EASYREAD_SYSTEM_PROXY_CONFIGURED": "1"}, clear=True):
            self.assertEqual(proxy.chromium_args(), ["--no-proxy-server"])

    def test_unset_preserves_native_proxy_discovery_and_explicit_off_overrides_it(self):
        initial = {"HTTP_PROXY": "", "HTTPS_PROXY": "", "NO_PROXY": ""}
        native = {"http": "http://system:7890", "https": "http://system:7890"}
        with patch.dict(os.environ, {}, clear=True), patch.object(proxy, "_INITIAL", initial), patch.object(proxy.urllib.request, "getproxies", return_value=native), patch.object(proxy.urllib.request, "install_opener"):
            proxy.apply(None)
            self.assertNotIn("NO_PROXY", os.environ)
            self.assertNotIn("https_proxy", os.environ)
            self.assertTrue(proxy.public()["enabled"])
            self.assertEqual(proxy.public()["source"], "system")
            self.assertEqual(proxy.chromium_args(), [])
            from easyread.engines import netcheck
            self.assertEqual(netcheck.proxy_env()["HTTPS_PROXY"], native["https"])
            proxy.apply({"enabled": False, "http_proxy": "", "https_proxy": "", "no_proxy": ""})
            self.assertEqual(proxy.chromium_args(), ["--no-proxy-server"])
            self.assertIsNone(netcheck.proxy_env())

    def test_environment_defaults_do_not_modify_saved_model_config(self):
        with patch.object(proxy, "_INITIAL", {"HTTP_PROXY": "http://env:7890", "HTTPS_PROXY": "http://env:7890", "NO_PROXY": "example"}):
            self.assertEqual(proxy.public()["source"], "environment")
            self.assertTrue(proxy.public()["enabled"])

    def test_runtime_capability_is_not_a_secret(self):
        with patch.dict(os.environ, {"EASYREAD_TERMINAL": "1", "EASYREAD_ACCESS_CODE": "DO-NOT-EXPOSE"}):
            public = config.public(config.DEFAULTS)
            self.assertTrue(public["embedded_terminal"])
            self.assertNotIn("docker_terminal", public)
            self.assertNotIn("DO-NOT-EXPOSE", str(public))

    def test_concurrent_saves_keep_disk_and_environment_in_the_same_order(self):
        off = {"enabled": False, "http_proxy": "", "https_proxy": "", "no_proxy": ""}
        on = {**off, "enabled": True, "https_proxy": "http://proxy.lan:7890"}
        stored = {**copy.deepcopy(config.DEFAULTS), "system_proxy": off}
        entered, release, second_started = threading.Event(), threading.Event(), threading.Event()
        real_apply = proxy.apply

        def save(patch):
            stored.update(copy.deepcopy(patch))
            return copy.deepcopy(stored)

        def apply(settings):
            if settings["enabled"]:
                entered.set()
                self.assertTrue(release.wait(5))
            real_apply(settings)

        def disable():
            second_started.set()
            return settings_api.save_system_proxy(off)

        with patch.dict(os.environ, {}, clear=True), patch.object(config, "load", side_effect=lambda: copy.deepcopy(stored)), patch.object(config, "save", side_effect=save), patch.object(proxy, "apply", side_effect=apply), patch.object(proxy.urllib.request, "install_opener"), ThreadPoolExecutor(2) as pool:
            first = pool.submit(settings_api.save_system_proxy, on)
            self.assertTrue(entered.wait(5))
            second = pool.submit(disable)
            self.assertTrue(second_started.wait(5))
            self.assertFalse(second.done())
            release.set()
            first.result(5); second.result(5)
            self.assertFalse(stored["system_proxy"]["enabled"])
            self.assertNotIn("https_proxy", os.environ)

    def test_only_dedicated_proxy_route_changes_environment(self):
        settings = {"enabled": False, "http_proxy": "", "https_proxy": "", "no_proxy": ""}
        cfg = {**config.DEFAULTS, "system_proxy": settings}
        with patch.object(config, "load", return_value=cfg), patch.object(config, "save", return_value=cfg) as save, patch.object(proxy, "apply") as apply:
            settings_api.save_system_proxy(settings)
            save.assert_called_once_with({"system_proxy": settings})
            apply.assert_called_once_with(settings)
        with self.assertRaises(ValueError):
            settings_api.save_config({"system_proxy": settings})
