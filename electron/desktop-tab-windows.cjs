// Detached reader shells share the backend, but have their own trusted main-frame IPC.
const path = require('node:path');
const tabs = require('./desktop-tabs.cjs');

function registerTabWindows({ BrowserWindow, screen, ipcMain, shell, dialog, getMainWindow, getBackendUrl, trustedWindow, saveWindow, isQuitting }) {
  const windows = new Set();
  let mainBounds, mainMinimum;
  function senderWindow(event) {
    trustedWindow(event);
    return [getMainWindow(), ...windows].find(win => win?.webContents === event.sender);
  }
  function splitBounds(request) {
    const display = screen.getDisplayNearestPoint({ x: Math.round(Number(request?.x) || 0), y: Math.round(Number(request?.y) || 0) });
    const area = display.workArea;
    const width = Math.floor(area.width / 2);
    const x = Number(request?.x) >= area.x + width ? area.x + width : area.x;
    return { x, y: area.y, width, height: area.height };
  }
  ipcMain.handle('easyread:detach-window', async (event, token, request) => {
    const owner = senderWindow(event);
    if (!/^dt-[a-zA-Z0-9-]{1,100}$/.test(token || '')) throw new Error('Invalid detached tab token');
    const bounds = splitBounds(request);
    const main = getMainWindow();
    if (owner === main && main?.getBounds) {
      mainBounds ||= main.getBounds();
      mainMinimum ||= main.getMinimumSize?.();
      main.setMinimumSize?.(480, 400);
      const area = screen.getDisplayNearestPoint({ x: bounds.x, y: bounds.y }).workArea;
      main.unmaximize();
      main.setBounds({ x: bounds.x === area.x ? area.x + bounds.width : area.x, y: area.y, width: bounds.width, height: area.height });
    }
    const win = new BrowserWindow({ ...bounds, minWidth: 480, minHeight: 400, show: false,
      title: 'EasyRead', icon: path.join(__dirname, 'assets', 'icon.ico'),
      webPreferences: { contextIsolation: true, nodeIntegration: false, preload: path.join(__dirname, 'preload.cjs') } });
    windows.add(win);
    tabs.bindShortcuts(win);
    win.webContents.setWindowOpenHandler(({ url }) => {
      if (/^https?:/i.test(url)) shell.openExternal(url);
      return { action: 'deny' };
    });
    let saved = false, saving = false;
    win.on('close', event => {
      if (saved || isQuitting()) return;
      event.preventDefault();
      if (saving) return;
      saving = true;
      saveWindow(win).then(() => { saved = true; win.close(); })
        .catch(error => dialog.showErrorBox('EasyRead', error.message)).finally(() => { saving = false; });
    });
    win.on('closed', () => windows.delete(win));
    try { await win.loadURL(tabs.detachedShellUrl(getBackendUrl(), token)); win.show(); }
    catch (error) { saved = true; win.close(); throw error; }
    return true;
  });
  ipcMain.handle('easyread:close-current-window', event => {
    const win = senderWindow(event);
    if (windows.has(win)) win.close();
  });
  ipcMain.handle('easyread:restore-main-window', event => {
    senderWindow(event);
    const main = getMainWindow();
    if (mainBounds && main) {
      if (mainMinimum) main.setMinimumSize(...mainMinimum);
      main.setBounds(mainBounds); mainBounds = mainMinimum = undefined;
    }
    main?.show(); main?.focus();
  });
  return { owns: wc => [...windows].some(win => win.webContents === wc), all: () => [...windows] };
}
module.exports = { registerTabWindows };
