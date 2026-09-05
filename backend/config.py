"""Operator settings stored locally with owner-only permissions."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from security.guardian import policy_defaults
except ImportError:
    from backend.security.guardian import policy_defaults

DEFAULTS = {
    **policy_defaults("safe"),
    "developer_mode": False,
    "matrix": "medium",
    "ollama_endpoint": "http://127.0.0.1:11434",
    "ai_enabled": True,
    "ai_verbosity": "balanced",
    "model_primary": "phi4-mini:3.8b",
    "model_planner": "qwen3:4b",
    "model_fast": "llama3.2:3b",
    "model_specialist": "gemma3:4b",
    "model_timeout_seconds": 12,
    "model_max_parallel": 2,
    "model_keepalive": "0m",
    "first_run_complete": False,
    "host_tool_access": False,
}


def _load_backend_paths():
    try:
        from .vortex_backend import config_root, canonical
    except ImportError:
        from vortex_backend import config_root, canonical
    return config_root, canonical


def settings_path() -> Path:
    config_root, _ = _load_backend_paths()
    return config_root() / "settings.json"


def _typed_value(key: str, value: Any) -> Any:
    expected = type(DEFAULTS[key])
    if expected is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")
        return value
    if expected is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} must be an integer")
        return value
    if expected is str:
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        return value[:200]
    return value


def load_settings() -> dict[str, Any]:
    path = settings_path()
    data = dict(DEFAULTS)
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for key, value in loaded.items():
                    if key not in DEFAULTS:
                        continue
                    try:
                        data[key] = _typed_value(key, value)
                    except ValueError:
                        # Corrupt or pre-typed files keep the compiled default.
                        continue
        except (OSError, ValueError):
            pass
    env_offline = os.environ.get("VORTEX_OFFLINE")
    if env_offline in {"1", "true", "yes"}:
        data["offline"] = True
    if data.get("profile") not in {"safe", "standard", "expert"}:
        data["profile"] = "safe"
    if data.get("privacy_mode") not in {"local", "hybrid", "cloud"}:
        data["privacy_mode"] = "local"
    if data.get("ai_verbosity") not in {"brief", "balanced", "detailed"}:
        data["ai_verbosity"] = "balanced"
    data["model_timeout_seconds"] = max(2, min(int(data.get("model_timeout_seconds") or 12), 60))
    data["model_max_parallel"] = max(1, min(int(data.get("model_max_parallel") or 2), 3))
    data["auto_low_risk"] = data["profile"] in {"standard", "expert"}
    data["auto_medium_risk"] = False
    data["allow_root"] = False
    try:
        from models.router import DEFAULT_OLLAMA, loopback_http_endpoint
    except ImportError:
        from backend.models.router import DEFAULT_OLLAMA, loopback_http_endpoint
    canonical_endpoint = loopback_http_endpoint(str(data.get("ollama_endpoint") or ""), default="")
    data["ollama_endpoint"] = canonical_endpoint or DEFAULT_OLLAMA
    return data


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    _, canonical = _load_backend_paths()
    current = load_settings()
    for key, value in updates.items():
        if key not in DEFAULTS:
            raise ValueError(f"unknown setting: {key}")
        current[key] = _typed_value(key, value)
    if current["privacy_mode"] not in {"local", "hybrid", "cloud"}:
        current["privacy_mode"] = "local"
    if current["profile"] not in {"safe", "standard", "expert"}:
        current["profile"] = "safe"
    if current.get("ai_verbosity") not in {"brief", "balanced", "detailed"}:
        current["ai_verbosity"] = "balanced"
    current["model_timeout_seconds"] = max(2, min(int(current.get("model_timeout_seconds") or 12), 60))
    current["model_max_parallel"] = max(1, min(int(current.get("model_max_parallel") or 2), 3))
    # Safe always confirms. HTTP/settings cannot unlock medium auto-run or root.
    current["auto_low_risk"] = current["profile"] in {"standard", "expert"}
    current["auto_medium_risk"] = False
    current["allow_root"] = False
    try:
        from models.router import DEFAULT_OLLAMA, loopback_http_endpoint
    except ImportError:
        from backend.models.router import DEFAULT_OLLAMA, loopback_http_endpoint
    canonical_endpoint = loopback_http_endpoint(str(current.get("ollama_endpoint") or ""), default="")
    current["ollama_endpoint"] = canonical_endpoint or DEFAULT_OLLAMA
    path = settings_path()
    path.write_text(canonical(current), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return current
