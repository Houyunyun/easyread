const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.join(__dirname, '../../easyread/web');
const readerWeb = process.env.PAPERREAD_READER_WEB ? path.resolve(process.env.PAPERREAD_READER_WEB) : web;
const read = (root, file) => fs.readFileSync(path.join(root, 'js', file), 'utf8');
function setup() {
  const nodes = new Map();
  class Element {
    constructor() {
      this.dataset = {}; this.children = []; this.listeners = new Map(); this.queries = new Map(); this.attrs = new Map();
      this.style = {setProperty() {}};
      const classes = new Set();
      this.classList = {add: key => classes.add(key), remove: key => classes.delete(key), contains:key => classes.has(key), toggle:(key, on) => on ? classes.add(key) : classes.delete(key)};
    }
    addEventListener(name, fn) { if (!this.listeners.has(name)) this.listeners.set(name, []); this.listeners.get(name).push(fn); }
    setAttribute(key, value) { this.attrs.set(key, value); }
    getAttribute(key) { return this.attrs.get(key); }
    removeAttribute(key) { this.attrs.delete(key); }
    append(...children) { this.children.push(...children); children.forEach(child => child.parentNode = this); }
    insertBefore(child) { this.append(child); }
    replaceChildren(...children) { this.children = []; this.append(...children); }
    querySelector(selector) { if (!this.queries.has(selector)) this.queries.set(selector, new Element()); return this.queries.get(selector); }
    get lastElementChild() { return this.querySelector('.dock-content'); }
    matches() { return false; }
    focus() {}
  }
  const PR = {t:s => s, ls:{get:(_key, fallback) => fallback || {}, set() {}}, state:{paper:{meta:{}}}, store:{mode:'server'},
    $:selector => { if (!nodes.has(selector)) nodes.set(selector, new Element()); return nodes.get(selector); },
    $$:() => [], icon:() => '', logo:() => '', debounce:fn => fn, on() {}, emit() {}, toast() {}, savePrefs() {},
    setSideSpace() {}, renderResearch() {}, blockAction:() => false
  };
  const context = vm.createContext({window:{PR, addEventListener() {}}, document:{body:new Element(), createElement:() => new Element(), addEventListener() {}}, matchMedia:() => ({addEventListener() {}}), location:{protocol:'http:'}});
  vm.runInContext(read(web, 'common/features.js'), context);
  return {PR, context, nodes};
}
test('research defaults on, opt-in autohide stays off, and unknown features retain EasyRead compatibility', () => {
  const {PR} = setup();
  assert.equal(PR.FEATURES.find(([id]) => id === 'research')[2], true);
  assert.equal(PR.feature('research'), true);
  assert.equal(PR.feature('autohide_tabs'), false);
  assert.equal(PR.feature('unregistered-existing-feature'), true);
  assert.equal(PR.keyAction('r'), 'research');
  PR.applyUi({features:{research:false}}, false);
  assert.equal(PR.feature('research'), false);
  assert.equal(PR.keyAction('r'), null);
});
const hasReaderPort = fs.existsSync(path.join(readerWeb, 'js/reader/planner.js'));
test('real reader button, dock and R shortcut can open the default-enabled research panel', {
  skip: !hasReaderPort && !process.env.PAPERREAD_READER_WEB ? 'Isolated workspace lane: set PAPERREAD_READER_WEB to exercise the reader port before integration.' : false
}, () => {
  const {PR, context, nodes} = setup();
  const load = file => vm.runInContext(read(readerWeb, file), context, {filename:file});
  load('common/reader-typography.js');
  load('reader/reader-dock.js');
  const planner = read(readerWeb, 'reader/planner.js');
  const end = planner.indexOf('  function paperTitle()');
  assert.ok(end > 0, 'planner entrypoints must be present');
  // Load the actual availability/toggle functions, without unrelated analysis UI or API startup.
  vm.runInContext(planner.slice(0, end) + '\n})(window.PR);', context, {filename:'reader/planner.js'});
  load('reader/panels.js'); load('reader/keys.js');
  PR.applyFeatures();
  assert.equal(nodes.get('[data-act="research"]').hidden, false);
  const button = {dataset:{act:'research'}, closest:selector => selector === '[data-act]' ? button : null};
  for (const listener of nodes.get('#bar').listeners.get('click')) listener({target:button});
  assert.equal(PR.dockVisible('research'), true, 'topbar research button opens the panel');
  PR.closeDockTab('research');
  assert.equal(PR.runAction(PR.keyAction('r')), true);
  assert.equal(PR.dockVisible('research'), true, 'R shortcut opens the panel');
  PR.closeDockTab('research'); PR.openSide('research');
  assert.equal(PR.dockVisible('research'), true, 'dock entry opens the panel');
  PR.applyUi({features:{research:false}}, false); PR.applyFeatures();
  assert.equal(nodes.get('[data-act="research"]').hidden, true);
  assert.equal(PR.dockVisible('research'), false);
});
