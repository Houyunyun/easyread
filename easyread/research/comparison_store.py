"""Per-library comparison reports; accepting a report never writes to a Vault."""
from __future__ import annotations

import difflib
import json
import re
import time
from pathlib import Path
from uuid import UUID, uuid4

from ..app.i18n import tr
from ..library.store import dir_lock, read_json
from . import obsidian_export
from .language import ui_target
from .markdown import metadata, new_note
from .store import atomic_replace

FOLDER = ".paperread-comparisons"


def _folder(root: Path) -> Path:
    folder = Path(root).resolve() / FOLDER
    if folder.is_symlink():
        raise ValueError(tr("比较报告路径必须位于当前文献库内。"))
    return folder


def _path(root: Path, identity: str) -> Path:
    try:
        if str(UUID(identity)) != identity:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError(tr("提案编号格式不正确。")) from None
    path = _folder(root) / f"{identity}.json"
    if path.is_symlink():
        raise ValueError(tr("比较报告路径必须位于当前文献库内。"))
    return path


def _load(root: Path, identity: str) -> dict | None:
    try:
        report = read_json(_path(root, identity), None)
    except (json.JSONDecodeError, UnicodeError):
        raise ValueError(tr("比较报告无法读取，原始文件已保留。")) from None
    if report is not None and (not isinstance(report, dict) or report.get("id") != identity
                              or report.get("storage") != "library" or report.get("kind") != "comparison"):
        raise ValueError(tr("比较报告无法读取，原始文件已保留。"))
    return report


def _require(root: Path, identity: str) -> dict:
    report = _load(root, identity)
    if report is None:
        raise ValueError(tr("找不到这个研究提案。"))
    return report


def _write(root: Path, report: dict, *, create: bool = False) -> None:
    data = (json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    atomic_replace(_path(root, report["id"]), data, overwrite=not create)


def _diff(content: str) -> str:
    return "\n".join(difflib.unified_diff([], content.splitlines(), fromfile="/dev/null",
                                          tofile=tr("跨论文比较提案"), lineterm=""))


def _public(report: dict, *, detail: bool = True) -> dict:
    fields = ("id", "status", "kind", "title", "storage", "target", "output_target", "model", "created", "updated")
    result = {key: report.get(key) for key in fields}
    result.update(paper_count=len(report.get("sources") or []), linked_paper_count=0)
    if detail:
        result.update({key: report.get(key) for key in ("task", "diff", "sources", "usage")})
        result["content"] = metadata(report.get("after") or "")[1]
    return result


def create(root: Path, title: str, body: str, papers: list[dict], model: str, model_usage: dict,
           target: str = "") -> dict:
    identity = str(uuid4())
    title = re.sub(r"[\r\n\t]+", " ", title).strip()[:100] or tr("论文比较")
    content = new_note("comparison", title, body, {
        "source_papers": [f"sha256:{item['sha256']}" for item in papers if item.get("sha256")],
        "comparison_model": model,
    })
    now = time.time()
    report = {"id": identity, "status": "pending", "kind": "comparison", "title": title,
              "storage": "library", "target": f"{FOLDER}/{identity}.json", "output_target": target or ui_target(),
              "task": tr("比较指定的论文"), "before": "", "after": content, "base_hash": "", "diff": _diff(content),
              "sources": papers, "model": model, "usage": model_usage, "created": now, "updated": now}
    folder = _folder(root)
    folder.mkdir(parents=True, exist_ok=True)
    with dir_lock(folder):
        _write(root, report, create=True)
    return _public(report)


def get(root: Path, identity: str) -> dict | None:
    """Only an absent local report may fall back to the legacy Vault proposals."""
    report = _load(root, identity)
    return _public(report) if report is not None else None


def list_comparisons(root: Path) -> list[dict]:
    results = []
    for path in _folder(root).glob("*.json"):
        try:
            report = _load(root, path.stem)
        except (OSError, ValueError):
            continue
        if report is not None:
            results.append(_public(report, detail=False))
    return sorted(results, key=lambda item: item.get("created", 0), reverse=True)


def latest(root: Path, *, pending: bool = False) -> dict | None:
    for report in list_comparisons(root):
        if not pending or report["status"] == "pending":
            return get(root, report["id"]) if pending else report
    return None


def rename(root: Path, identity: str, title: str) -> dict:
    _require(root, identity)
    clean = re.sub(r"\s+", " ", str(title or "")).strip().strip("`*_#\"'『』「」")[:80]
    if not clean:
        raise ValueError(tr("比较名称不能为空白。"))
    with dir_lock(_folder(root)):
        report = _require(root, identity)
        report["title"] = clean
        report["after"] = re.sub(r"(?m)^(#\s+).+$", lambda match: match.group(1) + clean, report["after"], count=1)
        report["diff"] = _diff(report["after"])
        report["updated"] = time.time()
        _write(root, report)
    return _public(report)


def decide(root: Path, identity: str, accept: bool) -> dict:
    _require(root, identity)
    with dir_lock(_folder(root)):
        report = _require(root, identity)
        if report["status"] == "pending":
            report["status"] = "accepted" if accept else "rejected"
            report["updated"] = time.time()
            _write(root, report)
    return _public(report)


def export(root: Path, identity: str) -> dict:
    report = _require(root, identity)
    if report["status"] != "accepted":
        raise ValueError(tr("请先接受比较报告，再导出到 Obsidian。"))
    body = metadata(report["after"])[1]
    body = re.sub(r"(?m)^#\s+.*\n?", "", body, count=1).strip()
    return obsidian_export.export_to_vault([{
        "id": "comparison:" + report["id"], "kind": "comparison", "title": report["title"],
        "body": body, "links": [],
    }])
