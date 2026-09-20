'use strict';
// Real Electron + preload IPC + Python sidecar. No renderer/API mocks.
const { _electron: electron, expect } = require('@playwright/test');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert/strict');
const { electronExecutablePath, electronVersion } = require('../scripts/ensure-electron');

function requireRealElectronBinary() {
  const version = electronVersion();
  const executable = electronExecutablePath(version);
  if (executable) return executable;
  throw new Error(
    '[native acceptance] A real Electron binary is required and is not installed. ' +
    'Run `node scripts/ensure-electron.js --required` on a host with an approved source, ' +
    'or set ELECTRON_OVERRIDE_DIST_PATH to a real system Electron directory. ' +
    'This test intentionally does not import electron/package index.js because that would retry a download.'
  );
}

(async () => {
  const root = path.resolve(__dirname, '..');
  const electronExecutable = requireRealElectronBinary();
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vortex-native-'));
  let app;
  try {
    app = await electron.launch({
      executablePath: electronExecutable,
      args: [path.join(root, 'desktop/main.js'), '--no-sandbox'],
      env: { ...process.env, VORTEX_DATA_DIR: path.join(tmp, 'data'), VORTEX_CONFIG_DIR: path.join(tmp, 'config'), VORTEX_RUNTIME_DIR: path.join(tmp, 'runtime'), VORTEX_UI: '' },
      timeout: 60000,
    });
    const page = await app.firstWindow();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await expect(page.getByTitle('Sidecar connected')).toBeVisible({ timeout: 30000 });
    const ipc = (route, options) => page.evaluate(async ({ route, options }) => window.vortexApi.request(route, options), { route, options });
    assert.ok((await ipc('/api/system/health')).health);
    await assert.rejects(() => ipc('/api/not-an-allowed-route'));
    await page.getByLabel('Maximize application').click();
    await expect(page.getByLabel('Restore application')).toBeVisible();
    await page.getByLabel('Restore application').click();
    await expect(page.getByLabel('Maximize application')).toBeVisible();
    await page.getByLabel('Minimize application').click();
    await expect.poll(() => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isMinimized())).toBe(true);
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].restore());
    await page.getByTitle('Vortex Terminal start menu', { exact: true }).click();
    await page.getByRole('dialog', { name: 'VORTEX TERMINAL START MENU', exact: true }).getByRole('button', { name: /^Host Shell / }).click();
    const shell = page.getByRole('dialog', { name: 'HOST SHELL (LIVE PTY)', exact: true });
    const input = shell.getByPlaceholder('Type into the live host shell…');
    await expect(input).toBeEnabled();
    await input.fill("printf 'NATIVE_%s_OK\\n' PTY");
    await input.press('Enter');
    await expect(shell.locator('pre')).toContainText('NATIVE_PTY_OK', { timeout: 15000 });
    await shell.getByLabel('Close window').click();
    await expect.poll(async () => (await ipc('/api/sessions')).sessions.filter(s => s.status === 'running').length).toBe(0);
    assert.deepEqual(errors, []);
    const closed = app.waitForEvent('close');
    // Clicking the control that shuts the app down can tear the page down before
    // Playwright's click() settles, which rejects with "Target page, context or
    // browser has been closed" even though the click landed. The assertion that
    // matters is that the application really exits, so only that specific race is
    // tolerated: if the window does not close, `closed` still rejects.
    await page.getByLabel('Close application').click({ timeout: 15000 }).catch((error) => {
      if (!/closed/i.test(String(error && error.message))) throw error;
    });
    await closed;
    app = null;
    console.log('PASS: native Electron startup, real IPC, allowlist rejection, minimize/maximize/restore/close, real PTY/SSE and cleanup');
  } finally {
    if (app) await app.close();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
