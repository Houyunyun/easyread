const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../../easyread/web/js/common/presence.js"), "utf8");

function run(protocol) {
  const sockets = [], timers = [];
  vm.runInNewContext(source, {
    location: { protocol, host: "easyread.example:8443" },
    WebSocket: class { constructor(url) { this.url = url; sockets.push(this); } },
    setTimeout(fn, delay) { timers.push({ fn, delay }); },
  });
  return { sockets, timers };
}

test("presence uses ws for HTTP and wss for HTTPS", () => {
  assert.equal(run("http:").sockets[0].url, "ws://easyread.example:8443/api/presence");
  assert.equal(run("https:").sockets[0].url, "wss://easyread.example:8443/api/presence");
});

test("offline exports do not open a presence socket", () => {
  assert.equal(run("file:").sockets.length, 0);
});

test("HTTPS presence reconnects after a disconnect", () => {
  const { sockets, timers } = run("https:");
  sockets[0].onclose();
  assert.equal(timers[0].delay, 1000);
  timers[0].fn();
  assert.equal(sockets[1].url, sockets[0].url);
});
