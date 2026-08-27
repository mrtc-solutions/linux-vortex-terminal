"""Append-only JSON logs. Payloads are redacted; no secrets by default."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _clean(value: Any, redact) -> Any:
    if isinstance(value, str):
        return redact(value)[:2000]
    if isinstance(value, dict):
        return {str(key)[:80]: _clean(item, redact) for key, item in list(value.items())[:40]}
    if isinstance(value, list):
        return [_clean(item, redact) for item in value[:40]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact(str(value))[:200]


def log_event(store: Any, kind: str, payload: dict[str, Any]) -> None:
    try:
        from vortex_backend import data_root, now_iso, redact
    except ImportError:
        from backend.vortex_backend import data_root, now_iso, redact
    root = Path(getattr(store, "root", None) or data_root())
    path = root / "vortex.jsonl"
    record = {"at": now_iso(), "kind": kind, "payload": _clean(payload, redact)}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
