/* Turn comparison evidence markers into safe links after Markdown rendering. */
(function (PR) {
  "use strict";
  const marker = /\[P(\d+)\s*\|\s*(?:(?:(?:第\s*|[页頁]\s*|page\s+|p\.\s*|p\s+)?(\d+)\s*[页頁]?\s*)\|\s*)?([a-zA-Z0-9_.:-]+)(?:\s*\|\s*([^\]]*))?\]/gi;
  function target(source, block) {
    if (!source || !block) return "";
    let id = String(source.id || "");
    if (/^[a-f0-9]{64}$/i.test(id)) id = id.slice(0, 12);
    if (!/^[a-zA-Z0-9_-]{1,128}$/.test(id)) id = /^[a-f0-9]{64}$/i.test(source.sha256 || "") ? source.sha256.slice(0, 12) : "";
    if (!id || !/^[a-zA-Z0-9_.:-]{1,128}$/.test(block)) return "";
    return "/read/" + encodeURIComponent(id) + "#b-" + encodeURIComponent(block);
  }
  function html(content, sources) {
    const box = document.createElement("div");
    box.innerHTML = PR.mdBlocks ? PR.mdBlocks(content || "") : PR.esc(content || "");
    const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT), nodes = [];
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!node.parentElement.closest("a,pre,code,.katex,math")) nodes.push(node);
    }
    for (const node of nodes) {
      const raw = node.nodeValue, fragment = document.createDocumentFragment();
      let position = 0, changed = false;
      marker.lastIndex = 0;
      for (let match; (match = marker.exec(raw));) {
        const source = (sources || [])[Number(match[1]) - 1], href = target(source, match[3]);
        if (!href) continue;
        fragment.append(document.createTextNode(raw.slice(position, match.index)));
        const link = document.createElement("a");
        link.className = "rw-evidence-jump"; link.href = href; link.target = "_blank"; link.rel = "noopener";
        link.textContent = match[0];
        if (match[4]) link.title = match[4].trim();
        fragment.append(link); position = marker.lastIndex; changed = true;
      }
      if (changed) { fragment.append(document.createTextNode(raw.slice(position))); node.replaceWith(fragment); }
    }
    return box.innerHTML;
  }
  PR.researchCitations = { target, html, marker };
})(window.PR);
