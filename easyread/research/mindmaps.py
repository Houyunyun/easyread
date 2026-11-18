"""Persist manual Mermaid edits without changing the existing generation action."""
from __future__ import annotations

from ..app.i18n import tr

import re
from hashlib import sha256

from ..library import planning_store


def validate_mermaid(value) -> str:
    if not isinstance(value, str):
        raise ValueError(tr("心智图必须是 Mermaid 文本"))
    value = value.strip()
    if not re.match(r"^mindmap\b", value) or len(value) > 20000 or re.search(
        r"<\s*/?\s*(?:script|iframe|foreignObject)|javascript:|%%\{", value, re.I
    ):
        raise ValueError(tr("Mermaid 心智图无效"))
    return value


def save(app, pid: str, body: dict) -> dict:
    from .workspace import _mindmap_language_guide, _mindmap_source

    ws = app.lib.ws(pid)
    if not ws:
        raise ValueError(tr("找不到这篇论文。"))
    paper = ws.load("paper") or {}
    meta = paper.get("meta") or {}
    target, _ = _mindmap_language_guide(meta)
    _, source_hash = _mindmap_source(paper)
    requested_target, requested_source = body.get("target"), body.get("source_sha256")
    if (not isinstance(requested_target, str) or not requested_target
            or not isinstance(requested_source, str) or not requested_source):
        raise ValueError(tr("心智图缺少语言或来源标识，请重新载入后编辑。"))
    if requested_target != target:
        raise ValueError(tr("心智图语言已变更，请重新载入后编辑。"))
    if requested_source != source_hash:
        raise ValueError(tr("心智图来源已变更，请重新载入后编辑。"))
    cache_key = f"mindmap:{target}:" + sha256(source_hash.encode()).hexdigest()
    revision = body.get("revision")
    if revision is not None and (type(revision) is not int or revision < 0):
        raise ValueError(tr("心智图版本无效"))
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
    from .workspace import _mindmap_language_guide, _mindmap_source

    paper = ws.load("paper") or {}
    meta = paper.get("meta") or {}
    target, _ = _mindmap_language_guide(meta)
    _, source_hash = _mindmap_source(paper)
    keys = [f"mindmap:{target}:" + sha256(source_hash.encode()).hexdigest()]
    saved, checked = {}, None
    path = ws.root.parent / ".paperread-planning.sqlite3"
    if path.is_file():
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cache'").fetchone():
                for key in keys:
                    row = db.execute("SELECT payload_json,updated FROM cache WHERE cache_key=?", (key,)).fetchone()
                    if row:
                        value = json.loads(row[0])
                        if value.get("target") == target and value.get("source_sha256") == source_hash:
                            saved, checked = value, row[1]
                            break
        finally:
            db.close()
    return {"mindmap": {**saved, "cached": bool(saved), "checked_at": checked, "target": target,
                        "source_sha256": source_hash, "paper_id": ws.id, "task": None},
            "deep_analysis": deep_analysis.get_report(ws)}
