# Local GGUF models (not in Git)

These files are **too large for GitHub and for the `.deb`**. Place them here
(or in `$VORTEX_MODELS_DIR`, or `~/linux-vortex-terminal/models/`) after you
install Vortex Terminal. Then open **Dependencies → Refresh** or **Models →
REFRESH**.

## Curated pair

| File | Role | Typical size |
|---|---|---|
| `Llama-3.2-3B-Instruct-Q4_K_M.gguf` | Fast conversation | ~2 GB |
| `Qwen2.5-3B-Instruct-Q4_K_M.gguf` | Planner / analysis | ~2 GB |

Operator-manual sources (review the model card and license first):

- https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF
- https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF

Vortex Terminal **does not** fetch these URLs for you. Copy the `.gguf` into
this directory, or use **Models → ADD LOCAL MODEL**.

## Engine (pick one)

1. `pip install --user llama-cpp-python`
2. A `llama-cli` / `llama.cpp` binary on a safe PATH
3. Managed **llamafile** from the Models popup (operator-confirmed)

Without an engine, GGUF stays `unavailable` and the app still runs.

## Hardware

**Minimum:** 2 GB RAM, 2 GHz i5-class CPU. That is a floor, not a cap.
Hosts with more RAM automatically use a larger context (see
`docs/LOCAL_GGUF.md`).
