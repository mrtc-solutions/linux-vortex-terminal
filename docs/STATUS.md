# Current implementation status

VORTEX 0.2.21 is a real Linux application. Production paths use installed host
tools, typed argv, and observed output only. Test doubles exist only inside
controlled tests.

**Automated validation is passing:** 193 Python tests, plus JS terminal,
window-control, frontend smoke, and frontend runtime smoke suites.

## 0.2.21 — local-AI-first advisory routing and install-flow audit

This round focused on the plan follow-up: re-review the app, investigate the
reported tool-installation failure, test the whole reachable surface, and fix
any remaining inaccuracies.

### What was implemented or tightened

- Local-AI-first advisory routing remains loopback-only and non-authoritative.
- Dependency inventory now covers Node.js, npm, pnpm, yarn, Go, Docker/Podman,
  reviewed wordlists, Ollama runtime, and the local model pool.
- Dependency proposals now distinguish:
  - reviewed apt-plan requests such as `install package <pkg>`
  - manual Ollama bootstrap guidance
  - manual local model-pool pull guidance
- Health/setup checks now surface Node.js, npm, pnpm, yarn, Go, Ollama, and
  model-pool readiness.
- Real read-only acceptance now treats an unavailable `systemctl` bus in this
  sandbox as an honest sandbox limitation instead of a false app failure.

### Defects found in the latest audit pass

| # | Defect | Why it mattered | Fix |
|---|---|---|---|
| 1 | Per-turn execution could lose the intended Ollama settings snapshot | A saved or per-turn Ollama endpoint was not always used consistently across execution analysis | Settings propagation was fixed across backend execution/orchestration/CLI paths and covered by regression tests |
| 2 | Dependency inventory counted `blocked` runtimes like Node/npm/yarn as missing installs | It looked like VORTEX had failed to install tools even when the binaries were already present on the host | Blocked runtimes are now reported as present-but-flagged, with security flags preserved |
| 3 | Dependency inventory ignored saved Ollama settings | `deps` could report the wrong endpoint/runtime state | Inventory now loads saved runtime settings before probing model status |
| 4 | Health/setup checks treated blocked runtimes as unavailable | First-run checks could falsely imply Node/npm/yarn/Go were absent rather than review-needed | Health now reports `warning` for blocked paths and setup checks accept that state honestly |

## Directive coverage

| Area | State |
|---|---|
| Real execution / PTY / NL Linux (reviewed adapters) | Done + tested |
| Guardian, risk policy, STOP ALL | Done + tested |
| Engagements / scope / exclusions / close | Done + tested |
| Tasks, resume, pause, reject, replay, replan bounds | Done + tested |
| Conversations, branch, export, search | Done + tested |
| Tool registry live probes | Done + tested |
| Agent council discovery (builtin + third-party probes) | Done + tested |
| Reports MD/HTML/JSON/PDF + assessment scope | Done + tested |
| Memory / procedures / experiences | Done + tested |
| Missing-dependency inventory and reviewed install proposals | Done + tested |
| User-local install, `vortex serve`, `vortex turn` | Done + tested |
| Android APK client | Done + tested |
| Linux desktop .deb packaging | Done + tested |
| Local-AI-first Ollama advisory routing | Done + tested; advisory only, loopback only |
| Ollama runtime/model-pool dependency visibility | Done + tested |
| Wordlist dependency proposal | Done + tested |
| Node/npm/pnpm/yarn/Go health/setup visibility | Done + tested |
| Docker/Podman runtime probe | Done + tested; execution remains limited |
| Third-party agent non-interactive consult execution | Not implemented |
| Docker/Podman sandbox execution | Not implemented |
| sqlmap / msf execution adapters | Not implemented |
| MCP | Not implemented |
| Remote graphical sessions | Not implemented |

## What the earlier “install failure” really was

There is no general silent installer in this product.

- `scripts/install-user.sh` writes only a launcher.
- `vortex install --user` writes only a launcher.
- Reviewed distro packages become reviewed apt plans.
- Those plans still require an operator/admin to execute them separately.
- Ollama and third-party agents remain operator-installed.
- Binaries found in unsafe paths may show as `blocked`, which means “present but
  not silently trusted,” not “missing because install failed.”

## Remaining host / release gates that cannot be faked

1. Real reviewed apt/systemd mutation on a host you administer
2. Real default Ollama runtime at `http://127.0.0.1:11434` on this sandbox host
3. Reviewed third-party agent consult execution for actual installed CLIs
4. Reviewed Docker/Podman sandbox execution beyond probe/inspect/log surfaces
5. Signed `.deb` release evidence on a release-controlled VM

## Latest validation summary

- `python3 -m unittest tests.test_local_ai -v` → PASS (`Ran 12 tests`)
- `python3 -m compileall -q backend cli tests && node --check ...` → PASS
- `npm test` → PASS (`Ran 193 tests ... OK` + JS suites)
- `npm run lint` → PASS
- `VORTEX_REAL_ACCEPTANCE=1 ... ./tests/linux_acceptance.sh` → PASS
- Live CLI validation for `install`, `doctor`, `health`, `deps`, `model status`,
  and `benchmark` → PASS
- Live loopback local-AI validation against a stub Ollama runtime/model pool → PASS

## Bottom line

Everything reachable in this sandbox for the recent plan is green. The remaining
unknowns are real environment limits outside this sandbox, not untested claims
inside the codebase.
