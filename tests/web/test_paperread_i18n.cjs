const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.join(__dirname, '../../easyread/web');
const read = file => fs.readFileSync(path.join(web, file), 'utf8');
const dictionaries = Object.fromEntries(['en', 'zh-Hant'].map(lang => [lang, JSON.parse(read(`i18n/${lang}.json`))]));
const esc = value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const placeholders = text => [...text.matchAll(/\{\w+\}/g)].map(match => match[0]).sort();
function setup(lang = 'en') {
  const nodes = new Map(), events = new Map(), calls = [], translations = [];
  function node() {
    const children = new Map();
    return { innerHTML: '', textContent: '', hidden: true, value: '', classList: {toggle() {}, add() {}, remove() {}},
      addEventListener() {}, querySelectorAll: () => [],
      querySelector(selector) {
        if (selector === '[data-modal-save]' && !this.innerHTML.includes('data-modal-save')) return null;
        if (selector === '[data-progress-form]' && !this.innerHTML.includes('data-progress-form')) return null;
        if (!children.has(selector)) children.set(selector, node());
        return children.get(selector);
      },
      elements: Object.fromEntries(['id','start_date','end_date','title'].map(name => [name, {value:'', focus() {}}])), reset() {}
    };
  }
  for (const view of ['explore','board','candidates','summaries','path','progress','comparisons']) nodes.set(`[data-view='${view}']`, node());
  nodes.set('#rw-modal', node());
  const PR = {lang, esc, titleHtml:esc, mdBlocks:esc, icon:() => '',
    t(text, vars) {
      translations.push(text);
      const translated = dictionaries[lang][text] || text;
      return vars ? translated.replace(/\{(\w+)\}/g, (match, key) => vars[key] ?? match) : translated;
    },
    $:(selector, root) => root?.querySelector ? root.querySelector(selector) : nodes.get(selector) || null,
    $$:() => [], on() {}, toast() {},
    api:async (url, opts) => { calls.push({url, ...opts}); return {title:'Test publication', container_title:'Journal', year:2026, type:'article', doi:'10.1/test'}; }
  };
  const context = {window:{PR}, document:{addEventListener(name, handler) { if (!events.has(name)) events.set(name, []); events.get(name).push(handler); }},
    location:{search:''}, URL, URLSearchParams, setTimeout:() => 0, clearTimeout() {}, history:{replaceState() {}}};
  const source = read('js/research/workspace.js').replace('  init();\n})(window.PR);', `
    window.workspace = { S, renderExplore, renderBoard, renderCandidates, renderSummaries, renderComparisonSetup,
      openModal, CLOSE_ONLY, queueModal, taskCard, quickPeekEditor, searchSources };
  })(window.PR);`);
  vm.runInNewContext(source, context);
  return {PR, context, nodes, events, calls, translations, ...context.window.workspace};
}
function noChinese(html) { assert.doesNotMatch(html, /[\u4e00-\u9fff]/); }

test('research literal keys exist in both dictionaries with matching placeholders', () => {
  const keys = new Set();
  for (const file of fs.readdirSync(path.join(web, 'js/research')).filter(file => file.endsWith('.js'))) {
    const source = read('js/research/' + file);
    for (const match of source.matchAll(/PR\.t\(("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g)) {
      const key = vm.runInNewContext(match[1]);
      if (/[\u4e00-\u9fff]/.test(key)) keys.add(key);
    }
    assert.doesNotMatch(source, /固定使用繁體中文|i18n-dom:/);
  }
  assert.ok(keys.size > 450);
  for (const key of keys) {
    for (const lang of ['en', 'zh-Hant']) {
      assert.ok(dictionaries[lang][key], `${lang}: ${key}`);
      assert.deepEqual(placeholders(dictionaries[lang][key]), placeholders(key), `${lang}: ${key}`);
    }
    noChinese(dictionaries.en[key]);
  }
});

test('dynamic discovery labels, placeholders, provider states and empty results are English', () => {
  const s = setup(), host = s.nodes.get("[data-view='explore']");
  s.renderExplore(); noChinese(host.innerHTML);
  assert.match(host.innerHTML, /data-mode="topic"/);
  s.S.mode = 'conference'; s.S.venueBusy = true;
  s.S.venueOptions = [{id:'S123', name:'Journal', type:'journal', works_count:3}];
  s.S.loadingSearch = true; s.renderExplore(); noChinese(host.innerHTML);
  s.S.loadingSearch = false; s.S.results = [{title:'A paper', id:'W1'}];
  s.S.providerStatus = {OpenAlex:'loading', Crossref:'failed', DBLP:'done'};
  s.renderExplore(); noChinese(host.innerHTML);
  assert.match(host.innerHTML, /value="publication_date:desc"/);
});

test('discovery Enter submits the search rather than activating a mode button', () => {
  const s = setup();
  s.renderExplore();
  const html = s.nodes.get("[data-view='explore']").innerHTML;
  const modeButtons = [...html.matchAll(/<button\b[^>]*data-mode="[^"]+"[^>]*>/g)];
  assert.equal(modeButtons.length, 2);
  for (const [button] of modeButtons) assert.match(button, /type="button"/);
  assert.equal((html.match(/type="submit"/g) || []).length, 1);
});

test('board and candidate UI localizes statuses without translating custom data or identifiers', () => {
  const s = setup();
  s.S.statuses = [{id:'unread', label:'待閱讀', builtin:true, color:'#123456'}, {id:'custom-1', label:'自己的标签', builtin:false}];
  s.S.saved = [{paper_key:'doi:10/x', metadata:{title:'Candidate'}, status:'unread', pdf_state:'running'}];
  s.renderBoard();
  const board = s.nodes.get("[data-view='board']").innerHTML;
  assert.match(board, /data-column="unread"/); assert.match(board, /data-column="custom-1"/);
  assert.ok(board.includes('自己的标签')); noChinese(board.replaceAll('自己的标签', 'Custom'));
  assert.equal(s.S.statuses[0].label, '待閱讀');
  const peek = s.quickPeekEditor({status:'unread', tags:[]});
  assert.ok(peek.includes('自己的标签')); noChinese(peek.replaceAll('自己的标签', 'Custom'));
  s.S.saved = []; s.S.candidates = [{paper:{title:'Candidate'}, paper_key:'test', summary_status:'running'}];
  s.renderCandidates(); noChinese(s.nodes.get("[data-view='candidates']").innerHTML);
  s.S.summaries = [{paper:{title:'Summary'}, paper_key:'test'}];
  s.renderSummaries(); noChinese(s.nodes.get("[data-view='summaries']").innerHTML);
});

test('modal close sentinel preserves close-only behavior while all displayed controls translate', () => {
  const s = setup(), modal = s.nodes.get('#rw-modal');
  assert.equal(s.CLOSE_ONLY, '關閉');
  s.openModal('Title', '<p>Body</p>', async () => {}, s.CLOSE_ONLY, {headerClose:true});
  assert.ok(!modal.innerHTML.includes('data-modal-save')); noChinese(modal.innerHTML);
  s.openModal('Title', '<p>Body</p>', async () => {});
  assert.ok(modal.innerHTML.includes('data-modal-save')); noChinese(modal.innerHTML);
  s.queueModal({title:'Candidate'}); noChinese(modal.innerHTML);
  assert.match(modal.innerHTML, /id="q-interested"/);
});

test('comparison labels translate but protocol dimension values and custom text remain unchanged', () => {
  const s = setup();
  s.S.compareDimensions.add('自己的维度');
  const html = s.renderComparisonSetup();
  assert.match(html, /data-compare-dimension="研究問題"/);
  assert.ok(html.includes(dictionaries.en['研究問題']));
  assert.ok(html.includes('自己的维度'));
  assert.ok(s.S.compareDimensions.has('研究問題'));
  assert.ok(!s.S.compareDimensions.has(dictionaries.en['研究問題']));
  const visible = html.replace(/data-compare-dimension="[^"]*"/g, '').replaceAll('自己的维度', 'Custom');
  noChinese(visible);
});

test('publication-check dialogs and asynchronous error messages translate after initial render', async () => {
  const s = setup();
  const button = {dataset:{action:'publication-check', doi:'10.1/test'}, closest(selector) { return selector === '[data-action]' ? this : null; }};
  for (const handler of s.events.get('click')) await handler({target:button});
  assert.ok(s.nodes.get('#rw-modal').innerHTML.includes('Test publication'));
  noChinese(s.nodes.get('#rw-modal').innerHTML); noChinese(button.textContent);
  assert.ok(s.calls[0].url.includes('/publication-check?doi=10.1%2Ftest'));
  s.nodes.set('#rw-venue-query', {value:''});
  await s.searchSources();
  assert.equal(s.S.error, dictionaries.en['請輸入期刊或會議名稱。']);
});

test('progress fields translate once and recurrence/follow enum values remain unchanged in both locales', () => {
  for (const lang of ['en','zh-Hant']) {
    const s = setup(lang);
    const source = read('js/research/progress.js').replace('  PR.researchProgress = {', '  PR.progressTest = { state, mount, renderLists };\n  PR.researchProgress = {');
    vm.runInNewContext(source, s.context);
    s.PR.progressTest.mount();
    const html = s.nodes.get("[data-view='progress']").innerHTML;
    assert.ok(html.includes(dictionaries[lang]['目标名称']));
    assert.match(html, /value="weekly"/); assert.match(html, /value="author"/);
    assert.equal(s.translations.filter(key => key === '目标名称').length, 1);
    s.PR.progressTest.state.milestones = [{id:'goal', title:'My goal', start_date:'2026-01-01', end_date:'2026-01-02', recurrence:'weekly'}];
    s.PR.progressTest.state.follows = [{id:'follow', kind:'topic', value:'自定义主题', label:'My topic'}];
    s.PR.progressTest.renderLists();
    const host = s.nodes.get("[data-view='progress']");
    const milestones = host.querySelector('[data-progress-milestones]').innerHTML;
    const follows = host.querySelector('[data-progress-follows]').innerHTML;
    assert.ok(milestones.includes(dictionaries[lang]['每周']));
    assert.ok(follows.includes('自定义主题'));
    assert.ok(follows.includes(dictionaries[lang]['探索主题']));
    if (lang === 'en') { noChinese(html); noChinese(milestones); noChinese(follows.replaceAll('自定义主题', 'Custom topic')); }
  }
});
