"""Engagement scope checks independent of the planner."""
from __future__ import annotations

from typing import Any


def _host(value: str) -> str:
    text = (value or "").strip().lower()
    if "://" in text:
        from urllib.parse import urlparse
        return (urlparse(text).hostname or text).lower()
    return text.split("/", 1)[0].split(":", 1)[0]


def excluded(target: str, engagement: dict[str, Any] | None) -> bool:
    if not engagement:
        return False
    host = _host(target)
    value = (target or "").strip().lower()
    for item in engagement.get("excluded_targets") or []:
        raw = str(item).strip().lower()
        if not raw:
            continue
        item_host = _host(raw)
        if value == raw or host == item_host or (item_host and host.endswith("." + item_host)):
            return True
    return False


def environment_class(engagement: dict[str, Any] | None, lab_mode: bool = False) -> str:
    if engagement and engagement.get("environment"):
        return str(engagement["environment"])
    if lab_mode:
        return "authorized-lab"
    if engagement:
        return "authorized-assessment"
    return "local-admin"
