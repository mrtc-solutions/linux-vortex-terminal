# Changelog

## 0.2.8 — 2026-08-26

- Settings files with string booleans (`"false"`) keep compiled defaults; they
  cannot enable offline or first-run-complete.
- HTTP `plan_id`, engagement `targets`, and artifact `path`/`kind` must be
  strings. Numeric IDs are 422, not silently coerced.

## 0.2.7 — 2026-08-26

- HTTP PTY input must be a string; cols/rows must be integers (booleans rejected).
- Settings booleans are JSON `true`/`false` only (`"false"` does not enable a flag).
- Engagement names, secret slots, conversation titles, and task resume cwd stay strings.
- `complete-task` requires a task bound to that operation. Follow-up failures are audited.
- CLI `--approval-token` empty string no longer falls back to the stored plan token.

## 0.2.6 — 2026-08-26

- HTTP cwd/engagement/conversation/shell must be strings. Prune days and
  feedback ratings must be integers (booleans rejected). Non-string cwd is 422.

## 0.2.5 — 2026-08-26

- HTTP JSON must be an object. `confirm`/`offline`/`overwrite` are JSON
  `true` only (`"true"` does not execute). Approval tokens must be strings.
- Negative Content-Length is rejected. Duplicate backups return 409.
- Auto follow-up after a failed task is limited to low-risk local diagnostics.

## 0.2.4 — 2026-08-26

- HTTP backups always write under `data/backups/<filename>.db`; absolute paths
  cannot overwrite host files. Concurrent PTY sessions are capped.
- Guardian treats expired engagements as inactive. Agent probes use the same
  safe-PATH executable identity as managed tools. Conversation edit routes
  reject malformed paths.

## 0.2.3 — 2026-08-26

- HTTP `/api/execute` never accepts `allow_root`. Offline policy cannot be
  cleared by the renderer. GET `/api/plans/{id}` omits the approval token.
- HTTP backups must land inside the VORTEX data directory.
- Safe profile always confirms: settings cannot enable auto-run, medium auto,
  root, or a non-loopback Ollama endpoint.

## 0.2.2 — 2026-08-26

- Unknown, closed, or expired engagement IDs cannot plan outbound work and
  are not bound onto local diagnostics.
- Guardian matches `mkfs.ext4`-style destructive stems. HTTP artifact analyze
  stays inside the VORTEX data directory. Wordlists must live under `/usr/share`
  or the data directory; `/etc/passwd` is never accepted.
- sqlmap/msfconsole requests stay UNAVAILABLE with no fabricated command.

## 0.2.1 — 2026-08-26

- Reviewed nuclei / nikto / amass / ffuf / gobuster argv adapters. Missing
  binaries or wordlists stay UNAVAILABLE; no command is fabricated.
- `vortex install --user`, `vortex serve`, and `vortex turn` for real
  operator install and use. Session UI prefers EventSource.
- `vortex turn --yes` honors `--profile` and actually executes; task finish
  writes the report and episode reward before marking COMPLETED.
- Step-by-step operator guide: `docs/USER_GUIDE.md`.

## 0.2.0 — 2026-08-25

- Workspace SEND uses `/api/workspace/turn`. REJECT and PAUSE are real HTTP
  routes. Conversation export is a JSON attachment. Engagement assessments
  include only that engagement's operations.
- Guardian destructive checks are word-level (`adduser` is not treated as `dd`).
  Excluded targets match hosts, not arbitrary substrings.
- os-release / lscpu adapters, engagement close, task events, capabilities
  document, session SSE, static path-traversal tests, restored report engine.
- Workspace: conversations (branch on edit, export, search), VTX tasks with
  resume/restart/delete/pause, Guardian, Agent Council discovery, memory/procedures,
  system health, first-run probes, STOP ALL, report downloads (MD/HTML/JSON/PDF).
- Replanning records whether an observed operation met the objective. Missing
  tools do not produce a fabricated next step.
- Tool registry and sandbox/plugin endpoints probe the real host. Docker
  isolation and external agents stay UNAVAILABLE when not installed.
- Security tests cover command injection, prompt-injection phrasing, and
  Guardian independence from agent/plan text.
- Local Ollama is probed on loopback only. Cloud providers stay disabled.

## 0.1.0 — 2026-08-25

- Foundation: sidecar, deterministic planner, typed plans, approval tokens,
  real shell-free execution, redaction, audit chain, CLI, Electron-ready UI.
