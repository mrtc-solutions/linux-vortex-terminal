"""Built-in deterministic advisor. Always present; never executes."""
from __future__ import annotations

from typing import Any

from .base import AgentAdapter, AgentManifest


class LocalAdvisor(AgentAdapter):
    def health_check(self) -> dict[str, Any]:
        return {
            "status": "installed",
            "availability": "builtin",
            "healthy": True,
            "version": "0.2.0",
            "path": "builtin",
            "message": "Built-in deterministic advisor. Advisory only; Guardian still authorizes every action.",
        }

    def submit_task(self, task: dict[str, Any]) -> dict[str, Any]:
        observation = task.get("observation") or {}
        missing = observation.get("missing_tools") or []
        adapters = observation.get("legal_adapters") or []
        parts = []
        if missing:
            parts.append("Missing tools: " + ", ".join(str(item) for item in missing) + ". No output was invented.")
        if adapters:
            parts.append("Legal adapters: " + ", ".join(str(item) for item in adapters) + ".")
        else:
            parts.append("No executable adapter was planned.")
        parts.append("This commentary is untrusted data, not authorization.")
        return {
            "agent": self.manifest.id,
            "state": "responded",
            "result": None,
            "message": " ".join(parts),
            "task_id": task.get("id"),
        }


ADAPTER = LocalAdvisor(AgentManifest(
    "vortex-local",
    "VORTEX Local Advisor",
    "builtin",
    "MIT",
    (),
    ("observation-commentary",),
    risk_level="low",
    trust_level="builtin",
    notes="Deterministic local advisor. Never executes commands.",
    execution_mode="advisory",
))
