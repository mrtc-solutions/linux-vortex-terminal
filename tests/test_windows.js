'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { EventEmitter } = require('events');
const {
  applyControl,
  attachWindowState,
  registerWindowControls,
  stateOf
} = require('../desktop/window-controls');
const {
  isAllowedApiRequest,
  isDirectRendererRequest,
  isExternalWebUrl,
  isSidecarDownloadUrl,
  parseBootInfo,
  sameSidecarUrl
} = require('../desktop/security');

class FakeWindow extends EventEmitter {
  constructor() {
    super();
    this.minimized = false;
    this.maximized = false;
    this.fullScreen = false;
    this.closed = false;
    this.messages = [];
    this.webContents = {
      isDestroyed: () => this.closed,
      send: (channel, payload) => this.messages.push({ channel, payload })
    };
  }
  isDestroyed() { return this.closed; }
  isMinimized() { return this.minimized; }
  isMaximized() { return this.maximized; }
  isFullScreen() { return this.fullScreen; }
  isMinimizable() { return true; }
  isMaximizable() { return true; }
  isClosable() { return true; }
  minimize() { this.minimized = true; this.emit('minimize'); }
  maximize() { this.maximized = true; this.emit('maximize'); }
  unmaximize() { this.maximized = false; this.emit('unmaximize'); }
  close() { this.closed = true; this.emit('closed'); }
}

const direct = new FakeWindow();
assert.strictEqual(applyControl(direct, 'minimize'), true);
assert.strictEqual(direct.minimized, true);
assert.strictEqual(applyControl(direct, 'toggle-maximize'), true);
assert.strictEqual(direct.maximized, true);
assert.strictEqual(applyControl(direct, 'toggle-maximize'), true);
assert.strictEqual(direct.maximized, false);
assert.strictEqual(applyControl(direct, 'not-a-control'), false);
assert.deepStrictEqual(stateOf(direct), {
  minimized: true,
  maximized: false,
  fullScreen: false,
  minimizable: true,
  maximizable: true,
  closable: true
});

const ipc = {
  listeners: new Map(),
  handlers: new Map(),
  on(channel, callback) { this.listeners.set(channel, callback); },
  handle(channel, callback) { this.handlers.set(channel, callback); }
};
const controlled = new FakeWindow();
const BrowserWindow = { fromWebContents: sender => sender.window };
registerWindowControls(ipc, BrowserWindow);
attachWindowState(controlled);
const event = { sender: { window: controlled } };
ipc.listeners.get('vortex-window-control')(event, 'toggle-maximize');
assert.strictEqual(controlled.maximized, true);
assert.ok(controlled.messages.some(message => message.channel === 'vortex-window-state' && message.payload.maximized));
assert.strictEqual(ipc.handlers.get('vortex-window-state')(event).maximized, true);
ipc.listeners.get('vortex-window-control')(event, 'close');
assert.strictEqual(controlled.closed, true);

const frontendSource = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'windows.js'), 'utf8');
const context = { window: {} };
vm.runInNewContext(frontendSource, context);
const windows = context.window.VortexWindows;
assert.ok(windows, 'frontend window controller must be exported');
assert.strictEqual(windows.nextWindowState('normal', 'minimize'), 'minimized');
assert.strictEqual(windows.nextWindowState('minimized', 'minimize'), 'normal');
assert.strictEqual(windows.nextWindowState('normal', 'maximize'), 'maximized');
assert.strictEqual(windows.nextWindowState('maximized', 'maximize'), 'normal');
assert.strictEqual(windows.nextWindowState('normal', 'close'), 'closed');
const firstFocus = { id: 'first' };
const lastFocus = { id: 'last' };
assert.strictEqual(windows.focusTrapTarget([firstFocus, lastFocus], lastFocus, false), firstFocus);
assert.strictEqual(windows.focusTrapTarget([firstFocus, lastFocus], firstFocus, true), lastFocus);
assert.strictEqual(windows.focusTrapTarget([firstFocus, lastFocus], {}, false), firstFocus);
assert.strictEqual(windows.focusTrapTarget([firstFocus, lastFocus], firstFocus, false), null);

const html = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'index.html'), 'utf8');
assert.ok(html.includes('data-native-window-action="minimize"'));
assert.ok(html.includes('data-native-window-action="toggleMaximize"'));
assert.ok(html.includes('data-native-window-action="close"'));
assert.ok((html.match(/data-surface-window/g) || []).length >= 2, 'auto-opened surfaces need reusable controls');
assert.ok(html.includes('data-terminal-window-action="maximize"'));

const main = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'main.js'), 'utf8');
const preload = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'preload.js'), 'utf8');
assert.ok(main.includes('frame: false'), 'custom title bar must own the frameless Electron window');
assert.ok(main.includes('registerWindowControls(ipcMain, BrowserWindow)'));
assert.ok(main.includes('SIDECAR_BOOT_TIMEOUT_MS'), 'sidecar startup must have a deadline');
assert.ok(main.includes('SIDECAR_BOOT_OUTPUT_LIMIT'), 'sidecar startup output must be bounded');
assert.ok(main.includes('setWindowOpenHandler'), 'unexpected popup creation must be denied');
assert.ok(main.includes("on('will-navigate'"), 'unexpected navigation must be denied');
assert.ok(main.includes('setPermissionRequestHandler'), 'renderer permissions must fail closed');
assert.ok(main.includes('isDirectRendererRequest'), 'token injection must be route-scoped');

const sidecar = 'http://127.0.0.1:8765';
assert.strictEqual(isAllowedApiRequest('/api/health', 'GET'), true);
assert.strictEqual(isAllowedApiRequest('/api/settings', 'POST'), true);
assert.strictEqual(isAllowedApiRequest('/api/dependencies/plan', 'POST'), true);
assert.strictEqual(isAllowedApiRequest('/api/ollama/install/cancel', 'POST'), true);
assert.strictEqual(isAllowedApiRequest('/api/ollama/models/activate', 'POST'), true);
assert.strictEqual(isAllowedApiRequest('/api/dependencies/execute', 'POST'), true);
assert.strictEqual(isAllowedApiRequest('/api/execute', 'GET'), false);
assert.strictEqual(isAllowedApiRequest('/api/store/backup', 'POST'), false);
assert.strictEqual(isAllowedApiRequest('/api/../settings', 'POST'), false);
assert.strictEqual(isAllowedApiRequest('/api/%2e%2e/settings', 'POST'), false);
assert.strictEqual(isAllowedApiRequest('/api/health', 'DELETE'), false);
assert.strictEqual(isDirectRendererRequest(`${sidecar}/`, sidecar, 'GET'), true);
assert.strictEqual(isDirectRendererRequest(`${sidecar}/assets/app.js`, sidecar, 'GET'), true);
assert.strictEqual(isDirectRendererRequest(`${sidecar}/api/health`, sidecar, 'GET'), false);
assert.strictEqual(isDirectRendererRequest(`${sidecar}/api/operations/abc/stream`, sidecar, 'GET'), true);
assert.strictEqual(isSidecarDownloadUrl(`${sidecar}/api/reports/abc/download?format=md`, sidecar), true);
assert.strictEqual(isSidecarDownloadUrl('https://example.test/api/reports/abc/download', sidecar), false);
assert.strictEqual(sameSidecarUrl(`${sidecar}/api/health`, sidecar), true);
assert.strictEqual(sameSidecarUrl('http://127.0.0.1:9999/', sidecar), false);
assert.strictEqual(isExternalWebUrl('https://github.com/example/repo'), true);
assert.strictEqual(isExternalWebUrl('javascript:alert(1)'), false);
assert.deepStrictEqual(
  { ...parseBootInfo('{"backend":"online","host":"127.0.0.1","port":8765,"version":"1"}') },
  { host: '127.0.0.1', port: 8765, version: '1' }
);
assert.strictEqual(parseBootInfo('{"backend":"online","host":"0.0.0.0","port":8765}'), null);
assert.strictEqual(parseBootInfo('{"backend":"online","host":"127.0.0.1","port":70000}'), null);

const exposed = {};
const sent = [];
const listeners = new Map();
const ipcRenderer = {
  send: (...args) => sent.push(args),
  invoke: () => Promise.resolve({ maximized: false }),
  on: (channel, callback) => listeners.set(channel, callback)
};
vm.runInNewContext(preload, {
  require: name => {
    assert.strictEqual(name, 'electron');
    return { contextBridge: { exposeInMainWorld: (name, value) => { exposed[name] = value; } }, ipcRenderer };
  },
  Object,
  Promise
});
assert.ok(exposed.vortexApi);
assert.ok(exposed.vortexWindow);
exposed.vortexWindow.minimize();
exposed.vortexWindow.toggleMaximize();
exposed.vortexWindow.close();
assert.deepStrictEqual(sent, [
  ['vortex-window-control', 'minimize'],
  ['vortex-window-control', 'toggle-maximize'],
  ['vortex-window-control', 'close']
]);
let changedState = null;
exposed.vortexWindow.onStateChange(state => { changedState = state; });
listeners.get('vortex-window-state')(null, { maximized: true, minimizable: true, maximizable: true, closable: true });
assert.strictEqual(changedState.maximized, true);
console.log('window control tests: PASS');
