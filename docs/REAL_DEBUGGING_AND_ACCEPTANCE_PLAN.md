# Real debugging and acceptance plan

## Purpose and standard

This plan is the required path for debugging and accepting the **real** Vortex
Terminal application. It is deliberately stricter than a green unit-test run:
a mock, static check, or fake runtime can establish a regression contract, but
cannot be recorded as proof that a real browser, Electron window, local model,
or graphical remote-desktop target works.

**10/10 means every domain below has passed with its stated real dependency.**
The executable release equivalent is `python3 scripts/release_gates.py`; it has
eleven commands because its browser, production UI, dev-proxy, package,
Electron, model, and remote-desktop checks split several of the ten domains
into independently observable gates. It must finish `11/11 (100%)` on a
properly provisioned Linux runner.

The faster `python3 scripts/final_gates.py` is an important 10-gate regression
audit, but some model routing is intentionally deterministic/test-injected. It
is not a substitute for a real model-inference acceptance run.

## Application map reviewed before debugging

| Layer | Real authority / entrypoint | Main evidence |
|---|---|---|
| Desktop shell | `desktop/main.js` → isolated `desktop/preload.js` → `desktop/security.js` | native Electron acceptance and IPC allow-list rejection |
| React workbench | `src/main.tsx`, `src/App.tsx`, components, `src/services/vortexApi.ts` | Vite/Playwright browser tests plus production sidecar HTTP |
| Legacy fallback | `frontend/*.js`, served only when `dist/index.html` is absent or explicitly selected | syntax, sanitization, and backend serving tests |
| Sidecar and execution authority | `backend/vortex_backend.py`, `workspace.py`, `orchestrate.py`, Guardian/scope modules | real loopback HTTP, CLI, policy, persistence, and audit-chain tests |
| Local advisory models | `backend/models/{gguf,llamafile,manager,router}.py` | real model inference plus lifecycle/reaping tests |
| Remote desktop | `backend/remote_desktop.py`, websocket routes, `RemoteDesktopView.tsx` | real RFB/VNC graphical target acceptance |
| CLI and packaging | `cli/vortex.py`, `vortex`, `packaging/deb/*` | extracted payload, real `dpkg --root`, and package live-sidecar tests |
| Startup and resource policy | `scripts/start.js`, `scripts/build.js`, `scripts/ensure-dist.js` | constrained-build checks, actual Vite bundle, desktop-launch contract |

The system has one production execution authority: the Python sidecar/CLI path.
Renderer and model output can request or advise, but cannot bypass typed argv,
Guardian, scope, approval, executable identity, or evidence recording.

## Debugging workflow

1. **Reproduce without changing behavior.** Capture command, complete stderr,
   exit/signal, host RAM/swap/cgroup facts, and whether a current `dist/`
   exists. Do not describe `Killed` as a compile error before checking the
   kernel/resource cause.
2. **Classify the failing layer.** Startup/build, Electron/preload, React,
   sidecar HTTP/auth, planner/Guardian/executor, model, remote desktop,
   package, or host prerequisite are distinct failures with different owners.
3. **Reduce to one real entrypoint.** Prefer a real production bundle and
   isolated sidecar/data directory. Keep model, browser, VNC, and Electron
   prerequisites explicit rather than substituting a success-looking stub.
4. **Fix the smallest owning layer.** Preserve the authority boundary and
   explicit failure semantics; never solve a resource failure by silently
   raising a heap cap or solve a missing runtime by claiming it passed.
5. **Add a regression.** Exercise the exact former failure, normal path, and
   cleanup/error path. Resource and child-process fixes must prove descriptor
   closure and reaping, not merely suppress a warning.
6. **Retest outward.** Run the focused test, whole relevant suite, build,
   package, live endpoint/CLI path, and the full release matrix when its real
   dependencies are installed.
7. **Record only observable evidence.** State `PASS`, `FAIL`, or
   `BLOCKED BY PREREQUISITE`; never convert blocked into pass.

## Ten real acceptance domains

| # | Domain and required proof | Primary command(s) | Pass condition |
|---:|---|---|---|
| 1 | **Target-resource production build**: 2-core / 4-GB / no-swap-safe startup behavior | `node tests/test_start.js`, `npm run build`, `npm start -- --rebuild` | 512-MiB normal cap builds; controlled OOM retry completes at 384 MiB; known-low-memory path preserves a prior bundle or refuses safely |
| 2 | **Core authority, policy, persistence, and CLI** | `npm test`, `VORTEX_REAL_ACCEPTANCE=1 ./tests/linux_acceptance.sh` | typed execution, Guardian, scope, audit, DB integrity, and actual host probes pass without fabricated outcomes |
| 3 | **Sidecar HTTP/auth/security** | `python3 scripts/final_gates.py`; isolated sidecar requests | authenticated routes, CSP, traversal/CORS/allow-list refusals, and real loopback API responses pass |
| 4 | **React production and Vite proxy** | `npm run build`; `python3 scripts/test_live_ui.py`; `python3 scripts/test_live_ui.py --dev` | real browser loads production and dev UI, executes authenticated backend interactions, and observes error states |
| 5 | **Electron desktop/IPC/PTY** | `node tests/native_acceptance.cjs` under Xvfb/window manager | real Electron starts the sidecar, preload blocks an unallowed route, controls work, and an actual PTY emits/cleans up output |
| 6 | **Local model behavior** | `python3 tests/real_provider_acceptance.py` with `VORTEX_REAL_MODEL` and real CPU engine | model performs actual local inference; fallback remains honest when unavailable; server processes stop/reap correctly |
| 7 | **Authorized remote desktop** | `python3 tests/remote_desktop_acceptance.py --report artifacts/remote-desktop-acceptance.json` | real graphical target, real VNC/RFB bytes through authenticated bridge, ticket/scope restrictions, cleanup evidence |
| 8 | **Package/repository installability** | `npm run package:deb`; package tests; extracted payload sidecar/CLI | fresh signed/hashed package has correct payload, installs/upgrades/removes in a real `dpkg --root` transaction, and serves its bundled production UI |
| 9 | **Lifecycle and resource hygiene** | warning-instrumented full unittest run; child/descriptor instrumentation | no `ResourceWarning`, no tracked open descriptors, no orphaned sidecars/model children after normal or failed startup |
| 10 | **Integrated release regression** | `python3 scripts/release_gates.py` | every listed real prerequisite gate passes; output is `FINAL RELEASE CHECKS: 11/11 (100%)` |

## Current evidence after the low-memory remediation

The following is **real, runnable evidence** obtained in the current Linux
sandbox:

- `npm test`: PASS — 644 Python tests and all eleven JavaScript suites.
- Full warning/descriptor-instrumented Python discovery: PASS — 644 tests,
  zero `ResourceWarning`s and zero tracked open file/Popen handles.
- `python3 scripts/final_gates.py`: PASS — `FINAL: 10/10 (100%)`.
- Production Vite bundle: repeatedly completed using the default 512-MiB cap
  and the 384-MiB retry cap. The exact `transforming … Killed` symptom was
  injected as a first attempt and recovered through the real build command.
- Desktop launch orchestration: production build plus desktop entrypoint
  contract completed; this proves launcher behavior but is not labelled a real
  Electron GUI pass without the Electron binary.
- Production sidecar/preview: React shell and representative health,
  capability, dashboard, models, and settings routes returned real `200`
  responses. A fresh Vite development server also proxied those real sidecar
  APIs successfully.
- Debian package: fresh package built, SHA-256 verified, extracted production
  payload served real sidecar routes, and extracted CLI payload passed
  `doctor`, `health`, and DB-integrity checks. The regression suite additionally
  exercised real unprivileged `dpkg --root` install/upgrade/remove transactions.
- Static authority audit: production backend/CLI subprocess sites use typed
  argv; no `shell=True`, `os.system`, Node `exec`, React
  `dangerouslySetInnerHTML`, or dynamic evaluation site is accepted in
  production paths. Legacy HTML sinks are covered by the existing escaping
  regression suite and use the `esc()` encoder for data-bearing fields.

## Explicit open prerequisites — not passes

This sandbox currently has no Chromium/Chrome/Firefox, Electron binary, Xvfb,
window manager, VNC target stack, Playwright browser cache, or real GGUF model
engine/model. Browser/Electron binary downloads reset before TLS setup, and no
local APT candidate/cache is available. Native acceptance detects that state
without importing Electron's self-downloading package loader, so it fails
immediately with remediation rather than pretending to test a GUI. Therefore
domains **4–7 and the full 10th release domain cannot honestly be marked passed
here**.

A properly provisioned runner must use the concrete setup in
`.github/workflows/react-ui.yml`:

```bash
npm ci
npx playwright install --with-deps chromium
sudo apt-get update
sudo apt-get install -y xvfb openbox x11vnc xterm x11-utils x11-xserver-utils xdotool
# Install the pinned CPU inference engine and a real GGUF test model as in CI.
xvfb-run -a sh -c 'openbox >/tmp/vortex-openbox.log 2>&1 & python3 scripts/release_gates.py'
```

That runner is the final required proof. Until it produces `11/11`, the honest
state is: all runnable domains are green; full real GUI/model/VNC acceptance is
blocked by unavailable external runtimes, not asserted as complete.
