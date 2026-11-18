const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function fixture(engine='claude') {
  const calls=[];
  const PR={settingsTabs:{},t:x=>x,esc:x=>String(x).replaceAll('<','&lt;'),opt:()=>'',confirm:async()=>true,settingsRender(){},$:()=>({}),
    api:async(url,args)=>{calls.push({url,args});return {settings:args.body,skills:[],native:{path:'/native/settings'}};}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../easyread/web/js/common/settings-qa-cli.js'),'utf8'),{window:{PR},Object,Promise});
  const s={tab:'qa_cli',cfg:{embedded_terminal:true},qaCli:{engine,loading:false,tools:['shell','web_search'],skills:[],native:{path:'/native/settings'},settings:{mode:'default',skills:false,mcp:false,web_search:true,web_fetch:true,allowed_tools:[],sandbox:'read-only',skill_overrides:{}}}};
  return {PR,s,calls,tab:PR.settingsTabs.qa_cli,root:{querySelectorAll:()=>[],querySelector:()=>null}};
}

test('provider subpages render scope, modes, skills and native setting link',()=>{
  for(const engine of ['claude','codex']) {
    const f=fixture(engine), html=f.tab.render(f.s);
    assert.ok(html.includes('data-qa-mode="default"'));
    assert.ok(html.includes('data-qa-mode="full"'));
    assert.ok(html.includes('data-qa-mode="custom"'));
    assert.ok(html.includes('不影响翻译'));
    assert.ok(html.includes('data-qa-import'));
    assert.ok(html.includes('/native/settings'));
    assert.ok(html.includes('data-qa-terminal'));
  }
});

test('saving uses only the QA endpoint and preserves engine separation',async()=>{
  const f=fixture('codex');f.s.qaCli.settings.mode='full';
  await f.tab.save(f.s,f.root);
  assert.equal(f.calls.length,1);
  assert.equal(f.calls[0].url,'/api/chat/cli/codex');
  assert.equal(f.calls[0].args.body.mode,'full');
  assert.equal(f.calls[0].args.body.engine,undefined);
});

test('toggling a skill back restores inheritance instead of leaving a stale override',()=>{
  const f=fixture();f.s.qaCli.skills=[{id:'native:x',enabled:true}];f.s.qaCli.initialOverrides={};
  const box={dataset:{qaSkill:'native:x'},checked:false};
  f.root.querySelectorAll=selector=>selector==='[data-qa-skill]'?[box]:[];
  f.tab.sync(f.s,f.root);assert.equal(f.s.qaCli.settings.skill_overrides['native:x'],false);
  box.checked=true;f.tab.sync(f.s,f.root);assert.equal(Object.hasOwn(f.s.qaCli.settings.skill_overrides,'native:x'),false);
});

test('cancelled full-mode confirmation does not broaden capabilities',async()=>{
  const f=fixture();f.PR.confirm=async()=>false;
  const mode={dataset:{qaMode:'full'}};
  await f.tab.click({target:{closest:s=>s==='[data-qa-mode]'?mode:null}},f.s,f.root);
  assert.equal(f.s.qaCli.settings.mode,'default');assert.equal(f.calls.length,0);
});
