const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { registerTabWindows } = require('../../electron/desktop-tab-windows.cjs');
function setup() {
  const handlers = new Map(), windows = [], errors = [];
  class Window extends EventEmitter {
    constructor(options) { super(); this.options = options; this.webContents = new EventEmitter(); this.webContents.setWindowOpenHandler = fn => this.openHandler = fn; windows.push(this); }
    async loadURL(url) { this.url = url; }
    show() { this.shown = true; }
    focus() { this.focused = true; }
    getBounds() { return { x: 0, y: 0, width: 1200, height: 800 }; }
    getMinimumSize() { return [960, 680]; }
    setMinimumSize(...minimum) { this.minimum = minimum; }
    setBounds(bounds) { this.bounds = bounds; }
    unmaximize() {}
    close() { let blocked = false; this.emit('close', { preventDefault: () => blocked = true }); if (!blocked) { this.closed = true; this.emit('closed'); } }
  }
  const main = new Window(), trusted = { sender: main.webContents };
  let fail = false;
  const manager = registerTabWindows({ BrowserWindow: Window, screen: { getDisplayNearestPoint: () => ({ workArea: { x: 0, y: 0, width: 1366, height: 768 } }) },
    ipcMain: { handle: (name, fn) => handlers.set(name, fn) }, shell: { openExternal() {} }, dialog: { showErrorBox: (...args) => errors.push(args) },
    getMainWindow: () => main, getBackendUrl: () => 'http://127.0.0.1:8765',
    trustedWindow: event => { if (event !== trusted && !manager.owns(event.sender)) throw new Error('untrusted'); },
    saveWindow: async () => { if (fail) throw new Error('unsaved'); }, isQuitting: () => false });
  return { handlers, main, trusted, manager, windows, errors, fail: value => fail = value };
}
test('desktop detached shells clamp split bounds, preserve preload isolation and restore original window geometry', async () => {
  const s = setup();
  await s.handlers.get('easyread:detach-window')(s.trusted, 'dt-123-ab', { x: 999999, width: 999999 });
  const win = s.manager.all()[0];
  assert.equal(win.options.width, 683); assert.equal(win.options.x, 683);
  assert.equal(win.options.webPreferences.nodeIntegration, false);
  assert.equal(win.options.webPreferences.contextIsolation, true);
  assert.match(win.url, /^http:\/\/127\.0\.0\.1:8765\/web\/tabs\.html\?detached=dt-123-ab$/);
  assert.deepEqual(s.main.minimum, [480, 400]);
  s.handlers.get('easyread:restore-main-window')({sender:win.webContents});
  assert.deepEqual(s.main.minimum, [960, 680]);
  assert.equal(s.main.bounds.width, 1200);
});
test('desktop detach rejects untrusted senders/tokens and retains an unsaved detached window', async () => {
  const s = setup(), detach = s.handlers.get('easyread:detach-window');
  await assert.rejects(detach({sender:{}}, 'dt-123', {}), /untrusted/);
  await assert.rejects(detach(s.trusted, '../../bad', {}), /Invalid/);
  await detach(s.trusted, 'dt-123', {});
  const win = s.manager.all()[0];
  s.fail(true); win.close(); await new Promise(resolve => setImmediate(resolve));
  assert.ok(!win.closed); assert.equal(s.errors[0][1], 'unsaved');
  s.fail(false); win.close(); await new Promise(resolve => setImmediate(resolve));
  assert.ok(win.closed); assert.equal(s.manager.all().length, 0);
});
