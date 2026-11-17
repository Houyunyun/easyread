"""HTTPS with system trust and bundled roots, including in frozen builds."""
from __future__ import annotations

import os
import ssl
import urllib.request
from urllib.parse import urlsplit
from functools import lru_cache

import certifi
import truststore


@lru_cache(maxsize=4)
def _context(cafile: str | None, capath: str | None):
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Native trust handles macOS Keychain / Windows roots; certifi also makes
    # Linux and PyInstaller builds independent of build-machine CA paths.
    context.load_verify_locations(cafile=certifi.where())
    if cafile or capath:
        context.load_verify_locations(cafile=cafile or None, capath=capath or None)
    return context


class SafeProxyHandler(urllib.request.ProxyHandler):
    def proxy_open(self, request, endpoint, protocol):
        if "://" in endpoint and urlsplit(endpoint).scheme != "http":
            raise ValueError("Use an http:// CONNECT proxy; TLS-to-proxy transport is not supported")
        return super().proxy_open(request, endpoint, protocol)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        redirected = super().redirect_request(request, response, code, message, headers, new_url)
        if redirected is None:
            return None
        old, new = urlsplit(request.full_url), urlsplit(new_url)
        cross_origin = (old.scheme, old.netloc.lower()) != (new.scheme, new.netloc.lower())
        for name, _ in list(redirected.header_items()):
            if name.lower() == "proxy-authorization" or (cross_origin and name.lower() in ("authorization", "cookie")):
                redirected.remove_header(name)
        return redirected


def urlopen(url, *args, **kwargs):
    # Always use the redirect guard, including calls with an explicit context.
    target = url.full_url if isinstance(url, urllib.request.Request) else url
    parsed = urlsplit(target)
    if parsed.hostname and not urllib.request.proxy_bypass(parsed.hostname):
        endpoint = urllib.request.getproxies().get(parsed.scheme)
        if endpoint and "://" in endpoint and urlsplit(endpoint).scheme != "http":
            raise ValueError("Use an http:// CONNECT proxy; TLS-to-proxy transport is not supported")
    context = kwargs.pop("context", None) or _context(os.environ.get("SSL_CERT_FILE"), os.environ.get("SSL_CERT_DIR"))
    opener = urllib.request.build_opener(SafeProxyHandler(), SafeRedirectHandler(), urllib.request.HTTPSHandler(context=context))
    return opener.open(url, *args, **kwargs)
