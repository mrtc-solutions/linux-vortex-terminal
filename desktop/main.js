'use strict';

const { app, BrowserWindow, dialog, ipcMain, session, shell, nativeImage } = require('electron');
const { spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { attachWindowState, registerWindowControls } = require('./window-controls');
const {
  isAllowedApiRequest,
  isDirectRendererRequest,
  isExternalWebUrl,
  isSidecarDownloadUrl,
  parseBootInfo,
  sameSidecarUrl
} = require('./security');

if (process.platform !== 'linux') {
  throw new Error('Linux Vortex Terminal is Linux-only.');
}

const SIDECAR_BOOT_TIMEOUT_MS = 15000;
const SIDECAR_BOOT_OUTPUT_LIMIT = 64 * 1024;
const SIDECAR_STOP_TIMEOUT_MS = 10000;

let sidecar;
let sidecarUrl;
let mainWindow;
let stoppingSidecar = false;
let quitting = false;
const trustedWebContents = new Set();
const capability = crypto.randomBytes(32).toString('hex');

function terminateChild(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  try { child.kill('SIGTERM'); } catch (_) { /* already gone */ }
  const timer = setTimeout(() => {
    if (child.exitCode === null && child.signalCode === null) {
      try { child.kill('SIGKILL'); } catch (_) { /* already gone */ }
    }
  }, 1000);
  timer.unref();
}

function startSidecar() {
  return new Promise((resolve, reject) => {
    const root = path.resolve(__dirname, '..');
    const child = spawn(process.env.PYTHON || 'python3', [path.join(root, 'backend', 'vortex_backend.py'), '--host', '127.0.0.1', '--port', '0'], {
      cwd: root,
      env: { ...process.env, VORTEX_SIDECAR_TOKEN: capability },
      stdio: ['ignore', 'pipe', 'pipe']
    });
    sidecar = child;
    let settled = false;
    let bootFailed = false;
    let buffer = '';

    const bootTimer = setTimeout(() => {
      fail(new Error(`sidecar did not become ready within ${SIDECAR_BOOT_TIMEOUT_MS / 1000} seconds`));
    }, SIDECAR_BOOT_TIMEOUT_MS);

    function fail(error) {
      if (settled) return;
      settled = true;
      bootFailed = true;
      clearTimeout(bootTimer);
      terminateChild(child);
      reject(error);
    }

    child.stdout.on('data', chunk => {
      if (settled) return; // listener still drains the pipe without retaining it
      buffer += chunk.toString('utf8');
      if (Buffer.byteLength(buffer, 'utf8') > SIDECAR_BOOT_OUTPUT_LIMIT) {
        fail(new Error('sidecar boot output exceeded the safety limit'));
        return;
      }
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        const info = parseBootInfo(line.trim());
        if (!info) continue;
        settled = true;
        clearTimeout(bootTimer);
        sidecarUrl = `http://127.0.0.1:${info.port}`;
        resolve();
        break;
      }
    });
    child.stderr.on('data', chunk => process.stderr.write(`[vortex-sidecar] ${chunk}`));
    child.on('error', error => {
      if (!settled) fail(error);
      else if (!quitting) {
        dialog.showErrorBox('Vortex Terminal sidecar error', String(error.message || error));
        app.quit();
      }
    });
    child.on('exit', (code, signalName) => {
      if (!settled) {
        fail(new Error(`sidecar exited before boot (${signalName || code})`));
      } else if (!bootFailed && !quitting && !stoppingSidecar) {
        dialog.showErrorBox('Vortex Terminal sidecar stopped', `The local sidecar exited unexpectedly (${signalName || code}).`);
        app.quit();
      }
    });
  });
}

async function sidecarRequest(route, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  if (!isAllowedApiRequest(route, method)) throw new Error('sidecar route or method is not exposed to the renderer');
  const response = await fetch(`${sidecarUrl}${route}`, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Vortex-Token': capability },
    body: options.body === undefined ? undefined : JSON.stringify(options.body)
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error?.message || `Sidecar request failed (${response.status})`);
  return payload;
}

function openExternal(url) {
  if (!isExternalWebUrl(url)) return;
  shell.openExternal(url).catch(error => process.stderr.write(`[vortex-desktop] external link failed: ${error.message}\n`));
}

function secureNavigation(win) {
  const guard = (event, url) => {
    if (sameSidecarUrl(url, sidecarUrl)) return;
    event.preventDefault();
    openExternal(url);
  };
  win.webContents.on('will-navigate', guard);
  win.webContents.on('will-redirect', guard);
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isSidecarDownloadUrl(url, sidecarUrl)) {
      win.webContents.downloadURL(url, { headers: { 'X-Vortex-Token': capability } });
    } else {
      openExternal(url);
    }
    return { action: 'deny' };
  });
}

function appIcon() {
  const candidates = [
    path.join(__dirname, '..', 'assets', 'icons', 'vortex.png'),
    path.join(__dirname, '..', 'assets', 'icons', 'vortex-256.png'),
    path.join(__dirname, '..', 'assets', 'icons', 'vortex-512.png'),
    path.join(__dirname, '..', 'assets', 'icons', 'vortex.svg'),
  ];
  for (const candidate of candidates) {
    try {
      if (!fs.existsSync(candidate)) continue;
      const image = nativeImage.createFromPath(candidate);
      if (!image.isEmpty()) return image;
    } catch (_) {
      // Try the next real file; never skip opening a window because of art.
    }
  }
  return undefined;
}

function createWindow() {
  const icon = appIcon();
  const win = new BrowserWindow({
    title: 'Vortex Terminal // Linux Orchestration',
    width: 1440, height: 940, minWidth: 960, minHeight: 680,
    backgroundColor: '#0a0a0c', show: false,
    ...(icon ? { icon } : {}),
    // Linux desktop decorations vary by window manager. Vortex Terminal owns a visible,
    // tested title bar so minimize/maximize/close remain available everywhere.
    frame: false,
    autoHideMenuBar: true,
    minimizable: true,
    maximizable: true,
    closable: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
      spellcheck: false
    }
  });
  mainWindow = win;
  // Keep the primitive identity, rather than dereferencing webContents during
  // teardown. Electron destroys webContents before the BrowserWindow `closed`
  // event on some window managers, which previously raised "Object has been
  // destroyed" while closing the app.
  const webContentsId = win.webContents.id;
  trustedWebContents.add(webContentsId);
  attachWindowState(win);
  secureNavigation(win);
  win.setMenuBarVisibility(false);
  win.once('ready-to-show', () => win.show());
  win.on('closed', () => {
    trustedWebContents.delete(webContentsId);
    if (mainWindow === win) mainWindow = null;
  });
  win.loadURL(`${sidecarUrl}/`).catch(error => {
    if (!quitting) {
      dialog.showErrorBox('Vortex Terminal failed to load', error.message);
      app.quit();
    }
  });
  return win;
}

// The renderer is served from the sidecar origin, so a WebSocket upgrade cannot
// carry the capability header the way IPC does. Mint the same short-lived
// browser session the web build uses and install it as a real cookie, which
// keeps desktop and browser remote-desktop authorization identical.
async function establishRendererSession() {
  try {
    const response = await fetch(`${sidecarUrl}/api/auth/session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Vortex-Token': capability },
      body: '{}'
    });
    if (!response.ok) throw new Error(`sidecar answered ${response.status}`);
    const cookies = typeof response.headers.getSetCookie === 'function' ? response.headers.getSetCookie() : [];
    const sessionCookie = cookies.find(value => value.startsWith('Vortex-Session='));
    const value = sessionCookie ? sessionCookie.slice('Vortex-Session='.length).split(';')[0] : '';
    if (!value) throw new Error('no session cookie in the response');
    await session.defaultSession.cookies.set({
      url: sidecarUrl,
      name: 'Vortex-Session',
      value,
      httpOnly: true,
      sameSite: 'strict',
      secure: false,
      expirationDate: Math.floor(Date.now() / 1000) + 28800
    });
  } catch (error) {
    // The workbench still works over IPC; only the WebSocket-backed remote
    // desktop needs this cookie, and it reports its own actionable error.
    process.stderr.write(`[vortex-desktop] renderer session bootstrap failed: ${error.message}\n`);
  }
}

app.whenReady().then(async () => {
  await startSidecar();
  registerWindowControls(ipcMain, BrowserWindow);
  ipcMain.handle('vortex-request', (event, route, options = {}) => {
    if (!trustedWebContents.has(event.sender.id) || !sameSidecarUrl(event.senderFrame?.url || '', sidecarUrl)) throw new Error('untrusted renderer');
    const method = String(options?.method || 'GET').toUpperCase();
    if (!isAllowedApiRequest(route, method)) throw new Error('invalid sidecar capability request');
    return sidecarRequest(route, { method, body: options?.body });
  });

  session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
  session.defaultSession.webRequest.onBeforeSendHeaders({ urls: [`${sidecarUrl}/*`] }, (details, callback) => {
    if (trustedWebContents.has(details.webContentsId) && isDirectRendererRequest(details.url, sidecarUrl, details.method)) {
      details.requestHeaders['X-Vortex-Token'] = capability;
    }
    callback({ requestHeaders: details.requestHeaders });
  });
  await establishRendererSession();
  createWindow();
}).catch(error => {
  process.stderr.write(`[vortex-desktop] startup failed: ${error.stack || error}\n`);
  dialog.showErrorBox('Vortex Terminal could not start', String(error.message || error));
  app.quit();
});

app.on('window-all-closed', () => app.quit());

app.on('before-quit', event => {
  quitting = true;
  if (!sidecar || sidecar.exitCode !== null || sidecar.signalCode !== null) return;
  event.preventDefault();
  if (stoppingSidecar) return;
  stoppingSidecar = true;
  const child = sidecar;
  let completed = false;
  let forceTimer;
  const completeQuit = () => {
    if (completed) return;
    completed = true;
    if (forceTimer) clearTimeout(forceTimer);
    sidecar = null;
    app.quit();
  };
  // Subscribe before signalling so a fast clean exit cannot be missed between
  // kill() and listener registration, leaving the prevented quit stuck.
  child.once('exit', completeQuit);
  try { child.kill('SIGTERM'); } catch (_) { completeQuit(); return; }
  forceTimer = setTimeout(() => {
    if (child.exitCode === null && child.signalCode === null) {
      try { child.kill('SIGKILL'); } catch (_) { completeQuit(); }
    } else {
      completeQuit();
    }
  }, SIDECAR_STOP_TIMEOUT_MS);
});
