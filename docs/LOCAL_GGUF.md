# Local GGUF models (primary on-device AI)

VORTEX answers first from your own GGUF files, on your own CPU, with no
network involved. Everything else — Ollama loopback, the agent council, the
deterministic core — is secondary fallback chosen by fuzzy routing.

## The two curated models

| File | Role | Advisory work |
|---|---|---|
| `Llama-3.2-3B-Instruct-Q4_K_M.gguf` | fast + primary | conversation, explanation, summaries |
| `Qwen2.5-3B-Instruct-Q4_K_M.gguf` | planner + specialist | planning, analysis, verification |

Place both files in `~/linux-vortex-terminal/models/` (or set
`VORTEX_MODELS_DIR`, or `models_dir` in Settings). VORTEX validates the GGUF
magic bytes before trusting any file and reports per-file size, family,
quantization, and 8 GB RAM fit in the Models view.

## 8 GB RAM / ~2 GHz tuning (automatic)

* **One model resident at a time** — loading the planner unloads the fast
  model first (single-slot policy).
* **2048-token context**, ≤4 threads, 128-token batches, memory-mapped
  weights, no `mlock`. A 3B Q4_K_M file (~2 GB) stays near ~2.5–3 GB
  resident, leaving headroom for the OS and sidecar.
* **Bounded calls** — plan-phase advisory is capped so a slow CPU never
  stalls a turn; the fuzzy router demotes a delaying primary to the
  secondary automatically (`backend/models/fuzzy.py`).

Override via Settings: `gguf_ctx` (512–8192), `gguf_threads` (1–8),
`gguf_timeout_seconds` (2–120).

## Inference engine (pick one)

1. **llama-cpp-python** (recommended): `pip install llama-cpp-python`
   in your user environment. VORTEX detects it automatically — no config.
2. **llama-cli binary** (`llama-cli`, `llama.cpp`, `llamacpp`, or `llama`)
   on a safe PATH. VORTEX runs it with typed argv, a timeout, and
   process-group cleanup.

With neither installed, VORTEX reports GGUF `unavailable` with guidance and
keeps working through Ollama / council / deterministic layers. Model output
is never simulated.

## Verify on your machine

```bash
./vortex model status --json   # providers.gguf.state should be "healthy"
./vortex model test --json     # real smoke completion, exit 0 when answered
./vortex serve --bind-host 127.0.0.1 --bind-port 8765
# Models view → "Local GGUF models" panel shows files, roles, RAM fit
```

Roles are assigned per file (`USE FOR ROLE` in the Models view or
`POST /api/models/gguf/activate`). Ollama roles (`model_*`) stay separate:
Ollama is the secondary pool and keeps its own preferences.

## Fallback order (fuzzy)

1. GGUF primary → 2. Ollama loopback → 3. agent council (deterministic,
   no generated text) → 4. deterministic VORTEX core.

`./vortex model status` shows the live `fuzzy` winner, ranking, and reason.
Every real call feeds latency back into the router, so a primary that
starts delaying or failing yields to the secondary on the next decision.

## Every function is AI-assisted

Plan, explain, palette, search, dashboard, assets, health, deps, replan,
report, memory, engagement, session, interpret, verify, and error paths all
carry an `ai_hint` (see `GET /api/assist/coverage`). Hints are explanatory
only: planning stays deterministic, Guardian stays independent, and every
function works unchanged when no model answers.
