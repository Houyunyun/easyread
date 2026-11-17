"""Safe, repeatable multi-file exports for an Obsidian research vault."""
from __future__ import annotations

import base64
import io
import hashlib
import json
import os
import re
import time
import zipfile
from pathlib import Path

from ..library.store import dir_lock
from .store import atomic_replace, contained_path, sha256_text, vault_path


EXPORT_FOLDERS = {
    "analysis": "01-論文分析",
    "mindmap": "02-心智圖",
    "annotations": "03-閱讀標註",
    "deep-analysis": "04-論文深度剖析",
    "comparison": "05-跨論文比較",
    "summary": "06-論文摘要",
}
MANAGED_START = "<!-- paperread:managed:start -->"
MANAGED_END = "<!-- paperread:managed:end -->"
INDEX_NAME = ".paperread-index.json"
MAX_DOCUMENTS = 32
MAX_DOCUMENT_SIZE = 2_000_000


def _index_path(root: Path) -> Path:
    return contained_path(root, Path("Research") / INDEX_NAME)


def _load_index(root: Path) -> dict:
    path = _index_path(root)
    if not path.exists():
        return {"version": 1, "documents": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("documents"), dict):
        raise ValueError("Existing research index is not a supported export index")
    return value


def _safe_title(value: str, fallback: str) -> str:
    title = re.sub(r"[\r\n\t]+", " ", str(value or ""))
    title = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "-", title).strip(" .-")
    title = re.sub(r"\s+", " ", title)
    if len(title) > 80:
        title = (title[:80].rsplit(" ", 1)[0] or title[:80]).strip(" .-")
    if not title:
        title = fallback
    if title.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        title = "_" + title
    return title


def _safe_subfolder(value: str) -> Path | None:
    """Allow safe multi-level subfolder path without accepting path traversal."""
    raw = str(value or "").strip()
    if not raw:
        return None
    parts = [p.strip() for p in re.split(r"[/\\]+", raw) if p.strip()]
    for p in parts:
        if p in {".", ".."} or not p:
            raise ValueError("匯出資料夾名稱不受支援。")  # i18n-ok: export validation message is fixed Traditional Chinese.
    safe_parts = [_safe_title(p, "Folder") for p in parts]
    return Path(*safe_parts) if safe_parts else None


def _relative(root: Path, path: Path) -> str:
    return os.path.relpath(os.path.realpath(path), os.path.realpath(root)).replace(os.sep, "/")


def _contained_file(root: Path, raw_path: str) -> Path | None:
    """Resolve an index path only when it remains inside the configured Vault."""
    if not raw_path or Path(raw_path).is_absolute():
        return None
    candidate = root / raw_path
    try:
        root_real = os.path.realpath(os.fspath(root))
        candidate_real = os.path.realpath(os.fspath(candidate))
        if os.path.normcase(os.path.commonpath([root_real, candidate_real])) != os.path.normcase(root_real):
            return None
    except ValueError:
        return None
    resolved = Path(candidate_real)
    return resolved if resolved.suffix.lower() == ".md" else None


def _read_research_id(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return ""
    match = re.search(r"(?m)^research_id:\s*[\"']?([^\"'\s]+)", text[:12000])
    return match.group(1) if match else ""


def _existing_path(root: Path, identity: str, index: dict) -> Path | None:
    entry = index.get("documents", {}).get(identity) or {}
    candidate = _contained_file(root, str(entry.get("path") or ""))
    if candidate and candidate.is_file() and _read_research_id(candidate) == identity:
        return candidate
    research = contained_path(root, Path("Research"))
    if research.is_dir():
        for path in research.rglob("*.md"):
            candidate = _contained_file(root, str(path.relative_to(root)))
            if candidate and _read_research_id(candidate) == identity:
                return candidate
    return None


def _identity(doc: dict) -> str:
    raw = str(doc.get("id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9:_-]{1,180}", raw):
        raise ValueError("匯出資料缺少有效的穩定 ID。")  # i18n-ok: export validation message is fixed Traditional Chinese.
    return raw


def _links_for(doc: dict, paths: dict[str, str]) -> list[str]:
    links = []
    for target in doc.get("links") or []:
        rel = paths.get(str(target))
        if rel:
            links.append(f"[[{Path(rel).with_suffix('').as_posix()}]]")
    return list(dict.fromkeys(links))


def _managed_body(doc: dict, paths: dict[str, str]) -> str:
    body = str(doc.get("body") or "").strip()
    title = re.sub(r"[\r\n]+", " ", str(doc.get("title") or "未命名研究筆記")).strip() or "未命名研究筆記"
    links = _links_for(doc, paths)
    parts = [f"# {title}"]
    if body:
        parts.extend(["", body])
    if links:
        parts.extend(["", "## 相關筆記", "", *[f"- {link}" for link in links]])
    return "\n".join(parts).rstrip()


def _frontmatter(doc: dict, identity: str) -> str:
    kind = str(doc.get("kind") or "analysis")
    paper_id = str(doc.get("paper_id") or "")
    title = re.sub(r"[\r\n]+", " ", str(doc.get("title") or "未命名研究筆記")).strip() or "未命名研究筆記"
    def quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    lines = ["---", f"research_id: {quote(identity)}", f"type: {quote(kind)}", 'schema_version: "2"']
    if paper_id:
        lines.append(f"paper_id: {quote(paper_id)}")
    lines.append(f"title: {quote(title)}")
    lines.extend(["---", ""])
    return "\n".join(lines)


def _render_new(doc: dict, identity: str, paths: dict[str, str]) -> str:
    return _frontmatter(doc, identity) + MANAGED_START + "\n" + _managed_body(doc, paths) + "\n" + MANAGED_END + "\n"


def _merge_existing(existing: str, generated: str) -> str | None:
    start = existing.find(MANAGED_START)
    end = existing.find(MANAGED_END, start + len(MANAGED_START)) if start >= 0 else -1
    if start < 0 or end < 0:
        return None
    managed_start = generated.find(MANAGED_START)
    managed_end = generated.find(MANAGED_END, managed_start + len(MANAGED_START))
    if managed_start < 0 or managed_end < 0:
        return None
    return existing[:start] + generated[managed_start:managed_end + len(MANAGED_END)] + existing[end + len(MANAGED_END):]


def _plan(root: Path, documents: list[dict], index: dict) -> tuple[list[dict], dict[str, str]]:
    paths: dict[str, str] = {}
    planned = []
    used = set()
    for doc in documents:
        identity = _identity(doc)
        if identity in paths:
            raise ValueError("Duplicate export document ID")
        kind = str(doc.get("kind") or "")
        if kind not in EXPORT_FOLDERS:
            raise ValueError("匯出資料類型不受支援。")  # i18n-ok: export validation message is fixed Traditional Chinese.
        body = str(doc.get("body") or "")
        if len(body.encode("utf-8")) > MAX_DOCUMENT_SIZE:
            raise ValueError("單一匯出檔案過大，請拆分後再匯出。")  # i18n-ok: export validation message is fixed Traditional Chinese.
        folder = root / "Research" / EXPORT_FOLDERS[kind]
        subfolder = _safe_subfolder(doc.get("subfolder"))
        if subfolder:
            folder /= subfolder
        filename = _safe_title(str(doc.get("filename") or doc.get("title") or ""), kind) + ".md"
        desired = contained_path(root, folder / filename)
        existing = _existing_path(root, identity, index)
        if desired.is_file() and _read_research_id(desired) == identity:
            existing = desired
        if existing:
            rel = _relative(root, existing)
        else:
            candidate = desired
            serial = 0
            while candidate.exists() or _relative(root, candidate) in used:
                serial += 1
                candidate = contained_path(root, desired.with_name(
                    desired.stem + "-" + identity.replace(":", "-")[-12:] + f"-{serial}" + desired.suffix))
            rel = _relative(root, candidate)
        if rel in used:
            raise ValueError("同一匯出中出現重複的檔案位置。")  # i18n-ok: export validation message is fixed Traditional Chinese.
        used.add(rel)
        paths[identity] = rel
        planned.append({"doc": doc, "id": identity, "path": rel, "existing": existing})
    return planned, paths


def _render(planned: list[dict], paths: dict[str, str]) -> list[dict]:
    output = []
    for item in planned:
        doc, identity = item["doc"], item["id"]
        generated = _render_new(doc, identity, paths)
        existing = item["existing"]
        current = existing.read_text(encoding="utf-8-sig") if existing else ""
        content = generated if not current else _merge_existing(current, generated)
        output.append({**item, "generated": generated, "current": current, "content": content})
    return output


def _index_payload(index: dict, rendered: list[dict]) -> dict:
    docs = dict(index.get("documents") or {})
    now = time.time()
    for item in rendered:
        doc = item["doc"]
        docs[item["id"]] = {"path": item["path"], "kind": doc.get("kind"), "title": doc.get("title") or "", "updated_at": now, "attachments": item.get("attachment_hashes", {})}
    return {"version": 1, "documents": docs}


def register_document(root: Path, identity: str, kind: str, title: str, path: str) -> None:
    """Record a note written by the proposal workflow in the shared export index."""
    if not re.fullmatch(r"[A-Za-z0-9:_-]{1,180}", str(identity or "")):
        return
    safe_path = _contained_file(root, str(path))
    if safe_path is None:
        return
    with dir_lock(root, ".paperread-export.lock"):
        _register_document(root, identity, kind, title, safe_path)


def _register_document(root, identity, kind, title, safe_path):
    index = _load_index(root)
    documents = dict(index.get("documents") or {})
    documents[str(identity)] = {"path": _relative(root, safe_path), "kind": str(kind or ""),
                                "title": str(title or ""), "updated_at": time.time()}
    destination = _index_path(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_replace(destination, (json.dumps({"version": 1, "documents": documents}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _validate_documents(value) -> list[dict]:
    if not isinstance(value, list) or not value or len(value) > MAX_DOCUMENTS:
        raise ValueError("請至少選擇一項匯出內容。")  # i18n-ok: export validation message is fixed Traditional Chinese.
    documents = [item for item in value if isinstance(item, dict)]
    if not documents:
        raise ValueError("請至少選擇一項匯出內容。")  # i18n-ok: export validation message is fixed Traditional Chinese.
    return documents


def _attachments(item: dict, root: Path) -> dict[Path, bytes]:
    doc = item["doc"]
    raw = doc.get("attachments")
    attachments = raw if isinstance(raw, list) else [doc["attachment"]] if isinstance(doc.get("attachment"), dict) else []
    if not attachments and doc.get("image_base64"):
        attachments = [{"filename": Path(item["path"]).with_suffix(".png").name, "content_base64": doc["image_base64"]}]
    result = {}
    for att in attachments:
        if not isinstance(att, dict) or not att.get("content_base64"):
            continue
        name = str(att.get("filename") or "image.png").replace("\\", "/")
        parts = name.split("/")
        if any(p in ("", ".", "..") for p in parts) or re.match(r"^[A-Za-z]:", name):
            raise ValueError("Attachment must use a relative file path")
        dest = contained_path(root, Path(item["path"]).parent / Path(*[_safe_title(p, "attachment") for p in parts]))
        # Attachments cannot overwrite notes or the shared export index.
        if dest.suffix.lower() in (".md", ".json") or dest == _index_path(root):
            raise ValueError("Attachment cannot replace a research note or index")
        raw_data = str(att["content_base64"])
        if len(raw_data) > MAX_DOCUMENT_SIZE * 4:
            raise ValueError("Attachment too large")
        data = base64.b64decode(raw_data, validate=True)
        if dest in result and result[dest] != data:
            raise ValueError("Duplicate attachment path")
        result[dest] = data
    return result


def export_to_vault(documents: list[dict]) -> dict:
    root = vault_path()
    if root is None:
        raise ValueError("請先設定 Obsidian Vault 資料夾。")  # i18n-ok
    root = Path(root).resolve()
    docs = _validate_documents(documents)
    # Preflight the index before creating even a lock in the vault.
    _index_path(root)
    with dir_lock(root, ".paperread-export.lock"):
        return _export_locked(root, docs)


def _export_locked(root: Path, docs: list[dict]) -> dict:
    index = _load_index(root)
    original_index = _index_path(root).read_bytes() if _index_path(root).exists() else None
    planned, paths = _plan(root, docs, index)
    rendered = _render(planned, paths)
    conflicts = [{"id": item["id"], "path": item["path"], "reason": "existing_note_without_managed_block"}
                 for item in rendered if item["content"] is None]
    attachments = {}
    originals = {}
    # Validate every path and attachment before any output is written.
    for item in rendered:
        old_hashes = (index.get("documents", {}).get(item["id"]) or {}).get("attachments") or {}
        item["attachment_hashes"] = {}
        for dest, data in _attachments(item, root).items():
            relative = _relative(root, dest)
            digest = hashlib.sha256(data).hexdigest()
            if dest in attachments and attachments[dest] != data:
                raise ValueError("Duplicate attachment path")
            originals[dest] = dest.read_bytes() if dest.is_file() else None
            if dest.exists() and originals[dest] != data:
                if originals[dest] is None or hashlib.sha256(originals[dest]).hexdigest() != old_hashes.get(relative):
                    conflicts.append({"id": item["id"], "path": relative, "reason": "unrelated_or_modified_attachment"})
            attachments[dest] = data
            item["attachment_hashes"][relative] = digest
    if conflicts:
        return {"written": [], "updated": [], "conflicts": conflicts, "index": _relative(root, _index_path(root))}
    written, updated = [], []
    for item in rendered:
        destination = contained_path(root, Path(item["path"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = contained_path(root, destination)
        if item["existing"] and destination.read_text(encoding="utf-8-sig") != item["current"]:
            raise ValueError("Research note changed during export; retry")
        atomic_replace(destination, item["content"].encode("utf-8"), overwrite=bool(item["existing"]))
        (updated if item["existing"] else written).append(item["path"])
    for dest, data in attachments.items():
        dest = contained_path(root, dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        current = dest.read_bytes() if dest.exists() else None
        if current != originals[dest]:
            raise ValueError("Attachment changed during export; retry")
        if current != data:
            atomic_replace(contained_path(root, dest), data, overwrite=originals[dest] is not None)
    index_path = _index_path(root)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    if (index_path.read_bytes() if index_path.exists() else None) != original_index:
        raise ValueError("Research index changed during export; retry")
    atomic_replace(index_path, (json.dumps(_index_payload(index, rendered), ensure_ascii=False, indent=2) + "\n").encode("utf-8"), overwrite=original_index is not None)
    return {"written": written, "updated": updated, "conflicts": [], "index": _relative(root, index_path)}


def export_zip(documents: list[dict]) -> dict:
    root = vault_path()
    if root is None:
        raise ValueError("請先設定 Obsidian Vault 資料夾。")  # i18n-ok: export validation message is fixed Traditional Chinese.
    docs = _validate_documents(documents)
    index = _load_index(root)
    planned, paths = _plan(root, docs, index)
    rendered = _render(planned, paths)
    index_data = _index_payload(index, rendered)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in rendered:
            if item["content"] is None:
                continue
            archive.writestr(item["path"], item["content"])
            for dest, data in _attachments(item, root).items():
                archive.writestr(_relative(root, dest), data)
        archive.writestr("Research/" + INDEX_NAME, json.dumps(index_data, ensure_ascii=False, indent=2) + "\n")
    return {"filename": "PaperRead-Research.zip", "content_base64": base64.b64encode(stream.getvalue()).decode("ascii"), "conflicts": [item["id"] for item in rendered if item["content"] is None]}
