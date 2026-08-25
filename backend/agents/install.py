"""Controlled install *proposals*. Nothing is installed unless the operator runs it."""
from __future__ import annotations

from typing import Any

from .council import ADAPTERS


def proposal(agent_id: str) -> dict[str, Any]:
    adapter = ADAPTERS.get(agent_id)
    if not adapter:
        return {"agent": agent_id, "state": "unknown", "auto_install": False, "message": "Unknown agent."}
    health = adapter.health_check()
    if health.get("healthy"):
        return {"agent": agent_id, "state": "installed", "auto_install": False, "path": health.get("path"), "message": "Already present. No install is required."}
    repo = adapter.manifest.repository or "unverified"
    return {
        "agent": agent_id,
        "name": adapter.manifest.name,
        "state": "missing",
        "auto_install": False,
        "source": repo,
        "license": adapter.manifest.license,
        "permissions": ["operator-owned-python-or-docker", "network-to-source", "no-sudo-from-vortex"],
        "commands": [
            f"# Review {repo} and its license before installing.",
            "# VORTEX will not run this for you.",
        ],
        "message": "Install is operator-controlled. VORTEX does not silently install third-party agents.",
    }
