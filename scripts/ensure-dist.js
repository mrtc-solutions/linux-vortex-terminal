#!/usr/bin/env node
'use strict';

/**
 * `prepreview` hook for `npm run preview`: rebuild `dist/` only when it is
 * missing or older than the sources, then let the sidecar serve.
 *
 * Unlike `npm start`, this step never blocks the preview: when the build
 * fails (low-memory OOM-kill, compile error), it warns and exits 0, and the
 * sidecar honestly serves the legacy UI fallback instead of nothing.
 */

const { needsRebuild, runBuild, looksLikeOOM } = require('./start');

async function main() {
  if (!needsRebuild()) {
    process.stderr.write('[vortex-preview] dist/ is fresh; serving without a rebuild.\n');
    return 0;
  }
  process.stderr.write('[vortex-preview] dist/ is missing or stale; rebuilding…\n');
  const result = await runBuild();
  if (result.ok) return 0;
  if (looksLikeOOM(result)) {
    process.stderr.write(
      '[vortex-preview] warning: the rebuild was OOM-killed (low RAM), so this preview\n' +
      '[vortex-preview] serves the legacy UI. Free memory and rerun for the React shell,\n' +
      '[vortex-preview] or build once with NODE_OPTIONS=--max-old-space-size=768.\n'
    );
  } else {
    process.stderr.write(
      '[vortex-preview] warning: the rebuild failed (see output above), so this preview\n' +
      '[vortex-preview] serves the legacy UI. Fix the error and rerun for the React shell.\n'
    );
  }
  return 0;
}

if (require.main === module) {
  main().then(
    code => process.exit(code),
    error => {
      process.stderr.write(`[vortex-preview] warning: ${error && error.message ? error.message : error} (serving anyway)\n`);
      process.exit(0);
    }
  );
}
