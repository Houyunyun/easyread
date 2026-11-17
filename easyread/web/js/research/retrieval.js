/* Cross-paper evidence retrieval; answers remain in the library's existing Ask AI dialog. */
(function (PR) {
  "use strict";
  const API = "/api/research/v1";
  const state = { busy: false, results: [], query: "", index: {} };
  const host = () => PR.$("[data-view='retrieval']");
  function readerUrl(result) {
    if (!/^[a-zA-Z0-9_-]{1,128}$/.test(result.source_id || "")) return "";
    const block = String(result.block || "").replace(/^b-/, "");
    return "/read/" + encodeURIComponent(result.source_id) + (block ? "#b-" + encodeURIComponent(block) : "");
  }
  function resultsHtml(results, query) {
    return results.map(result => {
      const url = readerUrl(result);
      const title = PR.titleHtml(result.title || PR.t("未命名论文"));
      const source = [result.section, result.page ? PR.t("第 {n} 页", {n:result.page}) : "", result.path].filter(Boolean).map(PR.esc).join(" · ");
      return '<article class="rw-card rw-paper"><h3>' + (url ? '<a href="' + PR.esc(url) + '">' + title + '</a>' : title) + '</h3><p class="meta">' + source + '</p><p class="rw-retrieval-snippet">' + PR.highlightSnippet(result.snippet || result.text || "", query) + '</p>' + (url ? '<a class="btn sm line" href="' + PR.esc(url) + '">' + PR.t("核对原文") + '</a>' : '<p class="rw-source">' + PR.t("此结果来自 Vault 笔记，请按上方路径在 Obsidian 中核对。") + '</p>') + '</article>';
    }).join("") || '<div class="rw-empty">' + PR.t("没有找到相关段落。请换用论文中的术语或检查索引。") + '</div>';
  }
  function status(text, error = false) {
    const node = host().querySelector("[data-retrieval-status]");
    node.textContent = text; node.className = error ? "rw-error" : "rw-source";
  }
  function show() {
    host().querySelector("[data-retrieval-results]").innerHTML = resultsHtml(state.results, state.query);
    const errors = state.index.errors || [];
    const summary = [PR.t("找到 {n} 个相关段落", { n: state.results.length })];
    if (Number.isFinite(state.index.chunks)) summary.push(PR.t("索引包含 {n} 个段落", {n:state.index.chunks}));
    if (state.index.semantic_task && ["queued", "running", "cancelling"].includes(state.index.semantic_task.state)) summary.push(PR.t("语义索引正在后台建立，目前可先使用词语匹配结果。"));
    if (errors.length) summary.push(PR.t("部分索引或语义模型尚未就绪：{errors}", {errors:errors.map(error => PR.t(error)).join(" · ")}));
    status(summary.join(" · "), !!errors.length);
  }
  async function search(query, kind = "", limit = 10) {
    if (state.busy || !query.trim()) return;
    state.busy = true;
    const button = host().querySelector('[type="submit"]');
    button.disabled = true; status(PR.t("正在检索原文…"));
    try {
      const result = await PR.api(API + "/query", { method: "POST", body: { query: query.trim(), kind, limit } });
      state.query = query.trim(); state.results = result.results || []; state.index = result.index || {};
      if (state.index.semantic_task) PR.researchTaskMonitor?.track(state.index.semantic_task);
      show();
    } catch (error) { status(error.message, true); }
    finally { state.busy = false; button.disabled = false; }
  }
  function render() {
    const root = host();
    if (root.querySelector("[data-retrieval-form]")) return;
    root.innerHTML = '<section class="rw-panel"><h2>' + PR.t("跨论文检索") + '</h2><p class="rw-source">' + PR.t("检索已整理的论文和已连接 Vault 中的笔记，查看相关段落并回到原文核对。不会生成答案。") + '</p><form data-retrieval-form><label class="rw-field"><span>' + PR.t("想核对什么？") + '</span><textarea class="input" name="query" rows="3" maxlength="2000" required></textarea></label><div class="rw-form-grid"><label class="rw-field"><span>' + PR.t("检索范围") + '</span><select name="kind"><option value="">' + PR.t("论文与笔记") + '</option><option value="paper">' + PR.t("论文") + '</option></select></label><label class="rw-field"><span>' + PR.t("结果数量") + '</span><select name="limit"><option value="10">10</option><option value="20">20</option><option value="30">30</option></select></label></div><div class="actions"><button class="btn accent" type="submit">' + PR.t("检索") + '</button><button class="btn line" type="button" data-retrieval-vault>' + PR.t("连接 Obsidian Vault") + '</button></div></form><p role="status" data-retrieval-status></p></section><div class="rw-results" data-retrieval-results></div>';
    root.querySelector("form").addEventListener("submit", event => {
      event.preventDefault();
      const form = event.currentTarget;
      void search(form.elements.query.value, form.elements.kind.value, Number(form.elements.limit.value));
    });
    root.querySelector("[data-retrieval-vault]").onclick = async event => {
      const button = event.currentTarget; button.disabled = true;
      try {
        const vault = await PR.pickFolder({title:PR.t("选择 Obsidian Vault 文件夹")});
        if (!vault) return;
        await PR.api(API + "/setup", {method:"POST", body:{vault}});
        status(PR.t("已连接 Vault，请重新检索。首次建立语义索引可能需要下载本地模型。"));
      } catch (error) { status(error.message, true); }
      finally { button.disabled = false; }
    };
  }
  PR.researchRetrieval = { render, readerUrl, resultsHtml, search };
})(window.PR);
