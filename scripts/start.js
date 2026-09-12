#!/usr/bin/env node
'use strict';

/**
 * `npm start` entry for the VORTEX desktop shell.
 *
 * Guarantees the Electron platform binary exists (downloading it with
 * mirror fallback when needed) before launching, so a failed first start
 * produces one clear explanation instead of Electron's raw
 * "Electron failed to install correctly" crash. Any arguments after
 * `npm start --` are forwarded to the app.
 */

const { spawnSync } = require('child_process');
const path = require('path');
const { ensureElectron, ELECTRON_DIR, ROOT } = require('./ensure-electron');

const APP_ENTRY = path.join(ROOT, 'desktop', 'main.js');
const CLI_JS = path.join(ELECTRON_DIR, 'cli.js');

function main() {
  if (process.platform !== 'linux') {
    process.stderr.write('[vortex-start] Linux Vortex Terminal is Linux-only.\n');
    process.exit(1);
  }

  if (!ensureElectron()) {
    // ensureElectron already printed exact remediation; preview is the
    // zero-Electron way to test the workbench on this host.
    process.exit(1);
  }

  if (!process.env.DISPLAY && !process.env.WAYLAND_DISPLAY) {
    process.stderr.write(
      '[vortex-start] no $DISPLAY/WAYLAND_DISPLAY: on a headless host use\n' +
      '               `xvfb-run -a npm start`, or test in a browser with `npm run preview`.\n'
    );
  }

  // cli.js relays exit codes and termination signals for the child.
  const result = spawnSync(process.execPath, [CLI_JS, APP_ENTRY, ...process.argv.slice(2)], {
    cwd: ROOT,
    stdio: 'inherit'
  });
  if (result.error) {
    process.stderr.write(`[vortex-start] failed to launch Electron: ${result.error.message}\n`);
    process.exit(1);
  }
  process.exit(result.status === null ? 1 : result.status);
}

main();
