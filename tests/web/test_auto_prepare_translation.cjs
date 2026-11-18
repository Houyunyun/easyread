const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');

test('automatic preparation translation setting renders, autosaves and collects a boolean', () => {
  let saved = 0;
  const field = {type: 'checkbox', checked: true, dataset: {k: 'auto_translate_after_prepare'}, matches: () => false};
  const PR = {t: x => x, esc: String, settingsTabs: {}, $: () => ({addEventListener() {}}),
    $$: () => [field], saveModelSettings: () => saved++};
  const ctx = {window: {PR, addEventListener() {}}, document: {addEventListener() {}}, location: {search: ''}, URLSearchParams};
  for (const name of ['settings.js', 'settings-chat.js', 'settings-translation.js'])
    vm.runInNewContext(fs.readFileSync('easyread/web/js/common/' + name, 'utf8'), ctx);
  PR.saveModelSettings = () => saved++;
  PR.agentClis = {};
  const state = {cfg: {claude: {}, codex: {}, openai: {}}};
  assert.match(PR.translationSettingsHtml(state), /data-k="auto_translate_after_prepare">/);
  PR.settingsTabs.chat.change({target: field}, state);
  assert.equal(saved, 1);
  assert.equal(PR.settingsTabs.engine.collect(state).auto_translate_after_prepare, true);
  assert.match(PR.translationSettingsHtml(state), /data-k="auto_translate_after_prepare" checked/);
  field.checked = false;
  PR.settingsTabs.chat.change({target: field}, state);
  assert.equal(PR.settingsTabs.engine.collect(state).auto_translate_after_prepare, false);
});

test('stop-model selection includes pending automatic handoffs but excludes plain preparations', () => {
  const PR = {lib: {}, $: () => ({}), t: x => x};
  vm.runInNewContext(fs.readFileSync('easyread/web/js/library/stop-jobs.js', 'utf8'), {window: {PR}});
  for (const state of ['queued', 'running']) {
    assert.equal(PR.lib.modelBusy({job: {type: 'prepare', state, auto_translate_pending: true}}), true);
    assert.equal(PR.lib.modelBusy({job: {type: 'prepare', state, auto_translate_pending: false}}), false);
  }
  assert.equal(PR.lib.modelBusy({job: {type: 'prepare', state: 'done', auto_translate_pending: true}}), false);
});

test('automatic handoff labels are translated and distinct from explicit reservations', () => {
  for (const lang of ['en', 'zh-Hant']) {
    const dict = JSON.parse(fs.readFileSync('easyread/web/i18n/' + lang + '.json', 'utf8'));
    const PR = {lang, t: key => dict[key] || key};
    vm.runInNewContext(fs.readFileSync('easyread/web/js/common/util.js', 'utf8'), {
      window: {PR, addEventListener() {}}, document: {addEventListener() {}},
    });
    const job = {type: 'prepare', phase: 'prepare', state: 'queued', auto_translate_pending: true};
    const queued = PR.formatJobMessage(job);
    const running = PR.formatJobMessage({...job, state: 'running'});
    assert.notEqual(queued, running);
    assert.notEqual(queued, PR.formatJobMessage({...job, auto_translate_pending: false, translate: true}));
    if (lang === 'en') assert.doesNotMatch(queued + running, /[一-鿿]/);
  }
});
