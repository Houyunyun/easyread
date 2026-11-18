const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const generatedMap = (overrides = {}) => ({paper_id:'paper-id', target:'en', source_sha256:'a'.repeat(64),
  mermaid:'mindmap\n  root((Generated))', revision:1, ...overrides});

function setup({mode = 'server', fail = false, storage = new Map(), generated = generatedMap(), api = null} = {}) {
  let listener, click, pendingTimer, lastKey;
  const status = {textContent:''}, actions = {hidden:true}, calls = [], notices = [], saved = [];
  const box = {innerHTML:'', querySelector:selector => selector === '[role=status]' ? status : actions,
    addEventListener:(_type, fn) => {click = fn;}};
  const data = {nodeData:{id:'me-root',topic:'Root',children:[{id:'one',topic:'Method $x^2$'}]}};
  const instance = {getData:() => data, bus:{addListener:(_event,fn) => {listener = fn;}, removeListener(){}},
    enableEdit(){this.editable = true;}, disableEdit(){this.editable = false;}};
  const PR = {pid:'paper-id',paperKey:'paper-id',store:{mode},state:{mindmap:generated},t:s=>s,esc:s=>s,toast:s=>notices.push(s),
    ls:{get:(key,fallback)=>storage.get(key) ?? fallback,set:(key,value)=>{lastKey=key;storage.set(key,value);return true;}},
    api:async (url,options)=>{calls.push({url,...options});if(fail)throw new Error('conflict');
      return api ? api(url,options) : {...options.body,paper_id:'paper-id',revision:options.body.revision+1};}};
  const context = {window:{PR},document:{createElement:()=>box},setTimeout:fn=>{pendingTimer=fn;return 1;},clearTimeout:()=>{pendingTimer=null;}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../easyread/web/js/reader/mindmap-edit.js'),'utf8'),context);
  const editor = PR.mindmapEdits.attach({appendChild(){}},instance,generated,result=>saved.push(result));
  return {PR, data, editor, status, calls, notices, saved, instance, storage, changed:()=>listener({name:'finishEdit'}),
    click:action=>click({target:{closest:()=>({dataset:{mapEdit:action},setAttribute(){}})},stopPropagation(){}}),
    draft:()=>storage.get(lastKey), draftKey:()=>lastKey, timer:()=>pendingTimer};
}

test('mindmap edits persist immediately with identity and save with optimistic revision', async () => {
  const r = setup();
  await r.click('toggle'); assert.equal(r.instance.editable,true);
  r.data.nodeData.children[0].topic = 'Edited (method) "quoted" $x^2$'; r.changed();
  assert.match(r.draft().mermaid,/Edited/); assert.ok(r.timer());
  assert.equal(r.draft().paper_key,'paper-id'); assert.equal(r.draft().target,'en');
  assert.equal(r.draft().source_sha256,'a'.repeat(64)); assert.equal(r.draft().mode,'server');
  await r.editor.save();
  assert.equal(r.calls[0].url,'/api/research/v2/paper/paper-id/mindmap/save');
  assert.equal(r.calls[0].body.revision,1); assert.equal(r.draft(),null);
  assert.equal(r.calls[0].body.target,'en'); assert.equal(r.calls[0].body.source_sha256,'a'.repeat(64));
  assert.equal(r.PR.state.mindmap.revision,2); assert.equal(r.status.textContent,'已保存');
});

test('failed mindmap synchronization retains the exact scoped draft and exposes retry', async () => {
  const r = setup({fail:true}); r.changed(); const draft = r.draft(); await r.editor.save();
  assert.equal(r.draft(),draft); assert.match(r.status.textContent,/同步失败/);
  assert.deepEqual(r.notices,['conflict']);
  assert.equal(r.PR.mindmapEdits.current(generatedMap()).mermaid,draft.mermaid);
});

test('offline drafts restore only in the same static mode, identity and revision', async () => {
  const r = setup({mode:'static'}); r.changed(); await r.editor.save();
  assert.equal(r.calls.length,0); assert.match(r.status.textContent,/本浏览器/);
  const restored = setup({mode:'static',storage:r.storage});
  assert.equal(restored.PR.mindmapEdits.current(generatedMap()).mermaid,r.draft().mermaid);
  const online = setup({storage:r.storage});
  assert.equal(online.PR.mindmapEdits.current(generatedMap()).mermaid,generatedMap().mermaid);
});

test('an unsynced English draft cannot overlay or overwrite a Simplified map at the same revision', async () => {
  const r = setup({fail:true}); r.data.nodeData.topic = 'English draft'; r.changed();
  const englishKey = r.draftKey(), englishDraft = r.draft();
  const chinese = generatedMap({target:'zh',mermaid:'mindmap\n  root((简体内容))'});
  assert.equal(r.PR.mindmapEdits.current(chinese),chinese);
  r.PR.state.mindmap = chinese;
  r.data.nodeData.topic = 'Older English editor still open'; r.changed();
  assert.equal(r.PR.state.mindmap,chinese);
  await r.editor.save();
  assert.equal(r.calls[0].body.target,'en'); assert.equal(r.calls[0].body.revision,1);
  assert.equal(r.PR.state.mindmap,chinese); assert.equal(r.saved.length,0);
  assert.match(r.storage.get(englishKey).mermaid,/Older English/);
  const zhEditor = setup({generated:chinese,storage:r.storage});
  await zhEditor.editor.save(); assert.equal(zhEditor.calls.length,0);
  zhEditor.changed(); assert.notEqual(zhEditor.draftKey(),englishKey);
  assert.equal(r.storage.get(englishKey).target,englishDraft.target);
});

test('source changes and regeneration do not automatically restore stale drafts', async () => {
  const r = setup(); r.changed(); const draft = r.draft();
  for (const map of [generatedMap({source_sha256:'b'.repeat(64)}), generatedMap({revision:2})]) {
    assert.equal(r.PR.mindmapEdits.current(map),map);
    const next = setup({generated:map,storage:r.storage});
    await next.editor.save(); assert.equal(next.calls.length,0);
    assert.equal(r.storage.get(r.draftKey()),draft);
  }
});

test('legacy and mismatched identity records are retained but never automatically applied', async () => {
  const legacy = {mermaid:'mindmap\n  root((Legacy English))',revision:1};
  const storage = new Map([['easyread-mindmap-draft-paper-id',legacy]]);
  const r = setup({storage});
  assert.equal(r.PR.mindmapEdits.current(generatedMap()).mermaid,generatedMap().mermaid);
  await r.editor.save(); assert.equal(r.calls.length,0); assert.equal(storage.get('easyread-mindmap-draft-paper-id'),legacy);
  r.changed(); const valid = r.draft();
  for (const mismatch of [{target:'zh'}, {source_sha256:'b'.repeat(64)}, {paper_id:'other'}, {paper_key:'other'}, {mode:'static'}]) {
    const draft = {...valid,...mismatch}; storage.set(r.draftKey(),draft);
    const next = setup({storage});
    assert.equal(next.PR.mindmapEdits.current(generatedMap()).mermaid,generatedMap().mermaid);
    await next.editor.save(); assert.equal(next.calls.length,0); assert.equal(storage.get(r.draftKey()),draft);
  }
});

test('new manual maps use identity from an empty response and revision zero', async () => {
  const empty = generatedMap({mermaid:undefined,revision:undefined});
  const r = setup({generated:empty}); r.changed(); await r.editor.save();
  assert.equal(r.calls[0].body.revision,0); assert.equal(r.calls[0].body.target,'en');
  const missing = setup({generated:{mermaid:'mindmap\n  root((Legacy))'}});
  missing.changed(); await missing.click('save');
  assert.equal(missing.calls.length,0); assert.equal(missing.storage.size,0);
  assert.match(missing.status.textContent,/缺少语言或来源标识/);
});

test('save retains the attach-time paper and static mode, not current globals', async () => {
  const r = setup(); r.changed(); const key = r.draftKey();
  r.PR.pid = r.PR.paperKey = 'another-paper'; r.PR.state.mindmap = generatedMap({paper_id:'another-paper'});
  await r.editor.save();
  assert.equal(r.calls[0].url,'/api/research/v2/paper/paper-id/mindmap/save');
  assert.equal(r.PR.state.mindmap.paper_id,'another-paper'); assert.equal(r.saved.length,0);
  assert.equal(r.storage.get(key),null);
  const offline = setup({mode:'static'}); offline.changed(); const offlineKey = offline.draftKey();
  offline.PR.store.mode = 'server'; await offline.editor.save();
  assert.equal(offline.calls.length,0); assert.equal(offline.draftKey(),offlineKey);
  assert.equal(offline.draft().mode,'static');
});

test('a mismatched save response cannot discard a draft or relabel its output', async () => {
  const r = setup({api:async (_url,options)=>({...options.body,paper_id:'paper-id',target:'zh',revision:2})});
  r.changed(); const draft = r.draft(); await r.editor.save();
  assert.equal(r.draft(),draft); assert.equal(r.PR.state.mindmap.target,'en'); assert.equal(r.saved.length,0);
  assert.match(r.status.textContent,/同步失败/);
});

test('an edit made during synchronization keeps its draft and adopts the new base revision', async () => {
  let resolve;
  const r = setup({api:(_url,options)=>new Promise(done=>{resolve=()=>done({...options.body,paper_id:'paper-id',revision:2});})});
  r.changed(); const saving = r.editor.save();
  r.data.nodeData.topic = 'Newer edit'; r.changed(); resolve(); await saving;
  assert.equal(r.draft().revision,2); assert.match(r.draft().mermaid,/Newer edit/);
  assert.match(r.PR.mindmapEdits.current(r.PR.state.mindmap).mermaid,/Newer edit/); assert.equal(r.saved.length,1);
  assert.equal(r.PR.mindmapEdits.current(r.saved[0]).mermaid,r.draft().mermaid);
  assert.equal(r.PR.mindmapEdits.current(generatedMap({revision:2})).mermaid,r.draft().mermaid);
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
