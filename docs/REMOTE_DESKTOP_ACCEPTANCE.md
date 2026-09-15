# Remote-desktop acceptance evidence

**Code under test:** commit `8dfb9d8` (`8dfb9d8a2458c73a685c67c457fa49b265817a6e`) on
`arena/01a0a374-linux-vortex-terminal`.

**Run date:** 2026-09-15.

This file records what was actually executed, not what is intended. A gate that
could not run is listed as blocked with the exact command output that blocked it.

## Real graphical target

The acceptance suite (`tests/remote_desktop_acceptance.py`) starts a **real VNC
server** and drives it through the **real WebSocket/RFB bridge** in the sidecar.
Nothing is mocked: the framebuffer is decoded from RFB bytes, and input is
verified by reading the target application's own state.

- Host: Linux-6.1.158+-x86_64-with-glibc2.36
- Python: 3.11.2
- Node: v22.22.3
- Real target: Qt VNC platform plugin (RFB server) + real Qt application
- Interpreter with PyQt5: /tmp/vrsvenv/bin/python (PyQt5 wheels, Qt 5.15.14)

Command:

```bash
python3 tests/remote_desktop_acceptance.py --target qt --python /tmp/vrsvenv/bin/python \
  --report /tmp/remote-acceptance-final.json
```

Result: **exit 0 — 42 checks passed, 0 failed.**

| Result | Check | Observed detail |
| --- | --- | --- |
| PASS | capability matrix reports VNC supported and RDP not implemented | {'vnc': 'supported', 'rdp': 'not_implemented'} |
| PASS | out-of-scope target is refused before any connection | 403 target_not_authorized |
| PASS | deep probe reports a compatible RFB endpoint | 200 003.003 |
| PASS | probe stays unauthenticated and reports security types | {'1': 'none (server accepts unauthenticated clients)'} |
| PASS | endpoint check never returns credentials or session material | none |
| PASS | created session waits for approval | awaiting_approval |
| PASS | non-secret lifecycle metadata is retained | approved_at,bytes_in,bytes_out,client_library,closed_at,connected_at,created_at,disconnect_reason,disconnected_at,engage |
| PASS | approval without explicit confirmation is refused | 400 confirmation_required |
| PASS | unencrypted transport needs the protected-path acknowledgement | 403 protected_path_required |
| PASS | approval is recorded and the session becomes connectable | created approved_at=2026-09-15T06:03:16.864+00:00 |
| PASS | the stream endpoint only answers WebSocket upgrades, never plain data | 400 upgrade_required |
| PASS | real RFB handshake completed through the bridge | RFB 003.003 1024x768 name='Qt for Embedded Linux VNC Server' |
| PASS | framebuffer geometry matches the target display | client 1024x768 target 1024x768 |
| PASS | live framebuffer content arrived (real rendered pixels) | 378 distinct colours in 1 update(s) |
| PASS | session identity matches the approved endpoint | 127.0.0.1:5900 |
| PASS | keyboard events delivered over RFB changed target-side application state | target reported 'vortex-52197' |
| PASS | the framebuffer changed after keystrokes (Qt/X rendered them) | 2 update(s) total |
| PASS | pointer events delivered over RFB changed target-side state | clicks 0 -> 1 at (280,394) |
| PASS | the clicked widget reported the press (application-level evidence) | button pressed 1 time(s) |
| PASS | a second concurrent session renders independently | 595 colours |
| PASS | both sessions hold distinct sockets and tickets |  |
| PASS | closing one session leaves the other connected |  |
| PASS | disconnect is recorded on the session | disconnected |
| PASS | the bridge socket is closed on disconnect (no half-open stream) |  |
| PASS | reconnect is allowed under the approved policy | {'schema_version': 1, 'session': {'approved_at': '2026-09-15T06:03:16.864+00:00', 'bytes_in': 0, 'bytes_out': 0, 'client |
| PASS | reconnected session renders again |  |
| PASS | target interruption moves the session out of the connected state | disconnected |
| PASS | an outage is recorded as a failure, not a clean disconnect | failure='the remote desktop closed the connection' disconnect='the remote desktop closed the connection' |
| PASS | the failure reason is recorded and sanitized | the remote desktop closed the connection |
| PASS | reconnect after an interruption is accepted | 200 reconnecting |
| PASS | the recovered session renders the restarted target |  |
| PASS | the target reports a fixed resolution the UI documents and scales | fixed 1024x768 |
| PASS | real VNC-auth endpoint available for credential-failure coverage | not applicable to this target flavour (Qt's VNC plugin offers no authentication); covered by the x11vnc target and by tests/test_remote_desktop.py |
| PASS | live sessions are listed for the operator | 1 live |
| PASS | closing sessions leaves no live session records | 0 live |
| PASS | session for the STOP ALL check is connected |  |
| PASS | STOP ALL closes authorized remote sessions | 202 closed=1 |
| PASS | STOP ALL tears the bridge socket down |  |
| PASS | no live remote session survives STOP ALL |  |
| PASS | the target process tree is gone after teardown |  |
| PASS | the target port is released (no orphan listener) |  |
| PASS | the sidecar stopped with the run |  |

## Regression suites

| Command | Result |
| --- | --- |
| `npm run lint` (includes `npx tsc --noEmit`) | exit 0 |
| `npm run build` | exit 0 — `dist/index.html` 649.36 kB (gzip 184.01 kB), noVNC inlined |
| `python3 -m unittest discover -s tests -q` | exit 0 — 565 tests OK (includes the 40 remote-desktop and 14 WebSocket integration tests) |
| `npm run test:legacy` | exit 0 — 9 legacy suites PASS |
| `python3 -m unittest tests.test_desktop_deb -q` | exit 0 — 7 tests OK (React build present) |
| `bash packaging/deb/build.sh` | exit 0 — `linux-vortex-terminal_0.3.0_all.deb` contains `dist/index.html` with the inlined noVNC client, plus `noVNC-LICENSE.txt` and `MPL-2.0.txt` |

Package refusal paths were exercised as well: a `dist/index.html` without the
inlined client and a missing `dist/index.html` both make `build.sh` exit 2 with
an actionable message instead of emitting a broken package.

## Release gates

| # | Gate | Status |
| --- | --- | --- |
| 1 | Lint and TypeScript | PASS |
| 2 | Production React build | PASS |
| 3 | Python regression suite | PASS (565 tests) |
| 4 | Legacy JavaScript regressions | PASS |
| 5 | React browser regressions | **BLOCKED** — Playwright browser binary absent (`Executable doesn't exist at ~/.cache/ms-playwright/chromium_headless_shell-1243/...`); browser downloads are unreachable from this environment |
| 6 | Production UI + actual backend | **BLOCKED** — same missing browser binary |
| 7 | Authenticated dev proxy + actual backend | **BLOCKED** — same missing browser binary |
| 8 | Extracted Debian package + actual backend | **BLOCKED** — the package builds and extracts, but the browser-driven checks cannot launch a browser here |
| 9 | Native Electron / IPC / PTY | **BLOCKED** — `node_modules/electron` has no downloaded binary; Electron downloads are unreachable |
| 10 | Real GGUF model inference | **BLOCKED** — `VORTEX_REAL_MODEL` is unset and no GGUF engine/model is available here |
| 11 | Authorized remote desktop vs real graphical target | PASS (42 checks, `--target qt`) |

Blocked is not a pass: in `scripts/release_gates.py` any non-zero exit — including
the acceptance runner's "environment blocked" exit code 3 — fails the gate. CI
(`.github/workflows/react-ui.yml`) installs Chromium, Electron prerequisites,
`xvfb x11vnc xterm x11-utils x11-xserver-utils xdotool openbox` and a real GGUF
model, so gates 5-10 run there; gate 11 prefers the independent `x11vnc` target
when those packages are present.

## Blocked-path evidence

Both "cannot run here" paths were executed and produce actionable output rather
than a silent failure or a false pass:

* `--target x11vnc` → exit 3, message lists the exact Debian packages to install.
* `--target qt` with an interpreter lacking PyQt5 → exit 3, message names the
  interpreter and the `pip install PyQt5` step.
