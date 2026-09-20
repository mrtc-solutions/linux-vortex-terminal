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
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { ensureElectron, ELECTRON_DIR, ROOT } = require('./ensure-electron');

const APP_ENTRY = path.join(ROOT, 'desktop', 'main.js');
const CLI_JS = path.join(ELECTRON_DIR, 'cli.js');
const DIST_INDEX = path.join(ROOT, 'dist', 'index.html');
const BUILD_META_NAME = '.vortex-build.json';
const BUILD_META_VERSION = 1;

// Loose files whose mtime invalidates the bundle, plus everything under src/.
// package.json / package-lock.json are NOT here: they are fingerprinted by
// dependency content instead, so script-only edits never force a rebuild.
const BUILD_INPUT_FILES = [
  'index.html',
  'vite.config.ts',
  'tsconfig.json'
];
const BUILD_INPUT_DIRS = ['src'];

// Bounded tail kept from the build log for failure diagnosis.
const BUILD_LOG_TAIL_CHARS = 200 * 1024;
const MEBIBYTE = 1024 * 1024;

// The current single-file React workbench is repeatedly verified with this
// V8 cap on a 2-core, 4-GB, swapless Linux host.  It deliberately does not
// scale up with all currently-free RAM: an interactive desktop, Electron, and
// the kernel also need room while Vite is transforming modules.
const DEFAULT_BUILD_HEAP_MB = 512;
const OOM_RETRY_HEAP_MB = 384;
const MIN_BUILD_AVAILABLE_BYTES = 768 * MEBIBYTE;

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

/** Dependency subset of package.json that can change the bundle. */
function hashManifestDeps(pkgFile) {
  try {
    const pkg = JSON.parse(fs.readFileSync(pkgFile, 'utf8'));
    const subset = {
      dependencies: pkg.dependencies || {},
      devDependencies: pkg.devDependencies || {},
      peerDependencies: pkg.peerDependencies || {},
      overrides: pkg.overrides || {}
    };
    return `sha1:${crypto.createHash('sha1').update(JSON.stringify(subset)).digest('hex')}`;
  } catch (_) {
    return null;
  }
}

function hashFileContents(file) {
  try {
    return `sha1:${crypto.createHash('sha1').update(fs.readFileSync(file)).digest('hex')}`;
  } catch (_) {
    return null;
  }
}

function collectInputFiles(rootDir, newest) {
  const files = [];
  const visit = dir => {
    let entries;
    try {
      entries = fs.readdirSync(path.join(rootDir, dir), { withFileTypes: true });
    } catch (_) {
      return newest;
    }
    for (const entry of entries) {
      if (entry.name === 'node_modules' || entry.name === '.git' || entry.name === 'dist') continue;
      const rel = path.join(dir, entry.name);
      let stat;
      try {
        stat = fs.statSync(path.join(rootDir, rel));
      } catch (_) {
        continue;
      }
      if (stat.mtimeMs > newest) newest = stat.mtimeMs;
      if (entry.isDirectory()) {
        newest = visit(rel);
      } else {
        files.push(rel);
      }
    }
    return newest;
  };
  for (const dir of BUILD_INPUT_DIRS) newest = visit(dir);
  for (const file of BUILD_INPUT_FILES) {
    try {
      const mtime = fs.statSync(path.join(rootDir, file)).mtimeMs;
      if (mtime > newest) newest = mtime;
      files.push(file);
    } catch (_) {
      // A missing loose input is simply absent from the set; the build
      // itself reports it, and its absence still invalidates the manifest.
    }
  }
  files.sort();
  return { files, newest };
}

function collectInputs(rootDir) {
  const { files, newest } = collectInputFiles(rootDir, -1);
  return {
    files,
    newest,
    manifests: {
      package: hashManifestDeps(path.join(rootDir, 'package.json')),
      lock: hashFileContents(path.join(rootDir, 'package-lock.json'))
    }
  };
}

function readBuildMeta(rootDir) {
  try {
    const meta = JSON.parse(fs.readFileSync(path.join(rootDir, 'dist', BUILD_META_NAME), 'utf8'));
    if (!meta || meta.version !== BUILD_META_VERSION || !Array.isArray(meta.files) ||
        typeof meta.newest !== 'number' || !meta.manifests || typeof meta.manifests !== 'object') {
      return null;
    }
    return meta;
  } catch (_) {
    return null;
  }
}

/** Record what a successful managed build was built from. Best-effort: a
 *  missing manifest only falls back to the legacy mtime rule. */
function writeBuildMeta(rootDir = ROOT) {
  try {
    const current = collectInputs(rootDir);
    fs.mkdirSync(path.join(rootDir, 'dist'), { recursive: true });
    fs.writeFileSync(
      path.join(rootDir, 'dist', BUILD_META_NAME),
      JSON.stringify({ version: BUILD_META_VERSION, ...current })
    );
    return true;
  } catch (_) {
    return false;
  }
}

function sameStringArrays(a, b) {
  return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((v, i) => v === b[i]);
}

/** True when the bundle must be rebuilt (missing, stale, or unreadable).
 *
 * A build manifest (`dist/.vortex-build.json`) records the exact input file
 * set, newest input mtime, and dependency fingerprints of the last managed
 * build, so added/removed sources are detected by SET DIFFERENCE — not by
 * directory mtimes, which some filesystems quantize too coarsely to trust.
 * A bare `vite build` (no manifest update) is still honored: when dist/ is
 * newer than every current input and the set matches, the build covered it.
 */
function needsRebuild(rootDir = ROOT) {
  let distMtime = -1;
  try {
    distMtime = fs.statSync(path.join(rootDir, 'dist', 'index.html')).mtimeMs;
  } catch (_) {
    return true;
  }
  const current = collectInputs(rootDir);
  const meta = readBuildMeta(rootDir);
  if (!meta) {
    // No manifest (bare `vite build`, older launcher, wiped meta): legacy
    // mtime rule, including the manifest FILES' own mtimes.
    let newest = current.newest;
    for (const file of ['package.json', 'package-lock.json']) {
      try {
        const mtime = fs.statSync(path.join(rootDir, file)).mtimeMs;
        if (mtime > newest) newest = mtime;
      } catch (_) {
        // Missing manifests cannot invalidate by mtime; the build reports them.
      }
    }
    return newest >= distMtime;
  }
  const setsEqual = sameStringArrays(current.files, meta.files);
  const contentChanged = current.newest > meta.newest;
  const manifestsChanged = JSON.stringify(current.manifests) !== JSON.stringify(meta.manifests);
  if (setsEqual && !contentChanged && !manifestsChanged) return false;
  if (!setsEqual || manifestsChanged) return true;
  // Only mtimes moved: a bare build newer than every input already covered it.
  return distMtime < current.newest;
}

/** Parse Linux `MemAvailable` from procfs without treating filesystem cache as
 * unavailable RAM. Returns null for malformed or unavailable input. */
function parseMemAvailableBytes(meminfo) {
  if (typeof meminfo !== 'string') return null;
  const match = /^MemAvailable:\s+(\d+)\s+kB\s*$/mi.exec(meminfo);
  if (!match) return null;
  const kibibytes = Number(match[1]);
  return Number.isSafeInteger(kibibytes) ? kibibytes * 1024 : null;
}

function optionalBytes(readFile, file) {
  try {
    const raw = String(readFile(file, 'utf8')).trim();
    // cgroup v2 uses `max` for no memory limit.
    if (raw === 'max') return null;
    const value = Number(raw);
    // Very large v1 values are the conventional unlimited sentinel, not a
    // useful host budget. Keep the parser bounded as well as numeric.
    return Number.isSafeInteger(value) && value >= 0 && value < Number.MAX_SAFE_INTEGER / 2 ? value : null;
  } catch (_) {
    return null;
  }
}

function cgroupDirectories(root, relativePath) {
  const parts = String(relativePath || '').split('/').filter(Boolean);
  if (parts.some(part => part === '.' || part === '..' || /[\\\u0000-\u001f]/.test(part))) return [];
  const directories = [];
  // A child can inherit a finite `memory.max` from a parent even when its own
  // file says `max`, so account for each ancestor's remaining capacity too.
  for (let length = parts.length; length >= 0; length -= 1) {
    directories.push(path.join(root, ...parts.slice(0, length)));
  }
  return directories;
}

/** Memory-controller file pairs for the process's actual cgroup and all of
 * its parents, then common root fallbacks for simple/container layouts. */
function cgroupMemoryLayouts(readFile = fs.readFileSync) {
  const layouts = [];
  const add = (limitFile, currentFile) => {
    const key = `${limitFile}\u0000${currentFile}`;
    if (!layouts.some(item => item.key === key)) layouts.push({ key, limitFile, currentFile });
  };
  const addHierarchy = (root, relativePath, limitName, currentName) => {
    for (const directory of cgroupDirectories(root, relativePath)) {
      add(path.join(directory, limitName), path.join(directory, currentName));
    }
  };
  try {
    for (const line of String(readFile('/proc/self/cgroup', 'utf8')).split(/\r?\n/)) {
      const firstColon = line.indexOf(':');
      const secondColon = firstColon < 0 ? -1 : line.indexOf(':', firstColon + 1);
      if (firstColon < 0 || secondColon < 0) continue;
      // A cgroup path itself may contain a colon, so split only the two
      // protocol separators rather than discarding a valid trailing path.
      const hierarchy = line.slice(0, firstColon);
      const controllers = line.slice(firstColon + 1, secondColon);
      const relativePath = line.slice(secondColon + 1);
      if (hierarchy === '0' && controllers === '') {
        addHierarchy('/sys/fs/cgroup', relativePath, 'memory.max', 'memory.current');
      } else if (controllers.split(',').includes('memory')) {
        addHierarchy('/sys/fs/cgroup/memory', relativePath, 'memory.limit_in_bytes', 'memory.usage_in_bytes');
      }
    }
  } catch (_) {
    // Root fallbacks below cover hosts where procfs is intentionally hidden.
  }
  add('/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory.current');
  add('/sys/fs/cgroup/memory/memory.limit_in_bytes', '/sys/fs/cgroup/memory/memory.usage_in_bytes');
  return layouts;
}

/** Remaining bytes in the process's cgroup v2/v1 memory controller. */
function cgroupAvailableMemoryBytes(readFile = fs.readFileSync) {
  let available = null;
  for (const { limitFile, currentFile } of cgroupMemoryLayouts(readFile)) {
    const limit = optionalBytes(readFile, limitFile);
    const current = optionalBytes(readFile, currentFile);
    if (limit === null || current === null) continue;
    const remaining = Math.max(0, limit - current);
    available = available === null ? remaining : Math.min(available, remaining);
  }
  return available;
}

/**
 * Memory that the build may safely consume. On Linux this uses MemAvailable
 * and, when present, the tighter cgroup budget; elsewhere it falls back to
 * Node's free-memory estimate. Injectables keep the calculation testable.
 */
function availableMemoryBytes({
  platform = process.platform,
  readFile = fs.readFileSync,
  freeMemory = os.freemem
} = {}) {
  let systemAvailable = null;
  if (platform === 'linux') {
    try {
      systemAvailable = parseMemAvailableBytes(readFile('/proc/meminfo', 'utf8'));
    } catch (_) {
      systemAvailable = null;
    }
  }
  const cgroupAvailable = platform === 'linux' ? cgroupAvailableMemoryBytes(readFile) : null;
  if (systemAvailable !== null && cgroupAvailable !== null) return Math.min(systemAvailable, cgroupAvailable);
  if (systemAvailable !== null) return systemAvailable;
  if (cgroupAvailable !== null) return cgroupAvailable;
  try {
    const fallback = Number(freeMemory());
    return Number.isFinite(fallback) && fallback >= 0 ? fallback : null;
  } catch (_) {
    return null;
  }
}

/**
 * Conservative V8 old-space cap for the build child. It is intentionally
 * fixed rather than proportional to free RAM: on a 4-GB desktop, a 3-GB V8
 * allowance leaves too little room for the OS and can cause a SIGKILL even
 * though this bundle compiles comfortably in 512 MiB. Never overrides an
 * explicit operator-provided heap setting.
 */
function heapCapMB(_availableBytes) {
  return DEFAULT_BUILD_HEAP_MB;
}

function hasExplicitHeapCap(env = process.env) {
  return /max[-_]old[-_]space[-_]size/i.test(env.NODE_OPTIONS || '');
}

function buildEnv(heapMB) {
  const env = { ...process.env };
  if (!hasExplicitHeapCap(env)) {
    const requested = Number(heapMB);
    const cap = Number.isSafeInteger(requested) && requested >= 128
      ? requested
      : heapCapMB(availableMemoryBytes());
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
    '[vortex-start] Vortex automatically uses a 512 MiB build heap and retries once at 384 MiB.',
    '[vortex-start] Fix one of:',
    '[vortex-start]   1. Free RAM: close browser tabs / heavy apps, then check `free -h`.',
    '[vortex-start]   2. Skip the rebuild and reuse the last good bundle:',
    '[vortex-start]        npm start -- --no-build',
    '[vortex-start]   3. Test the workbench in a browser (rebuilds only when stale,',
    '[vortex-start]      serves the existing bundle, or legacy UI if none, when a build cannot run):',
    '[vortex-start]        npm run preview   # serves http://127.0.0.1:4173',
    '[vortex-start]   4. Low-RAM VM: add swap (e.g. a 2 GB swapfile) or raise the VM memory.',
    '[vortex-start]   5. Force the smallest verified build heap explicitly:',
    '[vortex-start]        NODE_OPTIONS=--max-old-space-size=384 npm run build && npm start -- --no-build'
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
function runBuild(heapMB) {
  return new Promise(resolve => {
    const child = spawn(process.platform === 'win32' ? 'npm.cmd' : 'npm', ['run', 'build'], {
      cwd: ROOT,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: buildEnv(heapMB)
    });
    let tail = '';
    let settled = false;
    const tee = chunk => {
      const text = chunk.toString('utf8');
      process.stdout.write(chunk);
      tail += text;
      if (tail.length > BUILD_LOG_TAIL_CHARS) tail = tail.slice(tail.length - BUILD_LOG_TAIL_CHARS);
    };
    child.stdout.on('data', tee);
    child.stderr.on('data', tee);
    child.on('error', error => {
      if (settled) return;
      settled = true;
      resolve({ ok: false, tail, signal: null, status: null, error });
    });
    // `close`, not `exit`: the final error line can still be in the pipes
    // when the process exits, and the OOM diagnosis needs that tail.
    child.on('close', (code, signal) => {
      if (settled) return;
      settled = true;
      const ok = code === 0 && !signal;
      if (ok) writeBuildMeta();
      resolve({ ok, tail, signal: signal || null, status: code, error: null });
    });
  });
}

/**
 * A SIGKILL can arrive before V8 reaches its normal heap limit when another
 * desktop process briefly consumes RAM. Retry once at the smallest heap this
 * bundle is verified to build with, unless the operator deliberately supplied
 * their own NODE_OPTIONS heap setting.
 */
async function runBuildWithOOMRetry() {
  let result = await runBuild();
  if (result.ok || result.error || !looksLikeOOM(result) || hasExplicitHeapCap()) return result;
  process.stderr.write(
    `[vortex-start] build was memory-killed; retrying once with a ${OOM_RETRY_HEAP_MB} MiB V8 heap...\n`
  );
  result = await runBuild(OOM_RETRY_HEAP_MB);
  return result;
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

async function maybeBuild(options, {
  distExistsFn = () => fs.existsSync(DIST_INDEX),
  needsRebuildFn = needsRebuild,
  availableMemoryBytesFn = availableMemoryBytes,
  runBuildWithOOMRetryFn = runBuildWithOOMRetry,
  stderrWrite = message => process.stderr.write(message)
} = {}) {
  const distExists = distExistsFn();
  if (options.skipBuild) {
    if (distExists) {
      stderrWrite('[vortex-start] --no-build: reusing the existing dist/ bundle.\n');
    } else {
      stderrWrite(
        '[vortex-start] --no-build with no dist/ yet: the desktop will serve the legacy UI.\n' +
        '[vortex-start] Run `npm run build` once (or plain `npm start`) for the React shell.\n'
      );
    }
    return true;
  }
  if (!options.rebuild && !needsRebuildFn()) {
    stderrWrite('[vortex-start] dist/ is newer than every build input; skipping rebuild (use --rebuild to force).\n');
    return true;
  }
  const availableBytes = availableMemoryBytesFn();
  if (availableBytes !== null && availableBytes < MIN_BUILD_AVAILABLE_BYTES) {
    const availableMB = Math.floor(availableBytes / MEBIBYTE);
    const message =
      `[vortex-start] only ${availableMB} MiB RAM is available; not starting a build that could destabilize this host.\n` +
      `[vortex-start] Free RAM or add swap, then retry (the safe threshold is ${MIN_BUILD_AVAILABLE_BYTES / MEBIBYTE} MiB).\n`;
    if (distExists) {
      stderrWrite(`${message}[vortex-start] continuing with the existing dist/ bundle.\n`);
      return true;
    }
    stderrWrite(`${message}[vortex-start] No existing React bundle is available yet, so desktop launch is cancelled.\n`);
    return false;
  }
  const result = await runBuildWithOOMRetryFn();
  if (result.ok) return true;
  if (result.error) {
    stderrWrite(`[vortex-start] could not run the build: ${result.error.message}\n`);
    stderrWrite(`${buildFailureRemediation()}\n`);
    return false;
  }
  if (looksLikeOOM(result)) {
    stderrWrite(`${oomRemediation()}\n`);
    // An OOM-kill says nothing about the code, so a previous good bundle is
    // still trustworthy — launch it rather than stranding the operator.
    if (distExistsFn()) {
      stderrWrite('[vortex-start] continuing with the existing dist/ bundle.\n');
      return true;
    }
    return false;
  }
  stderrWrite(`${buildFailureRemediation()}\n`);
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

module.exports = {
  DEFAULT_BUILD_HEAP_MB,
  MIN_BUILD_AVAILABLE_BYTES,
  OOM_RETRY_HEAP_MB,
  ROOT,
  availableMemoryBytes,
  buildEnv,
  cgroupAvailableMemoryBytes,
  collectInputs,
  hasExplicitHeapCap,
  heapCapMB,
  looksLikeOOM,
  maybeBuild,
  needsRebuild,
  parseArgs,
  parseMemAvailableBytes,
  readBuildMeta,
  runBuild,
  runBuildWithOOMRetry,
  writeBuildMeta
};

if (require.main === module) {
  main().then(
    code => process.exit(code),
    error => {
      process.stderr.write(`[vortex-start] startup failed: ${error && error.stack ? error.stack : error}\n`);
      process.exit(1);
    }
  );
}
