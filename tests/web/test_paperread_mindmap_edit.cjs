const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup({mode = 'server', fail = false, savedDraft = null} = {}) {
  let listener, click, pendingTimer, draft = savedDraft;
  const status = {textContent:''}, actions = {hidden:true}, calls = [], notices = [];
  const box = {innerHTML:'', querySelector:selector => selector === '[role=status]' ? status : actions,
    addEventListener:(_type, fn) => {click = fn;}};
  const data = {nodeData:{id:'me-root',topic:'Root',children:[{id:'one',topic:'Method $x^2$'}]}};
  const instance = {getData:() => data, bus:{addListener:(_event,fn) => {listener = fn;}, removeListener(){}},
    enableEdit(){this.editable = true;}, disableEdit(){this.editable = false;}};
  const PR = {pid:'paper-id',paperKey:'paper-id',store:{mode},state:{},t:s=>s,esc:s=>s,toast:s=>notices.push(s),
    ls:{get:()=>draft,set:(_key,value)=>{draft=value;return true;}},
    api:async (url,options)=>{calls.push({url,...options});if(fail)throw new Error('conflict');return {...options.body,revision:2};}};
  const context = {window:{PR},document:{createElement:()=>box},setTimeout:fn=>{pendingTimer=fn;return 1;},clearTimeout:()=>{pendingTimer=null;}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../easyread/web/js/reader/mindmap-edit.js'),'utf8'),context);
  const editor = PR.mindmapEdits.attach({appendChild(){}},instance,{mermaid:'mindmap\n Root',revision:1});
  return {PR, data, editor, status, calls, notices, instance, changed:()=>listener({name:'finishEdit'}),
    click:action=>click({target:{closest:()=>({dataset:{mapEdit:action},setAttribute(){}})},stopPropagation(){}}),
    draft:()=>draft, timer:()=>pendingTimer};
}

test('mindmap edits persist immediately as a draft and save with optimistic revision', async () => {
  const r = setup();
  await r.click('toggle'); assert.equal(r.instance.editable,true);
  r.data.nodeData.children[0].topic = 'Edited (method) "quoted" $x^2$'; r.changed();
  assert.match(r.draft().mermaid,/Edited/); assert.ok(r.timer());
  await r.editor.save();
  assert.equal(r.calls[0].url,'/api/research/v2/paper/paper-id/mindmap/save');
  assert.equal(r.calls[0].body.revision,1); assert.equal(r.draft(),null);
  assert.equal(r.PR.state.mindmap.revision,2); assert.equal(r.status.textContent,'已保存');
});

test('failed mindmap synchronization retains the draft and exposes retry rather than losing edits', async () => {
  const r = setup({fail:true}); r.changed(); await r.editor.save();
  assert.match(r.draft().mermaid,/Method/); assert.match(r.status.textContent,/同步失敗/);
  assert.deepEqual(r.notices,['conflict']);
  assert.equal(r.PR.mindmapEdits.current({mermaid:'older'}).mermaid,r.draft().mermaid);
});

test('offline mindmaps save locally without any API request and restore after opening again', async () => {
  const r = setup({mode:'static'}); r.changed(); await r.editor.save();
  assert.equal(r.calls.length,0); assert.match(r.status.textContent,/本瀏覽器/);
  const restored = setup({mode:'static',savedDraft:r.draft()});
  assert.equal(restored.PR.mindmapEdits.current({}).mermaid,r.draft().mermaid);
});

test('quoted Mermaid serialization preserves math, shape-like labels and quotes when parsed', () => {
  const r = setup();
  r.data.nodeData.topic = 'Method(x)'; r.data.nodeData.children[0].topic = '"quoted" \\frac{x}{y}';
  const source = r.PR.mindmapEdits.toMermaid(r.data);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../easyread/web/js/reader/mindmap-view.js'),'utf8'),{window:{PR:r.PR}});
  const parsed = r.PR.mindmap.parseToData(source);
  assert.equal(parsed.nodeData.topic,r.data.nodeData.topic);
  assert.equal(parsed.nodeData.children[0].topic,r.data.nodeData.children[0].topic);
});
