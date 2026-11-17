const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const esc = value => String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
function setup() {
  const window = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../easyread/web/js/research/path-map.js'), 'utf8'), { window });
  return window.PRPathMap;
}
test('path-map renders distinct sequence/citation edges, escapes titles, and marks selected/start papers', () => {
  const map = setup();
  const steps = ['a', 'b', 'c'].map(key => ({ paper_key: key, role: 'background', paper: { title: '<img onerror=alert(1)>', is_start_paper: key === 'a' } }));
  const html = map.render({ steps, esc, showSequence: true, showRelations: true, selectedKey: 'a', relations: [{source: 'c', target: 'a'}, {source: 'a', target: 'a'}, {source: 'missing', target: 'b'}] });
  assert.equal((html.match(/class="rw-path-edge rw-path-edge-sequence/g) || []).length, 2);
  assert.equal((html.match(/class="rw-path-edge rw-path-edge-citation/g) || []).length, 1);
  assert.match(html, /is-selected is-start/);
  assert.match(html, /aria-pressed="true"/);
  assert.match(html, /&lt;img/);
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('NaN'));
});
test('fit centers the whole map rather than resetting to an overflowing scale of one', () => {
  const map = setup();
  const stage = { clientWidth: 968, clientHeight: 560 };
  const canvas = { style: { getPropertyValue: name => name === '--map-width' ? '2420px' : '560px' } };
  const view = map.fit({ querySelector: selector => selector.endsWith('stage') ? stage : canvas });
  assert.ok(view.scale < .55);
  assert.ok(2420 * view.scale + view.panX * 2 <= stage.clientWidth + .01);
  assert.ok(560 * view.scale + view.panY * 2 <= stage.clientHeight + .01);
  assert.ok(view.panX >= 16 && view.panY >= 16);
});
test('path-map edges meet the rectangles and keyboard/pointer pan preserve view state', () => {
  const map = setup(), events = {}, changes = [];
  const canvas = { style: {}, querySelectorAll: () => [] };
  const stage = { addEventListener: (name, fn) => events[name] = fn, classList: {add() {}, remove() {}}, setPointerCapture() {} };
  map.bind({ querySelector: sel => sel.endsWith('stage') ? stage : canvas }, { scale: 1, panX: 10, panY: 20 }, view => changes.push(view));
  events.keydown({ key: 'ArrowRight', preventDefault() {} });
  assert.equal(changes[0].panX, -14);
  events.pointerdown({ button: 0, clientX: 5, clientY: 5, target: { closest: () => null } });
  events.pointermove({ clientX: 20, clientY: 30 }); events.pointerup();
  assert.equal(changes[1].panX, 1); assert.equal(changes[1].panY, 45);
  assert.match(canvas.style.transform, /translate\(1px,45px\) scale\(1\)/);
  const edge = map.edgePath({x:0,y:0,width:100,height:100}, {x:300,y:0,width:100,height:100});
  assert.match(edge, /^M 100 50 C /); assert.match(edge, /L 299 50$/);
});
