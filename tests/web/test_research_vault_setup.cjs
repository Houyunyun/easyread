const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('reader loads the Vault picker and its prompt dependency before research export', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../easyread/web/reader.html'), 'utf8');
  const confirm = html.indexOf('/web/js/common/confirm.js');
  const picker = html.indexOf('/web/js/common/pick-folder.js');
  const exporter = html.indexOf('/web/js/reader/research-export.js');
  assert.ok(confirm >= 0 && picker > confirm && exporter > picker);
});

test('headless reader export prompts for a server-side Vault path and honors cancellation', async () => {
  for (const answer of ['/vault', null]) {
    let click, prompted;
    const calls = [];
    const dialog = {addEventListener(_name, fn) {click = fn;}, classList: {remove() {}}};
    const PR = {state: {paper: {meta: {title_en: 'Test'}}, reader: {paper_note: {body: 'A note'}}},
      pid: 'paper', store: {mode: 'server'}, t: s => s, $: () => dialog,
      $$: () => [{dataset: {exp: 'paper'}, checked: true}], ls: {set() {}},
      notesMarkdown: () => 'A note', toast() {},
      promptText: async opts => {prompted = opts; return answer;},
      api: async (url, options) => {
        calls.push({url, options});
        if (url.endsWith('/status')) return {configured: false};
        if (url.endsWith('/pick-folder')) return {supported: false, path: ''};
        return {configured: true, written: ['Research/note.md']};
      }};
    const context = {window: {PR}};
    for (const file of ['common/pick-folder.js', 'reader/research-export.js']) {
      vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../easyread/web/js', file), 'utf8'), context);
    }
    const button = {disabled: false, innerHTML: 'Export', hasAttribute: x => x === 'data-exp-vault'};
    await click({target: {closest: x => x === '[data-exp-vault]' ? button : null}});
    assert.match(prompted.body, /Docker/);
    const setup = calls.find(c => c.url.endsWith('/setup'));
    const exported = calls.find(c => c.url.endsWith('/export/obsidian'));
    if (answer) {
      assert.equal(setup.options.body.vault, '/vault');
      assert.equal(exported.options.body.documents[0].kind, 'analysis');
    } else {
      assert.equal(setup, undefined);
      assert.equal(exported, undefined);
      assert.equal(button.disabled, false);
    }
  }
});
