# Current implementation status

VORTEX 0.2.0 is a real Linux application. Production paths use installed host
tools and observed output only. Test doubles exist only inside tests.

**153 Python tests + JS terminal, window-control, and frontend suites: passing.**

## Audit round (2026-08-28)

A full repository audit was run against the actual source and runtime rather
than against the README. Four genuine defects were found and fixed, each with a
regression test. No feature was removed and no subsystem was rewritten.

Full write-up: [`AUDIT_REPORT_2026-08-28.md`](AUDIT_REPORT_2026-08-28.md).

| # | Defect | Severity | Root cause | Fix |
|---|---|---|---|---|
| 1 | Exclusion-list check crashed in package import context | High | `from security.scope import excluded` only resolves when `backend/` is on `sys.path`; a `backend.security.guardian` consumer raised `ModuleNotFoundError` before the exclusion loop | `_load_scope_excluded()` resolves under all import contexts and Guardian fails closed if it cannot load |
| 2 | Guardian's engagement gate could be bypassed | High | The gate only fired for `kind in {authorized_engagement, ssh_diagnostics}`; a network-effecting command under any other plan kind reached `decision=approve` with no engagement | Guardian now recomputes the requirement from the typed command specs (`guardian.requires_engagement`), mirroring `plan_requires_engagement` |
| 3 | Operations stuck `running` forever after a crash | Medium | Nothing reconciled operation rows at startup, so their tasks stayed `EXECUTING` permanently | `Store.reconcile_stale_operations()` + `Workspace.reconcile_orphaned_tasks()` mark them `unknown_after_crash` / `PAUSED` |
| 4 | Replan budget was not enforced across iterations | Medium | The `depth` counter was never passed through the executor thread, so every follow-up re-entered at depth 0 | Budget persisted on the task result with duplicate-plan digest detection |

Verified working during the audit and left unchanged: `shell=False` argv
execution, PTY lifecycle, approval-token single-use and replay rejection,
executable identity pinning, audit hash-chain tamper detection (payload edit,
row delete, event-type change all detected), path-traversal rejection, STOP ALL,
apt/systemd preflight gating, and honest UNAVAILABLE for every missing tool.

## Directive coverage

| Area | State |
|---|---|
| Real execution / PTY / NL Linux (reviewed adapters) | Done + tested |
| os-release / lscpu adapters | Done + tested |
| Guardian, risk policy, kill switch | Done + tested |
| Engagements / scope / excluded targets / close | Done + tested |
| Tasks (VTX-*), resume, pause, reject, events, replan | Done + tested |
| Conversations, branch, export, message search | Done + tested |
| Tool registry live probes | Done + tested |
| Agent adapters + discovery (9 third-party + builtin `vortex-local`) | Done + tested; third-party consult = REQUIRES CONFIGURATION |
| Reports MD/HTML/JSON/PDF + assessment (engagement-scoped) | Done + tested |
| Memory / procedures / experiences | Done + tested |
| Workspace SEND (`/api/workspace/turn`) | Done + tested |
| SSE operations + sessions | Done |
| Secret slots (values never returned) | Done + tested |
| Static path-traversal rejection | Done + tested |
| Capabilities document (`GET /api/capabilities`) | Done + tested |
| Missing-dependency window + INSTALL buttons | Done + tested (apt plans / operator proposals; no silent install) |
| Linux desktop + first-run/dependency/terminal window controls | Done + JS tested; display-server smoke remains a release-host check |
| Aggregate inventory latency (no third-party version fan-out) | Done + tested |
| CLI `tasks pause` / `tasks reject` / `deps` | Done + tested |
| Observe → typed action → host-state reward (WAA-inspired, Linux argv) | Done + tested |
| Built-in `vortex-local` advisor (always present, never executes) | Done + tested |
| nuclei / ffuf / nikto / amass / gobuster execution adapters | Done + tested; host binary + engagement required |
| User-local install, `vortex serve`, `vortex turn`, USER_GUIDE | Done + tested |
| Session EventSource | Done (poll fallback remains) |
| Bounded replanning + duplicate-plan detection | Done + tested |
| Crash reconciliation of stale operations/tasks | Done + tested |
| MCP | Not implemented |
| Remote graphical sessions | Not implemented |
| Ollama loopback probe | Done; unavailable here |
| Docker isolation **execution** | Probe only; runtime missing here |
| Plugin code loading | Deliberately not implemented |
| FastAPI / PostgreSQL / pgvector | Intentionally not added |
| sqlmap / msf execution | Honest UNAVAILABLE; no command fabricated |
| Signed 1.0 `.deb` | Not a 1.0 gate pass |

**Plan to make “only host tools remain”:** `docs/READY_WHEN_TOOLS_EXIST.md`

## Remaining host / release gates (cannot be faked)

These stay UNAVAILABLE until the host has the software or a release VM:

1. Reviewed non-interactive consult APIs for third-party agents that are actually installed
2. Disposable-VM apt/systemd mutation acceptance
3. Full xterm + durable PTY attach across sidecar restarts
4. Signed `.deb` install/upgrade/uninstall evidence
5. Scanner execution on a host that actually has nuclei/ffuf/nmap and reviewed wordlists (adapters exist; this host does not)
