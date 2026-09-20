#!/usr/bin/env node
'use strict';

/**
 * `npm start` entry for the Vortex Terminal desktop shell.
 *
 * Guarantees the Electron platform binary exists (downloading it with
 * mirror fallback when needed) before launching, so a failed first start
 * produces one clear explanation instead of Electron's raw
 * "Electron failed to install correctly" crash.
 *
 * The React bundle is rebuilt incrementally: when `dist/index.html` is newer
 * than every build input the rebuild is skipped, so everyday launches stay
 * fast and low-memory hosts are not asked to rebuild for no reason.
 *
 * Launcher flags (consumed here, never forwarded to the app):
 *   --rebuild              rebuild `dist/` even when it looks fresh
 *   --no-build, --skip-build
 *                          start without building (uses the last `dist/`,
 *                          or the legacy UI when no build exists)
 *   -h, --help             print usage
 * Any other arguments after `npm start --` are forwarded to the app.
 */

const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { ensureElectron, ELECTRON_DIR, ROOT } = require('./ensure-electron');

const APP_ENTRY = path.join(ROOT, 'desktop', 'main.js');
const CLI_JS = path.join(ELECTRON_DIR, 'cli.js');
const DIST_INDEX = path.join(ROOT, 'dist', 'index.html');

// Files whose mtime invalidates the bundle, plus everything under src/.
const BUILD_INPUT_FILES = [
  'index.html',
  'vite.config.ts',
  'package.json',
  'package-lock.json',
  'tsconfig.json'
];
const BUILD_INPUT_DIRS = ['src'];

// Bounded tail kept from the build log for failure diagnosis.
const BUILD_LOG_TAIL_BYTES = 200 * 1024;
// Below this much free RAM the build is likely to be OOM-killed on a
// desktop host, so warn up front instead of after the kill.
const LOW_MEMORY_WARN_BYTES = 700 * 1024 * 1024;

function parseArgs(argv) {
  const options = { rebuild: false, skipBuild: false, help: false, forward: [] };
  for (const arg of argv) {
    if (arg === '--rebuild') options.rebuild = true;
    else if (arg === '--no-build' || arg === '--skip-build') options.skipBuild = true;
    else if (arg === '-h' || arg === '--help') options.help = true;
    else options.forward.push(arg);
  }
  // An explicit rebuild wins over an explicit skip: contradictory flags must
  // not silently start a stale bundle.
  if (options.rebuild) options.skipBuild = false;
  return options;
}

function walkMtimes(root, newest) {
  try {
    // The directory's own mtime moves on add/delete/rename, so removed or
    // added sources invalidate the bundle even when no surviving file changed.
    const dirMtime = fs.statSync(root).mtimeMs;
    if (dirMtime > newest) newest = dirMtime;
  } catch (_) {
    return newest;
  }
  let entries;
  try {
    entries = fs.readdirSync(root, { withFileTypes: true });
  } catch (_) {
    return newest;
  }
  for (const entry of entries) {
    // Dependency trees and caches never invalidate the bundle; descending
    // into them would also make the check slow on big checkouts.
    if (entry.name === 'node_modules' || entry.name === '.git' || entry.name === 'dist') continue;
    const full = path.join(root, entry.name);
    let stat;
    try {
      stat = fs.statSync(full);
    } catch (_) {
      continue;
    }
    if (stat.mtimeMs > newest) newest = stat.mtimeMs;
    if (entry.isDirectory()) newest = walkMtimes(full, newest);
  }
  return newest;
}

/** True when the bundle must be rebuilt (missing, stale, or unreadable). */
function needsRebuild(rootDir = ROOT) {
  let distMtime = -1;
  try {
    distMtime = fs.statSync(path.join(rootDir, 'dist', 'index.html')).mtimeMs;
  } catch (_) {
    return true;
  }
  let newestInput = -1;
  for (const file of BUILD_INPUT_FILES) {
    try {
      const mtime = fs.statSync(path.join(rootDir, file)).mtimeMs;
      if (mtime > newestInput) newestInput = mtime;
    } catch (_) {
      // A missing input is not a reason to rebuild; the build itself reports it.
    }
  }
  for (const dir of BUILD_INPUT_DIRS) {
    newestInput = walkMtimes(path.join(rootDir, dir), newestInput);
  }
  return newestInput >= distMtime;
}

/**
 * Conservative V8 heap cap (MiB) for the build child, sized from currently
 * free RAM. The Vortex Terminal bundle builds fine in a 512 MiB heap; capping
 * forces earlier GC instead of growing until the kernel OOM-kills the build
 * on small Kali VMs. Never overrides an explicit user setting.
 */
function heapCapMB(freeBytes) {
  const freeMB = Math.floor(Number(freeBytes) / 1048576);
  if (!Number.isFinite(freeMB) || freeMB <= 0) return 1024;
  return Math.max(512, Math.min(3072, Math.floor(freeMB * 0.6)));
}

function buildEnv() {
  const env = { ...process.env };
  if (!/max[-_]old[-_]space[-_]size/i.test(env.NODE_OPTIONS || '')) {
    const cap = heapCapMB(os.freemem());
    env.NODE_OPTIONS = `${env.NODE_OPTIONS || ''} --max-old-space-size=${cap}`.trim();
  }
  return env;
}

/** True when the build outcome smells like the kernel OOM-killer, not code. */
function looksLikeOOM({ tail, signal, status }) {
  if (signal === 'SIGKILL' || status === 137) return true;
  const text = tail || '';
  // Case-sensitive on purpose: shells report the kill as `Killed` (often glued
  // onto Vite's progress line: `src/main.tsxKilled`), while lowercase
  // `*_killed` counters belong to unrelated tool output.
  if (text.includes('Killed')) return true;
  return /javascript heap out of memory|heap out of memory|ERR_WORKER_OUT_OF_MEMORY/i.test(text);
}

function oomRemediation() {
  return [
    '[vortex-start] the build was KILLED by the OS (out of memory), not by a code error.',
    '[vortex-start] The bundle needs only ~0.5 GB free while it compiles. Fix one of:',
    '[vortex-start]   1. Free RAM: close browser tabs / heavy apps, then check `free -h`.',
    '[vortex-start]   2. Skip the rebuild and reuse the last good bundle:',
    '[vortex-start]        npm start -- --no-build',
    '[vortex-start]   3. Test the workbench in a browser (rebuilds only when stale,',
    '[vortex-start]      serves the legacy UI instead of failing when the build cannot run):',
    '[vortex-start]        npm run preview   # serves http://127.0.0.1:4173',
    '[vortex-start]   4. Low-RAM VM: add swap (e.g. a 2 GB swapfile) or raise the VM memory.',
    '[vortex-start]   5. Force a smaller heap explicitly, then rebuild once:',
    '[vortex-start]        NODE_OPTIONS=--max-old-space-size=768 npm run build && npm start -- --no-build'
  ].join('\n');
}

function buildFailureRemediation() {
  return [
    '[vortex-start] React build failed; desktop launch cancelled.',
    '[vortex-start] The error is in the build output above.',
    '[vortex-start] Escape hatches: `npm start -- --no-build` (reuse last dist/),',
    '[vortex-start] or `npm run preview` (browser workbench, serves even when the build fails).'
  ].join('\n');
}

/**
 * Run `npm run build` with live output, keeping a bounded tail so failures
 * can be diagnosed (OOM-kill vs compile error) after the fact.
 */
function runBuild() {
  return new Promise(resolve => {
    const child = spawn(process.platform === 'win32' ? 'npm.cmd' : 'npm', ['run', 'build'], {
      cwd: ROOT,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: buildEnv()
    });
    let tail = '';
    const tee = chunk => {
      const text = chunk.toString('utf8');
      process.stdout.write(chunk);
      tail += text;
      if (tail.length > BUILD_LOG_TAIL_BYTES) tail = tail.slice(tail.length - BUILD_LOG_TAIL_BYTES);
    };
    child.stdout.on('data', tee);
    child.stderr.on('data', tee);
    child.on('error', error => resolve({ ok: false, tail, signal: null, status: null, error }));
    child.on('exit', (code, signal) => {
      resolve({ ok: code === 0 && !signal, tail, signal: signal || null, status: code, error: null });
    });
  });
}

function printUsage() {
  process.stdout.write(
    [
      'Usage: npm start [-- <app args>] [--rebuild | --no-build]',
      '',
      '  --rebuild            rebuild dist/ even when it looks fresh',
      '  --no-build           skip the rebuild (last dist/, else legacy UI)',
      '  -h, --help           show this help',
      '  -- <app args>        forwarded to the Electron app',
      ''
    ].join('\n')
  );
}

async function maybeBuild(options) {
  const distExists = fs.existsSync(DIST_INDEX);
  if (options.skipBuild) {
    if (distExists) {
      process.stderr.write('[vortex-start] --no-build: reusing the existing dist/ bundle.\n');
    } else {
      process.stderr.write(
        '[vortex-start] --no-build with no dist/ yet: the desktop will serve the legacy UI.\n' +
        '[vortex-start] Run `npm run build` once (or plain `npm start`) for the React shell.\n'
      );
    }
    return true;
  }
  if (!options.rebuild && !needsRebuild()) {
    process.stderr.write('[vortex-start] dist/ is newer than every build input; skipping rebuild (use --rebuild to force).\n');
    return true;
  }
  const freeBytes = os.freemem();
  if (freeBytes > 0 && freeBytes < LOW_MEMORY_WARN_BYTES) {
    const freeMB = Math.floor(freeBytes / 1048576);
    process.stderr.write(
      `[vortex-start] warning: only ${freeMB} MB RAM free — the build may be OOM-killed.\n` +
      '[vortex-start] Close heavy apps, or use `npm start -- --no-build` / `npm run preview`.\n'
    );
  }
  const result = await runBuild();
  if (result.ok) return true;
  if (result.error) {
    process.stderr.write(`[vortex-start] could not run the build: ${result.error.message}\n`);
    process.stderr.write(`${buildFailureRemediation()}\n`);
    return false;
  }
  if (looksLikeOOM(result)) {
    process.stderr.write(`${oomRemediation()}\n`);
    // An OOM-kill says nothing about the code, so a previous good bundle is
    // still trustworthy — launch it rather than stranding the operator.
    if (fs.existsSync(DIST_INDEX)) {
      process.stderr.write('[vortex-start] continuing with the existing dist/ bundle.\n');
      return true;
    }
    return false;
  }
  process.stderr.write(`${buildFailureRemediation()}\n`);
  return false;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    printUsage();
    return 0;
  }
  if (process.platform !== 'linux') {
    process.stderr.write('[vortex-start] Linux Vortex Terminal is Linux-only.\n');
    return 1;
  }

  if (!(await maybeBuild(options))) return 1;
  if (!ensureElectron()) {
    // ensureElectron already printed exact remediation; preview is the
    // zero-Electron way to test the workbench on this host.
    return 1;
  }

  if (!process.env.DISPLAY && !process.env.WAYLAND_DISPLAY) {
    process.stderr.write(
      '[vortex-start] no $DISPLAY/WAYLAND_DISPLAY: on a headless host use\n' +
      '               `xvfb-run -a npm start`, or test in a browser with `npm run preview`.\n'
    );
  }

  // cli.js relays exit codes and termination signals for the child.
  const { spawnSync } = require('child_process');
  const result = spawnSync(process.execPath, [CLI_JS, APP_ENTRY, ...options.forward], {
    cwd: ROOT,
    stdio: 'inherit'
  });
  if (result.error) {
    process.stderr.write(`[vortex-start] failed to launch Electron: ${result.error.message}\n`);
    return 1;
  }
  return result.status === null ? 1 : result.status;
}

module.exports = { parseArgs, needsRebuild, heapCapMB, buildEnv, looksLikeOOM, runBuild };

if (require.main === module) {
  main().then(
    code => process.exit(code),
    error => {
      process.stderr.write(`[vortex-start] startup failed: ${error && error.stack ? error.stack : error}\n`);
      process.exit(1);
    }
  );
}
