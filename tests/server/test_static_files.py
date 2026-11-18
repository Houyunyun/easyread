import http.client
import io
import os
import tempfile
import threading
import unittest
from contextlib import nullcontext
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from easyread.library.library import Library
from easyread.server import server, static_files
from tests.http_support import anonymous_access


class StaticFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.web = self.root / "web"
        self.web.mkdir()
        self.script = self.web / "app.js"
        self.script.write_bytes(b"const example = 'static asset';\n")
        (self.web / "vendor").mkdir()
        (self.web / "vendor" / "test.js").write_bytes(b"// vendor\n")
        (self.web / "library.html").write_text("<html><head></head><body>Library</body></html>")
        app = SimpleNamespace(
            lib=Library(self.root / "library"), access=anonymous_access(self.root), token="test-token",
            jobs=SimpleNamespace(small_status=lambda: []),
            location=SimpleNamespace(request=lambda *args: nullcontext(), status="idle",
                                     marker=SimpleNamespace(other_device=lambda: False)))

        class Handler(server.Handler):
            def log_message(self, *args):
                pass

        Handler.app = app
        self.patches = [patch.object(server, "WEB", self.web), patch.object(server.config, "load", return_value={}),
                        patch.object(server.config, "is_first_run", return_value=False)]
        for p in self.patches:
            p.start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=5)

    def tearDown(self):
        self.conn.close()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def request(self, path="/web/app.js", method="GET", headers=None):
        self.conn.request(method, path, headers=headers or {})
        response = self.conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    def test_get_conditional_and_keepalive_have_correct_framing(self):
        code, headers, body = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(body, self.script.read_bytes())
        self.assertEqual(int(headers["Content-Length"]), len(body))
        self.assertIn("javascript", headers["Content-Type"])
        self.assertEqual(headers["Cache-Control"], "private, no-cache")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        etag = headers["ETag"]
        for validator in (etag, etag.removeprefix("W/"), '"other", ' + etag, "*"):
            with self.subTest(validator=validator):
                code, headers, body = self.request(headers={"If-None-Match": validator})
                self.assertEqual((code, body), (304, b""))
                self.assertEqual(headers["ETag"], etag)
                self.assertEqual(headers["Cache-Control"], "private, no-cache")
                self.assertNotIn("Content-Length", headers)
        self.assertEqual(self.request()[2], self.script.read_bytes())
        self.assertEqual(self.request(headers={"If-None-Match": '"unrelated"'})[0], 200)

    def test_head_has_get_headers_no_body_and_can_revalidate(self):
        _, get, _ = self.request()
        code, head, body = self.request(method="HEAD")
        self.assertEqual((code, body), (200, b""))
        for key in ("ETag", "Content-Length", "Content-Type", "Cache-Control"):
            self.assertEqual(head[key], get[key])
        self.assertEqual(self.request(method="HEAD", headers={"If-None-Match": head["ETag"]})[0], 304)
        self.assertEqual(self.request()[0], 200)

    def test_file_replacement_changes_validator_even_with_same_mtime_and_size(self):
        _, headers, _ = self.request()
        previous = self.script.stat()
        replacement = self.web / "replacement.js"
        replacement.write_bytes(self.script.read_bytes().replace(b"example", b"changed"))
        os.utime(replacement, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        replacement.replace(self.script)
        code, fresh, body = self.request(headers={"If-None-Match": headers["ETag"]})
        self.assertEqual(code, 200)
        self.assertNotEqual(fresh["ETag"], headers["ETag"])
        self.assertIn(b"changed", body)

    def test_vendor_and_query_paths_revalidate_instead_of_being_immutable(self):
        for path in ("/web/vendor/test.js", "/web/app.js?v=2"):
            code, headers, _ = self.request(path)
            self.assertEqual(code, 200)
            self.assertEqual(headers["Cache-Control"], "private, no-cache")
            self.assertEqual(self.request(path, headers={"If-None-Match": headers["ETag"]})[0], 304)

    def test_missing_and_traversal_remain_uncacheable(self):
        (self.root / "secret.txt").write_text("private")
        for path in ("/web/missing.js", "/web/../secret.txt", "/web/%2e%2e/secret.txt"):
            code, headers, body = self.request(path, headers={"If-None-Match": "*"})
            self.assertEqual(code, 404)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertNotIn("ETag", headers)
            self.assertNotIn(b"private", body)

    def test_api_and_injected_pages_keep_no_store_and_trash_uses_count(self):
        with patch.object(server.trash, "items", side_effect=AssertionError("trash metadata read")), \
                patch.object(server.trash, "count", return_value=3) as count:
            code, headers, body = self.request("/api/library", headers={"If-None-Match": "*"})
        self.assertEqual(code, 200)
        self.assertIn(b'"trash": 3', body)
        count.assert_called_once()
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("ETag", headers)
        code, headers, _ = self.request("/", headers={"If-None-Match": "*"})
        self.assertEqual(code, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("ETag", headers)

    def test_encoding_requests_remain_identity_including_q_zero(self):
        for value in ("gzip", "gzip;q=0", "gzip;q=0, *;q=1", "br, gzip;q=0.5"):
            code, headers, body = self.request(headers={"Accept-Encoding": value})
            self.assertEqual(code, 200)
            self.assertNotIn("Content-Encoding", headers)
            self.assertEqual(body, self.script.read_bytes())

    def test_head_and_304_never_read_the_file_body(self):
        with self.script.open("rb") as stream:
            etag = static_files._etag(os.fstat(stream.fileno()))
            for method, headers in (("HEAD", {}), ("GET", {"If-None-Match": etag})):
                handle = MagicMock(wraps=stream)
                handle.read.side_effect = AssertionError("body read")
                # Use a real descriptor but forbid reading it.
                with patch.object(Path, "open", return_value=handle):
                    handler = SimpleNamespace(headers=headers, command=method, close_connection=False,
                                              send_response=Mock(), send_header=Mock(), end_headers=Mock(), wfile=io.BytesIO())
                    static_files.send(handler, self.script)
                self.assertEqual(handler.wfile.getvalue(), b"")
