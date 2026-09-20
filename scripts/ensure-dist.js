#!/usr/bin/env node
'use strict';

/**
 * `prepreview` hook for `npm run preview`: rebuild `dist/` only when it is
 * missing or older than the sources, then let the sidecar serve.
 *
 * Unlike `npm start`, this step never blocks the preview: when the build
 * cannot run (low memory, OOM-kill, compile error), it warns and exits 0.
 * The sidecar serves an existing bundle when present, otherwise its legacy UI
 * fallback, instead of leaving the operator with nothing.
 */

const {
  MIN_BUILD_AVAILABLE_BYTES,
  availableMemoryBytes,
  looksLikeOOM,
  needsRebuild,
  runBuildWithOOMRetry
} = require('./start');

async function main({
  needsRebuildFn = needsRebuild,
  availableMemoryBytesFn = availableMemoryBytes,
  runBuildWithOOMRetryFn = runBuildWithOOMRetry,
  looksLikeOOMFn = looksLikeOOM
} = {}) {
  if (!needsRebuildFn()) {
    process.stderr.write('[vortex-preview] dist/ is fresh; serving without a rebuild.\n');
    return 0;
  }
  const availableBytes = availableMemoryBytesFn();
  if (availableBytes !== null && availableBytes < MIN_BUILD_AVAILABLE_BYTES) {
    const availableMB = Math.floor(availableBytes / (1024 * 1024));
    process.stderr.write(
      `[vortex-preview] warning: only ${availableMB} MiB RAM is available; skipping a rebuild that could destabilize this host.\n` +
      `[vortex-preview] Free RAM or add swap (safe threshold: ${MIN_BUILD_AVAILABLE_BYTES / (1024 * 1024)} MiB); serving the existing bundle or legacy UI.\n`
    );
    return 0;
  }
  process.stderr.write('[vortex-preview] dist/ is missing or stale; rebuilding…\n');
  const result = await runBuildWithOOMRetryFn();
  if (result.ok) return 0;
  if (looksLikeOOMFn(result)) {
    process.stderr.write(
      '[vortex-preview] warning: the rebuild was OOM-killed (low RAM), so this preview\n' +
      '[vortex-preview] serves the existing bundle (or legacy UI if none). Free memory and rerun for the React shell,\n' +
      '[vortex-preview] or build once with NODE_OPTIONS=--max-old-space-size=384.\n'
    );
  } else {
    process.stderr.write(
      '[vortex-preview] warning: the rebuild failed (see output above), so this preview\n' +
      '[vortex-preview] serves the existing bundle (or legacy UI if none). Fix the error and rerun for the React shell.\n'
    );
  }
  return 0;
}

module.exports = { main };

if (require.main === module) {
  main().then(
    code => process.exit(code),
    error => {
      process.stderr.write(`[vortex-preview] warning: ${error && error.message ? error.message : error} (serving anyway)\n`);
      process.exit(0);
    }
  );
}
