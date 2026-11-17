"""Account for discovery downloads and summary workers during library migration."""
from __future__ import annotations

import threading
from collections import Counter

_LOCK = threading.Lock()
_ACTIVE = Counter()


def busy(root) -> bool:
    with _LOCK:
        return bool(_ACTIVE[str(root.resolve())])


def start(app, target, *args, name: str) -> None:
    key = str(app.lib.root.resolve())
    location = getattr(app, "location", None)
    if location:
        location.begin()
    with _LOCK:
        _ACTIVE[key] += 1

    def finish():
        with _LOCK:
            _ACTIVE[key] -= 1
            if not _ACTIVE[key]:
                del _ACTIVE[key]
        if location:
            location.end()

    def run():
        try:
            target(app, *args)
        finally:
            finish()

    try:
        threading.Thread(target=run, daemon=True, name=name).start()
    except BaseException:
        finish()
        raise
