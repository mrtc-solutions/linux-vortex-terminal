# Vortex Terminal

**Verified Orchestration, Reasoning, Testing, Execution & eXperience**

Linux-native, local-first, multi-provider AI cybersecurity and operations workbench.

---

## Overview

**Vortex Terminal** is a local-first AI terminal and operations environment for Linux. It turns natural-language operational objectives into inspectable, deterministic execution plans, evaluates them with an independent security **Guardian**, runs typed commands through reviewed adapters, and records observed evidence with cryptographic integrity.

Vortex features a **dual-path conversation & execution architecture**:
1. **Conversational Requests** ("hello", "what is Docker?", "explain TLS 1.3") route directly through a multi-provider AI layer (local Qwen 2.5 3B primary, free cloud tiers fallback) for natural, immediate responses without unnecessary command planning or Guardian overhead.
2. **Action & System Requests** ("check disk usage", "list listening ports", "audit SUID binaries") route through the deterministic Planner, Guardian authorization authority, and reviewed adapters. The AI model may propose actions, but it **never directly executes shell commands**.

> **Authorized Use Only.** Vortex Terminal is designed for systems, networks, and artifacts you own or are explicitly authorized to assess.

---

## Features

* **Primary Local AI (Qwen 2.5 3B):** Local-first, offline inference via loopback Ollama (`http://127.0.0.1:11434`). Fully private, $0 cost forever, zero API keys required.
* **Multi-Provider Cloud AI:** Integrated support for 30+ cloud AI providers discovered via the `awesome-freellm-apis` catalogue.
* **Strict Free-Only Mode (`FREE_ONLY_MODE=true`):** Built-in cost protection guaranteeing $0 operation. Paid models, unverified pricing, and trial overage risks are automatically blocked.
* **Three-Model Gemini Architecture:** Configurable `Gemini #1`, `Gemini #2`, and `Gemini #3` logical slots served by up to 3 independent API keys with Flash/Flash-Lite free-tier optimization.
* **Multi-Model Fallback & Cooldowns:** Automatic graceful degradation across local and verified free cloud providers with intelligent cooldown handling on rate limits (HTTP 429) or quota exhaustion.
* **Multi-Model Consensus & Agent Council:** On-demand or automatic multi-model council for complex reasoning, planning critique, code review, and synthesis.
* **Guardian Security Authority:** Deterministic policy engine that evaluates execution risk, enforces scope constraints, and blocks dangerous system mutations.
* **Cloud Privacy & Secret Redaction:** Automatic stripping of API keys, Bearer tokens, private keys, `.env` values, and credentials before any prompt is transmitted to cloud models.
* **Terminal & Host Adapters:** Safe, typed adapters for system inspection, process monitoring, network enumeration, and cybersecurity tools (e.g. nmap, ss, ps, journalctl).
* **Memory & Knowledge Base:** Persistent local SQLite database recording tasks, plans, execution evidence, procedures, and conversation history.
* **Filesystem & Git Integration:** Real-time workspace tracking, `/out` directory artifact retention, and Git repository awareness.

---

## AI Architecture

```text
                                  VORTEX
                                     |
                             Conversation Router
                                     |
                 +-------------------+-------------------+
                 |                                       |
           Conversation                                Action
                 |                                       |
                 v                                       v
    Historical Answer Intelligence                    Planner
                 |                                       |
       +---------+---------+                             v
       |                   |                          Guardian
       v                   v                             |
  Historical          New Cloud                          v
  Candidates          Candidates                      Adapter
       |                   |                             |
       +---------+---------+                             v
                 |                                    Execute
                 v                                       |
          Candidate Scoring                              v
                 |                               Observed Evidence
                 v
       Local Qwen Arbitrator
       (Evidence Comparison)
                 |
        +--------+--------+
        |        |        |
        v        v        v
     History   Cloud   Synthesis
        |        |        |
        +--------+--------+
                 |
                 v
           Final Response
```

---

## Historical Answer Intelligence & Candidate Arbitration

Vortex Terminal does not assume that a newly generated cloud answer is automatically superior to a previous solution. Sometimes a historical response in conversation memory is more reliable, specifically because it incorporates **verified local environment facts**, **successful command executions**, or **user-confirmed results**.

Therefore, Vortex treats **historical answers** and **newly generated AI answers** as **competing candidates**, evaluated by the local **Qwen 2.5 3B** arbitrator.

```text
CURRENT USER REQUEST
        |
        v
REQUEST UNDERSTANDING
        |
        +----------------------------+
        |                            |
        v                            v
HISTORICAL RETRIEVAL            NEW AI CANDIDATES
        |                            |
        v                            v
Historical Answer 1             Cloud Answer 1 (Gemini)
Historical Answer 2             Cloud Answer 2 (Groq)
Historical Answer 3             Cloud Answer 3 (OpenRouter)
        |                            |
        +-------------+--------------+
                      |
                      v
          9-DIMENSIONAL CANDIDATE SCORING
                      |
                      v
            LOCAL QWEN ARBITRATOR (`qwen2.5:3b`)
                      |
            +---------+----------+
            |         |          |
            v         v          v
         History    Cloud    Synthesis
            |         |          |
            +---------+----------+
                      |
                      v
         FINAL RESPONSE & LINEAGE TREE
```

### 1. The 9-Dimensional Scoring Framework

Every candidate (both retrieved from history and newly generated by cloud LLMs) is scored across 9 distinct dimensions:

| Dimension | Description | Base Weight (Technical) | Base Weight (Explanatory) |
| :--- | :--- | :---: | :---: |
| **Relevance** | Semantic and lexical overlap with the current query intent | 15% | 25% |
| **Correctness** | Factual accuracy, absence of structural errors and syntax validity | 15% | 30% |
| **Evidence** | Backed by concrete output digests, verified files, and logs | 20% | 10% |
| **Observed Outcome** | Real Linux execution state (exit code 0, goal achieved, reward = 1.0) | 25% | 0% |
| **Context Match** | Compatibility with host OS (Debian), arch (x86_64), and RAM (4GB) | 15% | 5% |
| **Freshness** | Temporal validity with exponential decay on volatile API versions | 5% | 10% |
| **Completeness** | Coverage of all sub-questions and operator constraints | 3% | 15% |
| **Consistency** | Absence of internal contradictions or conflicting statements | Folded | Folded |
| **User Feedback** | Boosted by past positive acceptance ("That worked", 5★ rating) | 2% | 5% |

### 2. Arbitration Decision Modes

The local Qwen arbitrator evaluates the normalized candidates and selects one of three definitive outcomes:

#### Outcome A: History Wins (`historical`)
* **Scenario:** The user asks why their model is slow. A past verified answer notes that the host has 4GB RAM and context should be reduced to 2048, while a cloud model generically suggests upgrading to a 70B parameter model on 64GB RAM.
* **Decision:** Historical answer wins ($96.5$ vs $72.0$). Vortex returns the verified local answer without making redundant cloud calls.

#### Outcome B: Cloud Wins (`cloud`)
* **Scenario:** The user asks for the current API endpoint of a cloud provider. History contains a deprecated 2024 endpoint, while the newly queried cloud candidate provides the updated v1 specification.
* **Decision:** Cloud answer wins ($94.0$ vs $55.0$) due to superior freshness and currency.

#### Outcome C: Evidence Synthesis (`synthesized`)
* **Scenario:** A near-tie occurs (score difference $\le 5.0$). History contains verified local socket configuration (`http://127.0.0.1:11434`), while the cloud candidate contains updated API documentation (`GET /api/tags`).
* **Decision:** Qwen synthesizes both into a unified, evidence-based response, marking `historicalContribution: "synthesized"`.

### 3. Ground-Truth Reinforcement Loop

* **POMDP Execution Linkage:** When an actionable task runs, the observed exit codes and rewards are recorded in the `candidate_feedback` store.
* **Automatic Confidence Adjustment:** Succeeded operations (`exit_code = 0`) increase the confidence of associated historical answers; failed operations automatically apply confidence penalties.
* **Provenance & Lineage:** Every final message preserves an inspectable lineage tree tracing from the final response back through candidate scores to the original task and operation digest.

---

## Local AI Architecture

Vortex Terminal is engineered with a **local-first philosophy**:

* **Primary Local Model:** `qwen2.5:3b` running on Ollama (`http://127.0.0.1:11434`).
* **Why Qwen 2.5 3B?** Qwen 2.5 3B provides an optimal balance of concise reasoning, accurate coding assistance, low memory consumption (usable in ~2 GB RAM), and fast token generation on commodity Linux CPUs without requiring a dedicated GPU.
* **Ollama Integration:** Vortex probes Ollama via `GET /api/tags` and `/api/ps` for live model discovery, warm/cold state detection, and resource-aware context management.
* **Llama Optional:** `llama3.2:3b` and other models are completely optional extras. Vortex does not require Llama to run and will never loop or fail if Llama is absent.

---

## Free AI Discovery Catalogue

Vortex integrates provider discovery metadata referencing the open-source catalogue:

* **Repository:** [`open-free-llm-api/awesome-freellm-apis`](https://github.com/open-free-llm-api/awesome-freellm-apis)
* **Live Directory:** [https://freellm.net/](https://freellm.net/)

The catalogue tracks 495+ free LLM APIs across 30+ providers with rate limits, context windows, and official API key registration links.

---

## Important Disclaimers & Pricing Distinctions

### Mandatory Disclaimers

> **Disclaimer on Catalogue Information:**
> The free-model catalogue is a discovery resource, not a guarantee that every listed model or provider will remain free forever. Provider quotas, policies, model availability, and billing terms may change at any time.

> **"Free API" vs. "Open Source Model":**
> A model being accessible via a **Free API** does **not** mean the model itself is **Open Source** or open-weight. A cloud provider may offer a free inference tier for proprietary models.

> **"Open Source Catalogue" vs. "Open Source Providers":**
> The `awesome-freellm-apis` discovery repository is open-source (MIT licensed), but the underlying AI services and cloud providers it indexes operate under their own commercial terms and proprietary infrastructure.

### Classification Categories

Vortex explicitly classifies every AI provider and model into one of these transparent categories:

1. **`LOCAL_$0`:** Offline on-device model running locally on your hardware. 100% private, zero cost forever.
2. **`FREE_NO_CARD`:** Cloud API with a free tier requiring no credit card details.
3. **`FREE_REGISTRATION`:** Free API tier requiring standard email/account sign-up.
4. **`FREE_PHONE_VERIFICATION`:** Free API credits/tier requiring phone number (SMS) verification.
5. **`FREE_RATE_LIMITED`:** Free tier governed by strict Requests-Per-Minute (RPM) and Requests-Per-Day (RPD) caps.
6. **`FREE_BILLABLE_OVERAGE`:** Free allocation tier where exceeding limits could incur billing if a payment card is attached.
7. **`RENEWABLE_CREDITS`:** Free promotional credits that periodically reset (e.g. monthly recurring allowance).
8. **`TRIAL_ONLY`:** One-time expiring trial credits. Blocked under strict free-only mode.
9. **`PAID`:** Pay-as-you-go or subscription API endpoints. Blocked under strict free-only mode.
10. **`UNKNOWN`:** Unverified pricing terms. Disabled by default in free-only mode until manually verified by the operator.

---

## Supported AI Providers

| Provider | Mode | Transport API | Free Classification | Key Slot / Requirement | Official Portal |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Local Ollama** | Local | Ollama (`/api/chat`) | `LOCAL_$0` | None (Localhost) | [ollama.com](https://ollama.com) |
| **Gemini #1** | Cloud | Google Generative API | `FREE_RATE_LIMITED` | `GEMINI_API_KEY_1` | [aistudio.google.com](https://aistudio.google.com/apikey) |
| **Gemini #2** | Cloud | Google Generative API | `FREE_RATE_LIMITED` | `GEMINI_API_KEY_2` | [aistudio.google.com](https://aistudio.google.com/apikey) |
| **Gemini #3** | Cloud | Google Generative API | `FREE_RATE_LIMITED` | `GEMINI_API_KEY_1` | [aistudio.google.com](https://aistudio.google.com/apikey) |
| **Groq** | Cloud | OpenAI Compatible | `FREE_NO_CARD` | `GROQ_API_KEY` | [console.groq.com](https://console.groq.com/keys) |
| **OpenRouter** | Cloud | OpenAI Compatible | `FREE_RATE_LIMITED` | `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai/keys) |
| **NVIDIA NIM** | Cloud | OpenAI Compatible | `FREE_PHONE_VERIFICATION` | `NVIDIA_NIM_API_KEY` | [build.nvidia.com](https://build.nvidia.com) |
| **ModelScope** | Cloud | OpenAI Compatible | `FREE_REGISTRATION` | `MODELSCOPE_API_KEY` | [modelscope.cn](https://modelscope.cn) |
| **Cloudflare Workers AI** | Cloud | Cloudflare API | `FREE_BILLABLE_OVERAGE` | `CLOUDFLARE_API_TOKEN` | [dash.cloudflare.com](https://dash.cloudflare.com) |
| **Pollinations** | Cloud | OpenAI Compatible | `FREE_NO_CARD` | None (Keyless Community) | [pollinations.ai](https://pollinations.ai) |
| **Mistral AI** | Cloud | OpenAI Compatible | `FREE_RATE_LIMITED` | `MISTRAL_API_KEY` | [console.mistral.ai](https://console.mistral.ai) |
| **Cohere** | Cloud | OpenAI Compatible | `FREE_RATE_LIMITED` | `COHERE_API_KEY` | [dashboard.cohere.com](https://dashboard.cohere.com) |
| **Cerebras** | Cloud | OpenAI Compatible | `FREE_RATE_LIMITED` | `CEREBRAS_API_KEY` | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| **DeepSeek** | Cloud | OpenAI Compatible | `FREE_REGISTRATION` | `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com) |
| **SiliconFlow** | Cloud | OpenAI Compatible | `FREE_REGISTRATION` | `SILICONFLOW_API_KEY` | [cloud.siliconflow.cn](https://cloud.siliconflow.cn) |
| **Z AI / Zhipu AI** | Cloud | OpenAI Compatible | `FREE_REGISTRATION` | `ZAI_API_KEY` | [open.bigmodel.cn](https://open.bigmodel.cn) |
| **SambaNova** | Cloud | OpenAI Compatible | `FREE_RATE_LIMITED` | `SAMBANOVA_API_KEY` | [cloud.sambanova.ai](https://cloud.sambanova.ai) |
| **OpenCode Zen** | Cloud | OpenAI Compatible | `FREE_NO_CARD` | `OPENCODE_API_KEY` | [opencode.ai](https://opencode.ai/auth) |
| **LLM7.io** | Cloud | OpenAI Compatible | `FREE_NO_CARD` | `LLM7_API_KEY` | [llm7.io](https://llm7.io) |
| **Ollama Cloud** | Cloud | OpenAI Compatible | `FREE_RATE_LIMITED` | `OLLAMA_CLOUD_API_KEY` | [ollama.com](https://ollama.com) |
| **Kilo Code** | Cloud | OpenAI Compatible | `FREE_NO_CARD` | `KILO_API_KEY` | [kilo.ai](https://kilo.ai) |
| **OVHcloud AI** | Cloud | OpenAI Compatible | `FREE_NO_CARD` | `OVHCLOUD_API_KEY` | [endpoints.ai.cloud.ovh.net](https://endpoints.ai.cloud.ovh.net) |
| **Hugging Face** | Cloud | OpenAI Compatible | `FREE_RATE_LIMITED` | `HUGGINGFACE_API_KEY` | [huggingface.co](https://huggingface.co/settings/tokens) |
| **Aion Labs** | Cloud | OpenAI Compatible | `FREE_NO_CARD` | `AION_API_KEY` | [aionlabs.ai](https://aionlabs.ai) |
| **Agnes AI** | Cloud | OpenAI Compatible | `FREE_REGISTRATION` | `AGNES_API_KEY` | [agnes-ai.com](https://agnes-ai.com) |
| **Alibaba Model Studio** | Cloud | OpenAI Compatible | `RENEWABLE_CREDITS` | `ALIBABA_API_KEY` | [dashscope.aliyun.com](https://dashscope.console.aliyun.com) |
| **xAI (Grok)** | Cloud | OpenAI Compatible | `RENEWABLE_CREDITS` | `XAI_API_KEY` | [console.x.ai](https://console.x.ai) |
| **Chutes.ai** | Cloud | OpenAI Compatible | `FREE_NO_CARD` | `CHUTES_API_KEY` | [chutes.ai](https://chutes.ai) |
| **Glhf.chat** | Cloud | OpenAI Compatible | `FREE_NO_CARD` | `GLHF_API_KEY` | [glhf.chat](https://glhf.chat) |
| **AI21 Labs** | Cloud | OpenAI Compatible | `FREE_RATE_LIMITED` | `AI21_API_KEY` | [studio.ai21.com](https://studio.ai21.com) |
| **Nscale** | Cloud | OpenAI Compatible | `FREE_NO_CARD` | `NSCALE_API_KEY` | [console.nscale.com](https://console.nscale.com) |
| **Nebius** | Cloud | OpenAI Compatible | `TRIAL_ONLY` | `NEBIUS_API_KEY` | [studio.nebius.com](https://studio.nebius.com) |
| **Cline** | Cloud | OpenAI Compatible | `FREE_REGISTRATION` | `CLINE_API_KEY` | [cline.bot](https://cline.bot) |
| **Tencent Hunyuan** | Cloud | OpenAI Compatible | `FREE_REGISTRATION` | `TENCENT_API_KEY` | [cloud.tencent.com](https://cloud.tencent.com) |
| **Arli AI** | Cloud | OpenAI Compatible | `FREE_RATE_LIMITED` | `ARLI_API_KEY` | [arliai.com](https://arliai.com) |

---

## Configuration & Credentials

Credentials are read from `.env` in the repository root or `~/.config/vortex/.env`, or directly from environment variables.

To configure your providers:
```bash
cp .env.example .env
# Edit .env and insert keys for the providers you wish to use
```

### Invariants:
1. `.env` is gitignored: never commit secrets to version control.
2. Credentials are never logged and never exposed to browser or renderer code.
3. Outward-facing endpoints report only `configured: true | false`.
4. All prompts sent to cloud providers have sensitive tokens, passwords, private keys, and API secrets automatically redacted before transmission.

---

## Quick Start & Installation

### Requirements
* Linux OS (Debian, Ubuntu, Kali, Arch, Fedora, etc.)
* Node.js 22.12.0+
* Python 3.10+
* 2 GB RAM minimum (4 GB+ recommended)

### Run from Checkout
```bash
# 1. Install dependencies
npm install

# 2. Build the single-file React bundle
npm run build

# 3. Start desktop workbench (Electron)
npm start

# Or run zero-Electron browser preview on loopback (http://127.0.0.1:4173)
npm run preview
```

### Run Tests & Validation
```bash
npm test            # Run full Python & Node.js test suite
npm run lint        # Code check across Python, JS, and TypeScript
npm run typecheck   # Validate TypeScript types
```

---

## License

Vortex Terminal is released under the **MIT License**. See [`LICENSE`](LICENSE) for complete details.
