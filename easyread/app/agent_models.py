"""Bounded, cached model discovery for Antigravity; no inference or login."""
from __future__ import annotations

import re
import subprocess
import time
from functools import lru_cache

from ..engines import agent_cli


@lru_cache(maxsize=8)
def _catalog(executable: str, bucket: int) -> tuple[tuple[str, str], ...]:
    try:
        result = subprocess.run([executable, "models"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if result.returncode:
        return ()
    models = {}
    for line in result.stdout.splitlines():
        raw, _, name = line.strip().partition("\t")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,119}", raw):
            continue
        identity = re.sub(r"-(low|medium|high|xhigh|max)$", "", raw)
        label = re.sub(r"\s*\((Low|Medium|High|XHigh|Max)\)$", "", name, flags=re.I).strip()
        models.setdefault(identity, label or identity)
    return tuple(models.items())


def antigravity(config: dict) -> dict:
    executable = agent_cli.path("agy", config)
    models = _catalog(executable, int(time.monotonic() // 300)) if executable else ()
    return {"models": [{"id": identity, "name": label} for identity, label in models],
            "default": config.get("model") or "",
            "configured_reasoning": config.get("reasoning_effort") or ""}
