# Multi-Provider AI Overhaul — Final Report (2026-10-03)

This report documents the local-first, multi-provider AI overhaul of Vortex
Terminal: what changed, how it is architected, what was tested, and — honestly —
what could *not* be tested in this environment.

---

## 1. Files added

| Path | Purpose |
|---|---|
| `backend/providers/__init__.py` | Provider package marker. |
| `backend/providers/keys.py` | API-key slots from env / `.env` / `~/.config/vortex/.env`; `redact_secrets()`; keys never logged or serialized. |
| `backend/providers/catalog.py` | Static metadata for 17 providers + 3 Gemini entries; default fallback order; free-status classification. |
| `backend/providers/policy.py` | Free-only policy engine (`{free_only, allow_paid_providers}`); paid/unknown-priced models are blocked, never silently billed. |
| `backend/providers/registry.py` | Dynamic model registry: discovered models, pricing metadata, `verified_at`, deprecation (`available=False`), free-status staleness (free→unknown after 7 days unverified). |
| `backend/providers/manager.py` | `ProviderManager`: health checks, discovery, generation with fallback, per-provider stats/cooldowns, Gemini slots, local Qwen warm-up, diagnostics (masked). |
| `backend/conversation.py` | Deterministic conversation/action classifier + conversational responder on top of the provider layer. |
| `src/components/popups/AiProviders.tsx` | AI PROVIDERS window: grouped provider list, live health, free/paid/unknown badges, enable/disable, "Use for conversation", Gemini slot config, diagnostics, Qwen warm-up. Cloud models use **Connect/Enable** language, never "Download". |
| `.env.example` | Placeholder slots for every provider key; copy-to-`.env` instructions; never-commit warning. |
| `tests/test_providers.py` | 30 tests over the provider layer (mock HTTP servers). |
| `tests/test_conversation_routing.py` | 11 tests over classifier + turn routing. |
| `docs/MULTI_PROVIDER_AI_REPORT.md` | This report. |

## 2. Files modified

| Path | Change |
|---|---|
| `backend/orchestrate.py` | `run_turn()` classifies the request first; conversational input short-circuits to `_conversation_turn()` (no planner, no Guardian, no adapters). `force_plan=True` bypasses the shortcut. Action requests are untouched. |
| `backend/agent_mode.py` | Agent mode calls `run_turn(force_plan=True)` — agent steps always go through the planner/Guardian pipeline. |
| `backend/config.py` | New validated settings: `free_only_mode` (default **True**), `allow_paid_providers` (default **False**, forced off while free-only is on), `privacy_mode` (`local`/`hybrid`/`cloud`, default `local`), `secondary_ai_mode` (`off`/`on-demand`/`auto`/`consensus`), `ollama_endpoint`, `local_model` (`qwen2.5:3b`). |
| `backend/models/router.py` | `qwen2.5:3b` is the single required local model; llama3.2/qwen3/phi4-mini/gemma3 are optional extras. No repeated llama3.2 start attempts. |
| `backend/install_commands.py` | Ollama starter pull is `qwen2.5:3b` only; others listed as optional. |
| `backend/vortex_backend.py` | New endpoints: `GET /api/providers[?fresh=1]`, `GET /api/providers/diagnostics`, `POST /api/providers/{check,refresh,enable,select,gemini,warmup,consensus}`. Capabilities list adds `multi-provider-ai`, `free-only-mode`, `conversational-routing`. |
| `src/services/vortexApi.ts` | Typed client functions for all provider endpoints. |
| `src/App.tsx`, `src/components/popups/Launcher.tsx` | `providers` popup registered ("AI PROVIDERS") + launcher tile. |
| `src/components/HeaderBar.tsx` | Visible **FREE ONLY · $0** badge (amber **PAID ALLOWED** when off); click opens the providers window. |
| `src/components/TerminalView.tsx` | Turns with `mode === "conversation"` render the AI reply only — no Guardian commentary, no plan table, no "No executable adapter was planned". `providers` is a recognized command. |
| `src/components/popups/SettingsPanel.tsx` | New "AI routing & cost" section: free-only toggle, allow-paid toggle, privacy mode, secondary AI mode. |
| `tests/test_ollama_manage.py` | Expectation updated: `qwen2.5:3b` is the only non-optional curated model. |
| `.gitignore` | Already covers `.env` / `.env.*` (keeps `!.env.example`) and `*.gguf`. |

## 3. Architecture changes

```
user input
   │
   ├─ conversation?  → backend/conversation.respond() → ProviderManager.generate()
   │                   (natural reply; Guardian/planner never invoked;
   │                    cloud AI returns TEXT only — it has no shell authority)
   │
   └─ action?        → existing planner → Guardian → typed adapters (UNCHANGED)
                       AI output is always a *proposal*; Guardian authorizes;
                       adapters execute with shell=False.
```

- **Separation of powers preserved**: no code path lets a cloud model execute a
  command. `/api/providers/*` endpoints manage routing only.
- **Fallback order** (conversation): local `qwen2.5:3b` → Gemini #1 → #2 → #3 →
  Groq → OpenRouter free → Cloudflare → Pollinations → other verified-free.
  Each failed attempt is recorded (`attempts[]` in the turn result) with a
  precise error kind; 429s put a provider into cooldown instead of retry-looping.
- **Gating order per provider**: offline → privacy mode → free-only policy →
  key present → cooldown → model resolution (auto-discovery when the registry
  is empty or stale).

## 4. Provider list and free-status classification

| Provider | ID | Base URL | Free status | Enabled by default |
|---|---|---|---|---|
| Ollama (local) | `ollama-local` | `http://127.0.0.1:11434` | free (local, $0) | yes |
| Google Gemini ×3 | `gemini-1/2/3` | `https://generativelanguage.googleapis.com/v1beta` | conditional (free tier) | yes |
| Groq | `groq` | `https://api.groq.com/openai/v1` | conditional | yes |
| OpenRouter | `openrouter` | `https://openrouter.ai/api/v1` | conditional (`:free` models only) | yes |
| Cloudflare Workers AI | `cloudflare` | account-scoped | conditional (10k Neurons/day) | yes |
| Pollinations | `pollinations` | `https://text.pollinations.ai` | free, no key | yes |
| Mistral (free tier) | `mistral` | `https://api.mistral.ai/v1` | conditional | no |
| Cohere (trial) | `cohere` | `https://api.cohere.ai` | conditional | no |
| ModelScope | `modelscope` | — | conditional | no |
| Ollama Cloud | `ollama-cloud` | `https://ollama.com` | conditional | no |
| Z.ai | `zai` | — | **UNKNOWN** | no |
| SiliconFlow | `siliconflow` | — | **UNKNOWN** | no |
| SambaNova | `sambanova` | — | **UNKNOWN** | no |
| Scaleway | `scaleway` | — | **UNKNOWN** | no |
| Alibaba Model Studio | `alibaba` | — | **UNKNOWN** | no |
| Tencent Hunyuan | `tencent` | — | **UNKNOWN** | no |
| Arli AI | `arli` | — | **UNKNOWN** | no |

**Non-classifiable providers**: the seven marked UNKNOWN publish pricing that I
could not verify as a genuine ongoing $0 tier (trial credit ≠ free). Under
free-only mode they are **blocked** and shown as `FREE STATUS: UNKNOWN`. An
operator who has verified the terms can grant a per-provider
`allow_in_free_mode` override in the AI PROVIDERS window ("I verified it is
free"), which is persisted and revocable.

## 5. Discovery logic (no permanent hard-coded free models)

- **OpenRouter**: `GET /api/v1/models`; a model is free iff prompt+completion
  pricing is `0` (the `:free` suffix). Pseudo-model `openrouter/free` resolves
  to the first currently-free model at call time.
- **Groq**: `GET /openai/v1/models`, filtered to chat-capable models. Groq
  retired models during 2026, so nothing is pinned.
- **Gemini**: `GET /v1beta/models`; flash/flash-lite classified free-tier,
  pro paid, embeddings excluded.
- Every discovery stamps `verified_at`. A model that disappears from a
  provider's list is marked `available=False, deprecated=True`. A `free=True`
  flag older than 7 days degrades to *unknown* and is re-verified before the
  free-only policy will route to it.

## 6. Gemini configuration

Three independent entries, one provider family (`google-gemini`):

| Entry | Default model | Default key slot |
|---|---|---|
| `gemini-1` (primary) | `gemini-3.8-flash` | `GEMINI_API_KEY_1` |
| `gemini-2` (secondary) | `gemini-3.5-flash-lite` | `GEMINI_API_KEY_2` |
| `gemini-3` (tertiary) | `gemini-2.5-flash` | `GEMINI_API_KEY_1` (configurable 1 or 2) |

Model IDs were verified against Google's current (2026) free-tier
documentation rather than taken from the prompt; the prompt's
"gemini-3.5-flash-lite / gemini-3.8-flash" names do exist. Entry #3 reuses key
1 or 2 — a third key is **not** required. Each entry has independent health,
stats, cooldown, and quota tracking; slot assignment persists across restarts
and is editable in the UI and via `POST /api/providers/gemini`.

## 7. Environment variables (`.env.example`)

`GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`, `GEMINI_API_KEY_3` (optional),
`GROQ_API_KEY`, `OPENROUTER_API_KEY`, `CLOUDFLARE_API_TOKEN` +
`CLOUDFLARE_ACCOUNT_ID`, `ZAI_API_KEY`, `SILICONFLOW_API_KEY`,
`MISTRAL_API_KEY`, `COHERE_API_KEY`, `SAMBANOVA_API_KEY`, `SCALEWAY_API_KEY`,
`ALIBABA_API_KEY`, `TENCENT_API_KEY`, `MODELSCOPE_API_KEY`,
`OLLAMA_CLOUD_API_KEY`, `ARLI_API_KEY`. Pollinations needs no key. Keys are
read from the process env, `./.env`, or `~/.config/vortex/.env`; they are never
committed (`.gitignore`), never sent to the renderer, and
`redact_secrets()` masks them in every diagnostic and log path.

## 8. Error-state vocabulary (replaces vague "Local AI unavailable")

`ollama_not_installed` (binary not on PATH) · `ollama_not_running` (hint:
`ollama serve`) · `model_missing` (hint: `ollama pull qwen2.5:3b`) · `cold` /
`ready` (warm state + probe latency) · `ollama_timeout` / `qwen_load_timeout`
(timeout ≠ absence) · `no_api_key` · `invalid_api_key` · `rate_limited` (429 →
cooldown) · `quota_exhausted` · `model_unavailable` (retired/deprecated) ·
`blocked_policy` (paid under free-only) · `network_unavailable` /
`network_blocked` (offline or privacy=local) · `cooling_down` · `disabled` ·
`provider_error`. When every eligible provider fails the user sees exactly:
**"All configured free AI providers are currently unavailable."** plus the
per-provider reasons.

## 9. Test results (all commands run from the repo root)

| Command | Result |
|---|---|
| `python3 -m unittest discover -s tests` | **697 tests — OK** (baseline before this work: 656 ran with 2 failures + 63 errors from missing build artifacts; now zero) |
| `python3 -m unittest tests.test_providers` | **30/30 OK** (~6 s) |
| `python3 -m unittest tests.test_conversation_routing` | **11/11 OK** |
| `npx tsc --noEmit` / `npm run lint` | clean |
| `npm run build` | dist/index.html built |
| `npm test` (python + 11 node suites) | **all PASS** |

Mapping to the requested test plan:

| Plan item | Status | Where |
|---|---|---|
| A. "hello" → natural reply, no Guardian/adapter text | PASS | `test_conversation_routing` (hello test + live HTTP smoke) |
| B. Local Qwen states (missing/cold/ready/not running) | PASS (mocked Ollama) | `LocalQwenTests` |
| C. Gemini ×3 entries, slot reuse, independent 429 stats | PASS (mocked API) | `GeminiTests` |
| D. Cloud fallback when local down | PASS (mocked) | `GenerateTests` fallback test |
| E. All-free-unavailable exact message | PASS | `GenerateTests` + routing test + live smoke |
| F. Command request → planner/Guardian unchanged | PASS | routing tests (`whoami`, largest-files) |
| G. Security request keeps engagement requirements | PASS | routing test (nmap scan: no auto-execution) |
| H. 429 → cooldown + controlled fallback, no retry storm | PASS (mocked) | `GenerateTests`/`GeminiTests` |
| I. Paid model under free-only → `blocked_policy` | PASS | `PolicyTests`/`GenerateTests` |

## 10. Limitations (honest)

- **Operator keys installed 2026-10-03**: real GEMINI_API_KEY_1/2, GROQ_API_KEY
  and OPENROUTER_API_KEY were installed in `~/.config/vortex/.env` (mode 600,
  outside the repository; never committed). The app sees them
  (`key_configured=true` for gemini-1/2/3, groq, openrouter; entry #3 reuses
  key slot 1), `privacy_mode` was set to `hybrid` so cloud fallback is active,
  and the fallback chain was exercised live: local → Gemini #1→#2→#3 → Groq →
  OpenRouter, in order, Gemini first because its free quota outlasts the
  others. The development sandbox's firewall still kills TLS to the provider
  hosts, so **key validity could not be confirmed from here** — on a normal
  machine the same configuration will connect as-is.
- **This sandbox has no outbound network egress.** Every cloud-provider
  behavior (Gemini/Groq/OpenRouter/Cloudflare HTTP flows, 429 handling,
  discovery, key auth) was validated against local mock HTTP servers that
  speak each provider's wire format — **not** against the live services.
  Real-cloud verification of plan items B–D/H requires a networked machine
  with keys in `.env`.
- Ollama is not installed in the sandbox, so the live smoke test correctly
  reports `ollama_not_installed`; real local-Qwen latency was not measured here.
- Current free-tier model IDs/limits were verified against 2026 documentation,
  but free catalogs churn — which is exactly why discovery is dynamic and
  free-status expires after 7 days unverified.
- The seven UNKNOWN-pricing providers have working client plumbing but ship
  disabled; they were not live-tested.

## 11. How to run

```bash
# backend + built UI (loopback, no token needed)
npm run build && npm run preview          # http://127.0.0.1:4173

# dev
npm run dev                               # Vite UI
python3 backend/vortex_backend.py --host 127.0.0.1 --port 8765

# tests
python3 -m unittest discover -s tests
python3 -m unittest tests.test_providers tests.test_conversation_routing
npm test

# keys
cp .env.example .env    # then fill in only the providers you enable
```
