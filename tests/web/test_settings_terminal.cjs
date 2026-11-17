const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function fixture() {
  const pending = [], calls = [], mount = { replaceChildren(frame) { this.frame = frame; } };
  const state = { tab: 'terminal', cfg: { embedded_terminal: true } };
  const root = { classList: { contains: () => state.tab !== 'closed' }, querySelector: s => s === '#terminalMount' ? mount : {} };
  const PR = { settingsTabs: {}, t: x => x, esc: x => x, toast() {}, confirm: async () => true, settingsRender() {},
    api(url, options) { calls.push({url,body:options?.body}); if (url.endsWith('/open')) return new Promise(resolve => pending.push(resolve)); return Promise.resolve({}); },
  };
  const document = { createElement: () => ({ src: '', setAttribute() {}, getAttribute() { return this.src; }, remove() {} }) };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../easyread/web/js/common/settings-terminal.js'), 'utf8'), { window: { PR }, document });
  const button = { dataset: { cliAction: 'shell' }, disabled: false };
  return { PR, state, root, pending, calls, mount, button, click: () => PR.settingsTabs.terminal.click({ target: { closest: s => s === '[data-cli-action]' ? button : null } }, state, root) };
}

test('terminal startup is single-flight before the first await', async () => {
  const f = fixture(), first = f.click();
  await f.click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.pending.length, 1);
  f.pending[0]({url: '/terminal/one/'}); await first;
  assert.equal(f.mount.frame.src, '/terminal/one/');
});

test('stale open completion cleans only its own terminal, not the replacement', async () => {
  const f = fixture(), first = f.click();
  await new Promise(resolve => setImmediate(resolve));
  await f.PR.settingsTabs.terminal.dispose();
  const second = f.click();
  await new Promise(resolve => setImmediate(resolve));
  f.pending[1]({url: '/terminal/new/'}); await second;
  f.pending[0]({url: '/terminal/old/'}); await first;
  assert.equal(f.mount.frame.src, '/terminal/new/');
  const closes = f.calls.filter(x => x.url.endsWith('/close'));
  assert.equal(closes.at(-1).body.url, '/terminal/old/');
  await f.PR.settingsTabs.terminal.dispose();
  assert.equal(f.calls.at(-1).body.url, '/terminal/new/');
  assert.equal(f.PR.settingsTabs.terminal.active(), false);
});
