# VORTEX Change Plan — Local GGUF folder selection

## Problem

The Models view discovers GGUF files from configured/default locations, but it
does not let an operator select a local model file or folder. This leaves the
existing `models_dir` setting inaccessible from the UI and does not satisfy the
manual-import workflow.

## Evidence

* `backend/models/gguf.py` already validates GGUF headers and reports model
  size, family, quantization, RAM fit, engine availability, and usable state.
* `backend/config.py` already persists a bounded `models_dir` setting.
* `frontend/index.html` exposes GGUF status and role activation, but no file or
  folder chooser; `frontend/models.js` only calls the GGUF activation endpoint.

## Root cause

The earlier GGUF provider implementation (commit `5795f6a`, merged by
`24cf8bf`) added discovery for default/configured roots but did not add an
operator-facing mechanism for changing the configured root. The current
redesign commit `704f8bb` retained that omission. No prior manual-import fix
was found in the relevant file history.

## Files affected

* `backend/models/gguf.py` — safely support configured external roots and
  recursively scan a selected folder with bounded traversal.
* `backend/models/manager.py` — validate and persist a user-selected local
  model file/folder without copying or claiming inference support.
* `backend/vortex_backend.py` — expose a capability-authenticated import route.
* `frontend/index.html` and `frontend/models.js` — add file/folder controls,
  render real inspection outcomes, and refresh state after selection.
* `tests/test_ollama_manage.py` and/or `tests/test_gguf_fuzzy.py` — regression
  coverage for file/folder import, validation, persistence, and discovery.

## Proposed solution

Use native Electron/Chromium file inputs (`accept=.gguf`; `webkitdirectory`)
to obtain an explicit operator choice. Send only the selected absolute paths to
a backend endpoint. The backend resolves one valid regular GGUF file or a
common parent directory, rejects oversized/non-GGUF/corrupt input, persists the
directory in the existing `models_dir` setting, invalidates the discovery
cache, and returns the existing truthful inspection fields. The implementation
will not move, copy, execute, or load model weights as part of import.

## Risk

Low to medium: external filesystem paths are operator-provided. Mitigate using
bounded request lengths/counts, resolved regular-file checks, GGUF header
validation, a directory traversal/file cap, and no file mutation. Existing
default discovery remains intact when no import is used.

## Tests

* Unit tests for valid file selection, folder selection, corrupt/unsupported
  rejection, and configured-root discovery.
* Existing Python and JS suites, lint, and package build.

## Rollback plan

Revert this commit. No model file is copied, moved, or modified; the only
persisted effect is `models_dir` and it can be cleared through Settings/API or
by removing the local settings file.

---

## Follow-up review: desktop delivery defects

### Problem and evidence

Post-implementation review found two release-blocking defects: Electron 44
does not expose an absolute filesystem path through the renderer `File.path`
property, and the desktop IPC allowlist did not include the new import route.
Consequently, the prior UI could submit no usable paths and, even if it did,
the desktop main process would reject the request before it reached the
sidecar.

### Root cause and previous implementation

The first implementation assumed an old Electron renderer API and added the
sidecar route without tracing the existing `desktop/security.js` capability
allowlist. The backend validation itself was correct but unreachable from the
supported desktop application.

### Proposed solution, risk, and tests

Expose a narrowly scoped preload helper backed by Electron's `webUtils`
`getPathForFile`, accepting only a real `File` object and returning a bounded
string. Add the exact GGUF-import POST route to the desktop allowlist. Update
the renderer to use the helper and fail honestly outside Electron rather than
submitting a fake path. Add preload/security and renderer regression tests,
then run the complete suite serially (no overlapping package builds).

### Rollback

Revert the follow-up commit; no imported model data is ever changed.

### Test isolation follow-up

The GGUF tests call role activation, which persists settings. Their fixture did
not isolate `XDG_CONFIG_HOME`, so a full suite could inherit offline/model
settings from a prior test or an operator's home directory. Because the
sidecar deliberately uses the root user's configuration home when it runs as
root, `XDG_CONFIG_HOME` is insufficient in this CI container; isolate the
explicit `VORTEX_CONFIG_DIR` instead and restore the previous environment
after each test so the complete suite is deterministic and cannot mutate user
settings.
