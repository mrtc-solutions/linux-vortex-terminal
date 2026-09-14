# VORTEX Terminal — Expansion Plan (REVISED for `mrtc-solutions-patch-2`)

> Status: **IMPLEMENTED on `arena/01a09b13-linux-vortex-terminal`** — Phases 0–6 complete,
> `scripts/final_gates.py` 10/10 (100%), shipped as 0.3.0. This document is kept as the
> implementation record. Target: merge into `main` via PR after review.

## 0. What `mrtc-solutions-patch-2` actually contains (I read it fully)

- `mrtc-solutions-patch-2` = `main` **plus the extracted design uploaded at the repo root**: `index.html`,
  `src/` (10 components, 4 services, types, css — **byte-identical to `ai-powered-terminal-design.zip`**),
  `tsconfig.json`, `vite.config.ts`. Commit `35369b6` ("Add files via upload") on top of `7a4d97e`.
- `backend/`, `frontend/` (vanilla), `cli/`, `desktop/`, `tests/`, `docs/` are **untouched** — all real operations
  from `main` are present and intact.
- ⚠️ **One problem the upload created:** root `package.json` / `package-lock.json` were **overwritten** with the
  React demo's versions. That deleted the project's real scripts (`npm test`, `npm run lint`, Electron `start`,
  `package:deb`) and the `electron` devDependency. **Phase 0 restores a merged `package.json` first** —
  nothing can be verified until that is fixed.
- **Where the work happens:** this Arena session is fixed to branch `arena/01a09b13-linux-vortex-terminal`
  (I cannot switch branches). So I have **imported patch-2's tree into this session branch**
  (fast-forward to `35369b6` — our working tree IS patch-2 now, plus this plan file).
  All expansion below happens **in place, on the already-existing code** — no staging copies, no rewrites.
  The final PR goes from this branch → `main` and carries the design + all real functionality together.

## 1. What I learned from reading the entire app

### 1A. The REAL engine (already in this branch, from `main`)

- **Backend = one local Python authority** (`backend/vortex_backend.py`, ~5,400 lines, stdlib-only HTTP on
  `127.0.0.1:8765`). Real `shell=False` argv execution, real PTY sessions, audit hash chain, output caps, redaction.
- **Planning → Guardian → execution** (`backend/dependencies.py`, `backend/security/guardian.py`): natural language
  becomes a *typed plan* over reviewed adapters only; the independent Guardian recomputes risk (safe/standard/expert)
  and cannot be self-approved by any model/agent; engagements/scope gate active network work.
- **Orchestration** (`backend/orchestrate.py`, `backend/workspace.py`, `backend/replan.py`): turn flow = intent →
  plan → council/fuzzy advisory → Guardian → optional execution → observe → verify → bounded replan (max 2
  follow-ups) → report. Tasks/conversations/memory persist in SQLite under `$XDG_DATA_HOME/vortex` (0700).
- **Tools** (`backend/tools/registry.py`, `hostscan.py`, `backend/health.py`): live probes; present-but-blocked for
  unsafe paths; honest UNAVAILABLE when binaries/wordlists/runtimes miss.
- **Local AI today** (`backend/models/manager.py`, `router.py`, `gguf.py`, `fuzzy.py`): on-device GGUF →
  loopback Ollama pool → deterministic agent council (builtin `vortex-local` only) → deterministic core.
  Fuzzy engine blends availability + latency EWMA + RAM fit + phase fit; `ai_hint` advisory-only, never blocks.
- **CLI/Desktop/Packaging**: `./vortex` (40+ subcommands), Electron wrapper (`desktop/`), `.deb` + APK builders,
  431 Python tests + JS suites, `scripts/final_gates.py` (10/10).

### 1B. The DESIGN in `src/` (gorgeous, but 100% simulated — this is what we expand)

- Shell: `src/App.tsx` + `HeaderBar` (6 tabs) + `QuickPromptBar` + theme engine (matrix/amber/cyan/crimson/violet
  CSS vars) + `MatrixRainCanvas` + CRT overlay + `soundEffects.ts`.
- Tabs: **Terminal / Tactical Map / /out Directory / Report Gen / Fuzzy Consensus / Agent Reach**.
- Simulations to replace with real wiring (rendering code stays, data source changes):
  - `services/multiLLMOrchestrator.ts`: hardcoded `if (includes('scan'))…` fake outputs → real API calls.
  - `services/virtualFileSystem.ts`: in-memory fake FS → real artifacts/history/PTY endpoints.
  - `services/fuzzyLogicEngine.ts`: real Mamdani/centroid math kept, but fed with **real** backend scores.
  - `components/TacticalMap.tsx`, `ReportGeneratorModal.tsx`, `OutDirectoryExplorer.tsx`: hardcoded nodes/findings
    → observed-only backend data. `TerminalView.tsx`: fake `setTimeout` deliberation → live SSE output.

**Net: expand the existing `src/` in place — keep every pixel, replace every fake byte with the real engine.**

## 2. Design-freeze + expansion rules (your guarantees)

- **Frozen (pixel-identical):** `src/index.css` themes/glows/CRT/radar/scrollbar/cursor, `MatrixRainCanvas.tsx`,
  `HeaderBar.tsx` layout, `QuickPromptBar.tsx`, `soundEffects.ts`, all 5 themes, fonts, tab order, animations.
- **Expand, don't rewrite:** existing components keep their structure; we **ADD** files alongside them
  (`src/services/vortexApi.ts`, `src/components/WindowManager.tsx`, `src/components/popups/*`,
  `src/components/os/*`) and rewire data sources. New UI uses existing `var(--theme-*)` tokens so it looks native.
- **Branding → VORTEX Terminal (mandatory, locked).** Visible "NEO-HEX" strings (header, `<title>`, greetings,
  report footers) become **Vortex Terminal**. Design untouched.

## 3. Simplification — KEEP vs DROP (simple but effective, no drag)

### KEEP (the effective core) — where each lives in the expanded UI

| Real capability | Home in expanded `src/` |
|---|---|
| Real PTY terminal + typed execution | Terminal tab (main surface, existing `TerminalView.tsx` expanded) |
| NL → plan → Guardian → approve/execute (safe/standard/expert) | Terminal tab + new `popups/Approvals.tsx` |
| **Orchestration** (advisory → Guardian → execute → observe → replan → report) | Terminal + Fuzzy tab (real scores) + new `popups/AiOps.tsx` |
| Engagements / scope gate | New `popups/Scope.tsx` |
| Tool registry + host tools live probes | New `popups/Tools.tsx` |
| Artifacts (`/out`) + Reports (observed only) | Existing `/out` tab + Report tab, rewired to real endpoints |
| Tasks (resume/pause/reject) | New `popups/Tasks.tsx` |
| Conversations + Memory (locked: you need these) | New `popups/History.tsx`, `popups/Memory.tsx` (list/search/export + simple save) |
| **Local LLM via llamafile** + fuzzy routing + honest fallback | New `popups/Models.tsx` + real header badges (existing `HeaderBar.tsx` extended) |
| Health/doctor/dashboard facts | New `popups/System.tsx` |
| Audit verify, STOP ALL, offline mode, settings | `popups/System.tsx` + `popups/Settings.tsx` |

### DROP / DEFER from the UI (backend stays, UI stays lean)

- Mobile APK builder UI, desktop `.deb` builder UI (CLI/scripts remain; no buttons in new UI).
- Full Learning/Procedures/Experiences editors (backend tables remain; read-only mini-list later if needed).
- Asset-graph full explorer → honest Tactical Map instead (observed/declared nodes only).
- Plugin-manifest browser, upstream-agent tracking table (builtin council only in v1).
- Old vanilla `frontend/*.js` (archived as `frontend/legacy-vanilla/` for one release after cutover, not shipped).

## 4. Target architecture (simple — same processes, new skin)

```
┌─ src/ React shell (single-file dist/, served by Python backend at /) ────┐
│ Terminal (main) │ Tactical Map │ /out │ Report Gen │ Fuzzy │ Agent Reach │
│ + popups: Tasks · Scope · Tools · Models(llamafile) · System · History · │
│   Memory · Approvals · AI Ops · Settings (+ optional Vortex OS launcher  │
│   overlay with Linux-style icons — same popups, toggleable, off default) │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │ loopback fetch() only (127.0.0.1:8765)
┌───────────────────────────────▼───────────────────────────────────────────┐
│ Python sidecar (single authority, stdlib-only): plans, Guardian, executor, │
│ PTY, store/audit, tools, reports + NEW llamafile provider                 │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │ loopback only
┌───────────────────────────────▼───────────────────────────────────────────┐
│ llamafile server (127.0.0.1, OpenAI-compatible /v1/*) — 1 binary, CPU or  │
│ --n-gpu-layers 99. GGUF import or fused llamafile. Nothing auto-downloads.│
└───────────────────────────────────────────────────────────────────────────┘
```

- **One authority stays Python.** React never executes anything; only calls existing `/api/*` + new `/api/llamafile/*`.
- **No new npm runtime deps** (reuse react/tailwind/lucide already in `src/`).

## 5. UI expansion plan — tabs stay, everything else becomes popups

1. **Keep the 6 existing tabs exactly** (order, labels, icons, animations) in `App.tsx` / `HeaderBar.tsx`.
2. **ADD one `src/components/WindowManager.tsx`** (port of proven `frontend/windows.js` semantics):
   minimize / maximize / close + restore tray + focus z-order + `Esc` close + focus return, themed natively.
3. **ADD `src/components/popups/*`** (each lazy-mounted — zero cost until opened): Tasks, Scope, Tools, Models,
   System, History, Memory, Approvals, AiOps, Settings, Help.
4. **ADD `src/components/os/VortexOsLauncher.tsx`** (locked: build as optional toggle): full-overlay app drawer
   with Linux-style icons + slim dock, opening the same popups. Default view stays the 6-tab look.
5. **EXTEND `HeaderBar.tsx`**: cluster badges flip from fake model names to real installed-model status;
   one launcher button added in existing style. Nothing else moves.

## 6. Real-operations mapping (simulation → real endpoint)

| Existing simulation in `src/` | Real replacement (expand in place) |
|---|---|
| `orchestrateCommand()` fake scenarios | New `src/services/vortexApi.ts` → `POST /api/workspace/turn`, `/api/plan`, `/api/palette`, `/api/operations/:id/approve\|cancel`, `/api/control/stop-all`; `TerminalView.tsx` rendering kept, SSE live output added |
| `virtualFileSystem` + fake `ls/cat/top/ifconfig` | Real PTY (`POST /api/sessions`, `GET /api/sessions/:id/stream` SSE + poll fallback), `/api/history`, `/api/artifacts`, `/api/dashboard`, `/api/doctor` |
| Fake fuzzy 91–99% deliberations | Real `backend/models/fuzzy.py` ranking + AI Ops trace; `FuzzyTab.tsx` renders **real** provider/latency/RAM/Guardian verdict; `fuzzyLogicEngine.ts` math kept for visualization only |
| Hardcoded Tactical Map nodes/CVEs | `GET /api/assets/graph` + `/api/findings` + engagements; honest empty states; node click → scoped plan proposal |
| Hardcoded /out + reports | `GET /api/artifacts`, `/api/reports`, `/api/reports/:id/download`, `/api/search?q=` |
| Fake `LOCAL_MODELS` badges | Real llamafile + GGUF + Ollama status (§7); badges show **installed models only** |
| Fake `AgentReachInspector` levels | Real Guardian risk + scope + `host_tool_access` + tool states (installed/blocked/unavailable) |
| Sounds on fake success | Same `soundEffects.ts`, triggered by **real** exit codes / Guardian verdicts |

## 7. Local LLM via llamafile (free, GitHub, loopback-only)

Single executable serving an **OpenAI-compatible API on loopback**
(`./llamafile -m model.gguf --server --port 8080`, CPU AVX2 or `--n-gpu-layers 99`) [1](https://markaicode.com/howto/llamafile-setup-and-configuration-guide/);
same OpenAI Chat Completions shape as llama.cpp server mode (`POST /v1/chat/completions` on `127.0.0.1`) [2](https://canitrun.dev/guides/llama-cpp-setup/) [3](https://blog.4sapi.com/blog/llama-cpp-local-deployment-guide).
Mozilla-ai publishes versioned binaries under `mozilla-ai/llamafile` releases (latest seen: v0.10.5).

### New backend module: `backend/models/llamafile.py` (mirrors `manager.py` safety patterns)

- **Install (operator-confirmed, never silent, blocked offline):** pinned release binary + published SHA-256,
  enforce size/hash, `chmod +x`, store under `data_root()/llamafile/` (0700). No sudo, no `curl|sh`.
- **Models:** import owner-local `.gguf` **or** fused `*.llamafile`; single resident server at a time.
- **Lifecycle (background thread, pollable):** start on `127.0.0.1:<auto port>`; health via `GET /v1/models`;
  stop/cancel/remove; crash → honest `unavailable`.
- **Advisory-only proxy:** `POST /v1/chat/completions` with short timeouts; planning + Guardian stay authoritative.
- **New endpoints:** `GET /api/llamafile`, `POST /api/llamafile/install|import|server/start|server/stop|
  models/activate|models/remove`, wired into `/api/assist/coverage` + `POST /api/refresh`.
- **Router (`router.py` + `fuzzy.py`, locked hybrid):**
  `llamafile → gguf-direct → ollama → council → deterministic`, with per-call latency feedback.
- **UI:** `popups/Models.tsx` = install/import/start/stop/activate + role badges; header badges real;
  every hint degrades honestly with no model. **Default: one small 3–4B Q4** (locked); 7–8B one-click later.

## 8. Orchestration (not forgotten — it IS the product)

Real flow preserved and surfaced in the expanded `src/`:

1. NL in Terminal (or QuickPrompt chip / Map node action) → `POST /api/workspace/turn`.
2. Backend: **typed plan** (reviewed adapters) → **local-AI advisory** (llamafile→…→council) →
   **independent Guardian** → **engagement scope check**.
3. Low-risk + auto-run policy → executes typed argv; else **`Approvals` popup** waits for you.
4. Live output via SSE/poll; **STOP ALL** kills everything; bounded **replan** (≤2, no duplicates).
5. Evidence hashed + audit-chained; **Reports + /out** update; **Fuzzy tab** shows real consensus inputs.
6. `fallback.used` semantics from `orchestrate.py` intact — no fake "secondary checked" text.

## 9. No-drag performance budget

- **No new npm runtime deps**; popups lazy-mounted; lists capped (≤120 rows + search); artifacts paginated.
- MatrixRain: cap DPR 1.5, pause when hidden/minimized, auto-degrade if FPS < 40 for 2s; rain/CRT/sound toggles keep working.
- Reuse SSE + poll fallback; no polling < 5s; dashboard/probes cached 30–60s; `POST /api/refresh` operator-triggered only.
- Backend stdlib-only stays; llamafile is a separate OS process (no GIL drag); advisory calls time out fast (2–8s), never block execution.
- Acceptance: cold load ≤ 2s (rain ON), popup open ≤ 150ms, keystroke echo unaffected by rain.

## 10. Branch, merge & testing strategy

1. **All implementation on `arena/01a09b13-linux-vortex-terminal`**, which now contains patch-2's tree
   (fast-forwarded to `35369b6`). `mrtc-solutions-patch-2` itself is left untouched; nothing is pushed anywhere
   except this session branch.
2. **Cutover:** Python backend serves built `dist/index.html` at `/` (flag `VORTEX_UI=neohex` during build,
   default after gates); old vanilla `frontend/*.js` → `frontend/legacy-vanilla/` for one release.
3. **Gates before PR to `main`:** restored `npm test` (431 Python + JS suites incl. new `test_llamafile.py`
   with mocked loopback server), `npm run lint` (extended to `tsc --noEmit` + `vite build`), `final_gates.py`
   10/10, `tests/linux_acceptance.sh`, live sidecar probe (`/api/plan|palette|workspace/turn|llamafile|
   artifacts|reports|assets/graph`), perf budget (§9).
4. **Merge:** PR from `arena/01a09b13-linux-vortex-terminal` → `main`. Tag release, keep this plan in `docs/`.

## 11. Implementation phases — expanding the existing code (after you approve)

- **Phase 0 — Repair + scaffold (0.5 day):** restore merged root `package.json` (vortex scripts + `dev/build/preview`,
  `electron` + vite/tailwind deps; regenerate lockfile); rebrand strings to Vortex Terminal; ADD
  `src/services/vortexApi.ts`; prove `vite build` + Python serving `dist/` behind `VORTEX_UI=neohex`. Design untouched.
- **Phase 1 — llamafile backend (1–2 days):** ADD `backend/models/llamafile.py` + endpoints + router/fuzzy order +
  `tests/test_llamafile.py` (mock server); ADD `popups/Models.tsx`; EXTEND header badges to real status.
- **Phase 2 — Real terminal turn (1–2 days):** rewire `TerminalView.tsx` from `orchestrateCommand()` to
  `vortexApi.turn()`; ADD `WindowManager.tsx` + `popups/Approvals.tsx`; SSE live output; STOP ALL; delete fake delays.
- **Phase 3 — Popups (2–3 days):** ADD Tasks, Scope, Tools, System, History, Memory, AiOps, Settings; honest empty states.
- **Phase 4 — Honest Map/out/Reports/Fuzzy (1–2 days):** rewire existing `TacticalMap`, `OutDirectoryExplorer`,
  `ReportGeneratorModal`, `FuzzyTab`, `AgentReachInspector` to real endpoints; remove hardcoded data.
- **Phase 5 — Vortex OS overlay (0.5–1 day, locked):** ADD `os/VortexOsLauncher.tsx` grid + dock (optional toggle).
- **Phase 6 — Cutover + gates (1 day):** default `VORTEX_UI=neohex`, archive legacy, run all gates + perf check.
- **Phase 7 — PR to `main`:** changelog, user-guide update, release notes (what was dropped and why).

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| llamafile download flaky/offline | Pinned version + hash + retry/cancel; offline blocks cleanly; GGUF-direct + council still work |
| Big models drag CPU boxes | Default small 3–4B; single resident model; RAM-fit fuzzy guard; GPU offload optional |
| Single-file bundle grows | No new deps; lazy mount; caps; rain auto-degrade; perf acceptance gate |
| Scope creep from old UI | §3 DROP list enforced; anything outside KEEP needs your explicit approval |
| patch-2's clobbered lockfile | Phase 0 regenerates via `npm install`; verified by `npm test` + `npm run lint` before any feature work |

## 13. Decisions — LOCKED IN (your answers, 2026-09-13)

1. **Popup scope → Minimal + Conversations/Memory.** Tasks, Scope, Tools, Models, System, History/Conversations,
   Memory (list/search/export + simple save), Approvals, AI Ops, Settings. Full Learning/Procedures editors deferred.
2. **LLM fallback → Hybrid.** llamafile → GGUF-direct → Ollama (optional) → council → deterministic.
3. **Default model → Small 3–4B Q4.** 7–8B stays a one-click upgrade.
4. **Vortex OS launcher → Yes, as optional toggle.** Default view stays the 6-tab look.
5. **Branding → VORTEX Terminal (mandatory).** All visible "NEO-HEX" strings rebranded; design untouched.
6. **Base → patch-2's tree, expanded in place** on this session branch (imported via fast-forward to `35369b6`).

---
*Sources: llamafile single-binary server [1](https://markaicode.com/howto/llamafile-setup-and-configuration-guide/);
llama.cpp OpenAI-compatible server [2](https://canitrun.dev/guides/llama-cpp-setup/) [3](https://blog.4sapi.com/blog/llama-cpp-local-deployment-guide);
mozilla-ai/llamafile releases (v0.10.5 latest seen).*
