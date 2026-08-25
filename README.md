# Linux Vortex Terminal

**Linux-native, AI-powered authorized cybersecurity and Linux operations workbench.**

Vortex turns a natural-language objective into an inspectable plan, checks the
real tools installed on the host, asks for explicit approval, runs only typed
argv through one local Python authority, and records truthful evidence. It works
without a model or network. The desktop renderer is an optional local Electron
shell; `./vortex` is the dependency-free CLI path. The operator’s PTY shell and
explicit `vortex run -- ...` path retain native Linux access; adapters constrain
AI-proposed operations, not the capabilities of the user’s own shell.

> **Authorized use only.** Vortex is for systems, networks, and artifacts you
> own or are explicitly authorized to assess. High-risk attack classes are
> blocked. Missing tools and offline backends produce no fabricated findings.

## Quick start

Requires Linux and Python 3.11+. No Python package download is needed for the
current vertical slice.

```bash
./vortex --help
./vortex doctor --json
./vortex tools
./vortex adapters --json
./vortex artifact inspect ./scan.xml --type nmap-xml
./vortex plan "system health"
./vortex plan "install package ripgrep" # real preflight + root-required plan; no auto-sudo
./vortex "git status"

# Optional desktop preview (same local sidecar; binds 0.0.0.0 for a dev preview)
npm run preview

# Optional Electron desktop after npm install on Linux
npm install
npm start
```

The default data directory is `$XDG_DATA_HOME/vortex` (or
`~/.local/share/vortex`) with owner-only permissions. For an isolated test:

```bash
VORTEX_DATA_DIR="$(mktemp -d)" ./vortex plan "show listening ports"
```

## Capability matrix

| Capability | Status |
|---|---|
| Natural-language deterministic planner | Implemented + tested |
| Explicit typed plans and approval tokens | Implemented + tested |
| Real `shell=False` argv execution and process groups | Implemented + tested |
| Redaction, output bounds, exit/signal evidence | Implemented + tested |
| XDG local SQLite + tamper-evident audit chain | Implemented + tested |
| Linux context and factual tool probes | Implemented + tested |
| Engagement creation, canonical targets, scope gate | Implemented + tested |
| Desktop planning/activity/reports/settings UI | Implemented + smoke-tested |
| Python-owned local PTY sessions and cancellation | Implemented + tested |
| Matrix binary rain and project-owned artwork | Implemented + accessible fallback |
| Full PTY tabs/panes and shell integration | Planned |
| Scoped nmap/curl planning and evidence parsers | Implemented + tested; tool availability varies |
| Real apt preflight, impact parsing, and guarded package plans | Implemented + tested; Linux VM mutation gate remains |
| Systemd state parsing, user-bus detection, and guarded plans | Implemented + tested; host context varies |
| Docker/Podman read-only container inspection | Implemented + tested; runtime availability varies |
| SSH effective-config diagnostics | Implemented + tested; no connection or key read |
| Nuclei/content-discovery active adapters | Planned; reviewed templates/wordlists required |
| Local model / specialist worker bus | Planned; provider disabled by default |
| Signed knowledge packages and `.deb` release | Planned |
| Cloud API, remote control, attack automation, telemetry | Explicitly unsupported |

## Trust model

The renderer cannot execute a process. In desktop mode, Electron starts one
loopback-only Python sidecar with a per-launch capability token and exposes only a
typed preload bridge. The sidecar resolves and fingerprints executables, validates
argv/cwd/scope, uses a minimal environment and new process group, streams bounded
redacted output, and persists a hash-chained audit event. A plan expires after 15
minutes and a second execution attempt is rejected. The optional local model is
not installed, not contacted, and not trusted by default.

## Documentation

- [`LINUX_VORTEX_TERMINAL_BUILD_PLAN.md`](LINUX_VORTEX_TERMINAL_BUILD_PLAN.md) —
  supplied comprehensive plan and all binding review amendments.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — authority and data flow.
- [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) — threat boundary and mitigations.
- [`docs/EXIT_CODES.md`](docs/EXIT_CODES.md) — machine contract.
- [`docs/IMPLEMENTATION_REPORT.md`](docs/IMPLEMENTATION_REPORT.md) — this slice,
  commands run, and limitations.
- [`SECURITY.md`](SECURITY.md) — disclosure and safe-use policy.

## Development

```bash
npm run lint
npm test
```

The project intentionally has no browser/backend cloud dependency for core use.
The default low-resource mode does not load a local LLM, so the deterministic CLI,
PTY, adapters, and evidence parsers are usable on modest hardware such as 8 GB
RAM and a 2 GHz CPU. Local models remain optional and disabled by default.
Build output, local databases, credentials, reports, and Node dependencies are
ignored by Git. Contributions must preserve the single execution authority and
truthful unavailable/failed states.
