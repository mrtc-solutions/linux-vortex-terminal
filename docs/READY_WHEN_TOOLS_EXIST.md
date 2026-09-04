# Ready when tools exist — current state

**Product:** VORTEX (Verified Orchestration, Reasoning, Testing, Execution & eXperience)  
**Updated:** 2026-09-04  
**Goal:** Define the honest boundary between code that is already implemented and host software that must still exist on a machine you administer.

This document is intentionally conservative. Guardian, typed argv, engagements,
no silent install, and no password capture remain binding.

## What is true now

1. Installing VORTEX does **not** install host packages, Ollama, models, Docker,
   or third-party agents.
2. **Dependencies → INSTALL** builds either:
   - a **reviewed apt plan** for mapped distro packages, or
   - an **operator-manual proposal** for things VORTEX will not auto-install.
3. Root-required reviewed plans are executed separately with:

   ```bash
   sudo vortex --allow-root run <plan-id>
   ```

4. Local-AI-first behavior is now implemented as **advisory-only** loopback
   Ollama routing. It never authorizes execution and never leaves loopback.
5. Dependency inventory now distinguishes:
   - `installed` = trusted and ready
   - `blocked` = present on the host, but flagged for path-safety review
   - `absent` / `unavailable` = not present or not healthy
6. The dependency and health surfaces now cover:
   - Node.js / npm / pnpm / yarn / Go
   - Docker / Podman runtime presence
   - reviewed wordlists
   - Ollama runtime
   - recommended Ollama model pool

## Current definition of “good to go”

On a Debian/Kali host you administer, VORTEX is ready for real use when the host
has the tools you need and VORTEX reports them honestly.

| Host prerequisite | VORTEX behavior today |
|---|---|
| coreutils, iproute2, procps, git, ssh, systemd | Real typed plans + real execution after Guardian |
| `nmap`, `curl`, `nuclei`, `nikto`, `amass`, `ffuf`, `gobuster` + engagement + reviewed wordlist | Real typed plans + real execution, otherwise honest UNAVAILABLE |
| reviewed apt package available | Reviewed install plan only; root-required execution remains explicit |
| wordlist package missing | Reviewed apt proposal for distro wordlists such as `seclists` |
| Ollama on loopback with recommended models | Advisory local-AI routing, model status, health, and benchmark work for real |
| Ollama missing or unhealthy | Honest `runtime:ollama` / `data:ollama-models` unavailable state + manual guidance |
| agent CLI missing | Honest missing / requires configuration |
| Docker / Podman missing | Honest unavailable runtime / probe-only surfaces |

## What the recent audit completed

The recent implementation pass closed the main “looks like it failed to install”
confusion points.

### 1) Install flow is now explicit end to end

- `scripts/install-user.sh` installs only a launcher.
- `vortex install --user` installs only a launcher.
- There is no hidden general package installer.
- Apt-backed dependencies become reviewed plans, not immediate installs.
- Ollama and model pulls remain operator-controlled.

### 2) Dependency reporting is more accurate

- Node/npm/yarn discovered in unsafe or user-writable locations are now shown as
  **present but blocked for review**, not falsely counted as missing installs.
- Those items retain `security_flags` so the operator can see why VORTEX did not
  silently trust them.
- Dependency inventory now follows the saved Ollama endpoint setting instead of
  assuming only the hardcoded default endpoint.

### 3) Local AI is implemented but bounded

When the loopback runtime is healthy, VORTEX can:

- show model status
- benchmark local advisory routing
- expose dependency/runtime/model-pool status
- attach advisory-only Local AI summaries to plan/result analysis

It still cannot:

- approve commands
- invent execution authority
- bypass Guardian
- send prompts to non-loopback Ollama endpoints

## Recommended local AI model pool

Required recommended models:

- `phi4-mini:3.8b`
- `qwen3:4b`
- `llama3.2:3b`

Optional specialist:

- `gemma3:4b`

Typical operator steps after installing Ollama manually:

```bash
ollama serve
curl http://127.0.0.1:11434/api/version
ollama pull phi4-mini:3.8b
ollama pull qwen3:4b
ollama pull llama3.2:3b
# optional
ollama pull gemma3:4b
curl http://127.0.0.1:11434/api/tags
```

## Remaining real gaps

These are still honest product limits, not fake-passed features:

1. Reviewed non-interactive consult execution for third-party agent CLIs
2. Reviewed Docker/Podman sandbox **execution** beyond probe/inspect/log surfaces
3. Any future product decision on sqlmap / msf execution adapters
4. Real root-approved apt/systemd mutation acceptance on a disposable/admin host
5. A real default Ollama runtime at `http://127.0.0.1:11434` on this sandbox host

## How to use the install path today

```bash
./vortex install --user
vortex deps --json
vortex model status --json
# UI: Dependencies → INSTALL <item>
# review the typed plan or operator proposal
sudo vortex --allow-root run <plan-id>
```

## Bottom line

The current VORTEX codebase is no longer blocked by an imaginary “tool
installer” feature. The remaining gap is the real host environment:

- if the tool exists and is within a reviewed path/runtime boundary, VORTEX can
  use it through reviewed adapters where implemented,
- if the tool does not exist, VORTEX says so honestly,
- if the tool exists in an unsafe path, VORTEX shows it as present but blocked,
- if installation requires root or upstream/manual steps, VORTEX proposes those
  steps without pretending it already performed them.
