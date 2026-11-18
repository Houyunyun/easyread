"""Technical deep audit / X-Ray analysis for library papers."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..chat import chat_models
from ..app import config
from ..engines import engines
from ..engines import usage
from ..app.i18n import tr
from ..library.store import write_json_atomic
from . import tasks, obsidian_export
from .language import output_rule
from ..translate import langs

MAX_TEXT_CHARS = 48000


def _safe_report(report, phase: str, done: int, total: int, message: str, **kwargs):
    try:
        report(phase, done, total, message, **kwargs)
    except TypeError:
        report(phase, done, total, message)


def build_audit_prompt(meta: dict | None, text: str = "", focus: str = "") -> str:
    lang_rule = "1. " + output_rule(langs.reply_code(meta))

    base = f"""你是一位具备顶尖同行评审（Senior Peer Reviewer / Area Chair）标准的学术技术审计员。
你的任务是对以下论文进行客观、深度、技术性的全面审查与剖析。

【核心原则】
{lang_rule}
2. 秉持「严谨批判、不讲客套」的态度，拒绝空泛的赞美或套话；严格区分作者声称（Claim）与论文实证（Evidence）。若论文缺乏实质证据或推论跳跃，必须直接指明。
3. 数学公式：行内公式一律使用 $TeX$，独立行间公式一律使用 $$TeX$$ 并单独成行。不要使用 \\( \\) 或 \\[ \\]。公式内部保持干净，多行推导使用 aligned。
4. 引用位置：提及原文依据时标注章节名或页码（如「第 3.2 节」「第 5 页表 2」），不要凭空捏造。若正文未提供某项资讯，明确注记「论文未报告」。

【报告结构】请严格依照以下 5 大维度展开详细剖析，使用二级标题（##）：

## 1. 核心假说与实证对齐
- 精确提炼作者在摘要与引言中提出的 1~3 项核心假说（Core Claims）与方法创新点。
- 逐一对照正文论证与实验结果，评估每项主张的实证支持强度（「充分支持」、「部分支持」或「存在推论跳跃」）。
- 指出作者是否有论述过于宽泛、宣传性评价或未经直接实验检验之处。

## 2. 消融实验审计 (Ablation Audit)
- 核心架构机制 vs 辅助性技巧 (Engineering Tricks) 贡献拆解：这篇论文的核心架构到底带来了多少增益？哪些提升其实来自于资料增强、学习率调度、正规化等次要工程技巧？
- 关键组件敏感度：拿掉关键设计（如移除特定 Attention、特定 Loss 权重）后性能如何变化？列出关键数据。
- 对照组缺陷：审查作者是否缺少「应该做却没做」的控制组（Control Group）或消融对照？

## 3. 关键公式微型推导与数值示范 (Formula & Toy Example)
- 挑选本文最关键的 1~2 个核心数学公式，说明每个变数、运算子与张量形状（Tensor Dimensions）的物理或统计意涵。
- 提供一组可手算的微型数值示例 (Toy Example)：设定极简的具体数值（例如 2 个维度或 2 个 token 的小向量/小矩阵），一步步手算展示前向计算过程与每一步中间值，直至算出最终数值。明确标记这是教学示范，让读者看懂底层计算细节。

## 4. 实验条件、基线公平性与资料审查
- 评估指标：所选用的指标（如 BLEU、Accuracy、FID 等）是否能真实反映该任务的核心痛点？是否有挑选有利指标的嫌疑？
- Baselines 公平性：对比的先前文献是否为当下强基准？对照方法是否获得了同等的训练步数、参数量与超参数调优预算？
- 资料与开销：是否存在潜在的资料外泄 (Data Leakage) 或过拟合测试集的风险？作者是否如实报告了 GPU/TPU 训练时长、FLOPs 与推论延迟？

## 5. 局限性、边界条件与潜在盲点
- 作者明示局限 vs 隐含边界：区分作者在 Conclusion/Limitation 中承认的问题，与实验数据背后隐含的适用边界。
- 失效模式 (Failure Modes)：在哪些边界情况、极端分布 (OOD) 或实际落地环境中，本方法很可能会失效？
- 未解的核心挑战与未来延伸方向。
"""
    prompt = base + (f"\n\n【论文全文内容】\n{text}" if text else "")
    if focus.strip():
        prompt += f"\n\n【读者特别关注的审查重点】\n读者提出了本次剖析的特别焦点：{focus.strip()}\n请在完成上述 5 大维度分析的同时，在文末增加「## 6. 特别焦点深度回应」，专门针对读者的焦点进行深度剖析。"
    return prompt


AUDIT_PROMPT_SYSTEM = build_audit_prompt({"target": "zh"})

# Source section matching accepts both Chinese scripts; never convert paper text.
BUCKET_KEYWORDS = {
    'intro_bg': ('abstract', 'introduction', 'background', 'related work', 'overview', 'motivation', '绪论', '引言', '背景', '相关工作', '概述', '緒論', '相關工作'),  # i18n-ok: source heading matching
    'method_formula': ('method', 'approach', 'architecture', 'formulation', 'model', 'proposed', 'framework', '方法', '架构', '模型', '演算法', '公式', '推导', '架構', '推導'),  # i18n-ok: source heading matching
    'experiments_ablation': ('experiment', 'result', 'ablation', 'benchmark', 'evaluation', 'setup', 'baseline', '实验', '结果', '消融', '评估', '基准', '實驗', '結果', '評估', '基準'),  # i18n-ok: source heading matching
    'limitations_conclusion': ('limitation', 'discussion', 'conclusion', 'future work', 'broader impact', '局限', '讨论', '结论', '未来工作', '影响', '討論', '結論', '未來工作', '影響'),  # i18n-ok: source heading matching
    'appendix': ('appendix', 'supplement', 'supplementary', 'proof', '附录', '补充资料', '证明', '附錄', '補充資料', '證明'),  # i18n-ok: source heading matching
}


def analyze_paper_sections(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Bucket paper blocks into semantic categories so long papers preserve later sections."""
    buckets: dict[str, list[dict[str, Any]]] = {
        "intro_bg": [],
        "method_formula": [],
        "experiments_ablation": [],
        "limitations_conclusion": [],
        "appendix": [],
        "other": [],
    }
    current_bucket = "intro_bg"
    found_sections = set()
    max_page = 1

    for block in blocks:
        page = int(block.get("page") or 1)
        if page > max_page:
            max_page = page

        kind = block.get("type") or "paragraph"
        if kind == "references":
            continue

        if kind == "heading":
            h_text = " ".join(str(block.get(k) or "").lower() for k in ("en", "zh", "num"))
            matched = False
            for bucket_name, kws in BUCKET_KEYWORDS.items():
                if any(kw in h_text for kw in kws):
                    current_bucket = bucket_name
                    found_sections.add(bucket_name)
                    matched = True
                    break
            if not matched:
                current_bucket = "other"

        buckets[current_bucket].append(block)

    section_labels = {
        "intro_bg": tr("摘要与引言"),
        "method_formula": tr("方法与公式"),
        "experiments_ablation": tr("实验与消融"),
        "limitations_conclusion": tr("限制与讨论"),
        "appendix": tr("附录与补充"),
    }
    covered = [section_labels[k] for k in ("intro_bg", "method_formula", "experiments_ablation", "limitations_conclusion") if k in found_sections]
    uncovered = [section_labels[k] for k in ("intro_bg", "method_formula", "experiments_ablation", "limitations_conclusion") if k not in found_sections]
    if "appendix" in found_sections:
        covered.append(section_labels["appendix"])
    else:
        uncovered.append(tr("附录部分表格与补充"))

    if not covered:
        covered = [tr("全文段落（无明确章节结构）")]

    data_scope = tr("全文 1–{n} 页（涵盖：{sections}）", n=max_page, sections=", ".join(covered))
    return {
        "covered_sections": covered,
        "uncovered_sections": uncovered,
        "data_scope": data_scope,
        "max_page": max_page,
        "buckets": buckets,
    }


def _format_blocks(blocks: list[dict[str, Any]], max_chars: int | None = None) -> str:
    lines = []
    total = 0
    section = "未标示章节"
    for block in blocks:
        kind = block.get("type") or "paragraph"
        if kind == "references":
            continue
        if kind == "heading":
            section = " ".join(str(block.get(k) or "").strip() for k in ("num", "en", "zh")).strip() or section
            lines.append(f"\n[章节标题 p.{block.get('page') or '?'}] {section}")
            continue
        content = [str(block.get(k) or "").strip() for k in ("en", "caption_en", "tex")]
        if not any(content):
            content = [str(block.get(k) or "").strip() for k in ("zh", "caption_zh")]
        if kind == "list":
            content.extend(str(item.get("en") or item.get("zh") or "").strip() for item in block.get("items") or [])
        if kind == "table":
            content.extend(" | ".join(map(str, row)) for row in (block.get("head") or []) + (block.get("rows") or []))
        val = "\n".join(p for p in content if p)
        if val:
            entry = f"[{block.get('id') or '?'} p.{block.get('page') or '?'}] {val}"
            lines.append(entry)
            total += len(entry)
            if max_chars is not None and total >= max_chars:
                lines.append("...（本章节超过字数配额已节录）...")
                break
    return "\n".join(lines)


def extract_paper_text(ws, max_chars: int = MAX_TEXT_CHARS) -> tuple[dict, str]:
    """Extract paper text. If total text fits within max_chars, include all blocks in order;
    if it exceeds max_chars, allocate proportional budgets across sections to prevent losing later chapters."""
    paper = ws.load("paper") or {}
    meta = paper.get("meta") or {}
    blocks = paper.get("blocks") or []

    if not blocks:
        return meta, ""

    title = meta.get("title_zh") or meta.get("title_en") or ws.id
    authors = meta.get("authors") or ""
    abstract = meta.get("abstract") or ""
    header_lines = [f"论文标题：{title}"]
    if authors:
        header_lines.append(f"作者：{authors}")
    if abstract:
        header_lines.append(f"摘要：\n{abstract}\n")
    header_text = "\n".join(header_lines)

    full_body = _format_blocks(blocks, max_chars=None)
    full_untruncated = f"{header_text}\n{full_body}".strip()
    if len(full_untruncated) <= max_chars:
        return meta, full_untruncated

    remaining_chars = max(1000, max_chars - len(header_text))
    analysis = analyze_paper_sections(blocks)
    buckets = analysis["buckets"]

    budgets = {
        "intro_bg": int(remaining_chars * 0.20),
        "method_formula": int(remaining_chars * 0.35),
        "experiments_ablation": int(remaining_chars * 0.35),
        "limitations_conclusion": int(remaining_chars * 0.10),
    }

    bucket_texts = []
    has_buckets = sum(1 for k in budgets if len(buckets.get(k) or []) > 0) >= 2
    if has_buckets:
        for k, budget in budgets.items():
            b_blocks = buckets.get(k) or []
            if b_blocks:
                b_text = _format_blocks(b_blocks, budget)
                if b_text.strip():
                    bucket_texts.append(b_text)
        if buckets.get("other"):
            other_text = _format_blocks(buckets["other"], int(remaining_chars * 0.10))
            if other_text.strip():
                bucket_texts.append(other_text)
        if buckets.get("appendix"):
            app_text = _format_blocks(buckets["appendix"], int(remaining_chars * 0.08))
            if app_text.strip():
                bucket_texts.append(app_text)
        body_text = "\n\n".join(bucket_texts)
        return meta, f"{header_text}\n\n{body_text}"

    # Fallback when paper has no recognizable section headings: keep head + middle + tail
    head_budget = int(remaining_chars * 0.45)
    tail_budget = remaining_chars - head_budget
    head_part = full_body[:head_budget]
    tail_part = full_body[-tail_budget:] if tail_budget > 0 else ""
    return meta, f"{header_text}\n{head_part}\n\n...（中间段落因超过字数上限已节录）...\n\n{tail_part}"


def get_report(ws) -> dict | None:
    if not ws:
        return None
    rep = ws.load("report")
    if rep and isinstance(rep, dict) and rep.get("markdown"):
        return rep
    return None


def list_reports(lib) -> list[dict]:
    reports = []
    for ws in lib.all():
        rep = ws.load("report")
        if rep and isinstance(rep, dict) and rep.get("markdown"):
            meta = (ws.load("paper") or {}).get("meta") or {}
            item = ws.load("item") or {}
            reports.append({
                "paper_id": ws.id,
                "title": meta.get("title_zh") or meta.get("title_en") or item.get("title") or ws.id,
                "authors": meta.get("authors") or item.get("authors") or "",
                "year": meta.get("year") or item.get("year") or "",
                "venue": meta.get("venue") or item.get("venue") or "",
                "model": rep.get("model", ""),
                "created_at": rep.get("created_at", ""),
                "updated_at": rep.get("updated_at", ""),
                "focus": rep.get("focus", ""),
                "markdown": rep.get("markdown", ""),
                "target": rep.get("target", ""),
            })
    return sorted(reports, key=lambda x: str(x.get("updated_at") or ""), reverse=True)


def delete_report(ws) -> dict:
    if not ws:
        raise ValueError(tr("找不到指定的论文"))
    report_file = ws.root / "report.json"
    if report_file.is_file():
        report_file.unlink()
    return {"ok": True, "paper_id": ws.id}


def current_task(root: Path, pid: str | None = None) -> dict | None:
    scope = tasks.scope_id(root)
    live = next((t for t in tasks.list_tasks(scope=scope)
                 if t.get("kind") == "deep-analysis" and (not pid or t.get("paper_id") == pid or t.get("key") == pid)), None)
    if live:
        return tasks.get(live["id"], scope=scope) or live
    return None


def start_deep_analysis_task(app, pid: str, model: str = "", focus: str = "") -> dict:
    ws = app.lib.ws(pid)
    if not ws:
        raise ValueError(tr("找不到指定的论文：{id}", id=pid))
    scope = tasks.scope_id(app.lib.root)
    previous_report = get_report(ws)
    target = langs.reply_code((ws.load("paper") or {}).get("meta"))

    def run(cancel, report):
        paper = ws.load("paper") or {}
        blocks = paper.get("blocks") or []
        if not blocks:
            raise ValueError(tr("论文尚未完成原文整理，无法进行深度剖析。"))

        analysis = analyze_paper_sections(blocks)
        data_scope = analysis["data_scope"]

        _safe_report(report, "read", 1, 4, tr("正在读取论文原文与章节结构…"),
                     stage_label=tr("读取全文"),
                     data_scope=data_scope,
                     preserved_previous=previous_report)

        meta, text = extract_paper_text(ws)
        if not text.strip():
            raise ValueError(tr("论文尚未完成原文整理，无法进行深度剖析。"))

        _safe_report(report, "audit", 2, 4, tr("正在进行深度技术审计与微型推导…"),
                     stage_label=tr("深度技术审计"),
                     data_scope=data_scope,
                     preserved_previous=previous_report)

        cfg = config.load()
        model_cfg, selected = chat_models.engine_cfg(cfg, model or (cfg.get("chat") or {}).get("default"))
        meter = usage.Meter(model_cfg.get("engine", ""))

        prompt = build_audit_prompt({**meta, "target": target}, text, focus)

        answer = engines.run(engines.for_translation(model_cfg), prompt, app.lib.root, [], cancel, meter).strip()

        _safe_report(report, "save", 3, 4, tr("正在储存深度剖析报告…"),
                     stage_label=tr("生成剖析报告"),
                     data_scope=data_scope,
                     preserved_previous=previous_report)

        now_iso = datetime.now(timezone.utc).isoformat()
        result_data = {
            "paper_id": ws.id,
            "title": meta.get("title_zh") or meta.get("title_en") or ws.id,
            "model": selected.get("name") or selected.get("id") or model or "",
            "created_at": now_iso,
            "updated_at": now_iso,
            "focus": focus,
            "markdown": answer,
            "target": target,
        }
        if cancel.is_set():
            raise engines.Cancelled()
        if not answer:
            raise ValueError(tr("深度剖析报告为空，已保留原报告"))
        write_json_atomic(ws.root / "report.json", result_data)

        _safe_report(report, "done", 4, 4, tr("深度剖析报告已完成！"),
                     stage_label=tr("剖析完成"),
                     data_scope=data_scope,
                     result_state="completed",
                     next_actions=["view"])
        return {"paper_id": pid, "result": result_data}

    task = tasks.submit("deep-analysis", run, retry_failed=True, scope=scope,
                        key=pid, paper_id=pid, target=target, preserved_previous=previous_report)
    return task


def apply_to_paper_note(ws, report_markdown: str) -> dict:
    if not ws:
        raise ValueError(tr("找不到指定的论文"))
    now_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    section_text = "\n\n---\n\n## 🔬 " + tr("论文深度剖析报告（{date}）", date=now_str) + f"\n\n{report_markdown.strip()}\n"
    def append(reader):
        current_note = (reader.get("paper_note") or {}).get("body") or ""
        new_body = (current_note.rstrip() + section_text) if current_note.strip() else section_text.strip()
        return [{"op": "paper_note", "body": new_body}]
    res = ws.update_reader_ops(append, client="deep-analysis")
    return {"ok": True, "rev": res.get("rev")}


def export_to_obsidian(ws, report_data: dict) -> dict:
    if not ws:
        raise ValueError(tr("找不到指定的论文"))
    meta = (ws.load("paper") or {}).get("meta") or {}
    title = meta.get("title_zh") or meta.get("title_en") or ws.id
    markdown = str(report_data.get("markdown") or "").strip()
    if not markdown:
        saved = get_report(ws)
        markdown = (saved or {}).get("markdown") or ""
    if not markdown:
        raise ValueError(tr("目前尚无可汇出的深度剖析报告"))
    stem = obsidian_export._safe_title(meta.get("title_en") or meta.get("title_zh") or ws.id, "Paper")
    doc = {
        "id": f"paper:{ws.id}:deep_analysis",
        "kind": "deep-analysis",
        "paper_id": ws.id,
        "title": title + " - " + tr("深度剖析"),
        "filename": f"{stem}-deep-analysis",
        "body": markdown,
    }
    return obsidian_export.export_to_vault([doc])
