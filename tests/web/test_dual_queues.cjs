const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const {page} = require('../helpers/library_page.cjs');

function helpers(lang = 'zh') {
  const dict = lang === 'zh' ? {} : JSON.parse(fs.readFileSync('easyread/web/i18n/' + lang + '.json', 'utf8'));
  const PR = {lang, t: s => dict[s] || s};
  vm.runInNewContext(fs.readFileSync('easyread/web/js/common/util.js', 'utf8'), {
    window: {PR, addEventListener() {}}, document: {addEventListener() {}},
  });
  return {jobPreparing: PR.jobPreparing, canReserveTranslation: PR.canReserveTranslation, formatJobMessage: PR.formatJobMessage};
}

test('stage labels distinguish preparations, reservations, translations, originals and images in every locale', () => {
  for (const lang of ['zh', 'en', 'zh-Hant']) {
    const h = helpers(lang);
    const plain = {state: 'queued', phase: 'prepare', type: 'prepare', translate: false, message: '排队中'};
    const reserved = {...plain, type: 'translate', translate: true};
    const model = {...reserved, phase: 'model'};
    const labels = [h.formatJobMessage(plain), h.formatJobMessage({...plain, state: 'running'}),
      h.formatJobMessage(reserved), h.formatJobMessage({...reserved, state: 'running'}),
      h.formatJobMessage(model), h.formatJobMessage({...model, type: 'read', read: true})];
    assert.equal(new Set(labels).size, 6, lang);
    if (lang === 'en') assert.ok(labels.every(s => !/[一-鿿]/.test(s)));
    assert.equal(h.canReserveTranslation(plain), true);
    assert.equal(h.canReserveTranslation({...plain, state: 'running'}), true);
    for (const job of [reserved, model, {...plain, state: 'done'}, {...model, type: 'figure-images'}, undefined])
      assert.equal(h.canReserveTranslation(job), false);
    assert.match(h.formatJobMessage({...model, type: 'figure-images', message: '译图排队中'}), lang === 'en' ? /figure/i : /图|圖/);
  }
});

test('details offer reservation during preparation but not after one is already requested', async () => {
  const p = page();
  const item = {id: 'paper1', title_en: 'Test paper', added: '2026-11-18', pages: 0, done_pages: 0,
    job: {state: 'running', phase: 'prepare', type: 'prepare', translate: false}};
  p.library([item]);
  await p.boot();
  p.PR.lib.items = [item];
  Object.assign(p.PR, helpers(), {usageShort: () => '', relTime: () => '', titleHtml: String});
  p.run('library/detail.js');
  p.PR.lib.selected = item.id;
  p.PR.renderDetail();
  assert.match(p.node('#detail').innerHTML, /data-d="translate">预约翻译/);
  assert.match(p.node('#detail').innerHTML, /正在预处理 PDF/);
  const calls = [];
  p.PR.startTranslation = async id => {calls.push(id); return true;};
  p.PR.toast = () => {};
  p.PR.lib.load = async () => {};
  await p.node('#detail').click({target: {closest: s => s === '[data-d]' ? {dataset: {d: 'translate'}} : null}});
  assert.deepEqual(calls, ['paper1']);
  Object.assign(p.PR.lib.byId(item.id).job, {type: 'translate', translate: true});
  p.PR.renderDetail();
  assert.doesNotMatch(p.node('#detail').innerHTML, /data-d="translate"/);
  assert.match(p.node('#detail').innerHTML, /已预约模型任务/);
});

test('batch translation includes queued and running preparation while skipping existing reservations', async () => {
  const p = page();
  const items = [
    {id: 'queued', job: {type: 'prepare', state: 'queued', phase: 'prepare'}},
    {id: 'running', job: {type: 'prepare', state: 'running', phase: 'prepare'}},
    {id: 'reserved', job: {type: 'translate', state: 'queued', phase: 'prepare', translate: true}},
    {id: 'model', job: {type: 'translate', state: 'running', phase: 'model'}},
    {id: 'ready', job: {state: 'done'}},
    {id: 'done', pages: 2, done_pages: 2, job: {state: 'done'}},
  ];
  p.library(items);
  await p.boot();
  p.PR.lib.items = items;
  const calls = [];
  Object.assign(p.PR, helpers(), {translationDialog: async () => 'Keep symbols', toast() {},
    api: async (url, options) => {calls.push({url, body: options.body}); return {};}});
  p.PR.lib.engine = 'codex';
  p.PR.lib.picked = new Set(items.map(i => i.id));
  p.PR.lib.load = async () => {};
  p.run('library/batch.js');
  p.node('#batchBar').click({target: {closest: () => ({dataset: {b: 'translate'}})}});
  await p.flush();
  assert.deepEqual(calls.map(c => c.url), ['/api/p/queued/translate', '/api/p/running/translate', '/api/p/ready/translate']);
  assert.ok(calls.every(c => c.body.translation_extra === 'Keep symbols'));
});
