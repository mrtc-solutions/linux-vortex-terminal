# VORTEX — ARCHITECTURE MAP & AI/LLM RESPONSIBILITY REPORT

Date: 2026-09-06 · Branch `arena/01a0782e-linux-vortex-terminal` · head `8017e56`
Method: traced actual execution paths (not filenames) through the renderer,
the HTTP sidecar, the orchestrator, the council, the Guardian, and the
execution/PTY layers. Every claim below is grounded in the checked-in code.

---

## 1. The REAL architecture (discovered, not assumed)

```text
USER (browser / Electron renderer / CLI)
 │  fetch() over the sidecar HTTP API (or the typed Electron preload bridge)
 ▼
VortexHandler — backend/vortex_backend.py
 │  single stdlib ThreadingHTTPServer; routes /api/* to components
 ▼
orchestrate.run_turn() — backend/orchestrate.py   (the turn pipeline)
 │  1. build_plan()          deterministic planner → typed, reviewed adapter argv
 │  2. episode.observe()     deterministic observation record
 │  3. models.router.advise()  LOCAL LLM advisory (loopback Ollama)   [optional]
 │  4. agents.council.consult()  AI-ASSISTANT council (advisory)      [optional]
 │  5. security.guardian.evaluate()  THE AUTHORITY (deterministic)    [essential]
 │  6. ExecutionManager.start()  →  subprocess.Popen(argv, shell=False) [essential]
 │  7. execution threads  →  stdout/stderr captured, redacted, capped, timed
 │  8. finish_task()  →  models.router.advise(phase="interpret") advisory again
 │       + deterministic analysis/report/episode/replan
 ▼
UI response (plan card → analysis card → report)
```

### Component inventory

| Component | Where | What it does | Called by | Calls | Sync/async | Local/remote | Essential? | Perf-sensitive? | Tested? |
|---|---|---|---|---|---|---|---|---|---|
| **Renderer app shell** | `frontend/index.html`, `app.js` | SPA views, plan/analysis rendering, session UI | user | `api()` → sidecar | async (fetch/SSE) | local | yes | terminal yes | yes |
| **Workspace UI** | `frontend/workspace.js` | conversations/tasks/reports/memory overlays | `app.js` | sidecar | async | local | yes | no | yes |
| **Models UI** | `frontend/models.js` | Ollama runtime + model download manager | `setView('models')` | `/api/ollama*` | async + poll | local | no | no | yes |
| **Terminal emulator** | `frontend/terminal.js` | `VortexTerminal` ANSI→HTML buffer | `app.js` | — | sync (rAF-coalesced) | local | yes | **yes** | yes |
| **Electron shell** | `desktop/main.js`, `preload.js` | spawns sidecar, token proxy, window controls | OS | sidecar | async | local | no | no | partial |
| **CLI** | `cli/vortex.py` | terminal entry, `--allow-root`, run/stop | user | sidecar | sync-ish | local | no | no | yes |
| **HTTP handler** | `backend/vortex_backend.py` `VortexHandler` | routing, auth, JSON, SSE, static assets | any client | all backend services | threaded | local | yes | no | yes |
| **Store** | `backend/vortex_backend.py` `Store` | SQLite (WAL), audit hash chain, plans/ops/sessions/artifacts | handler/services | sqlite3 | sync | local | yes | minor | yes |
| **Planner** | `build_plan()` | NL → typed, reviewed adapter argv (no shell) | `run_turn` | `probe_executable`, knowledge, adapters | sync | local | yes | no | yes |
| **Guardian** | `backend/security/guardian.py` | independent, deterministic safety authority | `run_turn`, executor | scope, policy | sync | local | **yes (authority)** | no | yes |
| **Executor** | `ExecutionManager` | runs typed argv w/ caps/timeouts/cancel | Guardian-approved | `subprocess.Popen(shell=False)` | async threads | local | yes | yes | yes |
| **PTY sessions** | `SessionManager` | `pty.fork` + `os.execve`, read/wait/reaper, resize ioctl | `/api/sessions` | kernel PTY | async threads | local | yes | **yes** | yes |
| **Orchestrator** | `backend/orchestrate.py` | turn pipeline, replan budget, task finish | handler | planner/LLM/council/Guardian/executor | sync + async | local | yes | yes | yes |
| **Local LLM router** | `backend/models/router.py` | loopback-only Ollama advisory (`advise`) | `run_turn`, executor | `ollama /api/chat` | sync (bounded) | **loopback** | no (optional) | **yes (latency)** | yes |
| **Ollama manager** | `backend/models/manager.py` | install/start/stop, pull/cancel/remove, catalog | `/api/ollama*` | `ollama` binary + API | async threads | loopback + outbound download | no (optional) | no | yes |
| **AI council** | `backend/agents/council.py` | select/consult/critique agent adapters | `run_turn` | agent adapters | sync | local | no | no | yes |
| **Agent adapters** | `backend/agents/*.py` | 1 builtin advisor + 9 external stubs | council | probe/health | sync | local | no | no | yes |
| **Adapters/tools** | `backend/adapter_registry.py`, `tools/` | 45 typed manifests + tool catalog + host scan | planner | `probe_executable` | sync | local | yes | no | yes |
| **Facts/artifacts** | `backend/facts.py`, `artifacts.py`, `network.py` | parse observed output into typed evidence | executor/finish | parsers | sync | local | yes | no | yes |
| **Health/deps** | `backend/health.py`, `dependencies.py`, `probe_cache.py` | live subsystem probes, TTL cache | `/api/health` etc. | `probe_executable` | sync | local | no | no | yes |
| **Workspace/reports/episode** | `backend/workspace.py`, `reports/`, `episode.py`, `replan.py` | persistence, reports, learning loop | orchestrator | Store | sync | local | yes | no | yes |

**Trace notes.** The planner is fully deterministic: it maps natural language to
*reviewed* adapter argv (`adapter_command`, `command_spec`) and never interprets
shell text. The local LLM is invoked only as an *advisory explainer* (the system
prompt says "advisory explainer only … never claim to have executed commands").
Guardian is the sole authority and is explicitly `independent_of_model: True`.

---

## 2. AI ASSISTANTS (the secondary/supporting team)

All assistants live under `backend/agents/` behind the `AgentAdapter` contract
(`base.py`). None executes commands, none reaches the network, none calls a
model. Their `submit_task()` contract is advisory.

| Assistant | Location | This assistant exists to… | State |
|---|---|---|---|
| **VORTEX Local Advisor** (`vortex-local`) | `backend/agents/local.py` | …provide deterministic commentary over the plan observation (missing tools / legal adapters). Only assistant that returns `responded`. Builtin, always present, never executes. | working |
| **HackerAI** (`hackerai`) | `backend/agents/hackerai.py` | …advertise a pentest advisory CLI; health check only (`hackerai` binary). Returns `requires_configuration` if present; `unavailable` otherwise. | stub |
| **Nebula** (`nebula`) | `backend/agents/nebula.py` | …advertise BerylliumSec/nebula CLI-assisted pentest advice; health check only (`nebula`). | stub |
| **CAI** (`cai`) | `backend/agents/cai.py` | …advertise aliasrobotics/CAI; health check only (`cai`). | stub |
| **PentestGPT** (`pentestgpt`) | `backend/agents/pentestgpt.py` | …advertise PentestGPT; health check only (`pentestgpt`/`pentestgpt-cli`). | stub |
| **HexStrike** (`hexstrike`) | `backend/agents/hexstrike.py` | …advertise HexStrike MCP tools; health check only (`hexstrike`/`hexstrike-ai`). | stub |
| **HALO** (`halo`) | `backend/agents/halo.py` | …advertise HALO; health check only (`halo`/`halo-ai`), no verified repo configured. | stub |
| **PentAGI** (`pentagi`) | `backend/agents/pentagi.py` | …advertise PentAGI autonomous pentest; health check only (`pentagi`). | stub |
| **Strix** (`strix`) | `backend/agents/strix.py` | …advertise Strix pentest advice + fix suggestions; health check only (`strix`). | stub |
| **DarkMoon** (`darkmoon`) | `backend/agents/darkmoon.py` | …advertise DarkMoon advisory; health check only (`darkmoon`), no verified repo. | stub |

**Per-assistant facts (from `base.py` / `council.py`):**

- **Purpose:** advisory pentest/CLI-assistant commentary. They are *not* the
  intelligence; they are optional third-party *sources of commentary*.
- **Inputs:** `submit_task(payload)` where payload = task id + request +
  observation (never secrets, never process control).
- **Outputs:** `{agent, state, result, message}`. External ones return
  `requires_configuration` (installed) or `unavailable` (absent) — no output is
  fabricated.
- **Who invokes them:** `agents/council.py::consult()`, called once per turn by
  `orchestrate.run_turn()`.
- **What they invoke:** nothing — only `health_check()` (a `probe_executable`
  PATH probe) and a no-op `submit_task`. `stop_task`/`receive_result`/`cleanup`
  are no-ops for the stubs.
- **Local LLM?** No. **Another provider?** No. **Execute commands?** No.
  **Analyze/validate commands?** No (Guardian does). **Orchestrate?** No.
  **Plan?** No. **Error analysis/recovery?** No (deterministic pipeline does).
- **Essential?** No — the turn completes without them.
- **Overhead:** negligible (PATH probes are cached; `select_agents` caps at 3).
- **Duplication:** the 9 external stubs are near-identical manifest wrappers.
  They are *not* redundant by accident: each declares a distinct third-party
  tool/license/repository so the inventory is honest about what *could* be
  integrated. Per requirement they are **left intact**; no removal.

**Latency finding:** `council.consult()` adds ~0 ms in practice (no network, no
model calls). It is not a latency source. The turn-latency source was the local
LLM plan-phase consultation, already bounded (see §4).

---

## 3. LOCAL LLMs (the advisory local intelligence)

| Field | Value |
|---|---|
| **Models (catalog)** | `phi4-mini:3.8b` (conversation/interpret/report/verify), `qwen3:4b` (plan/tooling/verify), `llama3.2:3b` (fast/fallback), `gemma3:4b` (optional specialist) |
| **Where configured** | `backend/models/router.py::MODEL_CATALOG`; operator prefs in `backend/config.py` (`model_primary/planner/fast/specialist`) |
| **Where loaded/selected** | `choose_route()` picks per phase (conversation/plan/report/interpret) from installed candidates |
| **How invoked** | `advise()` → `_ollama_json(endpoint, "/api/chat", POST, body)` with `stream:False`, `format:"json"` |
| **Endpoint/process** | `http://127.0.0.1:11434` loopback only (enforced by `loopback_http_endpoint`); the service is Ollama (system, or VORTEX-managed via `models/manager.py`) |
| **Prompts** | system: "You are VORTEX Local AI. You are an advisory explainer only… Return compact JSON with keys fact_summary, meaning, unknowns, next_steps, caution, status_alignment." + role goal; user: request/role/route/evidence JSON |
| **Outputs** | structured JSON → `_coerce_reply` → deterministic synthesis (`fact_summary`, `meaning`, `unknowns`, `next_steps`, `caution`) |
| **Who consumes it** | `orchestrate.run_turn` (plan phase) and `ExecutionManager._run` (interpret phase) → `analysis.local_ai` → `renderAnalysis` in the UI |
| **Reasoning?** | Yes, but bounded advisory reasoning over supplied evidence only |
| **Command planning/generation?** | **No.** The deterministic planner generates commands; the LLM explains them |
| **Interpret user intent?** | Indirectly (advisory only); deterministic planner is the intent interpreter |
| **Analyze results?** | Yes — post-execution interpret phase summarizes observed evidence (never claims execution) |
| **Recovery/reasoning?** | No (replan budget is deterministic) |
| **Agent loops?** | No. The LLM is not an agent and participates in no loop |
| **Primary intelligence?** | **No — by design.** Guardian + planner are authoritative |
| **Optional?** | Yes. `ai_enabled`, `offline`, and absence all degrade gracefully |
| **Installed in sandbox?** | No Ollama runtime present (`binary_state: absent`) |
| **Detection** | `model_status()` → `ollama_status()` probes `/api/version` + `/api/tags` on loopback |
| **Absence handling** | Correct: `advise()` returns `state: unavailable` with reason; the turn continues deterministically |
| **Actually used?** | Only when healthy + enabled + a model is installed; otherwise skipped |

### Local LLM verification (per §6 of the spec)

- **Final reasoning decision:** Guardian (`vortex-guardian`, `independent_of_model: True`).
- **Command generation:** deterministic `build_plan` via reviewed adapters.
- **User-request interpretation:** deterministic planner.
- **Command-result analysis:** deterministic `make_analysis` + the LLM's advisory interpret phase (labeled "advisory").
- **What happens next:** deterministic `replan` budget (max 2 follow-ups, deduped by plan digest).
- **Failure handling:** deterministic lifecycle mapping in `finish_task`.
- **Ollama communication:** `models/router.py` (advisory chat) + `models/manager.py` (lifecycle).
- **Model context ownership:** the renderer/backend never hold model weights; Ollama owns context. VORTEX sends one-shot, bounded requests (`num_ctx`, `num_predict`, `keep_alive`).

**Discrepancy vs. the intended "local LLMs are primary intelligence" principle:**
The repository's real architecture makes the **local LLM secondary/advisory** and
the **deterministic planner + Guardian primary**. This is intentional, documented
in-code, and enforced by tests (`test_local_ai.py`, Guardian tests). It is *not*
a bug: assistants never bypass the LLM because the LLM was never given authority
to give away. Per the spec I **report this discrepancy and do not change it**
without explicit direction — changing it would mean granting model output
execution authority, which contradicts the repo's core safety design.

---

## 4. Responsibility matrix ("who does what")

| Component | Primary responsibility | Secondary | Uses local LLM? | Executes commands? | Generates commands? |
|---|---|---|---|---|---|
| Deterministic planner (`build_plan`) | NL → typed reviewed argv | suggestions, knowledge | No | No | **Yes** (only component) |
| Guardian | Safety authority, approve/block | scope re-check | No | No | No |
| ExecutionManager | Run typed argv w/ caps/timeouts | cancel, evidence digest | No | **Yes** | No |
| SessionManager (PTY) | Interactive shell, streaming, resize | idle reap | No | **Yes** (interactive) | No |
| Local LLM router (`advise`) | Advisory explanation/synthesis | interpret-phase summary | **Yes (itself)** | No | No |
| AI council + adapters | Advisory commentary | agent inventory | No | No | No |
| Ollama manager | Runtime + model lifecycle | catalog, verification | No | No (subprocess for ollama) | No |
| Orchestrator (`run_turn`) | Sequence the pipeline | task/report/replan wiring | via router | via executor | via planner |
| Renderer | Present state | streaming, progress | No | No | No |
| Store / Workspace | Persistence + audit chain | retention, search | No | No | No |

---

## 5. Existing weaknesses (found, not assumed)

1. `VortexTerminal` still does a full-buffer `innerHTML` render per frame
   (coalesced, so acceptable; a delta renderer would be a larger rewrite).
2. The 9 external agent adapters are health-check stubs — honest, but they add
   catalog surface with no functional consult path yet.
3. Ollama install/model downloads need real network; in this sandbox they were
   exercised only through the failure path (TLS refused → `failed/network`).
4. No JS build/type-check step exists (vanilla JS); `node --check` is the gate.

## 6. Recommended architecture changes (for a later, separately-approved pass)

- If "local LLM as primary intelligence" is ever desired, it must be introduced
  as a *proposal* layer: LLM proposes a plan **structure**, the deterministic
  planner re-renders it into typed adapter argv, and Guardian still authorizes.
  Do **not** hand argv generation or approval to a model.
- Replace the full terminal renderer with a line/row delta renderer only if
  profiling shows jank on very large scrollback (not yet observed).
- Add a reviewed, non-executing consult interface for at least one external
  agent to make the council functionally multi-agent — optional, low priority.

---

## 7. Verification evidence (this session)

- `python3 -m unittest discover -s tests -v` → **270 OK** (262 prior + 8 new:
  failure classification, storage gating, speed/ETA, loopback API probe,
  install network-failure classification, pull progress parsing + verification,
  pull verification-failure, pipe-close resource check).
- Node suites (terminal, windows, frontend smoke, frontend runtime) → **PASS**.
- `npm run lint` (compileall + `node --check` incl. `models.js`) → **PASS**.
- Live sidecar: `GET /api/ollama` (stable install schema), `POST install confirm`
  → async, `downloading → failed/network` with `failure_reason` (sandbox has no
  egress); `/api/health` reports `diagnostics.step = install`.
