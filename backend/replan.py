"""Decide whether an observed operation completed the user's objective."""
from __future__ import annotations

from typing import Any

ACHIEVED_KINDS = {
    "identity", "clock", "filesystem_list", "filesystem", "processes",
    "network_interfaces", "plan", "os_release", "cpu",
}


def evaluate_objective(plan: dict[str, Any], operation: dict[str, Any] | None) -> dict[str, Any]:
    kind = plan.get("kind") or ""
    status = (operation or {}).get("status") if operation else plan.get("status")
    commands = (operation or {}).get("commands") or []
    if plan.get("status") in {"clarified", "rejected"}:
        return {"achieved": False, "replan": False, "reason": "No executable plan was produced.", "next_request": None}
    if plan.get("status") == "unavailable" or status == "unavailable":
        missing = plan.get("missing_tools") or []
        return {
            "achieved": False,
            "replan": False,
            "reason": "A required tool was missing. VORTEX will not invent results or silently install software.",
            "next_request": None,
            "missing_tools": missing,
        }
    if status in {"cancelled", "interrupted"}:
        return {"achieved": False, "replan": False, "reason": "The operator stopped execution.", "next_request": None}
    if status in {"failed", "timed_out"}:
        return {"achieved": False, "replan": True, "reason": "A command did not complete successfully. A fresh plan is required.", "next_request": plan.get("request")}
    if status == "succeeded" or (not operation and plan.get("status") == "planned"):
        if kind == "container_diagnose":
            joined = "\n".join((item.get("stdout") or "") + (item.get("stderr") or "") for item in commands).lower()
            if "cannot connect" in joined or "is the docker daemon running" in joined:
                return {
                    "achieved": False,
                    "replan": True,
                    "reason": "The client is installed but the daemon was not reachable. A service-inspection plan can be created if systemd is available.",
                    "next_request": "inspect service docker.service",
                }
        if kind in ACHIEVED_KINDS or kind in {"container_inspection", "container_logs", "container_diagnose", "authorized_engagement", "ssh_diagnostics", "package_operation", "systemd_mutation"}:
            if status == "succeeded":
                return {"achieved": True, "replan": False, "reason": "Observed commands completed; the declared adapter objective was met.", "next_request": None}
        if status == "succeeded":
            return {"achieved": True, "replan": False, "reason": "Observed terminal outcome reached.", "next_request": None}
    return {"achieved": False, "replan": False, "reason": "Insufficient evidence to declare the objective complete.", "next_request": None}
