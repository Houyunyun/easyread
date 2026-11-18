/* PWA shell only. API responses and writes always go to the server. */
/*PWA_CONFIG*/
importScripts("/web/js/common/pwa-db.js");
const SHELL = "easyread-shell-" + BUILD;
const LIBRARY = "/pwa/shell/library", READER = "/pwa/shell/reader";
const allowed = new Set(ASSETS);
self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL);
    // Bounded concurrency avoids flooding a slow connection during installation.
    const urls = [...ASSETS, LIBRARY, READER];
    async function fill() {
      while (urls.length) {
        const url = urls.shift(), response = await fetch(url, {cache: "reload"});
        if (!response.ok || response.redirected) throw new Error("Incomplete application shell: " + url);
        await cache.put(url, response);
      }
    }
    await Promise.all(Array.from({length: 4}, fill));
  })());
});
self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) if (name.startsWith("easyread-shell-") && name !== SHELL) await caches.delete(name);
    await self.clients.claim();
  })());
});
async function network(request) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 6000);
  try { return await fetch(request, {signal: controller.signal}); }
  finally { clearTimeout(timer); }
}
self.addEventListener("fetch", event => {
  const request = event.request, url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (allowed.has(url.pathname)) {
    event.respondWith((async () => (await (await caches.open(SHELL)).match(url.pathname)) || fetch(request))());
    return;
  }
  if (/^\/p\/[A-Za-z0-9_-]+\/(figures\/[^/]+|chat-media\/[a-f0-9]{32}\.png)$/.test(url.pathname)) {
    event.respondWith((async () => {
      try { return await network(request); }
      catch (_) {
        const db = self.EasyReadOfflineDB, scope = await db.get("meta", "active");
        if (!scope || await db.get("meta", "locked:" + scope)) return Response.error();
        return (await (await caches.open("easyread-media-" + scope)).match(url.pathname)) || Response.error();
      }
    })());
    return;
  }
  const shell = url.pathname === "/" || url.pathname === "/index.html" ? LIBRARY
    : /^\/read\/[A-Za-z0-9_-]+$/.test(url.pathname) ? READER : null;
  if (request.mode === "navigate" && shell) {
    event.respondWith((async () => {
      try { return await network(request); } // Never conceal an HTTP error or login redirect.
      catch (_) { return (await (await caches.open(SHELL)).match(shell)) || Response.error(); }
    })());
  }
});
