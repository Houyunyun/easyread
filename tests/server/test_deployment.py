import argparse
import errno
import http.client
import json
import os
import tempfile
import threading
import unittest
from email.message import Message
from unittest.mock import patch

from easyread.app import cli, config
from easyread.server import launch, network, server


class NetworkRulesTest(unittest.TestCase):
    def headers(self, *hosts):
        headers = Message()
        for host in hosts:
            headers["Host"] = host
        return headers

    def test_host_allowlist(self):
        self.assertEqual(network.allowed_hosts("0.0.0.0"), network.LOOPBACK_HOSTS)
        hosts = network.allowed_hosts("192.168.1.20", " easyread.lan,https://NAS.local:443/,*")
        self.assertTrue({"192.168.1.20", "easyread.lan", "nas.local"} <= hosts)
        self.assertNotIn("*", hosts)
        for host in ("LocalHost:8765", "127.0.0.1", "[::1]:8765", "localhost.:8765"):
            self.assertTrue(network.check_host(self.headers(host), hosts), host)
        for host in ("evil.example", "localhost/evil", "localhost@evil.example", "localhost:bad", "[::1", ""):
            self.assertFalse(network.check_host(self.headers(host), hosts), host)
        self.assertFalse(network.check_host(self.headers(), hosts))
        self.assertFalse(network.check_host(self.headers("localhost", "evil.example"), hosts))

    def test_origin_matches_authority_not_forwarded_headers(self):
        for origin in (None, "http://easyread.lan:8443", "https://easyread.lan:8443"):
            self.assertTrue(network.check_origin(origin, "easyread.lan:8443"))
        for origin in ("https://evil.example", "https://easyread.lan", "null"):
            self.assertFalse(network.check_origin(origin, "easyread.lan:8443"))


class LaunchRulesTest(unittest.TestCase):
    def test_only_implicit_local_port_conflicts_fall_back(self):
        conflict = OSError(errno.EADDRINUSE, "in use")
        with patch.object(launch, "_Server", side_effect=[conflict, "server"]) as bind:
            self.assertEqual(launch._bind("127.0.0.1", 8765, True), "server")
            self.assertEqual(bind.call_args.args[0], ("127.0.0.1", 0))
        for error, fallback in ((conflict, False), (OSError(errno.EACCES, "denied"), True)):
            with patch.object(launch, "_Server", side_effect=error) as bind:
                with self.assertRaises(OSError):
                    launch._bind("0.0.0.0", 8765, fallback)
                self.assertEqual(bind.call_count, 1)

    def test_cli_environment_defaults_and_explicit_overrides(self):
        with patch.dict(os.environ, {"EASYREAD_HOST": "0.0.0.0", "EASYREAD_PORT": "8766"}), patch.object(cli, "cmd_serve") as run:
            cli.main(["serve"])
            self.assertEqual((run.call_args.args[0].host, run.call_args.args[0].port), ("0.0.0.0", 8766))
            cli.main(["serve", "--host", "127.0.0.1", "--port", "8767"])
            self.assertEqual((run.call_args.args[0].host, run.call_args.args[0].port), ("127.0.0.1", 8767))

    def test_explicit_host_does_not_reuse_local_server(self):
        args = argparse.Namespace(port=None, host="0.0.0.0", open=False, exit_on_close=False)
        with patch.object(cli, "running_server") as running, patch.object(launch, "serve") as serve:
            cli.cmd_serve(args)
            running.assert_not_called()
            serve.assert_called_once_with(None, False, exit_on_close=False, host="0.0.0.0")


class DeploymentHTTPTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"EASYREAD_LIBRARY": self.temp.name})
        self.env.start()
        self.app = server.App(config.load())
        self.app_patch = patch.object(server.Handler, "app", self.app, create=True)
        self.host_patch = patch.object(server.Handler, "allowed_hosts", network.allowed_hosts("0.0.0.0", "easyread.lan"))
        self.app_patch.start()
        self.host_patch.start()
        self.httpd = launch._Server(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)
        self.host_patch.stop()
        self.app_patch.stop()
        self.env.stop()
        self.temp.cleanup()

    def request(self, method, path, host=None, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=5)
        try:
            conn.putrequest(method, path, skip_host=True)
            if host is not None:
                conn.putheader("Host", host)
            for key, value in (headers or {}).items():
                conn.putheader(key, value)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_local_and_configured_hosts_work(self):
        for host in ("127.0.0.1:8765", "localhost:8765", "easyread.lan:8443"):
            status, body = self.request("GET", "/api/library", host)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["token"], self.app.token)
        status, body = self.request("HEAD", "/", "easyread.lan")
        self.assertEqual((status, body), (200, b""))

    def test_rebinding_cannot_read_or_write(self):
        status, body = self.request("GET", "/api/library", "evil.example")
        self.assertEqual(status, 403)
        self.assertNotIn(self.app.token.encode(), body)
        status, _ = self.request("POST", "/api/presence/keep", "evil.example", {"X-Token": self.app.token}, b"{}")
        self.assertEqual(status, 403)
        status, _ = self.request("GET", "/api/version")
        self.assertEqual(status, 400)

    def test_writing_still_requires_token(self):
        status, _ = self.request("POST", "/api/presence/keep", "easyread.lan", body=b"{}")
        self.assertEqual(status, 403)
        status, _ = self.request("POST", "/api/presence/keep", "easyread.lan", {"X-Token": self.app.token}, b"{}")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
