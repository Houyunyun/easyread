/* Progressive enhancement: private reading snapshots, not a second reader. */
(function (PR) {
  "use strict";
  if (location.protocol === "file:" || window.easyreadDesktop || document.getElementById("pr-data")) return;
  const db = globalThis.EasyReadOfflineDB;
  if (!db || !window.isSecureContext || !("serviceWorker" in navigator)) return;
  let scope = "", offline = false, blocked = false, serial = Promise.resolve();
  const key = id => scope + ":" + id;
  const mediaName = () => "easyread-media-" + scope;
  const emit = () => PR.emit("pwa-status");
  const fail = error => { PR.pwa.error = error.message; emit(); };
  const budget = () => PR.ls.get("easyread-offline-budget", 128) * 1024 * 1024;
  const automatic = () => PR.features?.offline_reading !== false;
  const pending = id => {
    try { return Object.keys(localStorage).some(k => k.startsWith("pr-outbox-" + scope + "-" + id + "-") && JSON.parse(localStorage.getItem(k) || "[]").length); }
    catch (_) { return true; } // Corrupt/disabled storage is never permission to discard notes.
  };
  function enqueue(action) {
    const next = serial.then(action); serial = next.catch(fail); return next;
  }
  async function useScope(id) {
    if (!/^[a-f0-9]{24}$/.test(id || "")) return;
    if (scope && scope !== id && PR.pid) {
      blocked = true;
      throw new Error(PR.t("文献库已切换，请重新打开阅读页；未同步修改仍保留在原库。"));
    }
    scope = id; blocked = false;
    await db.put("meta", "active", id);
  }
  async function initScope() { scope = await db.get("meta", "active") || ""; }
  const ready = initScope().catch(fail);
  async function json(url, options = {}) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 6000);
    let response;
    try { response = await fetch(url, {cache: "no-store", ...options, signal: controller.signal}); }
    catch (error) { offline = true; emit(); throw error; }
    finally { clearTimeout(timer); }
    if (!response.ok || response.redirected) {
      offline = false;
      if (response.status === 401 || response.status === 403 || response.redirected) {
        blocked = true;
        if (scope) await db.put("meta", "locked:" + scope, true);
      }
      emit();
      const error = new Error(PR.t("请求失败 {status}", {status: response.status}));
      error.http = true; throw error;
    }
    const data = await response.json();
    if (data.library_id) { await useScope(data.library_id); await db.del("meta", "locked:" + scope); }
    offline = false; emit(); return data;
  }
  function snapshot(data) {
    const clean = {};
    for (const name of ["paper", "reader", "discussion", "layout", "item", "versions"]) clean[name] = data[name] || {};
    // Never retain machine paths, model configuration, tokens or live jobs.
    clean.paper = JSON.parse(JSON.stringify(clean.paper));
    if (clean.paper.meta) delete clean.paper.meta.source_pdf_path;
    return clean;
  }
  async function entries() { await ready; return (await db.all("papers")).filter(p => p.scope === scope); }
  async function remove(id) {
    if (pending(id) || (PR.pid === id && PR.store?.pending)) throw new Error(PR.t("仍有未同步修改，不能清除此文献。"));
    const record = await db.get("papers", key(id));
    if (!record) return;
    const cache = await caches.open(mediaName());
    for (const url of record.urls || []) await cache.delete(url);
    await db.del("papers", key(id)); emit();
  }
  async function trim(extra = 0, keep = "") {
    const records = await entries();
    let total = records.reduce((n, p) => n + p.bytes, 0) + extra;
    for (const p of records.sort((a,b) => a.at - b.at)) {
      if (total <= budget()) break;
      if (p.id === keep || p.pinned || pending(p.id) || p.id === PR.pid) continue;
      await remove(p.id); total -= p.bytes;
    }
    if (total > budget()) throw new Error(PR.t("离线空间不足，请清理缓存或提高容量上限；笔记未被删除。"));
  }
  async function save(id, data, force = false) {
    await ready;
    if (!scope || blocked) return;
    const old = await db.get("papers", key(id));
    if (!old && !force && !automatic()) return;
    const clean = snapshot(data), bytes = new Blob([JSON.stringify(clean)]).size;
    await trim(Math.max(0, bytes - (old?.dataBytes || 0)), id);
    await db.put("papers", key(id), {...old, id, scope, data: clean, dataBytes: bytes,
      bytes: bytes + (old?.mediaBytes || 0), at: Date.now(), title: clean.paper.meta?.title_zh || clean.paper.meta?.title_en || id});
    emit();
  }
  async function read(id) {
    await ready;
    if (!scope || blocked || await db.get("meta", "locked:" + scope)) return null;
    return db.get("papers", key(id));
  }
  async function loadReader(id) {
    await ready;
    try {
      const data = await json("/api/p/" + id + "/state");
      await enqueue(() => save(id, data)).catch(() => {});
      return data;
    } catch (error) {
      if (error.http || blocked) throw error;
      const record = await read(id);
      if (!record) throw new Error(PR.t("这篇文献尚未保存到本设备，请联网后打开。"));
      const data = {...record.data, token: "", engine: "none", job: {}};
      const response = await (await caches.open(mediaName())).match("/p/" + id + "/source.html");
      if (response) data.web_snapshot = await response.text();
      return data;
    }
  }
  let downloading = null;
  async function download(id, pinned = true) {
    if (downloading) throw new Error(PR.t("已有离线保存任务，请等待或取消。"));
    const controller = new AbortController(); downloading = controller;
    try {
      const data = await json("/api/p/" + id + "/state");
      await enqueue(() => save(id, data, true));
      let record = await read(id);
      if (!record) return;
      await db.put("papers", key(id), {...record, pinned: pinned || record.pinned, complete: false});
      const urls = new Set(), prefix = "/p/" + id + "/";
      if (data.paper.meta?.source_type === "web") urls.add(prefix + "source.html");
      for (const block of data.paper.blocks || []) {
        for (const src of [block.src, block.translated_image?.src]) if (src?.startsWith("figures/") && !src.includes("..")) urls.add(prefix + src);
      }
      const noteText = JSON.stringify(data.reader || {});
      for (const match of noteText.matchAll(/\/p\/[A-Za-z0-9_-]+\/chat-media\/[a-f0-9]{32}\.png/g)) if (match[0].startsWith(prefix)) urls.add(match[0]);
      const cache = await caches.open(mediaName());
      let done = 0, missing = (data.paper.meta?.snapshot_external_assets || []).length;
      for (const url of urls) {
        if (controller.signal.aborted) throw new DOMException("Cancelled", "AbortError");
        if (!await cache.match(url)) {
          try {
            const response = await fetch(url, {signal: controller.signal, cache: "no-store"});
            if (!response.ok || response.redirected) throw new Error("Resource unavailable");
            const blob = await response.blob();
            await enqueue(async () => {
              await trim(blob.size, id);
              await cache.put(url, new Response(blob, {headers: {"Content-Type": response.headers.get("Content-Type") || "application/octet-stream"}}));
              record = await db.get("papers", key(id));
              const saved = [...new Set([...(record.urls || []), url])];
              await db.put("papers", key(id), {...record, urls: saved, mediaBytes: (record.mediaBytes || 0) + blob.size, bytes: record.bytes + blob.size});
            });
          } catch (error) { if (controller.signal.aborted) throw error; missing++; }
        }
        PR.pwa.progress = PR.t("正在保存资源 {done}/{total}", {done: ++done, total: urls.size}); emit();
      }
      record = await db.get("papers", key(id));
      await db.put("papers", key(id), {...record, complete: missing === 0, missing, pinned: pinned || record.pinned});
      navigator.storage?.persist?.().catch(() => {});
    } finally { downloading = null; PR.pwa.progress = ""; emit(); }
  }
  PR.pwa = {
    get scope() { return scope; }, get offline() { return offline; }, get blocked() { return blocked; },
    ready, json, loadReader, read, entries, pending,
    save: (id, data) => enqueue(() => save(id, data)),
    remove: id => enqueue(() => remove(id)), download,
    cancel: () => downloading?.abort(),
    async rememberList(data) {
      await ready; await useScope(data.library_id);
      if (!scope) return;
      const {items, research_statuses, version} = data;
      await db.put("lists", scope, {items, research_statuses, version});
    },
    async cachedList() {
      await ready;
      if (!scope || blocked || await db.get("meta", "locked:" + scope)) return null;
      const data = await db.get("lists", scope);
      const papers = await entries(), ids = new Set(papers.map(p => p.id));
      if (!data) return null;
      return {...data, items: data.items.filter(i => ids.has(i.id)), engine: "none", offline: true};
    },
    outboxKey(id) { return scope ? "pr-outbox-" + scope + "-" + id + "-" + PR.uid("tab") : "pr-outbox-" + id; },
    loadOutbox(id) {
      const prefix = "pr-outbox-" + scope + "-" + id + "-";
      const legacy = "pr-outbox-" + id;
      const previous = PR.ls.get(legacy, []);
      if (previous.length) {
        // Adopt pre-PWA pending notes only into the first verified library.
        const owner = PR.ls.get("easyread-legacy-outbox-scope", scope);
        PR.ls.set("easyread-legacy-outbox-scope", owner);
        if (owner === scope && PR.ls.set(prefix + "legacy", previous)) PR.ls.del(legacy);
      }
      const ops = Object.keys(localStorage).filter(k => k.startsWith(prefix)).flatMap(k => JSON.parse(localStorage.getItem(k) || "[]"));
      return [...new Map(ops.map(op => [JSON.stringify(op), op])).values()];
    },
    ack(id, batch) {
      const done = new Set(batch.map(op => JSON.stringify(op))), prefix = "pr-outbox-" + scope + "-" + id + "-";
      for (const k of Object.keys(localStorage).filter(k => k.startsWith(prefix))) {
        const left = JSON.parse(localStorage.getItem(k) || "[]").filter(op => !done.has(JSON.stringify(op)));
        if (left.length) localStorage.setItem(k, JSON.stringify(left)); else localStorage.removeItem(k);
      }
    },
    async beforeLogout() {
      await ready;
      if ((await entries()).some(p => pending(p.id)) || PR.store?.pending) throw new Error(PR.t("仍有未同步修改，请先联网保存或导出后再退出。"));
      for (const p of await entries()) await remove(p.id);
      if (scope) { await db.del("lists", scope); await caches.delete(mediaName()); await db.put("meta", "locked:" + scope, true); }
      PR.ls.del("easyread-library-list");
    },
  };
  PR.on("reader-ready", () => {
    if (!offline && automatic()) download(PR.pid, false).catch(fail);
  });
  window.addEventListener("offline", () => { offline = true; emit(); });
  window.addEventListener("online", () => { PR.poll?.(); PR.lib?.load(); });
  navigator.serviceWorker.register("/sw.js", {scope: "/", updateViaCache: "none"}).then(reg => {
    PR.pwa.registration = reg;
    const update = () => { PR.pwa.updateWaiting = !!reg.waiting; emit(); };
    reg.addEventListener("updatefound", () => reg.installing?.addEventListener("statechange", update)); update();
    return navigator.serviceWorker.ready;
  }).then(() => { PR.pwa.shellReady = true; emit(); }).catch(fail);
})(window.PR);
