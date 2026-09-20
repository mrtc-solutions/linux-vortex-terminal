'use strict';

/** No-network regression tests for Electron runtime preflight. The real native
 * acceptance suite must report a missing binary honestly rather than importing
 * node_modules/electron/index.js, whose fallback behavior downloads one. */

const assert = require('assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { electronExecutablePath, isInstalled } = require('../scripts/ensure-electron');

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vortex-electron-preflight-'));
try {
  const electronDir = path.join(root, 'electron');
  const dist = path.join(electronDir, 'dist');
  fs.mkdirSync(dist, { recursive: true });
  fs.writeFileSync(path.join(dist, 'version'), 'v44.3.0\n');
  fs.writeFileSync(path.join(electronDir, 'path.txt'), 'electron\n');
  const executable = path.join(dist, 'electron');
  fs.writeFileSync(executable, '#!/bin/sh\nexit 0\n', { mode: 0o755 });

  const options = { electronDir, env: {}, platform: 'linux' };
  assert.strictEqual(electronExecutablePath('44.3.0', options), executable);
  assert.strictEqual(isInstalled('44.3.0', options), true);
  assert.strictEqual(electronExecutablePath('44.2.0', options), null, 'version mismatch must be rejected');
  fs.chmodSync(executable, 0o644);
  assert.strictEqual(electronExecutablePath('44.3.0', options), null, 'a non-executable Unix file must be rejected');
  fs.chmodSync(executable, 0o755);
  fs.mkdirSync(path.join(dist, 'not-a-binary'));
  fs.writeFileSync(path.join(electronDir, 'path.txt'), 'not-a-binary\n');
  assert.strictEqual(electronExecutablePath('44.3.0', options), null, 'a directory must not count as an executable');

  fs.writeFileSync(path.join(electronDir, 'path.txt'), '../outside\n');
  assert.strictEqual(electronExecutablePath('44.3.0', options), null, 'path.txt traversal must be rejected');

  const override = path.join(root, 'system-electron');
  fs.mkdirSync(override);
  const overrideBinary = path.join(override, 'electron');
  fs.writeFileSync(overrideBinary, '#!/bin/sh\nexit 0\n', { mode: 0o755 });
  assert.strictEqual(
    electronExecutablePath('missing-version-is-irrelevant-for-override', {
      electronDir,
      env: { ELECTRON_OVERRIDE_DIST_PATH: override },
      platform: 'linux'
    }),
    overrideBinary,
    'an explicit real system-runtime directory must be usable without reading package metadata'
  );

  assert.strictEqual(
    electronExecutablePath('44.3.0', { electronDir, env: {}, platform: 'win32' }),
    null,
    'platform-specific executable names must not be guessed'
  );
  console.log('Electron runtime preflight tests: PASS');
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}
