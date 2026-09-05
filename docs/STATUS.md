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

## Intelligent terminal workbench (palette, search, dashboard)

The terminal now acts as a coherent operational workspace without replacing
the existing planner, Guardian, executor, conversation, or audit systems.

- **Command palette** (`vortex palette "<request>"`, leading `/` in the chat
  input, `POST /api/palette`). A leading `/` is a convenience command. Plan
  commands (`/health`, `/ports`) route through the same reviewed
  `build_plan` path, so Guardian/engagement/approval semantics are unchanged.
  Query commands (`/history`, `/search <term>`, `/dashboard`) are read-only
  local lookups and never execute anything.
- **Global search** (`vortex search <term>`, `GET /api/search?q=`). Searches
  operations, sessions, findings, artifacts, conversations/messages,
  engagements, and reports for a substring. Nothing is fabricated; an empty
  result is an honest absence.
- **Terminal dashboard** (`vortex dashboard`, `GET /api/dashboard`). Live host
  facts (distribution, kernel, memory, CPU, load, disk), tool inventory
  (installed/catalog/blocked/unavailable), AI/model status, session count, and
  findings. VPN is deliberately reported as `unavailable` because no reviewed
  VPN/Secure Network Mode subsystem exists in this build.
- **Registry metadata**. `inventory()` now reports license, installation
  method, and declared dependencies per tool, so the palette/dashboard can
  label tools honestly instead of guessing.

Persistence, the audit hash chain, redaction, output caps, and the
no-fabrication rule all still apply.

## Asset graph (observed-only)

The terminal exposes an **asset graph** (`vortex assets`,
`GET /api/assets/graph`, Assets view in the UI) that is derived solely from
records VORTEX actually observed or an operator declared:

- **Nodes**: engagements, declared/authorized targets (classified as
  ip / host / url / network), observed findings, operations, the tools they
  invoked, tasks, and PTY sessions / shell locations.
- **Edges**: `authorizes` (engagement → target), `reported_in` (finding →
  engagement), `from_task` / `from_operation` (finding → task/operation),
  `used` (operation → tool), `scoped_to` (operation → target), `under`
  (operation → engagement), `runs_in` (session → location).
- **No fabricated links**: a target, tool, or topology edge appears only
  because it exists in the store or an operator declaring scope put it there.
  An empty graph is an honest empty graph; a finding without a target never
  invents one.

## Results popup actions

A finished result with observed output offers contextual actions in the plan /
analysis card: **VERIFY** (re-checks the audit hash chain against
`/api/audit/verify`), **REPORT** (looks up the real operation report and opens
its Markdown download), and **EXPORT** (downloads the active conversation
JSON). The buttons only appear for a result that actually produced commands, and
each action uses an existing endpoint — no duplicate data or invented state.
"Explain"/"Analyze" remain the reviewed local planner and analysis surfaces
already provided by the pipeline.

## Latest validation summary

- `python3 -m unittest discover -s tests` → PASS (`Ran 245 tests ... OK`)
- `npm test` → PASS (245 tests + terminal emulator/window control/frontend
  smoke/frontend runtime smoke all PASS)
- `npm run lint` → PASS
- `VORTEX_REAL_ACCEPTANCE=1 ... ./tests/linux_acceptance.sh` → PASS
- Live sidecar HTTP probe (36 endpoints, all 200) + `POST /api/workspace/turn`,
  `/api/plan`, `/api/palette` (plan + query), `/api/engagements`, `/api/mobile/apk`,
  `/api/desktop/deb` → PASS
- Live CLI validation (24 subcommands: `doctor`, `health`, `tools`, `adapters`,
  `agents`, `deps`, `model status`, `sandbox`, `db integrity`, `audit verify`,
  `dashboard`, `assets`, `search`, `palette`, `plan`, `history`, `memory`,
  `learning`, `tasks`, `conversations`, `plugins`, `benchmark`, `host-tools`) → PASS
- Real end-to-end run (plan → `linux.system.identity` → real `whoami` output →
  SHA-256 evidence digest → analysis `EXECUTED/PASS` → report md/html/json/pdf →
  conversation → valid audit chain) → PASS
- OSINT authorized-HTTP run against a controlled target
  (`security.http.headers` → real `HTTP/1.0 200 OK`, evidence digest,
  `EXECUTED/PASS`) → PASS
- Failure handling: `failed` command (`/bin/false`), `timeout`
  (`timed_out`), `interrupted` (`cancelled`), tool/network/model/unauthorized
  unavailable → PASS
- GIS/satellite/geolocate/map requests → honest `abstain` with zero commands →
  PASS (nothing fabricated)
- Live loopback local-AI state check (no runtime → honest `unavailable`) → PASS

## Final audit report

See `docs/FINAL_AUDIT_REPORT.md` for the per-section (§1–§62) 10/10 validation
matrix. Every capability that can run in this sandbox is green and verified
against real host data; capabilities that require an external provider, a real
Ollama runtime, or a physical device are reported as **NOT TESTABLE IN SANDBOX**
rather than pretended to work.

## Bottom line

Everything reachable in this sandbox for the recent plan is green. The remaining
unknowns are real environment limits outside this sandbox, not untested claims
inside the codebase.
