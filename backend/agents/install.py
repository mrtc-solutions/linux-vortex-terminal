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
    try:
        from .upstream import install_guide, table
    except ImportError:
        try:
            from agents.upstream import install_guide, table  # type: ignore
        except ImportError:
            from backend.agents.upstream import install_guide, table  # type: ignore
    guide = install_guide(agent_id)
    upstream = (table().get(agent_id) or {})
    commands = [f"# {step}" if not str(step).startswith("#") else str(step) for step in guide]
    commands.append("# VORTEX will not run this for you.")
    return {
        "agent": agent_id,
        "name": adapter.manifest.name,
        "state": "missing",
        "auto_install": False,
        "source": repo,
        "docs": upstream.get("docs") or repo,
        "license": adapter.manifest.license,
        "sync_state": upstream.get("sync_state") or "not_checked",
        "permissions": ["operator-owned-python-or-docker", "network-to-source", "no-sudo-from-vortex"],
        "commands": commands,
        "message": "Install is operator-controlled. VORTEX does not silently install third-party agents.",
    }
