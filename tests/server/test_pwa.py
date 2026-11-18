import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from easyread.app import config
from easyread.server import pwa
from tests.server.test_access import AccessHTTPTest


class PwaHTTPTests(unittest.TestCase):
    setUp = AccessHTTPTest.setUp
    tearDown = AccessHTTPTest.tearDown
    request = AccessHTTPTest.request
    login = AccessHTTPTest.login

    def test_public_install_routes_have_no_private_data(self):
        for path in ('/manifest.webmanifest', '/sw.js', '/pwa/shell/library', '/pwa/shell/reader', '/web/pwa/icon-192.png'):
            status, headers, body = self.request('GET', path)
            self.assertEqual(status, 200, path)
            self.assertNotIn(self.app.token.encode(), body)
            self.assertNotIn(b'alpha-code', body)
            if path.endswith('webmanifest'):
                manifest = json.loads(body)
                self.assertEqual(manifest['display'], 'standalone')
                self.assertEqual(manifest['scope'], '/')
        self.assertEqual(self.request('GET', '/api/library')[0], 401)
        self.assertEqual(self.request('GET', '/api/config')[0], 401)
        self.assertEqual(self.request('GET', '/p/private/source.pdf')[0], 302)

    def test_worker_precache_is_complete_and_excludes_documents(self):
        script = pwa.worker()
        assets = json.loads(re.search(r'const ASSETS = (\[.*?\]);', script).group(1))
        self.assertIn('/web/js/common/pwa-db.js', assets)
        self.assertIn('/web/js/reader/store.js', assets)
        for url in assets:
            self.assertTrue(url.startswith('/web/'))
            self.assertTrue((config.WEB / url[5:]).is_file(), url)
            self.assertFalse(url.endswith('.pdf'))
        self.assertNotIn('/*PWA_CONFIG*/', script)
        self.assertNotIn('skipWaiting', script)
        self.assertIn('X-EasyRead-Web-Build', script)

    def test_scope_is_persistent_and_private_pages_have_build_validator(self):
        cookie = self.login()
        status, headers, _ = self.request('GET', '/', cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(headers['X-EasyRead-Web-Build'], pwa.build_id())
        _, _, body = self.request('GET', '/api/library', cookie=cookie)
        scope = json.loads(body)['library_id']
        self.assertRegex(scope, r'^[a-f0-9]{24}$')
        self.assertEqual(scope, pwa.library_id(self.app.lib))
        with tempfile.TemporaryDirectory() as folder:
            self.assertNotEqual(scope, pwa.library_id(SimpleNamespace(root=Path(folder))))
        marker = self.app.lib.root / '.pwa-id'
        marker.unlink()
        self.assertNotEqual(scope, pwa.library_id(self.app.lib))


if __name__ == '__main__':
    unittest.main()
