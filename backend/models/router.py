"""Local model router. Never contacts a public cloud endpoint by default."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_OLLAMA = "http://127.0.0.1:11434"


def _endpoint(raw: str | None) -> str:
    value = (raw or os.environ.get("VORTEX_OLLAMA_ENDPOINT") or DEFAULT_OLLAMA).strip().rstrip("/")
    if not value.startswith("http://127.0.0.1") and not value.startswith("http://localhost"):
        return ""
    return value


def ollama_status(endpoint: str | None = None, offline: bool = False) -> dict[str, Any]:
    if offline:
        return {"provider": "ollama", "state": "disabled", "reason": "offline mode", "models": [], "endpoint": None}
    url = _endpoint(endpoint)
    if not url:
        return {"provider": "ollama", "state": "blocked", "reason": "endpoint is not loopback", "models": [], "endpoint": None}
    request = urllib.request.Request(url + "/api/tags", method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8", "replace") or "{}")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return {"provider": "ollama", "state": "unavailable", "reason": str(exc)[:200], "models": [], "endpoint": url}
    models = []
    for item in payload.get("models") or []:
        name = item.get("name")
        if isinstance(name, str) and name:
            models.append({"name": name[:120], "size": item.get("size")})
    return {"provider": "ollama", "state": "healthy" if models or payload.get("models") == [] else "healthy", "models": models[:50], "endpoint": url, "reason": None}


def model_status(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    offline = settings.get("offline") is True
    privacy = settings.get("privacy_mode") or "local"
    local = ollama_status(settings.get("ollama_endpoint"), offline=offline)
    return {
        "privacy_mode": privacy,
        "offline": offline,
        "local": local,
        "cloud": {"state": "disabled", "providers": [], "reason": "Cloud providers are not configured and are disabled by default."},
        "selected": "local-ollama" if local.get("state") == "healthy" else None,
        "message": "Deterministic planner remains the execution authority. Models are advisory only.",
    }
