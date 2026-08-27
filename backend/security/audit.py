"""Security-event helper around the hash-chained audit log."""
from __future__ import annotations

from typing import Any


def record(store: Any, kind: str, payload: dict[str, Any]) -> str:
    return store.append_audit(kind, payload)
