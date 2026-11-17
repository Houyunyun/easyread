import base64
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from easyread.app import proxy
from easyread.server import http


class ProxyRedirectTest(unittest.TestCase):
    def setUp(self):
        self.received_proxy = None
        self.received_destination = None
        owner = self

        class Destination(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.received_destination = dict(self.headers)
                self.send_response(200); self.send_header('Content-Length', '2'); self.end_headers(); self.wfile.write(b'ok')

        self.destination = ThreadingHTTPServer(('127.0.0.1', 0), Destination)

        class RedirectingProxy(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.received_proxy = dict(self.headers)
                self.send_response(302)
                self.send_header('Location', f'http://127.0.0.1:{owner.destination.server_port}/final')
                self.send_header('Content-Length', '0'); self.end_headers()

        self.proxy_server = ThreadingHTTPServer(('127.0.0.1', 0), RedirectingProxy)
        self.servers = [self.destination, self.proxy_server]
        for server in self.servers:
            threading.Thread(target=server.serve_forever, daemon=True).start()
        self.saved_opener = urllib.request._opener

    def tearDown(self):
        urllib.request.install_opener(self.saved_opener)
        for server in self.servers:
            server.shutdown(); server.server_close()

    def request(self):
        return urllib.request.Request('http://upstream.invalid/start', headers={'Authorization': 'Bearer synthetic-model-key'})

    def assert_credentials_not_forwarded(self):
        expected = 'Basic ' + base64.b64encode(b'user:synthetic-secret').decode()
        self.assertEqual(self.received_proxy.get('Proxy-Authorization'), expected)
        self.assertIsNotNone(self.received_destination)
        self.assertNotIn('Proxy-Authorization', self.received_destination)
        self.assertNotIn('Authorization', self.received_destination)

    def test_explicit_context_transport_drops_credentials_on_proxy_bypass_redirect(self):
        endpoint = f'http://user:synthetic-secret@127.0.0.1:{self.proxy_server.server_port}'
        with patch.dict('os.environ', {'http_proxy': endpoint, 'no_proxy': 'localhost,127.0.0.1'}, clear=True):
            with http.urlopen(self.request(), timeout=5) as response:
                self.assertEqual(response.read(), b'ok')
        self.assert_credentials_not_forwarded()

    def test_global_opener_uses_the_same_redirect_guard(self):
        endpoint = f'http://user:synthetic-secret@127.0.0.1:{self.proxy_server.server_port}'
        with patch.dict('os.environ', {}, clear=True):
            proxy.apply({'enabled': True, 'http_proxy': endpoint, 'https_proxy': '', 'no_proxy': 'localhost,127.0.0.1'})
            with urllib.request.urlopen(self.request(), timeout=5) as response:
                self.assertEqual(response.read(), b'ok')
        self.assert_credentials_not_forwarded()

    def test_tls_proxy_endpoint_is_rejected_before_sending_authentication(self):
        with patch.dict('os.environ', {'https_proxy': 'https://user:synthetic-secret@proxy.invalid:7890'}, clear=True), patch.object(urllib.request, 'build_opener') as build:
            with self.assertRaises(ValueError):
                http.urlopen('https://model.invalid/', timeout=5)
            build.assert_not_called()
