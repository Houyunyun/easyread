"""Read/export saved maps through HTTP while the task monitor polls and acknowledges."""
import http.client
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from easyread.research import obsidian_export, tasks
from easyread.server import server
from tests.research.test_port_safety import PortFixture


class MindmapHTTPTest(PortFixture):
    def test_completed_task_manual_edit_polling_and_export_do_not_block(self):
        class Handler(server.Handler):
            app = self.app
            def log_message(self, *args):
                pass
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        tasks.recover(self.lib.root)

        def request(path, body=None):
            c = http.client.HTTPConnection('127.0.0.1', httpd.server_port, timeout=3)
            try:
                c.request('GET' if body is None else 'POST', path,
                          body=None if body is None else json.dumps(body), headers={'X-Token': 'token'})
                r = c.getresponse()
                value = json.loads(r.read())
                self.assertEqual(r.status, 200, value)
                return value
            finally:
                c.close()

        prefix = '/api/research/v2/paper/' + self.ws.id + '/mindmap'
        with patch('easyread.chat.chat_models.engine_cfg', return_value=({'engine': 'none'}, {'id': 'test'})), \
             patch('easyread.engines.engines.run', return_value='mindmap\n  root((Generated))'):
            task = request(prefix + '/tasks', {})['task']
            deadline = time.monotonic() + 3
            while tasks.get(task['id'])['state'] not in ('completed', 'failed') and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(tasks.get(task['id'])['state'], 'completed')
        identity = request(prefix)
        saved = request(prefix + '/save', {'target': identity['target'], 'source_sha256': identity['source_sha256'], 'mermaid': 'mindmap\n  root((Edited))', 'revision': 1})
        self.assertEqual(saved['revision'], 2)

        def poll(_):
            for _ in range(3):
                request('/api/research/v1/monitor')
                request(prefix + '/tasks/' + task['id'] + '/ack', {})
                got = request(prefix)
                self.assertEqual(got['revision'], 2)
                self.assertIn('Edited', got['mermaid'])
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(poll, range(4)))
        with patch.object(obsidian_export, 'vault_path', return_value=self.vault):
            exported = request('/api/research/v2/export/obsidian', {'documents': [self.doc(body=saved['mermaid'])]})
        self.assertEqual(len(exported['written']), 1)
        self.assertIn('Edited', (self.vault / exported['written'][0]).read_text())
