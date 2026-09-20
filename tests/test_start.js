'use strict';

/**
 * Launcher tests for scripts/start.js: flag parsing/forwarding, incremental
 * rebuild detection, heap-cap sizing, and OOM diagnosis. The launcher must
 * never forward its own flags to Electron, never rebuild when dist/ is
 * fresh, and never mistake an OOM-kill for a code error.
 */

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const start = require('../scripts/start.js');

function touch(file, mtimeMs) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, 'x');
  const date = new Date(mtimeMs);
  fs.utimesSync(file, date, date);
}

function makeTree({ withDist, distMtime, srcMtime }) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vortex-start-'));
  touch(path.join(root, 'src', 'main.tsx'), srcMtime);
  touch(path.join(root, 'index.html'), srcMtime);
  touch(path.join(root, 'vite.config.ts'), srcMtime);
  touch(path.join(root, 'package.json'), srcMtime);
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

// 2. Incremental rebuild detection.
{
  const now = Date.now();
  const fresh = makeTree({ withDist: true, distMtime: now, srcMtime: now - 60000 });
  assert.strictEqual(start.needsRebuild(fresh), false, 'fresh dist/ must skip the rebuild');
  const stale = makeTree({ withDist: true, distMtime: now - 60000, srcMtime: now });
  assert.strictEqual(start.needsRebuild(stale), true, 'stale dist/ must rebuild');
  const missing = makeTree({ withDist: false, distMtime: now, srcMtime: now - 60000 });
  assert.strictEqual(start.needsRebuild(missing), true, 'missing dist/ must rebuild');
  // Deleting (or adding) a source bumps the directory mtime past dist/.
  const pruned = makeTree({ withDist: true, distMtime: now, srcMtime: now - 60000 });
  fs.rmSync(path.join(pruned, 'src', 'main.tsx'));
  assert.strictEqual(start.needsRebuild(pruned), true, 'a deleted source must rebuild');
  for (const root of [fresh, stale, missing, pruned]) fs.rmSync(root, { recursive: true, force: true });
}

// 3. Heap cap: bounded, proportional, never zero.
{
  assert.strictEqual(start.heapCapMB(0), 1024);
  assert.strictEqual(start.heapCapMB(-5), 1024);
  assert.strictEqual(start.heapCapMB(NaN), 1024);
  // 800 MB free -> floor of 512 (the bundle builds fine in 512 MB).
  assert.strictEqual(start.heapCapMB(800 * 1048576), 512);
  // 2 GB free -> 60% = 1228 (truncated).
  assert.strictEqual(start.heapCapMB(2048 * 1048576), 1228);
  // 16 GB free -> ceiling of 3072.
  assert.strictEqual(start.heapCapMB(16 * 1073741824), 3072);
}

// 4. buildEnv respects an explicit user heap setting.
{
  const before = process.env.NODE_OPTIONS;
  process.env.NODE_OPTIONS = '--max-old-space-size=4096';
  assert.strictEqual(start.buildEnv().NODE_OPTIONS, '--max-old-space-size=4096');
  delete process.env.NODE_OPTIONS;
  assert.match(start.buildEnv().NODE_OPTIONS || '', /--max-old-space-size=\d+/);
  if (before === undefined) delete process.env.NODE_OPTIONS;
  else process.env.NODE_OPTIONS = before;
}

// 5. OOM diagnosis: signals and shell/markers, not plain exit codes.
{
  assert.strictEqual(start.looksLikeOOM({ tail: '', signal: 'SIGKILL', status: null }), true);
  assert.strictEqual(start.looksLikeOOM({ tail: '', signal: null, status: 137 }), true);
  assert.strictEqual(start.looksLikeOOM({ tail: 'transforming (1) src/main.tsxKilled', signal: null, status: 1 }), true);
  assert.strictEqual(start.looksLikeOOM({ tail: 'FATAL ERROR: JavaScript heap out of memory', signal: null, status: 1 }), true);
  assert.strictEqual(start.looksLikeOOM({ tail: 'error TS2322: Type X is not assignable', signal: null, status: 1 }), false);
  assert.strictEqual(start.looksLikeOOM({ tail: '', signal: null, status: 0 }), false);
}

console.log('launcher start tests: PASS');
