"""Conditional responses for packaged /web assets, not API or paper data."""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path


CACHE_CONTROL = "private, no-cache"


def _etag(st: os.stat_result) -> str:
    # Metadata validators are weak: they do not claim byte-for-byte identity.
    return 'W/"' + "-".join(format(value, "x") for value in (
        st.st_dev, st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size,
    )) + '"'


def _matches(value: str, etag: str) -> bool:
    return any(tag.strip() == "*" or tag.strip().removeprefix("W/") == etag.removeprefix("W/")
               for tag in value.split(","))


def send(handler, path: Path | None) -> None:
    if path is None:
        return handler._json(404, {"error": "not found"})
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype.endswith("javascript"):
        ctype += "; charset=utf-8"
    # Stat/read the same opened file so atomic upgrades cannot mix validators
    # from one version with bytes from its replacement. No body read for 304/HEAD.
    try:
        stream = path.open("rb")
    except FileNotFoundError:
        return handler._json(404, {"error": "not found"})
    with stream:
        st = os.fstat(stream.fileno())
        etag = _etag(st)
        unchanged = _matches(handler.headers.get("If-None-Match", ""), etag)
        body = None if unchanged or handler.command == "HEAD" else stream.read()
    handler.send_response(304 if unchanged else 200)
    handler.send_header("ETag", etag)
    # Names (including vendor files) are mutable across upgrades: always
    # revalidate rather than serving an old script alongside new HTML.
    handler.send_header("Cache-Control", CACHE_CONTROL)
    if not unchanged:
        handler.send_header("Content-Type", ctype)
        handler.send_header("Content-Length", str(st.st_size if body is None else len(body)))
    if handler.close_connection:
        handler.send_header("Connection", "close")
    handler.end_headers()
    if body is not None:
        handler.wfile.write(body)
