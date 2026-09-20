# Changelog

## Unreleased

- **Fix: `PolicyError` in CLI now returns exit 4 (`policy_denied`).** When
  Guardian blocked a plan, executable identity mismatched, or scope authorization
  was denied, the CLI previously fell into generic `except Exception` and exited
  with 1 (`failure`) despite `docs/EXIT_CODES.md` specifying exit 4 for policy,
  scope, identity, or authorization denials. `cli/vortex.py` now catches
  `PolicyError` explicitly and returns `EXIT_CODES['policy_denied']` (4).
- **Security: Guardian destructive command coverage expanded.** Added
  `unlink`, `truncate`, `mkswap`, and `find -delete` to Guardian's destructive
  command detection, preventing destructive deletion or truncation via direct or
  planned execution. File arguments with extensions (e.g. `unlink.log`,
  `truncate.txt`) remain non-destructive and unblocked.
- **Fix: Planner and systemd parser safely handle newlines and shell syntax.**
  `parse_systemd_mutation` previously raised `PolicyError("systemd request contains unsafe shell syntax")`
  on any input containing newlines before checking whether the request was even
  a systemd mutation. Now non-systemd requests with newlines or compound shell
  syntax are cleanly classified as `unsupported_shell_syntax` by `build_plan`.
- **Fix: a concurrent `vortex` CLI marked the sidecar's live operation as
  crashed — and could kill it.** The sidecar and every CLI process share one
  SQLite store, but `ExecutionManager.__init__` reconciled *every*
  `started`/`running` row to `unknown_after_crash` on the assumption that it
  was the only execution authority. Reproduced on a real host: process A ran
  an approved `sleep 25`; a `vortex run -- true` started 1.5 s later flipped
  A's row to `unknown_after_crash` with a false `sidecar_restart` reason and
  a permanent `operations_reconciled_after_restart` audit event; A's waiting
  CLI then returned exit 6 ("the sidecar stopped before this operation
  reached a terminal state") and its shutdown killed the still-running
  command. Operations now carry the owning process identity (`authority`:
  pid + kernel start time), and reconciliation closes only rows whose owner
  is dead, a zombie, recycled, or unrecorded. Same scenario after the fix:
  A stays `running`, finishes `succeeded`, exit 0, no false audit event.
  Regression tests cover live owner (same process and another process),
  owner death, pid reuse, malformed identities, and legacy rows.
- **Fix: `vortex … | head` printed a `BrokenPipeError` traceback.** The CLI
  now exits quietly with the `interrupted` code when the reader closes the
  pipe early; regression test drives real subprocesses with a closed reader.
- **Docs match the shipped code again.** README/STATUS still said remote
  graphical sessions were "not implemented" and that "no session code
  exists" although the VNC/RFB remote desktop (bridge, UI window, real-VNC
  CI gate) shipped in 0.3.0; the feature table, the not-claimed list, the
  test-suite counts (636 Python tests, 10 JS suites), the STATUS version
  header, the crash-recovery ADR, and the `schema_version` contract wording
  in `docs/EXIT_CODES.md` are corrected.
- **Fix: published APT repositories were unreadable to apt.** `make-repo.sh`
  staged the tree with `mktemp -d` and published it as-is, so the repository
  root was mode 0700. apt runs its acquire methods as the unprivileged
  `_apt` user, so on a real Debian 12 host every `sudo apt update` after
  `install-repo.sh` failed with `Permission denied` and `sudo apt install
  linux-vortex-terminal` (and every later upgrade) could not resolve the
  package — the unprivileged test suite never sandboxes to `_apt`, which is
  why it stayed green. The repository is now published 0755/0644 (installer
  0755) with every mode set explicitly; `build_repo()` verification enforces
  the invariant; `install-repo.sh` checks, before writing anything, that
  `_apt` can traverse the repository and every parent directory (Debian
  12+/Ubuntu private home directories are the common trap) and names the
  blocking path with a copy-to-`/srv/vortex-apt` fix; and it refreshes the
  Vortex source on its own before the full `apt update`, restoring the
  previous registration state when apt cannot read the new repository so a
  broken source never lingers. Proven end to end on a real Debian 12 host
  with `sudo`: register → `apt install` → publish a newer version →
  `apt upgrade` → damage files → `apt install --reinstall` → `apt remove`.
  Seven new regression tests (`tests/test_apt_repo.py`) fail against the
  previous scripts and pass now; docs (`README.md`, `packaging/README.md`,
  `docs/USER_GUIDE.md`, `NEXT-STEPS.txt`) show the world-readable copy step.
- **Install, upgrade, and repair by APT package name.** New
  `packaging/deb/make-repo.sh` builds a deterministic APT repository from
  one or more `.deb` files (pool, per-architecture indexes, hashed Release,
  optional GPG signing with an exported key), new
  `packaging/deb/install-repo.sh` registers it on a target machine as a
  DEB822 source with `Signed-By` (unsigned repos are refused unless
  `--trust-unsigned` is passed explicitly for local testing), and
  `vortex desktop repo` orchestrates the flow from the app with the same
  verify-before-publish discipline as the `.deb` builder (hash
  re-verification of every index and payload, rebuilds require `--replace`,
  failed rebuilds preserve the last verified repo). `sudo apt install
  linux-vortex-terminal` now resolves by name; a repository carrying
  several versions resolves to the newest, and because the package ships no
  maintainer scripts and no conffiles, upgrades and `--reinstall` repairs
  cleanly replace every installed file. The `.deb` now carries a `Homepage`
  field, derives its default version from `APP_VERSION` (as does
  `vortex --version`), and ships the repo tooling under
  `/usr/share/vortex/packaging/deb/`. New `tests/test_apt_repo.py` (25
  tests) proves the flow with real `apt-get`/`apt-cache` resolution, a
  boot-and-serve smoke test of the extracted payload, and
  tamper/replace/refusal cases.
- **APT hardening round.** The `.deb` now Depends on `python3 (>= 3.10)`
  (Ubuntu 22.04 unblocked; shipped code is grammar-gated and API-swept for
  3.10 so the floor cannot silently rot) and carries `Installed-Size`;
  `make-repo.sh` rejects pool filenames with whitespace and accepts a
  `VORTEX_GPG` signer override; `install-repo.sh` requires complete armor
  (BEGIN + END), verifies the suite/component of local repositories, and
  refuses system roots unprivileged; `build_repo()` resolves symlinks and
  containment strictly, validates outputs before locking, and trusts `gpg`
  before staging. `tests/test_apt_repo.py` grows to 38 tests: stub-gpg
  signing plumbing and failure atomicity, `--key-url` download over local
  HTTP, real `apt-get -s` upgrade (`[0.2.0] (0.3.0)`) and repair
  (`[0.3.0] (0.3.0)`) simulations, and output/suite/component refusal cases.
- **Real-transaction round.** `tests/test_apt_repo.py` (48 tests) now drives
  genuine `dpkg --install/--status/--remove` transactions in an unprivileged
  `--root`: clean configure with no recorded scripts/conffiles, upgrade
  from 0.2.0 restoring a deliberately damaged file to packaged bytes, and
  removal leaving no packaged files. `vortex serve` rebinds past TIME_WAIT,
  names the address plus the way out on port conflicts (both entry points),
  and both launchers pin `python3 -X utf8` so C-locale machines cannot crash
  non-ASCII output (proven with a hostile-locale run that fails without the
  flag). The sidecar also boots and serves with an empty PATH, repo
  registration is idempotent, `install-repo.sh` checks for apt-get before
  writing, and the docs cover atomic publishing plus uninstall.
- **Self-contained repo round.** `make-repo.sh` now ships `install-repo.sh`
  (byte-identical, executable) plus a generated `NEXT-STEPS.txt` inside every
  repository, so one copied directory is everything the target machine needs;
  publishing without the installer alongside is refused. `build_repo()`
  requires the executable installer during verification and reports it, the
  man page documents `desktop deb/repo`, all three shell completions list
  `desktop` with `deb`/`repo` actions (bash completion executes for real in
  tests), and the flow is proven end to end: copy tree → run its own
  installer from `.` → real `apt update` → candidate by name. Also covered:
  first-run `doctor` from the installed payload, `desktop --help`, and a
  0.3.0→0.4.0 upgrade simulation proving newest-pick is not version-specific
  (suite is now 627 Python + 10 JS).

- **`npm start` survives low-memory hosts.** The launcher now rebuilds
  `dist/` only when it is missing or older than the sources (`--rebuild`
  forces, `--no-build` skips), sizes the build heap from free RAM without
  overriding an explicit `NODE_OPTIONS`, warns when free memory is too low
  to compile, and tells an OOM-`Killed` build apart from a real compile
  error — continuing into the app on the last good bundle after a kill
  instead of stranding the operator. Freshness is tracked by a build
  manifest (`dist/.vortex-build.json`, written by the new `npm run build`
  wrapper): added/removed sources invalidate by set difference rather than
  by directory mtimes, which some filesystems quantize too coarsely to
  trust, and `package.json` is fingerprinted by dependency content so
  script-only edits never force a rebuild. New `npm run start:no-build`
  alias and `tests/test_start.js` pin the flag parsing, freshness check,
  heap cap, and OOM diagnosis (suite is now 568 Python + 10 JS).
  `npm run preview` shares the same incremental check and, unlike the old
  unconditional pre-build, still serves (legacy UI fallback) when a rebuild
  cannot run.
- **Leaner production build.** `vite.config.ts` disables sourcemaps and the
  gzip-size pass the singlefile bundle never needed, cutting build time and
  peak memory on small Kali VMs.
- **Cheaper background effects.** The matrix rain canvas pauses when the tab
  is hidden or the window blurs, rebuilds its columns on resize (maximizing
  used to leave the right side dry), hoists per-frame style work out of the
  loop, and degrades from ~30fps to ~20fps under software rendering instead
  of stacking frames. Rain/CRT toggles now persist across restarts and the
  rain defaults off when the OS prefers reduced motion.
- **Prompt-bar scrollbar fix.** `QuickPromptBar` referenced a `no-scrollbar`
  utility that did not exist; it is now defined, so the chip bar no longer
  shows a scroll rail.
- **Agent Mode (v1).** Goal-directed runs with a visible transcript:
  think → plan → Guardian → execute → observe, looping until the goal is
  verified or a budget stops the run. Thinking rides the local stack
  llamafile-first with GGUF/Ollama fallback; every proposal is grounded
  through deterministic planning (model text never becomes shell);
  Guardian-`auto` steps run while anything else pauses for exact-step
  approval; one run at a time with step/time budgets, a stable
  repeat-guard, stop/resume, SSE transcript streaming, and an honest
  `needs_model` refusal pointing at the Models view when no local model
  is healthy. New sidecar routes `/api/agent/*`, Agent Mode surface
  window, `docs/AGENT_MODE.md`, and 13 tests including real-execution
  achieve/approve/stop/loop-guard and live-HTTP coverage.


- **Installable Android APK.** The hand-written `AndroidManifest.xml`
  encoder described every start-tag with a short `ResXMLTree_attrExt`
  (attribute count read back as zero), so no device could parse the
  manifest; it now emits the full six-field header per the AOSP layout.
  The DEX writer also indexed `MainActivity.onCreate` as a diff of 1
  instead of its absolute method id 11, which fails ART verification;
  both are pinned by independent structural decoders written against
  the platform specs, stash-proven to fail pre-fix.
- **Packaged builds ship the whole frontend.** `aiops.js` is referenced
  by `index.html` but was missing from the `.deb` file list and the APK
  payload, so the AI OPS window 404'd outside a checkout; both shippers
  now carry it, and the packaging tests assert every `/assets/` reference
  ships instead of pinning two files.
- **GGUF engine honesty.** The optional Python inference path no longer
  converts engine errors into timeouts, bounds its wait with a real
  timeout that detaches orphans, and serializes single-slot inference
  under a lock with a handle-identity recheck.
- **llamafile loopback hardening.** Advisory `probe`/`chat` bypass an
  inherited proxy for loopback servers, and concurrent `start` calls
  share one in-flight launch instead of racing.
- **Smaller pass-7 fixes.** Host scan rejects unbalanced quotes with a
  clarification instead of raising; dependency guidance points at the
  verified Models-view install/pull routes; the Ollama guide pulls the
  curated catalog tags; `target_endpoint` never raises on malformed
  input; the lint gate syntax-checks `aiops.js`.
- **llamafile advisory that always reaches the server.** An operator-configured
  loopback llamafile server now serves advisory through the model it actually
  serves even when no model file is registered locally, and `server_state`,
  `server_start`, and `chat` resolve saved settings from partial call-site
  dicts. Proven end-to-end against a live loopback server (`responded` via
  `llamafile`) with two new regression tests.
- **About popup (app + downloads + license).** New `about` command, Launcher
  tile, and Help row opening live version/sidecar state, the full MIT license
  text, Android APK sync/download with size and SHA-256, Linux DEB
  build/download, and an honest no-iOS note (Apple signing cannot be produced
  or verified on Linux).
- **Honest timeouts.** The React API client now reports `timeout` (with the
  elapsed budget and a retry hint) instead of mislabeling slow answers as
  `network` / "Sidecar unreachable".
- **Models download progress.** llamafile installs show MB received/total,
  percent, and a progress bar while the existing 3s poll runs.
- **Electron allowlist.** Desktop `security.js` now permits the real GET
  routes the shell calls (`artifacts`, `capabilities`, `license`,
  `reports/system`, `mobile/apk`, `desktop/deb`, `tasks/:id`,
  `tasks/:id/events`) plus the system-report download; `test_windows.js`
  asserts each, including method-mismatch denials.
- **Product naming.** User-visible surfaces now say "Vortex Terminal"
  (all-caps VORTEX TERMINAL only for the header wordmark and window titles);
  the APK label, report titles, agent name, and backend messages match.
- **Desktop + token auth for the React shell.** API calls ride Electron IPC
  (`window.vortexApi`) when hosted in the desktop app, with an IPC timeout
  race; token-protected sidecars get a one-shot `#vortex-token=PASTE`
  cookie bootstrap, and 401s explain exactly how to authenticate. Closed
  four IPC allowlist gaps the shell needs (`plan`, operation
  cancel/complete-task, artifact analysis, assessment reads).
- **Mutation preflight review.** Operations that pause in
  `awaiting_confirmation` now open a second explicit CONFIRM MUTATION step
  (preflight digest + next command shown); leaving it paused is honest too.
- **Task ledger cancel.** Tasks bound to a live operation offer Cancel op;
  removed the dead `approveOperation`/`completeOperationTask` client exports.
- **Reconnect prefers your shell.** The Host Shell popup re-attaches to its
  own PTY session instead of grabbing whichever session lists first.
- **Dev ergonomics.** Vite dev/preview listen on all interfaces, accept
  preview hosts, and proxy `/api` to a local sidecar on 8765.

## 0.3.0 — 2026-09-13

New default UI shell (React terminal, served at `/`), free local LLM via
llamafile, and the full popup workspace. No simulation: every surface reads
the loopback sidecar and degrades to an honest empty/unavailable state.

- **React terminal shell.** Six tabs (Terminal, Tactical Map, /out, Reports,
  Fuzzy, Agent Reach) plus pop-up windows (plan approvals, tasks, scope,
  tools, models, system, conversations, memory, settings, AI Ops, help,
  raw host PTY, start-menu launcher). Terminal turns run plan → Guardian →
  execute → observe with live SSE output; WAITING plans open a real
  approve/reject review. Served automatically once `npm run build` produces
  `dist/`; `VORTEX_UI=legacy` forces the vanilla workbench.
- **llamafile provider.** Pinned single-binary local LLM (v0.10.5,
  SHA-256 verified), operator-confirmed install, loopback-only server,
  GGUF/fused-model import, start/stop/activate/remove. Router order is now
  llamafile → GGUF-direct → Ollama → agent council → deterministic core,
  with per-call latency feedback and honest unavailable states.
- **Real tabs.** Tactical Map renders the observed asset graph; /out shows
  stored artifacts with observations and re-analysis; Reports browses,
  downloads (md/html/json/pdf), and deletes sidecar reports plus live system
  and per-engagement assessments; Fuzzy shows the live router ranking with
  membership traces; Agent Reach shows the real roster and capabilities.
- **Policy settings UI.** Profile selector (safe/standard/expert) with the
  derived `auto_low_risk` flag shown honestly; `auto_medium_risk` stays a
  Guardian invariant (always off).
- **Dropped from the UI** (backend/CLI unchanged): the React demo's staged
  network map, fake model cluster, in-memory filesystem, and canned
  deliberations. The vanilla `frontend/` workbench remains as the legacy
  fallback and is still covered by the JS suites.

## 0.2.23 — 2026-09-12

Windowed workspace, global REFRESH ALL, visible local-AI trace, the
model-discovery fix, and a roster that shows only working advisors.
On-device GGUF primary, fuzzy provider routing, and per-function AI
assistance all ship here. No simulation: every new surface degrades to an
honest unavailable state when its files, engine, or network are absent.

- **Windowed workspace redesign.** The main screen now keeps only the chat
  and plan/evidence columns; System health, Tasks, AI Ops, and Models open as
  pop-up surface windows with maximize/minimize/close controls, a raised
  z-order manager, and a restore tray for minimized windows
  (`frontend/windows.js`, `frontend/styles.css`).
- **Global REFRESH ALL.** New `POST /api/refresh` forces one fresh re-probe
  of every subsystem — agents, tool registry, host tools, GGUF model
  directory, Ollama runtime, and dependencies — and returns a single
  summary with per-section counts and `elapsed_ms`. The header button toasts
  what was re-checked and the HUD counters update from the same payload.
- **Model discovery fix.** `GET /api/ollama?fresh=1` now invalidates the
  GGUF scan cache and the router status cache, so a file dropped into
  `~/linux-vortex-terminal/models` appears on the next refresh instead of
  waiting out the scan TTL; REFRESH ALL performs the same invalidation.
- **AI Ops trace window.** Step-by-step local-AI pipeline per turn: provider
  selected, per-provider latency, fuzzy match, synthesis, and guardian
  outcome — plus the live provider ranking (`routing` on `/api/ollama`).
  When an AI assistant, Ollama, or the GGUF engine is unavailable, the
  window shows the exact commands to run in the main Linux terminal
  (upstream install guides, Ollama install flow, or drop-the-GGUF-file
  steps) — never a silent install.
- **One-paste install block.** New `GET /api/install/commands` aggregates the
  verified commands for every layer actually missing on the host (Ollama
  runtime, GGUF engine, GGUF model files) into a single copy-paste block with
  COPY ALL / OPEN IN TERMINAL in the AI Ops window. Paste-safe by
  construction: prose and any line with backticks/substitutions/redirects is
  demoted to a comment, so pasting never runs an unexpected command.
- **Advisor roster trimmed to what works.** The nine third-party agent
  adapters that could not connect (advisory health-check stubs, none ever
  executed) were removed from the app — no trace left in backend, frontend,
  tests, docs, or NOTICE. The council now ships only the built-in
  `vortex-local` advisor; the roster, dependencies view, and install block
  all reflect that, and nothing unavailable is listed.
- **Preview support.** `--allow-frame-host` lets an operator name a preview
  proxy host that may embed the app (CSP `frame-ancestors` names the exact
  origin); default remains frame-locked.
- **Cleanup.** Removed the nine root-level plan/history markdown files and
  dead code/unused CSS (stale `makePlan` in `app.js`, superseded
  context-column styles); the test suite is now 442 Python + 8 JS.

### Also in this release

- **Fixed fresh-clone desktop bootstrap** (`npm install` / `npm start`).
  Electron 44+ no longer downloads its ~110 MB platform binary at install
  time; the deferred first-start download crashed with `fetch failed` /
  "Electron failed to install correctly" on any host unable to reach GitHub
  release assets. New `scripts/ensure-electron.js` postinstall fetches the
  binary up front, retries through known mirrors (npmmirror, huaweicloud)
  with stale `.npmrc` mirror config stripped for fallback attempts, verifies
  `dist/version` + executable afterwards, honors
  `ELECTRON_OVERRIDE_DIST_PATH`, and prints exact remediation instead of
  failing silently. Best-effort at install so lint/test/preview keep
  working; `npm start` (`scripts/start.js`) guarantees the binary before
  launch, warns on headless hosts (`xvfb-run -a npm start`), forwards args,
  and propagates exit codes. Raw entry kept as `npm run start:electron`;
  `npm run preview` remains the zero-Electron browser fallback. `engines`
  corrected to Node >=22.12.0 (electron@44's real requirement).

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
- **Advisor upstream metadata** (`backend/agents/upstream.py`): the
  built-in advisor carries its upstream record; `POST
  /api/agents/upstream/refresh` stays offline-safe and bounded (no
  GitHub-backed advisor is tracked, so it never dials the network).
- New suite `tests/test_gguf_fuzzy.py` and operator guide
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
  in the CLI prompt, SECURITY.md, and USER_GUIDE. Vortex Terminal still never sees the
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
  link and the window states plainly that Vortex Terminal will not download or run
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

- Host PATH scanner discovers Kali/Linux tools that were installed after Vortex Terminal
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

- Electron now uses a Vortex Terminal-owned Linux title bar with working minimize,
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
- HTTP backups must land inside the Vortex Terminal data directory.
- Safe profile always confirms: settings cannot enable auto-run, medium auto,
  root, or a non-loopback Ollama endpoint.

## 0.2.2 — 2026-08-26

- Unknown, closed, or expired engagement IDs cannot plan outbound work and
  are not bound onto local diagnostics.
- Guardian matches `mkfs.ext4`-style destructive stems. HTTP artifact analyze
  stays inside the Vortex Terminal data directory. Wordlists must live under `/usr/share`
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
