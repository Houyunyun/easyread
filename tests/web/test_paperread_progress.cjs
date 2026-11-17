const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function setup() {
  const PR = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../easyread/web/js/research/progress.js'), 'utf8'), { window: { PR } });
  return PR.researchProgress;
}
test('milestone progress derives from linked paper state, including saved candidates and missing papers', () => {
  const progress = setup();
  const result = progress.completion({ linked: ['paper:a', 'paper:doi:10/x', 'paper:missing'] }, [
    { id: 'a', status: 'done', progress: 0.1 }, { saved_key: 'doi:10/x', progress: 0.5 }
  ]);
  assert.equal(result.total, 3); assert.equal(result.done, 1); assert.equal(result.percent, 50);
});
test('milestone reminder claims have stable occurrence keys, skip completed/cancelled events, and respect weekly exceptions', () => {
  const progress = setup();
  const m = { id: 'weekly', title: 'Read', start_date: '2026-01-01', end_date: '2026-01-02', recurrence: 'weekly', linked: ['paper:a'] };
  assert.equal(progress.reminders([m], [], '2026-01-08').length, 0);
  const reminder = progress.reminders([m], [], '2026-01-09')[0];
  assert.equal(reminder.key, 'milestone:weekly:2026-01-08');
  assert.equal(progress.reminders([m], [], '2026-01-10')[0].key, reminder.key);
  assert.equal(progress.reminders([m], [{id:'a', status:'done'}], '2026-01-09').length, 0);
  assert.equal(progress.reminders([{...m, exceptions:{ cancelled:['2026-01-08'] }}], [], '2026-01-09').length, 0);
  assert.equal(progress.reminders([{...m, exceptions:{ overrides:{'2026-01-08':{end_date:'2026-01-12'}} }}], [], '2026-01-09').length, 0);
});
