"""Local secret slots. Values never go to logs, reports, or API responses."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
            data = json.loads(path.read_text(encoding="utf-8"))
            configured = [key for key in ALLOWED if data.get(key)]
        except (OSError, ValueError):
            configured = []
    return {"slots": ALLOWED, "configured": configured, "values": None}


def put(slot: str, value: str) -> dict[str, Any]:
    if slot not in ALLOWED:
        raise ValueError("unknown secret slot")
    path = _path()
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    if value:
        data[slot] = value[:4096]
    else:
        data.pop(slot, None)
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return status()
