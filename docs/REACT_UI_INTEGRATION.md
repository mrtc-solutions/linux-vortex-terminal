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

## Production and release acceptance

The mocked browser suite is only one layer. The following opt-in runners create
isolated sidecars and use actual HTTP responses, real approved `whoami` execution,
PTY/SSE output, independent shell sessions, and saved-conversation branching:

```sh
npm run build
python3 scripts/test_live_ui.py            # Python-served production build
python3 scripts/test_live_ui.py --dev      # authenticated Vite proxy
python3 scripts/test_live_ui.py --package  # actual extracted Debian package
```

`npm run test:release` requires ten checks, without skips: lint/typechecking,
production build, Python regressions, legacy JS regressions, React browser tests,
three live browser targets, native Electron/IPC/PTY, and real-weight GGUF inference.
GitHub Actions installs Electron, Xvfb/Openbox, Chromium and a CPU GGUF engine, and
downloads a small real model into runner temporary storage. Missing prerequisites
fail the gate; the earlier regression-only `scripts/final_gates.py` is not a
substitute for this release suite.

The native test drives the actual frameless Electron window and preload bridge.
The real-provider test uses a tiny story model from `ggml-org/models` on Hugging
Face. It verifies successful real inference through the GGUF provider, not answer
quality, every Ollama/llamafile version, or suitability for operational advice.
Model weights and binaries are never committed. The acceptance output records
the model SHA-256 for reproducibility.

The UI now includes model import/activation/removal, guarded Ollama downloads,
conversation search and Edit & Branch, saved operation evidence restoration,
native window controls, and a bounded Agent Mode surface distinct from AI Ops.

## Compatibility and limits

Legacy scripts remain only for explicit compatibility/fallback and their regression
coverage. They are not loaded into the React document. Desktop startup builds
React; Debian packaging refuses to silently omit it and verifies its digest.
Deleting the compatibility renderer is a separate migration, not a prerequisite
for eliminating simultaneous script collisions.

These tests do not certify every external model, privileged host mutation, every
legacy branch feature, or every desktop/window-manager combination. A 10/10 result
means all ten defined gates passed—not that all possible bugs are absent.

See [REAL_INTEGRATION_AUDIT.md](REAL_INTEGRATION_AUDIT.md) for historical failure
evidence and remediation. The latest `release-acceptance` PR check is the source
of truth for the current commit's release result.
