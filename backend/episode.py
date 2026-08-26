"""Observation → action → evaluation loop.

Inspired by the Windows Agent Arena POMDP framing (observe, act, evaluate
from environment state). VORTEX applies that on Linux with reviewed argv
only. Agents never receive process control; reward comes from observed
command outcomes, not model text.

Reference: https://github.com/microsoft/WindowsAgentArena (MIT). No WAA
source is vendored.
"""
from __future__ import annotations

from typing import Any


def observe(plan: dict[str, Any], operation: dict[str, Any] | None = None, *, host: dict[str, Any] | None = None) -> dict[str, Any]:
    commands = (operation or {}).get("commands") or []
    return {
        "schema": "vortex-observation-v1",
        "instruction": plan.get("request"),
        "plan_id": plan.get("id"),
        "plan_status": plan.get("status"),
        "plan_kind": plan.get("kind"),
        "missing_tools": list(plan.get("missing_tools") or []),
        "legal_adapters": [spec.get("adapter_id") for spec in plan.get("commands") or [] if spec.get("adapter_id")],
        "last_operation_status": (operation or {}).get("status"),
        "last_exit_codes": [item.get("exit_code") for item in commands],
        "observed_command_count": len(commands),
        "untrusted_output": True,
        "host": {
            "distribution": ((host or {}).get("distribution") or {}).get("id"),
            "architecture": (host or {}).get("architecture"),
            "uid": (host or {}).get("uid"),
        } if host else None,
    }


def legal_actions(plan: dict[str, Any]) -> list[dict[str, Any]]:
    actions = []
    for spec in plan.get("commands") or []:
        actions.append({
            "type": "execute_argv",
            "adapter_id": spec.get("adapter_id"),
            "display": spec.get("display"),
            "risk": spec.get("risk"),
            "privilege": spec.get("privilege") or "user",
            "requires_guardian": True,
        })
    return actions


def reward(plan: dict[str, Any], operation: dict[str, Any] | None) -> dict[str, Any]:
    try:
        from replan import evaluate_objective
    except ImportError:
        from backend.replan import evaluate_objective
    objective = evaluate_objective(plan, operation)
    achieved = bool(objective.get("achieved"))
    return {
        "reward": 1.0 if achieved else 0.0,
        "done": achieved or not objective.get("replan"),
        "achieved": achieved,
        "replan": bool(objective.get("replan")),
        "reason": objective.get("reason"),
        "next_request": objective.get("next_request"),
        "missing_tools": objective.get("missing_tools") or [],
        "source": "observed-host-state",
    }


def step(plan: dict[str, Any], operation: dict[str, Any] | None = None, *, host: dict[str, Any] | None = None) -> dict[str, Any]:
    observation = observe(plan, operation, host=host)
    return {
        "observation": observation,
        "actions": legal_actions(plan),
        "evaluation": reward(plan, operation),
        "note": "Reward is computed from observed Linux outcomes. Agent text cannot change it.",
    }
