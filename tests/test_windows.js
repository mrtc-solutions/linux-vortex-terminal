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
