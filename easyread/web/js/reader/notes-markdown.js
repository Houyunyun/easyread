/* Markdown notes, quotations and research export sections. */
(function (PR) {
  "use strict";
  const S = PR.state;
  /* 导出的 Markdown：论文笔记 + 按原文顺序的批注 */
  /* pick：{paper, note, highlight, question, ai, chat, quote}，不传就全要 */
  function exportTextPair(key) {
    const [id, field] = String(key || "").split("#");
    const block = PR.blockById && PR.blockById[id];
    if (!block) return { zh: "", en: "", sents: null };
    if (field === "caption") { const edit = PR.editOf && PR.editOf(key); return { zh: edit && edit.zh != null ? edit.zh : block.caption_zh || "", en: block.caption_en || "", sents: block.sents || null }; }
    if (field === "image") { const edit = PR.editOf && PR.editOf(key); return { zh: edit && edit.zh != null ? edit.zh : block.image_zh || "", en: block.image_en || "", sents: block.sents || null }; }
    if (/^\d+$/.test(field || "")) {
      const item = (Array.isArray(block.items) ? block.items : [])[Number(field)] || {};
      const edit = PR.editOf && PR.editOf(key);
      return { zh: edit && edit.zh != null ? edit.zh : item.zh || "", en: item.en || "", sents: item.sents || null };
    }
    const edit = PR.editOf && PR.editOf(key);
    return { zh: edit && edit.zh != null ? edit.zh : block.zh || "", en: block.en || "", sents: block.sents || null };
  }

  function translatedExportQuote(item) {
    const d = item.data || {};
    if (!d.quote) return { text: "", translated: false };
    if (d.target === "formula") return { text: d.quote, translated: false, formula: true };
    const pair = exportTextPair(d.key || d.anchor);
    if (!pair.zh) return { text: d.quote, translated: false };
    // 新標註會明確記錄 side；較早的手動劃線可能沒有 side，
    // 只在引用明確出現在英文而未出現在譯文時，才把它視為英文原文。
    const isEnglish = d.side === "en" || (!d.side && pair.en && pair.en.includes(d.quote) && !pair.zh.includes(d.quote));
    if (!isEnglish) return { text: d.quote, translated: false };
    const start = pair.en.indexOf(d.quote);
    const sents = Array.isArray(pair.sents) ? pair.sents.filter((row) => Array.isArray(row) && row.length === 2) : [];
    if (start >= 0 && sents.length >= 2) {
      const end = start + d.quote.length;
      const first = sents.findIndex((row) => row[0] > start);
      const last = sents.findIndex((row) => row[0] >= end);
      if (first >= 0 && last >= 0) {
        const zhStart = first === 0 ? 0 : sents[first - 1][1];
        const zhEnd = sents[last][1];
        const text = pair.zh.slice(zhStart, zhEnd).trim();
        if (text) return { text, translated: true };
      }
    }
    // 沒有句子對齊時仍保留中文譯文，但不假裝它是精確的片語對應。
    return { text: pair.zh, translated: true };
  }

  function exportQuote(item, pick) {
    // 接受後的智慧標註已是「我的劃線」，應與手動劃線一樣可匯出；
    // 頁邊 AI 回答仍不在這裡附加引用，避免把解釋誤當成使用者劃線。
    if (!pick.quote || !item.data?.quote || item.src !== "mine") return "";
    const result = translatedExportQuote(item);
    const side = item.data.side;
    return PR.t("「{q}」", { q: result.text }) + (side === "en" ? (result.translated ? PR.t("（译文）") : PR.t("（原文，尚无译文对齐）")) : "");
  }

  function exportQuoteDetails(item, pick) {
    if (!pick.quote || !item.data?.quote || item.src !== "mine") return { text: "", label: "" };
    const result = translatedExportQuote(item);
    if (!result.text) return { text: "", label: "" };
    const side = item.data.side;
    return {
      text: result.text,
      label: result.formula ? PR.t("公式") : side === "en" ? (result.translated ? PR.t("引用（中文译文；原始划线为英文）") : PR.t("引用（英文原文；尚无译文对齐）")) : PR.t("引用（中文译文）"),
      formula: !!result.formula,
    };
  }

  function markdownLines(text, prefix) {
    return String(text || "").split("\n").map((line, index) => index ? prefix + line : line);
  }

  function mineAnnotationLines(item, pick) {
    const d = item.data || {};
    const quote = exportQuoteDetails(item, pick);
    const noteLabel = d.kind === "question" ? PR.t("我的问题") : PR.t("我的注记");
    const lines = [];
    if (quote.formula) {
      lines.push("- **" + quote.label + "**");
      lines.push("  $$", ...String(quote.text).split("\n").map((line) => "  " + line), "  $$");
      if (d.body) lines.push("  - **" + noteLabel + "：** " + markdownLines(d.body, "    ").join("\n")); // i18n-ok: Markdown formatting punctuation, not UI copy.
    } else if (quote.text) {
      lines.push("- **" + quote.label + "**");
      lines.push("  > 「" + quote.text + "」"); // i18n-ok: Markdown quote punctuation, not UI copy.
      if (d.body) lines.push("  - **" + noteLabel + "：** " + markdownLines(d.body, "    ").join("\n")); // i18n-ok: Markdown formatting punctuation, not UI copy.
    } else if (d.body) {
      lines.push("- **" + noteLabel + "：** " + markdownLines(d.body, "  ").join("\n")); // i18n-ok: Markdown formatting punctuation, not UI copy.
    }
    return lines;
  }

  PR.notesMarkdown = function (pick, chat, exportOptions) {
    pick = pick || { paper: true, note: true, highlight: true, question: true, ai: true, quote: true };
    const m = S.paper.meta || {};
    const link = m.url || (m.arxiv ? "https://arxiv.org/abs/" + String(m.arxiv).replace(/^arXiv:/i, "").split(/[\sv]/)[0] : "");
    const out = ["# " + (m.title_zh || m.title_en || ""), "", m.title_en ? "*" + m.title_en + "*  " : "", [m.authors, m.date, link].filter(Boolean).join(" · "), ""];
    if (exportOptions) {
      const pn = (S.reader.paper_note || {}).body;
      const annotations = PR.annotationItems();
      const groups = {
        note: annotations.filter((it) => it.src === "mine" && it.data.kind !== "question" && it.data.kind !== "highlight"),
        highlight: annotations.filter((it) => it.src === "mine" && it.data.kind === "highlight"),
        question: annotations.filter((it) => it.src === "mine" && it.data.kind === "question"),
        ai: annotations.filter((it) => it.src !== "mine"),
      };
      const labels = { note: PR.t("我的笔记"), highlight: PR.t("我的划线"), question: PR.t("我的问题"), ai: PR.t("AI 的回答和解释") };
      const order = Array.isArray(exportOptions.order) ? exportOptions.order : ["paper", "note", "highlight", "question", "ai", "chat", "mindmap", "deep_analysis"];
      for (const kind of order) {
        if (kind === "paper" && pick.paper && pn) out.push("## " + PR.t("论文笔记"), "", pn, "");
        else if (groups[kind] && pick[kind] && groups[kind].length) {
          out.push("## " + labels[kind], "");
          let lastSec = "";
          for (const it of groups[kind]) {
            const sec = it.anchor === "head" ? PR.t("论文开头") : PR.sectionOf(it.anchor);
            if (sec !== lastSec) { out.push("### " + sec, ""); lastSec = sec; }
            const d = it.data;
            const q = exportQuote(it, pick);
            if (it.src === "mine") { out.push(...mineAnnotationLines(it, pick)); if (PR.noteMedia?.has(d)) out.push(PR.noteMedia.markdown(d)); }
            else out.push("- " + (d.title ? "**" + d.title + "** " : "") + q + (d.q ? PR.t("（问：{q}）", { q: d.q }) : "") + "\n\n  " + (d.body || "").replace(/\n/g, "\n  "));
          }
          out.push("");
        } else if (kind === "chat" && pick.chat && exportOptions.chat?.length) {
          out.push("## " + PR.t("问 AI 的对话"), "");
          for (const c of exportOptions.chat) out.push(c.role === "user" ? PR.t("**我**：") + c.content : PR.t("**AI**（{model}）：", { model: c.model || "" }) + c.content, "");
        } else if (kind === "mindmap" && pick.mindmap && exportOptions.mindmap) { const fence = String.fromCharCode(96).repeat(3); out.push("## " + PR.t("论文心智图"), "", fence + "mermaid", exportOptions.mindmap, fence, "");
        } else if (kind === "deep_analysis" && pick.deep_analysis && exportOptions.deepAnalysis) {
          out.push("## " + PR.t("论文深度剖析"), "", exportOptions.deepAnalysis, "");
        }
      }
      return PR.unlink ? PR.unlink(out.join("\n")) : out.join("\n");
    }
    const pn = (S.reader.paper_note || {}).body;
    if (pick.paper && pn) out.push("## " + PR.t("论文笔记"), "", pn, "");
    const want = (it) => it.src === "mine" ? !!pick[it.data.kind === "question" ? "question" : it.data.kind === "highlight" ? "highlight" : "note"] : !!pick.ai;
    const list = PR.annotationItems().filter(want);
    if (list.length) out.push("## " + PR.t("批注"), "");
    let lastSec = "";
    for (const it of list) {
      const sec = it.anchor === "head" ? PR.t("论文开头") : PR.sectionOf(it.anchor);
      if (sec !== lastSec) { out.push("### " + sec, ""); lastSec = sec; }
      const d = it.data;
      const q = exportQuote(it, pick);
      if (it.src === "mine") { out.push(...mineAnnotationLines(it, pick)); if (PR.noteMedia?.has(d)) out.push(PR.noteMedia.markdown(d)); }
      else out.push("- **AI" + (d.kind === "reply" ? " " + PR.t("回答") : "") + (d.title ? PR.t("：") + d.title : "") + "**" + q + (d.q ? PR.t("（问：{q}）", { q: d.q }) : "") + "\n\n  " + (d.body || "").replace(/\n/g, "\n  "));
    }
    if (pick.chat && chat && chat.length) {
      out.push("", "## " + PR.t("问 AI 的对话"), "");
      for (const c of chat) out.push(c.role === "user" ? PR.t("**我**：") + c.content : PR.t("**AI**（{model}）：", { model: c.model || "" }) + c.content, "");
    }
    return PR.unlink ? PR.unlink(out.join("\n")) : out.join("\n");
  };
})(window.PR);
