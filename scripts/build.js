#!/usr/bin/env node
'use strict';

/**
 * `npm run build`: compile the singlefile bundle, then record the build
 * manifest (`dist/.vortex-build.json`) so incremental starts can trust
 * `dist/` without rebuilding. Exit code and output match a bare vite run;
 * extra CLI arguments are forwarded to vite.
 */

const { spawnSync } = require('child_process');
const path = require('path');
const { buildEnv, writeBuildMeta, ROOT } = require('./start');

function main() {
  const viteBin = path.join(ROOT, 'node_modules', 'vite', 'bin', 'vite.js');
  const result = spawnSync(process.execPath, [viteBin, 'build', ...process.argv.slice(2)], {
    cwd: ROOT,
    stdio: 'inherit',
    env: buildEnv()
  });
  if (result.error) {
    process.stderr.write(`[vortex-build] could not run vite: ${result.error.message}\n`);
    return 1;
  }
  if (result.signal || result.status !== 0) {
    return result.status === null ? 1 : result.status;
  }
  writeBuildMeta();
  return 0;
}

if (require.main === module) {
  process.exit(main());
}

module.exports = { main };
