from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import quote

from ..app import config
from ..app import prefs
from ..app.i18n import tr


KINDS = {
    "paper": "Papers",
    "topic": "Topics",
    "concept": "Concepts",
    "question": "Questions",
    "hypothesis": "Hypotheses",
    "comparison": "05-跨論文比較",
}

# New multi-file Obsidian export layout.  The legacy folders above remain
# readable for compatibility with existing Research OS notes.
EXPORT_FOLDERS = ("01-論文分析", "02-心智圖", "03-閱讀標註", "04-論文深度剖析", "05-跨論文比較", "06-論文摘要")


def state_dir() -> Path:
    path = config.HOME / ".research-os"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings() -> dict:
    return (prefs.load().get("research") or {}).copy()


def normalize_folders(value=None) -> list[str]:
    if value is None:
        value = ["Research", "Papers"]
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")
    if not isinstance(value, (list, tuple)):
        raise ValueError(tr("索引資料夾必須是 Vault 內的相對路徑清單。"))
    result = []
    for item in value:
        raw = str(item or "").strip().replace("\\", "/")
        if not raw:
            continue
        # Check before normalization: stripping a leading slash would otherwise
        # turn an absolute path into an apparently safe vault-relative path.
        raw_parts = raw.split("/")
        if raw.startswith("/") or any(part in (".", "..") or part.startswith(".") for part in raw_parts):
            raise ValueError(tr("索引資料夾必須位於 Vault 內，且不能包含隱藏資料夾。"))
        path = PurePosixPath(raw)
        if path.is_absolute() or PureWindowsPath(raw).drive:
            raise ValueError(tr("索引資料夾必須位於 Vault 內，且不能包含隱藏資料夾。"))
        normalized = path.as_posix()
        if normalized.casefold() not in {entry.casefold() for entry in result}:
            result.append(normalized)
    return result


def index_folders() -> list[str]:
    # An old or partially saved preference may contain an empty list. Keep the
    # Research OS usable in that case and stay within its standard folders.
    return normalize_folders(settings().get("folders")) or normalize_folders(None)


def vault_path() -> Path | None:
    raw = settings().get("vault")
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def set_vault(raw: str, folders=None) -> Path:
    if not raw.strip():
        raise ValueError(tr("請選擇 Obsidian Vault 資料夾。"))
    path = Path(raw).expanduser()
    selected_folders = normalize_folders(folders)
    path.mkdir(parents=True, exist_ok=True)
    path = path.resolve(strict=True)
    if not path.is_dir():
        raise ValueError(tr("所選路徑不是資料夾。"))
    if path == config.HOME.resolve() or path == config.library_dir().resolve():
        raise ValueError(tr("請選擇 Obsidian Vault 資料夾，不可選 PaperRead 資料目錄。"))
    destinations = [contained_path(path, Path("Research") / name) for name in {*KINDS.values(), *EXPORT_FOLDERS}]
    for destination in destinations:
        destination.mkdir(parents=True, exist_ok=True)
    prefs.save({"research": {"vault": str(path), "folders": selected_folders}})
    return path


def contained_path(root: Path, path: Path) -> Path:
    """Canonical containment, including existing symlinks in uncreated destinations."""
    root = Path(root).expanduser().resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise ValueError("Path must remain inside the selected Vault")
    return candidate


def validate_vault_path(path: Path) -> Path:
    root = vault_path()
    if root is None:
        raise ValueError(tr("請先設定 Obsidian Vault 資料夾。"))
    resolved = contained_path(root, path)
    if resolved.suffix.lower() != ".md":
        raise ValueError(tr("筆記路徑必須是所選 Vault 內的 Markdown 檔案。"))
    return resolved


def open_easyread(sha256: str, block: str = "") -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        return ""
    query = f"sha256={sha256}"
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", block or ""):
        query += "&block=" + quote(block)
    return "easyread://open?" + query


def markdown_path(root: Path, kind: str, title: str, identity: str) -> Path:
    folder = KINDS.get(kind)
    if not folder:
        raise ValueError(tr("不支援的研究筆記類型。"))
    safe = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "-", title).strip(" .-")[:100] or kind.title()
    if safe.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        safe = "_" + safe
    candidate = contained_path(root, Path("Research") / folder / f"{safe}.md")
    suffix = 0
    while candidate.exists():
        suffix += 1
        candidate = contained_path(root, Path("Research") / folder / f"{safe} ({identity[:8]}-{suffix}).md")
    return candidate


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_replace(path: Path, data: bytes, *, overwrite: bool = True) -> None:
    # mkstemp reserves a different name for every concurrent writer.
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(tmp, path)
        else:
            os.link(tmp, path)  # Fail rather than replace a newly created unrelated note.
    finally:
        tmp.unlink(missing_ok=True)
