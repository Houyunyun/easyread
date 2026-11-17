import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from easyread.app import config
from easyread.server import server, launch
from easyread.server.access import Access


class AccessTest(unittest.TestCase):
    def test_hash_storage_rotation_disable_and_restart(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'EASYREAD_ACCESS_CODE': ''}):
            path = Path(root) / '.access.json'
            access = Access(path)
            self.assertFalse(access.enabled)
            sid = access.update({'enabled': True, 'code': 'alpha-code'})
            self.assertTrue(access.valid(sid))
            self.assertNotIn('alpha-code', path.read_text())
            access.changed = changed = unittest.mock.Mock()
            with self.assertRaises(ValueError):
                access.update({'enabled': False, 'current_code': 'wrong'})
            new = access.update({'enabled': True, 'current_code': 'alpha-code', 'code': 'second-code'})
            self.assertFalse(access.valid(sid)); self.assertTrue(access.valid(new))
            changed.assert_called_once()
            restarted = Access(path)
            self.assertTrue(restarted.verify('second-code'))
            self.assertFalse(restarted.valid(new))
            restarted.update({'enabled': False, 'current_code': 'second-code'})
            self.assertFalse(Access(path).enabled)

    def test_invalid_persisted_records_fail_closed(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'EASYREAD_ACCESS_CODE': ''}):
            path = Path(root) / '.access.json'
            for value in (None, {}, {'enabled': 0}, {'enabled': True, 'salt': 'invalid', 'hash': 'invalid'}):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError): Access(path)

    def test_failed_write_preserves_live_state_and_sessions(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'EASYREAD_ACCESS_CODE': 'alpha-code'}):
            access = Access(Path(root) / '.access.json')
            sid = access.issue()
            with patch.object(access, '_save', side_effect=OSError('disk full')):
                with self.assertRaises(OSError): access.update({'enabled':False, 'current_code':'alpha-code'})
            self.assertTrue(access.enabled); self.assertTrue(access.valid(sid)); self.assertTrue(access.verify('alpha-code'))

    def test_enabling_cannot_issue_anonymous_session_after_rotation(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'EASYREAD_ACCESS_CODE': ''}):
            access = Access(Path(root) / '.access.json')
            paused, release = threading.Event(), threading.Event()
            original = access.issue
            result = {}
            def issue():
                paused.set(); self.assertTrue(release.wait(3)); return original()
            with patch.object(access, 'issue', side_effect=issue):
                thread = threading.Thread(target=lambda: result.update(admitted=access.admit({})))
                thread.start(); self.assertTrue(paused.wait(3))
                updater = threading.Thread(target=lambda: access.update({'enabled':True, 'code':'alpha-code'}))
                updater.start(); release.set(); thread.join(3); updater.join(3)
            self.assertFalse(access.valid(result['admitted'][0]))
            self.assertEqual(access.admit({}), ('', False))

    def test_bruteforce_and_session_expiry(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'EASYREAD_ACCESS_CODE': 'alpha-code'}):
            access = Access(Path(root) / '.access.json')
            for _ in range(8): self.assertEqual(access.login('wrong', 'a')[1], 401)
            self.assertEqual(access.login('alpha-code', 'a')[1], 429)
            sid, status = access.login('alpha-code', 'b')
            self.assertEqual(status, 200)
            self.assertTrue(access.valid(sid)); access.logout(sid); self.assertFalse(access.valid(sid))


class AccessHTTPTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'EASYREAD_LIBRARY': self.temp.name, 'EASYREAD_ACCESS_CODE': 'alpha-code', 'EASYREAD_TERMINAL': ''})
        self.env.start()
        self.app = server.App(config.load())
        self.app_patch = patch.object(server.Handler, 'app', self.app, create=True); self.app_patch.start()
        self.httpd = launch._Server(('127.0.0.1', 0), server.Handler)
        self.port = self.httpd.server_port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.app.terminals.close(); self.httpd.shutdown(); self.httpd.server_close()
        self.app_patch.stop(); self.env.stop(); self.temp.cleanup()

    def request(self, method, path, body=None, cookie='', token='', origin=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        headers = {'Content-Type': 'application/json'}
        if cookie: headers['Cookie'] = cookie
        if token: headers['X-Token'] = token
        if origin: headers['Origin'] = f'http://127.0.0.1:{self.port}'
        data = json.dumps(body).encode() if body is not None else None
        try:
            conn.request(method, path, data, headers)
            r = conn.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally: conn.close()

    def login(self):
        code, headers, _ = self.request('POST', '/api/access/login', {'code':'alpha-code'})
        self.assertEqual(code,200)
        self.assertNotIn('WWW-Authenticate',headers)
        self.assertIn('HttpOnly',headers['Set-Cookie']); self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        return headers['Set-Cookie'].split(';')[0]

    def test_login_page_and_api_are_gated_without_browser_basic_popup(self):
        code, headers, _ = self.request('GET','/')
        self.assertEqual(code,302); self.assertTrue(headers['Location'].startswith('/login?'))
        for path in ('/api/library','/api/config','/api/prefs','/terminal/not-real/',
                     '/api/research/v1/status','/api/research/v2/init'):
            self.assertEqual(self.request('GET',path)[0],401)
        self.assertEqual(self.request('GET','/healthz')[0],200)
        self.assertIn(b'accessForm',self.request('GET','/login')[2])
        self.assertEqual(self.request('POST','/api/access/login',{'code':'alpha-code'},origin=False)[0],403)
        cookie=self.login()
        self.assertEqual(self.request('GET','/api/library',cookie=cookie)[0],200)
        self.assertEqual(self.request('GET','/api/access',cookie=cookie)[0],200)
        self.assertEqual(self.request('GET','/research?mode=path')[0],302)
        self.assertEqual(self.request('GET','/research?mode=path',cookie=cookie)[0],200)
        self.assertEqual(self.request('GET','/api/research/v2/init',cookie=cookie)[0],200)
        body = {'title': 'Protected goal', 'start_date': '2026-11-17'}
        self.assertEqual(self.request('POST','/api/research/v2/milestones',body,cookie=cookie)[0],403)
        self.assertEqual(self.request('POST','/api/research/v2/milestones',body,cookie=cookie,token=self.app.token)[0],200)

    def test_cli_updates_are_rejected_while_research_work_is_active(self):
        cookie = self.login()
        with patch('easyread.research.tasks.busy', return_value=True), \
             patch.object(self.app.terminals, 'open') as opened:
            self.assertEqual(self.request('POST','/api/terminal/open',{'action':'codex-update'},
                                          cookie=cookie,token=self.app.token)[0],400)
            opened.assert_not_called()

    def test_rotation_revokes_other_browser_and_disabled_mode_still_requires_csrf(self):
        first,second=self.login(),self.login()
        token=self.app.token
        self.assertEqual(self.request('POST','/api/access',{'enabled':False,'current_code':'alpha-code'},cookie=first,token=token,origin=False)[0],403)
        result, headers, _=self.request('POST','/api/access',{'enabled':True,'current_code':'alpha-code','code':'next-code'},cookie=first,token=token)
        self.assertEqual(result,200)
        self.assertEqual(self.request('GET','/api/library',cookie=second)[0],401)
        self.assertEqual(self.request('GET','/api/research/v2/init',cookie=second)[0],401)
        current=headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('POST','/api/access',{'enabled':False,'current_code':'next-code'},cookie=current,token=token)[0],200)
        self.assertEqual(self.request('GET','/api/library')[0],200)
        self.assertEqual(self.request('POST','/api/terminal/open',{'action':'shell'},token=token,origin=False)[0],403)
        self.assertEqual(self.request('POST','/api/access',{'enabled':True,'code':'attacker'})[0],403)
