# Implementation report — VORTEX 0.2.21

**Status:** production-quality modular monolith; not a 1.0 release

## What is real now

- One Python execution authority: `shell=False`, PTY, approval tokens, audit chain.
- Independent Guardian. Agents and models cannot self-approve.
- Workspace turn: plan → council (observation as data) → Guardian → optional execute.
- Built-in `vortex-local` advisor is always present and never executes.
- Local-AI-first advisory routing through loopback-only Ollama is implemented.
- Recommended local model pool is tracked live: `phi4-mini:3.8b`, `qwen3:4b`, `llama3.2:3b`, optional `gemma3:4b`.
- Dependency inventory/proposals now cover Node.js, npm, pnpm, yarn, Go,
  Docker/Podman, reviewed wordlists, Ollama runtime, and the Ollama model pool.
- INSTALL remains proposal-driven:
  - reviewed apt dependencies become typed plans
  - root-required reviewed plans are rerun with `sudo vortex --allow-root run <plan-id>`
  - Ollama, model pulls, and third-party agents remain operator-manual
- `blocked` binaries are treated as present-but-flagged rather than falsely missing.
- Health and first-run setup checks surface runtime/model readiness honestly.
- `vortex install --user`, `vortex serve`, `vortex turn`, and the desktop/web/mobile surfaces are live.
- 193 Python tests plus JS terminal, window-control, frontend smoke, and frontend runtime smoke suites are passing.

## What the recent pass fixed

1. Execution analysis now preserves per-turn/saved Ollama settings snapshots.
2. Dependency inventory no longer mislabels blocked Node/npm/yarn installs as missing.
3. Dependency inventory now uses saved Ollama settings when probing runtime/model status.
4. Health/setup checks now show blocked runtimes as warnings instead of false absence.
5. Real read-only acceptance now reports unavailable `systemctl` bus access in this sandbox honestly rather than failing the whole checklist.

## Honest limits

This sandbox still cannot prove:

- reviewed apt/systemd mutation on a disposable/admin-controlled host
- a real default Ollama runtime at `http://127.0.0.1:11434`
- third-party agent non-interactive consult execution
- reviewed Docker/Podman sandbox execution

Do not describe VORTEX 0.2.21 as an unrestricted autonomous pentest platform
or as silently installing tools for the operator.
