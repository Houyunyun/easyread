/* Save the report currently being viewed, without replacing an existing paper note. */
(function (PR) {
  "use strict";
  PR.appendDeepReport = async function (report, button) {
    if (button?.disabled || !report?.markdown) return;
    if (PR.store.mode !== "server") { PR.toast(PR.t("离线页面请复制报告后粘贴到笔记。")); return; }
    if (button) button.disabled = true;
    try {
      await PR.finishPanelNote?.();
      if (!await PR.flushPending()) throw new Error(PR.t("修改尚未保存，请稍后重试"));
      await PR.api("/api/research/v2/paper/" + encodeURIComponent(PR.pid) + "/deep-analysis/apply-to-note", {
        method: "POST", body: { markdown: report.markdown }
      });
      await PR.poll();
      PR.toast(PR.t("报告已追加到论文笔记，原有内容已保留。"));
    } catch (error) { PR.toast(PR.errorText ? PR.errorText(error) : String(error.message || error)); }
    finally { if (button) button.disabled = false; }
  };
})(window.PR);
