"""Dynamic model catalog cache.

Stores per-provider model lists with pricing/free metadata and a
``verified_at`` timestamp, so FREE-ONLY mode can reject models whose $0
status is stale or has changed. Nothing here is permanent: providers
retire models and move them between free and paid, and this cache records
exactly what was observed and when.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_MAX_MODELS_PER_PROVIDER = 256
_MAX_CATALOG_BYTES = 2 * 1024 * 1024
# After this long without re-verification a "free" marking degrades to
# unknown (None) for policy purposes.
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


def normalize_model(provider_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a discovered model into the registry schema."""
    model_id = str(raw.get("id") or "")[:200]
    free = raw.get("free")
    if free is not None:
        free = bool(free)
    entry = {
        "id": model_id,
        "provider": str(provider_id)[:64],
        "label": str(raw.get("label") or model_id)[:200],
        "free": free,
        "price_input": raw.get("price_input"),
        "price_output": raw.get("price_output"),
        "context_length": raw.get("context_length"),
        "capabilities": [str(item)[:40] for item in (raw.get("capabilities") or [])][:12],
        "modalities_in": [str(item)[:24] for item in (raw.get("modalities_in") or ["text"])][:6],
        "modalities_out": [str(item)[:24] for item in (raw.get("modalities_out") or ["text"])][:6],
        "reasoning": bool(raw.get("reasoning", False)),
        "tool_calling": bool(raw.get("tool_calling", False)),
        "available": raw.get("available", True) is not False,
        "deprecated": bool(raw.get("deprecated", False)),
        "detail": str(raw.get("detail") or "")[:300],
        "verified_at": str(raw.get("verified_at") or _now_iso())[:40],
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
        normalized = [normalize_model(provider_id, item) for item in models[:_MAX_MODELS_PER_PROVIDER] if item.get("id")]
        providers = self._data.setdefault("providers", {})
        previous = {item["id"]: item for item in (providers.get(provider_id, {}).get("models") or [])}
        # A model that disappears from discovery is kept but marked
        # unavailable/deprecated so the UI can explain retirement honestly.
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
        return normalized

    def get_models(self, provider_id: str) -> list[dict[str, Any]]:
        self._load()
        entry = (self._data.get("providers") or {}).get(provider_id) or {}
        models = entry.get("models") or []
        return [dict(item) for item in models if isinstance(item, dict)]

    def refreshed_at(self, provider_id: str) -> str | None:
        self._load()
        entry = (self._data.get("providers") or {}).get(provider_id) or {}
        value = entry.get("refreshed_at")
        return str(value) if value else None

    def effective_free(self, model_entry: dict[str, Any]) -> bool | None:
        """Free marking, degraded to unknown when verification is stale."""
        free = model_entry.get("free")
        if free is not True:
            return free
        verified = str(model_entry.get("verified_at") or "")
        try:
            parsed = time.strptime(verified, "%Y-%m-%dT%H:%M:%SZ")
            age = time.time() - time.mktime(parsed) + time.timezone
        except (ValueError, OverflowError):
            return None
        if age > FRESHNESS_SECONDS:
            return None
        return True


_REGISTRY = ModelRegistry()


def registry() -> ModelRegistry:
    return _REGISTRY
