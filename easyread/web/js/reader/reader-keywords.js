/* Per-paper research keywords alongside the existing translation glossary. */
(function (PR) {
  "use strict";
  const S = PR.state;
  let termsView = "glossary", paperKeywords = null, paperNoText = false, loading = false;
  PR.refreshKeywords = () => { paperKeywords = null; if (document.body.classList.contains("drawer-open")) PR.renderDrawer(); };
  function keywordGroups() {
    const groups = new Map();
    (paperKeywords || []).forEach((link) => {
      let g = groups.get(link.keyword_id);
      if (!g) { g = { id: link.keyword_id, name: link.name, match_text: link.match_text, hits: 0, manual: [], auto: [] }; groups.set(link.keyword_id, g); }
      if (link.source === "auto") { g.hits += link.occurrences || 0; g.auto.push(link); } else g.manual.push(link);
    });
    return [...groups.values()];
  }
  function paperKeywordsHtml() {
    if (paperKeywords == null) return '<p class="hint">' + PR.t("載入關鍵字中…") + "</p>";
    const groups = keywordGroups();
    const list = groups.map((g) => {
      const sources = g.auto.concat(g.manual);
      const status = g.hits ? PR.t("原文找到 {n} 處", { n: g.hits }) : (paperNoText ? PR.t("尚無可比對原文") : PR.t("原文未找到"));
      return '<div class="kw-item"><div><b>' + PR.esc(g.name) + "</b><small>" + PR.esc(g.match_text) + " · " + status + (g.manual.length ? " · " + PR.t("手動收錄") : "") + "</small></div>" +
        '<details><summary>' + PR.t("展開命中片段") + " (" + sources.length + ")</summary><ul>" +
        sources.map((l) => "<li><blockquote>" + PR.esc(l.quote || PR.t("手動收錄")) + "</blockquote>" + (l.anchor ? '<button class="btn sm line" data-kw-jump="' + PR.esc(l.anchor) + '">' + PR.t("跳轉") + "</button>" : "") + "</li>").join("") + "</ul></details>" +
        "</div>";
    }).join("");
    const ids = groups.map((g) => g.id).join(",");
    const topBar = '<div class="kw-top-bar">' +
      '<form class="kw-add-box" id="kwAddForm">' +
        '<span class="kw-add-icon">' + PR.icon("plus", "sm") + '</span>' +
        '<input class="input kw-add-input" id="kwQuickAdd" placeholder="' + PR.esc(PR.t("+ 新增關鍵字… (輸入後按 Enter 加入)")) + '" maxlength="120" autocomplete="off">' +
        '<button class="kw-add-btn" type="submit" title="' + PR.esc(PR.t("新增關鍵字")) + '">' + PR.icon("arrowUp", "sm") + '</button>' +
      '</form>' +
    '</div>';
    const footer = '<div class="kw-footer">' +
      '<span class="kw-footer-count">' + PR.t("共 {n} 個關鍵字", { n: groups.length }) + '</span>' +
      '<a class="kw-footer-link" href="/research?mode=keywords' + (ids ? "&ids=" + encodeURIComponent(ids) : "") + '">' +
        PR.t("前往跨論文搜尋") + " ↗" +
      '</a>' +
    '</div>';
    return topBar +
      (paperNoText ? '<p class="hint">' + PR.t("本篇尚無可比對原文；這不代表原文沒有這些關鍵字。") + "</p>" : "") +
      (list ? '<div class="terms-keywords">' + list + "</div>" : '<p class="hint">' + PR.t("尚未為本篇收錄關鍵字。") + "</p>") +
      footer;
  }

  PR.readerKeywords = {
    html(glossary) {
      if (PR.store.mode !== "server") return glossary;
      if (paperKeywords == null && !loading) {
        loading = true;
        PR.api("/api/research/v2/keywords?paper_id=" + encodeURIComponent(PR.pid)).then(data => {
          paperKeywords = data.links || []; paperNoText = (data.no_text || []).some(x => x.id === PR.pid);
          loading = false;
          if (termsView === "keywords") PR.renderDrawer();
        }).catch(error => { loading = false; paperKeywords = []; PR.toast(PR.esc(error.message)); if (termsView === "keywords") PR.renderDrawer(); });
      }
      const tabs = '<div class="seg terms-view"><button data-terms-view="glossary" class="' + (termsView === "glossary" ? "on" : "") + '">' + PR.t("術語表") + '</button><button data-terms-view="keywords" class="' + (termsView === "keywords" ? "on" : "") + '">' + PR.t("我的關鍵字") + '</button></div>';
      if (termsView === "keywords") return tabs + paperKeywordsHtml();
      let index = 0;
      glossary = glossary.replace(/<tr><td>/g, () => '<tr><td><input type="checkbox" aria-label="' + PR.t("選擇術語") + '" data-keyword-term="' + index++ + '">');
      return tabs + (index ? '<button class="btn sm line" data-keywords-add>' + PR.t("加入關鍵字") + '</button>' : '') + glossary;
    },
  };
  PR.$("#drawer").addEventListener("submit", (e) => {
    if (e.target.id === "kwAddForm") {
      e.preventDefault();
      const input = PR.$("#kwQuickAdd");
      const raw = (input?.value || "").trim();
      if (!raw) return;
      let name = raw, match = raw;
      if (raw.includes("/")) {
        const parts = raw.split("/");
        name = parts[0].trim();
        match = parts.slice(1).join("/").trim() || name;
      } else {
        const glossary = S.paper.glossary || [];
        const lower = raw.toLowerCase();
        const byZh = glossary.find((g) => g && g.zh && g.zh.trim().toLowerCase() === lower);
        if (byZh && byZh.en) {
          name = byZh.zh.trim();
          match = byZh.en.trim();
        } else {
          const byEn = glossary.find((g) => g && g.en && g.en.trim().toLowerCase() === lower);
          if (byEn && byEn.zh) {
            name = byEn.zh.trim();
            match = byEn.en.trim();
          }
        }
      }
      PR.addKeyword({ name, match_text: match, paper_id: PR.pid })
        .then((saved) => {
          PR.toast(PR.t("已加入關鍵字「{name}」", { name }));
          if (input) input.value = "";
          return PR.scanKeyword(saved.keyword.id);
        })
        .then(() => PR.refreshKeywords())
        .catch((error) => PR.toast(PR.t("加入關鍵字失敗：{message}", { message: error.message })));
    }
  });
  PR.$("#drawer").addEventListener("click", e => {
    const termsTab = e.target.closest("[data-terms-view]");
    if (termsTab) { termsView = termsTab.dataset.termsView; return PR.renderDrawer(); }
    const kwJump = e.target.closest("[data-kw-jump]");
    if (kwJump) { const id = "b-" + kwJump.dataset.kwJump; if (!document.getElementById(id)) return PR.toast(PR.t("找不到這個段落，來源可能已變動")); PR.jumpTo(id); return; }
    const keywordAdd = e.target.closest("[data-keywords-add]");
    if (keywordAdd) {
      const selected = PR.$$("[data-keyword-term]:checked", PR.$("#drawer")).map((box) => S.paper.glossary[Number(box.dataset.keywordTerm)]).filter(Boolean);
      if (!selected.length) return PR.toast(PR.t("請先勾選術語"));
      Promise.all(selected.map((term) => PR.addKeyword({ name: term.zh || term.en, match_text: term.en || term.zh, paper_id: PR.pid })))
        .then(() => { PR.toast(PR.t("已加入 {n} 個關鍵字，正在比對其他論文原文…", { n: selected.length })); return PR.scanKeyword(); })
        .then((task) => { if (task && task.state === "completed") PR.toast(PR.t("原文比對完成")); })
        .catch((error) => PR.toast(PR.t("加入關鍵字失敗：{message}", { message: error.message })));
      return;
    }
  });
})(window.PR);
