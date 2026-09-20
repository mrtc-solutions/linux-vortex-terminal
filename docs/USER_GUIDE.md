# Vortex Terminal — install, test, and use

**Verified Orchestration, Reasoning, Testing, Execution & eXperience**
(VORTEX for short)

This is a real Linux application. Every command you approve is executed as
typed argv (`shell=False`) on the host. Missing tools, agents, Docker, and
models are reported as unavailable. Nothing is fabricated to look complete.

> **Authorized use only.** Assess systems you own or have written permission
> to test.

This Arena session cannot merge the working branch into `main`. Use the
checkout below on your own machine, or merge the pull request from GitHub
when you are ready.

## 1. What you need

| Requirement | Why |
|---|---|
| Linux: Debian 12+, Ubuntu 22.04+, Mint 21+, Kali rolling | Only supported platforms (Python 3.10+) |
| Python 3.11+ | Core CLI and sidecar; **no pip packages required** |
| `git` | Clone the repository |
| Optional: Node 20+ + Electron | Desktop window |
| Optional: `nmap`, `curl`, `nuclei`, … | Security adapters (engagement required) |
| Optional: Docker/Podman, Ollama, agent CLIs | Probed; stay UNAVAILABLE if missing |

Installing Vortex Terminal does **not** apt-install Kali tools, Docker, or agents.

## 2. Get the source

```bash
git clone https://github.com/mrtc-solutions/linux-vortex-terminal.git
cd linux-vortex-terminal
git checkout arena/01a06dc4-linux-vortex-terminal
```

If you already have a clone:

```bash
git fetch origin
git checkout arena/01a06dc4-linux-vortex-terminal
git pull --ff-only origin arena/01a06dc4-linux-vortex-terminal
```

## 3. Verify the build (recommended first)

No virtualenv is required.

```bash
python3 -m compileall -q backend cli
python3 -m unittest discover -s tests -q
node --check frontend/app.js
node --check frontend/workspace.js
node tests/test_terminal.js
```

Or:

```bash
make lint
make test
# if Node is installed:
npm test
npm run lint
```

All Python tests must print `OK`. The terminal emulator prints `PASS`.

## 4. Install as a real user-local app (no root)

This writes `~/.local/bin/vortex` pointing at this source tree. It does
**not** install apt packages and never asks for a sudo password. Reviewed
package installs stay separate: Vortex Terminal builds a plan first, opens it in a
managed installation PTY, performs a fresh preflight, and lets the operating
system authenticate only the final typed mutation. Do not launch Vortex Terminal itself
with `sudo`.

```bash
./vortex install --user --json
# or
bash scripts/install-user.sh
```

Then:

```bash
export PATH="$HOME/.local/bin:$PATH"
hash -r
vortex --version
vortex --help
```

To uninstall the launcher only:

```bash
rm -f ~/.local/bin/vortex
```

Local data stays in `$XDG_DATA_HOME/vortex` (usually `~/.local/share/vortex`).
Remove that directory if you also want history, tasks, and the audit DB gone.

### Optional Debian package (unsigned)

```bash
# requires dpkg-deb on a Linux builder (version defaults to APP_VERSION)
packaging/deb/build.sh
# then, as an administrator of that machine:
# sudo apt install ./dist/deb/linux-vortex-terminal_<version>_all.deb
```

The package does not start a daemon, create user data, or install agents.
It ships no maintainer scripts and no conffiles, so a newer version
cleanly replaces every installed file on upgrade or
`sudo apt install --reinstall`.

### Optional APT repository (install by name)

```bash
# 1. Build the package, then the repository (refuses to overwrite; --replace rebuilds).
vortex desktop deb
vortex desktop repo
# 2. Copy the repo directory to the target machine, or serve it over https.
# 3. On the target machine, as root (signed by default; --trust-unsigned is
#    for a local repo you built yourself):
sudo packaging/deb/install-repo.sh --repo-url https://<host>/vortex --key <copied-dir>/vortex-archive-key.asc
# (on an installed machine the script is at
# /usr/share/vortex/packaging/deb/install-repo.sh)
# 4. Install, upgrade, and repair by package name.
sudo apt install linux-vortex-terminal
sudo apt upgrade linux-vortex-terminal
```

A repository carrying several versions resolves to the newest one. See
`packaging/README.md` for the full flow, including the `make-repo.sh` /
`install-repo.sh` shell equivalents and the `--sign` release path.

## 5. First-run health check

```bash
vortex doctor --json
vortex health --json
vortex tools
vortex agents --json
vortex deps --json
vortex model status --json
vortex sandbox --json
vortex db integrity
vortex audit verify
vortex host-tools --json
vortex mobile apk --sidecar-url http://127.0.0.1:8765/
```

Read the `state` fields. `absent` / `UNAVAILABLE` means the binary is not
on this host. `blocked` or a component `warning` means Vortex Terminal found the tool
but refused to silently trust the path because of path-safety policy; reinstall
is not automatically required. That is expected in some sandboxes and custom
`/usr/local/bin` setups.

`vortex host-tools` walks only safe PATH directories and reports Kali-known
and newly installed binaries. Planning those tools still requires **Settings →
Host tool access** (off by default). Guardian, engagement scope, and
`shell=False` still apply.

`vortex mobile apk` rebuilds a signed Android client from the live frontend
before writing the APK. In the UI, **DOWNLOAD APK** does the same sync-then-
download. The phone talks to this sidecar over the same HTTP API as the
desktop workbench.

Vortex Terminal is MIT-licensed (`LICENSE`, `GET /api/license`, Settings → License).

### Optional local AI (on-device GGUF first, Ollama loopback second)

Vortex Terminal is local-AI-first only in an **advisory** sense. Deterministic planning,
Guardian, and the typed executor remain authoritative.

- **Primary:** your own GGUF files in `~/linux-vortex-terminal/models/` —
  `Llama-3.2-3B-Instruct-Q4_K_M.gguf` (fast/conversation) and
  `Qwen2.5-3B-Instruct-Q4_K_M.gguf` (planner/analysis). Tuned for 8 GB RAM /
  ~2 GHz CPU (one resident model, 2048 ctx). See `docs/LOCAL_GGUF.md`.
- **Secondary:** Ollama loopback pool, default endpoint
  `http://127.0.0.1:11434` (clamped to loopback-only settings).
  Recommended pool: `phi4-mini:3.8b`, `qwen3:4b`, `llama3.2:3b`;
  optional specialist `gemma3:4b`.
- **Fallback:** fuzzy routing (GGUF → Ollama → agent council →
  deterministic core) demotes a delaying/failing primary automatically.
  Every function also carries a best-effort `ai_hint`.

Check live status:

```bash
vortex model status --json
vortex model test --json
vortex deps --json
vortex benchmark --json
```

If `runtime:ollama` or `data:ollama-models` is missing in Dependencies, Vortex Terminal
shows operator steps such as `ollama serve`, `ollama pull <model>`, and
`curl http://127.0.0.1:11434/api/version`. It does **not** run an upstream
installer, does **not** pull models for you, and does **not** send model traffic
outside loopback.

## 6. Use it from the terminal (no browser)

Plan only (nothing executes):

```bash
vortex plan "system health"
vortex plan "whoami"
vortex plan "check my disk space"
vortex plan "show listening ports"
vortex plan "what distro is this"
vortex plan "lscpu"
```

Workspace path (planner + Agent Council + Guardian; same as the UI SEND
button). Safe profile still waits for approval unless you pass `--yes`
**and** policy allows low-risk auto-run:

```bash
vortex --profile standard --yes turn "whoami"
```

Approve a planned command from the CLI:

```bash
vortex --yes "whoami"
```

`--yes` only skips the interactive prompt for a **policy-valid** plan. It
does not bypass Guardian.

## 7. Use the web workbench

Local-only (recommended on your machine):

```bash
vortex serve --bind-host 127.0.0.1 --bind-port 8765
# open http://127.0.0.1:8765/
# "cannot serve on …" means another copy is already running; stop it or
# pick a free port with --bind-port.
```

Preview bind (local loopback; `make preview` and `npm run preview` agree):

```bash
npm run preview
# or
make preview
# equivalent:
python3 backend/vortex_backend.py --host 127.0.0.1 --port 4173
```

A non-loopback bind (`0.0.0.0` or a LAN address) is refused unless you pass a
capability token of at least 32 characters (`--token` / `VORTEX_SIDECAR_TOKEN`).

The default shell is the Vortex Terminal React terminal (served automatically
once `npm run build` has produced `dist/`): six tabs — Terminal, Tactical Map,
/out, Reports, Fuzzy, Agent Reach — plus pop-up windows for plan approvals,
tasks, scope, tools, models, system, conversations, memory, settings, AI Ops,
help, about/downloads, and a raw host shell. Set `VORTEX_UI=legacy` to force
the previous vanilla workbench instead.

In the React shell:

1. Type a request such as `check disk usage` in the terminal and press **Run**.
2. Low-risk plans auto-run under your policy profile (Settings popup);
   everything else opens a **Guardian plan review** — APPROVE & EXECUTE or REJECT.
3. Watch real output stream in; **Stop** (STOP ALL) signals running work.
4. Type `launcher` (or press the grid button in the header) for every surface;
   `shell` opens a raw host PTY; `aiops` shows the last advisory trace;
   `about` shows the version, MIT license, and APK/DEB downloads.
5. Mutation plans pause a second time at a **preflight review** — CONFIRM
   MUTATION is a separate, explicit click; nothing auto-continues past it.
6. For free local AI, open **Models**: install llamafile (confirmed download),
   drop a `.gguf` file into `models/`, then start the loopback server.
7. If the sidecar was started with `--token`, open the shell once with
   `#vortex-token=PASTE` appended to the URL (token printed at startup);
   the shell exchanges it for a session cookie and strips it from the address bar.

In the legacy vanilla UI:

1. Complete first-run checks (optional components stay unavailable).
2. Type a request such as `system health` and press **SEND**.
3. Review the typed argv, risk, and Guardian decision.
4. Click **APPROVE & EXECUTE** unless policy auto-ran a low-risk local command.
5. Read **observed** stdout in the live output pane. That is host output.
6. Open **Dependencies** and type one exact Debian package, `ollama`, or a
   validated local `model:tag`. A package creates a reviewed apt plan; **OPEN
   INSTALL TERMINAL** preserves that exact plan while OS authentication stays
   outside Vortex Terminal. Ollama/model workflows show download, verification,
   cancellation, retry, rescan, and role-integration status. Vortex Terminal
   never silent-installs.
7. When local Ollama is healthy, the plan/result views show role-aware **Local
   AI** advisory output and explicit fallback attribution. That text never
   authorizes execution.

## 8. Optional desktop window (Electron)

Requires Node.js 22.12+ (Electron 44 requirement).

```bash
npm install
npm start
```

`npm install` also downloads the ~110 MB Electron platform binary from
GitHub release assets (Electron 44+ no longer bundles it; the project's
`postinstall` fetches it up front with mirror fallback). If every download
source is unreachable, install still succeeds but prints remediation — the
binary is fetched lazily on the next `npm start` once network policy allows
it. On networks that block GitHub release assets, use a mirror:

```bash
ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ \
ELECTRON_CUSTOM_DIR="{{ version }}" \
node scripts/ensure-electron.js --required
```

Headless host with no `$DISPLAY`: `xvfb-run -a npm start`, or skip Electron
entirely and test the identical workbench in a browser with
`npm run preview` (serves on `http://127.0.0.1:4173`). `npm run
start:electron` bypasses the wrapper and invokes Electron directly.

### Build says `Killed` on a small VM (out of memory, not a bug)

`transforming (...) src/main.tsx Killed` means the Linux OOM-killer shot the
compiler: the box had less than ~0.5 GB free while Vite ran. The code is
fine — the starter also sizes the build heap from free RAM and says so
explicitly. Fix one of:

1. Free RAM: close browser tabs and heavy apps, then check `free -h`.
2. Reuse the last good bundle instead of rebuilding: `npm run start:no-build`
   (an OOM-kill with an existing `dist/` now continues into the app
   automatically and says so).
3. Skip the desktop shell: `npm run preview` rebuilds only when `dist/` is
   stale and serves the legacy UI instead of failing when a build cannot run.
4. Give a 2 GB VM some headroom: add a 2 GB swapfile or raise its memory.
5. Build once with a small heap, then start without rebuilding:
   `NODE_OPTIONS=--max-old-space-size=768 npm run build && npm run start:no-build`.

A genuine compile error (TypeScript/JSX mistake) still cancels the launch and
points at the error in the build output above — that path is unchanged.

Electron starts the Python sidecar on `127.0.0.1` with a random capability
token. The renderer cannot spawn processes: every API call travels over
authenticated main-process IPC (route-allowlisted), while the shell bundle,
live streams, and package downloads ride direct renderer requests with an
injected token.

The Vortex Terminal title bar provides minimize, maximize/restore, and close controls on
Linux without depending on window-manager decorations. Drag the title bar to
move the app or double-click it to maximize/restore. Auto-opened first-run and
dependency dialogs have their own minimize, maximize/restore, and close controls.
The Terminal view has matching controls; closing that panel does not terminate a
live PTY (use **STOP** when you intend to terminate one).

## 9. Authorized assessment (engagements)

Active network tools need a declared engagement. Example:

```bash
vortex engagement create \
  --name "Lab assessment" \
  --authorization "ticket-123" \
  --target https://lab.example.test

# then, with that engagement id:
vortex --engagement-id <id> plan "curl https://lab.example.test"
```

In the UI: **Engagements → NEW ENGAGEMENT**, then send
`curl https://your-authorized-target`.

Reviewed security adapters (tool must be installed; otherwise UNAVAILABLE):

| Request contains | Adapter | Extra requirement |
|---|---|---|
| `nmap` | scoped nmap | engagement + target |
| `curl` / HTTP headers | curl | engagement + `http(s)://` URL |
| `nuclei` | nuclei | engagement + URL |
| `nikto` | nikto | engagement + URL |
| `amass` | amass passive | engagement + domain |
| `ffuf` / `gobuster` | content discovery | engagement + URL + existing host wordlist |

Wordlist: pass `wordlist /absolute/path` or have a standard Kali path such as
`/usr/share/wordlists/dirb/common.txt`. If no reviewed wordlist exists, Vortex Terminal
does not invent one; Dependencies can instead propose a reviewed apt plan for a
distro wordlist package such as `seclists`.

`sqlmap` and `msfconsole` are catalogued and probed only. There is no
execution adapter.

## 10. Kali vs this sandbox

Installing Vortex Terminal on Kali does **not** install the rest of Kali. Kali
already has many tools; Vortex Terminal only probes `PATH` and uses what is present.

In this Arena sandbox: Debian 12, no Docker/Podman, no default Ollama runtime,
typically no nmap. Local Linux adapters (whoami, df,
ss, git, systemd inspect, os-release, lscpu, …) work because those binaries
exist. On the audited host, `node`, `npm`, and `yarn` were discoverable under
`/usr/local/bin` but reported as blocked-by-review rather than trusted installs.

## 11. If Vortex Terminal restarts mid-operation

A command runs in a process owned by one sidecar. If that sidecar is killed
(crash, `Ctrl+C`, reboot) while an operation is in flight, Vortex Terminal cannot know
what the host actually did, so on the next start it says so instead of
guessing:

- the operation becomes `unknown_after_crash` with the reason `sidecar_restart`
- the VTX task that was waiting on it moves to `PAUSED` with a recovery note
- a `recovered_after_restart` task event is recorded

A task is never marked `COMPLETED` on the basis of an outcome nobody observed.
Inspect what happened, then resume or restart the task:

```bash
vortex tasks
vortex task show <task-id>
```

## 12. Automatic follow-ups are bounded

When an observed result does not meet the objective, Vortex Terminal may propose one
reviewed follow-up. That loop is capped: at most **2** follow-up iterations per
task, and a follow-up is refused if it repeats a plan the same task already
executed. Both the count and the executed plan digests are stored on the task,
so the cap survives a sidecar restart. When the loop stops you will see a
`replan_stopped` task event carrying the reason. Follow-ups are additionally
restricted to low-risk local diagnostics that Guardian auto-approves; a
follow-up never escalates into network or mutating work.

## 13. Data, privacy, and stop

| Item | Location |
|---|---|
| SQLite + audit chain | `$XDG_DATA_HOME/vortex/vortex.db` (mode 0600) |
| Config | `~/.config/vortex` |
| Runtime sidecar metadata | `$XDG_RUNTIME_DIR/vortex/sidecar.json` |

STOP ALL in the UI (or cancel from the CLI) interrupts Vortex Terminal-owned process
groups. It does not kill unrelated user processes.

The path to “installed tools ⇒ real execution, nothing fabricated” is
`docs/READY_WHEN_TOOLS_EXIST.md`.

## 14. Authorized remote desktops (VNC)

An engagement that covers a target can also carry a *graphical* session, opened
in its own window next to the local terminal. Nothing connects without an
explicit approval step, and a desktop window is only ever opened for an endpoint
that really answered.

1. Open the target's details and choose **Open remote desktop for …**, or use
   `Launcher → Remote Sessions`.
2. Press **Endpoint check**. If the host is only reachable over SSH, Vortex says
   *"Remote shell access is available, but no compatible graphical session has
   been verified."* and offers configuration guidance — it never fakes a desktop.
3. **Create the session**, tick the authorization confirmation, and approve it.
   Unencrypted RFB additionally requires the deployment opt-in and a protected
   path acknowledgement.
4. The window opens and renders the live remote framebuffer. Click the surface
   to send keyboard and mouse input; a banner shows while input is going to the
   remote device. Press **Escape twice** or **RELEASE KEYBOARD** to take control
   back; clicking elsewhere releases it automatically.
5. **RECONNECT** after a drop (authorization is re-checked), **DISCONNECT** to
   end the stream but keep the record, **CLOSE SESSION** to remove it, or
   **STOP ALL** to end everything.

Credentials are typed into the window, used once, and never stored. Clipboard
synchronization, file transfer, audio redirection, and shared folders are off;
screen contents and keystrokes are not recorded. Details, limits (concurrent
sessions, idle timeout), and the exact support matrix are in
[`REMOTE_DESKTOP.md`](REMOTE_DESKTOP.md).

## 15. What is not claimed

- Third-party AI agent code — none ships; only the built-in deterministic advisor is rostered
- Docker sandbox **execution** when no runtime is installed
- Cloud model inference
- Silent package or agent installation
- Signed 1.0 `.deb` / unrestricted LLM OS control

Those stay honest UNAVAILABLE / REQUIRES CONFIGURATION states.
