"""Dynamic model catalog cache and registry.

Stores per-provider model lists with comprehensive pricing, free metadata,
capabilities, context limits, and verification timestamps.

Discovery is dynamic: models are probed from official endpoints or the
open-free-llm-api reference catalogue, and their availability is re-evaluated.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

try:
    from . import catalog as _catalog
except ImportError:
    try:
        from providers import catalog as _catalog  # type: ignore
    except ImportError:
        from backend.providers import catalog as _catalog  # type: ignore

_MAX_MODELS_PER_PROVIDER = 256
_MAX_CATALOG_BYTES = 4 * 1024 * 1024
FRESHNESS_SECONDS = 7 * 24 * 3600


def _catalog_path() -> Path | None:
    try:
        try:
            from vortex_backend import config_root  # type: ignore
        except ImportError:
            from backend.vortex_backend import config_root  # type: ignore
        root = config_root() / "providers"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return root / "model_catalog.json"
    except Exception:
        return None


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_iso(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        import calendar
        parsed = time.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
        return calendar.timegm(parsed)
    except Exception:
        return None


def normalize_model(provider_id: str, raw: dict[str, Any], definition: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize a discovered model into the registry schema."""
    if definition is None:
        definition = _catalog.provider_def(provider_id) or {}

    model_id = str(raw.get("id") or raw.get("modelId") or "")[:200]
    label = str(raw.get("displayName") or raw.get("label") or model_id)[:200]
    mode = str(raw.get("mode") or definition.get("mode") or "cloud")

    free = raw.get("free")
    if free is not None:
        free = bool(free)
    else:
        # Infer from provider default free status if not explicitly given
        prov_status = str(definition.get("free_status") or _catalog.STATUS_UNKNOWN)
        if prov_status in {
            _catalog.STATUS_LOCAL_0,
            _catalog.STATUS_FREE_NO_CARD,
            _catalog.STATUS_FREE_REGISTRATION,
            _catalog.STATUS_FREE_PHONE_VERIFICATION,
            _catalog.STATUS_FREE_RATE_LIMITED,
            _catalog.STATUS_RENEWABLE_CREDITS,
        }:
            free = True
        elif prov_status in {_catalog.STATUS_PAID, _catalog.STATUS_TRIAL_ONLY, _catalog.STATUS_UNKNOWN, "unknown"}:
            free = None

    free_status = str(raw.get("freeStatus") or raw.get("free_status") or definition.get("free_status") or _catalog.STATUS_UNKNOWN)
    pricing_status = "free" if free else ("conditional" if free is None else "paid")

    input_price = raw.get("inputPrice", raw.get("price_input"))
    output_price = raw.get("outputPrice", raw.get("price_output"))
    context_length = raw.get("contextLength", raw.get("context_length", definition.get("context_length")))
    rate_limits = raw.get("rateLimits", raw.get("rate_limits", definition.get("rate_limits")))
    source_url = str(raw.get("sourceUrl") or raw.get("source_url") or definition.get("source_url") or "")

    raw_caps = raw.get("capabilities")
    if raw_caps is None:
        capabilities = ["chat"]
    else:
        capabilities = [str(item)[:40] for item in raw_caps][:12]

    modalities = [str(item)[:24] for item in (raw.get("modalities") or raw.get("modalities_in") or ["text"])][:6]
    verified_at = str(raw.get("lastVerified") or raw.get("verified_at") or _now_iso())[:40]

    entry = {
        # CamelCase schema matching spec
        "id": model_id,
        "providerId": str(provider_id)[:64],
        "displayName": label,
        "modelId": model_id,
        "mode": mode,
        "freeStatus": free_status,
        "pricingStatus": pricing_status,
        "inputPrice": input_price,
        "outputPrice": output_price,
        "contextLength": context_length,
        "modalities": modalities,
        "capabilities": capabilities,
        "rateLimits": rate_limits,
        "requiresApiKey": bool(definition.get("requires_api_key", True)),
        "requiresCard": bool(definition.get("requires_card", False)),
        "requiresPhone": bool(definition.get("requires_phone", False)),
        "enabled": raw.get("enabled", True) is not False,
        "healthy": raw.get("healthy", True) is not False,
        "lastVerified": verified_at,
        "sourceUrl": source_url,

        # Snake_case compatibility aliases
        "provider": str(provider_id)[:64],
        "label": label,
        "free": free,
        "free_status": free_status,
        "price_input": input_price,
        "price_output": output_price,
        "context_length": context_length,
        "modalities_in": modalities,
        "modalities_out": [str(item)[:24] for item in (raw.get("modalities_out") or ["text"])][:6],
        "reasoning": bool(raw.get("reasoning", False)),
        "tool_calling": bool(raw.get("tool_calling", False)),
        "available": raw.get("available", True) is not False,
        "deprecated": bool(raw.get("deprecated", False)),
        "detail": str(raw.get("detail") or definition.get("free_detail") or "")[:300],
        "verified_at": verified_at,
    }
    return entry


class ModelRegistry:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {"providers": {}}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        path = _catalog_path()
        if path is None or not path.is_file():
            return
        try:
            raw = path.read_text(encoding="utf-8")
            if len(raw) > _MAX_CATALOG_BYTES:
                return
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and isinstance(parsed.get("providers"), dict):
                self._data = parsed
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        path = _catalog_path()
        if path is None:
            return
        try:
            try:
                from fileio import atomic_write  # type: ignore
            except ImportError:
                from backend.fileio import atomic_write  # type: ignore
            atomic_write(path, json.dumps(self._data, sort_keys=True), mode=0o600)
        except Exception:
            pass

    def update_models(self, provider_id: str, models: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self._load()
        definition = _catalog.provider_def(provider_id) or {}
        normalized = [normalize_model(provider_id, item, definition) for item in models[:_MAX_MODELS_PER_PROVIDER] if item.get("id")]
        providers = self._data.setdefault("providers", {})
        previous = {item["id"]: item for item in (providers.get(provider_id, {}).get("models") or [])}
        current_ids = {item["id"] for item in normalized}
        retired = []
        for old_id, old in previous.items():
            if old_id not in current_ids and old.get("available", True):
                old = dict(old)
                old["available"] = False
                old["deprecated"] = True
                old["detail"] = (str(old.get("detail") or "") + " No longer listed by the provider (possibly retired).").strip()[:300]
                retired.append(old)
        providers[provider_id] = {
            "models": normalized + retired[:32],
            "refreshed_at": _now_iso(),
        }
        self._save()
        return list(providers[provider_id]["models"])

    def get_models(self, provider_id: str) -> list[dict[str, Any]]:
        self._load()
        entry = self._data.get("providers", {}).get(provider_id)
        if entry and isinstance(entry.get("models"), list):
            return list(entry["models"])
        definition = _catalog.provider_def(provider_id) or {}
        static = definition.get("static_models")
        if static:
            return self.update_models(provider_id, static)
        default_model = definition.get("default_model")
        if default_model:
            return [normalize_model(provider_id, {"id": default_model, "label": default_model}, definition)]
        return []

    def all_models(self) -> dict[str, list[dict[str, Any]]]:
        self._load()
        result: dict[str, list[dict[str, Any]]] = {}
        for provider_id in _catalog.PROVIDERS_BY_ID:
            result[provider_id] = self.get_models(provider_id)
        return result

    def refreshed_at(self, provider_id: str) -> str | None:
        self._load()
        return self._data.get("providers", {}).get(provider_id, {}).get("refreshed_at")

    def effective_free(self, entry: dict[str, Any] | None) -> bool | None:
        if not entry or not isinstance(entry, dict):
            return None
        # Stale verification check
        verified_at = entry.get("lastVerified") or entry.get("verified_at")
        ts = _parse_iso(str(verified_at) if verified_at else None)
        now = time.time()
        if ts is not None and (now - ts) > FRESHNESS_SECONDS:
            return None
        if entry.get("free") is not None:
            return bool(entry["free"])
        status = str(entry.get("freeStatus") or entry.get("free_status") or "")
        if status in {
            _catalog.STATUS_LOCAL_0,
            _catalog.STATUS_FREE_NO_CARD,
            _catalog.STATUS_FREE_REGISTRATION,
            _catalog.STATUS_FREE_PHONE_VERIFICATION,
            _catalog.STATUS_FREE_RATE_LIMITED,
            _catalog.STATUS_RENEWABLE_CREDITS,
        }:
            return True
        if status in {_catalog.STATUS_PAID, _catalog.STATUS_TRIAL_ONLY, _catalog.STATUS_UNKNOWN, "unknown"}:
            return False
        return None


_REGISTRY: ModelRegistry | None = None


def registry() -> ModelRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ModelRegistry()
    return _REGISTRY
