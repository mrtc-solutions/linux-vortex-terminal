const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('vortexApi', Object.freeze({
  request: (route, options = {}) => ipcRenderer.invoke('vortex-request', route, {
    method: options.method || 'GET',
    body: options.body === undefined ? undefined : options.body
  })
}));
