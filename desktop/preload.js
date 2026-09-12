'use strict';

const { contextBridge, ipcRenderer, webUtils } = require('electron');

function localFilePath(file) {
  try {
    const value = webUtils.getPathForFile(file);
    return typeof value === 'string' && value.length > 0 && value.length <= 1024 ? value : '';
  } catch (_) {
    return '';
  }
}

contextBridge.exposeInMainWorld('vortexApi', Object.freeze({
  request: (route, options = {}) => ipcRenderer.invoke('vortex-request', route, {
    method: options.method || 'GET',
    body: options.body === undefined ? undefined : options.body
  }),
  localFilePath
}));

const safeWindowState = state => Object.freeze({
  minimized: state?.minimized === true,
  maximized: state?.maximized === true,
  fullScreen: state?.fullScreen === true,
  minimizable: state?.minimizable !== false,
  maximizable: state?.maximizable !== false,
  closable: state?.closable !== false
});

contextBridge.exposeInMainWorld('vortexWindow', Object.freeze({
  minimize: () => ipcRenderer.send('vortex-window-control', 'minimize'),
  toggleMaximize: () => ipcRenderer.send('vortex-window-control', 'toggle-maximize'),
  close: () => ipcRenderer.send('vortex-window-control', 'close'),
  getState: () => ipcRenderer.invoke('vortex-window-state').then(safeWindowState),
  onStateChange: callback => {
    if (typeof callback !== 'function') return;
    ipcRenderer.on('vortex-window-state', (_event, state) => callback(safeWindowState(state)));
  }
}));
