const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const source = name => fs.readFileSync(path.join(__dirname, '../../easyread/web/js/reader', name), 'utf8');

function fixture() {
  const nodes = new Map(), callbacks = new Map(), frames = [], scrolls = [], modes = new Set();
  const classes = () => ({add(){},remove(){},toggle(){}});
  const state = {paper:{meta:{source_type:'web',title_en:'Blog'},blocks:[]},reader:{}};
  let current = {op:'progress',block:'last',off:0,ratio:0}, captures = 0;
  const context = {
    scrollY:0,innerHeight:800,
    document:{body:{classList:{add(){},toggle(k,on){if(on)modes.add(k);else modes.delete(k);}}},documentElement:{scrollHeight:11000},
      getElementById(id) {
        const box = id === 'b-head' ? {top:0,height:200} : id === 'b-middle' ? {top:4500,height:500} : {top:10500,height:200};
        return {style:{},getBoundingClientRect:()=>({...box,top:box.top-context.scrollY})};
      }},
    window:{getSelection:()=>({removeAllRanges(){}}),dispatchEvent(){},scrollTo({top}) {context.scrollY=Math.max(0,Math.min(top,10200));scrolls.push(context.scrollY);}},
    MutationObserver:class {observe(){}},ResizeObserver:class {observe(){}},
    requestAnimationFrame:fn=>frames.push(fn),Event:class {},
  };
  const PR = {state,prefs:{},pid:'fixture',store:{mode:'server'},
    t:s=>s,ls:{set(){},get:()=> 'native'},savePrefs(){},
    progressOp:()=>{captures++;return {...current};},restoreProgress:()=>true,saveProgress(){},captureProgress(){},
    applyReadingLanguage(){},applyMarks(){},renderMargin(){},setCurrent(){},hidePopover(){},readingLine:()=>240,readingBlock:()=> 'last',
    on:(name,fn)=>callbacks.set(name,fn),
    $:()=>({before(){},classList:classes()}),
    el(tag,attrs) {
      const node={style:{},classList:classes(),dataset:{},children:[],hidden:false,
        append(child){this.children.push(child);},querySelectorAll(){return this.children;},
        addEventListener(name,fn){this[name]=fn;},setAttribute(){}};
      if (attrs['data-web-layout']) node.dataset.webLayout=attrs['data-web-layout'];
      if(attrs.id)nodes.set(attrs.id,node);
      return node;
    },
  };
  context.window.PR=PR;
  vm.runInNewContext(source('webpage.js'),context);
  callbacks.get('rendered')();
  return {PR,context,scrolls,modes,get captures(){return captures;},
    position(value){current=value;},
    layout(value){nodes.get('webLayoutToggle').children.find(x=>x.dataset.webLayout===value).onclick();},
    flush(){frames.splice(0).forEach(fn=>fn());}};
}

test('a native document still loading never reads the hidden last paragraph as its position', () => {
  const f=fixture();
  assert.deepEqual({...f.PR.progressOp()},{op:'progress',block:'head',off:0,ratio:0});
  f.layout('reader'); f.flush();
  assert.equal(f.context.scrollY,0);
  assert.equal(f.captures,0,'layout switch must not consult hidden projection geometry');
  assert.equal(f.modes.has('web-native'),false);
});

test('returning from a loading native frame preserves the last real reader position', () => {
  const f=fixture();f.layout('reader');f.flush();
  const middle={op:'progress',block:'middle',off:0.4,ratio:0.44};
  f.context.scrollY=4460;f.position(middle);f.layout('native');
  assert.deepEqual({...f.PR.progressOp()},middle);
  f.layout('reader');f.flush();
  assert.equal(f.context.scrollY,4460);
});

test('stale animation-frame alignment cannot overwrite a more recent layout change', () => {
  const f=fixture();f.layout('reader');
  f.context.scrollY=4460;f.position({op:'progress',block:'middle',off:0.4,ratio:0.44});
  f.layout('native');f.flush();
  assert.equal(f.context.scrollY,4460);
});

test('native positions use geometry when image/code records are out of DOM order', () => {
  const text=source('webpage.js');
  const code=text.slice(text.indexOf('  function blockAtLine('),text.indexOf('  function setup()'));
  const context={};vm.runInNewContext(code,context);
  const boxes={paragraph:{top:180,height:100},earlierImage:{top:-300,height:420},later:{top:500,height:100},hidden:{top:0,height:0}};
  const blocks=['paragraph','later','earlierImage','hidden'].map(id=>({id}));
  assert.equal(context.blockAtLine(blocks,240,id=>boxes[id]),'paragraph');
  assert.equal(context.blockAtLine(blocks,-1000,id=>boxes[id]),'head');
});

test('ordinary reading-block detection ignores zero-sized hidden paragraphs', () => {
  const main=source('main.js');
  const code=main.slice(main.indexOf('PR.readingBlock = function'),main.indexOf('PR.currentHeading = function'));
  let elements=[];
  const PR={readingLine:()=>240,$$:()=>elements};
  vm.runInNewContext(code,{PR});
  const block=(id,top,height)=>({dataset:{id},getBoundingClientRect:()=>({top,height})});
  elements=[block('head',0,0),block('first',0,0),block('last',0,0)];
  assert.equal(PR.readingBlock(),'head');
  elements=[block('visible',-40,500),block('hidden',0,0),block('later',500,200)];
  assert.equal(PR.readingBlock(),'visible');
});
