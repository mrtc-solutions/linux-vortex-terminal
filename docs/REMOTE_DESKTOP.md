# Authorized remote desktop (VNC)

Vortex Terminal can open a **real remote graphical session** in a window, under
an engagement's authorization, next to the existing local PTY terminal.

This document states exactly what is implemented, what is verified, how the
security model works, how to operate it, and what remains unsupported. Nothing
here is aspirational: every claim maps to code in `backend/remote_desktop.py`,
`src/components/RemoteDesktopView.tsx`, and the tests listed in
[§9 Verification](#9-verification-and-evidence).

---

## 1. Scope and non-goals

| Term | Meaning in Vortex |
| --- | --- |
| Reachable device | Something answers on the approved host/port. Not access. |
| Authenticated remote shell | A PTY session in the existing Shell window. Not graphical. |
| Reachable remote-desktop service | An RFB/VNC service answered the endpoint check. Not access. |
| Authenticated graphical session | The client completed the protocol handshake and the live framebuffer is being rendered. |

Shell access is never reported as graphical access. When a host is reachable
over SSH but no VNC service answers, the operator sees exactly:

> Remote shell access is available, but no compatible graphical session has been verified.

…plus configuration guidance. Vortex never draws a placeholder desktop, never
starts a VNC service on a target, never guesses credentials, and never retries a
rejected password on its own.

**Out of scope by design:** exploit delivery, credential theft, authentication
bypass, persistence, and covert installation of remote-access services.

---

## 2. Support matrix

| Capability | State | Evidence |
| --- | --- | --- |
| VNC / RFB desktops in-app (RFB 3.3–3.8, Raw + DesktopSize) | **Supported and verified** against a real VNC server | `tests/remote_desktop_acceptance.py` (41/41 checks) |
| WebSocket → RFB bridge owned by the sidecar | **Supported** (Python standard library, RFC 6455) | `tests/test_remote_ws.py` |
| SSRF/scope-validated dialling, tickets, ownership | **Supported** | `tests/test_remote_desktop.py` |
| Verified TLS (`vnc+tls`) with system trust store | **Supported** (not exercised against a live TLS VNC server in this environment) | `RemoteDesktopManager.dependency_items()`; unit coverage |
| Unencrypted RFB | **Supported but off by default**; requires the deployment setting *and* per-session acknowledgement of a protected path | `tests/test_remote_desktop.py` |
| RDP in-app | **Not implemented** (there is no reviewer-approved gateway integration; installing FreeRDP host tools changes nothing) | `capabilities_document()["intentionally_not_implemented"]` |
| Clipboard sync, file transfer, audio redirection, shared folders | **Off by default, separately authorized, not implemented** | capability document; `RemoteDesktopView.tsx` |
| Screen or keystroke recording | **Not implemented, and never enabled by default** | capability document |
| Resizing the remote display | Client-side scaling always; server-side resize only when the target supports RFB DesktopSize | acceptance check |

Protocol availability is reported through three distinct states so "supported"
is never confused with "available on this machine":

* `supported` — implemented and verified;
* `supported-but-dependency-missing` — implemented, but a required component is absent (the UI shows the exact install/rebuild step);
* `not-implemented` — no safe integration exists yet (RDP today).

---

## 3. Architecture

```
┌─────────────────────────── Electron / browser renderer (CSP: script-src 'self') ───────────────────────────┐
│  RemoteSessions popup ──approve──▶ sidecar HTTP                                                             │
│  RemoteDesktopView window ──noVNC (bundled, MPL-2.0)──▶ WSS  wss://<same origin>/api/remote-desktop/…      │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                              │  Sec-WebSocket-Protocol: vortex.rfb.v1, vortex-ticket.<token>
                                                              ▼
                                   ┌──────────────── Python sidecar (authority) ────────────────┐
                                   │ 1. authenticate (X-Vortex-Token or HttpOnly session cookie) │
                                   │ 2. verify Origin, consume the single-use session ticket     │
                                   │ 3. re-validate engagement scope + endpoint                  │
                                   │ 4. dial one host:port, then pipe RFB bytes both ways        │
                                   └────────────────────────────────────────────────────────────┘
                                                              │  TCP/TLS to the approved endpoint
                                                              ▼
                                                        VNC / RFB server
```

Key properties:

* **The browser never dials the target.** It connects only to the sidecar's own
  origin; the sidecar performs the network connection. There is no
  browser-side `localhost` dependency and no public exposure of the target or
  of the bridge.
* **The bridge is not a proxy.** It dials exactly one validated `host:port`
  (VNC display range 5900–5999 by default), refuses redirects, and speaks RFB
  framing only — text frames are rejected with close code 1003.
* **noVNC is inlined** into the single-file production document by the Vite
  build, so development, the Python-served build, Electron, the Debian package,
  and packaged previews all carry the client without a runtime download.
* **Windows are isolated.** Each window holds its own socket, ticket, input
  stream, and cleanup handler; closing one never disturbs another.

---

## 4. Authorization chain

1. **Engagement** — an active, unexpired engagement with the target in scope
   (exclusion rules win over inclusion). Cross-user and revoked/expired
   engagements are refused, and are re-checked on every connect *and* reconnect.
2. **Endpoint check (`probe`)** — Banner-only by default; a deep probe lists the
   server's security types and stops before authentication. No credential is
   sent, and the result is reported as availability only.
3. **Session creation** — records target identity, protocol, transport, and
   non-secret metadata; the session state is `awaiting_approval`.
4. **Explicit approval** — requires `confirm: true` plus, for unencrypted
   transports, `unencrypted_approved` and `protected_path_ack`, and re-resolves
   the endpoint. Failures: `confirmation_required`, `protected_path_required`,
   `unencrypted_disabled`.
5. **Ticket** — a short-lived (45 s), single-use, fingerprint-bound token, at
   most four outstanding per session, delivered as a WebSocket subprotocol
   (never in a URL, log, or storage).
6. **Stream upgrade** — the sidecar re-validates origin, credentials, ticket,
   and scope *before* dialling; the socket is handed to the bridge and the
   session becomes `connected`.

---

## 5. Session lifecycle and the remote-session manager

```
created → awaiting_approval → connecting → connected → reconnecting → disconnected | failed → closed
```

The **Remote Sessions** window (`Launcher → Remote Sessions`, or the target's
"Open remote desktop…" action) provides:

* **Dependencies** — real installed/unavailable state, purpose, version, source,
  license, and install/rebuild instructions.
* **Endpoint check** — protocol status (`supported`, `not_implemented`,
  `unavailable`), security types, and the exact shell-vs-graphical guidance.
* **Approval card** — explicit confirmations; nothing connects without them.
* **Open desktop when ready** — opt-in, default **off**, per approved target. It
  *watches* for an endpoint that becomes verifiable and reports readiness; it
  never connects by itself and never enables a service.
* **Per session** — RECONNECT, OPEN/FOCUS, DISCONNECT, CLOSE, plus live state,
  byte counters, timestamps, and sanitized failure reasons.
* **STOP ALL** — the same control that kills local sessions also closes every
  remote session and its socket (`remote_sessions_closed` in the response).

Limits and policy (CLI flag > environment > settings > default):

| Setting | Default | Range | Environment override |
| --- | --- | --- | --- |
| Concurrent sessions | 4 | 1–16 | `VORTEX_REMOTE_MAX_SESSIONS` |
| Idle timeout | 900 s | 30–86400 s | `VORTEX_REMOTE_IDLE_SECONDS` |
| Unencrypted transports allowed | off | — | settings only (per deployment) |
| Extra CA bundle | system store | — | `VORTEX_REMOTE_CA_FILE` |

`window close` semantics are visible in the window footer: with
*keep session on close* off (default) closing the window ends the session and
its socket; with it on, the session is disconnected and retained for an approved
reconnect. One window's teardown can never mark a reconnected session
disconnected (per-connection epoch guard).

---

## 6. Security model

* **Scope and SSRF** — hostnames are parsed and validated, addresses are
  resolved and re-checked against the engagement, ports must be in the display
  range, redirects are never followed, and one validated `host:port` is dialled.
  Loopback requires a literal scope entry; private/CGNAT/ULA addresses require a
  scope match or an explicit acknowledgement; metadata, link-local, multicast,
  and management endpoints are refused (`metadata_blocked`, `blocked_address`,
  `loopback_not_authorized`, `port_out_of_range`, `target_excluded`).
  There is no blanket allow or block of private networks.
* **Authentication and ownership** — every HTTP route and the WebSocket upgrade
  require the sidecar token or the HttpOnly `Vortex-Session` cookie, the request
  origin must match, and tickets are bound to the session *and* the credential
  context. Cross-user and expired/revoked credentials are rejected. The upgrade
  only accepts WebSocket handshakes; plain GETs get `upgrade_required`.
* **Secrets** — credentials live in process/renderer memory only, are cleared
  as soon as the handshake completes, are never written to settings, storage,
  URLs, logs, audit events, reports, or Git, and are never requested by Vortex.
  OS credential storage is not used; there is no "save password" path.
* **Transport** — `vnc+tls` uses the system trust store and never silently
  ignores certificate errors (`tls_handshake_failed`). Unencrypted RFB is
  refused unless the deployment opts in *and* the operator acknowledges an
  approved protected path for that session.
* **Renderer and desktop isolation** — the CSP (`script-src 'self'`) is
  unchanged, node integration stays off, the renderer's remote allowlists and
  same-origin checks are enforced in `desktop/security.js`, and no new
  unrestricted IPC channel was added. Clipboard synchronization is off: noVNC's
  clipboard events are ignored and `clipboardPasteFrom` is never called. Screen
  contents and keystrokes are not recorded; only the fact that input focus moved
  is audited (`input_begin`/`input_end`), never the keys.
* **Failure reporting** — reasons are sanitized and bounded; the UI shows
  progress, authentication failures, disconnects, and recovery, and an outage is
  recorded as a failure reason rather than a clean disconnect.

---

## 7. Dependencies, licensing, deployment

| Component | Role | License | How it is obtained |
| --- | --- | --- | --- |
| `@novnc/novnc` 1.7.0 | RFB client rendering + input | MPL-2.0 | `npm ci` at build time; inlined into `dist/index.html`. Never fetched at runtime. |
| Python sidecar bridge | RFC 6455 WebSocket + RFB piping | MIT (in-tree) | Ships with Vortex; no external package, no `websockify`. |
| Python `ssl`/OpenSSL | Verified TLS transports | PSF-2.0 / Apache-2.0 | Host Python. |
| RDP client | — | — | **Not integrated.** No dependency is installed for it. |

Installing a dependency is always an explicit, reviewed operator action; Vortex
never downloads or executes third-party installers on its own. Missing
components produce actionable errors (for example "run `npm ci && npm run
build`"), never a blank window or a false "connected".

Packaging: `packaging/deb/build.sh` fails with an actionable message if
`dist/index.html` is missing **or** does not contain the inlined noVNC client, so
a Debian package can never ship a remote-desktop window that would open blank.
The Electron shell spawns the same sidecar and sets the renderer session cookie
before the window loads; the desktop preview path is unchanged.

---

## 8. Operator instructions

1. **Select the target from the engagement.** Open the target's details and use
   *Open remote desktop for …* (or `Launcher → Remote Sessions`) — a desktop can
   only be opened for a target the engagement covers.
2. **Check the endpoint.** Press *Endpoint check*. Vortex reports whether an RFB
   service answered, its security types, and — if only SSH is reachable — the
   exact "remote shell access is available…" guidance. Configure a VNC display
   (or an approved tunnel) and re-check.
3. **Create the session, then approve it.** Confirm the authorization checkbox.
   For unencrypted RFB you must additionally acknowledge the protected path.
4. **Open the window.** The window is titled with the target identity and shows
   trusted-vs-plain transport, connection state, and resolution.
5. **Enter credentials in the window** if the server asks for them. They are
   used once for the handshake and discarded.
6. **Click the surface to capture the keyboard.** A banner states that input is
   going to the remote device. Press **Escape twice** or **RELEASE KEYBOARD** to
   hand control back; focus loss releases automatically.
7. **Recover or end.** *RECONNECT* after a disconnect (scope is re-validated),
   *DISCONNECT* to end the stream but keep the record, *CLOSE SESSION* to remove
   it. **STOP ALL** closes everything.

Optional, off by default: *Open desktop when ready* watches a specific approved
target and reports readiness — it does not connect, and it never enables a
service on the target.

---

## 9. Verification and evidence

| Suite | What it proves | Status |
| --- | --- | --- |
| `python3 tests/remote_desktop_acceptance.py` | **Real protocol acceptance.** A genuine VNC server (Qt's VNC platform plugin serving a real Qt application) is driven through the real WebSocket/RFB bridge: live framebuffer content, keyboard changing target-side app state, mouse clicks changing target-side state, session identity, two concurrent isolated sessions, disconnect/reconnect, target interruption and recovery, cleanup, STOP ALL, no orphan processes or listeners. | 41/41 checks pass |
| `python3 -m unittest tests.test_remote_ws -q` | Real sidecar process, hand-written RFC 6455 client: authentication, origin checks, ticket binding/replay, cross-session denial, STOP ALL teardown. | 14/14 pass |
| `python3 -m unittest tests.test_remote_desktop -q` | Scope/SSRF enforcement, ticket lifecycle, approval rules, concurrency/idle/revocation, redaction, dependency reporting, disconnect bookkeeping. | 40/40 pass |
| `python3 tests/remote_desktop_acceptance.py --target x11vnc` | Same acceptance against an **independent** server (Xvfb + openbox + xterm + xev + x11vnc) including a real VNC-authentication endpoint and a live display resize. | Runnable where `xvfb x11vnc xterm x11-utils x11-xserver-utils xdotool openbox` are installed (see [§10](#10-limitations-and-known-gaps)) |

Reproduce the acceptance run (PyQt5 target):

```bash
python3 -m pip install --user PyQt5          # real Qt widgets + Qt's VNC plugin
npm ci && npm run build                      # bundles the noVNC client
python3 tests/remote_desktop_acceptance.py --target qt --python "$(command -v python3)"
```

Reproduce it with an independent VNC server:

```bash
sudo apt-get install -y xvfb openbox x11vnc xterm x11-utils x11-xserver-utils xdotool
python3 tests/remote_desktop_acceptance.py --target x11vnc
```

The acceptance runner exits `0` on success, `1` on a failed check, and `3` when
the environment cannot provide a real target. In the release runner, exit `3`
counts as a **failed** gate: an environment-blocked gate is never a pass.

---

## 10. Limitations and known gaps

* **RDP is not implemented.** No maintained gateway integration has been
  reviewed, so `rdp` reports `not_implemented`. Vortex does not claim both
  protocols work.
* **TLS transports are not exercised against a live TLS VNC server here**,
  because no such server exists in this environment; verification behavior is
  covered by unit tests and by the transport code path, not by acceptance
  evidence. Certificate errors are refused by construction.
* **Qt's VNC plugin (Qt 5.15) offers no authentication** and a fixed resolution;
  credential-failure and live-resize coverage therefore live in the x11vnc
  target and the scripted unit fixtures. Credentials are only ever sent to
  servers that ask for them, and the client never authenticates on the
  operator's behalf.
* **Clipboard sync, file transfer, audio redirection, and shared folders are not
  implemented** and are off by default.
* **Browsers are not run in the acceptance path**: the gate is deliberately
  headless so it runs on build hosts without Chromium. The browser gates
  (`npm run test:browser`, `scripts/test_live_ui.py`) remain separate and are
  environment-blocked where no browser binary is available.
* Remote desktops are only attempted for endpoints in the engagement scope. If
  your engagement covers the host but not a VNC display, Vortex will refuse
  rather than widen the scope.
