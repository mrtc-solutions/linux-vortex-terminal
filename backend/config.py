"""Operator settings stored locally with owner-only permissions."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from security.guardian import policy_defaults

DEFAULTS = {
    **policy_defaults("safe"),
    "developer_mode": False,
    "matrix": "medium",
    "ollama_endpoint": "http://127.0.0.1:11434",
    "first_run_complete": False,
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


def load_settings() -> dict[str, Any]:
    path = settings_path()
    data = dict(DEFAULTS)
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for key, value in loaded.items():
                    if key in DEFAULTS:
                        data[key] = value
        except (OSError, ValueError):
            pass
    env_offline = os.environ.get("VORTEX_OFFLINE")
    if env_offline in {"1", "true", "yes"}:
        data["offline"] = True
    return data


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    _, canonical = _load_backend_paths()
    current = load_settings()
    for key, value in updates.items():
        if key not in DEFAULTS:
            raise ValueError(f"unknown setting: {key}")
        expected = type(DEFAULTS[key])
        if expected is bool:
            current[key] = bool(value)
        elif expected is str:
            current[key] = str(value)[:200]
        else:
            current[key] = value
    if current["privacy_mode"] not in {"local", "hybrid", "cloud"}:
        current["privacy_mode"] = "local"
    if current["profile"] not in {"safe", "standard", "expert"}:
        current["profile"] = "safe"
    path = settings_path()
    path.write_text(canonical(current), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return current
