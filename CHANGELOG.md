# Changelog

## 0.2.0 — 2026-08-25

- Workspace SEND uses `/api/workspace/turn`. REJECT and PAUSE are real HTTP
  routes. Conversation export is a JSON attachment. Engagement assessments
  include only that engagement's operations.
- Guardian destructive checks are word-level (`adduser` is not treated as `dd`).
  Excluded targets match hosts, not arbitrary substrings.
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
