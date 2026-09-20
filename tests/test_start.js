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

// 6. runBuild resolves after the pipes flush (`close`, not `exit`), so the
// diagnosis tail contains the final build line.
async function main() {
  const result = await start.runBuild();
  assert.strictEqual(result.ok, true, `vite build must succeed in a test checkout (tail: ${result.tail.slice(-300)})`);
  assert.match(result.tail, /built in/, 'runBuild must capture the full log tail');
  console.log('launcher start tests: PASS');
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
