"""One-way Zotero synchronization: remember deletions without modifying Zotero."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..library.store import dir_lock, read_json, write_json_atomic

SYNC_HISTORY = ".zotero-sync.json"


def library_token(lib) -> str:
    return hashlib.sha256(str(lib.root).encode("utf-8")).hexdigest()


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def history(lib) -> set[str]:
    data = read_json(lib.root / SYNC_HISTORY, {})
    return set(data.get("sha256", [])) if isinstance(data, dict) else set()


def remember(lib, digest: str) -> None:
    with dir_lock(lib.root, name=".zotero-sync.lock"):
        seen = history(lib)
        if digest not in seen:
            write_json_atomic(lib.root / SYNC_HISTORY, {"sha256": sorted(seen | {digest})})


def deleted(lib, digest: str, seen: set[str]) -> bool:
    if lib.ws(digest[:12]):
        return False
    if digest in seen:
        return True
    for folder in (lib.root / ".trash").glob(digest[:12] + "-*"):
        paper = read_json(folder / "paper.json", {})
        if (paper.get("meta") or {}).get("source_sha256") == digest:
            return True
    return False
