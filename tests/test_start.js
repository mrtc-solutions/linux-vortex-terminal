'use strict';

/**
 * Launcher tests for scripts/start.js: flag parsing/forwarding, incremental
 * rebuild detection, heap-cap sizing, and OOM diagnosis. The launcher must
 * never forward its own flags to Electron, never rebuild when dist/ is
 * fresh, and never mistake an OOM-kill for a code error.
 */

const assert = require('assert');
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const start = require('../scripts/start.js');
const ensureDist = require('../scripts/ensure-dist.js');

function touch(file, mtimeMs, content = 'x') {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content);
  const date = new Date(mtimeMs);
  fs.utimesSync(file, date, date);
}

const PKG = deps => JSON.stringify({ name: 't', scripts: { build: 'vite build' }, dependencies: deps });

function makeTree({ withDist, distMtime, srcMtime }) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vortex-start-'));
  touch(path.join(root, 'src', 'main.tsx'), srcMtime);
  touch(path.join(root, 'index.html'), srcMtime);
  touch(path.join(root, 'vite.config.ts'), srcMtime);
  touch(path.join(root, 'tsconfig.json'), srcMtime);
  touch(path.join(root, 'package.json'), srcMtime, PKG({ a: '1.0.0' }));
  touch(path.join(root, 'package-lock.json'), srcMtime, 'lock-1');
  if (withDist) touch(path.join(root, 'dist', 'index.html'), distMtime);
  return root;
}

// 1. Flag parsing: launcher flags are consumed, app args forwarded.
{
  const parsed = start.parseArgs(['--rebuild', '--foo', 'bar']);
  assert.strictEqual(parsed.rebuild, true);
  assert.strictEqual(parsed.skipBuild, false);
  assert.deepStrictEqual(parsed.forward, ['--foo', 'bar']);
}
{
  const parsed = start.parseArgs(['--no-build']);
  assert.strictEqual(parsed.skipBuild, true);
  assert.deepStrictEqual(parsed.forward, []);
}
{
  const parsed = start.parseArgs(['--skip-build']);
  assert.strictEqual(parsed.skipBuild, true);
}
{
  const parsed = start.parseArgs(['--', '--devtools']);
  assert.deepStrictEqual(parsed.forward, ['--', '--devtools']);
}
// Contradictory flags must rebuild, never silently start stale.
{
  const parsed = start.parseArgs(['--no-build', '--rebuild']);
  assert.strictEqual(parsed.rebuild, true);
  assert.strictEqual(parsed.skipBuild, false);
}
{
  assert.strictEqual(start.parseArgs(['-h']).help, true);
  assert.strictEqual(start.parseArgs(['--help']).help, true);
}

// 2. Incremental rebuild detection. All timestamps are pinned to the past so
// no assertion depends on filesystem timestamp granularity.
{
  const T0 = Date.now() - 60000;
  const roots = [];
  const managed = () => {
    const root = makeTree({ withDist: true, distMtime: T0, srcMtime: T0 - 1000 });
    roots.push(root);
    assert.strictEqual(start.writeBuildMeta(root), true, 'manifest must be writable');
    return root;
  };

  // Legacy path (no manifest): pure mtime rule.
  const fresh = makeTree({ withDist: true, distMtime: T0, srcMtime: T0 - 1000 });
  roots.push(fresh);
  assert.strictEqual(start.needsRebuild(fresh), false, 'fresh dist/ must skip the rebuild');
  const stale = makeTree({ withDist: true, distMtime: T0 - 1000, srcMtime: T0 });
  roots.push(stale);
  assert.strictEqual(start.needsRebuild(stale), true, 'stale dist/ must rebuild');
  const missing = makeTree({ withDist: false, distMtime: T0, srcMtime: T0 - 1000 });
  roots.push(missing);
  assert.strictEqual(start.needsRebuild(missing), true, 'missing dist/ must rebuild');

  // Managed path (manifest written): nothing changed -> skip.
  assert.strictEqual(start.needsRebuild(managed()), false, 'unchanged managed tree must skip');

  // Added/removed sources are caught by SET DIFFERENCE, not mtimes.
  const pruned = managed();
  fs.rmSync(path.join(pruned, 'src', 'main.tsx'));
  assert.strictEqual(start.needsRebuild(pruned), true, 'a deleted source must rebuild');
  const grown = managed();
  touch(path.join(grown, 'src', 'new.ts'), T0 - 50000);
  assert.strictEqual(start.needsRebuild(grown), true, 'an added source must rebuild');

  // Edited sources are caught by mtime vs the manifest.
  const edited = managed();
  touch(path.join(edited, 'src', 'main.tsx'), T0 + 5000);
  assert.strictEqual(start.needsRebuild(edited), true, 'an edited source must rebuild');

  // Dependency changes rebuild; script-only package.json edits do not.
  const deps = managed();
  touch(path.join(deps, 'package.json'), T0 + 5000, PKG({ a: '2.0.0' }));
  assert.strictEqual(start.needsRebuild(deps), true, 'changed dependencies must rebuild');
  const locked = managed();
  touch(path.join(locked, 'package-lock.json'), T0 + 5000, 'lock-2');
  assert.strictEqual(start.needsRebuild(locked), true, 'changed lockfile must rebuild');
  const scriptsOnly = managed();
  const pkg = JSON.parse(fs.readFileSync(path.join(scriptsOnly, 'package.json'), 'utf8'));
  pkg.scripts.lint = 'echo lint';
  touch(path.join(scriptsOnly, 'package.json'), T0 + 5000, JSON.stringify(pkg));
  assert.strictEqual(start.needsRebuild(scriptsOnly), false, 'script-only edits must not rebuild');

  // A bare build newer than every input covers mtime-only staleness.
  const bare = managed();
  touch(path.join(bare, 'src', 'main.tsx'), T0 + 5000);
  assert.strictEqual(start.needsRebuild(bare), true, 'sanity: edit first invalidates');
  touch(path.join(bare, 'dist', 'index.html'), T0 + 9000);
  assert.strictEqual(start.needsRebuild(bare), false, 'bare build covering the edit must skip');

  // A corrupt manifest falls back to the mtime rule instead of crashing.
  const corrupt = managed();
  fs.writeFileSync(path.join(corrupt, 'dist', '.vortex-build.json'), 'not json');
  assert.strictEqual(start.needsRebuild(corrupt), false, 'corrupt manifest + fresh dist must skip');

  for (const root of roots) fs.rmSync(root, { recursive: true, force: true });
}

// 3. The default heap stays small even when the machine is mostly free. A
// 4-GB desktop must retain room for the OS/Electron rather than giving V8 60%.
{
  assert.strictEqual(start.DEFAULT_BUILD_HEAP_MB, 512);
  for (const value of [0, -5, NaN, 800 * 1048576, 2048 * 1048576, 16 * 1073741824]) {
    assert.strictEqual(start.heapCapMB(value), 512);
  }
  assert.strictEqual(start.OOM_RETRY_HEAP_MB, 384);
  assert.ok(start.MIN_BUILD_AVAILABLE_BYTES >= 768 * 1048576);
}

// 4. Linux memory accounting prefers MemAvailable and then the tighter cgroup
// budget; malformed proc/cgroup input cannot crash the launcher.
{
  assert.strictEqual(start.parseMemAvailableBytes('MemTotal: 100 kB\nMemAvailable: 42 kB\n'), 42 * 1024);
  assert.strictEqual(start.parseMemAvailableBytes('MemFree: 42 kB\n'), null);
  assert.strictEqual(start.parseMemAvailableBytes('MemAvailable: nope kB\n'), null);

  const v2 = {
    '/sys/fs/cgroup/memory.max': '8192\n',
    '/sys/fs/cgroup/memory.current': '2048\n'
  };
  const v2Reader = file => {
    if (!(file in v2)) throw new Error('missing');
    return v2[file];
  };
  assert.strictEqual(start.cgroupAvailableMemoryBytes(v2Reader), 6144);
  const nestedV2 = {
    // A colon is legal in a cgroup path, so parsing must preserve everything
    // after the protocol's second colon delimiter.
    '/proc/self/cgroup': '0::/user/vortex:blue\n',
    '/sys/fs/cgroup/user/vortex:blue/memory.max': '12000\n',
    '/sys/fs/cgroup/user/vortex:blue/memory.current': '3000\n',
    // The nearest cgroup permits 9,000 bytes, but its parent only has 3,000
    // left. The parent cap is still a real limit for this build process.
    '/sys/fs/cgroup/user/memory.max': '8000\n',
    '/sys/fs/cgroup/user/memory.current': '5000\n'
  };
  const nestedReader = file => {
    if (!(file in nestedV2)) throw new Error('missing');
    return nestedV2[file];
  };
  assert.strictEqual(start.cgroupAvailableMemoryBytes(nestedReader), 3000, 'must honor the tightest actual-cgroup ancestor budget');
  assert.strictEqual(start.availableMemoryBytes({
    platform: 'linux',
    readFile: file => file === '/proc/meminfo' ? 'MemAvailable: 10 kB\n' : v2Reader(file),
    freeMemory: () => 999999
  }), 6144);
  const exhaustedV2 = { ...v2, '/sys/fs/cgroup/memory.current': '8192\n' };
  const exhaustedReader = file => {
    if (!(file in exhaustedV2)) throw new Error('missing');
    return exhaustedV2[file];
  };
  assert.strictEqual(start.availableMemoryBytes({
    platform: 'linux',
    readFile: file => file === '/proc/meminfo' ? 'MemAvailable: 999 kB\n' : exhaustedReader(file),
    freeMemory: () => 999999
  }), 0, 'a known exhausted cgroup must not be confused with unknown memory');
  assert.strictEqual(start.availableMemoryBytes({ platform: 'darwin', freeMemory: () => 12345 }), 12345);
  assert.strictEqual(
    start.availableMemoryBytes({ platform: 'darwin', freeMemory: () => { throw new Error('unavailable'); } }),
    null,
    'unknown memory must stay distinguishable from a real zero-byte budget'
  );
}

// 5. buildEnv applies the safe default/retry cap but respects an explicit user
// heap setting, including Node's underscore spelling.
{
  const before = process.env.NODE_OPTIONS;
  try {
    delete process.env.NODE_OPTIONS;
    assert.match(start.buildEnv().NODE_OPTIONS || '', /--max-old-space-size=512/);
    assert.match(start.buildEnv(start.OOM_RETRY_HEAP_MB).NODE_OPTIONS || '', /--max-old-space-size=384/);
    process.env.NODE_OPTIONS = '--max-old-space-size=4096';
    assert.strictEqual(start.buildEnv().NODE_OPTIONS, '--max-old-space-size=4096');
    assert.strictEqual(start.hasExplicitHeapCap(), true);
    process.env.NODE_OPTIONS = '--max_old_space_size=640';
    assert.strictEqual(start.hasExplicitHeapCap(), true);
  } finally {
    if (before === undefined) delete process.env.NODE_OPTIONS;
    else process.env.NODE_OPTIONS = before;
  }
}

// 6. OOM diagnosis: signals and shell/markers, not plain exit codes.
{
  assert.strictEqual(start.looksLikeOOM({ tail: '', signal: 'SIGKILL', status: null }), true);
  assert.strictEqual(start.looksLikeOOM({ tail: '', signal: null, status: 137 }), true);
  assert.strictEqual(start.looksLikeOOM({ tail: 'transforming (1) src/main.tsxKilled', signal: null, status: 1 }), true);
  assert.strictEqual(start.looksLikeOOM({ tail: 'FATAL ERROR: JavaScript heap out of memory', signal: null, status: 1 }), true);
  assert.strictEqual(start.looksLikeOOM({ tail: 'error TS2322: Type X is not assignable', signal: null, status: 1 }), false);
  assert.strictEqual(start.looksLikeOOM({ tail: '', signal: null, status: 0 }), false);
}

// 7. runBuild resolves after the pipes flush (`close`, not `exit`), so the
// diagnosis tail contains the final build line. Exercise both the normal
// low-RAM budget and the automatic-retry budget against the real bundle.
async function main() {
  // A real zero-byte cgroup budget must decline a build. Existing dist/ stays
  // launchable; a first launch is cancelled rather than risking the desktop.
  const lowMemoryOptions = { rebuild: true, skipBuild: false, help: false, forward: [] };
  const desktopLogs = [];
  let desktopBuildCalled = false;
  const lowMemoryDependencies = exists => ({
    distExistsFn: () => exists,
    availableMemoryBytesFn: () => 0,
    runBuildWithOOMRetryFn: async () => {
      desktopBuildCalled = true;
      return { ok: true };
    },
    stderrWrite: message => desktopLogs.push(String(message))
  });
  assert.strictEqual(await start.maybeBuild(lowMemoryOptions, lowMemoryDependencies(true)), true);
  assert.strictEqual(await start.maybeBuild(lowMemoryOptions, lowMemoryDependencies(false)), false);
  assert.strictEqual(desktopBuildCalled, false, 'desktop launcher must not start a build with a known exhausted budget');
  assert.match(desktopLogs.join(''), /continuing with the existing dist\/ bundle/);
  assert.match(desktopLogs.join(''), /desktop launch is cancelled/);

  // Browser preview must share desktop launch's low-memory guard rather than
  // attempting a risky rebuild just because it deliberately degrades to 0.
  const stderrWrite = process.stderr.write;
  const previewLog = [];
  let previewBuildCalled = false;
  try {
    process.stderr.write = chunk => {
      previewLog.push(String(chunk));
      return true;
    };
    const previewCode = await ensureDist.main({
      needsRebuildFn: () => true,
      availableMemoryBytesFn: () => start.MIN_BUILD_AVAILABLE_BYTES - 1,
      runBuildWithOOMRetryFn: async () => {
        previewBuildCalled = true;
        return { ok: true };
      }
    });
    assert.strictEqual(previewCode, 0);
    assert.strictEqual(previewBuildCalled, false, 'preview must not launch a build below the shared safety threshold');
    assert.match(previewLog.join(''), /existing bundle or legacy UI/);
  } finally {
    process.stderr.write = stderrWrite;
  }

  const result = await start.runBuild();
  assert.strictEqual(result.ok, true, `vite build must succeed in a test checkout (tail: ${result.tail.slice(-300)})`);
  assert.match(result.tail, /built in/, 'runBuild must capture the full log tail');
  const retryBudget = await start.runBuild(start.OOM_RETRY_HEAP_MB);
  assert.strictEqual(retryBudget.ok, true, `384 MiB retry build must succeed (tail: ${retryBudget.tail.slice(-300)})`);

  // Simulate the exact shell symptom from an OOM kill, then let the second
  // invocation run the real npm/Vite build. This verifies npm start continues
  // rather than merely printing recovery advice.
  const fakeBin = fs.mkdtempSync(path.join(os.tmpdir(), 'vortex-start-fake-npm-'));
  const state = path.join(fakeBin, 'state');
  const log = path.join(fakeBin, 'calls');
  const fakeNpm = path.join(fakeBin, 'npm');
  const realNpm = execFileSync('which', ['npm'], { encoding: 'utf8' }).trim();
  fs.writeFileSync(fakeNpm, [
    '#!/bin/sh',
    'printf "call\\n" >> "$VORTEX_TEST_NPM_LOG"',
    'if [ ! -e "$VORTEX_TEST_NPM_STATE" ]; then',
    '  : > "$VORTEX_TEST_NPM_STATE"',
    '  printf "transforming (1) src/main.tsxKilled\\n" >&2',
    '  exit 137',
    'fi',
    'exec "$VORTEX_TEST_REAL_NPM" "$@"'
  ].join('\n'), { mode: 0o755 });
  const old = {
    NODE_OPTIONS: process.env.NODE_OPTIONS,
    PATH: process.env.PATH,
    VORTEX_TEST_NPM_LOG: process.env.VORTEX_TEST_NPM_LOG,
    VORTEX_TEST_NPM_STATE: process.env.VORTEX_TEST_NPM_STATE,
    VORTEX_TEST_REAL_NPM: process.env.VORTEX_TEST_REAL_NPM
  };
  try {
    delete process.env.NODE_OPTIONS;
    process.env.PATH = `${fakeBin}${path.delimiter}${old.PATH || ''}`;
    process.env.VORTEX_TEST_NPM_LOG = log;
    process.env.VORTEX_TEST_NPM_STATE = state;
    process.env.VORTEX_TEST_REAL_NPM = realNpm;
    const automaticRetry = await start.runBuildWithOOMRetry();
    assert.strictEqual(automaticRetry.ok, true, `automatic low-heap retry must recover (tail: ${automaticRetry.tail.slice(-300)})`);
    assert.strictEqual(fs.readFileSync(log, 'utf8').trim().split(/\r?\n/).length, 2, 'OOM retry must invoke npm exactly twice');
  } finally {
    for (const [key, value] of Object.entries(old)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    fs.rmSync(fakeBin, { recursive: true, force: true });
  }
  console.log('launcher start tests: PASS');
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
