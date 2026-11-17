/* Only local reader/workspace URLs may be restored into privileged shell frames. */
(function (global) {
  "use strict";
  const KEY = "easyread-tabs-session";
  function reader(raw, id) {
    try {
      const url = new URL(raw, location.origin);
      const match = url.pathname.match(/^\/read\/([a-zA-Z0-9_-]+)$/);
      return url.origin === location.origin && match && match[1] !== "library" && (!id || id === match[1])
        ? { id: match[1], url: url.href } : null;
    } catch (_) { return null; }
  }
  function library(raw) {
    try {
      const url = new URL(raw, location.origin);
      return url.origin === location.origin && ["/", "/index.html", "/research"].includes(url.pathname)
        ? url.pathname + url.search + url.hash : "/";
    } catch (_) { return "/"; }
  }
  function clean(data) {
    const seen = new Set();
    const tabs = (Array.isArray(data?.tabs) ? data.tabs : []).flatMap(tab => {
      const target = reader(tab?.url, tab?.id);
      if (!target || seen.has(target.id)) return [];
      seen.add(target.id);
      return [{ ...target, title: String(tab.title || ""), group: typeof tab.group === "string" ? tab.group : null }];
    });
    const groups = (Array.isArray(data?.groups) ? data.groups : []).filter(g => g && typeof g.id === "string").map(g => ({
      id: g.id, title: String(g.title || g.id), color: /^#[a-f0-9]{6}$/i.test(g.color) ? g.color : "#64748b", collapsed: !!g.collapsed
    }));
    return { tabs, groups, active: seen.has(data?.active) ? data.active : "library", libraryUrl: library(data?.libraryUrl || "/") };
  }
  const storageKey = token => KEY + (token ? ":" + token : "");
  function load(token = "") {
    try { return clean(JSON.parse(sessionStorage.getItem(storageKey(token)) || "{}")); }
    catch (_) { return clean(null); }
  }
  function save(data, token = "") {
    try { sessionStorage.setItem(storageKey(token), JSON.stringify(clean(data))); } catch (_) { /* Reading still works with storage disabled. */ }
  }
  global.PRTabsSession = { reader, library, clean, load, save };
})(window);
