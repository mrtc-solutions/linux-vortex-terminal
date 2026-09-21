"""Built-in deterministic advisor. Always present; never executes.

Thinks like a bounded operator: observe the request and host facts, recommend
the next Guardian-reviewed action, and refuse unconstrained shell. Local GGUF
files are listed honestly; missing FOSS tools are proposed only as
``install package NAME`` plans.
"""
from __future__ import annotations

from typing import Any

from .base import AgentAdapter, AgentManifest


def _gguf_commentary() -> str:
    try:
        try:
            from models.gguf import status as gguf_status
        except ImportError:
            from backend.models.gguf import status as gguf_status  # type: ignore
        snapshot = gguf_status()
        files = [
            str(item.get("name"))
            for item in (snapshot.get("files") or [])
            if item.get("valid") and item.get("name")
        ]
        engine = snapshot.get("engine") or {}
        engine_state = str(engine.get("state") or "unknown")
        if files:
            return "Local GGUF models: " + ", ".join(files[:8]) + f" (engine {engine_state})."
        return "No valid local GGUF models were discovered in the models directories."
    except Exception:
        return ""


def _foss_catalog() -> str:
    try:
        try:
            from adapter_registry import TOOL_CATALOG
        except ImportError:
            from backend.adapter_registry import TOOL_CATALOG  # type: ignore
        names = [str(name) for name in TOOL_CATALOG if str(name)][:24]
        if not names:
            return ""
        return (
            "FOSS catalog (install via typed 'install package NAME' only): "
            + ", ".join(names) + "."
        )
    except Exception:
        return ""


class LocalAdvisor(AgentAdapter):
    def health_check(self) -> dict[str, Any]:
        return {
            "status": "installed",
            "availability": "builtin",
            "healthy": True,
            "version": "0.3.0",
            "path": "builtin",
            "message": "Built-in deterministic advisor. Advisory only; Guardian still authorizes every action.",
        }

    def submit_task(self, task: dict[str, Any]) -> dict[str, Any]:
        observation = task.get("observation") or {}
        missing = observation.get("missing_tools") or []
        adapters = observation.get("legal_adapters") or []
        request = str(task.get("request") or observation.get("instruction") or "").strip()[:240]
        parts: list[str] = []
        if request:
            parts.append("THINK: Operator asked: " + request + ".")
        else:
            parts.append("THINK: Review the observed plan without inventing a goal.")
        parts.append(
            "Work like a bounded operator: observe facts, propose one Guardian-reviewed "
            "typed argv step, then stop. Never spawn unconstrained shell."
        )
        if missing:
            parts.append("Missing tools: " + ", ".join(str(item) for item in missing) + ". No output was invented.")
        if adapters:
            parts.append("Legal adapters: " + ", ".join(str(item) for item in adapters) + ".")
        else:
            parts.append("No executable adapter was planned.")
        if missing:
            names = [str(item).strip() for item in missing if str(item).strip()][:6]
            recs = "; ".join(f"install package {name}" for name in names)
            if recs:
                parts.append(
                    "RECOMMEND: Plan " + recs
                    + " (Guardian-reviewed apt only; never a silent download)."
                )
        elif adapters:
            parts.append("RECOMMEND: Guardian still authorizes every adapter before execution.")
        else:
            parts.append(
                "RECOMMEND: Ask a narrower reviewed command, or start Agent Mode for a "
                "bounded think-plan-Guardian-execute-observe loop."
            )
        gguf = _gguf_commentary()
        if gguf:
            parts.append(gguf)
        foss = _foss_catalog()
        if foss:
            parts.append(foss)
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
    "Vortex Terminal Local Advisor",
    "builtin",
    "MIT",
    (),
    ("observation-commentary", "think-observe-recommend"),
    risk_level="low",
    trust_level="builtin",
    notes="Deterministic local advisor. Thinks, then recommends. Never executes commands.",
    execution_mode="advisory",
))
