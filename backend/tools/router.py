"""Stable internal tool router. Not MCP-dependent."""
from __future__ import annotations

from typing import Any


def route(intent: str) -> dict[str, Any]:
    intent = (intent or "").lower()
    mapping = (
        (("disk", "space", "df"), "linux.filesystem.usage"),
        (("whoami", "hostname", "pwd"), "linux.system.identity"),
        (("listen", "port", "socket"), "linux.network.sockets"),
        (("git",), "linux.development.git-status"),
        (("nmap",), "security.nmap.discovery"),
        (("curl", "http"), "security.http.headers"),
        (("docker", "podman", "container"), "linux.containers.inspect"),
    )
    for keys, adapter in mapping:
        if any(key in intent for key in keys):
            return {"protocol": "vortex-adapter", "adapter_id": adapter, "mcp": False}
    return {"protocol": "vortex-adapter", "adapter_id": None, "mcp": False, "message": "No reviewed adapter for this intent."}
