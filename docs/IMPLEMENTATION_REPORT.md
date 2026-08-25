# Implementation report — VORTEX 0.2.0

**Date:** 2026-08-25  
**Status:** production-quality modular monolith; not a 1.0 release

## Delivered beyond the 0.1 slice

- Independent Guardian (`backend/security/guardian.py`) recomputes risk and
  approval from command specs and policy. Models and agents cannot approve
  themselves. Destructive matching is word-level (`adduser` is not `dd`).
- Persistent conversations, VTX task IDs, edit-branching, export download,
  search, reject, pause.
- The overview SEND control posts `/api/workspace/turn` (plan + Guardian +
  optional auto-run). Approve still uses the single execution authority.
- Agent adapters as separate modules with live `health_check()`. Installed
  binaries are not invoked until a reviewed consult interface exists.
- Tool registry, system reports, assessment reports scoped to one engagement,
  JSONL observability, plugin manifests, sandbox capability probe, first-run
  checks, benchmark CLI, HTTP API tests, security tests.
- 70+ Python tests plus the JS terminal emulator test.

## Honest limits

See `docs/STATUS.md`. This host has no Docker, no Ollama, and none of the nine
external agent CLIs. Those subsystems report UNAVAILABLE rather than fake
success.

Do not describe VORTEX 0.2.0 as a full autonomous pentest platform or as
having working third-party agent conversations.
