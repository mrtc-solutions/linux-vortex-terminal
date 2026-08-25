"""Controlled local benchmark using real commands. No fixtures become findings."""
from __future__ import annotations

import time
from typing import Any


CASES = (
    {"id": "identity", "request": "whoami", "category": "linux-admin"},
    {"id": "health", "request": "system health", "category": "linux-admin"},
    {"id": "disk", "request": "check disk space", "category": "linux-admin"},
)


def run_suite(store: Any, workspace: Any, executor: Any, cwd: str | None = None) -> dict[str, Any]:
    from orchestrate import run_turn
    results = []
    for case in CASES:
        started = time.monotonic()
        turn = run_turn(
            store, workspace, executor, case["request"],
            cwd=cwd, engagement_id=None, conversation_id=None,
            settings={"profile": "standard", "auto_low_risk": True, "offline": True},
        )
        operation = turn.get("operation")
        if operation:
            for _ in range(200):
                current = store.get_operation(operation["id"])
                if current and current.get("status") not in {"started", "running"}:
                    operation = current
                    break
                time.sleep(0.02)
        elapsed = int((time.monotonic() - started) * 1000)
        status = (operation or {}).get("status") or turn["plan"].get("status")
        results.append({
            "id": case["id"],
            "category": case["category"],
            "request": case["request"],
            "task_id": turn["task"]["id"],
            "plan_status": turn["plan"]["status"],
            "operation_status": status,
            "auto_executed": turn.get("auto_executed"),
            "duration_ms": elapsed,
            "success": status in {"succeeded", "planned", "clarified"} and turn["plan"]["status"] != "rejected",
            "commands": len((operation or {}).get("commands") or turn["plan"].get("commands") or []),
        })
    passed = sum(1 for item in results if item["success"])
    return {"product": "VORTEX", "cases": results, "passed": passed, "total": len(results), "pass_rate": passed / len(results) if results else 0}
