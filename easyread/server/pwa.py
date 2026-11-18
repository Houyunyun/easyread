"""Public application shell, never private documents or authentication state."""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache

from ..app import config, i18n

PUBLIC = {"/sw.js", "/manifest.webmanifest", "/pwa/shell/library", "/pwa/shell/reader"}
PUBLIC.update(f"/web/pwa/icon-{size}.png" for size in (180, 192, 512))


def library_id(lib):
    # Include the resolved location: copied libraries must not share browser queues.
    return hashlib.sha256(str(lib.root.resolve()).encode()).hexdigest()[:24]


@lru_cache(maxsize=1)
def worker():
    web = config.WEB
    assets = set()
    for name in ("library.html", "reader.html"):
        assets.update(re.findall(r'(?:src|href)="(/web/[^"?#]+)"', (web / name).read_text(encoding="utf-8")))
    for folder in ("vendor", "stickers", "i18n", "pwa"):
        assets.update("/web/" + p.relative_to(web).as_posix() for p in (web / folder).rglob("*")
                      if p.is_file() and p.suffix in (".js", ".css", ".woff2", ".svg", ".png", ".webp", ".json"))
    # Shell routes are deliberately data-free; language dictionaries are bundled.
    files = sorted(assets)
    digest = hashlib.sha256()
    for url in files:
        digest.update(url.encode())
        digest.update((web / url[5:]).read_bytes())
    for name in ("reader.html", "library.html", "sw.js"):
        digest.update((web / name).read_bytes())
    script = (web / "sw.js").read_text(encoding="utf-8")
    return script.replace("/*PWA_CONFIG*/", "const BUILD = " + json.dumps(digest.hexdigest()[:16]) + ";\nconst ASSETS = " + json.dumps(files) + ";")


def get(handler, path):
    if path == "/sw.js":
        handler._send(200, worker().encode(), "text/javascript; charset=utf-8")
    elif path == "/manifest.webmanifest":
        handler._file(config.WEB / "pwa" / "manifest.webmanifest", ctype="application/manifest+json")
    elif path in ("/pwa/shell/library", "/pwa/shell/reader"):
        # No document ID, CSRF token, account state or server settings in these templates.
        page = (config.WEB / (path.rsplit("/", 1)[1] + ".html")).read_text(encoding="utf-8")
        handler._send(200, i18n.inject(page, "zh").encode(), "text/html; charset=utf-8")
    else:
        return False
    return True
