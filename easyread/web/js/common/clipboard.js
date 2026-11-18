/* Clipboard API on secure origins; selection-based copy for local HTTP readers. */
(function (PR) {
  "use strict";
  PR.copyText = async function (value) {
    const text = String(value ?? "");
    if (navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(text); return; } catch (_) { /* Try the local HTTP fallback. */ }
    }
    const active = document.activeElement, selection = window.getSelection();
    const ranges = selection ? Array.from({ length: selection.rangeCount }, (_, i) => selection.getRangeAt(i).cloneRange()) : [];
    const input = document.createElement("textarea");
    input.value = text; input.readOnly = true;
    input.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0";
    document.body.appendChild(input); input.select(); input.setSelectionRange(0, text.length);
    let copied = false;
    try { copied = document.execCommand("copy"); }
    finally {
      input.remove();
      active?.focus?.({ preventScroll: true });
      if (selection) { try { selection.removeAllRanges(); ranges.forEach(range => selection.addRange(range)); } catch (_) {} }
    }
    if (!copied) throw new Error(PR.t("浏览器不允许自动复制，请选择文字后手动复制。"));
  };
})(window.PR);
