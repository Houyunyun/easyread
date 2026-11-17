const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const esc = value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
function setup() {
  const nodes = new Map();
  const root = { querySelector: selector => { if (!nodes.has(selector)) nodes.set(selector, {}); return nodes.get(selector); } };
  const calls = [], tracked = [];
  const PR = { esc, titleHtml:esc, highlightSnippet:esc, t:(text, vars={}) => text.replace(/\{(\w+)\}/g, (_, key) => vars[key]),
    $:() => root, researchTaskMonitor:{track:task => tracked.push(task)},
    api:async (url, opts) => { calls.push({url, ...opts}); return { results:[{title:'Paper', source_id:'paper1', block:'p2', snippet:'<script>bad()</script>'}], index:{chunks:5, errors:['model missing'], semantic_task:{id:'index-1', kind:'index', state:'running'}}}; } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../easyread/web/js/research/retrieval.js'), 'utf8'), {window:{PR}});
  return { ...PR.researchRetrieval, nodes, calls, tracked };
}
test('retrieval links local evidence to reader block anchors and escapes titles/snippets/Vault paths', () => {
  const ui = setup();
  assert.equal(ui.readerUrl({source_id:'paper1', block:'p2'}), '/read/paper1#b-p2');
  assert.equal(ui.readerUrl({source_id:'paper1', block:'b-p2'}), '/read/paper1#b-p2');
  assert.equal(ui.readerUrl({source_id:'../bad', block:'x'}), '');
  const html = ui.resultsHtml([{title:'<img onerror=x>', snippet:'<script>x</script>', path:'<bad>'}], 'query');
  assert.ok(!html.includes('<img')); assert.ok(!html.includes('<script>')); assert.ok(html.includes('&lt;bad>'));
});
test('retrieval calls original v1 query contract and exposes lexical fallback/model warnings plus background index task', async () => {
  const ui = setup();
  await ui.search('  transformer  ', 'paper', 20);
  assert.equal(ui.calls[0].url, '/api/research/v1/query');
  assert.deepEqual(JSON.parse(JSON.stringify(ui.calls[0].body)), {query:'transformer', kind:'paper', limit:20});
  assert.equal(ui.tracked[0].id, 'index-1');
  assert.match(ui.nodes.get('[data-retrieval-status]').textContent, /model missing/);
  assert.match(ui.nodes.get('[data-retrieval-results]').innerHTML, /\/read\/paper1#b-p2/);
  assert.equal(ui.nodes.get('[type="submit"]').disabled, false);
});
