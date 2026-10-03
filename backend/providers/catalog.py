"""Normalized definitions for every AI provider Vortex knows how to talk to.

A definition describes HOW to reach a provider, how to discover its models,
and what is honestly known about its pricing. It never asserts that pricing
is permanent: ``free_status`` values are:

* ``"free"``        — $0 by construction (local inference, keyless free API).
* ``"conditional"`` — has a genuine $0 tier, but only specific models/plans
                      are free and the catalog changes; dynamic discovery and
                      per-model pricing metadata decide what is usable in
                      FREE-ONLY mode.
* ``"unknown"``     — pricing cannot be verified automatically. Disabled in
                      FREE-ONLY mode until the operator verifies the terms
                      and flips the per-provider override.
"""
from __future__ import annotations

from typing import Any

DEFAULT_LOCAL_MODEL = "qwen2.5:3b"
OLLAMA_LOCAL_ENDPOINT = "http://127.0.0.1:11434"

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Gemini free-tier model families, per Google's pricing page (verified
# 2026-10-03): only Flash / Flash-Lite model IDs carry a $0 free-tier row;
# Pro models are paid-only since April 2026. Re-verified at discovery time.
GEMINI_FREE_TIER_PATTERNS = ("flash",)
GEMINI_PAID_ONLY_PATTERNS = ("pro", "ultra", "deep-think")

# Default Gemini logical entries. Model IDs verified against the Gemini API
# catalog on 2026-10-03; discovery re-checks them and reports model_unavailable
# instead of silently assuming they still exist.
GEMINI_DEFAULT_ENTRIES: dict[str, dict[str, str]] = {
    "gemini-1": {"model": "gemini-3.8-flash", "key_slot": "GEMINI_API_KEY_1"},
    "gemini-2": {"model": "gemini-3.5-flash-lite", "key_slot": "GEMINI_API_KEY_2"},
    "gemini-3": {"model": "gemini-2.5-flash", "key_slot": "GEMINI_API_KEY_1"},
}

# Canonical provider definitions. "api" selects the transport adapter:
#   ollama      — loopback Ollama /api/chat
#   openai      — OpenAI-compatible /chat/completions
#   gemini      — Google generateContent (key via x-goog-api-key header)
#   cloudflare  — Cloudflare Workers AI OpenAI-compatible endpoint
# "discovery" selects how models are enumerated:
#   ollama-tags / openai-models / openrouter-models / gemini-models / static
PROVIDER_DEFS: list[dict[str, Any]] = [
    {
        "id": "ollama-local",
        "name": "Local Ollama",
        "family": "ollama",
        "mode": "local",
        "api": "ollama",
        "base_url": OLLAMA_LOCAL_ENDPOINT,
        "key_slot": None,
        "discovery": "ollama-tags",
        "free_status": "free",
        "free_detail": "Local inference on this machine. $0 forever.",
        "enabled_default": True,
        "priority": 0,
        "default_model": DEFAULT_LOCAL_MODEL,
    },
    {
        "id": "gemini-1",
        "name": "Gemini #1",
        "family": "google-gemini",
        "mode": "cloud",
        "api": "gemini",
        "base_url": GEMINI_BASE_URL,
        "key_slot": "GEMINI_API_KEY_1",   # configurable per entry
        "discovery": "gemini-models",
        "free_status": "conditional",
        "free_detail": "Google AI Studio free tier covers Flash/Flash-Lite models only (reduced daily quotas). Pro models are paid-only.",
        "enabled_default": True,
        "priority": 10,
        "default_model": GEMINI_DEFAULT_ENTRIES["gemini-1"]["model"],
    },
    {
        "id": "gemini-2",
        "name": "Gemini #2",
        "family": "google-gemini",
        "mode": "cloud",
        "api": "gemini",
        "base_url": GEMINI_BASE_URL,
        "key_slot": "GEMINI_API_KEY_2",
        "discovery": "gemini-models",
        "free_status": "conditional",
        "free_detail": "Google AI Studio free tier covers Flash/Flash-Lite models only (reduced daily quotas). Pro models are paid-only.",
        "enabled_default": True,
        "priority": 11,
        "default_model": GEMINI_DEFAULT_ENTRIES["gemini-2"]["model"],
    },
    {
        "id": "gemini-3",
        "name": "Gemini #3",
        "family": "google-gemini",
        "mode": "cloud",
        "api": "gemini",
        "base_url": GEMINI_BASE_URL,
        "key_slot": "GEMINI_API_KEY_1",   # two keys may serve three entries
        "discovery": "gemini-models",
        "free_status": "conditional",
        "free_detail": "Google AI Studio free tier covers Flash/Flash-Lite models only (reduced daily quotas). Pro models are paid-only.",
        "enabled_default": True,
        "priority": 12,
        "default_model": GEMINI_DEFAULT_ENTRIES["gemini-3"]["model"],
    },
    {
        "id": "groq",
        "name": "Groq",
        "family": "groq",
        "mode": "cloud",
        "api": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "key_slot": "GROQ_API_KEY",
        "discovery": "openai-models",
        "free_status": "conditional",
        "free_detail": "Groq free plan serves currently listed models at $0 within strict RPM/RPD/TPM limits; production pricing is paid. Model list changes — discovered dynamically.",
        "enabled_default": True,
        "priority": 20,
        "default_model": "",  # chosen from discovery
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "family": "openrouter",
        "mode": "cloud",
        "api": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "key_slot": "OPENROUTER_API_KEY",
        "discovery": "openrouter-models",
        "free_status": "conditional",
        "free_detail": "Models with ':free' IDs are $0 (20 req/min, 50 req/day unfunded). The free catalog changes month to month — discovered dynamically with pricing metadata.",
        "enabled_default": True,
        "priority": 30,
        "default_model": "",  # chosen from discovered :free models
        "extra_headers": {"HTTP-Referer": "https://github.com/mrtc-solutions/linux-vortex-terminal", "X-Title": "Vortex Terminal"},
    },
    {
        "id": "cloudflare",
        "name": "Cloudflare Workers AI",
        "family": "cloudflare",
        "mode": "cloud",
        "api": "cloudflare",
        "base_url": "https://api.cloudflare.com/client/v4",
        "key_slot": "CLOUDFLARE_API_TOKEN",
        "extra_key_slots": ["CLOUDFLARE_ACCOUNT_ID"],
        "discovery": "cloudflare-models",
        "free_status": "conditional",
        "free_detail": "Workers Free plan: 10,000 neurons/day shared across models; on the free plan exhausted allocation fails requests instead of billing. Paid plans bill overage.",
        "enabled_default": True,
        "priority": 40,
        "default_model": "@cf/meta/llama-3.1-8b-instruct",
    },
    {
        "id": "pollinations",
        "name": "Pollinations",
        "family": "pollinations",
        "mode": "cloud",
        "api": "openai",
        "base_url": "https://text.pollinations.ai/openai",
        "base_is_endpoint": True,
        "key_slot": None,
        "discovery": "static",
        "free_status": "free",
        "free_detail": "Keyless community free API. Availability is best-effort and may change.",
        "enabled_default": True,
        "priority": 50,
        "default_model": "openai",
        "static_models": [
            {"id": "openai", "label": "Pollinations default (OpenAI-compatible)", "free": True},
        ],
    },
    {
        "id": "mistral",
        "name": "Mistral",
        "family": "mistral",
        "mode": "cloud",
        "api": "openai",
        "base_url": "https://api.mistral.ai/v1",
        "key_slot": "MISTRAL_API_KEY",
        "discovery": "openai-models",
        "free_status": "conditional",
        "free_detail": "La Plateforme has a free experiment tier on selected models; quotas and eligibility change. Verify your plan before enabling in free-only mode.",
        "enabled_default": False,
        "priority": 60,
        "default_model": "",
    },
    {
        "id": "cohere",
        "name": "Cohere",
        "family": "cohere",
        "mode": "cloud",
        "api": "openai",
        "base_url": "https://api.cohere.ai/compatibility/v1",
        "key_slot": "COHERE_API_KEY",
        "discovery": "openai-models",
        "free_status": "conditional",
        "free_detail": "Trial keys are rate-limited and $0, production keys are paid. Vortex cannot distinguish key type automatically — verify before enabling in free-only mode.",
        "enabled_default": False,
        "priority": 61,
        "default_model": "",
    },
    {
        "id": "zai",
        "name": "Z.ai",
        "family": "zai",
        "mode": "cloud",
        "api": "openai",
        "base_url": "https://api.z.ai/api/paas/v4",
        "key_slot": "ZAI_API_KEY",
        "discovery": "static",
        "free_status": "unknown",
        "free_detail": "Z.ai has offered free GLM Flash models, but pricing metadata is not exposed by the API. FREE STATUS: UNKNOWN — verify terms, then enable manually.",
        "enabled_default": False,
        "priority": 62,
        "default_model": "glm-4.5-flash",
        "static_models": [
            {"id": "glm-4.5-flash", "label": "GLM-4.5 Flash", "free": None},
        ],
    },
    {
        "id": "siliconflow",
        "name": "SiliconFlow",
        "family": "siliconflow",
        "mode": "cloud",
        "api": "openai",
        "base_url": "https://api.siliconflow.com/v1",
        "key_slot": "SILICONFLOW_API_KEY",
        "discovery": "openai-models",
        "free_status": "unknown",
        "free_detail": "Some models have been free-tier; the /models API does not expose pricing. FREE STATUS: UNKNOWN — verify terms, then enable manually.",
        "enabled_default": False,
        "priority": 63,
        "default_model": "",
    },
    {
        "id": "sambanova",
        "name": "SambaNova",
        "family": "sambanova",
        "mode": "cloud",
        "api": "openai",
        "base_url": "https://api.sambanova.ai/v1",
        "key_slot": "SAMBANOVA_API_KEY",
        "discovery": "openai-models",
        "free_status": "unknown",
        "free_detail": "Developer tier has been free with limits; pricing is not exposed via the API. FREE STATUS: UNKNOWN — verify terms, then enable manually.",
        "enabled_default": False,
        "priority": 64,
        "default_model": "",
    },
    {
        "id": "scaleway",
        "name": "Scaleway Generative APIs",
        "family": "scaleway",
        "mode": "cloud",
        "api": "openai",
        "base_url": "https://api.scaleway.ai/v1",
        "key_slot": "SCALEWAY_API_KEY",
        "discovery": "openai-models",
        "free_status": "unknown",
        "free_detail": "Free beta ended; current accounts may be billed per token. FREE STATUS: UNKNOWN — verify terms, then enable manually.",
        "enabled_default": False,
        "priority": 65,
        "default_model": "",
    },
    {
        "id": "alibaba",
        "name": "Alibaba Model Studio",
        "family": "alibaba",
        "mode": "cloud",
        "api": "openai",
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "key_slot": "ALIBABA_API_KEY",
        "discovery": "openai-models",
        "free_status": "unknown",
        "free_detail": "New accounts get expiring trial token quotas — trial credit is not a free service. FREE STATUS: UNKNOWN — verify terms, then enable manually.",
        "enabled_default": False,
        "priority": 66,
        "default_model": "",
    },
    {
        "id": "tencent",
        "name": "Tencent Hunyuan",
        "family": "tencent",
        "mode": "cloud",
        "api": "openai",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "key_slot": "TENCENT_API_KEY",
        "discovery": "openai-models",
        "free_status": "unknown",
        "free_detail": "hunyuan-lite has been free; other models are paid and the API exposes no pricing. FREE STATUS: UNKNOWN — verify terms, then enable manually.",
        "enabled_default": False,
        "priority": 67,
        "default_model": "hunyuan-lite",
    },
    {
        "id": "modelscope",
        "name": "ModelScope",
        "family": "modelscope",
        "mode": "cloud",
        "api": "openai",
        "base_url": "https://api-inference.modelscope.cn/v1",
        "key_slot": "MODELSCOPE_API_KEY",
        "discovery": "openai-models",
        "free_status": "conditional",
        "free_detail": "Free daily inference quota (currently 2,000 calls/day) on listed models; quota and catalog change. Verify your account region/terms.",
        "enabled_default": False,
        "priority": 68,
        "default_model": "",
    },
    {
        "id": "ollama-cloud",
        "name": "Ollama Cloud",
        "family": "ollama-cloud",
        "mode": "cloud",
        "api": "openai",
        "base_url": "https://ollama.com/v1",
        "key_slot": "OLLAMA_CLOUD_API_KEY",
        "discovery": "openai-models",
        "free_status": "conditional",
        "free_detail": "Free tier has hourly/daily usage caps; paid tiers exist. Verify your plan before enabling in free-only mode.",
        "enabled_default": False,
        "priority": 69,
        "default_model": "",
    },
    {
        "id": "arli",
        "name": "Arli AI",
        "family": "arli",
        "mode": "cloud",
        "api": "openai",
        "base_url": "https://api.arliai.com/v1",
        "key_slot": "ARLI_API_KEY",
        "discovery": "openai-models",
        "free_status": "unknown",
        "free_detail": "Free account tier has existed with strict limits; pricing is not exposed via the API. FREE STATUS: UNKNOWN — verify terms, then enable manually.",
        "enabled_default": False,
        "priority": 70,
        "default_model": "",
    },
]

PROVIDERS_BY_ID: dict[str, dict[str, Any]] = {item["id"]: item for item in PROVIDER_DEFS}

# Default conversation fallback order (free-first). Only enabled + policy-
# allowed + key-configured providers are actually attempted.
DEFAULT_FALLBACK_ORDER: tuple[str, ...] = (
    "ollama-local",
    "gemini-1",
    "gemini-2",
    "gemini-3",
    "groq",
    "openrouter",
    "cloudflare",
    "pollinations",
    "mistral",
    "cohere",
    "modelscope",
    "ollama-cloud",
    "zai",
    "siliconflow",
    "sambanova",
    "scaleway",
    "alibaba",
    "tencent",
    "arli",
)


def provider_def(provider_id: str) -> dict[str, Any] | None:
    return PROVIDERS_BY_ID.get(str(provider_id or ""))
