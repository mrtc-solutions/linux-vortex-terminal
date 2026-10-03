"""Credential slots for cloud AI providers.

Keys are read from the process environment and, when present, from local
``.env`` files (repository root and the Vortex config directory). Values are
NEVER logged, never returned by any API payload, and never sent to the
renderer. Everything outward-facing reports only ``configured: true|false``.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

# Only names matching this pattern are ever read from .env files.
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]{1,63})\s*=\s*(.*?)\s*$")

KNOWN_KEY_SLOTS = (
    "GEMINI_API_KEY_1",
    "GEMINI_API_KEY_2",
    "GEMINI_API_KEY_3",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_ACCOUNT_ID",
    "ZAI_API_KEY",
    "SILICONFLOW_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
    "SAMBANOVA_API_KEY",
    "SCALEWAY_API_KEY",
    "ALIBABA_API_KEY",
    "TENCENT_API_KEY",
    "MODELSCOPE_API_KEY",
    "OLLAMA_CLOUD_API_KEY",
    "ARLI_API_KEY",
    "POLLINATIONS_API_KEY",
)

_CACHE: dict[str, Any] = {"at": 0.0, "values": {}}
_CACHE_TTL_SECONDS = 10.0


def _config_root() -> Path | None:
    try:
        try:
            from vortex_backend import config_root  # type: ignore
        except ImportError:
            from backend.vortex_backend import config_root  # type: ignore
        return config_root()
    except Exception:
        return None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        if not path.is_file():
            return values
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    if len(raw) > 64 * 1024:
        raw = raw[: 64 * 1024]
    for line in raw.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if not match:
            continue
        name, value = match.group(1), match.group(2)
        if value[:1] in {'"', "'"} and value[-1:] == value[:1] and len(value) >= 2:
            value = value[1:-1]
        if name and value:
            values[name] = value[:512]
    return values


def _load_values() -> dict[str, str]:
    now = time.monotonic()
    if (now - float(_CACHE.get("at") or 0.0)) < _CACHE_TTL_SECONDS and _CACHE.get("values"):
        return dict(_CACHE["values"])
    values: dict[str, str] = {}
    candidates: list[Path] = []
    override = os.environ.get("VORTEX_ENV_FILE")
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(_repo_root() / ".env")
    root = _config_root()
    if root is not None:
        candidates.append(root / ".env")
    for path in candidates:
        for name, value in _parse_env_file(path).items():
            values.setdefault(name, value)
    # Real environment variables always win over .env files.
    for name in KNOWN_KEY_SLOTS:
        env_value = os.environ.get(name)
        if env_value:
            values[name] = env_value[:512]
    _CACHE.update({"at": now, "values": dict(values)})
    return values


def invalidate_cache() -> None:
    _CACHE.update({"at": 0.0, "values": {}})


def get_key(slot: str) -> str | None:
    """Return the secret for a slot, or None. Never log the return value."""
    if not slot:
        return None
    value = _load_values().get(str(slot))
    return value or None


def has_key(slot: str) -> bool:
    return bool(get_key(slot))


def configured_slots() -> dict[str, bool]:
    """Presence map only — values are never included."""
    values = _load_values()
    return {name: bool(values.get(name)) for name in KNOWN_KEY_SLOTS}


def redact_secrets(text: str) -> str:
    """Strip any configured secret value out of free-form text (error bodies,
    URLs, exception strings) before it is stored or displayed."""
    out = str(text or "")
    for value in _load_values().values():
        if value and len(value) >= 6 and value in out:
            out = out.replace(value, "[REDACTED]")
    # Defensive: also mask query-string style key material.
    out = re.sub(r"([?&](?:key|api_key|apikey|token)=)[^&\s]+", r"\1[REDACTED]", out, flags=re.IGNORECASE)
    out = re.sub(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}", r"\1[REDACTED]", out)
    return out
