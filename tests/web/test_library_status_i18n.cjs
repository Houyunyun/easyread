const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {page} = require('../helpers/library_page.cjs');
const web = path.join(__dirname, '../../easyread/web');

function localize(PR, lang) {
  const dict = lang === 'zh' ? {} : JSON.parse(fs.readFileSync(path.join(web, 'i18n', lang + '.json'), 'utf8'));
  const document = {body:null, title:'EasyRead', documentElement:{lang:lang === 'zh' ? 'zh-CN' : lang, dataset:{langChoice:lang}, style:{setProperty(){}}},
    getElementById:() => ({textContent:JSON.stringify(dict)}), querySelector:() => null, addEventListener(){}};
  vm.runInNewContext(fs.readFileSync(path.join(web, 'js/common/i18n.js'), 'utf8'), {window:{PR}, document});
  return key => dict[key] || key;
}

const statuses = () => [
  {id:'unread', label:'待閱讀', builtin:1}, {id:'reading', label:'閱讀中', builtin:1},
  {id:'organizing', label:'待整理', builtin:1}, {id:'done', label:'已完成', builtin:1},
  {id:'paused', label:'暫停', builtin:1}, {id:'custom-1', label:'设置', builtin:0},
  {id:'custom-2', label:'我的繁體分類', builtin:0}, {id:'custom-3', label:'<b>不要解析</b>', builtin:0},
];

test('persisted Traditional defaults follow all locales in sidebar, pills, titles and sidebar settings', async () => {
  for (const lang of ['zh', 'en', 'zh-Hant']) {
    const p = page(), expected = localize(p.PR, lang), raw = statuses();
    const items = raw.filter(s => s.id !== 'paused').map((s, i) => ({id:'p'+i, title_zh:'我的繁體論文', tags:[], status:s.id, added:'2026-01-01'}));
    const before = JSON.stringify(raw);
    p.library(items, ['自訂分類']);
    p.setLibraryRead(() => ({items, research_statuses:raw, engine:'none'}));
    await p.boot(); p.renderSidebar();
    for (const [id, key] of [['unread','待阅读'],['reading','阅读中'],['organizing','待整理'],['done','已完成']]) {
      assert.equal(p.PR.lib.VIEWS.find(v => v[0] === id)[1], expected(key), lang + '/' + id);
      assert.ok(p.node('#side').innerHTML.includes(expected(key)));
      assert.ok(p.node('#list').innerHTML.includes('>' + expected(key) + '</span>'));
    }
    assert.equal(p.PR.lib.VIEWS.find(v => v[0] === 'starred')[1], expected('星标'));
    assert.ok(p.node('#side').innerHTML.includes(expected('已封存')));
    assert.ok(p.node('#side').innerHTML.includes('自訂分類'));
    assert.ok(p.node('#side').innerHTML.includes('&lt;b>不要解析&lt;/b>'));
    assert.ok(p.node('#list').innerHTML.includes('我的繁體論文'));
    assert.equal(p.PR.lib.VIEWS.find(v => v[0] === 'custom-1')[1], '设置');
    p.PR.lib.view = 'reading'; p.PR.lib.render();
    assert.equal(p.node('#viewTitle').textContent, expected('阅读中'));
    p.PR.settingsTabs = {}; p.run('library/settings-library.js');
    const settings = p.PR.settingsTabs.library.render({});
    assert.ok(settings.includes(expected('待整理')));
    assert.ok(settings.includes(expected('阅读中')));
    assert.ok(settings.includes('我的繁體分類'));
    assert.equal(JSON.stringify(raw), before, 'display must not rewrite stored labels');
  }
});

test('status editor preserves untouched localized defaults through redraws and saves', () => {
  for (const lang of ['zh', 'en', 'zh-Hant']) {
    const PR = {}; localize(PR, lang);
    for (const status of statuses()) {
      const displayed = PR.researchStatusLabel(status);
      assert.equal(PR.captureStatusLabel(status, displayed), status.label);
      assert.equal(PR.captureStatusLabel(status, undefined), status.label);
      assert.equal(PR.captureStatusLabel(status, '新的自訂名稱'), '新的自訂名稱');
      const colorOnly = {...status, color:'#123456', label:PR.captureStatusLabel(status, displayed)};
      assert.equal(PR.researchStatusLabel(colorOnly), displayed);
    }
  }
});

test('reader return tooltips localize cached built-in view labels but preserve custom category names', () => {
  for (const lang of ['zh', 'en', 'zh-Hant']) {
    for (const [view, label, source] of [['reading','閱讀中','阅读中'], ['starred','星標','星标']]) {
      const p = page(), expected = localize(p.PR, lang);
      const state = {view, tag:null, q:'', sort:'opened', label, scroll:0, offset:null};
      p.location.href = p.PR.libraryNav.readerUrl('paper1', state);
      p.PR.libraryNav.readerBack('paper1');
      assert.equal(p.node('#backBtn').title, p.PR.t('返回“{name}”', {name:expected(source)}));
      assert.equal(state.label, label);
    }
    const p = page(); localize(p.PR, lang);
    p.location.href = p.PR.libraryNav.readerUrl('paper2', {view:'all', tag:'我的繁體分類', q:'', sort:'opened', label:'全部', scroll:0, offset:null});
    p.PR.libraryNav.readerBack('paper2');
    assert.ok(p.node('#backBtn').title.includes('我的繁體分類'));
  }
});

test('all library status surfaces use the safe label helper rather than translating arbitrary names', () => {
  for (const file of ['library/sidebar.js', 'library/app.js', 'library/detail.js', 'library/batch.js']) {
    const source = fs.readFileSync(path.join(web, 'js', file), 'utf8');
    assert.match(source, /PR\.researchStatusLabel\(/, file);
    assert.doesNotMatch(source, /PR\.t\((?:s|status)\.label\)/, file);
  }
  const editor = fs.readFileSync(path.join(web, 'js/research/workspace.js'), 'utf8');
  assert.match(editor, /escAttr\(displayStatus\(s\)\)/);
  assert.match(editor, /PR\.captureStatusLabel\(s,/);
});
