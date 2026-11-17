"""Persist manual Mermaid edits without changing the existing generation action."""
from __future__ import annotations

import re
from hashlib import sha256

from ..library import planning_store


def validate_mermaid(value) -> str:
    if not isinstance(value, str):
        raise ValueError("Mindmap must be Mermaid text")
    value = value.strip()
    if not re.match(r"^mindmap\b", value) or len(value) > 20000 or re.search(
        r"<\s*/?\s*(?:script|iframe|foreignObject)|javascript:|%%\{", value, re.I
    ):
        raise ValueError("Invalid Mermaid mindmap")
    return value


def save(app, pid: str, body: dict) -> dict:
    from .workspace import _mindmap_language_guide, _mindmap_source

    ws = app.lib.ws(pid)
    if not ws:
        raise ValueError("Paper not found")
    paper = ws.load("paper") or {}
    meta = paper.get("meta") or {}
    target, _ = _mindmap_language_guide(meta)
    _, source_hash = _mindmap_source(paper)
    cache_key = f"mindmap:{target}:" + sha256(source_hash.encode()).hexdigest()
    revision = body.get("revision")
    if revision is not None and (type(revision) is not int or revision < 0):
        raise ValueError("Invalid mindmap revision")
    record = planning_store.save_mindmap(app.lib.root, cache_key, {
        "mermaid": validate_mermaid(body.get("mermaid")), "paper_id": pid,
        "title": meta.get("title_zh") or meta.get("title_en") or pid,
        "target": target, "source_sha256": source_hash, "edited": True, "cached": True,
    }, revision)
    return record


def offline_snapshot(ws) -> dict:
    """Read saved research data without initializing SQLite or scheduling work."""
    import json
    import sqlite3
    from . import deep_analysis
    from .workspace import _legacy_evidence_hash, _mindmap_language_guide, _mindmap_source

    paper = ws.load("paper") or {}
    meta = paper.get("meta") or {}
    target, _ = _mindmap_language_guide(meta)
    _, source_hash = _mindmap_source(paper)
    keys = [f"mindmap:{target}:" + sha256(source_hash.encode()).hexdigest(),
            "mindmap:" + sha256(source_hash.encode()).hexdigest()]
    if not meta.get("source_sha256"):
        legacy = sha256(_legacy_evidence_hash(paper).encode()).hexdigest()
        keys.extend([f"mindmap:{target}:" + legacy, "mindmap:" + legacy])
    saved, checked = {}, None
    path = ws.root.parent / ".paperread-planning.sqlite3"
    if path.is_file():
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cache'").fetchone():
                for key in keys:
                    row = db.execute("SELECT payload_json,updated FROM cache WHERE cache_key=?", (key,)).fetchone()
                    if row:
                        saved, checked = json.loads(row[0]), row[1]
                        break
        finally:
            db.close()
    return {"mindmap": {**saved, "cached": bool(saved), "checked_at": checked, "target": target, "paper_id": ws.id, "task": None},
            "deep_analysis": deep_analysis.get_report(ws)}
