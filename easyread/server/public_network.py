"""Bounded public-import HTTP transport; opt-in per worker, never process-global."""
from contextlib import contextmanager
from contextvars import ContextVar
import http.client
import ipaddress
import socket
import time
import urllib.request
from urllib.parse import urlsplit

_POLICY = ContextVar("public_import_policy", default=None)


class NetworkError(ValueError):
    """Safe, application-authored error text suitable for the public task result."""


def active():
    return _POLICY.get() is not None


@contextmanager
def importing():
    token = _POLICY.set({"deadline": time.monotonic() + 180, "requests": 0,
                         "remaining": 232 * 1024 * 1024})
    try:
        yield
    finally:
        _POLICY.reset(token)


def validate_url(url):
    try:
        p = urlsplit(url)
        if (p.scheme not in ("http", "https") or not p.hostname or p.username is not None
                or p.password is not None or p.port not in (None, 80, 443)
                or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url):
            raise ValueError()
    except ValueError:
        raise NetworkError("Only public HTTP(S) URLs on ports 80/443 without credentials are accepted") from None
    # Resolve again at connect time and connect to that exact validated address.
    addresses(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    return url


def addresses(host, port):
    try:
        found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise NetworkError("Import hostname could not be resolved") from None
    if not found or any(not ipaddress.ip_address(a[4][0]).is_global or ipaddress.ip_address(a[4][0]).is_multicast for a in found):
        raise NetworkError("Private, loopback, link-local and reserved import addresses are blocked")
    return found


def _connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **kwargs):
    policy = _POLICY.get()
    remaining = policy["deadline"] - time.monotonic()
    if remaining <= 0:
        raise NetworkError("Import deadline exceeded")
    timeout = min(float(timeout) if isinstance(timeout, (int, float)) else 15, 15, remaining)
    # No second DNS lookup after validating the addresses (DNS rebinding protection).
    last = None
    for family, kind, proto, _, sockaddr in addresses(*address):
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last = exc
            sock.close()
    raise last or OSError("Connection failed")


class _HTTP(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect


class _HTTPS(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_HTTP, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPS, req, context=self._context)


class _Guard(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _tick()
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _Response:
    def __init__(self, response):
        self.response = response
        self.headers = response.headers

    def geturl(self):
        return self.response.geturl()

    def read(self, size=-1):
        policy = _POLICY.get()
        size = min(size if size >= 0 else policy["remaining"] + 1, policy["remaining"] + 1)
        chunks = []
        while size:
            if time.monotonic() >= policy["deadline"]:
                raise NetworkError("Import deadline exceeded")
            chunk = self.response.read1(min(size, 64 * 1024))
            if not chunk:
                break
            policy["remaining"] -= len(chunk)
            if policy["remaining"] < 0:
                raise NetworkError("Import download budget exceeded")
            size -= len(chunk)
            chunks.append(chunk)
        return b"".join(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.response.close()


def _tick():
    policy = _POLICY.get()
    policy["requests"] += 1
    if policy["requests"] > 100 or time.monotonic() >= policy["deadline"]:
        raise NetworkError("Import request budget exceeded")


def urlopen(url, *args, **kwargs):
    from .http import _context
    _tick()
    target = url.full_url if isinstance(url, urllib.request.Request) else url
    validate_url(target)
    # Public imports deliberately do not inherit proxies: a proxy can resolve a
    # validated hostname differently and bypass the connection-time IP guard.
    context = kwargs.pop("context", None) or _context(None, None)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _HTTPHandler(),
                                         _HTTPSHandler(context=context), _Guard())
    return _Response(opener.open(url, *args, **kwargs))
