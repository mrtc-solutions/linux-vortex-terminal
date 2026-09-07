"""Local secret slots. Values never go to logs, reports, or API responses."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from .fileio import atomic_write, exclusive_file_lock, read_owner_text
except ImportError:  # pragma: no cover - direct module import
    from fileio import atomic_write, exclusive_file_lock, read_owner_text  # type: ignore

ALLOWED = ("ollama_token", "openai_api_key", "anthropic_api_key")


def _path() -> Path:
    try:
        from vortex_backend import config_root
    except ImportError:
        from backend.vortex_backend import config_root
    return config_root() / "secrets.json"


def status() -> dict[str, Any]:
    path = _path()
    configured = []
    if path.is_file():
        try:
            data = json.loads(read_owner_text(path, max_bytes=64 * 1024))
            configured = [key for key in ALLOWED if isinstance(data, dict) and data.get(key)]
        except (OSError, ValueError):
            configured = []
    return {"slots": ALLOWED, "configured": configured, "values": None}


def put(slot: str, value: str) -> dict[str, Any]:
    if slot not in ALLOWED:
        raise ValueError("unknown secret slot")
    path = _path()
    with exclusive_file_lock(path):
        data = {}
        if path.is_file():
            try:
                loaded = json.loads(read_owner_text(path, max_bytes=64 * 1024))
                data = loaded if isinstance(loaded, dict) else {}
            except (OSError, ValueError):
                data = {}
        if value:
            data[slot] = value[:4096]
        else:
            data.pop(slot, None)
        atomic_write(path, json.dumps(data, sort_keys=True), mode=0o600)
    return status()
