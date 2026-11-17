const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function setup(api = async () => ({}), search = '') {
  const calls = [], tracked = [], toasts = [], fields = new Map();
  const PR = { lang: "en", t: (text, vars = {}) => text.replace(/\{(\w+)\}/g, (_, key) => vars[key] ?? ''), esc: String,
    $: selector => fields.get(selector) || null, $$: () => [],
    api: async (url, opts) => { calls.push({ url, ...opts }); return api(url, opts); },
    toast: text => toasts.push(text), researchTaskMonitor: { track: (...args) => tracked.push(args) } };
  const context = { window: { PR }, document: { addEventListener() {} }, location: { search }, URL, URLSearchParams,
    history: { replaceState() {} }, setTimeout: () => 0, clearTimeout() {} };
  // Exercise the source's actual workflow functions without a browser rendering layer.
  const source = fs.readFileSync(path.join(__dirname, '../../easyread/web/js/research/workspace.js'), 'utf8').replace('  init();\n})(window.PR);', `
    renderPath = renderComparisons = renderExplore = renderBoard = () => {};
    switchTab = tab => { S.tab = tab; };
    window.workflow = { S, generatePath, applyPathSnapshot, movePathPaper, updatePathRelations, workCard, startComparison, saveTaskFields, mergeResults, loadRelation, search };
  })(window.PR);`);
  vm.runInNewContext(source, context);
  return { ...context.window.workflow, calls, tracked, toasts, fields };
}
test('reading path jobs retain source v2 request fields and task-monitor handoff', async () => {
  const task = { id: 'path-1', kind: 'reading-path', state: 'queued' };
  const s = setup(async () => ({task}), '?mode=path&start_title=Seed&start_doi=10.1/seed');
  s.fields.set('#rw-path-topic', {value:'Transformers'}); s.fields.set('#rw-path-goal', {value:'Build foundations'});
  s.S.candidates = [{ paper: {title:'Candidate'} }]; s.S.results = [{title:'Search result'}];
  await s.generatePath();
  const call = s.calls[0];
  assert.equal(call.url, '/api/research/v2/reading-path/tasks'); assert.equal(call.method, 'POST');
  assert.equal(call.body.start_paper.doi, '10.1/seed'); assert.equal(call.body.goal, 'Build foundations');
  assert.equal(call.body.candidate_papers[0].title, 'Candidate'); assert.equal(call.body.search_results.length, 1);
  assert.equal(s.tracked[0][0], task); assert.equal(s.tracked[0][1], true);
});
test('path reorder carries optimistic revision, applies server snapshot and retains state on conflict', async () => {
  const snapshot = { path_id:'saved', revision:4, results:[{paper_key:'a'},{paper_key:'b'}] };
  const s = setup(async (url, opts) => ({ path:{ ...snapshot, revision:5, results:opts.body.paper_keys.map(paper_key => ({paper_key})) } }));
  s.applyPathSnapshot(snapshot); await s.movePathPaper('b', -1);
  assert.equal(s.calls[0].url, '/api/research/v2/reading-path/reorder');
  assert.equal(s.calls[0].body.revision, 4); assert.equal(s.calls[0].body.paper_keys.join(','), 'b,a');
  assert.equal(s.S.pathRevision, 5); assert.equal(s.S.pathResults[0].paper_key, 'b');
  const failed = setup(async () => { throw new Error('revision conflict'); });
  failed.applyPathSnapshot(snapshot); await failed.movePathPaper('b', -1);
  assert.equal(failed.S.pathResults[0].paper_key, 'a'); assert.equal(failed.toasts[0], 'revision conflict');
});
test('comparison validates full text and retains v1 paper/dimension/focus contract', async () => {
  const s = setup(async url => url.endsWith('/status') ? {configured:true} : {id:'compare', kind:'comparison', state:'queued'});
  s.S.compareSelection = new Set(['a','b']); s.S.items = [{id:'a', parsed_blocks:1}, {id:'b', parsed_blocks:0}];
  await s.startComparison(); assert.equal(s.calls.length, 0);
  s.S.items[1].parsed_blocks = 2; s.S.compareFocus = 'data efficiency';
  await s.startComparison();
  const call = s.calls.find(call => call.url === '/api/research/v1/comparison');
  assert.equal(call.body.paper_ids.join(','), 'a,b'); assert.equal(call.body.focus, 'data efficiency');
  assert.ok(call.body.dimensions.length); assert.equal(s.tracked[0][0].id, 'compare');
});
test('board updates distinguish stored library papers from PDF-pending saved candidates', async () => {
  const s = setup();
  await s.saveTaskFields({id:'local'}, {status:'reading', manual_order:100});
  await s.saveTaskFields({id:'saved:doi:10/x', saved:true, saved_key:'doi:10/x'}, {status:'organizing', archived:false});
  assert.equal(s.calls[0].url, '/api/research/v2/item'); assert.equal(s.calls[0].body.id, 'local');
  assert.equal(s.calls[1].body.saved_key, 'doi:10/x'); assert.equal(s.calls[1].body.archived, false);
});
test('discovery merges duplicate DOI providers and relation exploration preserves seed metadata', async () => {
  const s = setup(async () => ({results:[{title:'Related'}], seed_id:'W123', seed_title:'Seed', seed_keywords:['attention'], relation:true}));
  s.mergeResults([{doi:'https://doi.org/10/x', title:'Paper', abstract:'Full abstract'}], 'OpenAlex');
  s.mergeResults([{doi:'10/x', title:'Paper', abstract:'', pdf_url:'https://example.org/p.pdf'}], 'Crossref');
  assert.equal(s.S.results.length, 1); assert.equal(s.S.results[0].abstract, 'Full abstract');
  assert.equal(s.S.results[0].sources.join(','), 'OpenAlex,Crossref');
  await s.loadRelation('W123', 'references', 'Seed', '10/x');
  assert.match(s.calls[0].url, /^\/api\/research\/v2\/work\/W123\?/);
  assert.match(s.calls[0].url, /relation=references/); assert.match(s.calls[0].url, /start_doi=10%2Fx/);
  assert.equal(s.S.relationRequest.keywords[0], 'attention');
});

test('discovery cards use the shared language string and reject scriptable source URLs', () => {
  const s = setup();
  const html = s.workCard({title:'Paper', url:'javascript:alert(1)', sources:['OpenAlex','Crossref']});
  assert.match(html, /OpenAlex, Crossref/); assert.ok(!html.includes('javascript:'));
  assert.match(s.workCard({title:'Paper', url:'https://example.org/paper'}), /href="https:\/\/example.org\/paper"/);
});
