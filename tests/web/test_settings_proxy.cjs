const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function settings() {
  const dialog = { addEventListener() {} };
  const PR = { settingsTabs: {}, t: x => x, esc: x => String(x).replaceAll('"', '&quot;'), $: selector => selector === '#settingsDlg' ? dialog : null };
  const ctx = { window: { PR, addEventListener() {} }, document: { addEventListener() {} }, location: { href: 'https://read.example:8765/read/p#anchor', search: '' }, URL, URLSearchParams };
  for (const file of ['settings.js', 'settings-proxy.js']) {
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../easyread/web/js/common', file), 'utf8'), ctx);
  }
  return PR;
}

test('settings exposes close lifecycle and no separate terminal origin', () => {
  const PR = settings();
  assert.equal(typeof PR.settingsClose, 'function');
  assert.equal(PR.dockerTerminalUrl, undefined);
});

test('proxy form escapes values and collects independent HTTP/HTTPS settings', () => {
  const PR = settings();
  const state = { cfg: { system_proxy: { enabled: true, http_proxy: 'http://proxy:7890', https_proxy: 'http://secure:7890', no_proxy: 'localhost' } } };
  const html = PR.settingsTabs.proxy.render(state);
  assert.ok(html.includes('proxyEnabled'));
  assert.ok(html.includes('http://secure:7890'));
  const values = { '#proxyEnabled': {checked: false}, '#proxyHttp': {value: 'http://one:7890'}, '#proxyHttps': {value: 'http://two:7890'}, '#proxyBypass': {value: 'localhost,example'} };
  PR.settingsTabs.proxy.sync(state, { querySelector: key => values[key] });
  assert.deepEqual(JSON.parse(JSON.stringify(PR.settingsTabs.proxy.collect(state))), {enabled: false, http_proxy: 'http://one:7890', https_proxy: 'http://two:7890', no_proxy: 'localhost,example'});
});
