# Linux Vortex Terminal — Comprehensive Build Plan

**Target repository:** `mrtc-solutions/linux-vortex-terminal`  
**Reviewed:** 2026-08-25  
**Status:** binding product direction for the Linux desktop agent  
**Command:** `vortex`

> This file records the supplied build plan and its review amendments. The final
> desktop-agent direction supersedes earlier “CLI-only/no GUI” wording: the
> product is a Linux-native Electron desktop workbench with a Python sidecar,
> while the sidecar remains the sole authority that can execute a real command.
> It is not a browser SaaS product, a remote-control service, or a terminal that fabricates
> execution. The UI is optional; the local sidecar and `vortex` CLI are useful on
> their own.

## 1. Product direction

Linux Vortex Terminal is an **AI-powered, authorized cybersecurity and ethical
assessment workbench for Linux**, with Linux administration and defensive
analysis capabilities. It runs inside the operator’s existing terminal or as a
hardened local desktop window. It understands a natural-language goal, asks for
missing target/authorization/scope information, probes the actual host, builds a
transparent typed plan, obtains approval, executes only the approved argv, and
presents observed evidence and truthful exit state.

The product preserves the useful Vortex experience: real terminal workspace,
multiple sessions, AI command planning, post-execution command analysis,
activity/history, reports, local artifacts, engagement/scope review, settings,
permissions, audit trail, bounded self-learning, and the dark Vortex identity.
It does not pretend to be a replacement shell, terminal emulator, Linux desktop,
or cloud SOC.

North-star requests:

```bash
vortex "why is this Linux server exposing port 8080? inspect locally first"
vortex "free space by finding large cache directories, show me the plan, then clean only caches I approve"
vortex "enumerate the authorized web application at https://lab.example.test, save evidence, and explain each step"
```

### What is in scope for v1

- Linux first, with Kali and Debian-family compatibility driven by factual probes;
  no distribution/version support claim is made without dedicated testing.
- Linux administration, diagnostics, files, processes, services, packages, Git,
  containers, SSH diagnostics, authorized reconnaissance, defensive triage, and
  supplied-artifact analysis.
- Real binaries already installed on the executing Linux host. No bundled scanner
  claims and no fabricated findings.
- Deterministic offline skills and reviewed offline knowledge.
- Optional local-only model providers through a Unix socket or loopback endpoint.
- A local Python sidecar owning PTY/process groups, adapters, policy, scope,
  evidence, SQLite history, reports, and audit events.
- An Electron/React renderer that is a convenience interface, never an execution
  authority; a dependency-free CLI remains available.

### Explicitly out of scope or blocked

Cloud models, telemetry by default, exposed LAN APIs, remote command-and-control,
SSH fan-out, autonomous background agents, silent privilege escalation, runtime
internet plugins, credential/password attacks, brute force/spraying, exploitation,
persistence, evasion, malware, phishing, denial of service, destructive payloads,
data exfiltration, wireless interference, raw disk writes, firewall/routing/DNS
mutation, unrestricted scanning, and package/repository installers are blocked.
A reference lab, practice artifact, or fixture is always labelled and never
appears as live evidence.

## 2. Non-negotiable truth and security invariants

Every request and operation records one independent lifecycle state:

`draft → clarified | planned → approved | rejected | expired → started → running → succeeded | failed | cancelled | interrupted | timed_out | unavailable | unknown_after_crash`

Generated, approved, and started are never synonyms for succeeded. Reports show
the observed redacted argv, executable/version facts, cwd, scope, timestamps,
duration, exit code or signal, output digest, parser state, and worker ledger.

1. **One execution authority.** The Python sidecar is the only production code
   allowed to spawn a command. The renderer never uses Node child processes and
   never turns model text into shell text.
2. **Typed argv.** Adapters produce `CommandSpec` values containing executable,
   argument array, cwd, minimal environment additions, stdin policy, timeout,
   resource profile, risk, network class, scope, and evidence requirements.
   Execution uses `shell=False`/execve semantics.
3. **Default deny.** The model is advisory. Adapter schemas, target and path
   validation, policy, executable identity checks, freshness checks, and explicit
   approval all happen before execution. Direct commands are visibly attributed
   `operator_direct` and remain logged; they are not AI-validated.
4. **Authorization before active work.** Active cybersecurity operations require
   an Engagement with authorization reference, canonical targets, operation
   classes, limits, expiry, and immutable event linkage. Every target is checked
   again immediately before execution; DNS/redirect/scope changes invalidate a
   plan.
5. **Capability identity.** At plan time and execution time, resolve an executable
   through a controlled PATH and compare canonical path, device, inode, owner,
   mode, size, SHA-256, and safe version probe. Reject writable, setuid/setgid,
   unexpected-capability, or unsafe interpreter chains. These checks do not
   protect a compromised root account or kernel.
6. **No automatic sudo.** Refuse UID 0 unless the invocation explicitly carries
   `--allow-root`; never read, pass, log, or store passwords. Show the minimum
   privileged command and ask the user to rerun with `sudo vortex ...` when needed.
7. **Honest absence.** A missing backend, worker, tool, authorization, or evidence
   produces `TOOL MISSING`, `BACKEND OFFLINE`, `UNAVAILABLE`, or `NOT RUN`; it
   produces no result table, finding, version, port, device, or success banner.
8. **Terminal safety.** Remove ANSI/OSC/control escapes before display and default
   storage; do not process links, shell snippets, or instructions found in output,
   docs, repositories, package metadata, or model responses. Use text labels in
   addition to colour.
9. **Privacy.** Data is local and permission restricted. Secret redaction is
   structural plus best-effort regex. Raw evidence is opt-in; prompts and raw
   output are not sent to providers without explicit consent.

## 3. User experience and contracts

The desktop has the Vortex dark/cyber visual identity: terminal workspace,
command input, plan card, confirmation, worker participation, real-time activity,
post-execution **AI Command Analysis** window, reports, engagement review, tool
health, and settings. The terminal stays selectable and real; background artwork
never overlays output.

Primary CLI contract:

```text
vortex "<natural-language request>"
vortex ask "<question>"                    # explanation/diagnosis; never executes
vortex plan "<request>"                    # save and print plan only
vortex run <plan-id>                        # approved saved plan
vortex run -- <command> [args...]           # explicit operator-direct command
vortex explain <history-id|command>
vortex doctor
vortex tools [list|probe|show <tool>]
vortex engagement [create|list|show|close]
vortex history [list|show|search|replay]
vortex undo <history-id>
vortex session [new|list|attach|kill]
vortex config [get|set|edit|show]
vortex model [status|list|use|test]
vortex knowledge [search|sources|verify]
vortex completion <bash|zsh|fish>
vortex report <history-id> --format md|json
vortex theme [show|preview|export|install|uninstall]
```

The current vertical slice implements natural-language planning, `ask`, `plan`,
`doctor`, `tools`, `engagement create/list`, saved-plan execution, direct argv
execution, local history, audit verification, desktop plan/execute/activity/
report/tool/engagement/settings views, and a local post-execution analysis. Other
commands are intentionally reported as planned rather than marketed as present.

Output protocol:

- stdout is data; stderr is diagnostics/prompts; machine output is versioned JSON
  with `schema_version` and contains no progress, ANSI, model prose, or prompts.
- No colour, spinner, redraw, or prompt in non-TTY mode. Honour `NO_COLOR`,
  `CLICOLOR=0`, `TERM=dumb`, terminal width, UTF-8, and reduced-motion settings.
- `--dry-run`, `--format text|json`, `--no-color`, `--cwd`, `--profile`,
  `--offline`, and `--non-interactive` are policy inputs, not execution bypasses.
- Exit codes are stable: `0` success; `1` general failure; `2` invalid usage;
  `3` unavailable; `4` policy denied; `5` confirmation/declined; `6` command
  non-zero; `7` interrupted; `8` timeout; `9` persistence integrity failure;
  `10` incompatible state. Non-interactive execution requires plan ID plus exact
  digest and approval token; `--yes` is never universal approval.

## 4. Linux compatibility contract

| Tier | Context | v1 promise |
|---|---|---|
| 1 | Linux on a supported host with required probes | Core CLI and local execution promise |
| 2 | Kali/Debian-family Linux | Apt/systemd behavior after host probes |
| 3 | Other Linux distributions | Best-effort facts; no mutation promise |
| Deferred | Non-Linux, WSL, immutable OS, and constrained containers | Detect and report limits |

`/etc/os-release`, actual executable probes, and usable-state probes are the
source of truth. `doctor` reports distro/version/family, physical/VM/container/
WSL context, PID 1 and systemd, shell, TTY, SSH, tmux/screen, confinement,
root status, cgroup version, package manager, and model connectivity. In a
systemd-less container, systemctl is unavailable; in a non-interactive SSH job,
approval cannot be guessed.

Root execution is guarded. Managed processes start in their own session/process
group, use a minimal allowlisted environment, close inherited file descriptors,
stream bounded output, forward interrupts, escalate TERM to KILL, reap
children, and report exit code, signal, and termination reason separately. An
optional future systemd scope/cgroup v2 resource profile is not claimed here.

## 5. Desktop architecture

```text
Electron main process (Linux lifecycle, hardened IPC, one launch capability token)
        │ context-isolated, typed preload API only
React/HTML renderer (terminal, AI plan, activity, reports, settings, scope)
        │ IPC bridge in Electron; same-origin local API in development preview
Python 3.11 local sidecar (single authority, loopback-only)
        ├─ process-group execution and future PTY sessions
        ├─ Linux facts and tool probes
        ├─ typed cybersecurity/admin adapters and artifact parsers
        ├─ policy, engagement, approval, plan freshness
        ├─ SQLite history, audit chain, redaction and reports
        ├─ deterministic planner and bounded worker ledger
        └─ optional disabled-by-default local model client
```

The current sidecar uses the Python standard library so a clean Linux host can
boot without downloading runtime dependencies; the packaged architecture can
swap the HTTP handler for FastAPI/Pydantic without changing the authority
boundary. Electron uses `contextIsolation`, `nodeIntegration=false`, sandboxed
renderer preferences, a random per-launch token, and only a typed `/api/` bridge.
The sidecar binds loopback in desktop mode and never opens a LAN listener.

XDG locations are owner-only: config `$XDG_CONFIG_HOME/vortex`, data
`$XDG_DATA_HOME/vortex` with SQLite/WAL, reports and artifacts, cache
`$XDG_CACHE_HOME/vortex`, and runtime `$XDG_RUNTIME_DIR/vortex`. No package
install creates user data. Uninstall preserves it unless the user explicitly
purges it. Config precedence is built-in secure defaults, optional `/etc` policy,
user config, then explicit flags; unknown keys fail validation.

## 6. AI, workers, tools, and evidence

The pipeline is:

```text
natural-language request
 → intent / risk / scope gate
 → engagement and authorization check
 → actual host/tool probes
 → bounded local specialist participation
 → evidence-grounded typed plan
 → policy + executable identity + freshness validation
 → explicit approval
 → real Python execution
 → parser / explanation / next-step proposal / audit
```

Deterministic skills always work offline. A local model may classify, explain, or
propose a structured candidate, but cannot add an executable, widen scope, alter
policy, fetch templates, call a public endpoint, or execute. Workers have a
manifest with ID/version, local proof, schema, health probe, license, limits,
risk classes, and advisory-only status. The ledger says queried, responded,
timed out, unavailable, rejected, or evidence-used. Missing workers are empty
seats, never implied consensus. Learning records only verified outcomes and
explicit corrections; it cannot create capabilities or relax policy and can be
inspected, exported, reset, or disabled.

Initial authorized adapters, only when factual probes find the installed tool:

| Family | Guardrails |
|---|---|
| `nmap` scoped service discovery/XML | engagement, host/CIDR/port bounds, conservative timing, no evasion/decoy/spoof |
| `nuclei` reviewed checks | signed/reviewed template/tag allowlist, bounded rate, no arbitrary download |
| `curl`/`httpx`/`whatweb` HTTP/TLS | URL scope, redirect/DNS revalidation, method/body/time limits |
| `ffuf`/`feroxbuster`/`gobuster` | wordlist provenance, bounded threads/rate/duration, no spraying |
| `nikto` | target scope, confirmation, bounded output/evidence |
| `amass` passive OSINT | declared domain scope, passive disclosure, no cloud creds |
| XML/capture/log/SBOM artifacts | size/type limits, hash/provenance, no invented findings |
| `ss`, `ip`, `lsof`, `journalctl`, `systemctl` | local read-only facts by default |

A parser may say `observed`, `inconclusive`, `tool_error`, or `not_run`; a model
summary cites the command/artifact and never turns absent output into a finding.
“No findings” only means the completed tool reported none in its declared scope.

## 7. Linux policy adapters

Filesystem reads (`ls`, `find`, `du`, `stat`, `df`, `mount`), system facts
(`uname`, `uptime`, `free`, `ps`, `lsof`, bounded journal), apt read-only facts,
Git status/diff/log, container list/inspect/logs, network/DNS diagnostics, and
SSH diagnosis are read-first capabilities. Service/package mutations require
fresh facts, exact identifiers, an impact card, and confirmation.

Apt must probe apt-get/apt-cache/dpkg-query/sudo, validate package grammar,
show installed/candidate version, architecture, origin, held state, dependency
changes and removals from a fresh `apt-get -s` preflight, dpkg/lock/reboot state,
and signature policy. No unauthenticated flags, trust bypasses, PPAs, curl-piped
installers, or arbitrary `.deb` files. Systemd validates unit names and user bus
context, bounds journals, and never performs vacuum/mask/default-target changes
in v1. Git destructive operations and container stop/remove/prune are separate
confirmed adapters. Prohibited classes remain blocked in every profile.

Profiles are `safe` (default), `standard`, and `expert`; expert may reduce
interactive friction for a local user but cannot bypass recording, blocked
classes, scope, executable identity, or exact plan approval.

## 8. Visual identity and accessibility

Use the Vortex palette: background `#0a0a0c/#0d0d10`, surfaces `#121217`,
foreground `#f0f0f4`, critical `#cc0000`, success `#23a049`, info/cyan
`#00d4aa`, warning `#e6a817`, and cursor reference `#00ff7f`. Themes are
`vortex-dark`, `vortex-high-contrast`, `plain`, and `auto`. Status text is always
present: `[PLANNED]`, `[CONFIRM REQUIRED]`, `[RUNNING]`, `[VERIFIED OK]`,
`[FAILED]`, `[BLOCKED]`, and `[NOT RUN]`.

Binary `0`/`1` matrix rain is a decorative canvas layer. It pauses when hidden,
obeys reduced motion, caps frame rate, reduces intensity, never receives input,
and never overlays terminal output. The project-owned hooded researcher SVG is
branding only and does not imply a real person, surveillance, or compromise.
Theme preview/export never edits a terminal profile; any future install is an
explicit diffed, backed-up, idempotent Vortex-owned operation with uninstall.
No OSC background/cursor/title sequences are emitted by default.

## 9. Delivery phases and gates

### Phase 0 — Foundation

Inspect repository/Git/licensing; add README, security, contributing, conduct,
threat model, ADRs, changelog convention, CI, pinned dev instructions,
compatibility matrix, I/O protocol, retention policy, threat boundary, and exit
codes. Gate: clean Linux host can boot help/doctor with no model or network.

### Phase 1 — Honest vertical slice (implemented in this delivery)

Implement the dependency-free Python sidecar, deterministic `ask`/`plan`/natural
language routing, doctor, tools, engagements, text/JSON envelopes, plan lifecycle,
Electron shell/preload bridge, cyber-themed renderer, real host probes, and tests.
Gate: unsupported requests abstain, missing tools never create evidence, no plan
or ask launches a command, and the UI discloses deterministic/local status.

### Phase 2 — Safe execution (implemented in this delivery)

Implement typed argv, explicit approval, direct operator attribution, safe cwd and
environment, path/executable identity capture, process groups, output caps,
redaction, signal/timeout handling, audit events, and post-execution analysis.
Gate: no shell interpolation, failed commands remain failed, real exit evidence
is stored, and dry-run/declined operations change nothing.

### Phase 3 — Core Linux and authorized security skills

Add apt preflight/source/lock handling, systemd semantic adapters, filesystem,
process/resource, Git, container, DNS/SSH, nmap and reviewed HTTP/content
adapters, target normalization, artifact hashes/parsers, tool-specific negative
and disposable Linux tests. No mutation is released without fresh facts and
confirmation.

### Phase 4 — Persistence/recovery

Add migrations, immutable audit verification, finite retention/pruning events,
backup/export, SQLite integrity and crash reconciliation, Markdown/JSON reports,
opt-in raw evidence, feedback/reset controls, and safe rollback metadata.

### Phase 5 — Optional local intelligence

Add signed reviewed knowledge packages, loopback/Unix-socket model clients,
endpoint allowlists, prompt minimization, provider status/test, structured
candidate validation, worker manifests and malicious-model evaluation corpus.

### Phase 6 — Shell integration and managed jobs

Generate Bash/Zsh/Fish completion and man page; add explicit install/uninstall
blocks, PTY session lifecycle, tmux/SSH/non-TTY behavior, cancellation, and
concurrency/resource caps. Shell RC files are never touched implicitly.

### Phase 7 — Linux release

Release tested signed/checksummed Linux Debian-family `.deb` first, with `/usr/bin/vortex`,
man page, completions, documentation, SBOM, SPDX inventory, provenance,
reproducibility notes, fresh-VM install/upgrade/uninstall tests, and no desktop
autostart/listener/telemetry. Defer Snap/Flatpak/RPM/AUR until confinement and
host-execution behavior are separately tested.

## 10. Quality, abuse resistance, and release blockers

Unit, integration, golden, property, fuzz/mutation, shell compatibility, and
real disposable Linux tests cover argv/path/package/unit parsing, plan digest and
approval invalidation, ANSI/bidi/control output, malformed UTF-8, giant output,
symlink traversal, public model endpoints, prompt injection, stale/replayed plans,
tampered audit/package data, sudo/password handling, forked descendants, signal
escalation, SSH disconnect, systemd-less contexts, missing tools, expired scope,
DNS/redirect changes, and worker unavailability. No shared host runs mutation
acceptance tests.

CI runs formatting, lint, tests, dependency/license/SBOM review, shellcheck,
unsafe-code review if introduced, dependency lock/provenance checks, and build
smoke tests on Linux. Maintain a capability matrix marked `implemented + tested`,
`available but tool missing`, `planned`, or `explicitly unsupported`; documentation
must not turn proposals into claims. Maintainers publish an incident process,
adapter emergency-disable list, knowledge revocation path, security update
channel, rollback instructions, and release support lifecycle.

Version 1 is blocked until a clean supported Linux VM demonstrates: no-network/no-
model install and operation; correct TTY/non-TTY stdout/stderr/JSON/exit behavior;
plan substitution/double-run/PATH replacement resistance; truthful cancellation,
timeout, SSH disconnect and crash states with no descendants; no password capture
or auto-escalation; fresh apt/systemd mutation facts; malicious model/terminal/
knowledge content cannot widen scope or execute; audit retention/backup/migration/
tamper behavior; clean `.deb`/man/completion lifecycle; and documentation that
clearly distinguishes real capability from proposal.

## 11. Product-owner decisions before mutation/release phases

1. Confirm Linux-first v1 and defer Fedora/Arch.
2. Keep command name `vortex` unless a distro collision requires `linux-vortex`.
3. Confirm MIT licensing and third-party attribution policy.
4. Choose Ollama, llama.cpp, or both behind the local OpenAI-compatible protocol.
5. Keep the optional TUI excluded; desktop UI is retained by the binding direction,
   but no browser or cloud product is introduced.
6. Ship signed `.deb` first; add other package formats only after dedicated tests.

## 12. Implementation progress log

### Priority 1 — real terminal/session layer

**Started and implemented in the current iteration.** The Python sidecar now owns
Linux controlling PTYs, process groups, session metadata, bounded sanitized event
polling, input, resize, cancellation with TERM/KILL escalation, idle cleanup,
stale-session recovery states, authenticated session routes, and explicit desktop
open/stop controls. The CLI can create and attach to a foreground local PTY in an
interactive terminal; the desktop sidecar supports session listing, event attach,
input, resize, and kill.

Remaining Priority 1 work is full terminal rendering/multiplexing: xterm-quality
ANSI handling, tabs, panes, reconnectable daemon-owned attach, SSH/tmux/non-TTY
compatibility tests, and a durable session/job protocol. These must be completed
before marking the complete terminal workspace acceptance gate passed.

### Priority 2 — real adapter registry

**Started and implemented in the current iteration.** A versioned manifest registry
now describes Linux health, filesystem usage, socket inspection, Git status,
systemd inspection, bounded HTTP headers, and scoped nmap discovery. Plans carry
adapter identity, version, limits, risk, network class, and real tool state.
`vortex adapters` and `/api/adapters` expose that factual registry. The nmap and
curl builders enforce engagement scope, bounded CIDRs/ports, conservative flags,
HTTP(S)-only URLs, and explicit offline blocking.

The direct operator PTY and `vortex run -- ...` path intentionally remain a full
native Linux escape hatch: the adapter policy governs AI-proposed operations and
never pretends to remove the operator’s ability to run authorized Linux commands.
Direct commands are still shell-free at the Vortex boundary, explicitly
attributed `operator_direct`, approval-gated/logged, and can invoke a shell as a
literal operator-selected executable.

Remaining Priority 2 work is a complete adapter package layout, DNS/redirect
revalidation, stronger container/SSH output parsers, nmap XML/HTTP hardening,
parser fuzzing, and disposable Linux acceptance evidence.

### Priority 2 — artifact parsing and evidence provenance

**Implemented in the current iteration.** Bounded parsers now accept supplied Nmap
XML, HTTP response headers, and generic text artifacts. Every result records a
random/local artifact identity, source provenance, byte size, SHA-256, parser ID
and version, and an honest `observed`, `inconclusive`, `tool_error`, or `not_run`
state. XML entities/DOCTYPEs, symlink inputs, oversized files, terminal escapes,
control characters, and common secret values are handled defensively. Parsed
observations are evidence only; no parser invents a vulnerability or security
finding.

Successful HTTP adapter operations and generated Nmap XML are parsed into the
operation report and local artifact table. Generated raw Nmap XML is deleted by
default after parsing; retention requires the explicit
`VORTEX_RETAIN_RAW_EVIDENCE=1` opt-in and mode 0600. Supplied artifacts can be
inspected without executing anything:

```text
vortex artifact inspect ./scan.xml --type nmap-xml
POST /api/artifacts/analyze {"path":"./scan.xml","kind":"auto"}
```

The remaining evidence work is parser confidence/error taxonomy expansion,
namespace/format coverage, DNS/redirect provenance, signed artifact packages,
and parser fuzzing in disposable Linux CI.

### Priority 3 — guarded apt and systemd operations

**Started and implemented in the current iteration.** The adapter registry now
includes typed package-operation plans for apt install/remove/upgrade and typed
systemd start/stop/restart/enable/disable plans. Package plans validate package
names, probe apt/dpkg tools, inspect lock availability, check dpkg state, show
candidate/source/package facts, run a fresh `apt-get -s` preflight immediately
before the mutation, and require a root-only final command. Systemd plans validate
unit names, probe systemd availability, show fresh unit state immediately before
the action, and mark persistent enable/disable changes. Forbidden repository
trust bypasses, PPAs, arbitrary debs, daemon reloads, masking, vacuum, and default
-target changes remain excluded.

Vortex never invokes sudo or captures passwords. Normal users receive a rerun
instruction such as `sudo vortex --allow-root run <plan-id>`; the native PTY and
explicit operator-direct path retain full Linux capability. Tests use planning
and policy checks only; no shared-host apt or service mutation is run.

Remaining Priority 3 work is richer held/reboot/incomplete-state reporting,
lock behavior on supported Linux, fresh privileged disposable-VM install/remove
and service acceptance tests, interactive privilege flows, and rollback/recovery
metadata. User-bus detection and strict `systemctl --user` routing are now
implemented.

### Priority 3 — apt/systemd factual result parsing

**Implemented in the current iteration.** Apt preflight output is now parsed for
upgrade/new/remove/not-upgraded counts, package lists, held/kept-back markers,
reboot hints, and lock/error states. Systemd `show` and bounded journal output
are parsed into unit load/active/substate/persistence fields and bounded failure
line observations. Adapter facts are attached to completed operation analysis.

Before a guarded mutation, the executor now requires fresh successful facts:
changed apt preflights that report removals for install/upgrade are blocked, a
remove with no observed removal is blocked, and missing/not-found systemd units
are blocked before the action command. The normal-user root gate remains in
place. Current tests use controlled test doubles only; production never fabricates output and no shared host is mutated.

The remaining acceptance work is a disposable supported Linux VM for real apt
install/remove and service actions, user-bus semantics, held/reboot edge cases,
and rollback metadata. The production path has no fake preflight mode; apt
`-s` is a real package-manager read-only preflight. Mutating operations pause
with the observed preflight facts and require a second exact approval before the
real mutation command runs.

### Product-owner platform clarification — Linux without version marketing

The product is presented as **Linux Vortex Terminal for Linux**, not as an
distribution-release-specific application. Kali Linux is a first-class Debian-family
runtime when factual probes show the required tools and context. Documentation,
branding, and capability claims must not name a Linux release version. `doctor`
may still return the host's factual `/etc/os-release` version in machine-readable
host diagnostics because hiding observed state would violate truthfulness; that
fact is not a support or release promise.

### Priority 2 — Linux container and SSH diagnostics

**Implemented in the current iteration.** Added factual Docker/Podman runtime
selection with read-only `ps --all --no-trunc` inspection and explicit missing-
runtime handling. Added read-only SSH effective-configuration resolution using
`ssh -G`; it does not connect, authenticate, read private keys, or harvest agent
secrets. Both adapters run only real installed host tools and are represented in
the adapter registry. Full container log parsers, SSH connection diagnostics,
and runtime-specific acceptance tests remain separate work.

### Priority 1 — terminal workspace progress

**Current slice implemented.** The desktop workspace now provides real session tabs,
a two-pane split view, safe SGR color/bold rendering, direct control/navigation
key forwarding, and explicit shell integration preview/install/uninstall. Shell
integration writes only a Vortex-owned idempotent block, creates a timestamped
backup, requires `--yes`, and removes only that block on uninstall. No shell RC
file is changed implicitly.

The native PTY and direct operator command paths retain full Linux capability.
The remaining terminal work is full cursor/erase terminal emulation, complete
alternate-screen/TUI behavior, reconnectable attach across sidecar restarts,
PTY history replay, and tmux/SSH/non-TTY acceptance evidence.
