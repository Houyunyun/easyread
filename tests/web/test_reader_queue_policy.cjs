const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {test} = require('node:test');

test('reader updates live auto-translation policy without a job file version change', async () => {
  let enabled = false, parts = 0;
  const events = [];
  const PR = {t: s => s, uid: () => 'client', emit: (name, value) => events.push([name,value]),
    ls: {get: (_key, fallback) => fallback, set: () => true}};
  const job = () => ({type:'prepare', phase:'prepare', state:'running', allow_auto_translate:true, auto_translate_pending:enabled});
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../easyread/web/js/reader/store.js'),'utf8'), {
    window:{PR, addEventListener(){}}, location:{pathname:'/read/paper'},
    document:{getElementById:()=>null}, setTimeout(){}, clearTimeout(){},
    fetch:async url => ({ok:true,json:async () => {
      if (url.endsWith('/state')) return {paper:{meta:{}},reader:{},job:job(),versions:{job:'unchanged'}};
      if (url.endsWith('/part/job')) { parts++; return {version:'unchanged',data:job()}; }
      return {job:'unchanged',auto_translate_pending:enabled};
    }}),
  });
  await PR.load(); await PR.poll(); assert.equal(parts,0);
  enabled = true; await PR.poll();
  assert.equal(parts,1); assert.equal(PR.state.job.auto_translate_pending,true);
  enabled = false; await PR.poll();
  assert.equal(parts,2); assert.equal(PR.state.job.auto_translate_pending,false);
  assert.equal(PR.state.versions.job,'unchanged');
  assert.equal(events.filter(([name, names]) => name === 'remote' && names.includes('job')).length,2);
});
