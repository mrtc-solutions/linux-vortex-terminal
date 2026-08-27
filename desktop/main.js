const { app, BrowserWindow, ipcMain, session } = require('electron');
const { spawn } = require('child_process');
const crypto = require('crypto');
const path = require('path');

if (process.platform !== 'linux') {
  throw new Error('Linux Vortex Terminal is Linux-only.');
}

let sidecar;
let sidecarUrl;
const capability = crypto.randomBytes(32).toString('hex');

function startSidecar() {
  return new Promise((resolve, reject) => {
    const root = path.resolve(__dirname, '..');
    sidecar = spawn(process.env.PYTHON || 'python3', [path.join(root, 'backend', 'vortex_backend.py'), '--host', '127.0.0.1', '--port', '0'], {
      cwd: root,
      env: { ...process.env, VORTEX_SIDECAR_TOKEN: capability },
      stdio: ['ignore', 'pipe', 'pipe']
    });
    let settled = false;
    let buffer = '';
    sidecar.stdout.on('data', chunk => {
      buffer += chunk.toString();
      const line = buffer.split('\n')[0];
      try {
        const info = JSON.parse(line);
        if (info.port && !settled) { settled = true; sidecarUrl = `http://127.0.0.1:${info.port}`; resolve(); }
      } catch (_) { /* wait for the complete boot line */ }
    });
    sidecar.stderr.on('data', chunk => process.stderr.write(`[vortex-sidecar] ${chunk}`));
    sidecar.on('error', err => { if (!settled) { settled = true; reject(err); } });
    sidecar.on('exit', code => { if (!settled) { settled = true; reject(new Error(`sidecar exited before boot (${code})`)); } });
  });
}

async function sidecarRequest(route, options = {}) {
  const response = await fetch(`${sidecarUrl}${route}`, {
    method: options.method || 'GET',
    headers: { 'Content-Type': 'application/json', 'X-Vortex-Token': capability },
    body: options.body === undefined ? undefined : JSON.stringify(options.body)
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error?.message || `Sidecar request failed (${response.status})`);
  return payload;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1440, height: 940, minWidth: 960, minHeight: 680,
    backgroundColor: '#0a0a0c', show: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true }
  });
  win.once('ready-to-show', () => win.show());
  win.loadURL(`${sidecarUrl}/`);
}

app.whenReady().then(async () => {
  await startSidecar();
  ipcMain.handle('vortex-request', (_event, route, options) => {
    if (typeof route !== 'string' || !route.startsWith('/api/') || route.includes('..')) throw new Error('invalid sidecar route');
    return sidecarRequest(route, options || {});
  });
  session.defaultSession.webRequest.onBeforeSendHeaders((details, callback) => {
    // The renderer does not get the token; only the typed bridge may call the sidecar.
    if (details.url.startsWith(sidecarUrl)) details.requestHeaders['X-Vortex-Token'] = capability;
    callback({ requestHeaders: details.requestHeaders });
  });
  createWindow();
});

app.on('window-all-closed', () => { if (sidecar) sidecar.kill('SIGTERM'); app.quit(); });
app.on('before-quit', () => { if (sidecar) sidecar.kill('SIGTERM'); });
