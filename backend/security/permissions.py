"""Privilege requirements derived from command specs, not model text."""
from __future__ import annotations

from typing import Any


def required_privilege(commands: list[dict[str, Any]]) -> str:
    if any(spec.get("privilege") == "root-required" for spec in commands):
        return "root-required"
    return "user"
