/* AI annotation suggestions, review and job lifecycle. */
(function (PR) {
  "use strict";
  const S = PR.state;
  let smartJob = null;
  function getBlockIndex(anchor) {
    if (!anchor) return 999999;
    const blocks = (S.paper && S.paper.blocks) || [];
    const idx = blocks.findIndex((b) => b && b.id === anchor);
    return idx >= 0 ? idx : 999999;
  }

  const smartItems = () => {
    const list = Object.values(S.reader.ai_annotations || {}).filter((a) => ["pending", "edited"].includes(a.status));
    return list.sort((a, b) => {
      const pageA = a.page != null ? Number(a.page) : 9999;
      const pageB = b.page != null ? Number(b.page) : 9999;
      if (pageA !== pageB) return pageA - pageB;
      const idxA = getBlockIndex(a.anchor);
      const idxB = getBlockIndex(b.anchor);
      if (idxA !== idxB) return idxA - idxB;
      return (a.created_at || "").localeCompare(b.created_at || "");
    });
  };

  function updateSmartNotesIndicator(running) {
    const btn = PR.$ && PR.$('[data-act="dock"]');
    if (btn) {
      if (running) {
        btn.classList.add("is-running");
      } else if (!PR.noteHelpRunning || !PR.noteHelpRunning()) {
        btn.classList.remove("is-running");
      }
    }
  }
  const smartSections = () => (PR.headings || []).filter((h) => h && h.id).map((h) => ({ id: h.id, label: (h.num ? h.num + " " : "") + PR.plain(PR.textFor(h.id) || h.zh || h.en || "") }));

  function smartColorLegend() {
    const highlighters = [
      ["yellow", PR.t("核心主张"), PR.t("标记完整的重要句子、核心论点与结论")],
      ["green", PR.t("方法与证据"), PR.t("标记研究方法、实验架构与关键结果")],
      ["blue", PR.t("背景知识"), PR.t("标记重要背景、问题定义与领域概念")],
      ["pink", PR.t("研究限制"), PR.t("标记研究限制、瓶颈、缺陷与待解问题")],
    ];
    const underlines = [
      ["yellow", PR.t("关键词"), PR.t("标记核心概念、专有名词与新术语")],
      ["green", PR.t("数据指标"), PR.t("标记数值、统计指标、百分比与实验数据")],
      ["blue", PR.t("引用来源"), PR.t("标记作者、理论名称、基准模型与文献")],
      ["pink", PR.t("疑点与风险"), PR.t("标记不确定性、矛盾语句与潜在风险")],
    ];

    const renderPills = (list, isUnderline) =>
      list.map(([color, semLabel, desc]) =>
        '<span class="smart-pill" title="' + PR.esc(desc) + '">' +
        (isUnderline
          ? '<span class="smart-bar ul-' + color + '"></span>'
          : '<span class="smart-dot hl-' + color + '"></span>') +
        '<span>' + PR.esc(semLabel) + '</span>' +
        '<span class="smart-info-tip" aria-label="' + PR.esc(desc) + '">i</span>' +
        '</span>'
      ).join("");

    return '<div class="smart-legend-box">' +
      '<div class="smart-legend-head">' +
      '<span class="smart-legend-title">' + PR.t("标注规则图例") + '</span>' +
      '</div>' +
      '<div class="smart-legend-body">' +
      '<div class="smart-legend-group">' +
      '<div class="smart-legend-subhead">' + PR.t("萤光笔（句子）") + '</div>' +
      '<div class="smart-legend-grid">' + renderPills(highlighters, false) + '</div>' +
      '</div>' +
      '<div class="smart-legend-group">' +
      '<div class="smart-legend-subhead">' + PR.t("底线笔（短语）") + '</div>' +
      '<div class="smart-legend-grid">' + renderPills(underlines, true) + '</div>' +
      '</div>' +
      '</div>' +
      '</div>';
  }

  function smartDialog() {
    const dlg = PR.$("#readerDlg");
    const sections = smartSections();
    dlg.querySelector(".dialog").innerHTML = '<h2>' + PR.t("智慧标注") + '</h2>' +
      '<div class="smart-alert-banner">' +
      '<span class="smart-alert-icon">ℹ</span>' +
      '<span>' + PR.t("先产生待确认建议；接受后才会套用到正文，不会覆盖手动标注。") + '</span>' +
      '</div>' +
      smartColorLegend() +
      '<div class="smart-form-section">' +
        '<div class="smart-form-group">' +
          '<label class="smart-group-label">' + PR.t("划记强度") + '</label>' +
          '<input type="hidden" id="smartIntensity" value="standard">' +
          '<div class="smart-segmented" role="radiogroup" aria-label="' + PR.esc(PR.t("划记强度")) + '">' +
            '<button type="button" class="smart-seg-btn" data-seg="smartIntensity" data-val="concise" title="' + PR.esc(PR.t("每段只保留最有价值的资讯，适合快速阅读")) + '">' +
              '<span class="seg-title">' + PR.t("精简") + '</span>' +
              '<span class="seg-sub">' + PR.t("快速阅读") + '</span>' +
            '</button>' +
            '<button type="button" class="smart-seg-btn active" data-seg="smartIntensity" data-val="standard" title="' + PR.esc(PR.t("保留各类重要资讯与核心词汇，适合一般研究")) + '">' +
              '<span class="seg-title">' + PR.t("标准") + '</span>' +
              '<span class="seg-sub">' + PR.t("一般研究") + '</span>' +
            '</button>' +
            '<button type="button" class="smart-seg-btn" data-seg="smartIntensity" data-val="detailed" title="' + PR.esc(PR.t("增加次要证据与详细数据，适合深入研究")) + '">' +
              '<span class="seg-title">' + PR.t("详细") + '</span>' +
              '<span class="seg-sub">' + PR.t("深入研究") + '</span>' +
            '</button>' +
          '</div>' +
        '</div>' +
        '<div class="smart-form-row">' +
          '<div class="smart-form-col">' +
            '<div class="smart-label-wrap">' +
              '<label class="smart-group-label" for="smartMode">' + PR.t("分析模式") + '</label>' +
              '<button type="button" class="smart-help-btn" data-smart-mode-help title="' + PR.esc(PR.t("说明三种标注模式的差异")) + '" aria-label="' + PR.esc(PR.t("说明三种标注模式的差异")) + '">' +
                PR.icon("question", "sm") +
              '</button>' +
            '</div>' +
            '<select id="smartMode" class="smart-select">' +
              '<option value="auto">' + PR.t("AI 自动标注") + '</option>' +
              '<option value="suggest">' + PR.t("AI 建议标注") + '</option>' +
              '<option value="purpose">' + PR.t("依研究目的标注") + '</option>' +
            '</select>' +
          '</div>' +
          '<div class="smart-form-col">' +
            '<label class="smart-group-label">' + PR.t("分析范围") + '</label>' +
            '<input type="hidden" id="smartScope" value="all">' +
            '<div class="smart-segmented" role="radiogroup" aria-label="' + PR.esc(PR.t("分析范围")) + '">' +
              '<button type="button" class="smart-seg-btn active" data-seg="smartScope" data-val="all">' +
                '<span class="seg-title">' + PR.t("全文") + '</span>' +
              '</button>' +
              '<button type="button" class="smart-seg-btn" data-seg="smartScope" data-val="section">' +
                '<span class="seg-title">' + PR.t("指定章节") + '</span>' +
              '</button>' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<section id="smartModeHelp" class="smart-mode-help" role="region" hidden>' +
          '<div class="smart-mode-help-head">' +
            '<b>' + PR.t("分析模式差异说明") + '</b>' +
            '<button type="button" class="smart-help-close" data-smart-mode-help-close aria-label="' + PR.t("关闭模式说明") + '">×</button>' +
          '</div>' +
          '<dl class="smart-mode-dl">' +
            '<dt>' + PR.t("AI 自动标注") + '</dt>' +
            '<dd>' + PR.t("由 AI 全面均衡分析全文，自动发掘最重要的核心主张、方法、关键词与数据指标。") + '</dd>' +
            '<dt>' + PR.t("AI 建议标注") + '</dt>' +
            '<dd>' + PR.t("侧重标注研究方法、架构设计、实验结果与文献引用，适合深化技术细节。") + '</dd>' +
            '<dt>' + PR.t("依研究目的标注") + '</dt>' +
            '<dd>' + PR.t("依读者自订的研究目的（在下方输入框填写）进行聚焦定向标记，精准过滤相关内容。") + '</dd>' +
          '</dl>' +
        '</section>' +
        '<div class="smart-field smart-section-field" hidden>' +
          '<label class="smart-group-label" for="smartSection">' + PR.t("章节") + '</label>' +
          '<select id="smartSection" class="smart-select">' + sections.map((s) => '<option value="' + PR.esc(s.id) + '">' + PR.esc(s.label) + '</option>').join("") + '</select>' +
        '</div>' +
        '<div class="smart-field smart-purpose-field">' +
          '<label class="smart-group-label" for="smartPurpose">' + PR.t("研究目的（可选）") + '</label>' +
          '<textarea id="smartPurpose" rows="2" class="smart-textarea" placeholder="' + PR.esc(PR.t("例如：找出可用于 3D segmentation 的方法与限制")) + '"></textarea>' +
        '</div>' +
      '</div>' +
      '<div class="actions"><button class="btn" data-smart-close>' + PR.t("取消") + '</button><button class="btn primary" data-smart-start>' + PR.t("开始分析") + '</button></div>';
    dlg.classList.add("open");

    const section = dlg.querySelector(".smart-section-field");
    dlg.querySelectorAll(".smart-seg-btn").forEach((btn) => {
      btn.onclick = () => {
        const targetId = btn.dataset.seg;
        const val = btn.dataset.val;
        btn.closest(".smart-segmented").querySelectorAll(".smart-seg-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        const inp = dlg.querySelector("#" + targetId);
        if (inp) inp.value = val;
        if (targetId === "smartScope" && section) {
          section.hidden = (val !== "section");
        }
      };
    });
    const modeSelect = dlg.querySelector("#smartMode");
    const purposeTextarea = dlg.querySelector("#smartPurpose");
    if (modeSelect && purposeTextarea) {
      modeSelect.onchange = () => {
        if (modeSelect.value === "purpose") {
          purposeTextarea.focus();
        }
      };
    }
    const modeHelpBtn = dlg.querySelector("[data-smart-mode-help]");
    const modeHelpBox = dlg.querySelector("#smartModeHelp");
    const modeHelpClose = dlg.querySelector("[data-smart-mode-help-close]");
    if (modeHelpBtn && modeHelpBox) {
      modeHelpBtn.onclick = () => {
        const isHidden = modeHelpBox.hidden;
        modeHelpBox.hidden = !isHidden;
        modeHelpBtn.classList.toggle("active", isHidden);
      };
    }
    if (modeHelpClose && modeHelpBox) {
      modeHelpClose.onclick = () => {
        modeHelpBox.hidden = true;
        modeHelpBtn?.classList.remove("active");
      };
    }
  }

  function smartCard(a) {
    const isUnderline = a.style === "underline" || a.type === "underline";
    const label = isUnderline ? PR.t("底线") : PR.t("萤光笔");
    const color = a.color === "pink" ? PR.t("红") : (PR.HL_COLORS.find(([key]) => key === a.color) || ["", a.color || PR.t("黄")])[1];
    const semanticRole = isUnderline ? ({
      yellow: PR.t("关键词"),
      green: PR.t("数据指标"),
      blue: PR.t("引用来源"),
      pink: PR.t("疑点与风险"),
    }[a.color] || PR.t("关键词")) : ({
      yellow: PR.t("核心主张"),
      green: PR.t("方法与证据"),
      blue: PR.t("背景知识"),
      pink: PR.t("研究限制"),
    }[a.color] || PR.t("核心主张"));
    const location = a.locatable ? (a.page ? PR.t("第 {page} 页", { page: a.page }) : PR.t("已定位")) :
      (a.stale_reason === "translation_changed" ? PR.t("译文已更新，请重新分析") :
        (a.source_stale ? PR.t("来源已更新，请重新分析") : PR.t("无法定位，请修改原文")));

    const overlapBadge = a.manual_overlap
      ? '<span class="smart-badge smart-badge-overlap" title="' + PR.esc(PR.t("与手动划记重叠（{quote}）", { quote: a.overlap_quote || "" })) + '">' + PR.t("与手动划记重叠") + '</span>'
      : '';

    let actionsHtml = '';
    if (a.manual_overlap) {
      actionsHtml = '<button class="btn sm warning" data-smart-action="accept" title="' + PR.esc(PR.t("保留此 AI 标注，与既有手动标注并存")) + '">' + PR.t("保留重叠") + '</button>' +
        '<button class="btn sm line" data-smart-action="reject" title="' + PR.esc(PR.t("略过此重叠标注")) + '">' + PR.t("略过") + '</button>' +
        '<button class="btn sm line" data-smart-action="edit">' + PR.t("修改") + '</button>';
    } else {
      actionsHtml = '<button class="btn sm primary" data-smart-action="accept"' + (a.locatable ? "" : " disabled") + '>' + PR.t("接受") + '</button>' +
        '<button class="btn sm line" data-smart-action="edit">' + PR.t("修改") + '</button>' +
        '<button class="btn sm line danger" data-smart-action="reject">' + PR.t("拒绝") + '</button>';
    }

    return '<article class="smart-card' + (a.locatable ? "" : " smart-unlocatable") + (a.manual_overlap ? " smart-overlap" : "") + '" data-smart-id="' + PR.esc(a.annotation_id) + '" data-anchor="' + PR.esc(a.anchor || "") + '">' +
      '<div class="smart-card-head"><span class="smart-tag smart-tag-' + PR.esc(a.color) + (isUnderline ? ' is-underline' : '') + '">' + PR.esc(semanticRole) + '</span>' + overlapBadge + '<span class="grow"></span><span class="smart-meta">' + PR.esc(color) + " · " + PR.esc(label) + " · " + PR.esc(location) + (PR.aiOutputLanguage(a.target) ? ' · ' + PR.esc(PR.aiOutputLanguage(a.target)) : '') + '</span></div>' +
      (a.manual_overlap ? '<div class="smart-overlap-hint">' + PR.esc(PR.t("侦测到此处已存在手动划记：「{quote}」。AI 不会覆盖您的划记，您可以决定是否保留此重叠建议。", { quote: a.overlap_quote || "" })) + '</div>' : '') +
      '<blockquote class="smart-quote' + (isUnderline ? ' smart-quote-underline' : '') + '">' + PR.md(a.quote || PR.t("没有可显示的原文"), { cite: false, xref: false }) + '</blockquote>' +
      (a.note ? '<p class="smart-note"><b>' + PR.t("AI 注记") + '</b> ' + PR.mdBlocks(a.note) + '</p>' : '') +
      (a.reason ? '<p class="smart-reason"><b>' + PR.t("标注原因") + '</b> ' + PR.esc(a.reason) + '</p>' : '') +
      '<div class="smart-actions">' + actionsHtml + '</div></article>';
  }

  function smartHtml() {
    const list = smartItems();
    const locatableList = list.filter((a) => a.locatable);
    const overlapCount = locatableList.filter((a) => a.manual_overlap).length;
    const cleanCount = locatableList.filter((a) => !a.manual_overlap).length;
    const running = smartJob && ["queued", "running"].includes(smartJob.state);
    const progressText = running
      ? (smartJob.total > 0
          ? PR.t("正在分析论文（第 {done} / {total} 批）…", { done: Math.min((smartJob.done || 0) + 1, smartJob.total), total: smartJob.total })
          : PR.t("正在分析论文，完成后会显示待确认项目…"))
      : "";

    let batchButtons = '';
    if (running) {
      batchButtons = '<button class="btn sm line" data-smart-cancel>' + PR.t("取消分析") + '</button>';
    } else if (list.length > 0) {
      if (cleanCount > 0) {
        batchButtons += '<button class="btn sm primary" data-smart-action="accept-all" title="' + PR.esc(PR.t("仅接受无手动冲突的标注")) + '">' + (overlapCount > 0 ? PR.t("批次接受（{n} 笔非重叠）", { n: cleanCount }) : PR.t("批次接受")) + '</button>';
      }
      if (overlapCount > 0) {
        batchButtons += '<button class="btn sm warning line" data-smart-action="accept-all-overlap" title="' + PR.esc(PR.t("包含与手动划记重叠的标注一并接受")) + '">' + PR.t("全部接受（含重叠 {n} 笔）", { n: overlapCount }) + '</button>';
        batchButtons += '<button class="btn sm line" data-smart-action="reject-overlaps" title="' + PR.esc(PR.t("略过所有与手动划记重叠的建议")) + '">' + PR.t("略过重叠") + '</button>';
      }
      batchButtons += '<button class="btn sm line danger" data-smart-action="reject-all">' + PR.t("批次拒绝") + '</button>';
    }

    let h = '<section class="np-smart"><div class="np-smart-head"><div><b>' + PR.t("AI 待确认标注") + '</b><span class="smart-count">' + list.length + '</span></div><span class="grow"></span>' +
      batchButtons + '</div>' +
      (running ? '<p class="hint smart-progress"><span class="spin"></span> ' + progressText + '</p>' : '') +
      (list.length ? '<div class="np-smart-list">' + list.map(smartCard).join("") + '</div>' : '<p class="hint smart-empty">' + PR.t("尚未产生 AI 标注建议。先按「智慧标注」开始分析。") + '</p>') + '</section>';
    return h;
  }

  async function smartAction(action, id, patch, extra) {
    try {
      if (!await PR.flushPending()) throw new Error(PR.t("修改尚未保存，请稍后重试"));
      const body = { action, id, patch, ...(extra || {}) };
      await PR.api("/api/p/" + encodeURIComponent(PR.pid) + "/smart-annotation", { method: "POST", body });
      await PR.poll();
      PR.renderNotesPanel();
      if (action === "accept" || action === "accept_all") { PR.applyMarks(); PR.renderMargin(); }
    } catch (error) { PR.toast(PR.t(PR.errorText(error))); }
  }

  function smartEdit(card, a) {
    PR.popover(card, '<div class="hd">' + PR.t("修改 AI 标注") + '</div>' +
      '<label class="smart-edit-field">' + PR.t("译文定位文字") + '<textarea id="smartEditQuote" rows="3">' + PR.esc(a.quote || "") + '</textarea></label>' +
      '<label class="smart-edit-field">' + PR.t("AI 注记") + '<textarea id="smartEditNote" rows="3">' + PR.esc(a.note || "") + '</textarea></label>' +
      '<label class="smart-edit-field">' + PR.t("标注原因") + '<textarea id="smartEditReason" rows="2">' + PR.esc(a.reason || "") + '</textarea></label>' +
      '<div class="smart-edit-actions"><button class="btn sm" data-smart-edit="cancel">' + PR.t("取消") + '</button><button class="btn sm primary" data-smart-edit="save">' + PR.t("储存修改") + '</button></div>', { sticky: true, wide: true });
    PR.$("#popover").onclick = (event) => {
      const b = event.target.closest("[data-smart-edit]");
      if (!b) return;
      if (b.dataset.smartEdit === "cancel") return PR.hidePopover();
      const value = { quote: PR.$("#smartEditQuote").value, note: PR.$("#smartEditNote").value, reason: PR.$("#smartEditReason").value };
      PR.hidePopover();
      smartAction("edit", a.annotation_id, value);
    };
  }


  PR.smartAnnotations = { html: smartHtml, open: smartDialog };
  PR.$("#notespanel").addEventListener("click", async e => {
    if (e.target.closest('[data-np-act="smart"]')) return smartDialog();
    const smartButton = e.target.closest("[data-smart-action]");
    if (smartButton) {
      const card = smartButton.closest("[data-smart-id]");
      const id = card && card.dataset.smartId;
      const act = smartButton.dataset.smartAction;
      if (act === "accept-all") return smartAction("accept_all", null, null, { include_overlap: false });
      if (act === "accept-all-overlap") return smartAction("accept_all", null, null, { include_overlap: true });
      if (act === "reject-overlaps") return smartAction("reject_overlaps");
      if (act === "reject-all") return smartAction("reject_all");
      const annotation = id && (S.reader.ai_annotations || {})[id];
      if (!annotation) return;
      if (act === "edit") return smartEdit(card, annotation);
      return smartAction(act, id);
    }
    const smartCardEl = e.target.closest(".smart-card");
    if (smartCardEl && !e.target.closest("button, a")) {
      if (smartCardEl.dataset.anchor) PR.jumpTo("b-" + smartCardEl.dataset.anchor);
      return;
    }
    if (e.target.closest("[data-smart-cancel]") && smartJob) {
      try { await PR.api("/api/p/" + encodeURIComponent(PR.pid) + "/smart-annotate-cancel", { method: "POST", body: { job: smartJob.id } }); }
      catch (error) { PR.toast(PR.errorText(error)); }
      smartJob = null;
      updateSmartNotesIndicator(false);
      PR.renderNotesPanel();
      return;
    }
  });
  function notifySmartComplete(job) {
    const list = smartItems();
    const count = list.length;
    const msg = count > 0
      ? PR.t("AI 标注分析完成，已产生 {count} 笔待确认标注。", { count })
      : PR.t("AI 标注分析完成，未发现高价值标注。");

    PR.toast(PR.esc(msg), count > 0 ? {
      label: PR.t("查看标注"),
      fn: () => {
        PR.openAnnotations();
        setTimeout(() => {
          const el = PR.$(".np-smart");
          if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
        }, 120);
      },
    } : null, 6000);

    if (document.hidden && "Notification" in window && Notification.permission === "granted") {
      try {
        new Notification(PR.t("EasyRead 智慧标注完成"), {
          body: msg,
          icon: "/web/favicon.svg",
        });
      } catch (_) {}
    }
  }

  async function waitSmartJob(job) {
    smartJob = job;
    if (PR.researchTaskMonitor?.track) PR.researchTaskMonitor.track({ ...job, paper_id: PR.pid }, false);
    updateSmartNotesIndicator(true);
    PR.renderNotesPanel();
    let lastDone = job.done || 0;
    const timer = setInterval(async () => {
      try {
        const found = (await PR.api("/api/jobs?pid=" + encodeURIComponent(PR.pid))).jobs.find((item) => item.id === job.id);
        if (!found) return;
        smartJob = found;
        if (PR.researchTaskMonitor?.track) PR.researchTaskMonitor.track({ ...found, paper_id: PR.pid }, false);
        if ((found.done || 0) > lastDone) {
          lastDone = found.done;
          await PR.poll();
          PR.renderNotesPanel();
        }
        if (!["done", "error", "cancelled"].includes(found.state)) {
          PR.renderNotesPanel();
          return;
        }
        clearInterval(timer);
        smartJob = null;
        updateSmartNotesIndicator(false);
        await PR.poll();
        PR.renderNotesPanel();
        if (found.state === "done") {
          notifySmartComplete(found);
        } else if (found.state === "error") {
          PR.toast(PR.t("AI 标注分析失败：{message}", { message: PR.esc(found.message || "") }));
        }
      } catch (_) { /* 下一次輪詢再試 */ }
    }, 1200);
  }

  async function syncRunningSmartJob() {
    try {
      if (!PR.pid) return;
      const data = await PR.api("/api/jobs?pid=" + encodeURIComponent(PR.pid));
      const running = (data.jobs || []).find((j) => j && j.kind === "smart-annotate" && ["queued", "running"].includes(j.state));
      if (running && (!smartJob || smartJob.id !== running.id)) {
        waitSmartJob(running);
      }
    } catch (_) {}
  }
  PR.on("reader-ready", () => { if (PR.store.mode === "server") syncRunningSmartJob(); });

  PR.on && PR.on("open-smart-annotations", () => {
    PR.openAnnotations();
    setTimeout(() => {
      const el = PR.$(".np-smart");
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 150);
  });
  PR.on && PR.on("retry-smart-annotations", () => {
    smartDialog();
  });
  if (new URLSearchParams(location.search).get("open") === "smart-annotations") {
    PR.on("reader-ready", () => {
      PR.openAnnotations();
      const el = PR.$(".np-smart");
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  PR.$("#readerDlg")?.addEventListener("click", async (e) => {
    if (e.target.closest("[data-smart-close]")) return PR.$("#readerDlg").classList.remove("open");
    const start = e.target.closest("[data-smart-start]");
    if (!start) return;
    try {
      if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission();
      }
    } catch (_) {}
    start.disabled = true;
    start.innerHTML = '<span class="spin"></span> ' + PR.t("正在送出…");
    try {
      const job = await PR.api("/api/p/" + encodeURIComponent(PR.pid) + "/smart-annotate", { method: "POST", body: {
        scope: PR.$("#smartScope").value, section_id: PR.$("#smartSection").value,
        mode: PR.$("#smartMode").value,
        intensity: PR.$("#smartIntensity") ? PR.$("#smartIntensity").value : "standard",
        purpose: PR.$("#smartPurpose").value,
      } });
      PR.$("#readerDlg").classList.remove("open");
      if (PR.researchTaskMonitor?.track) {
        PR.researchTaskMonitor.track(job, false);
      }
      await waitSmartJob(job);
    } catch (error) {
      start.disabled = false;
      start.textContent = PR.t("开始分析");
      PR.toast(PR.errorText(error));
    }
  });

})(window.PR);
