# Current implementation status

VORTEX 0.2.0 is a real Linux application. Production paths use installed host
tools and observed output only. Test doubles exist only inside tests.

## Directive coverage

| Area | State |
|---|---|
| Real execution / PTY / NL Linux (reviewed adapters) | Done + tested |
| Guardian, risk policy, kill switch | Done + tested (word-level destructive match) |
| Engagements / scope / excluded targets | Done + tested |
| Tasks (VTX-*), resume, pause, reject, replan evaluation | Done + tested |
| Conversations, branch on edit, export download, search | Done + tested |
| Tool registry live probes | Done + tested |
| Agent adapters + discovery | Done + tested; consult = REQUIRES CONFIGURATION |
| Reports MD/HTML/JSON/PDF + system inventory | Done + tested |
| Assessment reports scoped to one engagement | Done + tested |
| Memory / procedures / experiences | Done + tested |
| Health, first-run, offline, lab flag, developer mode | Done |
| Workspace SEND path (`/api/workspace/turn`) | Done |
| SSE operation stream + poll fallback | Done |
| Secret slots (values never returned) | Done |
| Internal tool router (not MCP-dependent) | Done |
| Auto low-risk replan follow-up (max 2, Guardian gated, enriched scope) | Done |
| Ollama loopback probe | Done; unavailable here |
| Docker isolation **execution** | Probe only; runtime missing here |
| Plugin code loading | Deliberately not implemented (manifests only) |
| FastAPI / PostgreSQL / pgvector | Not started; SQLite monolith is intentional |
| Nuclei/ffuf/nikto/amass/msf execution | Catalog probe only |
| Full VORTEX self-pentest / signed release | Not a 1.0 gate pass |

## Remaining host / release gates (cannot be faked)

1. Reviewed non-interactive consult APIs for agents that are actually installed
2. Disposable-VM apt/systemd mutation acceptance
3. Full xterm + durable PTY attach across sidecar restarts
4. Optional FastAPI/PostgreSQL only if packaging requires it
5. Signed `.deb` and install/upgrade/uninstall VM evidence
6. Deeper Nmap/HTTP/parser fuzzing on a host that has those tools
