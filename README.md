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
./vortex host-tools --json
./vortex mobile apk --sidecar-url http://127.0.0.1:8765/

# Local workbench (127.0.0.1) or Arena preview (0.0.0.0)
./vortex serve --bind-host 127.0.0.1 --bind-port 8765
npm run preview
```

Step-by-step install and use: [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).

Data lives in `$XDG_DATA_HOME/vortex` (or `~/.local/share/vortex`), mode 0700.

## What is implemented and tested

Statuses below are one of: **Implemented + tested** (verified by the automated
suite and exercised on this host), **Implemented** (present and exercised, not
yet covered by a dedicated regression test), **Implemented + unavailable
dependency** (code path exists; the host lacks the binary/runtime, so it reports
UNAVAILABLE), or **Not implemented**.

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
| Bounded replanning (max 2 follow-ups, duplicate-plan detection) | Implemented + tested |
| Crash recovery: stale operations/tasks reconciled at startup | Implemented + tested |
| Kali/Linux tool registry with live probes | Implemented + tested |
| Agent Council (9 third-party + builtin `vortex-local`) | Implemented + tested; third-party missing stay UNAVAILABLE |
| Observe → act → host-state reward | Implemented + tested |
| nuclei / ffuf / nikto / amass / gobuster adapters | Implemented + tested; UNAVAILABLE without the binary, engagement, and (for ffuf/gobuster) a host wordlist |
| User-local install / `vortex serve` / `vortex turn` | Implemented + tested |
| Session EventSource with poll fallback | Implemented |
| Natural-language planning → orchestration → Guardian → executor → verifier | Implemented + tested |
| Prompt-injection defense (tool output is data, never instructions) | Implemented + tested |
| MCP server / client | Not implemented |
| Remote graphical (VNC/RDP/noVNC) sessions | Not implemented |
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
| Host PATH / Kali tool discovery (newly installed tools) | Implemented + tested |
| Operator setting: host-tool access for the agent | Implemented + tested; off by default; Guardian still authorizes |
| Android APK client (sync-then-download, same API) | Implemented + tested |
| MIT license (LICENSE, LICENSES.md, in-app, APK assets) | Implemented + tested |

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
- MCP server or client (no MCP layer exists in this build)
- Remote graphical sessions (VNC / RDP / noVNC / Guacamole). No `Xvfb`,
  `x11vnc`, `websockify`, or RDP client is present and no session code exists;
  VORTEX shows no desktop rather than a fake one.

Verified absent on this host at the time of the last audit: `nmap`, `nuclei`,
`ffuf`, `nikto`, `amass`, `gobuster`, `sqlmap`, `msfconsole`, `docker`,
`podman`, `ollama`, and all nine third-party agent CLIs. Every one of those
reports UNAVAILABLE rather than a fabricated result. Present and exercised:
`git`, `ss`, `ip`, `curl`, `ssh`, `ps`, `df`, `systemctl`, `journalctl`.

## Trust model

```text
Renderer / CLI        no process access; typed preload bridge or direct module call
      ↓
Agent / Planner       deterministic adapter routing; agent text is a proposal
      ↓
Guardian              independent risk, policy, and engagement scope recomputation
      ↓
Execution Authority   one Python owner: shell=False argv, new session, bounded
      ↓
Real OS Tool          only a probed, identity-pinned executable
      ↓
Observed Evidence     sanitized, redacted, output-capped, digested
      ↓
Verifier              objective evaluation from evidence, never from model text
      ↓
User
```

**Why the renderer cannot execute.** The Electron renderer is context-isolated
with `nodeIntegration: false` and `sandbox: true`. It reaches the sidecar only
through a typed preload bridge that rejects any route outside `/api/`. The
capability token is held by the main process, never exposed to page JavaScript.

**Why agent text cannot authorize.** Commands come from reviewed adapters, not
from model output. The Guardian recomputes risk from the typed command specs
(`adapter_id`, `network_class`, `privilege`), so a plan cannot raise its own
authority by relabelling itself. Notes, agent messages, and tool output are
stored as data and are never parsed back into instructions.

**How scope is enforced.** Guardian derives the engagement requirement from the
commands themselves — any assessment adapter, SSH connection, or outbound-read
class needs a live engagement, regardless of how the plan is labelled. That
mirrors the execution authority's own gate, which re-validates engagement
status, expiry, target membership, and the exclusion list at execution time.
If the exclusion module cannot be loaded, Guardian fails closed.

**How evidence and audit integrity work.** Every plan, approval, operation, and
session lifecycle event is appended to a SHA-256 hash chain. Each entry commits
to the previous hash, so editing a payload, changing an event type, or deleting
a row is detected by `./vortex db integrity`. Executables are pinned by
sha256/device/inode at plan time and re-probed before execution, so a swapped
binary invalidates the plan instead of running.

**Recovery is honest.** If the sidecar dies mid-operation, the next start marks
the abandoned operation `unknown_after_crash` and pauses its task. VORTEX
records that it does not know the host outcome rather than inferring success.

## Documentation

- [`LINUX_VORTEX_TERMINAL_BUILD_PLAN.md`](LINUX_VORTEX_TERMINAL_BUILD_PLAN.md) — original binding plan
- [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) — install, test, and operate as a real app
- [`docs/STATUS.md`](docs/STATUS.md) — tested vs remaining gates
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — authority and data flow
- [`docs/IMPLEMENTATION_REPORT.md`](docs/IMPLEMENTATION_REPORT.md) — current slice
- [`docs/AUDIT_REPORT_2026-08-28.md`](docs/AUDIT_REPORT_2026-08-28.md) — full audit: defects found/fixed, test results, limitations
- [`LICENSE`](LICENSE) — MIT License
- [`LICENSES.md`](LICENSES.md) — SPDX MIT and third-party notes
- [`NOTICE`](NOTICE) — third-party agent attribution
- [`SECURITY.md`](SECURITY.md)
- [`mobile/android/README.md`](mobile/android/README.md) — Android APK client

## Development

```bash
npm run lint
npm test
```
