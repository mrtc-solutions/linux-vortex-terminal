# ADR-0001: single local execution authority

- **Status:** accepted
- **Date:** 2026-08-25

The Python sidecar owns every production process launch. Electron may own the
window, and the renderer may request a plan or an approved operation through a
context-isolated typed bridge, but it never runs Node child processes. The CLI
uses the same executor directly. This prevents duplicated PTY/process semantics
and makes cancellation, exit evidence, redaction, policy, and audit reviewable
at one boundary.

The current sidecar intentionally uses the Python standard library for a clean
Ubuntu bootstrap. FastAPI/Pydantic can become an adapter dependency when the
packaged desktop application needs it; they must not create a second authority.
