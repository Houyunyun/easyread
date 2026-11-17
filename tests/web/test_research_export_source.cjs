const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('Obsidian mindmap export keeps editable Mermaid and formulas alongside a PNG', () => {
  const PR = {state: {paper: {meta: {title_en: 'Test paper'}}, reader: {}}, pid: 'test-paper', t: s => s,
    $: () => ({addEventListener() {}})};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../easyread/web/js/reader/research-export.js'), 'utf8'), {window: {PR}});
  const mermaid = 'mindmap\n  root((Edited root))\n    $y=Wx$';
  const doc = PR.researchExport.documents({pick: {mindmap: true}, order: ['mindmap'], chat: [], mindmap: mermaid, mindmapPngBase64: 'UE5H'})[0];
  assert.match(doc.body, /!\[\[Test paper-mind-map\.png\]\]/);
  assert.ok(doc.body.includes('```mermaid\n' + mermaid + '\n```'));
  assert.equal(doc.attachment.content_base64, 'UE5H');
});
