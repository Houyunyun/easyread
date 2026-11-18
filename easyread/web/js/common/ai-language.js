/* Describe the saved output language, never infer it from the current UI. */
(function (PR) {
  "use strict";
  PR.normalizeOutputTarget = function (value) {
    const code = String(value || "").trim().replace(/_/g, "-").toLowerCase();
    if (["zh-tw", "zh-hk", "zh-mo", "zh-hant"].includes(code)) return "zh-Hant";
    if (["zh", "zh-cn", "zh-sg", "zh-hans"].includes(code)) return "zh";
    return (PR.TARGETS || []).some(([id]) => id === code) ? code : "";
  };
  PR.aiOutputLanguage = function (value) {
    const code = PR.normalizeOutputTarget(value);
    const name = (PR.TARGETS || []).find(([id]) => id === code)?.[1];
    return name ? PR.t("生成语言：{language}", { language: name }) : "";
  };
})(window.PR);
