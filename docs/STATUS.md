# Current implementation status

VORTEX 0.2.0 is a real Linux application. Production paths use installed host
tools and observed output only. Test doubles exist only inside tests.

**81 Python tests + JS terminal emulator: passing.**

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
| CLI `tasks pause` / `tasks reject` / `deps` | Done + tested |
| Observe → typed action → host-state reward (WAA-inspired, Linux argv) | Done + tested |
| Built-in `vortex-local` advisor (always present, never executes) | Done + tested |
| Ollama loopback probe | Done; unavailable here |
| Docker isolation **execution** | Probe only; runtime missing here |
| Plugin code loading | Deliberately not implemented |
| FastAPI / PostgreSQL / pgvector | Intentionally not added |
| Nuclei/ffuf/nikto/amass/msf execution | Catalog probe only |
| Signed 1.0 `.deb` | Not a 1.0 gate pass |

## Remaining host / release gates (cannot be faked)

These stay UNAVAILABLE until the host has the software or a release VM:

1. Reviewed non-interactive consult APIs for third-party agents that are actually installed
2. Disposable-VM apt/systemd mutation acceptance
3. Full xterm + durable PTY attach across sidecar restarts
4. Signed `.deb` install/upgrade/uninstall evidence
5. Scanner execution on a host that has nuclei/ffuf/nmap and reviewed wordlists
