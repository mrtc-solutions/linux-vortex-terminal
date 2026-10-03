"""Central Provider Manager for the Vortex multi-provider AI layer.

Responsibilities:
* normalized provider inventory (local Ollama + cloud providers);
* dynamic model discovery with pricing/free metadata (registry cache);
* health checks with precise failure states (never a vague
  "Local AI unavailable");
* free-only cost protection (policy engine) — no silent paid calls, ever;
* controlled fallback with per-provider cooldowns on 429/quota errors;
* per-entry usage statistics (requests, failures, latency, key slot) with
  all credentials masked.

Providers return TEXT ONLY. Nothing produced here is executed: system
actions still flow through planner -> Guardian -> reviewed adapters.
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

try:
    from . import catalog as _catalog
    from . import keys as _keys
    from . import policy as _policy
    from .registry import registry as _registry
except ImportError:  # direct module import (backend on sys.path)
    try:
        from providers import catalog as _catalog  # type: ignore
        from providers import keys as _keys  # type: ignore
        from providers import policy as _policy  # type: ignore
        from providers.registry import registry as _registry  # type: ignore
    except ImportError:
        from backend.providers import catalog as _catalog  # type: ignore
        from backend.providers import keys as _keys  # type: ignore
        from backend.providers import policy as _policy  # type: ignore
        from backend.providers.registry import registry as _registry  # type: ignore

_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_CHAT_MAX_CHARS = 24000
_DEFAULT_CLOUD_TIMEOUT = 30
_DEFAULT_LOCAL_TIMEOUT = 90

COOLDOWN_SECONDS = {
    "rate_limited": 120,
    "quota_exhausted": 600,
    "invalid_api_key": 600,
    "provider_error": 60,
    "network_unavailable": 30,
    "timeout": 20,
    "model_unavailable": 300,
}

_NON_CHAT_MODEL_HINTS = ("whisper", "tts", "embed", "rerank", "guard", "moderation", "audio", "image", "dall-e", "distil")

CONVERSATION_SYSTEM_PROMPT = (
    "You are Vortex, the AI assistant inside the Vortex Linux terminal. "
    "Answer conversationally, accurately, and concisely. You can discuss Linux, "
    "programming, security, and general topics. You never execute commands "
    "yourself: when the user wants something run or inspected on their system, "
    "Vortex's deterministic planner and Guardian handle it with explicit "
    "operator approval. Do not fabricate command output."
)


class ProviderError(Exception):
    """Classified provider failure. `kind` is one of the diagnostic states."""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(detail or kind)
        self.kind = kind
        self.detail = _keys.redact_secrets(detail or kind)[:300]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _http_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
               body: dict[str, Any] | None = None, timeout: float = 20.0) -> tuple[int, Any]:
    """Bounded HTTP+JSON call. Raises ProviderError with a classified kind."""
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request_headers = {"Content-Type": "application/json", "Accept": "application/json",
                       "User-Agent": "vortex-terminal/0.3"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=payload, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise ProviderError("provider_error", "response exceeded the size limit")
            text = raw.decode("utf-8", "replace")
            try:
                return response.status, json.loads(text) if text.strip() else {}
            except ValueError:
                return response.status, text
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(4096).decode("utf-8", "replace")
        except Exception:
            detail = ""
        detail = _keys.redact_secrets(detail)[:280]
        code = int(exc.code)
        if code == 429:
            kind = "quota_exhausted" if re.search(r"quota|exhaust|billing|RESOURCE_EXHAUSTED", detail, re.IGNORECASE) else "rate_limited"
            raise ProviderError(kind, f"HTTP 429: {detail}") from exc
        if code in {401, 403}:
            raise ProviderError("invalid_api_key", f"HTTP {code}: {detail}") from exc
        if code == 404:
            raise ProviderError("model_unavailable", f"HTTP 404: {detail}") from exc
        if code == 400 and re.search(r"model|not found|decommission|deprecat", detail, re.IGNORECASE):
            raise ProviderError("model_unavailable", f"HTTP 400: {detail}") from exc
        if code >= 500:
            raise ProviderError("provider_error", f"HTTP {code}: {detail}") from exc
        raise ProviderError("provider_error", f"HTTP {code}: {detail}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise ProviderError("timeout", f"no response within {timeout:.0f}s") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise ProviderError("timeout", f"no response within {timeout:.0f}s") from exc
        raise ProviderError("network_unavailable", str(reason)[:200]) from exc
    except OSError as exc:
        raise ProviderError("network_unavailable", str(exc)[:200]) from exc


def _state_path():
    try:
        try:
            from vortex_backend import config_root  # type: ignore
        except ImportError:
            from backend.vortex_backend import config_root  # type: ignore
        root = config_root() / "providers"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return root / "state.json"
    except Exception:
        return None


class ProviderManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stats: dict[str, dict[str, Any]] = {}
        self._health: dict[str, dict[str, Any]] = {}
        self._state: dict[str, Any] | None = None
        self._local_runtime: dict[str, Any] = {}

    # ------------------------------------------------------------------ state

    def _load_state(self) -> dict[str, Any]:
        with self._lock:
            if self._state is not None:
                return self._state
            state: dict[str, Any] = {"providers": {}, "gemini": {}}
            path = _state_path()
            if path is not None and path.is_file():
                try:
                    parsed = json.loads(path.read_text(encoding="utf-8")[:262144])
                    if isinstance(parsed, dict):
                        state["providers"] = parsed.get("providers") if isinstance(parsed.get("providers"), dict) else {}
                        state["gemini"] = parsed.get("gemini") if isinstance(parsed.get("gemini"), dict) else {}
                except (OSError, ValueError):
                    pass
            self._state = state
            return state

    def _save_state(self) -> None:
        with self._lock:
            state = self._load_state()
            path = _state_path()
            if path is None:
                return
            try:
                try:
                    from fileio import atomic_write  # type: ignore
                except ImportError:
                    from backend.fileio import atomic_write  # type: ignore
                atomic_write(path, json.dumps(state, sort_keys=True), mode=0o600)
            except Exception:
                pass

    def _overrides(self, provider_id: str) -> dict[str, Any]:
        state = self._load_state()
        entry = (state.get("providers") or {}).get(provider_id)
        return dict(entry) if isinstance(entry, dict) else {}

    def set_enabled(self, provider_id: str, enabled: bool, *, allow_in_free_mode: bool | None = None) -> dict[str, Any]:
        definition = _catalog.provider_def(provider_id)
        if definition is None:
            raise ValueError("unknown provider: " + str(provider_id)[:60])
        with self._lock:
            state = self._load_state()
            entry = state.setdefault("providers", {}).setdefault(provider_id, {})
            entry["enabled"] = bool(enabled)
            if allow_in_free_mode is not None:
                entry["allow_in_free_mode"] = bool(allow_in_free_mode)
            self._save_state()
        return {"provider": provider_id, "enabled": bool(enabled),
                "allow_in_free_mode": bool(entry.get("allow_in_free_mode", False))}

    def gemini_config(self) -> dict[str, dict[str, str]]:
        state = self._load_state()
        config: dict[str, dict[str, str]] = {}
        for entry_id, defaults in _catalog.GEMINI_DEFAULT_ENTRIES.items():
            stored = (state.get("gemini") or {}).get(entry_id)
            stored = stored if isinstance(stored, dict) else {}
            model = str(stored.get("model") or defaults["model"])[:120]
            key_slot = str(stored.get("key_slot") or defaults["key_slot"])[:40]
            if key_slot not in {"GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"}:
                key_slot = defaults["key_slot"]
            config[entry_id] = {"model": model, "key_slot": key_slot}
        return config

    def configure_gemini(self, entry_id: str, *, model: str | None = None, key_slot: str | None = None) -> dict[str, Any]:
        if entry_id not in _catalog.GEMINI_DEFAULT_ENTRIES:
            raise ValueError("gemini entry must be one of gemini-1, gemini-2, gemini-3")
        if key_slot is not None and key_slot not in {"GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"}:
            raise ValueError("key_slot must be GEMINI_API_KEY_1, GEMINI_API_KEY_2, or GEMINI_API_KEY_3")
        if model is not None and not re.fullmatch(r"[a-z0-9][a-z0-9.\-]{0,100}", str(model)):
            raise ValueError("model id has an unexpected format")
        with self._lock:
            state = self._load_state()
            entry = state.setdefault("gemini", {}).setdefault(entry_id, {})
            if model is not None:
                entry["model"] = str(model)
            if key_slot is not None:
                entry["key_slot"] = str(key_slot)
            self._save_state()
        config = self.gemini_config()[entry_id]
        return {"entry": entry_id, **config, "key_configured": _keys.has_key(config["key_slot"])}

    # ------------------------------------------------------------------ stats

    def _stat(self, provider_id: str) -> dict[str, Any]:
        with self._lock:
            return self._stats.setdefault(provider_id, {
                "requests": 0, "ok": 0, "failures": 0, "http_429": 0,
                "auth_failures": 0, "timeouts": 0,
                "latency_ms_ewma": None, "last_success": None,
                "last_failure": None, "last_error": None, "last_error_kind": None,
                "cooldown_until": 0.0,
            })

    def _record_success(self, provider_id: str, latency_ms: int) -> None:
        with self._lock:
            stat = self._stat(provider_id)
            stat["requests"] += 1
            stat["ok"] += 1
            prev = stat["latency_ms_ewma"]
            stat["latency_ms_ewma"] = int(latency_ms if prev is None else 0.7 * prev + 0.3 * latency_ms)
            stat["last_success"] = _now_iso()
            stat["cooldown_until"] = 0.0

    def _record_failure(self, provider_id: str, error: ProviderError) -> None:
        with self._lock:
            stat = self._stat(provider_id)
            stat["requests"] += 1
            stat["failures"] += 1
            if error.kind in {"rate_limited", "quota_exhausted"}:
                stat["http_429"] += 1
            if error.kind == "invalid_api_key":
                stat["auth_failures"] += 1
            if error.kind == "timeout":
                stat["timeouts"] += 1
            stat["last_failure"] = _now_iso()
            stat["last_error"] = error.detail
            stat["last_error_kind"] = error.kind
            cooldown = COOLDOWN_SECONDS.get(error.kind, 0)
            if cooldown:
                stat["cooldown_until"] = max(float(stat.get("cooldown_until") or 0.0), time.monotonic() + cooldown)

    def _in_cooldown(self, provider_id: str) -> float:
        stat = self._stat(provider_id)
        remaining = float(stat.get("cooldown_until") or 0.0) - time.monotonic()
        return max(0.0, remaining)

    # --------------------------------------------------------------- identity

    def _definition(self, provider_id: str) -> dict[str, Any]:
        definition = _catalog.provider_def(provider_id)
        if definition is None:
            raise ProviderError("provider_error", f"unknown provider {str(provider_id)[:60]}")
        definition = dict(definition)
        if definition.get("family") == "google-gemini":
            config = self.gemini_config().get(provider_id) or {}
            if config.get("key_slot"):
                definition["key_slot"] = config["key_slot"]
            if config.get("model"):
                definition["default_model"] = config["model"]
        return definition

    def _enabled(self, definition: dict[str, Any]) -> bool:
        overrides = self._overrides(definition["id"])
        if "enabled" in overrides:
            return overrides.get("enabled") is True
        return definition.get("enabled_default") is True

    def _key_ok(self, definition: dict[str, Any]) -> tuple[bool, str]:
        slot = definition.get("key_slot")
        if slot and not _keys.has_key(str(slot)):
            return False, f"API key not configured (set {slot})"
        for extra in definition.get("extra_key_slots") or []:
            if not _keys.has_key(str(extra)):
                return False, f"configuration not complete (set {extra})"
        return True, "configured"

    def _cloud_gate(self, settings: dict[str, Any]) -> str | None:
        """Why cloud providers cannot be used right now, or None if they can."""
        if settings.get("offline") is True:
            return "offline mode blocks all cloud providers"
        if str(settings.get("privacy_mode") or "local") == "local":
            return "privacy mode 'local' blocks cloud providers — set privacy mode to 'hybrid' or 'cloud' to allow cloud fallback"
        return None

    # -------------------------------------------------------------- discovery

    def discover_models(self, provider_id: str, settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        settings = settings or {}
        definition = self._definition(provider_id)
        style = str(definition.get("discovery") or "static")
        timeout = float(settings.get("cloud_timeout_seconds") or _DEFAULT_CLOUD_TIMEOUT)
        if definition.get("mode") == "cloud":
            gate = self._cloud_gate(settings)
            if gate:
                raise ProviderError("network_unavailable", gate)
        if style == "static":
            models = [dict(item) for item in definition.get("static_models") or []]
            for item in models:
                item.setdefault("verified_at", _now_iso())
            return _registry().update_models(provider_id, models)
        if style == "ollama-tags":
            return self._discover_ollama(definition, settings)
        key_ok, key_reason = self._key_ok(definition)
        if not key_ok:
            raise ProviderError("no_api_key", key_reason)
        if style == "openai-models":
            return self._discover_openai(definition, timeout)
        if style == "openrouter-models":
            return self._discover_openrouter(definition, timeout)
        if style == "gemini-models":
            return self._discover_gemini(definition, timeout)
        if style == "cloudflare-models":
            return self._discover_cloudflare(definition, timeout)
        raise ProviderError("provider_error", f"unsupported discovery style {style}")

    def _discover_ollama(self, definition: dict[str, Any], settings: dict[str, Any]) -> list[dict[str, Any]]:
        base = str(settings.get("ollama_endpoint") or definition["base_url"]).rstrip("/")
        status, payload = _http_json(base + "/api/tags", timeout=3.0)
        models = []
        for item in (payload.get("models") or []) if isinstance(payload, dict) else []:
            name = item.get("name") if isinstance(item, dict) else None
            if isinstance(name, str) and name:
                models.append({
                    "id": name, "label": name, "free": True,
                    "price_input": 0, "price_output": 0,
                    "detail": "Installed local Ollama model.",
                    "capabilities": ["chat"],
                })
        return _registry().update_models(definition["id"], models)

    def _auth_headers(self, definition: dict[str, Any]) -> dict[str, str]:
        headers: dict[str, str] = {}
        slot = definition.get("key_slot")
        if slot:
            key = _keys.get_key(str(slot))
            if key:
                headers["Authorization"] = "Bearer " + key
        headers.update(definition.get("extra_headers") or {})
        return headers

    def _discover_openai(self, definition: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
        url = str(definition["base_url"]).rstrip("/") + "/models"
        status, payload = _http_json(url, headers=self._auth_headers(definition), timeout=timeout)
        rows = payload.get("data") if isinstance(payload, dict) else None
        models = []
        for item in rows or []:
            model_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(model_id, str) or not model_id:
                continue
            lowered = model_id.lower()
            chatty = not any(hint in lowered for hint in _NON_CHAT_MODEL_HINTS)
            free: bool | None = None
            detail = ""
            if definition["id"] == "groq":
                # Groq's free developer plan serves its listed models at $0
                # within published rate limits; production tiers are paid.
                free = True
                detail = "Available on the Groq free plan (rate-limited). Production pricing is paid."
            models.append({
                "id": model_id, "label": model_id, "free": free,
                "context_length": item.get("context_window") if isinstance(item.get("context_window"), int) else None,
                "capabilities": ["chat"] if chatty else [],
                "detail": detail,
            })
        return _registry().update_models(definition["id"], models)

    def _discover_openrouter(self, definition: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
        url = str(definition["base_url"]).rstrip("/") + "/models"
        status, payload = _http_json(url, headers=self._auth_headers(definition), timeout=timeout)
        rows = payload.get("data") if isinstance(payload, dict) else None
        models: list[dict[str, Any]] = []
        for item in rows or []:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            if not isinstance(model_id, str) or not model_id:
                continue
            pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}

            def _price(key: str) -> float | None:
                raw = pricing.get(key)
                try:
                    return float(raw)
                except (TypeError, ValueError):
                    return None

            price_in = _price("prompt")
            price_out = _price("completion")
            free = None
            if price_in is not None and price_out is not None:
                free = price_in == 0.0 and price_out == 0.0
            if model_id.endswith(":free") and free is None:
                free = True
            context = item.get("context_length") if isinstance(item.get("context_length"), int) else None
            supported = item.get("supported_parameters") if isinstance(item.get("supported_parameters"), list) else []
            models.append({
                "id": model_id,
                "label": str(item.get("name") or model_id),
                "free": free,
                "price_input": price_in,
                "price_output": price_out,
                "context_length": context,
                "capabilities": ["chat"],
                "tool_calling": "tools" in supported,
                "reasoning": "reasoning" in supported or "include_reasoning" in supported,
                "detail": "Pricing read from the OpenRouter catalog; ':free' availability changes over time.",
            })
        # Keep free models first so auto-selection and the UI prefer them.
        models.sort(key=lambda entry: (entry.get("free") is not True, str(entry["id"])))
        pseudo = {
            "id": "openrouter/free",
            "label": "OpenRouter free pool (auto)",
            "free": True,
            "price_input": 0, "price_output": 0,
            "capabilities": ["chat"],
            "detail": "Resolved by Vortex at request time to a currently-discovered ':free' model.",
        }
        return _registry().update_models(definition["id"], [pseudo] + models[:200])

    def _discover_gemini(self, definition: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
        key = _keys.get_key(str(definition.get("key_slot") or ""))
        if not key:
            raise ProviderError("no_api_key", f"API key not configured (set {definition.get('key_slot')})")
        url = str(definition["base_url"]).rstrip("/") + "/models?pageSize=200"
        status, payload = _http_json(url, headers={"x-goog-api-key": key}, timeout=timeout)
        rows = payload.get("models") if isinstance(payload, dict) else None
        models = []
        for item in rows or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            model_id = name.removeprefix("models/")
            if not model_id:
                continue
            methods = item.get("supportedGenerationMethods") or []
            if "generateContent" not in methods:
                continue
            lowered = model_id.lower()
            free: bool | None = None
            detail = ""
            if any(pattern in lowered for pattern in _catalog.GEMINI_PAID_ONLY_PATTERNS):
                free = False
                detail = "Pro/Ultra Gemini models are paid-only on the current free tier."
            elif any(pattern in lowered for pattern in _catalog.GEMINI_FREE_TIER_PATTERNS):
                free = True
                detail = "Flash-class model with a $0 free-tier row (reduced daily quotas). Free tier terms can change."
            models.append({
                "id": model_id,
                "label": str(item.get("displayName") or model_id),
                "free": free,
                "context_length": item.get("inputTokenLimit") if isinstance(item.get("inputTokenLimit"), int) else None,
                "capabilities": ["chat"],
                "detail": detail,
            })
        return _registry().update_models(definition["id"], models)

    def _discover_cloudflare(self, definition: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
        account = _keys.get_key("CLOUDFLARE_ACCOUNT_ID")
        if not account:
            raise ProviderError("no_api_key", "configuration not complete (set CLOUDFLARE_ACCOUNT_ID)")
        url = (str(definition["base_url"]).rstrip("/")
               + f"/accounts/{urllib.parse.quote(account)}/ai/models/search?task=Text%20Generation&per_page=100")
        status, payload = _http_json(url, headers=self._auth_headers(definition), timeout=timeout)
        rows = payload.get("result") if isinstance(payload, dict) else None
        models = []
        for item in rows or []:
            if not isinstance(item, dict):
                continue
            model_id = item.get("name")
            if not isinstance(model_id, str) or not model_id:
                continue
            models.append({
                "id": model_id,
                "label": model_id,
                "free": True,
                "detail": "Covered by the Workers Free 10,000 neurons/day allocation; free-plan requests fail (not billed) when it is exhausted.",
                "capabilities": ["chat"],
            })
        return _registry().update_models(definition["id"], models)

    # ------------------------------------------------------------ local qwen

    def local_status(self, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        """Precise local state: installed / running / model present / warm."""
        settings = settings or {}
        base = str(settings.get("ollama_endpoint") or _catalog.OLLAMA_LOCAL_ENDPOINT).rstrip("/")
        model = str(settings.get("local_primary_model") or _catalog.DEFAULT_LOCAL_MODEL)
        result: dict[str, Any] = {
            "provider": "ollama-local", "endpoint": base, "model": model,
            "checked_at": _now_iso(),
        }
        started = time.monotonic()
        try:
            status, payload = _http_json(base + "/api/tags", timeout=2.5)
        except ProviderError as exc:
            if exc.kind == "timeout":
                result.update({"state": "ollama_timeout", "message": "Ollama did not answer its status probe in time (it may be starting)."})
            elif shutil.which("ollama") is None:
                result.update({"state": "ollama_not_installed", "message": "Ollama is not installed (the `ollama` binary is not on PATH)."})
            else:
                result.update({"state": "ollama_not_running", "message": f"Ollama is installed but not reachable at {base}. Start it with: ollama serve"})
            result["detail"] = exc.detail
            with self._lock:
                self._local_runtime = dict(result)
            return result
        names = [str(item.get("name") or "") for item in (payload.get("models") or []) if isinstance(item, dict)]
        result["installed_models"] = names[:64]
        result["latency_ms"] = int((time.monotonic() - started) * 1000)
        exact = model in names
        family = model.split(":", 1)[0]
        family_match = next((name for name in names if name.split(":", 1)[0] == family), None)
        if not exact and not family_match:
            result.update({
                "state": "model_missing",
                "message": f"Ollama is running but {model} is not installed. Install it with: ollama pull {model}",
            })
            with self._lock:
                self._local_runtime = dict(result)
            return result
        effective = model if exact else str(family_match)
        result["effective_model"] = effective
        warm = False
        try:
            status, loaded = _http_json(base + "/api/ps", timeout=2.5)
            running = [str(item.get("name") or "") for item in (loaded.get("models") or []) if isinstance(item, dict)]
            warm = effective in running or any(name.split(":", 1)[0] == family for name in running)
        except ProviderError:
            pass
        result.update({
            "state": "ready" if warm else "cold",
            "warm": warm,
            "message": "Local Qwen ready" if warm else "Local Qwen available but cold (first reply may take a while to load the model)",
        })
        if effective != model:
            result["message"] += f" — using installed tag {effective}"
        with self._lock:
            self._local_runtime = dict(result)
        return result

    def warm_up(self, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        """Single bounded load request. Never loops or retries."""
        settings = settings or {}
        status = self.local_status(settings)
        if status.get("state") not in {"ready", "cold"}:
            return status
        base = str(status.get("endpoint"))
        model = str(status.get("effective_model") or status.get("model"))
        started = time.monotonic()
        try:
            _http_json(base + "/api/generate", method="POST",
                       body={"model": model, "prompt": "", "keep_alive": "15m"},
                       timeout=float(settings.get("local_chat_timeout_seconds") or _DEFAULT_LOCAL_TIMEOUT))
            latency = int((time.monotonic() - started) * 1000)
            self._record_success("ollama-local", latency)
            return {**status, "state": "ready", "warm": True, "warmup_ms": latency,
                    "message": f"Local Qwen ready (warm-up took {latency / 1000:.1f}s)"}
        except ProviderError as exc:
            self._record_failure("ollama-local", exc)
            kind = "qwen_load_timeout" if exc.kind == "timeout" else exc.kind
            return {**status, "state": kind,
                    "message": f"Warm-up failed: {exc.detail}" if exc.kind != "timeout"
                    else "Qwen is still loading — the warm-up request timed out, but the model may become ready shortly."}

    # ------------------------------------------------------------------- chat

    def _resolve_model(self, definition: dict[str, Any], requested: str | None,
                       policy: dict[str, Any], overrides: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        provider_id = definition["id"]
        reg = _registry()
        known = {item["id"]: item for item in reg.get_models(provider_id)}
        candidates: list[str] = []
        if requested:
            candidates = [requested]
        else:
            default = str(definition.get("default_model") or "")
            if default:
                candidates.append(default)
            for item in reg.get_models(provider_id):
                if item.get("available") is False or item.get("deprecated"):
                    continue
                if item["id"] not in candidates and "chat" in (item.get("capabilities") or ["chat"]):
                    candidates.append(item["id"])
        last_reason = "no model is configured or discovered for this provider"
        for model_id in candidates[:24]:
            entry = known.get(model_id)
            effective = dict(entry) if entry else None
            if effective is not None:
                effective["free"] = reg.effective_free(effective)
                if effective.get("available") is False or effective.get("deprecated"):
                    last_reason = f"model {model_id} is no longer listed by the provider (retired or renamed)"
                    continue
            allowed, reason = _policy.model_allowed(policy, definition, effective, overrides)
            if allowed:
                if model_id == "openrouter/free":
                    resolved = next((item["id"] for item in reg.get_models(provider_id)
                                     if item["id"].endswith(":free") and item.get("available") is not False), None)
                    if resolved:
                        return resolved, known.get(resolved)
                    last_reason = "no ':free' OpenRouter model is currently discovered — refresh the catalog"
                    continue
                return model_id, effective
            last_reason = f"{model_id}: {reason}"
        raise ProviderError("blocked_policy" if "free-only" in last_reason or "pricing" in last_reason else "model_unavailable", last_reason)

    def _chat_ollama(self, definition: dict[str, Any], model: str, messages: list[dict[str, str]],
                     settings: dict[str, Any]) -> str:
        base = str(settings.get("ollama_endpoint") or definition["base_url"]).rstrip("/")
        timeout = float(settings.get("local_chat_timeout_seconds") or _DEFAULT_LOCAL_TIMEOUT)
        status, payload = _http_json(base + "/api/chat", method="POST", body={
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": 768},
        }, timeout=timeout)
        if not isinstance(payload, dict):
            raise ProviderError("provider_error", "unexpected Ollama response shape")
        content = ((payload.get("message") or {}).get("content") or "").strip()
        if not content:
            raise ProviderError("provider_error", "Ollama returned an empty reply")
        return content

    def _chat_openai(self, definition: dict[str, Any], model: str, messages: list[dict[str, str]],
                     timeout: float) -> str:
        base = str(definition["base_url"]).rstrip("/")
        url = base + "/chat/completions" if not definition.get("base_is_endpoint") else base
        status, payload = _http_json(url, method="POST", headers=self._auth_headers(definition), body={
            "model": model,
            "messages": messages,
            "stream": False,
        }, timeout=timeout)
        if not isinstance(payload, dict):
            raise ProviderError("provider_error", "unexpected response shape")
        choices = payload.get("choices") or []
        if not choices:
            raise ProviderError("provider_error", "provider returned no choices")
        content = ((choices[0] or {}).get("message") or {}).get("content") or ""
        if isinstance(content, list):
            content = " ".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
        content = str(content).strip()
        if not content:
            raise ProviderError("provider_error", "provider returned an empty reply")
        return content

    def _chat_gemini(self, definition: dict[str, Any], model: str, messages: list[dict[str, str]],
                     timeout: float) -> str:
        key = _keys.get_key(str(definition.get("key_slot") or ""))
        if not key:
            raise ProviderError("no_api_key", f"API key not configured (set {definition.get('key_slot')})")
        system_parts = [item["content"] for item in messages if item.get("role") == "system"]
        contents = []
        for item in messages:
            role = item.get("role")
            if role == "system":
                continue
            contents.append({
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": str(item.get("content") or "")}],
            })
        body: dict[str, Any] = {"contents": contents}
        if system_parts:
            body["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}
        url = str(definition["base_url"]).rstrip("/") + f"/models/{urllib.parse.quote(model)}:generateContent"
        status, payload = _http_json(url, method="POST", headers={"x-goog-api-key": key}, body=body, timeout=timeout)
        if not isinstance(payload, dict):
            raise ProviderError("provider_error", "unexpected Gemini response shape")
        candidates = payload.get("candidates") or []
        if not candidates:
            feedback = payload.get("promptFeedback") or {}
            raise ProviderError("provider_error", "Gemini returned no candidates " + json.dumps(feedback)[:120])
        parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
        text = " ".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
        if not text:
            raise ProviderError("provider_error", "Gemini returned an empty reply")
        return text

    def _chat_cloudflare(self, definition: dict[str, Any], model: str, messages: list[dict[str, str]],
                         timeout: float) -> str:
        account = _keys.get_key("CLOUDFLARE_ACCOUNT_ID")
        if not account:
            raise ProviderError("no_api_key", "configuration not complete (set CLOUDFLARE_ACCOUNT_ID)")
        url = (str(definition["base_url"]).rstrip("/")
               + f"/accounts/{urllib.parse.quote(account)}/ai/v1/chat/completions")
        status, payload = _http_json(url, method="POST", headers=self._auth_headers(definition), body={
            "model": model, "messages": messages, "stream": False,
        }, timeout=timeout)
        if not isinstance(payload, dict):
            raise ProviderError("provider_error", "unexpected response shape")
        choices = payload.get("choices") or []
        content = str(((choices[0] or {}).get("message") or {}).get("content") or "").strip() if choices else ""
        if not content:
            # Workers AI native shape fallback.
            content = str(((payload.get("result") or {}) if isinstance(payload.get("result"), dict) else {}).get("response") or "").strip()
        if not content:
            raise ProviderError("provider_error", "Cloudflare returned an empty reply")
        return content

    def _chat(self, definition: dict[str, Any], model: str, messages: list[dict[str, str]],
              settings: dict[str, Any]) -> str:
        api = str(definition.get("api") or "openai")
        timeout = float(settings.get("cloud_timeout_seconds") or _DEFAULT_CLOUD_TIMEOUT)
        if api == "ollama":
            return self._chat_ollama(definition, model, messages, settings)
        if api == "gemini":
            return self._chat_gemini(definition, model, messages, timeout)
        if api == "cloudflare":
            return self._chat_cloudflare(definition, model, messages, timeout)
        return self._chat_openai(definition, model, messages, timeout)

    # --------------------------------------------------------------- generate

    def candidate_order(self, settings: dict[str, Any]) -> list[str]:
        preferred = str(settings.get("conversation_provider") or "auto")
        order = list(_catalog.DEFAULT_FALLBACK_ORDER)
        if preferred != "auto" and preferred in order:
            order.remove(preferred)
            order.insert(0, preferred)
        return order

    def generate(self, messages: list[dict[str, str]], settings: dict[str, Any] | None = None, *,
                 provider_id: str | None = None, model: str | None = None,
                 allow_fallback: bool = True, purpose: str = "conversation") -> dict[str, Any]:
        """Generate text through the first eligible provider.

        Never calls a model that the cost policy does not allow. Returns a
        structured result; on total failure the message is explicit and NO
        paid endpoint has been contacted.
        """
        settings = settings or {}
        policy = _policy.cost_policy(settings)
        total_chars = sum(len(str(item.get("content") or "")) for item in messages)
        if total_chars > _CHAT_MAX_CHARS:
            # Trim oldest non-system turns rather than failing.
            system = [item for item in messages if item.get("role") == "system"]
            rest = [item for item in messages if item.get("role") != "system"]
            while rest and sum(len(str(item.get("content") or "")) for item in system + rest) > _CHAT_MAX_CHARS:
                rest.pop(0)
            messages = system + rest
        if provider_id:
            preferred_target: str | None = provider_id
            wanted_model = model
            order = [provider_id]
            if allow_fallback:
                order += [item for item in self.candidate_order(settings) if item != provider_id]
        else:
            configured = str(settings.get("conversation_provider") or "auto")
            preferred_target = configured if configured != "auto" else None
            wanted_model = model or (str(settings.get("conversation_model") or "") or None)
            order = self.candidate_order(settings)
        attempts: list[dict[str, Any]] = []
        for candidate in order:
            # A pinned model only applies to the provider it was pinned for;
            # fallback providers resolve their own policy-allowed model.
            requested_model = wanted_model if (preferred_target and candidate == preferred_target) else None
            try:
                definition = self._definition(candidate)
            except ProviderError as exc:
                attempts.append({"provider": candidate, "state": exc.kind, "detail": exc.detail})
                continue
            if not self._enabled(definition):
                attempts.append({"provider": candidate, "state": "disabled", "detail": "provider is disabled in settings"})
                continue
            if definition.get("mode") == "cloud":
                gate = self._cloud_gate(settings)
                if gate:
                    attempts.append({"provider": candidate, "state": "network_blocked", "detail": gate})
                    continue
            overrides = self._overrides(candidate)
            allowed, reason = _policy.provider_allowed(policy, definition, overrides)
            if not allowed:
                attempts.append({"provider": candidate, "state": "blocked_policy", "detail": reason})
                continue
            key_ok, key_reason = self._key_ok(definition)
            if not key_ok:
                attempts.append({"provider": candidate, "state": "no_api_key", "detail": key_reason})
                continue
            cooldown = self._in_cooldown(candidate)
            if cooldown > 0:
                stat = self._stat(candidate)
                attempts.append({"provider": candidate, "state": "cooling_down",
                                 "detail": f"temporarily unavailable after {stat.get('last_error_kind')} ({int(cooldown)}s remaining)"})
                continue
            try:
                resolved_model, model_entry = self._resolve_model(definition, requested_model, policy, overrides)
            except ProviderError as exc:
                if exc.kind in {"blocked_policy", "model_unavailable"} and str(definition.get("discovery")) not in {"static", "ollama-tags"}:
                    # One discovery attempt before giving up on this provider.
                    try:
                        self.discover_models(candidate, settings)
                        resolved_model, model_entry = self._resolve_model(definition, requested_model, policy, overrides)
                    except ProviderError as retry_exc:
                        attempts.append({"provider": candidate, "state": retry_exc.kind, "detail": retry_exc.detail})
                        continue
                else:
                    attempts.append({"provider": candidate, "state": exc.kind, "detail": exc.detail})
                    continue
            started = time.monotonic()
            try:
                reply = self._chat(definition, resolved_model, messages, settings)
                latency_ms = int((time.monotonic() - started) * 1000)
                self._record_success(candidate, latency_ms)
                return {
                    "state": "responded",
                    "provider": candidate,
                    "provider_name": definition.get("name"),
                    "family": definition.get("family"),
                    "mode": definition.get("mode"),
                    "model": resolved_model,
                    "free": (model_entry or {}).get("free", True if definition.get("mode") == "local" else None),
                    "latency_ms": latency_ms,
                    "reply": reply[:16000],
                    "attempts": attempts,
                    "purpose": purpose,
                    "policy": policy,
                }
            except ProviderError as exc:
                self._record_failure(candidate, exc)
                detail = exc.detail
                if candidate == "ollama-local" and exc.kind == "timeout":
                    detail = "Qwen inference timed out — the model may still be loading (cold start), not absent."
                elif candidate == "ollama-local" and exc.kind == "network_unavailable":
                    detail = ("Ollama is not installed (the `ollama` binary is not on PATH)."
                              if shutil.which("ollama") is None
                              else f"Ollama is installed but not running ({exc.detail}). Start it with: ollama serve")
                attempts.append({"provider": candidate, "model": resolved_model, "state": exc.kind, "detail": detail})
                if not allow_fallback:
                    break
                continue
        return {
            "state": "unavailable",
            "message": "All configured free AI providers are currently unavailable.",
            "attempts": attempts,
            "policy": policy,
            "purpose": purpose,
        }

    # ------------------------------------------------------------- secondary

    def consensus(self, prompt: str, settings: dict[str, Any] | None = None, *,
                  max_models: int = 3) -> dict[str, Any]:
        """Optional model council: ask several providers, then synthesize."""
        settings = settings or {}
        messages = [{"role": "system", "content": CONVERSATION_SYSTEM_PROMPT},
                    {"role": "user", "content": str(prompt)[:8000]}]
        responses: list[dict[str, Any]] = []
        used: set[str] = set()
        for candidate in self.candidate_order(settings):
            if len(responses) >= max(1, min(max_models, 4)):
                break
            family = str((_catalog.provider_def(candidate) or {}).get("family") or candidate)
            if family in used:
                continue
            result = self.generate(messages, settings, provider_id=candidate, allow_fallback=False, purpose="consensus")
            if result.get("state") == "responded":
                used.add(family)
                responses.append(result)
        if not responses:
            return {"state": "unavailable", "message": "All configured free AI providers are currently unavailable.", "responses": []}
        if len(responses) == 1:
            return {"state": "responded", "responses": responses, "synthesis": responses[0].get("reply"),
                    "synthesizer": responses[0].get("provider")}
        digest = "\n\n".join(
            f"[{item.get('provider_name') or item.get('provider')} / {item.get('model')}]\n{str(item.get('reply'))[:2500]}"
            for item in responses
        )
        synth_messages = [
            {"role": "system", "content": "You are Vortex's synthesis model. Combine the candidate answers below into one accurate, concise answer. Note real disagreements explicitly."},
            {"role": "user", "content": f"Question:\n{str(prompt)[:4000]}\n\nCandidate answers:\n{digest}"},
        ]
        synthesis = self.generate(synth_messages, settings, purpose="consensus-synthesis")
        return {
            "state": "responded",
            "responses": responses,
            "synthesis": synthesis.get("reply") if synthesis.get("state") == "responded" else None,
            "synthesizer": synthesis.get("provider") if synthesis.get("state") == "responded" else None,
        }

    # ------------------------------------------------------------- snapshots

    def providers_snapshot(self, settings: dict[str, Any] | None = None, *, probe_local: bool = True) -> dict[str, Any]:
        settings = settings or {}
        policy = _policy.cost_policy(settings)
        reg = _registry()
        cloud_gate = self._cloud_gate(settings)
        providers = []
        for raw in sorted(_catalog.PROVIDER_DEFS, key=lambda item: item.get("priority", 99)):
            definition = self._definition(raw["id"])
            overrides = self._overrides(definition["id"])
            allowed, reason = _policy.provider_allowed(policy, definition, overrides)
            key_ok, key_reason = self._key_ok(definition)
            stat = dict(self._stat(definition["id"]))
            cooldown = self._in_cooldown(definition["id"])
            stat["cooldown_seconds"] = int(cooldown)
            stat.pop("cooldown_until", None)
            models = reg.get_models(definition["id"])
            entry: dict[str, Any] = {
                "id": definition["id"],
                "name": definition["name"],
                "family": definition["family"],
                "mode": definition["mode"],
                "base_url": definition["base_url"],
                "free_status": definition["free_status"],
                "free_detail": definition.get("free_detail"),
                "enabled": self._enabled(definition),
                "allow_in_free_mode": overrides.get("allow_in_free_mode") is True,
                "requires_api_key": bool(definition.get("key_slot")),
                "key_slot": definition.get("key_slot"),
                "key_configured": key_ok if definition.get("key_slot") or definition.get("extra_key_slots") else True,
                "key_reason": None if key_ok else key_reason,
                "policy_allowed": allowed,
                "policy_reason": reason,
                "default_model": definition.get("default_model") or None,
                "models": models[:60],
                "models_refreshed_at": reg.refreshed_at(definition["id"]),
                "stats": stat,
                "cloud_blocked": cloud_gate if definition.get("mode") == "cloud" else None,
                "health": self._health.get(definition["id"]),
            }
            if definition.get("family") == "google-gemini":
                entry["gemini"] = self.gemini_config().get(definition["id"])
            providers.append(entry)
        local = dict(self._local_runtime)
        if probe_local or not local:
            try:
                local = self.local_status(settings)
            except Exception:
                local = dict(self._local_runtime)
        return {
            "policy": policy,
            "free_only": policy.get("free_only"),
            "cloud_gate": cloud_gate,
            "conversation_provider": str(settings.get("conversation_provider") or "auto"),
            "conversation_model": str(settings.get("conversation_model") or ""),
            "secondary_ai_mode": str(settings.get("secondary_ai_mode") or "on-demand"),
            "fallback_order": self.candidate_order(settings),
            "local": local,
            "providers": providers,
            "key_slots": _keys.configured_slots(),
        }

    def health_check(self, provider_id: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = settings or {}
        definition = self._definition(provider_id)
        started = time.monotonic()
        result: dict[str, Any] = {"provider": provider_id, "checked_at": _now_iso()}
        if provider_id == "ollama-local":
            local = self.local_status(settings)
            result.update({"state": local.get("state"), "detail": local.get("message"),
                           "latency_ms": local.get("latency_ms")})
        else:
            try:
                models = self.discover_models(provider_id, settings)
                free_count = sum(1 for item in models if item.get("free") is True)
                result.update({
                    "state": "ready",
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "models_discovered": len(models),
                    "free_models": free_count,
                    "detail": f"Provider ready — {len(models)} model(s) discovered, {free_count} verified $0.",
                })
            except ProviderError as exc:
                result.update({"state": exc.kind, "detail": exc.detail,
                               "latency_ms": int((time.monotonic() - started) * 1000)})
        with self._lock:
            self._health[provider_id] = result
        return result

    def diagnostics(self, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        """Developer diagnostics. Credentials are masked everywhere."""
        settings = settings or {}
        snapshot = self.providers_snapshot(settings, probe_local=True)
        lines = ["AI PROVIDER DIAGNOSTICS", ""]
        local = snapshot.get("local") or {}
        lines.append("Ollama (local)")
        lines.append(f"  Status: {str(local.get('state') or 'unknown').upper()}")
        lines.append(f"  Model: {local.get('model')}")
        if local.get("latency_ms") is not None:
            lines.append(f"  Latency: {local['latency_ms'] / 1000:.1f}s")
        lines.append("  Billing: LOCAL / $0")
        lines.append(f"  Last check: {local.get('checked_at')}")
        lines.append(f"  Note: {local.get('message')}")
        lines.append("")
        for provider in snapshot.get("providers") or []:
            if provider["id"] == "ollama-local":
                continue
            stat = provider.get("stats") or {}
            health = provider.get("health") or {}
            state = (health.get("state") or stat.get("last_error_kind")
                     or ("disabled" if not provider.get("enabled") else None)
                     or ("no_api_key" if not provider.get("key_configured") else "unchecked"))
            billing = {"free": "FREE", "conditional": "FREE TIER (per-model verification)",
                       "unknown": "UNKNOWN"}.get(str(provider.get("free_status")), "UNKNOWN")
            lines.append(str(provider.get("name")))
            lines.append(f"  Status: {str(state).upper()}")
            if provider.get("gemini"):
                slot = str((provider.get("gemini") or {}).get("key_slot") or "")
                lines.append(f"  Model: {(provider.get('gemini') or {}).get('model')}")
                lines.append(f"  Key slot: {slot[-1] if slot else '?'} ({'configured' if provider.get('key_configured') else 'NOT configured'})")
            else:
                lines.append(f"  Model: {provider.get('default_model') or 'dynamic (discovered)'}")
                if provider.get("key_slot"):
                    lines.append(f"  Key: {provider['key_slot']} ({'configured' if provider.get('key_configured') else 'NOT configured'})")
            lines.append(f"  Billing: {billing}")
            if stat.get("latency_ms_ewma"):
                lines.append(f"  Latency: {stat['latency_ms_ewma'] / 1000:.1f}s")
            if stat.get("requests"):
                lines.append(f"  Requests: {stat['requests']} ({stat['ok']} ok, {stat['failures']} failed, {stat['http_429']} rate-limited)")
            if stat.get("last_error"):
                lines.append(f"  Last error: {stat.get('last_error_kind')}: {stat.get('last_error')}")
            if provider.get("cloud_blocked"):
                lines.append(f"  Blocked: {provider['cloud_blocked']}")
            elif not provider.get("policy_allowed"):
                lines.append(f"  Blocked: {provider.get('policy_reason')}")
            lines.append("")
        text = _keys.redact_secrets("\n".join(lines))
        return {"text": text, "snapshot": snapshot}


_MANAGER = ProviderManager()


def manager() -> ProviderManager:
    return _MANAGER
