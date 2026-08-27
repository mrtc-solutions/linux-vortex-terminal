# Plan: real execution ready — only host tools remaining

**Product:** VORTEX (Verified Orchestration, Reasoning, Testing, Execution & eXperience)  
**Date:** 2026-08-27  
**Goal:** After this work, a Linux host you administer is **ready for real execution**. The only runtime gaps are **missing binaries / wordlists / Ollama**, not missing VORTEX code.

This is not a plan to become an unrestricted autonomous pentest platform. Guardian, engagements, typed argv, and no silent install stay binding.

## What we already told you (reviewed)

1. Installing VORTEX does **not** apt-install Kali tools, Docker, or agents.
2. **Dependencies → INSTALL** builds a **reviewed apt plan** or an **operator proposal**. It never silent-installs and never captures sudo.
3. With tools present, **reviewed adapters run for real** (nmap/curl/nuclei/nikto/amass/ffuf/gobuster, local Linux, apt/systemd).
4. Even with CLIs present, some paths stay **code-incomplete** today:
   - Third-party **agent consult** = REQUIRES CONFIGURATION (discovery only)
   - **sqlmap / msfconsole** = catalog probe, no argv adapter
   - **Docker sandbox execution** = probe only
   - **Ollama** = loopback probe only, no advisory inference
5. The suite can be 100% green. The **product** is not 100% of the master directive until the items below exist.

## Definition of done for this plan

On a Debian/Kali host **you administer**, after you install optional packages:

| If this is on PATH / loopback | VORTEX must |
|---|---|
| coreutils, iproute2, procps, git, ssh, systemd | Already: plan + execute after Guardian |
| `nmap`, `curl`, `nuclei`, `nikto`, `amass`, `ffuf`, `gobuster` + wordlist + engagement | Already: typed argv or honest UNAVAILABLE |
| `sqlmap` / `msfconsole` + engagement | **New:** bounded argv adapter, or stay catalog-only by explicit product decision |
| `docker` / `podman` | **New:** reviewed sandbox **run** of an allowlisted image, or stay inspect/logs only |
| Ollama on `127.0.0.1`/`localhost`/`::1` | **New:** advisory inference that cannot execute |
| Agent CLI (CAI, Strix, …) | **New:** non-interactive consult (observation in, text out) or stay REQUIRES CONFIGURATION |
| Apt tools + root/`--allow-root` | Already: preflight + second approval |

If a binary is absent, the UI/CLI still says **TOOL MISSING / UNAVAILABLE**. Never fabricate output.

## Already done (do not rebuild)

- One Python execution authority, `shell=False`, PTY, approval tokens, audit chain
- Workspace turn: intent → plan → council (data) → Guardian → execute
- Engagements, exclusions, closed/expired/unknown gates
- Fail-closed HTTP (typed JSON, report formats, backups, no `allow_root`)
- Apt INSTALL plans; agent INSTALL proposals
- User-local `vortex install --user` / `vortex serve` / `vortex turn`
- 115 Python tests + JS terminal emulator

## Must implement (code, not packages)

### Phase A — Finish “installed tool ⇒ real command”

These are the last **adapter holes**. Until they ship, installing the package is not enough.

1. **sqlmap adapter (optional, high-risk)**  
   - Bounded argv only (`--batch`, timeout, one scoped URL, no OS shell, no crawl explosion).  
   - Engagement + HTTP(S) URL required. Missing binary = UNAVAILABLE.  
   - **Product fork:** if we refuse exploitation-class tools in v1, keep the current honest UNAVAILABLE branch and document it as **unsupported**, not “coming when installed.”

2. **msfconsole adapter (optional, high-risk)**  
   - Same rule: reviewed non-interactive argv or **explicitly unsupported**.  
   - No resource scripts from untrusted output. No self-written exploits.

3. **Docker/Podman sandbox execution**  
   - New adapter: `linux.containers.sandbox`  
   - Allowlisted image digest or local image id only; `--network none` or engagement-scoped network; dropped caps; no `--privileged`; timeout; output cap.  
   - Inspect/logs stay as they are. Missing runtime = UNAVAILABLE.

4. **Ollama advisory inference**  
   - POST loopback `/api/chat` with observation JSON as **untrusted data**.  
   - Never add argv, never auto-execute, never leave loopback.  
   - Offline / bad host / timeout = disabled. Planner remains authority.

5. **Agent consult (one pattern, all nine CLIs)**  
   - If `health.healthy`: run a **reviewed non-interactive** argv (timeout, no TTY, stdin = observation JSON, stdout captured).  
   - If the CLI has no such mode: stay `requires_configuration` (honest).  
   - Output is council data only. Guardian still independent. Agents cannot approve.

### Phase B — Operator install path (so “inside the app” is complete on Linux)

6. **Apt INSTALL already plans.** Remaining: a clear UI/CLI path after approval:  
   `sudo vortex --allow-root run <plan-id>` printed on the plan card when privilege is `root-required`.  
   No password capture.

7. **Wordlists**  
   - If ffuf/gobuster is installed but no wordlist: INSTALL proposal for a distro wordlist package (`seclists` / `wordlists`) as apt plan, still operator-approved.  
   - Still reject `/etc/passwd` and world-writable lists.

8. **Ollama / agents**  
   - Keep proposal-only (upstream installers are not reviewed argv).  
   - After operator install, **Refresh** must flip state from missing → installed without restarting VORTEX.

### Phase C — Execution polish (optional for “tools remain,” required for 1.0)

9. Durable PTY attach across sidecar restarts (replay already exists; live fd does not).  
10. Signed `.deb` install/upgrade/uninstall on a disposable VM (release, not runtime).  
11. Disposable-VM apt/systemd mutation acceptance tests (no shared-host mutation).

## Will not implement (stay blocked even with every tool)

- Silent / unattended third-party install  
- Unrestricted LLM OS control  
- Plugin Python loading / code execution  
- FastAPI + PostgreSQL + pgvector (SQLite modular monolith is the product)  
- Cloud model send of terminal output by default  
- Auto-sudo or password capture  
- Agent or model self-approval  

These remaining as **blocked** is part of being ready, not a defect.

## Implementation order (next coding sessions)

1. Phase A.5 agent consult **or** document permanently unsupported CLIs that have no batch mode.  
2. Phase A.4 Ollama advisory (loopback already fail-closed).  
3. Phase A.3 docker sandbox run (inspect already real).  
4. Product decision + A.1/A.2 sqlmap/msf **or** freeze as unsupported.  
5. Phase B UI copy for `sudo vortex --allow-root run`.  
6. Tests: missing binary = no command; present binary (or fixture argv builder) = typed plan; Guardian still required.

## After this plan is coded

Then your earlier statement holds:

> Once I install this app on Linux and install the dependencies, it is good to go; remaining gaps are tools that are not on the host.

Until Phase A is done, installing sqlmap/msf/Ollama/agent CLIs/Docker still hits **code** UNAVAILABLE, not only **tool** UNAVAILABLE.

## How to use today (already real)

```bash
./vortex install --user
vortex serve --bind-host 127.0.0.1 --bind-port 8765
# UI: SEND whoami → APPROVE
# UI: Dependencies → INSTALL nmap → review apt plan → sudo vortex --allow-root run <plan-id>
# Engagements → then curl/nmap against authorized targets
```
