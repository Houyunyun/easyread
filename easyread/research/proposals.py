from __future__ import annotations

import difflib
import json
import os
import re
import time
import uuid
from pathlib import Path

from ..app import config
from ..engines import engines, usage
from ..library import library as library_module
from ..app.i18n import tr
from ..library.store import dir_lock, read_json, write_json_atomic
from . import workflows
from .language import ui_target, ui_text
from .markdown import FRONTMATTER, metadata, new_note
from .store import contained_path, atomic_replace, markdown_path, sha256_text, state_dir, vault_path


def _relative(root: Path, path: Path) -> str:
    """Return a Vault-relative POSIX path across Windows long/short spellings."""
    # Windows runners can spell the same temporary directory as either its
    # long path or an 8.3 path (for example RUNNER~1).  ``Path.relative_to``
    # compares those strings literally, so use the platform's relpath logic
    # after the path has already passed validate_vault_path().
    root_real = os.path.realpath(str(root))
    path_real = os.path.realpath(str(path))
    return os.path.relpath(path_real, root_real).replace(os.sep, "/")


def _proposal_file(identity: str) -> Path:
    if not re.fullmatch(r"[0-9a-f-]{36}", identity or ""):
        raise ValueError(tr("提案编号格式不正确。"))
    return contained_path(state_dir(), Path("proposals") / f"{identity}.json")



def _belongs_to_vault(proposal: dict) -> bool:
    root = vault_path()
    origin = proposal.get("vault_root")
    # The stored value is already canonical. Do not resolve it again: a replaced
    # directory symlink must not rebind an old proposal to a different Vault.
    return bool(root is not None and isinstance(origin, str) and Path(origin).is_absolute()
                and os.path.normcase(origin) == os.path.normcase(str(root.resolve())))


def _require_vault(proposal: dict) -> Path:
    if not proposal.get("vault_root"):
        raise ValueError(tr("旧提案没有来源 Vault，请重新生成后再审阅。"))
    if not _belongs_to_vault(proposal):
        raise ValueError(tr("此提案属于其他 Vault，请选择来源 Vault 或重新生成。"))
    return Path(proposal["vault_root"])


def _destination(root: Path, target: str) -> Path:
    path = contained_path(root, Path(target))
    if path.suffix.lower() != ".md":
        raise ValueError(tr("提案目标必须是来源 Vault 内的 Markdown 笔记"))
    return path


def list_notes() -> list[dict]:
    root = vault_path()
    if root is None:
        return []
    notes = []
    for path in root.glob("Research/**/*.md"):
        try:
            path = contained_path(root, path)
            text = path.read_text(encoding="utf-8-sig")
            meta, body = metadata(text)
            if not meta.get("research_id"):
                continue
            title = next((m.group(1).strip() for line in body.splitlines() if (m := re.match(r"^#\s+(.+)$", line))), path.stem)
            notes.append({"path": _relative(root, path), "title": title, "kind": meta.get("type", ""),
                          "id": meta.get("research_id", "")})
        except (OSError, UnicodeError, ValueError):
            continue
    return sorted(notes, key=lambda item: (item["kind"], item["title"].casefold()))


def create(title: str, kind: str, task: str, library, model: str = "", paper_id: str = "", block_id: str = "",
           target: str = "", limit: int = 10, source_context=None) -> dict:
    root = vault_path()
    if root is None:
        raise ValueError(tr("请先设定 Obsidian Vault 资料夹。"))
    if not task.strip():
        raise ValueError(tr("请描述要整理的研究内容。"))
    if kind not in workflows.KIND_GUIDANCE:
        raise ValueError(tr("不支援的研究笔记类型。"))
    title = re.sub(r"[\r\n\t]", " ", title or "").strip()[:180] or task.strip()[:100]
    found = workflows.gather(task, library, paper_id, block_id, limit)
    sources = list(found["sources"])
    # Candidate summaries and comparison drafts are useful starting context, but
    # they are not PDF evidence. Keep them explicitly labeled and hash their own
    # text without placing that digest in the PDF SHA-256 field.
    contexts = source_context if isinstance(source_context, list) else [source_context]
    for context in contexts[:5]:
        if not isinstance(context, dict):
            continue
        quote = str(context.get("text") or "").strip()[:16000]
        context_title = re.sub(r"[\r\n\t]", " ", str(context.get("title") or "")).strip()[:180]
        if not quote or not context_title:
            continue
        sources.insert(0, {
            "title": context_title,
            "section": re.sub(r"[\r\n\t]", " ", str(context.get("label") or tr("外部研究资料（非论文原文）"))).strip()[:120],
            "path": "provided-context/" + re.sub(r"[^\w.-]+", "-", str(context.get("id") or context_title))[:120],
            "kind": "provided-context", "quote": quote, "sha256": "", "content_sha256": sha256_text(quote),
            "block": "", "page": 0, "id": str(context.get("id") or "")[:180], "href": "",
        })
    sources = sources[:12]
    existing = ""
    target_path = ""
    if target:
        destination = _destination(root, target)
        if not destination.is_file():
            raise ValueError(tr("找不到要更新的 Obsidian 笔记。"))
        if destination.suffix.lower() != ".md":
            raise ValueError(tr("只能更新 Markdown 笔记。"))
        original = destination.read_text(encoding="utf-8-sig")
        meta, body = metadata(original)
        if not meta.get("research_id"):
            raise ValueError(tr("只能更新由 Research OS 建立并具有 research_id 的笔记。"))
        existing = body
        base_content = original
        target_path = _relative(root, destination)

    from ..chat import chat_models
    cfg = config.load()
    engine_cfg, selected = chat_models.engine_cfg(cfg, model or (cfg.get("chat") or {}).get("default"))
    output_target = ui_target()
    prompt = workflows._prompt(task, kind, sources, existing, target=output_target)
    meter = usage.Meter(engine_cfg.get("engine", ""))
    output = engines.run(engines.for_translation(engine_cfg), prompt, root, [], None, meter).strip()
    if not output:
        raise ValueError(tr("模型没有产生笔记内容。"))
    # Some models ignore the no-frontmatter instruction. Keep the existing user-owned
    # properties intact and use only the generated body.
    generated_meta, generated_body = metadata(output)
    body = workflows._cite_body(generated_body if generated_meta else output, sources, output_target)
    if target_path:
        match = FRONTMATTER.match(base_content)
        prefix = match.group(0) if match else ""
        next_content = prefix + "\n" + body.rstrip() + "\n"
    else:
        paper_sources = sorted({f"sha256:{item['sha256']}" for item in sources if item.get("sha256")})
        evidence = sorted({f"{item['sha256']}:{item['block']}:{sha256_text(item['quote'])}"
                           for item in sources if item.get("sha256") and item.get("block")})
        extra = {"source_papers": paper_sources, "source_evidence": evidence}
        if kind == "hypothesis":
            extra["status"] = "proposed"
        next_content = new_note(kind, title, body, extra)
        identity = re.search(r'research_id: "([^\"]+)"', next_content).group(1)
        target_path = _relative(root, markdown_path(root, kind, title, identity))
        base_content = ""

    destination = _destination(root, target_path)
    before_hash = sha256_text(base_content) if target_path and base_content else ""
    proposal = {
        "id": str(uuid.uuid4()), "status": "pending", "kind": kind, "title": title,
        "output_target": output_target, "task": task[:3000], "target": target_path, "base_hash": before_hash,
        "before": base_content, "after": next_content, "diff": "\n".join(difflib.unified_diff(
            base_content.splitlines(), next_content.splitlines(), fromfile=tr("Obsidian 现有内容") if base_content else "/dev/null",
            tofile=tr("Research OS 提案"), lineterm="")),
        "sources": sources, "model": selected.get("name") or selected.get("id"),
        "model_id": selected.get("id"), "usage": meter.snapshot(), "created": time.time(),
        "vault_relative": _relative(root, destination),
    }
    proposal["vault_root"] = str(root.resolve())
    path = _proposal_file(proposal["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, proposal)
    return _public_proposal(proposal)


def _paper_note_paths(root: Path) -> list[Path]:
    """Find exported notes across locales/moves without following paths outside the Vault."""
    from . import obsidian_export

    paths = set()
    try:
        index = obsidian_export._load_index(root)
    except (OSError, UnicodeError, ValueError):
        index = {}
    for identity, entry in (index.get("documents") or {}).items():
        if not isinstance(entry, dict) or entry.get("kind") not in ("analysis", "paper"):
            continue
        path = obsidian_export._contained_file(root, str(entry.get("path") or ""))
        if path and path.is_file() and obsidian_export._read_research_id(path) == identity:
            paths.add(path)
    # Also retain discovery of pre-index Research OS and legacy exports.
    folders = {"Papers", "01-论文分析", "01-論文分析"}  # i18n-ok: legacy folder names
    folders.update(ui_text("01-论文分析", locale) for locale in ("zh", "en", "zh-Hant"))
    for folder in folders:
        try:
            directory = contained_path(root, Path("Research") / folder)
            if directory.is_dir():
                paths.update(directory.rglob("*.md"))
        except (OSError, ValueError):
            continue
    return sorted(paths)


def from_comparison(title: str, body: str, papers: list[dict], model: str, model_usage: dict, target: str = "") -> dict:
    """Stage a new comparison note; only decide() may write it to the Vault."""
    root = vault_path()
    if root is None:
        raise ValueError(tr("请先设定 Obsidian Vault 资料夹。"))
    output_target = target or ui_target()
    paper_links = []
    def normalize(value: str) -> str:
        return " ".join(value.casefold().split())

    for note in _paper_note_paths(root):
        try:
            note = contained_path(root, note)
            text = note.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError, ValueError):
            continue
        meta, note_body = metadata(text)
        note_title = next((match.group(1).strip() for line in note_body.splitlines()
                           if (match := re.match(r"^#\s+(.+)$", line))), note.stem)
        is_paper_note = meta.get("type") in ("paper", "analysis")
        linked_by_id = is_paper_note and any(
            item.get("id") and item["id"] == meta.get("paper_id") for item in papers)
        linked_by_hash = is_paper_note and any(
            item.get("sha256") and item["sha256"] in text for item in papers)
        linked_by_title = any(normalize(note_title) in {
            normalize(item.get("title") or ""), normalize(item.get("title_en") or ""),
            normalize(item.get("title_zh") or ""),
        } - {""} for item in papers)
        if linked_by_id or linked_by_hash or linked_by_title:
            paper_links.append(f"- [[{Path(_relative(root, note)).with_suffix('').as_posix()}]]")
    if paper_links:
        body = body.rstrip() + ui_text("\n\n## 相关单篇笔记\n\n", output_target) + "\n".join(sorted(set(paper_links)))
    title = re.sub(r"[\r\n\t]", " ", title).strip()[:100] or tr("论文比较")
    extra = {"source_papers": [f"sha256:{item['sha256']}" for item in papers if item.get("sha256")],
             "comparison_model": model}
    content = new_note("comparison", title, body, extra)
    identity = re.search(r'research_id: "([^\"]+)"', content).group(1)
    destination = markdown_path(root, "comparison", title, identity)
    target = _relative(root, destination)
    proposal = {"id": str(uuid.uuid4()), "status": "pending", "kind": "comparison", "title": title,
                "output_target": output_target, "task": tr("比较指定的论文"), "target": target, "base_hash": "", "before": "", "after": content,
                "diff": "\n".join(difflib.unified_diff([], content.splitlines(), fromfile="/dev/null",
                                                    tofile=tr("Obsidian 比较笔记提案"), lineterm="")),
                "sources": papers, "linked_paper_count": len(set(paper_links)), "model": model, "usage": model_usage, "created": time.time(),
                "vault_relative": target}
    proposal["vault_root"] = str(root.resolve())
    path = _proposal_file(proposal["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, proposal)
    return _public_proposal(proposal)


def from_topic_matrix(topic_path: str, row: dict, model: str, model_usage: dict) -> dict:
    """Stage a single matrix-row patch while preserving every byte outside its managed region."""
    root = vault_path()
    if root is None:
        raise ValueError(tr("请先设定 Obsidian Vault 资料夹。"))
    destination = _destination(root, topic_path)
    if not destination.is_file():
        raise ValueError(tr("找不到要加入矩阵的主题笔记。"))
    before = destination.read_text(encoding="utf-8-sig")
    meta, body = metadata(before)
    if meta.get("type") != "topic" or not meta.get("research_id"):
        raise ValueError(tr("只能更新 Research OS 建立的 Topic 笔记。"))

    start = "<!-- research-os:topic-matrix:start -->"
    end = "<!-- research-os:topic-matrix:end -->"
    has_start, has_end = start in body, end in body
    if has_start != has_end:
        raise ValueError(tr("主题矩阵标记不完整，请先修复或移除标记后再试。"))
    headers = [tr(x) for x in ("论文", "研究问题", "方法与核心机制", "输入与输出", "实验证据与条件", "限制", "我的判断")]
    row_cells = row.get("cells") or {}
    paper_hash = str(row.get("sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", paper_hash):
        raise ValueError(tr("矩阵列缺少有效的论文 SHA-256。"))

    def render_row(judgment: str | None = None) -> str:
        values = [row_cells.get("title", ""), row_cells.get("problem", tr("未报告")), row_cells.get("method", tr("未报告")),
                  row_cells.get("io", tr("未报告")), row_cells.get("evidence", tr("未报告")), row_cells.get("limitations", tr("未报告")),
                  judgment if judgment is not None else row_cells.get("judgment", tr("待自行补充"))]
        values[-1] = (values[-1] or tr("待自行补充")) + f" <!-- research-os:paper-sha256:{paper_hash} -->"
        return "| " + " | ".join(str(value).replace("\r", " ").replace("\n", " ") for value in values) + " |"

    candidate_row = render_row()
    if has_start:
        left, rest = body.split(start, 1)
        managed, right = rest.split(end, 1)
        existing_row = next((line for line in managed.splitlines()
                             if f"research-os:paper-sha256:{paper_hash}" in line), "")
        if existing_row:
            cells = re.split(r"(?<!\\)\|", existing_row.strip().strip("|"))
            previous_judgment = cells[6].strip() if len(cells) >= 7 else tr("待自行补充")
            previous_judgment = re.sub(r"\s*<!--\s*research-os:paper-sha256:[0-9a-f]{64}\s*-->\s*", "", previous_judgment)
            candidate_row = render_row(previous_judgment or tr("待自行补充"))
            managed_lines = [line for line in managed.splitlines() if line != existing_row]
            managed = "\n".join(managed_lines).strip("\n")
        if not managed.strip():
            managed = "\n" + "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |"
        if candidate_row not in managed:
            managed = managed.rstrip() + "\n" + candidate_row
        after_body = left + start + "\n\n" + managed.strip("\r\n") + "\n\n" + end + right
    else:
        table = (tr("\n\n## 主题研究矩阵\n\n") + start + "\n\n| " + " | ".join(headers) + " |\n| " +
                 " | ".join("---" for _ in headers) + " |\n" + candidate_row + "\n\n" + end + "\n")
        after_body = body.rstrip() + table
    match = FRONTMATTER.match(before)
    prefix = match.group(0) if match else ""
    after = prefix + after_body
    if not after.endswith("\n"):
        after += "\n"
    relative = _relative(root, destination)
    proposal = {
        "id": str(uuid.uuid4()), "status": "pending", "kind": "matrix", "title": row.get("title") or tr("主题研究矩阵"),
        "task": tr("将一篇论文加入主题研究矩阵"), "target": relative, "base_hash": sha256_text(before),
        "before": before, "after": after,
        "diff": "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(),
                                                   fromfile=tr("Obsidian 主题笔记"), tofile=tr("主题矩阵提案"), lineterm="")),
        "sources": [{"title": row.get("title", ""), "sha256": paper_hash}], "model": model,
        "usage": model_usage, "created": time.time(), "vault_relative": relative,
    }
    proposal["vault_root"] = str(root.resolve())
    path = _proposal_file(proposal["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, proposal)
    return _public_proposal(proposal)


def create_topic(title: str) -> dict:
    """Stage an empty, user-editable topic note without inventing research claims."""
    root = vault_path()
    if root is None:
        raise ValueError(tr("请先设定 Obsidian Vault 资料夹。"))
    if latest_pending_topic():
        raise ValueError(tr("请先审阅或舍弃目前的新 Topic 提案。"))
    title = re.sub(r"[\r\n\t]", " ", str(title or "")).strip()[:120]
    if not title:
        raise ValueError(tr("请输入主题名称。"))
    sections = (tr("主题范围"), tr("研究方法族群"), tr("代表论文"), tr("共识与争议"), tr("开放问题"))
    headers = [tr(x) for x in ("论文", "研究问题", "方法与核心机制", "输入与输出", "实验证据与条件", "限制", "我的判断")]
    body = "".join(f"## {section}\n\n{tr('待补充。')}\n\n" for section in sections)
    body += ("## " + tr("主题研究矩阵") + "\n\n<!-- research-os:topic-matrix:start -->\n\n| "
             + " | ".join(headers) + " |\n| --- | --- | --- | --- | --- | --- | --- |\n"
             "\n<!-- research-os:topic-matrix:end -->\n")
    content = new_note("topic", title, body)
    identity = re.search(r'research_id: "([^\"]+)"', content).group(1)
    destination = markdown_path(root, "topic", title, identity)
    relative = _relative(root, destination)
    proposal = {"id": str(uuid.uuid4()), "status": "pending", "kind": "topic", "title": title,
                "task": tr("建立空白 Topic 笔记范本"), "target": relative, "base_hash": "", "before": "",
                "after": content, "diff": "\n".join(difflib.unified_diff([], content.splitlines(),
                    fromfile="/dev/null", tofile=tr("Obsidian Topic 笔记提案"), lineterm="")),
                "sources": [], "model": "", "usage": {}, "created": time.time(), "vault_relative": relative}
    proposal["vault_root"] = str(root.resolve())
    path = _proposal_file(proposal["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, proposal)
    return _public_proposal(proposal)


def _public_proposal(proposal: dict) -> dict:
    result = {key: proposal.get(key) for key in ("id", "status", "kind", "title", "task", "target", "output_target", "diff", "sources", "model", "usage", "conflict")}
    if proposal.get("kind") == "comparison":
        sources = proposal.get("sources") or []
        linked = proposal.get("linked_paper_count")
        if not isinstance(linked, int):
            body = str(proposal.get("after") or "")
            linked_section = body.split("## 相关单篇笔记", 1)[1] if "## 相关单篇笔记" in body else ""
            linked = len(re.findall(r"(?m)^-\s+\[\[[^\]]+\]\]", linked_section))
        result["paper_count"] = len(sources)
        result["linked_paper_count"] = linked
    if proposal.get("kind") in ("paper", "question", "hypothesis", "comparison", "matrix", "topic"):
        result["content"] = metadata(proposal.get("after") or "")[1]
    return result


def get(identity: str) -> dict:
    proposal = read_json(_proposal_file(identity), None)
    if not proposal:
        raise ValueError(tr("找不到这个研究提案。"))
    _require_vault(proposal)
    return _public_proposal(proposal)


def latest_pending_comparison() -> dict | None:
    return _latest_pending("comparison")


def latest_comparison() -> dict | None:
    """Return a small reference to the newest comparison proposal for status polling."""
    folder = state_dir() / "proposals"
    if not folder.is_dir():
        return None
    candidates = []
    for path in folder.glob("*.json"):
        proposal = read_json(path, None)
        if proposal and _belongs_to_vault(proposal) and proposal.get("kind") == "comparison":
            candidates.append(proposal)
    if not candidates:
        return None
    latest = max(candidates, key=lambda item: item.get("created", 0))
    return {key: latest.get(key) for key in ("id", "status", "title", "created", "output_target")}


def list_comparisons() -> list[dict]:
    """Return saved comparison results for the dedicated research view."""
    folder = state_dir() / "proposals"
    if not folder.is_dir():
        return []
    results = []
    for path in folder.glob("*.json"):
        proposal = read_json(path, None)
        if not proposal or not _belongs_to_vault(proposal) or proposal.get("kind") != "comparison":
            continue
        # The list view only needs card metadata.  Returning the full Markdown
        # and evidence diff here makes the research workspace unnecessarily
        # heavy; the detail endpoint loads the proposal when requested.
        results.append({
            "id": proposal.get("id"),
            "kind": "comparison",
            "output_target": proposal.get("output_target", ""),
            "status": proposal.get("status"),
            "title": proposal.get("title") or tr("论文比较"),
            "model": proposal.get("model"),
            "created": proposal.get("created", 0),
            "paper_count": len(proposal.get("sources") or []),
        })
    return sorted(results, key=lambda item: item.get("created", 0), reverse=True)


def latest_pending_matrix() -> dict | None:
    return _latest_pending("matrix")


def latest_pending_topic() -> dict | None:
    return _latest_pending("topic")


def _latest_pending(kind: str) -> dict | None:
    folder = state_dir() / "proposals"
    if not folder.is_dir():
        return None
    candidates = []
    for path in folder.glob("*.json"):
        proposal = read_json(path, None)
        if proposal and _belongs_to_vault(proposal) and proposal.get("kind") == kind and proposal.get("status") == "pending":
            candidates.append(proposal)
    return _public_proposal(max(candidates, key=lambda item: item.get("created", 0))) if candidates else None


def rename(identity: str, title: str) -> dict:
    """Rename a comparison proposal without changing its Markdown content."""
    path = _proposal_file(identity)
    proposal = read_json(path, None)
    if not proposal:
        raise ValueError(tr("找不到这个研究提案。"))
    _require_vault(proposal)
    if proposal.get("kind") != "comparison":
        raise ValueError(tr("只有跨论文比较结果可以修改名称。"))
    clean = re.sub(r"[\r\n\t]+", " ", str(title or ""))
    clean = re.sub(r"\s+", " ", clean).strip().strip("`*_#\"'『』「」")[:80]
    if not clean:
        raise ValueError(tr("比较名称不能为空白。"))
    proposal["title"] = clean
    # Pending proposals have not been written to Obsidian yet, so keep their
    # Markdown heading and review diff in sync with the edited display name.
    if proposal.get("status") == "pending" and proposal.get("after"):
        after = re.sub(r"(?m)^(#\s+).+$", lambda match: match.group(1) + clean, proposal["after"], count=1)
        proposal["after"] = after
        proposal["diff"] = "\n".join(difflib.unified_diff(
            (proposal.get("before") or "").splitlines(), after.splitlines(),
            fromfile=tr("Obsidian 现有内容") if proposal.get("before") else "/dev/null",
            tofile=tr("Research OS 提案"), lineterm=""))
    write_json_atomic(path, proposal)
    return _public_proposal(proposal)


def decide(identity: str, accept: bool) -> dict:
    path = _proposal_file(identity)
    proposal = read_json(path, None)
    if not proposal:
        raise ValueError(tr("找不到这个研究提案。"))
    # Legacy proposals may be discarded explicitly, but never rebound on accept.
    root = _require_vault(proposal) if accept or proposal.get("vault_root") else None
    if proposal.get("status") != "pending":
        return _public_proposal(proposal)
    if not accept:
        proposal["status"] = "rejected"
        write_json_atomic(path, proposal)
        return _public_proposal(proposal)

    destination = _destination(root, proposal["target"])
    with dir_lock(root, ".paperread-export.lock", timeout=15):
        destination = _destination(root, str(destination))
        exists = destination.exists()
        current = destination.read_text(encoding="utf-8-sig") if exists else ""
        current_hash = sha256_text(current) if exists else ""
        stale = current_hash != proposal.get("base_hash", "")
        if stale:
            proposal["status"] = "conflict"
            proposal["conflict"] = True
            proposal["latest_diff"] = "\n".join(difflib.unified_diff(
                proposal.get("before", "").splitlines(), current.splitlines(), fromfile=tr("审阅时的基准"), tofile=tr("Obsidian 目前内容"), lineterm=""))
            write_json_atomic(path, proposal)
            return {**_public_proposal(proposal), "conflict": True,
                    "error": tr("审阅期间笔记已变更，没有套用这份提案。请重新建立提案，再检查新的差异。")}

        if exists:
            backup_dir = contained_path(state_dir(), Path("backups") / identity)
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f"{int(time.time())}-{destination.name}"
            backup.write_bytes(destination.read_bytes())
            proposal["backup"] = str(backup)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
        # Repeat the content check immediately before replacing the note. If it changed
        # after the backup was made, retain both versions and ask for another review.
        latest = destination.read_text(encoding="utf-8-sig") if destination.exists() else ""
        if (sha256_text(latest) if latest else "") != proposal.get("base_hash", ""):
            proposal["status"] = "conflict"
            proposal["conflict"] = True
            write_json_atomic(path, proposal)
            return {**_public_proposal(proposal), "conflict": True,
                    "error": tr("Obsidian 笔记在储存前又有变更，请重新检查差异。")}
        _require_vault(proposal)
        atomic_replace(_destination(root, str(destination)), proposal["after"].encode("utf-8"), overwrite=exists)
        proposal["status"] = "accepted"
        proposal["accepted_at"] = time.time()
        proposal["written_path"] = _relative(root, destination)
        write_json_atomic(path, proposal)
    from . import index
    from . import obsidian_export
    generated_meta, _ = metadata(proposal.get("after") or "")
    obsidian_export.register_document(root, str(generated_meta.get("research_id") or ""),
                                     str(generated_meta.get("type") or proposal.get("kind") or ""),
                                     str(proposal.get("title") or ""), str(proposal.get("written_path") or ""))
    try:
        index.index_vault(rebuild=False)
    except Exception:  # Keep the accepted note even if the derived index is unavailable.
        pass
    return {**_public_proposal(proposal), "path": proposal.get("written_path"), "backup": proposal.get("backup")}
