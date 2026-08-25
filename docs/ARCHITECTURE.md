# Architecture decision record: one local execution authority

## Decision

Linux Vortex Terminal uses a Linux-only Electron renderer with a Python 3.11
local sidecar. Electron owns the desktop lifecycle and window; its renderer is
context isolated and receives only the typed preload API. The Python sidecar is
the only production component permitted to spawn a process.

The repository also ships a dependency-free `vortex` CLI that calls the same
core modules directly. The current HTTP handler uses Python's standard library
so a fresh Linux host has no runtime dependency download. A future FastAPI /
Pydantic handler must preserve the same route and authority boundary.

## Request flow

```text
renderer or CLI
  -> natural-language deterministic planner
  -> actual host and tool probes
  -> typed CommandSpec / Engagement gate
  -> policy + cwd + executable identity + freshness validation
  -> exact approval token
  -> Python ExecutionManager (shell=False, new session)
  -> bounded sanitized evidence + exit/signal
  -> SQLite operation + hash-chain audit + analysis
```

An optional model and local workers may propose structured candidates later. They
never get process access, scope authority, policy access, or a network transport
outside an explicit loopback/Unix-socket allowlist. The adapter registry applies
to AI-proposed operations. An operator using the real PTY or explicit
`vortex run -- ...` retains native Linux access, with the direct path visibly
attributed and still audited rather than falsely described as adapter-validated.

## Data model

- `plans`: random 256-bit identity, expiry, exact command digest, approval token,
  working-directory scope, policy/source versions, and lifecycle metadata.
- `operations`: one claimed execution of a plan and its per-command observed
  timeline. Plan claim is transactional, so a second caller cannot double-run.
- `engagements`: operator-declared authorization reference, normalized targets,
  classes, and expiry.
- `audit_events`: append-only event payloads chained with SHA-256. The chain
  detects ordinary alteration; it does not protect a compromised account.
- `feedback`: redacted local corrections only. It cannot create capabilities or
  relax policy.
- `artifacts`: hashes, parser provenance, and redacted observations for supplied
  files or real adapter output; raw generated evidence is removed by default.

The database is SQLite WAL with a five-second busy timeout. The data root is
created as mode 0700 and the database is intended to be mode 0600. Runtime raw
evidence is not retained in this slice; stored stdout/stderr is sanitized,
bounded, and redacted.

## Process safety

One-shot commands are invoked with `subprocess.Popen(..., shell=False)`,
`start_new_session` and `close_fds=True`. The environment is rebuilt from a
small allowlist. The executor reads stdout and stderr concurrently, caps output,
sends TERM then KILL to the process group on timeout, and records `exit_code`,
`signal`, and `termination_reason` separately.

Priority 1 also adds `SessionManager`: Linux `pty.fork()` creates a controlling
terminal, a dedicated process group, a bounded in-memory event ring, input,
resize, cancellation escalation, and a reaper. Session output is sanitized and
redacted before transport; input is never persisted. The renderer now offers
session tabs, a two-pane split view, safe SGR rendering, and per-key input
forwarding. Session metadata is stored, but old `running` sessions become
`unknown_after_crash` when a new sidecar owns the store. The desktop uses
authenticated event polling over the sidecar API. Full cursor/erase emulation
and durable daemon attach remain follow-up work.

## Desktop security

Electron starts the sidecar bound to `127.0.0.1` with a random per-launch token.
The renderer has no Node integration and uses a frozen preload bridge that accepts
only `/api/` routes. The local preview intentionally has no token and serves the
renderer and API same-origin; it is development convenience, not a production
LAN deployment. The sidecar never binds a public interface in desktop mode.

## Deliberate non-decisions

No cloud API, plugin execution, remote host management, automatic sudo, terminal
RC mutation, package auto-install, fake scan fixtures, or silent model fallback
is introduced. Each is an explicit future design requiring its own threat review.
