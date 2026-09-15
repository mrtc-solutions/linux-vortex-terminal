# Real integration audit — 2026-09-15

## Verdict: NOT ready for an unconditional merge/release

The passing unit tests and mocked React browser suite did not establish production
integration or full legacy parity. This audit tested commit ccb838f with its built
React output and isolated backend data. No legacy files were deleted. No privileged
host mutation or real model download was performed.

## Runtime evidence

| Area | Result | Evidence / limits |
|---|---|---|
| Production React served by Python | **FAIL — release blocker** | Chromium receives the single-file React HTML but renders an empty body. Console explicitly reports the inline script blocked by `script-src 'self'`. All three live browser tests fail at startup. `vite-plugin-singlefile` inlines the bundle; backend `_headers()` does not authorize it. Google Fonts CSS is also blocked, but the script is the startup blocker. |
| Dev UI with real authenticated backend | **FAIL** | Through the current Vite proxy, `/api/auth/session` returns 403 `cross_origin_denied`; subsequent API calls return 401. All three live browser tests fail at handshake. This is distinct from the production CSP failure. |
| Direct backend PTY / SSE | **PASS, bounded** | Created a real bash PTY; sent a `printf` command assembling `VORTEX_PTY_OK`; observed the assembled marker in the SSE output (not just echoed input). Killed the session and subsequently confirmed zero running sessions. This does not verify React shell lifecycle or Electron IPC. |
| Direct backend read-only operation | **PASS, bounded** | `whoami` generated a reviewed low-risk plan; default safe policy required explicit approval. Submitted its approval token through `/api/execute`. Final operation `succeeded`, exit 0, stdout `user\n`; conversation stored two messages. Real model output was not used. |
| Read-only Linux acceptance script | **PASS** | `tests/linux_acceptance.sh` with isolated data: doctor, adapters, database integrity and `dpkg --audit`; exit 0. No privileged mutations tested. |
| Actual model inference | **BLOCKED** | Real `/api/models`, `/api/models/gguf`, `/api/llamafile` probes: Ollama connection refused, no GGUF files/engine, no installed llamafile binary. Deterministic council fallback works; no successful LLM inference can be certified. |
| Native Electron | **BLOCKED** | No installed Electron runtime or Xvfb. `scripts/ensure-electron.js` attempted default and mirror sources; both failed to download. IPC security code/static tests are not native runtime evidence. |
| Debian package | **FAIL for new-UI delivery** | Built an actual .deb and inspected it with `dpkg-deb -c`: `usr/share/vortex/frontend/index.html` and legacy scripts present; no React `dist/index.html`. The current build script explicitly packages legacy assets only. |

## Confirmed parity gaps (source tracing)

These counterexamples disprove complete parity; this is not an exhaustive parity
certification of all old features.

- **GGUF import and activation:** legacy `frontend/models.js` calls the import
  route and renders USE FOR ROLE controls. React Models lists files; `importGguf`
  exists only as an unused API helper.
- **Ollama management:** legacy UI wires model pull/activate/remove and install
  flows. React Models renders a status/reason section; pull/activate/remove API
  helpers have no React callers.
- **Edit & Branch:** legacy workspace renders user-message editors and calls the
  message-edit endpoint. React defines `editMessage` but does not call it.
- **Conversation search:** legacy index has `conversation-search`; React History
  has no search control.
- **Native window controls:** Electron creates `frame: false`; legacy windows.js
  consumes the `vortexWindow` preload bridge. No React component references that
  bridge. React popup controls are not native application-window controls.
- **Rich transcript restoration:** current React resume restores saved message
  text, not the full set of live operation cards.

## Old-file disposition

Old scripts are **not redundant yet**. Backend `_ui_entrypoint()` uses legacy HTML
when the React build is absent or `VORTEX_UI=legacy` is selected. Debian packaging,
legacy tests, lint scripts and final_gates.py still reference them. Removing them
now would break these paths and remove features not yet ported.

## Reproducing the new live browser checks

`playwright.live.config.ts` and `tests/browser-live/acceptance.spec.ts` are opt-in,
use real HTTP responses (no mocks), and intentionally are not part of the existing
mocked-browser CI gate. The target must use disposable backend data/config and a
fresh React production build. The PTY test opens and kills a real shell; whoami is
read-only and approved using the normal review flow.

```sh
npm run build
# Start a sidecar using isolated VORTEX_DATA_DIR / VORTEX_CONFIG_DIR and a
# capability token. Store that test token in a private file, never in Git.
VORTEX_REAL_ACCEPTANCE=1 \
VORTEX_TEST_TOKEN_FILE=/path/to/private/test-token \
VORTEX_LIVE_URL=http://127.0.0.1:8765 \
npx playwright test --config playwright.live.config.ts
```

`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` can select an installed Chromium. The audit
used a temporary npm-distributed Chromium plus its runtime libraries because the
standard browser download was unavailable. No browser binaries, test capabilities,
raw operation approval tokens, or generated packages are committed.

## Required next work

1. Make production assets compatible with CSP without broadly allowing arbitrary
   inline script execution; test the actual Python-served build in CI.
2. Repair and test the authenticated dev-proxy handshake.
3. Ship the new UI in packages and explicitly define fresh-start/build behavior.
4. Port the missing model, conversation and native-window controls; repeat the
   parity audit before deleting old assets.
5. Repeat native Electron/PTY and real-provider acceptance on a suitably equipped
   disposable Linux desktop. Full host mutation acceptance remains separate.

PR #23 should remain unmerged pending these blockers. The earlier green checks
remain valid for their narrower coverage, not as a 10/10 production guarantee.
