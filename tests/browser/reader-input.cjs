// Node 22+; PYTHON=/path/to/venv/bin/python CHROME=/path/to/chrome node tests/browser/reader-input.cjs
// Own disposable fixture/profile only. Trusted CDP pen/touch != physical hardware verification.
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createInterface } = require('node:readline');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn, label) {
  for (let i = 0; i < 150; i++) { const value = await fn(); if (value) return value; await sleep(100); }
  throw Error('Timed out: ' + label);
}
async function connect(url) {
  const socket = new WebSocket(url), pending = new Map(); let id = 0;
  await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }); });
  socket.addEventListener('message', e => {
    const message = JSON.parse(e.data), entry = pending.get(message.id);
    if (!entry) return;
    pending.delete(message.id); clearTimeout(entry.timer);
    message.error ? entry.reject(Error(JSON.stringify(message.error))) : entry.resolve(message.result);
  });
  return { socket, send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const key = ++id, timer = setTimeout(() => { pending.delete(key); reject(Error('CDP timeout: ' + method)); }, 15000);
      pending.set(key, { resolve, reject, timer }); socket.send(JSON.stringify({ id: key, method, params }));
    });
  } };
}
async function main() {
  const root = path.resolve(__dirname, '../..'), profile = await fs.mkdtemp(path.join(os.tmpdir(), 'easyread-input-chrome-'));
  const service = spawn(process.env.PYTHON || 'python3', ['-X', 'utf8', 'scripts/preview_fixture.py', '--port', '0'], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  let serviceOutput = '', url, chrome, cdp;
  service.stderr.on('data', data => { serviceOutput += data; });
  createInterface({ input: service.stdout }).on('line', line => { serviceOutput += line + '\n'; url = line.match(/EasyRead 已启动：(http:\/\/127\.0\.0\.1:\d+)/u)?.[1] || url; });
  const checks = [];
  try {
    await until(() => { if (service.exitCode !== null) throw Error(serviceOutput); return url; }, 'fixture startup');
    chrome = spawn(process.env.CHROME || 'google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu', '--no-first-run', '--disable-dev-shm-usage', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'], { stdio: 'ignore' });
    const port = await until(async () => { try { return (await fs.readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; } catch { return null; } }, 'Chrome startup');
    const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    cdp = await connect(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
    const send = cdp.send;
    const screenshot = async name => {
      if (!process.env.SCREENSHOTS) return;
      await fs.mkdir(process.env.SCREENSHOTS, { recursive: true });
      const { data } = await send('Page.captureScreenshot', { format: 'png' });
      await fs.writeFile(path.join(process.env.SCREENSHOTS, name + '.png'), Buffer.from(data, 'base64'));
    };
    const ev = async expression => {
      const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
      if (result.exceptionDetails) throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result.value;
    };
    await send('Page.enable');
    await send('Page.addScriptToEvaluateOnNewDocument', { source: `window.inputAudit=[]; window.addEventListener('pointerdown', e=>inputAudit.push({type:e.pointerType,id:e.pointerId,trusted:e.isTrusted}), true);` });
    await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
    await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
    await send('Page.navigate', { url: url + '/read/sample-paper' });
    await until(() => ev(`!!window.PR?.setInkInputMode && !!document.querySelector('#b-p1-1 .zh')`), 'reader loaded');
    await sleep(300);
    const box = selector => ev(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})()`);
    const pointer = (type, point, kind = 'mouse', buttons = type === 'mouseReleased' ? 0 : 1) => send('Input.dispatchMouseEvent', {
      type, x: point.x, y: point.y, pointerType: kind, button: type === 'mouseMoved' ? 'none' : 'left', buttons, clickCount: type === 'mouseMoved' ? 0 : 1,
      ...(kind === 'pen' ? { force: buttons ? .6 : 0 } : {})
    });
    const click = async (selector, kind = 'mouse') => {
      await ev(`document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({block:'nearest',inline:'nearest'})`);
      const r = await box(selector), p = { x: r.x + r.width / 2, y: r.y + r.height / 2 };
      await pointer('mousePressed', p, kind); await pointer('mouseReleased', p, kind);
    };
    const live = () => ev(`Object.values(PR.state.reader.ink || {}).filter(s=>!s.deleted).length`);
    const state = () => ev(`({ink:PR.inkActive(),tools:!document.getElementById('inkTools').hidden,stickers:!document.getElementById('stickerPanel').hidden,mode:PR.inkInputMode()})`);
    await click('#stickerToggle');
    assert.deepEqual(await state(), { ink: false, tools: false, stickers: true, mode: 'mouse' });
    await click('#stickerToggle'); await click('#inkToggle'); await click('#stickerToggle');
    assert.deepEqual(await state(), { ink: false, tools: false, stickers: true, mode: 'mouse' });
    await screenshot('stickers-alone');
    checks.push('sticker library opens alone from closed and from handwriting');
    await click('#inkToggle');
    assert.equal((await state()).stickers, false);
    const r = await box('#b-p1-1'), start = { x: r.x + 35, y: r.y + 22 }, end = { x: r.x + 95, y: r.y + 25 };
    const stroke = async kind => { await pointer('mousePressed', start, kind); await pointer('mouseMoved', end, kind); await pointer('mouseReleased', end, kind); };
    const touch = async () => {
      await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ ...start, id: 8, radiusX: 10, radiusY: 10 }] });
      await send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ ...end, id: 8, radiusX: 10, radiusY: 10 }] });
      await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    };
    await stroke('mouse'); assert.equal(await live(), 1);
    await touch(); assert.equal(await live(), 2);
    await stroke('pen'); assert.equal(await live(), 2);
    checks.push('default mouse/touch draw; pen cannot draw without explicit pen mode');
    await click('[data-ink-input]'); assert.equal((await state()).mode, 'pen');
    await screenshot('pen-mode');
    await stroke('mouse'); await touch(); assert.equal(await live(), 2);
    // Real pen contact interleaved with real touch and synthetic mouse/compatibility/paragraph events.
    await pointer('mousePressed', start, 'pen');
    await pointer('mousePressed', start, 'mouse'); await pointer('mouseReleased', start, 'mouse');
    await touch();
    const blocked = await ev(`(()=>{
      let reached=0; const p=document.querySelector('#b-p1-1'), b=document.getElementById('inkToggle');
      const types=['mousedown','mouseup','click','dblclick','contextmenu','selectstart'];
      for(const el of [p,b]) for(const type of types) { const spy=()=>reached++; el.addEventListener(type,spy,{once:true}); el.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,detail:1})); el.removeEventListener(type,spy); }
      const layer=document.getElementById('inkLayer');
      for(const type of ['pointerdown','pointermove','pointerup']) layer.dispatchEvent(new PointerEvent(type,{pointerType:'mouse',pointerId:99,button:0,buttons:type==='pointerup'?0:1,clientX:999,clientY:999,bubbles:true,cancelable:true}));
      return {reached,active:PR.inkActive(),selected:getSelection().toString(),bar:document.getElementById('blockbar').classList.contains('open')};
    })()`);
    assert.deepEqual(blocked, { reached: 0, active: true, selected: '', bar: false });
    await pointer('mouseMoved', end, 'pen'); await pointer('mouseReleased', end, 'pen');
    assert.equal(await live(), 3);
    assert.ok(await ev(`Object.values(PR.state.reader.ink).filter(s=>!s.deleted).every(s=>s.points.every(p=>Math.abs(p[0])<500 && Math.abs(p[1])<500))`), 'non-owner mouse contaminated a pen stroke');
    await click('#inkToggle', 'pen'); assert.equal((await state()).ink, true);
    await click('[data-ink-input]'); assert.equal((await state()).mode, 'mouse');
    await click('[data-ink-input]'); assert.equal((await state()).mode, 'pen');
    checks.push('trusted pen draws; trusted touch/mouse rejected; active contact blocks compatibility, selection and paragraph actions; pen toolbar click rejected; mouse toolbar exits/configures immediately');
    // Eraser still operates as one undoable pen gesture.
    await click('[data-ink-erase]'); await stroke('pen'); assert.equal(await live(), 0);
    await click('[data-ink-undo]'); assert.equal(await live(), 3);
    await click('[data-ink-redo]'); assert.equal(await live(), 0);
    await click('[data-ink-undo]'); await click('[data-ink-color]');
    checks.push('pen eraser and undo/redo');
    for (const reset of ['pointercancel', 'lostpointercapture', 'blur', 'mode', 'panel']) {
      await ev(`PR.setInkActive(true);PR.setInkInputMode('pen')`);
      await pointer('mousePressed', start, 'pen');
      if (reset === 'mode') await ev(`PR.setInkInputMode('mouse')`);
      else if (reset === 'panel') await ev(`PR.toggleStickerPanel()`);
      else await ev(reset === 'blur' ? `window.dispatchEvent(new Event('blur'))` : `document.getElementById('inkLayer').dispatchEvent(new PointerEvent('${reset}',{pointerType:'pen',pointerId:inputAudit.filter(x=>x.type==='pen').at(-1).id,bubbles:true,cancelable:true}))`);
      await pointer('mouseReleased', end, 'pen');
      await sleep(450);
      assert.equal(await ev(`PR.readerInput.suppressing() || document.documentElement.classList.contains('ink-pen-contact')`), false, reset);
      // Click, rather than programmatic toggle, proves that the mouse is not locked out.
      if ((await state()).ink) await click('#inkToggle');
      else if ((await state()).stickers) await click('#stickerToggle');
      await click('#inkToggle'); assert.equal((await state()).ink, true, reset);
      const before = await live(); await stroke('pen'); assert.equal(await live(), before + (reset === 'mode' ? 0 : 1), reset);
    }
    checks.push('pointercancel/lostcapture/blur/mode/panel reset permits next gesture and toolbar click (reset events injected, pen down/up trusted)');
    // Lasso in pen mode excludes mouse/touch yet retains mixed object selection.
    await click('[data-ink-lasso]');
    await pointer('mousePressed', { x: start.x - 15, y: start.y - 15 }, 'pen');
    for (const p of [{ x: end.x + 15, y: start.y - 15 }, { x: end.x + 15, y: end.y + 15 }, { x: start.x - 15, y: end.y + 15 }, { x: start.x - 15, y: start.y - 15 }]) await pointer('mouseMoved', p, 'pen');
    await pointer('mouseReleased', start, 'pen');
    assert.equal(await ev(`PR.lassoMode`), false);
    assert.ok(await ev(`!!document.querySelector('#stickerTools [data-action="group"]')`));
    await click('#stickerTools [data-action="group"]');
    checks.push('pen lasso and group action remain functional');
    await click('[data-ink-text]');
    await pointer('mousePressed', { x: end.x + 100, y: end.y }, 'pen'); await pointer('mouseReleased', { x: end.x + 100, y: end.y }, 'pen');
    assert.ok(await ev(`!!document.querySelector('.ink-text-editor')`));
    await send('Input.insertText', { text: 'Pen input regression' });
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', modifiers: 2, windowsVirtualKeyCode: 13 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', modifiers: 2, windowsVirtualKeyCode: 13 });
    assert.ok(await ev(`Object.values(PR.state.reader.stickers).some(s=>s.text==='Pen input regression')`));
    checks.push('pen text placement and keyboard editing');
    await click('#stickerToggle');
    assert.equal((await state()).ink, false);
    await until(() => ev(`!!document.querySelector('#stickerPanel [data-asset="atom"]')`), 'sticker catalog');
    await click('[data-asset="atom"]'); await click('[data-insert]'); await click('#stickerToggle');
    const sticker = await until(() => ev(`Object.values(PR.state.reader.stickers).find(s=>s.assetId==='atom')`), 'inserted sticker');
    assert.ok(sticker);
    const sr = await box(`[data-sticker="${sticker.id}"] image`), sp = { x: sr.x + sr.width / 2, y: sr.y + sr.height / 2 };
    await pointer('mousePressed', sp); await pointer('mouseMoved', { x: sp.x + 20, y: sp.y + 10 }); await pointer('mouseReleased', { x: sp.x + 20, y: sp.y + 10 });
    assert.notEqual(await ev(`PR.state.reader.stickers[${JSON.stringify(sticker.id)}].x`), sticker.x);
    checks.push('standalone sticker insertion/drag remains usable with pen preference remembered');
    const trustedTypes = await ev(`[...new Set(inputAudit.filter(e=>e.trusted).map(e=>e.type))]`);
    assert.deepEqual(trustedTypes.sort(), ['mouse', 'pen', 'touch']);
    await ev(`PR.setInkActive(false);PR.flushPending()`);
    const oldTimeOrigin = await ev(`performance.timeOrigin`);
    await send('Page.reload'); await until(() => ev(`performance.timeOrigin!==${oldTimeOrigin} && !!window.PR?.setInkInputMode && !!document.querySelector('#b-p1-1 .zh')`), 'reload');
    assert.equal((await state()).mode, 'pen'); assert.equal((await state()).ink, false);
    await click('#inkToggle'); assert.equal(await ev(`PR.readerInput.penOnly()`), true);
    await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
    await sleep(200);
    assert.ok(await ev(`document.documentElement.scrollWidth<=innerWidth+1`));
    assert.ok(await ev(`(()=>{const r=document.getElementById('inkTools').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.bottom<=innerHeight})()`));
    await screenshot('pen-mode-narrow');
    checks.push('preference persists without auto-enabling handwriting; narrow toolbar stays within viewport');
    // Fresh document audit was reset by reload; produce a final trusted pen event for evidence.
    const nr = await box('#b-p1-1'); await pointer('mousePressed', { x: nr.x + 20, y: nr.y + 20 }, 'pen'); await pointer('mouseReleased', { x: nr.x + 20, y: nr.y + 20 }, 'pen');
    const audit = await ev(`inputAudit`);
    assert.ok(audit.some(e => e.type === 'pen' && e.trusted));
    console.log(JSON.stringify({ result: 'passed', browser: (await send('Browser.getVersion')).product, checks, trustedPointerTypes: trustedTypes, trustedPointerSample: audit, physicalHardwareVerified: false }, null, 2));
  } catch (error) {
    console.error('Completed checks:', checks); throw error;
  } finally {
    cdp?.socket.close();
    if (chrome) { chrome.kill(); await new Promise(resolve => chrome.exitCode !== null ? resolve() : chrome.once('exit', resolve)); }
    service.kill(); await new Promise(resolve => service.exitCode !== null ? resolve() : service.once('exit', resolve));
    await fs.rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
