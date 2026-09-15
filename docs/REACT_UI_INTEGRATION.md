# React UI regression checks

The React shell (`src/`) and the legacy renderer (`frontend/`) are separate
applications. The existing JavaScript smoke tests primarily cover the legacy
renderer; they are not evidence that React feature wiring works.

## Changes in this pass

- Dependencies are reachable from Tools, the launcher, and the `dependencies`
  terminal command. Inventory and proposals use the real sidecar routes. Apt
  plans open Guardian review; operator-only instructions never execute directly.
- Resume fetches and validates a transcript before changing the selected context,
  replaces terminal history, clears input history, and navigates to Terminal.
  New uses the same selection path. Errors leave the existing selection intact.
  Switching is blocked during a terminal turn or an open/executing approval.
- Windows no longer evict older windows when opening a ninth. Dragging, viewport
  clamping (including resize), a wrapping scrollable restore tray, and editor-aware
  Escape handling prevent the identified navigation collisions.

## Run

```sh
npm ci --ignore-scripts
npx playwright install --with-deps chromium
npm run test:browser
npm run lint
npm run build
npm test
```

`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` optionally selects a preinstalled Chromium.
Browser binaries, traces, and test output do not belong in Git.

The browser suite loads the real React app through Vite in Chromium and mocks
sidecar responses. It covers transcript/context synchronization, failure recovery,
Escape in an editor, dependency plan review without execution, more than eight
windows, a 375px viewport, drag bounds, and navigation while a turn is pending.
Every test also fails on uncaught browser exceptions. CI runs this suite separately
from the legacy/backend tests.

## Limits

These tests do not execute real host mutations, validate native Electron IPC/PTY
behavior, or certify complete feature parity with the legacy renderer. Resume
renders saved message text; it does not reconstruct every rich live-output card.
Legacy scripts and branches are deliberately retained pending a broader parity
and native-desktop acceptance audit. No zero-bug guarantee is implied.

## Subsequent real-backend audit

See [REAL_INTEGRATION_AUDIT.md](REAL_INTEGRATION_AUDIT.md). Real-backend testing
found production startup, authenticated dev-proxy, packaging and parity blockers.
The mocked-browser passes do not supersede these findings.
