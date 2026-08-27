# VORTEX

**Verified Orchestration, Reasoning, Testing, Execution & eXperience**

Linux-native, AI-assisted authorized cybersecurity and Linux operations workbench.

VORTEX turns a natural-language objective into an inspectable plan, checks tools
actually installed on the host, evaluates the plan with an independent Guardian,
runs only typed argv through one local Python authority, and records observed
evidence. Missing tools, agents, Docker, and models are reported as unavailable.
Nothing is fabricated to make the UI look complete.

> **Authorized use only.** VORTEX is for systems, networks, and artifacts you
> own or are explicitly authorized to assess.

## Quick start

Requires Linux and Python 3.11+. Core use has no pip dependency.

```bash
# Verify
python3 -m unittest discover -s tests -q

# User-local launcher (no sudo, no apt)
./vortex install --user
export PATH="$HOME/.local/bin:$PATH"

./vortex --help
./vortex doctor --json
./vortex health --json
./vortex tools
./vortex agents --json
./vortex deps --json
./vortex sandbox --json
./vortex plan "system health"
./vortex plan "whoami"
./vortex --profile standard --yes turn "whoami"
./vortex db integrity

# Local workbench (127.0.0.1) or Arena preview (0.0.0.0)
./vortex serve --bind-host 127.0.0.1 --bind-port 8765
npm run preview
```

Step-by-step install and use: [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).

Data lives in `$XDG_DATA_HOME/vortex` (or `~/.local/share/vortex`), mode 0700.

## What is implemented and tested

| Capability | Status |
|---|---|
| Real `shell=False` argv execution, PTY, cancellation | Implemented + tested |
| Natural-language plans for reviewed Linux adapters | Implemented + tested |
| Independent Guardian (cannot be self-approved by a model/agent) | Implemented + tested |
| Risk policy: safe / standard (auto low-risk) / expert | Implemented + tested |
| Engagements and scope gate for active network work | Implemented + tested |
| VTX task engine, persistence, resume/restart/delete | Implemented + tested |
| Conversations, edit-branching, export, search | Implemented + tested |
| Objective evaluation / replan proposal after observed results | Implemented + tested |
| Kali/Linux tool registry with live probes | Implemented + tested |
| Agent Council (9 third-party + builtin `vortex-local`) | Implemented + tested; third-party missing stay UNAVAILABLE |
| Observe → act → host-state reward | Implemented + tested |
| nuclei / ffuf / nikto / amass / gobuster adapters | Implemented + tested; UNAVAILABLE without the binary, engagement, and (for ffuf/gobuster) a host wordlist |
| User-local install / `vortex serve` / `vortex turn` | Implemented + tested |
| Session EventSource with poll fallback | Implemented |
| Missing-dependency window / `vortex deps` | Implemented + tested; no silent install |
| Reports Markdown / HTML / JSON / PDF from observed operations | Implemented + tested |
| System inventory report from doctor + tool probes | Implemented |
| Memory, experiences, validated procedures | Implemented + tested |
| First-run live requirement checks | Implemented |
| Offline mode, privacy mode, lab-mode flag | Implemented |
| STOP ALL kill switch | Implemented + tested |
| Local Ollama loopback probe | Implemented; unavailable unless a server is running |
| Docker/Podman isolation probe | Implemented; UNAVAILABLE when no runtime is installed |
| Plugin JSON manifests (no plugin code execution) | Implemented |
| Security tests: injection, prompt-injection text, Guardian | Implemented + tested |
| Audit hash chain, redaction, output caps | Implemented + tested |

## Explicitly not claimed on this host

These are either unimplemented, or implemented only as honest unavailable states:

- Calling CAI / Strix / Nebula / PentestGPT / HexStrike / PentAGI / HackerAI / HALO / DarkMoon consult APIs (no reviewed non-interactive consult; binaries not installed here)
- sqlmap / Metasploit **execution** adapters (catalog probes only)
- Scanner tools when the binary or wordlist is not on the host (honest UNAVAILABLE)
- FastAPI + PostgreSQL + pgvector (local SQLite modular monolith by design)
- Durable WebSocket PTY attach (operation and session EventSource exist; poll remains a fallback)
- Starting unreviewed Docker images as a sandbox
- Provisioning Juice Shop / DVWA / WebGoat
- Cloud model providers
- Silent package or agent installation
- Complete xterm compatibility and reconnectable daemon attach
- Privileged apt/systemd mutation acceptance on a disposable VM
- Signed `.deb` / 1.0 production release

## Trust model

The renderer cannot spawn a process. The Python sidecar is the only execution
authority. Guardian recomputes risk from command specs and policy; agent text
cannot authorize execution. Tool output is stored as data, not instructions.

## Documentation

- [`LINUX_VORTEX_TERMINAL_BUILD_PLAN.md`](LINUX_VORTEX_TERMINAL_BUILD_PLAN.md) — original binding plan
- [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) — install, test, and operate as a real app
- [`docs/STATUS.md`](docs/STATUS.md) — tested vs remaining gates
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — authority and data flow
- [`docs/IMPLEMENTATION_REPORT.md`](docs/IMPLEMENTATION_REPORT.md) — current slice
- [`NOTICE`](NOTICE) — third-party agent attribution
- [`SECURITY.md`](SECURITY.md)

## Development

```bash
npm run lint
npm test
```
