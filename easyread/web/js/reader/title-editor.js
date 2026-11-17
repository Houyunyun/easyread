/* Edit paper metadata without replacing the translator's text or reader layout. */
(function (PR) {
  "use strict";
  function prepare() {
    if (PR.store.mode !== "server") return;
    const title = PR.$("#paper .paper-head h1"), original = PR.$("#paper .paper-head .title-en");
    if (!title || title.querySelector("[data-edit-title]")) return;
    title.dataset.titleKey = "title_zh";
    title.title = PR.t("双击可编辑翻译标题");
    if (original) original.dataset.titleKey = "title_en";
    const button = document.createElement("button");
    button.type = "button"; button.className = "title-edit-btn"; button.dataset.editTitle = "";
    button.title = PR.t("编辑翻译标题"); button.setAttribute("aria-label", button.title); button.innerHTML = PR.icon("edit", "sm");
    title.append(button);
  }
  PR.saveMetaTitle = async function (key, text) {
    if (PR.store.mode !== "server" || !["title_zh", "title_en"].includes(key) || !text.trim()) return false;
    const S = PR.state, override = { ...(S.item.meta_override || {}), [key]: text };
    if (key === "title_zh") override.short_zh = PR.deriveShortTitle ? PR.deriveShortTitle(text, true) : text;
    await PR.api("/api/p/" + encodeURIComponent(PR.pid) + "/item", { method: "POST", body: { meta_override: override } });
    S.item.meta_override = override; Object.assign(S.paper.meta, override); PR.updateTitle();
    if (typeof BroadcastChannel !== "undefined") {
      const bus = new BroadcastChannel("paperread-tabs-bus");
      bus.postMessage({ type: "pr:paper-updated", pid: PR.pid, ...override, meta_override: override }); bus.close();
    }
    return true;
  };
  PR.editTitle = function (title) {
    if (PR.store.mode !== "server" || PR.editingKey) return;
    const key = title.dataset.titleKey, current = PR.state.paper.meta[key] || "";
    PR.editingKey = "title:" + key; PR.hideBlockbar();
    const wrap = PR.el("div", { class: "editor-wrap title-editor-wrap" });
    const input = PR.el("textarea", { class: "editor", "aria-label": PR.t("编辑标题") }); input.value = current;
    const bar = PR.el("div", { class: "editor-bar" }, '<span>' + PR.t("Enter 保存 · Shift+Enter 换行 · Esc 取消") + '</span><span class="grow"></span><button data-title-action="cancel">' + PR.t("取消") + '</button><button class="primary" data-title-action="save">' + PR.t("保存") + '</button>');
    wrap.append(input, bar); title.replaceChildren(wrap); PR.autosize(input); input.focus(); input.select();
    let saving = false;
    async function finish(action) {
      if (saving) return;
      const text = input.value.trim();
      if (action === "save" && !text) return;
      saving = true;
      try {
        if (action === "save" && text !== current) { await PR.saveMetaTitle(key, text); PR.toast(PR.t("标题已更新")); }
        PR.editingKey = null; PR.renderPaperHead();
      } catch (error) { PR.toast(PR.esc(PR.t("保存标题失败：{err}", { err: error.message }))); }
      finally { saving = false; }
    }
    bar.addEventListener("click", e => { const button = e.target.closest("[data-title-action]"); if (button) finish(button.dataset.titleAction); });
    input.addEventListener("keydown", e => {
      if (e.isComposing) return;
      if (e.key === "Escape" || (e.key === "Enter" && !e.shiftKey)) { e.preventDefault(); e.stopPropagation(); finish(e.key === "Escape" ? "cancel" : "save"); }
    });
  };
  document.addEventListener("dblclick", e => {
    const title = e.target.closest("#paper .paper-head [data-title-key]");
    if (!title || e.target.closest("a, button, textarea")) return;
    getSelection().removeAllRanges(); PR.$("#selbar").classList.remove("open"); PR.editTitle(title);
  });
  document.addEventListener("click", e => {
    const button = e.target.closest("[data-edit-title]");
    if (button) { e.preventDefault(); PR.editTitle(button.closest("h1")); }
  });
  PR.on("rendered", prepare); PR.on("paper-head-rendered", prepare);
})(window.PR);
