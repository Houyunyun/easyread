const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('easyread/web/js/reader/ink.js', 'utf8');
const safari = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.6 Safari/605.1.15';
const chrome = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36';
function fixture(userAgent) {
  let paints = 0, commits = 0, uid = 0;
  const events = () => ({listeners:{},addEventListener(k,f){(this.listeners[k] ||= []).push(f);},emit(k,e={}){for(const f of this.listeners[k] || []) f(e);}});
  const node = () => ({...events(),dataset:{},style:{},classList:{toggle(){},remove(){}},children:[],setAttribute(k,v){this[k]=v;},getAttribute(k){return this[k];},append(child){this.children.push(child);}});
  const layer = {...node(),replaceChildren(){this.children=[];paints++;},setPointerCapture(){}};
  const tools = {...node(),querySelector(){return null;}}, toggle = node();
  const stage = {clientWidth:100,scrollHeight:1000,scrollTop:0,getBoundingClientRect:()=>({left:0,top:0})};
  const block = {dataset:{id:'p1'},innerText:'text',getBoundingClientRect:()=>({left:0,top:0,bottom:100,width:100,height:100})};
  const document = {...events(),hidden:false,getElementById:id=>({inkLayer:layer,inkTools:tools,inkToggle:toggle,stage,paper:block,'b-p1':block}[id]),createElementNS:node};
  const window = {...events(),navigator:{userAgent}};
  const reader = {ink:{i1:{id:'i1',anchor:'p1',ref:[100,100],textHash:'text',points:[[1,1],[20,20]],color:'#1d1d1d',width:2}},stickers:{s1:{id:'s1'}}};
  const PR = {state:{reader},readerInput:{configure(){},acceptsCanvas:e=>e.pointerType==='mouse'},$$:()=>[block],on(){},t:s=>s,hashText:s=>s,uid:()=>`new-${++uid}`,nowIso:()=>'',commit(op){commits++;if(op.op==='ink')reader.ink[op.stroke.id]=op.stroke;},
    renderStickers(svg,_sr,_host,phase){if(phase==='front' && reader.stickers.s1)svg.append({dataset:{sticker:'s1'}});}};
  // Use the production debounce implementation, including its flush/cancel behavior.
  const util = fs.readFileSync('easyread/web/js/common/util.js','utf8');
  vm.runInNewContext(util.slice(util.indexOf('  PR.debounce ='),util.indexOf('  PR.throttle =')),{PR,setTimeout,clearTimeout});
  window.PR = PR;
  vm.runInNewContext(source,{window,document,ResizeObserver:class{observe(){}}});
  return {PR,window,document,layer,reader,paints:()=>paints,commits:()=>commits};
}

test('Safari repaints saved ink and stickers once after a scroll burst without writing data', t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const f=fixture(safari), before=JSON.stringify(f.reader);
  f.window.emit('scroll');t.mock.timers.tick(80);f.window.emit('scroll');t.mock.timers.tick(119);
  assert.equal(f.paints(),0);
  t.mock.timers.tick(1);
  assert.equal(f.paints(),1);
  assert.ok(f.layer.children.some(n=>n.dataset.stroke==='i1'));
  assert.ok(f.layer.children.some(n=>n.dataset.sticker==='s1'));
  assert.equal(JSON.stringify(f.reader),before);assert.equal(f.commits(),0);
  f.reader.ink={};f.window.emit('scroll');f.window.emit('scrollend');
  assert.equal(f.paints(),2,'sticker-only pages recover too');
  t.mock.timers.tick(200);assert.equal(f.paints(),2,'scrollend cancels the pending fallback');
  f.document.hidden=true;f.window.emit('scroll');t.mock.timers.tick(200);assert.equal(f.paints(),2);
});

test('Safari delayed repaint cannot clear a newly started stroke preview', t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const f=fixture(safari);f.PR.setInkActive(true);f.window.emit('scroll');
  f.layer.emit('pointerdown',{pointerType:'mouse',button:0,pointerId:1,clientX:10,clientY:10,preventDefault(){}});
  f.layer.emit('pointermove',{pointerType:'mouse',buttons:1,pointerId:1,clientX:30,clientY:30});
  const paints=f.paints(), preview=f.layer.children.at(-1);
  t.mock.timers.tick(200);f.window.emit('scrollend');
  assert.equal(f.paints(),paints);assert.equal(f.layer.children.at(-1),preview);
  f.layer.emit('pointerup',{pointerId:1});assert.equal(f.commits(),1);
});

test('Chrome retains its original scroll path without extra repaint scheduling', t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const f=fixture(chrome);
  assert.equal(f.window.listeners.scroll.length,1);
  assert.equal(f.window.listeners.scrollend,undefined);
  f.window.emit('scroll');t.mock.timers.tick(500);
  assert.equal(f.paints(),0);assert.equal(f.commits(),0);
});
