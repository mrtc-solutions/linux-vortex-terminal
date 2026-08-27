# Implementation report — VORTEX 0.2.0

**Status:** production-quality modular monolith; not a 1.0 release

## What is real

- One Python execution authority: `shell=False`, PTY, approval tokens, audit chain.
- Independent Guardian. Agents and models cannot self-approve.
- Workspace turn: plan → council (observation as data) → Guardian → optional execute.
- Episode reward is 0 or 1 from observed Linux outcomes (`backend/episode.py`).
- Built-in `vortex-local` advisor is always present and never executes.
- Third-party agent adapters probe binaries only; consult stays REQUIRES CONFIGURATION.
- Missing tools are listed live. INSTALL builds an apt plan or an operator proposal.
- nuclei/ffuf/nikto/amass/gobuster adapters emit real argv or UNAVAILABLE.
- `vortex install --user`, `vortex serve`, `vortex turn`, and `docs/USER_GUIDE.md`.
- 102 Python tests plus the JS terminal emulator.

## Honest limits

This host has no Docker, no Ollama, and none of the nine external agent CLIs.
Those subsystems report UNAVAILABLE rather than fake success.

Do not describe VORTEX 0.2.0 as a full autonomous pentest platform or as
having working third-party agent conversations.
