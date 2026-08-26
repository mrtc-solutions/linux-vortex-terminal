"""Security assessment reports from engagement + observed findings only."""
from __future__ import annotations

from typing import Any


def build(engagement: dict[str, Any], findings: list[dict[str, Any]], operations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "kind": "security-assessment",
        "engagement": {
            "id": engagement.get("id"),
            "name": engagement.get("name"),
            "authorization": engagement.get("authorization"),
            "targets": engagement.get("targets"),
            "excluded_targets": engagement.get("excluded_targets") or [],
            "classes": engagement.get("classes"),
            "status": engagement.get("status"),
        },
        "methodology": "Reviewed VORTEX adapters only. No fabricated scanner output.",
        "operations": len(operations),
        "findings": findings,
        "conclusion": "Findings are observed evidence, not confirmed vulnerabilities." if findings else "No observed findings were recorded for this engagement.",
    }


def as_operation_view(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": document.get("engagement", {}).get("id") or "assessment",
        "plan_id": "",
        "status": "observed",
        "commands": [],
        "analysis": {
            "fact": document.get("conclusion"),
            "inference": "Scope and methodology are operator-declared.",
            "unknown": "Absence of findings is not proof of security.",
        },
        "artifacts": [],
    }
