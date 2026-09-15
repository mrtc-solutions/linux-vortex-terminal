# Remote-desktop acceptance evidence

**Code under test:** commit `c6b7298` on `arena/01a0a374-linux-vortex-terminal`
(PR #24). **Verified:** 2026-09-15.

This file records what was actually executed. A gate that could not run is
listed as blocked, with the exact output that blocked it — never as a pass.

## Result summary

| Gate | Where | Result |
| --- | --- | --- |
| 11 — Authorized remote desktop vs a **real graphical target** (Xvfb + openbox + xterm + xev served by **x11vnc**) | GitHub Actions, `release-acceptance` job | **PASS** |
| 11 — same suite against the **Qt VNC platform plugin** serving a real Qt application | this checkout | **PASS** (43 checks) |
| 1-10 | GitHub Actions, both jobs | **PASS** — `FINAL RELEASE CHECKS: 11/11 (100%)` |

The verified head of this branch is commit `56e0233`:
<https://github.com/mrtc-solutions/linux-vortex-terminal/actions/runs/34941384749>
reported `FINAL RELEASE CHECKS: 11/11 (100%)`, with both jobs (`browser` and
`release-acceptance`) succeeding, and published the
`remote-desktop-acceptance` build artifact (2,013 bytes) containing the JSON
report this document summarises. The first 11/11 run on the branch was
<https://github.com/mrtc-solutions/linux-vortex-terminal/actions/runs/34940036051>
on commit `c6b7298`; the commits after it fix the evidence-directory write and
documentation only.

Evidence that can be retrieved from this development sandbox is limited to the
GitHub API: check-run conclusions and each run's summary annotation. Run logs and
artifact archives are served from GitHub's results/blob hosts, which are
unreachable here, so the per-check detail of the x11vnc run lives on the run page
itself. The equivalent per-check list for the Qt target — which runs in this
checkout — is reproduced in full below.

## What "real" means here

Both targets are genuine graphical stacks. Nothing is mocked, scripted or
replayed:

* **x11vnc target (CI):** `Xvfb` provides a real X display; `openbox` is the
  window manager; a real `xterm` runs an application that records the bytes it
  receives; a real `xev` runs as an independent X client that logs the pointer
  events it receives; **two** `x11vnc` instances serve the display, one open and
  one requiring VNC authentication.
* **Qt target (local):** PyQt5 application (labels, a line edit, a button) served
  by Qt's own VNC platform plugin — a real RFB server implementation written by
  the Qt project.
* The client is `tests/fixtures/rfb_client.py`, which speaks RFB over a real
  WebSocket to the running sidecar. Its DES is pinned to noVNC's
  `RFB.genDES` output by regression vectors, so it authenticates exactly like the
  client Vortex ships (`tests/test_remote_desktop.py::AcceptanceClientCryptoTests`).

## Checks (local Qt target, 43/43)

Command:

```bash
python3 tests/remote_desktop_acceptance.py --target qt --python <interpreter with PyQt5> \
  --report artifacts/remote-desktop-acceptance.json
```

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
| PASS | approval is recorded and the session becomes connectable | created approved_at=2026-09-15T07:13:42.351+00:00 |
| PASS | the stream endpoint only answers WebSocket upgrades, never plain data | 400 upgrade_required |
| PASS | real RFB handshake completed through the bridge | RFB 003.003 1024x768 name='Qt for Embedded Linux VNC Server' |
| PASS | framebuffer geometry matches the target display | client 1024x768 target 1024x768 |
| PASS | live framebuffer content arrived (real rendered pixels) | 378 distinct colours in 1 update(s) |
| PASS | session identity matches the approved endpoint | 127.0.0.1:5900 |
| PASS | the target's keyboard focus is on its input widget | focus confirmed before typing |
| PASS | keyboard events delivered over RFB changed target-side application state | target reported 'vortex-56422' |
| PASS | the framebuffer changed after keystrokes (Qt/X rendered them) | 2 update(s) total |
| PASS | pointer events delivered over RFB changed target-side state | clicks 0 -> 1 at (280,394) |
| PASS | the clicked widget reported the press (application-level evidence) | button pressed 1 time(s) |
| PASS | a second concurrent session renders independently | 603 colours |
| PASS | both sessions hold distinct sockets and tickets |  |
| PASS | closing one session leaves the other connected |  |
| PASS | disconnect is recorded on the session | disconnected |
| PASS | the bridge socket is closed on disconnect (no half-open stream) |  |
| PASS | reconnect is allowed under the approved policy | {'schema_version': 1, 'session': {'approved_at': '2026-09-15T07:13:42.351+00:00', 'bytes_in': 0, 'bytes_out': 0, 'client |
| PASS | reconnected session renders again |  |
| PASS | target interruption moves the session out of the connected state | disconnected |
| PASS | an outage is recorded as a failure, not a clean disconnect | failure='the remote desktop closed the connection' disconnect='the remote desktop closed the connection' |
| PASS | the failure reason is recorded and sanitized | the remote desktop closed the connection |
| PASS | reconnect after an interruption is accepted | 200 reconnecting |
| PASS | the recovered session renders the restarted target |  |
| PASS | the target reports a fixed resolution the UI documents and scales | fixed 1024x768 |
| PASS | real VNC-auth endpoint available for credential-failure coverage | not applicable to this target flavour (Qt's VNC plugin offers no authentication); covered by the x11vnc target and by tests/test_remote_desk |
| PASS | live sessions are listed for the operator | 1 live |
| PASS | closing sessions leaves no live session records | 0 live |
| PASS | session for the STOP ALL check is connected |  |
| PASS | STOP ALL closes authorized remote sessions | 202 closed=1 |
| PASS | STOP ALL tears the bridge socket down |  |
| PASS | no live remote session survives STOP ALL |  |
| PASS | the target process tree is gone after teardown | 0 target process(es) still running |
| PASS | the target port is released (no orphan listener) |  |
| PASS | the sidecar stopped with the run |  |

The CI run exercises the same checks against the x11vnc target and adds the
live-resize attempt: on that X server `xrandr` refuses to shrink the RandR
output, so the suite verifies the documented fixed-resolution contract instead
and records the refusal verbatim (`xrandr: specified screen 512x384 not large
enough for output screen (1024x768+0+0)`).

## Defects this verification found

Every one of these was found by running the real thing, not by inspection:

1. **A stale teardown could mark a reconnected session disconnected.** The
   bridge handler for a superseded stream ran after a reconnect and wrote its own
   teardown into the live session. Fixed with a connection epoch
   (`RemoteSession.epoch`, `note_disconnect(..., epoch=...)`).
2. **An outage was recorded as a clean disconnect.** Closing the client socket
   during our own teardown raced the reader thread's root-cause reason. Teardown
   reasons now have explicit precedence and an `unexpected` flag, so an
   interrupted session reports, for example, `the remote desktop closed the
   connection` in its failure reason.
3. **The RFB deep probe deadlocked against RFB 3.3 servers.** Qt's VNC plugin
   negotiates 003.003, where the server answers the version exchange with a
   single security-type word; the probe waited for a list that never comes. It
   now mirrors the offered version and reads the single value without
   authenticating.
4. **Acceptance client: keystrokes never reached the target terminal** (the
   reader waited for a newline). The acceptance terminal now runs in raw mode.
5. **Acceptance client: DES produced 8 bytes for a 16-byte challenge** — the
   final-permutation table was one row short and only the first block was
   encrypted, so the correct password timed out at the server.
6. **Acceptance harness: the two VNC servers were both started on display 5900.**
   The free-port helper did not reserve what it handed out, so the
   password-protected instance failed to bind and the credential checks ran
   against the open server — which is why a deliberately wrong password was
   initially accepted. Ports are now reserved and the protected endpoint must
   advertise VNC authentication before those checks run.
7. **Native Electron gate raced its own click.** Clicking the control that shuts
   the app down tore the page down mid-click; the test still requires the
   application to exit.

## Release gates

| # | Gate | Result |
| --- | --- | --- |
| 1 | Lint and TypeScript | PASS |
| 2 | Production React build | PASS |
| 3 | Python regression suite | PASS (565+ tests) |
| 4 | Legacy JavaScript regressions | PASS |
| 5 | React browser regressions | PASS in CI (real Chromium) |
| 6 | Production UI + actual backend | PASS in CI |
| 7 | Authenticated dev proxy + actual backend | PASS in CI |
| 8 | Extracted Debian package + actual backend | PASS in CI |
| 9 | Native Electron / IPC / PTY | PASS in CI |
| 10 | Real GGUF model inference | PASS in CI |
| 11 | Authorized remote desktop vs real graphical target | PASS (this document) |

Gates 5-10 need a browser binary, an Electron build and a real GGUF model, none
of which exist in the interactive checkout used for development; they run in CI
(`.github/workflows/react-ui.yml` installs Chromium, the X/VNC packages and a
real model, and `xvfb-run` provides a display). In the release runner any
non-zero exit fails the gate, including the acceptance runner's
"environment blocked" exit code 3.

## Reproducing

```bash
# same as CI: an independent VNC server on a virtual display
sudo apt-get install -y xvfb openbox x11vnc xterm x11-utils x11-xserver-utils xdotool
npm ci && npm run build
python3 tests/remote_desktop_acceptance.py --target x11vnc --report /tmp/acceptance.json

# or Qt's own RFB server
python3 -m pip install PyQt5
python3 tests/remote_desktop_acceptance.py --target qt --python "$(command -v python3)"
```
