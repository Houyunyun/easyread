"""Full-image dynamic import and real BabelDOC export with a local fake API.

Run in a disposable full-image container with /opt/babeldoc/bin/python. No model
account/login or paid API is used. BabelDOC may download its public font assets.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import fitz

from easyread.weblog import snapshot


class Fixture(BaseHTTPRequestHandler):
    calls = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        text = 'Dynamic browser fixture paragraph. ' * 12
        html = '<html><head><title>Dynamic fixture</title></head><body><script>document.body.innerHTML="<article><h1>Dynamic fixture</h1><p>' + text + '</p></article>";</script></body></html>'
        data = html.encode()
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_POST(self):
        json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        Fixture.calls += 1
        result = {'choices': [{'message': {'content': '这是 Docker 部署的测试译文。'}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}
        data = json.dumps(result).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)


server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    base = f'http://127.0.0.1:{server.server_port}'
    archived, metadata, _ = snapshot.fetch(base + '/article')
    assert 'Dynamic browser fixture paragraph.' in archived
    assert '<script' not in archived
    print('PASS: Chromium executed dynamic HTML and EasyRead safely archived the rendered article', flush=True)
    if '--browser-only' in sys.argv:
        raise SystemExit(0)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        source, output = root / 'test.pdf', root / 'out'
        output.mkdir()
        doc = fitz.open()
        page = doc.new_page(width=400, height=400)
        page.insert_textbox(fitz.Rect(30, 30, 370, 300), 'A deployment test paper. This paragraph verifies the complete PDF translation pipeline with a local test model. No external model account or paid request is involved.', fontsize=12)
        doc.save(source); doc.close()
        runner = Path(snapshot.__file__).resolve().parents[1] / 'translate/babeldoc_runner.py'
        cfg = {'engine': 'openai', 'openai': {'base_url': base + '/v1', 'model': 'local-test', 'api': 'chat', 'api_key': 'synthetic-key', 'timeout': 30}}
        command = [os.environ['EASYREAD_BABELDOC_PYTHON'], str(runner), '--input', str(source), '--output', str(output), '--target', 'zh', '--mono-only']
        result = subprocess.run(command, input=json.dumps(cfg), text=True, capture_output=True, timeout=240)
        if result.returncode:
            raise AssertionError(result.stderr[-5000:] or result.stdout[-5000:])
        files = list(output.glob('*.mono.pdf'))
        assert len(files) == 1 and files[0].stat().st_size > 1000, result.stdout[-2000:]
        with fitz.open(files[0]) as translated:
            assert len(translated) == 1
            assert translated[0].get_text().strip()
        assert Fixture.calls > 0
        print('PASS: real BabelDOC layout/translation/export pipeline produced a readable PDF using only a local fake API', flush=True)
finally:
    server.shutdown(); server.server_close(); thread.join(5)
