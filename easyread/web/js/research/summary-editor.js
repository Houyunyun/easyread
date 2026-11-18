/* Edit a saved source summary without changing the original paper or abstract. */
(function (PR) {
  "use strict";
  PR.editResearchSummary = function (record, onSaved) {
    const box = PR.el("dialog", { class: "confirm rw-summary-editor", "aria-label": PR.t("编辑摘要") },
      '<h2>' + PR.t("编辑摘要") + '</h2><p class="rw-source">' + PR.t("编辑保存的 Markdown 摘要，不会修改论文原文或来源摘要。") + '</p>' +
      '<textarea data-summary-editor aria-label="' + PR.esc(PR.t("摘要 Markdown")) + '" maxlength="40000"></textarea>' +
      '<article class="markdown" data-summary-preview hidden></article><div class="cf-acts">' +
      '<button type="button" class="btn line" data-summary-preview-toggle>' + PR.t("预览") + '</button>' +
      '<button type="button" class="btn line" data-summary-cancel>' + PR.t("取消") + '</button>' +
      '<button type="button" class="btn accent" data-summary-save>' + PR.t("保存摘要") + '</button></div>' +
      '<p role="status" data-summary-status></p>');
    document.body.appendChild(box);
    const input = box.querySelector("[data-summary-editor]"), preview = box.querySelector("[data-summary-preview]");
    const save = box.querySelector("[data-summary-save]"), status = box.querySelector("[data-summary-status]");
    input.value = record.summary_markdown || "";
    const close = () => { if (!save.disabled) { box.close(); box.remove(); } };
    box.querySelector("[data-summary-cancel]").onclick = close;
    box.addEventListener("cancel", event => { event.preventDefault(); close(); });
    box.querySelector("[data-summary-preview-toggle]").onclick = event => {
      const showing = preview.hidden;
      preview.innerHTML = PR.mdBlocks(input.value);
      preview.hidden = !showing; input.hidden = showing;
      event.currentTarget.textContent = showing ? PR.t("编辑") : PR.t("预览");
      if (!showing) input.focus();
    };
    save.onclick = async () => {
      if (save.disabled) return;
      const markdown = input.value.trim();
      if (!markdown) { status.textContent = PR.t("摘要不能为空。"); return; }
      save.disabled = true; status.textContent = PR.t("正在保存…");
      try {
        const result = await PR.api("/api/research/v2/summary/save", { method: "POST", body: {
          paper_key: record.paper_key, summary_markdown: markdown,
          expected_updated: record.summary_updated || record.updated || "", expected_markdown: record.summary_markdown || ""
        } });
        if (onSaved) await onSaved(result.summary);
        save.disabled = false; close(); PR.toast(PR.t("摘要已保存"));
      } catch (error) { status.textContent = PR.errorText ? PR.errorText(error) : String(error.message || error); save.disabled = false; }
    };
    box.addEventListener("keydown", event => {
      event.stopPropagation();
      if (!event.isComposing && event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); save.click(); }
    });
    box.showModal(); input.focus();
    return box;
  };
})(window.PR);
