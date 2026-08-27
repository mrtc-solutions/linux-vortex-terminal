'use strict';

const CONTROL_CHANNEL = 'vortex-window-control';
const STATE_CHANNEL = 'vortex-window-state';
const ACTIONS = new Set(['minimize', 'toggle-maximize', 'close']);
const attachedWindows = new WeakSet();

function stateOf(win) {
  return Object.freeze({
    minimized: Boolean(win && !win.isDestroyed() && win.isMinimized()),
    maximized: Boolean(win && !win.isDestroyed() && win.isMaximized()),
    fullScreen: Boolean(win && !win.isDestroyed() && win.isFullScreen()),
    minimizable: Boolean(win && !win.isDestroyed() && win.isMinimizable()),
    maximizable: Boolean(win && !win.isDestroyed() && win.isMaximizable()),
    closable: Boolean(win && !win.isDestroyed() && win.isClosable())
  });
}

function sendState(win) {
  if (!win || win.isDestroyed() || !win.webContents || win.webContents.isDestroyed()) return;
  win.webContents.send(STATE_CHANNEL, stateOf(win));
}

function applyControl(win, action) {
  if (!win || win.isDestroyed() || !ACTIONS.has(action)) return false;
  if (action === 'minimize' && win.isMinimizable()) {
    win.minimize();
  } else if (action === 'toggle-maximize' && win.isMaximizable()) {
    if (win.isMaximized()) win.unmaximize();
    else win.maximize();
  } else if (action === 'close' && win.isClosable()) {
    win.close();
  } else {
    return false;
  }
  return true;
}

function attachWindowState(win) {
  if (!win || attachedWindows.has(win)) return;
  attachedWindows.add(win);
  for (const eventName of ['ready-to-show', 'minimize', 'restore', 'maximize', 'unmaximize', 'enter-full-screen', 'leave-full-screen']) {
    win.on(eventName, () => sendState(win));
  }
}

function registerWindowControls(ipcMain, BrowserWindow) {
  ipcMain.on(CONTROL_CHANNEL, (event, action) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (!applyControl(win, action)) return;
    // Native state events normally send this too. Sending here also covers
    // window managers that do not emit one of Electron's optional events.
    sendState(win);
  });
  ipcMain.handle(STATE_CHANNEL, event => {
    const win = BrowserWindow.fromWebContents(event.sender);
    return stateOf(win);
  });
}

module.exports = {
  ACTIONS,
  CONTROL_CHANNEL,
  STATE_CHANNEL,
  applyControl,
  attachWindowState,
  registerWindowControls,
  stateOf
};
