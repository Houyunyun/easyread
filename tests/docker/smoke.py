"""Opt-in full Docker smoke test. Use disposable easyread-check-* projects only.

Requires Python stdlib + Docker CLI on the test host. Never logs in to model
accounts or sends paid model requests. Set EASYREAD_SMOKE_PASSWORD to the
administrator password of the disposable stack, not a production credential.
"""
import argparse
import base64
import hashlib
import http.client
import json
import os
import re
import socket
import ssl
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def container(project, service):
    ids = subprocess.check_output(['docker', 'ps', '-aq', '--filter', f'label=com.docker.compose.project={project}', '--filter', f'label=com.docker.compose.service={service}'], text=True).split()
    assert len(ids) == 1, (service, ids)
    return ids[0]


def exec_python(cid, code):
    return subprocess.check_output(['docker', 'exec', cid, 'python', '-c', code], text=True)


def pdf():
    stream = b'BT /F1 12 Tf 20 250 Td (Full Docker smoke test.) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    data = b'%PDF-1.4\n'; offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(data)
    data += b'xref\n0 6\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    data += f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return data


class Client:
    def __init__(self, url, context, auth):
        self.url, self.context, self.auth = url.rstrip('/'), context, auth
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))

    def request(self, path, body=None, token=None, anonymous=False, headers=None):
        headers = dict(headers or {})
        if not anonymous:
            headers['Authorization'] = self.auth
        if token:
            headers['X-Token'] = token
        if body is not None and not isinstance(body, bytes):
            headers['Content-Type'] = 'application/json'
            body = json.dumps(body).encode()
        req = urllib.request.Request(self.url + path, data=body, headers=headers)
        try:
            with self.opener.open(req, timeout=30) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read()

    def get(self, path):
        status, data = self.request(path)
        assert status == 200, (path, status, data[:200])
        return json.loads(data)


def websocket(client, origin, authenticated=True):
    url = urlsplit(client.url)
    connection = client.context.wrap_socket(socket.create_connection((url.hostname, url.port), timeout=10), server_hostname=url.hostname)
    key = base64.b64encode(os.urandom(16)).decode()
    headers = [f'GET /ws HTTP/1.1', f'Host: {url.netloc}', 'Upgrade: websocket', 'Connection: Upgrade',
               f'Sec-WebSocket-Key: {key}', 'Sec-WebSocket-Version: 13', 'Sec-WebSocket-Protocol: tty', f'Origin: {origin}']
    if authenticated:
        headers.append('Authorization: ' + client.auth)
    connection.sendall(('\r\n'.join(headers) + '\r\n\r\n').encode())
    data = b''
    while b'\r\n\r\n' not in data:
        data += connection.recv(4096)
    head, pending = data.split(b'\r\n\r\n', 1)
    return connection, int(head.split()[1]), pending


class Frames:
    def __init__(self, connection, pending):
        self.connection, self.pending = connection, pending

    def read(self, n):
        while len(self.pending) < n:
            part = self.connection.recv(65536)
            if not part:
                raise EOFError('WebSocket closed')
            self.pending += part
        data, self.pending = self.pending[:n], self.pending[n:]
        return data

    def send(self, payload, opcode=2):
        if isinstance(payload, str):
            payload = payload.encode()
        n = len(payload)
        head = bytes([0x80 | opcode])
        head += bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack('!H', n)
        mask = os.urandom(4)
        self.connection.sendall(head + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload)))

    def receive(self):
        first, second = self.read(2); n = second & 127
        if n == 126:
            n = struct.unpack('!H', self.read(2))[0]
        elif n == 127:
            n = struct.unpack('!Q', self.read(8))[0]
        mask = self.read(4) if second & 128 else None
        payload = self.read(n)
        if mask:
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        return first & 15, payload


def check(args, reader, terminal, app_cid, terminal_cid):
    for client, path in ((reader, '/'), (reader, '/api/library'), (terminal, '/'), (terminal, '/token')):
        assert client.request(path, anonymous=True)[0] == 401
        assert client.request(path, anonymous=True, headers={'X-Remote-User': 'admin', 'X-Forwarded-User': 'admin'})[0] == 401
    assert reader.request('/api/version', headers={'Host': 'evil.example'})[0] == 403
    for authenticated, origin, expected in ((False, terminal.url, 401), (True, reader.url, 403), (True, 'https://evil.example', 403)):
        connection, status, _ = websocket(terminal, origin, authenticated)
        connection.close(); assert status == expected, (status, expected)
    print('PASS: whole-site HTTP/WS authentication, forged-header and cross-origin guards')

    status, html = reader.request('/')
    assert status == 200 and b'settings-proxy.js' in html
    assert reader.request('/web/vendor/note-libraries.js')[0] == 200
    assert reader.get('/api/config')['config']['docker_terminal']['port'] == urlsplit(terminal.url).port
    token = reader.get('/api/library')['token']
    body = pdf(); pid = hashlib.sha256(body).hexdigest()[:12]
    status, result = reader.request('/api/import?name=smoke.pdf&translate=0', body, token, headers={'Content-Type': 'application/pdf'})
    assert status == 200 and json.loads(result)['id'] == pid
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if reader.request(f'/p/{pid}/pages/page-001.webp')[0] == 200:
            break
        time.sleep(.2)
    else:
        raise AssertionError('PDF preparation timed out')
    assert reader.request(f'/p/{pid}/source.pdf')[1] == body
    assert reader.request(f'/api/p/{pid}/ops', {'client': 'docker-smoke', 'ops': [{'op': 'paper_note', 'body': 'Full Docker persistent note', 'at': '2026-11-17T00:00:00Z'}]}, token)[0] == 200
    assert reader.request('/api/prefs', {'reader': {'fontSize': 19}}, token)[0] == 200
    print('PASS: actual PDF upload/preparation/retrieval, note and preference writes')

    if args.proxy_url:
        settings = {'enabled': True, 'http_proxy': args.proxy_url, 'https_proxy': args.proxy_url, 'no_proxy': 'localhost,127.0.0.1,mock'}
        assert reader.request('/api/system-proxy', settings, token)[0] == 200
        result = json.loads(reader.request('/api/system-proxy/test', settings, token)[1])
        print('Proxy reachability:', result)
        assert result['ok'], result
        assert reader.get('/api/config')['config']['system_proxy']['enabled']
    assert reader.request('/api/system-proxy', {'enabled': True, 'http_proxy': 'not-a-url'}, token)[0] == 400

    for cid in (app_cid, terminal_cid):
        paths = exec_python(cid, "import shutil,json; print(json.dumps({x:shutil.which(x) for x in ['claude','codex','chromium']}))")
        assert all(json.loads(paths).values()), paths
    sentinel = "from pathlib import Path; h=Path.home(); [(h / n).mkdir(exist_ok=True) for n in ['.claude','.codex']]; [(h / n / '.docker-smoke').write_text('synthetic-not-a-credential') for n in ['.claude','.codex']]"
    exec_python(terminal_cid, sentinel)
    connection, status, pending = websocket(terminal, terminal.url)
    assert status == 101, status
    frames = Frames(connection, pending)
    try:
        auth_token = terminal.get('/token').get('token', '')
        frames.send(json.dumps({'AuthToken': auth_token, 'columns': 80, 'rows': 24}), 1)
        frames.send('1' + json.dumps({'columns': 100, 'rows': 40}))
        frames.send("0printf '\\nTERMINAL_READY\\n'; stty size; claude --version; codex --version\n")
        output = ''
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            opcode, payload = frames.receive()
            if opcode == 9:
                frames.send(payload, 10); continue
            if payload[:1] == b'0':
                output += payload[1:].decode('utf-8', 'replace')
            if '\r\nTERMINAL_READY\r\n' in output and '40 100' in output and 'codex-cli' in output:
                break
        else:
            raise AssertionError(output[-1500:])
        print('PASS: authenticated interactive PTY input, resize and real CLI version commands')
    finally:
        connection.close()


def verify(reader, app_cid, terminal_cid, proxy_url=""):
    pid = hashlib.sha256(pdf()).hexdigest()[:12]
    assert reader.get(f'/api/p/{pid}/part/reader')['data']['paper_note']['body'] == 'Full Docker persistent note'
    assert reader.get('/api/prefs')['reader']['fontSize'] == 19
    if proxy_url:
        settings = reader.get('/api/config')['config']['system_proxy']
        assert settings['source'] == 'settings' and settings['http_proxy'] == proxy_url
    for cid in (app_cid, terminal_cid):
        result = exec_python(cid, "from pathlib import Path; h=Path.home(); assert all((h / n / '.docker-smoke').read_text() == 'synthetic-not-a-credential' for n in ['.claude','.codex']); print('shared HOME persisted')")
        assert 'persisted' in result
    print('PASS: library, note, preferences and synthetic CLI state survived recreation')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['check', 'verify'])
    parser.add_argument('--project', required=True)
    parser.add_argument('--reader', default='https://127.0.0.1:18765')
    parser.add_argument('--terminal', default='https://127.0.0.1:18766')
    parser.add_argument('--proxy-url', default='')
    args = parser.parse_args()
    if not re.fullmatch(r'easyread-check-[a-z0-9-]+', args.project):
        parser.error('Refusing to write to a non-disposable project')
    password = os.environ['EASYREAD_SMOKE_PASSWORD']
    auth = 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()
    app_cid, term_cid, gateway_cid = (container(args.project, name) for name in ('easyread', 'terminal', 'gateway'))
    for cid in (app_cid, term_cid):
        info = json.loads(subprocess.check_output(['docker', 'inspect', cid], text=True))[0]
        assert not any(info['NetworkSettings']['Ports'].values()), 'Internal service published on host'
    with tempfile.TemporaryDirectory() as directory:
        certificate = Path(directory) / 'gateway.crt'
        subprocess.run(['docker', 'cp', gateway_cid + ':/auth/tls.crt', str(certificate)], check=True)
        context = ssl.create_default_context(cafile=str(certificate))
        reader, terminal = Client(args.reader, context, auth), Client(args.terminal, context, auth)
        if args.phase == 'check':
            check(args, reader, terminal, app_cid, term_cid)
        else:
            verify(reader, app_cid, term_cid, args.proxy_url)
