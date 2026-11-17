"""Single-service smoke: use ONLY a disposable instance and synthetic access code.

python tests/docker/smoke.py http://127.0.0.1:18765
Writes a test code, opens a real PTY, rotates the code, then disables protection.
No provider login or paid model requests.
"""
import http.cookiejar
import json
import os
import select
import socket
import struct
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class Client:
    def __init__(self, base):
        self.base = base.rstrip('/')
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(self.cookies))
        self.token = ''

    def request(self, path, body=None):
        headers = {'Origin':self.base}
        if body is not None:
            headers.update({'Content-Type':'application/json', 'X-Token':self.token})
        request = urllib.request.Request(self.base+path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with self.opener.open(request,timeout=15) as r: return r.status, r.read()
        except urllib.error.HTTPError as e:
            with e: return e.code, e.read()

    def json(self, path, body=None):
        status, data = self.request(path,body)
        assert status==200,(path,status,data[:150])
        return json.loads(data)

    def ws(self,path,origin=None):
        u=urlsplit(self.base); sock=socket.create_connection((u.hostname,u.port),timeout=5)
        headers=[f'GET {path}ws HTTP/1.1',f'Host: {u.netloc}','Upgrade: websocket','Connection: Upgrade','Sec-WebSocket-Version: 13','Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==','Sec-WebSocket-Protocol: tty',f'Origin: {origin or self.base}', 'Cookie: '+'; '.join(c.name+'='+c.value for c in self.cookies)]
        sock.sendall(('\r\n'.join(headers)+'\r\n\r\n').encode())
        data=b''
        while b'\r\n\r\n' not in data:data+=sock.recv(65536)
        head,pending=data.split(b'\r\n\r\n',1)
        return sock,int(head.split()[1]),Frames(sock,pending)


class Frames:
    def __init__(self,sock,pending=b''):self.sock,self.pending=sock,pending
    def send(self,data,opcode=2):
        if isinstance(data,str):data=data.encode()
        n=len(data);mask=os.urandom(4)
        header=bytes([0x80|opcode])+(bytes([0x80|n]) if n<126 else b'\xfe'+struct.pack('!H',n))
        self.sock.sendall(header+mask+bytes(b^mask[i%4] for i,b in enumerate(data)))
    def read(self,n):
        while len(self.pending)<n:
            data=self.sock.recv(65536)
            if not data:raise EOFError()
            self.pending+=data
        data,self.pending=self.pending[:n],self.pending[n:];return data
    def receive(self):
        a,b=self.read(2);n=b&127
        if n==126:n=struct.unpack('!H',self.read(2))[0]
        if n==127:n=struct.unpack('!Q',self.read(8))[0]
        return a&15,self.read(n)


def run(base):
    owner=Client(base)
    owner.token=owner.json('/api/library')['token']
    assert owner.json('/api/access')['terminal']
    owner.json('/api/access',{'enabled':True,'code':'temporary-access-code'})
    visitor=Client(base)
    assert visitor.request('/api/library')[0]==401
    assert b'accessForm' in visitor.request('/')[1]
    assert visitor.request('/api/access/login',{'code':'wrong-code'})[0]==401
    visitor.json('/api/access/login',{'code':'temporary-access-code'})
    visitor.token=visitor.json('/api/library')['token']
    result=owner.json('/api/terminal/open',{'action':'shell'})
    path=result['url']
    assert visitor.request(path)[0]==403
    sock,status,_=owner.ws(path,'http://evil.example');sock.close();assert status==403
    sock,status,frames=owner.ws(path);assert status==101
    try:
        token=owner.json(path+'token').get('token','')
        frames.send(json.dumps({'AuthToken':token,'columns':80,'rows':24}),1)
        frames.send('1'+json.dumps({'columns':100,'rows':40}))
        frames.send("0printf '\\nINTEGRATED_OK\\n'; stty size; claude --version; codex --version\n")
        output='';deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            op,data=frames.receive()
            if op==9:frames.send(data,10);continue
            if data[:1]==b'0':output+=data[1:].decode(errors='replace')
            if 'INTEGRATED_OK' in output and '40 100' in output and 'codex-cli' in output:break
        else:raise AssertionError(output[-1500:])
        owner.json('/api/access',{'enabled':True,'code':'rotated-access-code','current_code':'temporary-access-code'})
        assert visitor.request('/api/library')[0]==401
        try:
            while True:frames.receive()
        except (EOFError,ConnectionResetError):pass
        print('PASS: code login, wrong-code rejection, same-origin PTY/resize/CLI commands, session ownership and rotation revoke')
    finally:sock.close()
    owner.json('/api/access',{'enabled':False,'current_code':'rotated-access-code'})
    assert Client(base).request('/api/library')[0]==200
    # Abrupt disconnects must not keep ttyd slots/processes alive.
    for _ in range(6):
        result=owner.json('/api/terminal/open',{'action':'shell'})
        sock,status,frames=owner.ws(result['url']);assert status==101
        frames.send(json.dumps({'AuthToken':'','columns':80,'rows':24}),1)
        sock.close()
    owner.json('/api/terminal/close',{})
    print('PASS: disabling protection takes effect; repeated raw disconnects release terminal resources')


if __name__=='__main__':
    base=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:18765'
    if urlsplit(base).port != 18765:raise SystemExit('This destructive smoke test requires disposable port 18765')
    run(base)
