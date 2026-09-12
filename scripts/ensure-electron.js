#!/usr/bin/env node
'use strict';

/**
 * Ensure the platform Electron binary pinned in node_modules/electron is
 * actually present on disk.
 *
 * Why this script exists: Electron 44+ no longer downloads its platform
 * binary during `npm install`. The ~110 MB zip is deferred to the first
 * `npm start`, which then fails on hosts that cannot reach GitHub release
 * assets (corporate proxies, regional blocks) with the confusing pair:
 *
 *   TypeError: fetch failed
 *   Error: Electron failed to install correctly.
 *
 * This installer pulls the download forward to install time, retries
 * through known mirrors when GitHub is unreachable, verifies the result,
 * and — when every source fails — prints exact remediation instead of
 * dying mid-start. It never fabricates a runtime:
 *
 *   node scripts/ensure-electron.js            best-effort, exit 0 on failure
 *                                              (used by `npm postinstall` so
 *                                              lint/test/preview keep working)
 *   node scripts/ensure-electron.js --required exit 1 on failure
 *                                              (used by `npm start`)
 */

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const ELECTRON_DIR = path.join(ROOT, 'node_modules', 'electron');
const INSTALL_JS = path.join(ELECTRON_DIR, 'install.js');
const ATTEMPT_TIMEOUT_MS = 10 * 60 * 1000;

// Mirrors tried, in order, when the default source (GitHub release assets,
// or the operator's own ELECTRON_MIRROR / npm config) fails. These mirrors
// omit the upstream "v" prefix in their directory names, so each attempt
// also sets ELECTRON_CUSTOM_DIR to the "{{ version }}" template.
const FALLBACK_MIRRORS = [
  'https://npmmirror.com/mirrors/electron/',
  'https://registry.npmmirror.com/-/binary/electron/',
  'https://mirrors.huaweicloud.com/electron/'
];

function log(message) {
  process.stderr.write(`[ensure-electron] ${message}\n`);
}

function electronVersion() {
  try {
    const manifest = JSON.parse(fs.readFileSync(path.join(ELECTRON_DIR, 'package.json'), 'utf8'));
    return typeof manifest.version === 'string' ? manifest.version : null;
  } catch (_) {
    return null;
  }
}

/**
 * Mirrors the checks in node_modules/electron/install.js and index.js:
 * dist/version must match the npm package version, and the executable
 * recorded in path.txt must exist.
 */
function isInstalled(version) {
  const overrideDir = process.env.ELECTRON_OVERRIDE_DIST_PATH;
  if (overrideDir) {
    return fs.existsSync(path.join(overrideDir, process.platform === 'win32' ? 'electron.exe' : 'electron'));
  }
  try {
    const recorded = fs.readFileSync(path.join(ELECTRON_DIR, 'dist', 'version'), 'utf8').replace(/^v/, '').trim();
    if (recorded !== version) return false;
    const executable = fs.readFileSync(path.join(ELECTRON_DIR, 'path.txt'), 'utf8').trim();
    return executable.length > 0 && fs.existsSync(path.join(ELECTRON_DIR, 'dist', executable));
  } catch (_) {
    return false;
  }
}

/**
 * npm-injected config (npm_config_electron_mirror, ...) outranks ELECTRON_*
 * environment variables inside @electron/get, so a stale/broken .npmrc
 * value would shadow our fallback mirrors. npm exports .npmrc values as
 * env vars into lifecycle scripts, so strip those keys from the whole
 * child environment for fallback attempts to guarantee the intended
 * mirror is what actually gets used.
 */
function clearNpmMirrorConfig(env) {
  const patterns = [
    /^npm_config_electron_/i,
    /^npm_package_config_electron_/i
  ];
  for (const key of Object.keys(env)) {
    if (patterns.some(pattern => pattern.test(key))) delete env[key];
  }
  return env;
}

function attempt(version, label, overrides, stripNpmConfig = false) {
  log(`downloading Electron v${version} (${label}) ...`);
  const env = stripNpmConfig ? clearNpmMirrorConfig({ ...process.env }) : { ...process.env };
  Object.assign(env, overrides);
  const result = spawnSync(process.execPath, [INSTALL_JS], {
    cwd: ROOT,
    stdio: 'inherit',
    env,
    timeout: ATTEMPT_TIMEOUT_MS,
    killSignal: 'SIGKILL'
  });
  if (result.error && result.error.code === 'ETIMEDOUT') {
    log(`${label}: timed out after ${ATTEMPT_TIMEOUT_MS / 60000} minutes`);
    return false;
  }
  if (result.status === 0 && isInstalled(version)) return true;
  log(`${label}: source failed${result.signal ? ` (${result.signal})` : ''}`);
  return false;
}

function remediation(version) {
  const lines = [
    `Electron v${version} binary is NOT installed and no download source was reachable.`,
    '',
    'The app itself is fine — its runtime was never fetched. Fix one of:',
    '  1. Network/proxy: allow https://github.com and',
    '     https://objects.githubusercontent.com (release assets), then run',
    '     `node scripts/ensure-electron.js --required` or reinstall.',
    '  2. Mirror (recommended where GitHub is blocked):',
    '     ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ \\',
    '     ELECTRON_CUSTOM_DIR="{{ version }}" \\',
    '     node scripts/ensure-electron.js --required',
    '  3. System Electron: point ELECTRON_OVERRIDE_DIST_PATH at a distro',
    '     Electron install directory, then `npm run start:electron`.',
    '',
    'No-Electron fallback to test the full workbench in a browser:',
    '  npm run preview   # serves the same UI on http://127.0.0.1:4173'
  ];
  return lines.join('\n');
}

/** Returns true when a usable Electron binary is present afterwards. */
function ensureElectron() {
  const version = electronVersion();
  if (!version || !fs.existsSync(INSTALL_JS)) {
    log('node_modules/electron is missing — run `npm install` first (devDependency electron is required).');
    return false;
  }
  if (isInstalled(version)) {
    log(`Electron v${version} binary already present.`);
    return true;
  }

  if (attempt(version, 'default source', {})) return true;
  for (const mirror of FALLBACK_MIRRORS) {
    const used = attempt(version, `mirror ${mirror}`, {
      ELECTRON_MIRROR: mirror,
      ELECTRON_CUSTOM_DIR: '{{ version }}'
    }, true);
    if (used) return true;
  }

  log(`\n${remediation(version)}\n`);
  return false;
}

if (require.main === module) {
  const required = process.argv.slice(2).includes('--required');
  const ok = ensureElectron();
  if (!ok && required) process.exit(1);
}

module.exports = { ensureElectron, isInstalled, electronVersion, ELECTRON_DIR, ROOT };
