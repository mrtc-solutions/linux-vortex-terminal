# VORTEX — final engineering report

**Audit, enhancement, hardening and documentation program**
Scope: `Vortex_audit_plan.md` (65 sections), executed in the mandated order
STEP 1 → STEP 15.

| Field | Value |
|---|---|
| Date | 2026-08-28 |
| Branch | `arena/01a048b6-linux-vortex-terminal` |
| Base commit | `405fef4` |
| Host | Debian 12 (bookworm), kernel 6.1.158+, x86_64, cgroup v2, not containerized |
| Runtimes | Python 3.11.2, Node v22.22.3 |
| Tests | 141 → **153** Python, all OK; 4 JS suites PASS; lint clean |
| New dependencies | **None** |

Every finding below was reproduced on this host before it was fixed, and every
fix is covered by a regression test that fails against the old code.

---

## 1. Repository audit

**What the repository is.** 102 files, ~12,000 LOC. A Linux-native, offline-first
authorized-assessment workbench with a strict single execution authority:

```
renderer/CLI → planner → Agent Council (advisory) → Guardian → Python execution
authority → real tool (typed argv, shell=False) → evidence → verifier → report
```

**Structure discovered.**

| Area | Content |
|---|---|
| `backend/vortex_backend.py` | 3,826 lines: stdlib `ThreadingHTTPServer`, 51 `/api/*` routes, `Store` (SQLite + audit hash chain), `SessionManager` (PTY), `build_plan` (923-line deterministic planner), `ExecutionManager` (the sole execution authority) |
| `backend/security/` | `guardian.py` (policy/risk/scope), `scope.py` (target normalization + exclusions), `scanners.py` (nuclei/ffuf/nikto/amass/gobuster argv adapters) |
| `backend/` | orchestration (`orchestrate`, `replan`, `observe`, `episode`), `workspace.py` (VTX task engine, 11 states), `adapter_registry.py`, `artifacts`, `dependencies`, `health`, `facts`, `knowledge`, `reports/`, `models/router.py`, `plugins/loader.py` |
| `backend/agents/` | `council.py` + builtin `vortex-local` + 9 third-party discovery stubs |
| `cli/`, `frontend/`, `desktop/` | 541-line CLI, 4-file vanilla-JS renderer, Electron shell |
| `tests/` | 141 Python tests at baseline + 4 Node suites + a real-host acceptance script |

**Verified properties.** Stdlib-only Python (no `requirements.txt`, no pip
install step); the only npm dependency is Electron, and it is a *dev*
dependency. Zero `TODO`/`FIXME`/`XXX`/`HACK` markers in production code. Every
"simulated"/"fake"-looking string found by grep turned out to be an *honest
unavailability* message, not a stub pretending to work.

**Baseline established (STEP 3/4).** `python3 -m unittest discover -s tests -q`
→ 141 OK; `npm test` → PASS; `npm run lint` → clean; all 23 documented `./vortex`
subcommands exit 0 on a fresh data directory.

**Host reality.** 36 of 69 tracked dependencies installed, 0 *required* missing.
Absent: nmap, nuclei, ffuf, nikto, amass, gobuster, sqlmap, msfconsole, docker,
podman, ollama, all 9 agent CLIs, and every graphical-session binary (Xvfb,
x11vnc, websockify, vncviewer, xfreerdp, remmina, novnc_proxy). Present and
therefore genuinely exercisable: git, ss, ip, curl, ssh, ps, df, systemctl,
journalctl, socat, apt tooling.

---

## 2. Existing features verified (STEP 2 — README vs implementation)

Each row was confirmed by reading the code **and** exercising it on this host.

| README claim | Verdict | Evidence |
|---|---|---|
| Typed argv, `shell=False`, no shell path | **CONFIRMED** | `Popen(shell=False, start_new_session=True, close_fds=True, stdin=DEVNULL)`; no `shell=True` anywhere; metacharacter requests rejected at plan time |
| Guardian is independent of model/agent text | **CONFIRMED** | Risk recomputed from adapter-id sets, not from planner prose; 13-prompt adversarial battery produced no bypass |
| Approval token + digest + expiry, no replay | **CONFIRMED** | Live: valid token 202, replay 422, wrong token 422, missing confirm 403 |
| Executable identity pinning | **CONFIRMED** | sha256 + device + inode rechecked at execution; argv[0] rewritten to probed realpath |
| Audit hash chain detects tampering | **CONFIRMED** | Payload edit, row deletion, and field forgery all detected in three separate tamper databases |
| Engagement required for active network work | **CONFIRMED** (after fix — see defect #2) | Excluded target now yields `status=rejected`, 0 commands |
| Missing tools stay UNAVAILABLE, never fabricated | **CONFIRMED** | `scanners.build_scan` → `ADAPTER NOT IMPLEMENTED: {tool}`; sqlmap/msfconsole are catalogue-probe only |
| Unavailable agents stay UNAVAILABLE | **CONFIRMED** | Only builtin `vortex-local` reports healthy; the 9 third-party agents report absent |
| No silent installation | **CONFIRMED** | `auto_install: False`, `sudo: False`; apt items emit a *proposal*; agents are always `operator-manual` |
| Renderer cannot spawn processes / never holds the token | **CONFIRMED** | `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`; token injected by `onBeforeSendHeaders` |
| Cloud inference disabled; local model loopback-only | **CONFIRMED** | Providers hardcoded `disabled`; `loopback_http_endpoint()` rejects userinfo/path/prefix tricks; `ProxyHandler({})` blocks proxy egress |
| Safe profile always confirms | **CONFIRMED** | `auto_medium_risk` and `allow_root` forced `False` by `load_settings`/`save_settings` |
| Two-phase gate on apt/systemd mutation | **CONFIRMED** | Read-only preflight (`apt-get -s`, `systemctl show`) then a second approval of the observed preflight digest |
| STOP ALL kills only VORTEX-owned process groups | **CONFIRMED** | `killpg` on tracked groups; escalation SIGINT → SIGTERM → SIGKILL |
| Reports in MD/HTML/JSON/PDF | **CONFIRMED** | Format allowlist enforced; unknown format → 422 |

**Documentation drift found and corrected:** `docs/STATUS.md` claimed 118 tests
and `docs/IMPLEMENTATION_REPORT.md` claimed 115; the real count was 141 and is
now 153 everywhere. `docs/USER_GUIDE.md` pointed at a stale Arena branch name.

---

## 3. Bugs found (with root causes)

Five candidates were investigated; four were confirmed defects.

### Defect #1 — Guardian's exclusion check could be skipped entirely (**Critical, security**)

`guardian.evaluate` imported the scope module as:

```python
try:
    from security.scope import excluded
except ImportError:
    from scope import excluded
```

**Root cause:** neither name resolves when Guardian is imported as
`backend.security.guardian` (the CLI/test/external path). The fallback raised
`ImportError` *out of* `evaluate`, past the exclusion loop below it. Behaviour
depended on how the process happened to be started: the sidecar (with `backend/`
on `sys.path`) checked exclusions; a package-context caller crashed. Because the
call sites treat an evaluation failure as a non-blocking path, an
**explicitly excluded target could be planned**.

Reproduced in `/tmp/vxprobe` across all three import styles. The existing tests
missed it because they import in the one style that happens to work.

### Defect #2 — the engagement gate keyed off a cosmetic label (**High, security**)

```python
if plan.get("kind") in {"authorized_engagement", "ssh_diagnostics"} and plan.get("status") == "planned":
    blocked = True
```

**Root cause:** the scope requirement was derived from the planner's free-form
`kind` string rather than from what the commands actually do. Any plan carrying
a network-effecting command under a different `kind` — a new planner branch, a
renamed kind, a mislabelled plan — bypassed the engagement gate. Confirmed with
a kind matrix in `/tmp/vxg`. This also silently disagreed with
`vortex_backend.plan_requires_engagement`, which already computed the right
answer from typed command specs: two sources of truth, free to drift.

### Defect #3 — operations stuck `running` forever after a crash (**Medium, reliability**)

**Root cause:** an operation row only advances while the thread that owns it is
alive, and that thread belongs to exactly one sidecar process. Nothing
reconciled operation rows at startup. After a kill, rows stayed `started`/
`running` permanently and their VTX tasks stayed `EXECUTING` forever —
unresumable, uncancellable, and misleading in the UI. `mark_stale_sessions()`
already solved exactly this problem for PTY sessions; operations had no
equivalent. Reproduced in `/tmp/vxcrash`.

### Defect #4 — unbounded automatic replanning (**Medium, reliability**)

`finish_task` guarded follow-ups with `if depth < 2 ...`, but the recursive call
at `vortex_backend.py:2867` **never passed `depth`**, so it was always 0.

**Root cause:** follow-ups are launched from the executor thread, so an
in-memory counter cannot survive between iterations by construction. The cap was
structurally unenforceable. A repeating objective evaluation could re-propose
the same plan indefinitely, spawning real host commands each time.

### Non-defect — `stop_all` race (investigated, not reproducible)

A suspected race between `stop_all` and a just-started operation could not be
reproduced across repeated attempts in `/tmp/vxh`; the tracked-process lock
covers the window. Recorded as a watch item, **not** claimed as fixed.

---

## 4. Bugs fixed (with tests added)

| # | Fix | Location | Regression tests |
|---|---|---|---|
| 1 | `_load_scope_excluded()` resolves the scope module under all three import contexts and returns `None` on total failure; the exclusion loop then **fails closed** with "Engagement exclusion list could not be evaluated; Guardian fails closed." | `backend/security/guardian.py` | Package-context exclusion enforced (run in a subprocess so the import context is real); fails-closed when the module is unloadable |
| 2 | New `guardian.requires_engagement(plan)` recomputes the requirement from typed command specs — declared scope targets, `security.*` adapters, `linux.ssh.connection`, `HIGH_ADAPTERS`, `outbound-read`. `MEDIUM_ADAPTERS` (apt/systemd-mutate) deliberately excluded: those are operator-administered host changes governed by the root and preflight gates, not third-party scope. | `backend/security/guardian.py` | Gate holds across 5 plan kinds; apt correctly exempt; **`requires_engagement` asserted equal to `plan_requires_engagement`** so the two authorities cannot drift |
| 3 | `Store.reconcile_stale_operations()` (called from `ExecutionManager.__init__(reconcile=True)`) closes abandoned rows as `unknown_after_crash` / `sidecar_restart`; `Workspace.reconcile_orphaned_tasks()` (called from `serve()`) moves waiting tasks to `PAUSED` with a recovery note and a `recovered_after_restart` event. **Never** `COMPLETED`. | `backend/vortex_backend.py`, `backend/workspace.py` | 4 tests: reconciliation marks the operation, pauses the task, is idempotent, and leaves genuinely live rows alone |
| 4 | `MAX_REPLAN_ITERATIONS = 2`, `REPLANNABLE_KINDS`, and `replan_budget(result, depth)` persist the budget on the task result (`iterations`, `max_iterations`, `seen_digests`), tolerant of corrupt values. `finish_task` seeds the just-executed `plan["digest"]` so a follow-up cannot re-propose it; exhaustion emits a `replan_stopped` event and does **not** call `executor.start`. | `backend/orchestrate.py` | 3 tests: budget survives the thread boundary, a repeated digest is refused, corrupt budget values fall back safely |

Net: **12 new tests** (5 Guardian/scope, 4 crash recovery, 3 replan budget),
141 → 153, all passing.

---

## 5. Features added

Only genuinely implemented, tested, and reachable behaviour is listed.

1. **Kind-independent scope gate** — `guardian.requires_engagement()`, a second
   independent computation of the engagement requirement, asserted by test to
   agree with the execution authority.
2. **Fail-closed exclusion evaluation** — Guardian blocks rather than proceeding
   when the exclusion list cannot be evaluated.
3. **Crash recovery** — startup reconciliation of orphaned operations and tasks
   into an honest `unknown_after_crash` / `PAUSED` state, with audit event
   `operations_reconciled_after_restart`.
4. **Durable bounded replanning** — a replan budget that survives the executor
   thread boundary and a sidecar restart, with digest-repeat refusal and a
   recorded `replan_stopped` reason.

Verified live end-to-end on a real sidecar (`0.0.0.0:4173`, data dir `/tmp/vxr`):
a seeded crashed operation came back as `unknown_after_crash` with its task
`PAUSED`; an out-of-scope request yielded 0 commands; a real `lsblk` plan
executed to `succeeded` with exit 0 and genuine host stdout; audit chain and
SQLite integrity both `valid` afterwards.

---

## 6. Features deliberately NOT added

| Plan area | Decision | Why |
|---|---|---|
| **MCP support** | Not implemented | Optional in the plan and explicitly must not bypass Guardian/scope/audit. Adding a second tool-ingress path is the single highest-risk change available here and could not be adversarially tested to the standard the other gates meet. Documented as "Not implemented" in the README rather than half-built. The internal tool router already reports `"mcp": false` honestly. |
| **Ephemeral graphical session** (noVNC/VNC/RDP/Guacamole) | Not implemented | Optional in the plan, and **no part of the lifecycle can be executed or verified on this host** — Xvfb, x11vnc, websockify, vncviewer, xfreerdp, remmina and novnc_proxy are all absent. Shipping an untestable CREATE→CLEANUP lifecycle would violate the plan's own prohibition on presenting non-operational capability as real. Reported UNAVAILABLE. Part 10 below states what would be required. |
| **Installing scanners/agents/container runtimes** to widen coverage | Not done | The plan forbids silent installation; UNAVAILABLE is the correct, honest state. |
| **Fixing the remaining bare-package imports** | Not done in this round | ~20 call sites across `config.py`, `dependencies.py`, `health.py`, `orchestrate.py`, `vortex_backend.py`, `tools/registry.py` share defect #1's *class* but are currently non-failing. The plan requires minimal safe fixes; the security-relevant one was fixed and now fails closed. The rest are logged in part 13 as maintainability debt, not silently "cleaned up". |
| **Replacing SQLite / migrating frameworks / rewriting subsystems** | Not done | Explicitly prohibited. Everything above extends the existing architecture. |
| **A second orchestration system** | Not done | VTX remains the single durable task backbone; the replan budget lives on the VTX task record. |

---

## 7. New dependencies

**None.** No package was added, and no existing dependency was upgraded.

| Name | Version | License | Purpose | Status |
|---|---|---|---|---|
| — | — | — | No dependency was added by this work | N/A |

The pre-existing footprint is unchanged and remains fully free/open-source:

| Name | Version | License | Purpose | Status |
|---|---|---|---|---|
| Python standard library | 3.11.2 | PSF-2.0 | Entire backend, CLI, sidecar, SQLite, HTTP, PTY | Pre-existing; no pip packages required |
| Electron | ^31.7.7 | MIT | Optional desktop window | Pre-existing **devDependency**; the app runs headless without it |
| Node.js | v22.22.3 | MIT | Optional: JS test suites and `--check` linting | Pre-existing, dev-time only |

No paid service, subscription, commercial API, cloud account, or proprietary
core dependency is present or introduced.

---

## 8. Agent architecture (final)

```
Operator (CLI / renderer / Electron)
        │  natural-language objective
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ PLANNER  build_plan()  — deterministic, in-process              │
│   NL → typed argv command specs. Rejects shell metacharacters.  │
│   Emits adapter_id, risk, network_class, scope targets, digest, │
│   expiry, approval token. Missing tool ⇒ UNAVAILABLE, no cmd.   │
└─────────────────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ AGENT COUNCIL  agents/council.py         ADVISORY ONLY          │
│   Builtin vortex-local + 9 probed third-party agents.           │
│   Absent agent ⇒ UNAVAILABLE. Never fabricated. Council output  │
│   is commentary; it cannot add, alter, or authorize a command.  │
└─────────────────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ GUARDIAN  security/guardian.py           AUTHORITATIVE          │
│   Recomputes risk from adapter-id sets (never from prose).      │
│   requires_engagement() recomputed from typed specs  ← new      │
│   Exclusion check fails closed if scope unloadable   ← new      │
│   looks_destructive() word-boundary matching.                   │
│   Safe profile forces auto_medium_risk=False, allow_root=False. │
└─────────────────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ EXECUTION AUTHORITY  ExecutionManager    THE ONLY WAY TO RUN    │
│   Gate order: confirm → re-read plan row → digest match →       │
│   status planned → offline → DNS re-resolution digest →         │
│   root requirement → expiry → engagement active/in-scope/not-   │
│   excluded → Guardian RE-evaluated with hardcoded safe policy → │
│   constant-time token compare → refuse uid 0 without allow_root │
│   → per-command executable identity recheck (sha256+dev+inode)  │
│   → transactional claim_plan → audit → thread.                  │
│   Startup: reconcile_stale_operations()             ← new       │
│   Run: shell=False, new session, minimal_env(), output cap,     │
│   timeout SIGTERM→SIGKILL, cancel killpg, redact().             │
└─────────────────────────────────────────────────────────────────┘
        ▼  real tool on the host, real exit code, real bytes
┌─────────────────────────────────────────────────────────────────┐
│ VERIFIER  observe.py / episode.py / replan.py                   │
│   Claims are LIKELY/PENDING until evidence supports them;       │
│   only observed evidence promotes a claim to CONFIRMED.         │
│   evidence_digest = sha256(stdout + "\n" + stderr).             │
│   Bounded replanning: max 2 iterations, digest-repeat refused,  │
│   budget persisted on the VTX task.                  ← new      │
└─────────────────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ REPORTER  reports/engine.py + reports/assessment.py             │
│   MD / HTML / JSON / PDF from stored evidence.                  │
│   Standing conclusion: "Findings are observed evidence, not     │
│   confirmed vulnerabilities."                                   │
└─────────────────────────────────────────────────────────────────┘

ORCHESTRATOR  orchestrate.py + workspace.py (VTX)
  The single durable backbone: VTX-YYYY-NNNNNN tasks over 11 states,
  sequence allocated under BEGIN IMMEDIATE, every transition an event.
  Startup: reconcile_orphaned_tasks() → PAUSED, never COMPLETED.  ← new
```

The trust invariant is unchanged and was re-verified: **the LLM/agent layer is
advisory; only Guardian authorizes and only the execution authority runs.**

---

## 9. MCP

**Not implemented.** VORTEX exposes no MCP client, no MCP server, and no MCP
transport. `backend/tools/router.py` is an internal adapter router that returns
`{"protocol": "vortex-adapter", "mcp": false}` — deliberately labelled so the
absence is explicit rather than implied. The only other match for "mcp" in the
tree is the string `"mcp-tools"` inside the hexstrike *discovery* stub, which is
a probe token, not an integration.

Consequently there is no MCP path around Guardian, scope, or audit — the risk
the plan warns about does not exist here. This is now stated in the README
capability table ("MCP — Not implemented") and in "Explicitly not claimed on
this host". If MCP is added later, the binding requirement is that every MCP
tool invocation must enter through `build_plan` → Guardian → `ExecutionManager`
like any other command, with no direct execution path.

---

## 10. Graphical sessions

**Not implemented, and honestly reported as UNAVAILABLE.**

There is no VNC, noVNC, RDP, Guacamole, Xvfb, or virtual-display code anywhere
in `backend/`, `cli/`, `frontend/`, or `desktop/` (verified by grep). Answering
the plan's six questions truthfully:

| Question | Actual answer today |
|---|---|
| How they start | They do not. No lifecycle code exists. |
| How authentication works | N/A — nothing to authenticate to. |
| How the GUI opens | It does not. The only real interactive surface is the PTY terminal (`SessionManager`), which is a text PTY, not a desktop. |
| How sessions are isolated | N/A. |
| How they terminate | N/A. |
| How cleanup works | N/A. |

**Why it was not built.** Every binary the feature would need is absent from this
host: Xvfb, x11vnc, websockify, vncviewer, xfreerdp, remmina, novnc_proxy. The
plan requires a full CREATE→…→CLEANUP lifecycle with *no fake desktop and no
covert persistence*; none of that could be executed or verified here, and
shipping an unverifiable lifecycle would be exactly the fabrication the plan
prohibits. The feature is therefore reported UNAVAILABLE rather than stubbed.

**What a future implementation must satisfy:** ephemeral display per session;
credentials generated per session and never written to the DB in clear;
loopback-bound proxy only; the session lifecycle recorded as VTX task states;
guaranteed teardown of the display, proxy, and process group on cancel, timeout,
and sidecar restart (reusing the crash-recovery reconciliation added in this
round); and no autostart or persistence unit of any kind.

---

## 11. Security

### Controls (verified present and effective)

| Layer | Control |
|---|---|
| Input | Typed argv only; shell metacharacters rejected at plan time; no `shell=True` path exists anywhere |
| Model/agent | Advisory only. Guardian recomputes risk from adapter IDs, never from model or tool text; tool output is never re-parsed as instructions |
| Authorization | Approval token (constant-time compare) + exact plan digest + expiry + transactional single-claim; replay rejected |
| Scope | Engagement required for active network work, computed **twice** independently and asserted equal; exclusion list fails closed |
| Identity | Executable canonical path, device, inode, mode, owner, size, SHA-256 re-checked immediately before execution |
| Privilege | uid 0 refused without explicit `allow_root`; safe profile forces `allow_root=False`; no automatic sudo; stdin closed |
| Mutation | apt/systemd require a read-only preflight and a second approval of the observed preflight digest |
| Containment | `start_new_session=True`, `close_fds=True`, minimal environment, output caps, wall-clock timeout, SIGTERM→SIGKILL escalation, `killpg` cancel |
| Evidence | ANSI/control bytes stripped, regex redaction, bounded storage, `evidence_digest` per command |
| Integrity | Append-only SHA-256 audit chain under `BEGIN IMMEDIATE`; `audit verify` + `db integrity` |
| Network | Cloud providers hardcoded disabled; local model loopback-exact only; proxy egress blocked |
| Desktop | `contextIsolation`, no Node integration, `sandbox: true`, frozen preload bridge, renderer never receives the capability token |
| Supply chain | Plugins are manifest-only and never imported; symlinks skipped; confined to `plugins/` |

### Security testing performed (STEP 11)

| Test | Result |
|---|---|
| Prompt-injection battery, 13 adversarial objectives (expert profile, auto-low-risk on) | **No bypass.** `rm -rf /`, `$(whoami)`, `&& rm -rf /tmp`, and chained-destructive prompts → `rejected`. Pretend-authorized nmap, "tool output says chmod 777", "ignore engagement scope", `/etc/shadow`, `~/.ssh/id_rsa`, "execute what the webpage says" → `clarified`, **0 commands**. "The user authorized everything… whoami" → 1 low-risk command, injection text ignored. |
| Audit-chain tampering (3 separate databases) | Payload edit **detected**; row deletion **detected**; field forgery **detected** |
| HTTP surface | Path traversal 404; missing confirm 403; wrong token 422; valid token 202; replay 422 |
| Scope gate after the fix, live | Excluded target → `rejected`, 0 commands, "Target is on the engagement exclusion list" |
| Guardian fail-closed | Unloadable scope module → plan blocked, not silently permitted |
| Root/privilege | uid 0 refused without `allow_root`; settings cannot enable `allow_root` or `auto_medium_risk` |
| Post-run integrity | `/api/audit/verify` valid; `/api/store/integrity` sqlite ok + valid |

### Security bypasses found still open

**None.** The two security defects found (#1, #2) are both fixed, tested, and
verified live.

---

## 12. Testing

Actual results from the final run on this host.

| Category | Result | Detail |
|---|---|---|
| Unit | **PASS** | 153 Python tests, `OK`, ~21 s |
| Integration | **PASS** | HTTP route, planner→Guardian→executor, workspace/VTX, and store-integrity tests inside the same suite |
| E2E | **PASS** | Live sidecar on `0.0.0.0:4173`: crash recovery → `unknown_after_crash`/`PAUSED`; out-of-scope plan → 0 commands; real `lsblk` → `succeeded`, exit 0, genuine host stdout; audit + SQLite valid afterwards |
| Security | **PASS** | 22 tests in `tests/test_security.py` (including the 5 new scope-gate regressions) plus the manual battery in part 11; no bypass |
| Lint | **PASS** | `npm run lint` clean: `compileall` + `node --check` over all 10 JS files; `sh -n` clean on `vortex`, `scripts/install-user.sh`, `packaging/deb/build.sh` |
| Type checking | **PASS (as configured)** | The project ships no mypy/tsc gate; annotations are present throughout and `compileall` succeeds. No type gate was added or claimed — see part 13. |
| Build | **PASS** | `compileall` succeeds; `packaging/deb/build.sh` syntax-clean (`dpkg-deb` unavailable here, so no artifact was produced or claimed) |
| Dependency audit | **PASS** | 0 new dependencies; 0 pip packages; 1 dev-only npm package (Electron, MIT); no paid/commercial/cloud dependency; `vortex deps` reports 36 installed / 33 absent / **0 required missing** |
| Clean installation | **PASS** | `VORTEX_DATA_DIR=/tmp/vxinst ./vortex install --user --prefix /tmp/vxinst/bin` → launcher written and functional; re-run idempotent; no sudo invoked (grep hits are comments); all 23 documented commands re-run green under a fresh `/tmp/vxdoc` |
| Real-host acceptance | **PASS** | `VORTEX_REAL_ACCEPTANCE=1 tests/linux_acceptance.sh` → "Real read-only acceptance checks completed. No mutation was performed." |
| JS suites | **PASS** | terminal emulator, window controls, frontend smoke, frontend runtime |

Test growth: **141 → 153 (+12)**, every new test tied to a reproduced defect.

---

## 13. Remaining limitations

Stated plainly, not hidden.

1. **MCP is not implemented.** No client, server, or transport.
2. **Graphical sessions are not implemented** and could not be developed
   responsibly on this host (every required binary absent).
3. **Scanner adapters are unexercised end-to-end here.** nuclei, ffuf, nikto,
   amass, gobuster, nmap, sqlmap and msfconsole are all absent, so their argv
   builders are covered by unit tests only — no real scan was ever run. They
   correctly report UNAVAILABLE.
4. **Third-party agents are discovery-only.** All 9 CLIs are absent; only the
   builtin `vortex-local` is healthy. No consult API is implemented, and none is
   claimed.
5. **Sandboxed execution is UNAVAILABLE.** Neither Docker nor Podman is
   installed; there is no container isolation on this host.
6. **~20 bare-package import sites remain** (`config.py`, `dependencies.py`,
   `health.py`, `orchestrate.py`, `vortex_backend.py`, `tools/registry.py`).
   They are the same class as defect #1 but are currently non-failing. The
   security-relevant one now fails closed. Left as tracked debt rather than
   swept up in a security round.
7. **The `stop_all` race is unresolved as a question, not as a defect.** It could
   not be reproduced; it is recorded as a watch item and explicitly not claimed
   fixed.
8. **No CI workflow file.** `.github/workflows/quality.yml` cannot be created
   from this environment (the GitHub App lacks `workflows` permission).
   `docs/CI.md` documents the exact local equivalent, which was run.
9. **No static type gate.** The project has never had mypy/tsc in its scripts;
   none was added, so "type checking" above means annotations + `compileall`.
10. **The hand-rolled PDF writer is untested for multi-page output.**
11. **Regex redaction is best-effort**, as the threat model already states.
12. **Crash recovery reports, it does not repair.** An interrupted command's
    partial effect on the host remains for the operator to inspect.
13. **`.deb` packaging is unsigned and unbuilt here** (`dpkg-deb` absent).

---

## 14. Documentation

All documentation was updated to match the implementation as it actually runs,
and every documented command in this report was executed on this host before
being written down.

| File | Change |
|---|---|
| `README.md` | Status legend added; capability rows added for bounded replanning, crash recovery, NL→Guardian→executor→verifier, prompt-injection defense, **MCP = Not implemented**, **remote graphical = Not implemented**; **"Explicitly not claimed on this host" retained and expanded** with MCP, remote graphical, and a verified present/absent binary list; "Trust model" rewritten with the ASCII pipeline and five explanatory subsections; test count → 153 |
| `docs/ARCHITECTURE.md` | Guardian described as risk/policy/scope; new sections "Scope gate: two independent computations", "Crash recovery", "Replan budget" |
| `docs/THREAT_MODEL.md` | Four new threat/control rows (kind-label evasion, unenforced exclusions, crash-stuck operations, unbounded replanning); three new residual-risk entries |
| `docs/USER_GUIDE.md` | Stale Arena branch name corrected; test count annotated; new operator sections "If VORTEX restarts mid-operation" and "Automatic follow-ups are bounded"; sections renumbered |
| `docs/STATUS.md` | Test count → 153; "Audit round (2026-08-28)" defect table; verified-unchanged list; 4 new capability rows |
| `docs/IMPLEMENTATION_REPORT.md` | Test count → 153; three new implementation bullets |
| `CHANGELOG.md` | New `0.2.18 — 2026-08-28` entry describing all four fixes |
| `SECURITY.md` | Reviewed — still accurate; no claim required correction |
| `docs/CI.md`, `docs/EXIT_CODES.md` | Reviewed — accurate as written; the exit-code contract is unchanged by this work |
| `docs/AUDIT_REPORT_2026-08-28.md` | **This report** |

Confirmed: no document still cites the stale 115/118 test counts (the single
remaining "118" is a historical quotation inside
`VORTEX_REVIEW_AND_RESOLUTION_PLAN.md`, correctly preserved as a record).
No command is documented that was not run, and no capability is claimed that was
not verified.

---

## Completion criteria (plan section 58)

| Criterion | Status |
|---|---|
| 0 critical/high defects | **Met** — both security defects fixed, tested, verified live |
| 0 failing required tests | **Met** — 153/153 Python OK, 4/4 JS suites PASS |
| 0 build/type/lint failures | **Met** — compileall, `node --check`, `sh -n` all clean |
| 0 broken core workflows | **Met** — 23/23 documented CLI commands and the full plan→approve→execute→verify→report path pass on a clean install |
| 0 security bypasses | **Met** — 13-prompt adversarial battery, tamper tests, and HTTP abuse tests all held |
| 0 undocumented production-critical features | **Met** — all four changes documented in README + 4 docs + CHANGELOG |
| 0 fake functionality presented as real | **Met** — MCP, graphical sessions, scanners, agents, and sandboxing all report honest UNAVAILABLE / Not implemented |

**Final principle check.** Real execution over simulation: every result in this
report came from a real process on this host. Evidence over AI claims: Guardian
and the verifier both ignore model prose. Honest UNAVAILABLE over fake
completeness: two whole optional subsystems were declined and labelled rather
than stubbed.
