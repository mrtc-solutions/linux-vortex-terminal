# Changelog

## Unreleased — 2026-09-09

On-device GGUF primary, fuzzy provider routing, per-function AI assistance,
and agent upstream tracking. No simulation: every new surface degrades to an
honest unavailable state when its files, engine, or network are absent.

- New **GGUF provider** (`backend/models/gguf.py`): discovers and validates
  `*.gguf` files (`~/linux-vortex-terminal/models` by default), with the two
  curated models Llama-3.2-3B-Instruct-Q4_K_M (fast/primary) and
  Qwen2.5-3B-Instruct-Q4_K_M (planner/specialist). Tuned for 8 GB RAM /
  ~2 GHz CPU: single resident model, 2048 ctx, ≤4 threads, mmap weights,
  llama-cpp-python or llama-cli engines, per-family chat templates.
- New **fuzzy router** (`backend/models/fuzzy.py`): GGUF → Ollama → agent
  council → deterministic core, blending availability, latency EWMA, RAM
  pressure, and phase fit. Every real call feeds back, so a delaying or
  failing primary yields to the secondary automatically.
- `advise()` is provider-aware (per-item `provider`, latency recording) and
  `model_status()` reports `providers` + `fuzzy` winner/ranking; `vortex
  model test` runs a real smoke completion.
- New **universal assistance** (`backend/models/assist.py`, 16 functions):
  plan, explain, palette, search, dashboard, assets, health, deps, replan,
  report, memory, engagement, session, interpret, verify, and error paths
  carry `ai_hint`. Advisory only; nothing blocks and nothing breaks without
  a model. New endpoints `POST /api/assist`, `GET /api/assist/coverage`.
- New **GGUF endpoints** `GET /api/models/gguf` and
  `POST /api/models/gguf/activate` (role persistence after file
  verification; traversal-safe), plus a Models-view GGUF panel and updated
  desktop preload allowlist.
- New **agent upstream tracking** (`backend/agents/upstream.py`): every
  secondary assistant links its original repository with license, install
  guide, and consult status; operator-triggered `POST
  /api/agents/upstream/refresh` checks GitHub HEAD (offline-safe, bounded).
  HALO/DarkMoon stay honestly `unverified` — no URL invented.
- Council `discover()` and install proposals now carry upstream metadata;
  Agents view renders repository links and sync state.
- New suite `tests/test_gguf_fuzzy.py` (32 tests) and operator guide
  `docs/LOCAL_GGUF.md`.

## 0.2.22 — 2026-09-07

Final hardening pass after the 0.2.21 network/auth/privilege work. Remaining
review findings are closed so the tree is consistent at every layer.

- `make preview` binds `127.0.0.1` like `npm run preview`. Non-loopback binds
  still require a 32+ character capability token.
- Git adapters isolate user/system gitconfig (`GIT_CONFIG_GLOBAL=/dev/null`,
  `GIT_CONFIG_NOSYSTEM=1`), blank the invoked alias, and disable hooks,
  fsmonitor, replace refs, ssh/gpg helpers, LFS filters, and ext-diff/textconv.
- PTY live ring is 400 events / 4 MiB (persisted replay 800 events) so typical
  small terminal chunks have usable scrollback without unbounded memory.
- Privilege handoff documents the OS `sudo -v` timestamp window (~15 minutes)
  in the CLI prompt, SECURITY.md, and USER_GUIDE. VORTEX still never sees the
  password.
- Version identity is 0.2.22 / APK code 222 across sidecar, CLI, frontend,
  APK, and `.deb`.

## Unreleased — 2026-09-06

Local AI lifecycle: **Install Ollama** and a **model download manager** join the
loopback-only advisory routing, plus terminal/AI-latency work and the removal of
the decorative rain background.

- The falling-rain canvas, its renderer, timers, CSS keyframes/surfaces, and the
  `matrix` settings default are **removed completely** (no replacement animation).
- New **Models view** (`frontend/models.js`): runtime status, INSTALL/START/STOP,
  curated model pool with RECOMMENDED/OPTIONAL badges, per-model
  DOWNLOAD/RETRY/CANCEL/REMOVE + progress, an active-downloads strip, and a custom
  `model:tag` pull input.
- New `backend/models/manager.py` owns the operator-facing lifecycle: a
  **user-space, checksum-verified, loopback-only** Ollama install (no root, no
  `curl | sh`) with a full `preparing → downloading → verifying → installing →
  completed` state machine, post-install executable/API verification, storage
  gating, and classified failures (`permission`/`storage`/`network`); plus
  pull/cancel/remove with shell-free argv, offline gating, explicit
  confirmation, honest byte progress + speed/ETA, and **post-pull verification**
  (a clean exit is never trusted without the model appearing on the loopback API).
- New routes: `GET /api/ollama`, `POST /api/ollama/install`,
  `POST /api/ollama/server/{start,stop}`, `POST /api/ollama/models/{pull,cancel,remove}`.
- Terminal streaming: PTY output is coalesced to one render per animation frame,
  session tabs/panes rebuild only on status change, and PTY resize is debounced
  to 160 ms.
- AI pipeline: plan-phase advisory is bounded to one primary model (≤6 s) and
  independent consultations run concurrently, removing the previous worst-case
  multi-model serialization during the conversation turn.
- **Secondary agent fallback**: when the primary local model (Ollama) cannot
  respond, the deterministic agent council is now composed as the honest
  secondary advisory layer (`compose_secondary_advisory`). Every agent is
  reported by its real installed/missing status and the only substantive text
  is the deterministic advisor's commentary — no model output is ever
  fabricated. The fallback is surfaced in both the plan and interpret phases,
  the turn explanation, and the task result.
- **Agents view now surfaces the local AI runtime + model pool**: the Agents
  view gains a `LOCAL AI · LOOPBACK ONLY` panel with the real **INSTALL
  OLLAMA / START SERVICE / STOP SERVICE** action and per-model **DOWNLOAD /
  REMOVE** buttons (a `MODELS →` link opens the full installer). Model
  downloads are gated until Ollama is installed and the service is running.
  Agent install proposals are clarified: the source repository is a clickable
  link and the window states plainly that VORTEX will not download or run
  third-party agent code (operator-installed, license-verified by the user).
- `backend/health.py` reports an actionable `diagnostics` step for Ollama
  (`install` / `start` / `pull` / `ok`).
- Fix: `POST /api/ollama/server/{start,stop}` returned the internal `_SERVER`
  dict (live `Popen` + log `deque`) through the JSON encoder and answered
  HTTP 500 even though the service actually started/stopped. Both routes now
  return a JSON-safe `_server_summary()`, and the captured stdout pipe is closed
  on stop (no per-cycle descriptor leak).
- Fix: the Models view double-escaped install-failure/download status text
  (TLS errors rendered as literal `&lt;…&gt;`); text is now escaped exactly once.
- Fix: the auto-replan follow-up passed `settings=` to `ExecutionManager.start`
  so follow-up operations keep their settings snapshot.

## 0.2.21 — 2026-08-29

Desktop twin of the mobile packaging flow: **DOWNLOAD .DEB** (Settings →
Desktop app) packages the live workbench as a real Linux `.deb` and downloads
it. Mirrors the verified APK flow end to end.

- New `backend/debbuild.py` orchestrates the reviewed
  `packaging/deb/build.sh` as the single source of truth. Every download
  rebuilds from the live tree first, so the package cannot lag behind the
  running workbench; a frontend digest is reported alongside size/sha256.
- Routes `GET/POST /api/desktop/deb` and `GET /api/desktop/deb/download`
  mirror `/api/mobile/apk*` and inherit the sidecar capability token gate.
- The layered download trigger (top-level tab → anchor fallback → manual
  toast link) is generalized into `triggerDownload()` and shared by the APK
  and `.deb` buttons, so both work in sandboxed iframe previews.
- The package gains a menu entry (`vortex serve`, `Terminal=true`) and an
  icon while shipping **no maintainer scripts, no daemon, no user data** —
  unchanged policy, now asserted by tests.
- `./vortex desktop deb [--output DIR]` is the CLI equivalent of the button.
- Honesty-first scope: the `.deb` is **unsigned** (signing stays a
  release-VM gate) and the Electron shell is still not bundled.
- Dependencies window rows no longer promise **INSTALL** for items with no
  reviewed installer mapping (lsusb, nft, third-party agents…). Those rows now
  say **REVIEW** and open the operator instructions; INSTALL is reserved for
  apt-mapped tools that produce a real typed plan. Found during live manual
  testing — policy unchanged, only the label stopped overpromising.
- Planner no longer misreads adjective phrases: "scan for open ports" is a
  read-only socket query (reviewed `ss -lntup` adapter), while "open port
  8080" remains a rejected firewall mutation. Also found during live manual
  testing.
- **Reports are fully interactive**: each card carries MD/HTML/JSON/PDF
  downloads, a **PREVIEW** modal showing the real markdown, and **DELETE**
  (`POST /api/reports/{id}/delete`) that removes only the derived report —
  history and the audit chain are untouched. **Renaming a conversation now
  renames its reports** so the two views stay identifiable together.
- **Next steps are one-click**: after execution the analysis card renders
  follow-ups as chips that start a new reviewed plan, instead of dead text.
- **Boot resilience**: a canvas failure (matrix rain) can no longer abort
  `init()` and kill every button on the page.
- Verified by an automated click-through audit (jsdom against the live
  sidecar): 15/15 checks — reports (links, preview, delete), tasks
  (restart/resume/delete firing real routes), conversations
  (rename/archive/delete/open), and dependency rows.
- **Analysis is verdict-first and quantitative.** Every finished operation now
  reports `VERDICT PASS/PARTIAL/FAIL` with passed/failed command counts, wall
  execution time, observed output lines and evidence bytes; each command in
  the timeline shows its exit code, duration, line and byte counts. The
  verdict block states plainly that PASS is an execution fact, not a security
  guarantee. Follow-up suggestions remain one click away in the same card.
- **One conversation, one report set.** The active conversation survives page
  reloads (localStorage); turns, follow-up chips, and edits continue the same
  thread until the operator taps NEW CONVERSATION. Reports are titled after
  their conversation (`"<conversation> · <task>"`) so one thread maps to one
  identifiable report set.

## 0.2.20 — 2026-08-29

Fix round for the mobile packaging flow: the DOWNLOAD APK control was
unreachable or silently dead in embedded previews. Both defects reproduced
before the fix and are covered by frontend regression tests.

- **DOWNLOAD APK now downloads in embedded previews.** The old trigger relied
  on a synthetic `link.click()`, which sandboxed iframes (web previews of the
  workbench) silently block — the sync toast appeared but no file arrived.
  The button now opens the download in a top-level tab first, keeps the
  classic anchor download for Electron and popup-blocked contexts, and the
  completion toast carries a real manual `vortex.apk` link as a last resort.
- **Topbar controls can no longer be clipped off-screen.** HELP and ABOUT
  moved from the topbar into the sidebar navigation (same windows, same
  wiring), and the topbar now wraps responsively instead of overflowing on
  narrow viewports. Previously DOWNLOAD APK and its neighbours were pushed
  past the right edge on screens below ~1300 px and could not be clicked.
- The APK packager already re-syncs the live `frontend/` on every build;
  version bumped to 0.2.20 / code 220 so freshly synced APKs are identifiable.

## 0.2.19 — 2026-08-28

- Host PATH scanner discovers Kali/Linux tools that were installed after VORTEX
  started, including binaries outside the builtin catalog. Newly seen names are
  marked `new_since_last_scan`. `GET /api/tools/host`, `POST /api/tools/host/rescan`,
  and `./vortex host-tools` expose the live inventory.
- Settings gain **host tool access**. When enabled, the planner and agent may
  propose typed argv for discovered tools. Guardian, engagement scope, denylist,
  and `shell=False` still apply. Interpreters cannot be passed `-c`/`-e` from
  natural language. Off by default.
- **DOWNLOAD APK** rebuilds a signed Android WebView client from the live
  frontend before the download starts. The phone talks to the same sidecar API
  as the desktop workbench. `./vortex mobile apk` is the CLI equivalent.
- MIT License is shown in Settings, `GET /api/license`, `LICENSES.md`, and
  inside the APK (`assets/LICENSE`).

## 0.2.18 — 2026-08-28

Audit round: four defects found by a full-repository review, each reproduced
before it was fixed and covered by a regression test. Test suite 141 → 153.

- Guardian resolves the engagement scope module under every supported import
  context. Previously the exclusion check could raise past its own loop in the
  package import context, so excluded targets were not checked. If the module
  still cannot be loaded, Guardian now blocks instead of continuing without an
  exclusion check.
- The engagement gate no longer keys off the planner's `kind` label. Guardian
  recomputes the requirement from typed command specs
  (`guardian.requires_engagement`), so a network-effecting command under an
  unrecognised plan kind cannot skip the gate. Local apt/systemd mutations stay
  outside the engagement gate and keep the root and fresh-preflight gates.
- Operations abandoned by a killed sidecar are reconciled at startup as
  `unknown_after_crash`, and the VTX tasks waiting on them move to `PAUSED`
  with a recovery note. Nothing is promoted to a success state on the basis of
  an unobserved outcome.
- Automatic replanning is bounded by a budget persisted on the task result:
  at most 2 follow-up iterations, and a follow-up that repeats a plan the task
  already executed is refused. The cap now survives the executor thread
  boundary and a sidecar restart; the stop reason is recorded as a
  `replan_stopped` task event.

## 0.2.17 — 2026-08-27

- Electron now uses a VORTEX-owned Linux title bar with working minimize,
  maximize/restore, close, drag, and double-click-to-maximize behavior. First-run,
  dependency, and terminal windows expose the same visible controls; closing the
  terminal panel preserves live PTY sessions.
- Aggregate tool, dependency, health, capability, sandbox, agent, and system-report
  inventories retain real paths, ownership/mode checks, and SHA-256 identity but
  no longer launch every installed third-party tool's version command. Individual
  command plans still probe versions by default.
- Scanner-builder tests now control the missing-wordlist fixture instead of
  assuming a Kali host has no reviewed `/usr/share` wordlist.

## 0.2.16 — 2026-08-27

- The Terminal view is a real Linux PTY surface: click the pane, type, paste.
  Keys go to the host shell via the sidecar. Cursor cell is marked in the
  renderer. Root-required plans show `sudo vortex --allow-root run <plan-id>`.

## 0.2.15 — 2026-08-27

- Ollama endpoints must be an exact loopback host (`127.0.0.1`, `localhost`,
  `::1`). Prefix matches such as `http://127.0.0.1.evil.test` and userinfo
  `http://127.0.0.1@host` are rejected.
- HTTP/planner requests longer than 8000 characters are 422. CLI `--yes` only
  supplies a plan token when `cli_yes` is JSON/bool true.

## 0.2.14 — 2026-08-27

- HTTP artifact analyze checks allowed roots before reading bytes, so `/etc`
  paths are rejected without being loaded. Missing out-of-scope paths do not
  leak existence.
- Plugin manifests that resolve outside `plugins/` are ignored. Electron IPC
  routes cannot contain `..`. Session `since` query values are length-capped.

## 0.2.13 — 2026-08-27

- Guardian treats only JSON/bool `True` as offline or auto-low-risk. A string
  `"true"` cannot auto-execute.
- Apt/systemd mutations no longer require a security engagement. Assessment
  and SSH still do. Preflight approval re-checks Guardian and exclusions.
- GET `q`/`id` query values longer than 200 characters are 422.

## 0.2.12 — 2026-08-26

- Guardian treats `chmod 0777` / `2777` / `a+rwx` as world-writable, not only
  the substring `chmod 777`.
- Execution re-evaluates Guardian and excluded targets; `/api/plan` cannot
  bypass exclusions. Invalid session `since` is 422, not silently replayed.
- Corrupt `VORTEX_MAX_SESSIONS` falls back to 8 instead of crashing the sidecar.

## 0.2.11 — 2026-08-26

- Operation and session finish threads no longer die on SQLite/disk I/O after
  the data directory is removed (test teardown or operator wipe). The observed
  command still ran; persistence failure is recorded as unknown_after_crash.

## 0.2.10 — 2026-08-26

- Assessment report downloads use the same md/html/json/pdf allowlist as
  system and task reports. Unknown formats are 422.

## 0.2.9 — 2026-08-26

- SEND fallback in `app.js` uses `/api/workspace/turn` (Guardian + council), not
  `/api/plan`. Workspace still overwrites `window.makePlan` when it loads.
- Report download formats are md/html/json/pdf only. Unknown GET formats are
  422 instead of 500.

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

## 0.2.21 (continued) — rename hardening

- Conversation **RENAME** and chat **EDIT & BRANCH** no longer use the native
  `prompt()` dialog, which sandboxed iframe previews block silently — they now
  open inline editors (SAVE/CANCEL, Enter/Esc, Ctrl+Enter for the branch box).
  Found while verifying rename during live manual testing; the API route and
  the report-title cascade were already correct.
