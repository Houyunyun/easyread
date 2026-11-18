const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function load() {
  const PR = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../easyread/web/js/research/citations.js'), 'utf8'), {window: {PR}});
  return PR.researchCitations;
}
test('comparison links use library IDs, not the full PDF SHA', () => {
  const c = load();
  assert.equal(c.target({id: 'paper-1', sha256: 'a'.repeat(64)}, 'p2-1'), '/read/paper-1#b-p2-1');
  assert.equal(c.target({sha256: 'a'.repeat(64)}, 'p2-1'), '/read/aaaaaaaaaaaa#b-p2-1');
  assert.equal(c.target({id: 'a'.repeat(64)}, 'p2-1'), '/read/aaaaaaaaaaaa#b-p2-1');
  assert.equal(c.target({id: '../escape'}, 'p2-1'), '');
  assert.equal(c.target({id: 'paper-1'}, 'x"><script>'), '');
});
test('evidence marker recognition supports generated page labels in each UI language', () => {
  for (const text of ['[P1 | 页 4 | p4-1 | evidence]', '[P1 | 第4頁 | p4-1 | evidence]', '[P1 | page 4 | p4-1 | evidence]', '[P1 | p. 4 | p4-1 | evidence]', '[P1 | p4-1 | evidence]']) {
    const match = load().marker.exec(text);
    assert.ok(match, text);
    assert.equal(match[3], 'p4-1');
  }
});
