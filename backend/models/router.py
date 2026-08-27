"""Local model router. Never contacts a public cloud endpoint by default."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_OLLAMA = "http://127.0.0.1:11434"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def loopback_http_endpoint(raw: str | None, default: str = DEFAULT_OLLAMA) -> str:
    """Accept only http://{127.0.0.1|localhost|::1}[:port] with no userinfo or extra path."""
    value = (raw or "").strip()
    if not value:
        return default
    try:
        parsed = urllib.parse.urlparse(value)
        host = (parsed.hostname or "").lower()
        port = parsed.port or 11434
    except ValueError:
        return default
    if (
        parsed.scheme != "http"
        or host not in LOOPBACK_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or port < 1
        or port > 65535
    ):
        return default
    netloc = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    return f"http://{netloc}"


def _endpoint(raw: str | None) -> str:
    value = raw or os.environ.get("VORTEX_OLLAMA_ENDPOINT") or DEFAULT_OLLAMA
    allowed = loopback_http_endpoint(value, default="")
    return allowed


def ollama_status(endpoint: str | None = None, offline: bool = False) -> dict[str, Any]:
    if offline is True:
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
