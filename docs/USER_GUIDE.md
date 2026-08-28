# VORTEX — install, test, and use

**Verified Orchestration, Reasoning, Testing, Execution & eXperience**

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
| Linux (Debian/Ubuntu/Kali recommended) | Only supported platform |
| Python 3.11+ | Core CLI and sidecar; **no pip packages required** |
| `git` | Clone the repository |
| Optional: Node 20+ + Electron | Desktop window |
| Optional: `nmap`, `curl`, `nuclei`, … | Security adapters (engagement required) |
| Optional: Docker/Podman, Ollama, agent CLIs | Probed; stay UNAVAILABLE if missing |

Installing VORTEX does **not** apt-install Kali tools, Docker, or agents.

## 2. Get the source

```bash
git clone https://github.com/mrtc-solutions/linux-vortex-terminal.git
cd linux-vortex-terminal
git checkout arena/01a048e3-linux-vortex-terminal
```

If you already have a clone:

```bash
git fetch origin
git checkout arena/01a048e3-linux-vortex-terminal
git pull --ff-only origin arena/01a048e3-linux-vortex-terminal
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
**not** install apt packages and never asks for a sudo password.

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

### Optional Debian package (unsigned 0.2)

```bash
# requires dpkg-deb on a Linux builder
VORTEX_VERSION=0.2.0 packaging/deb/build.sh
# then, as an administrator of that machine:
# sudo dpkg -i dist/deb/linux-vortex-terminal_0.2.0_all.deb
```

The package does not start a daemon, create user data, or install agents.

## 5. First-run health check

```bash
vortex doctor --json
vortex health --json
vortex tools
vortex agents --json
vortex deps --json
vortex sandbox --json
vortex db integrity
vortex audit verify
vortex host-tools --json
vortex mobile apk --sidecar-url http://127.0.0.1:8765/
```

Read the `state` fields. `absent` / `UNAVAILABLE` means the binary is not
on this host. That is expected in a minimal sandbox.

`vortex host-tools` walks only safe PATH directories and reports Kali-known
and newly installed binaries. Planning those tools still requires **Settings →
Host tool access** (off by default). Guardian, engagement scope, and
`shell=False` still apply.

`vortex mobile apk` rebuilds a signed Android client from the live frontend
before writing the APK. In the UI, **DOWNLOAD APK** does the same sync-then-
download. The phone talks to this sidecar over the same HTTP API as the
desktop workbench.

VORTEX is MIT-licensed (`LICENSE`, `GET /api/license`, Settings → License).

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
```

Preview bind (Arena / shared lab preview only):

```bash
npm run preview
# or
python3 backend/vortex_backend.py --host 0.0.0.0 --port 4173
```

In the UI:

1. Complete first-run checks (optional components stay unavailable).
2. Type a request such as `system health` and press **SEND**.
3. Review the typed argv, risk, and Guardian decision.
4. Click **APPROVE & EXECUTE** unless policy auto-ran a low-risk local command.
5. Read **observed** stdout in the live output pane. That is host output.
6. Open **Dependencies** for missing tools. **INSTALL** builds an apt *plan*
   or an operator proposal. VORTEX never silent-installs.

## 8. Optional desktop window (Electron)

```bash
npm install
npm start
```

Electron starts the Python sidecar on `127.0.0.1` with a random capability
token. The renderer cannot spawn processes.

The VORTEX title bar provides minimize, maximize/restore, and close controls on
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
`/usr/share/wordlists/dirb/common.txt`. If no wordlist exists, VORTEX does
not invent one.

`sqlmap` and `msfconsole` are catalogued and probed only. There is no
execution adapter.

## 10. Kali vs this sandbox

Installing VORTEX on Kali does **not** install the rest of Kali. Kali
already has many tools; VORTEX only probes `PATH` and uses what is present.

In this Arena sandbox: Debian 12, no Docker/Podman, no Ollama, no third-party
agent CLIs, typically no nmap. Local Linux adapters (whoami, df, ss, git,
systemd inspect, os-release, lscpu, …) work because those binaries exist.

## 11. If VORTEX restarts mid-operation

A command runs in a process owned by one sidecar. If that sidecar is killed
(crash, `Ctrl+C`, reboot) while an operation is in flight, VORTEX cannot know
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

When an observed result does not meet the objective, VORTEX may propose one
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

STOP ALL in the UI (or cancel from the CLI) interrupts VORTEX-owned process
groups. It does not kill unrelated user processes.

The path to “installed tools ⇒ real execution, nothing fabricated” is
`docs/READY_WHEN_TOOLS_EXIST.md`.

## 14. What is not claimed

- Third-party agent consult APIs (CAI, Strix, Nebula, …) — discovery only
- Docker sandbox **execution** when no runtime is installed
- Cloud model inference
- Silent package or agent installation
- Signed 1.0 `.deb` / unrestricted LLM OS control

Those stay honest UNAVAILABLE / REQUIRES CONFIGURATION states.
