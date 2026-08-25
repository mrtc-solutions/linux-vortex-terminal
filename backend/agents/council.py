"""Agent router, council, and critic. Agents recommend; Guardian decides."""
from __future__ import annotations

import os
from typing import Any

from . import cai, darkmoon, hackerai, halo, hexstrike, nebula, pentagi, pentestgpt, strix

ADAPTERS = {
    module.ADAPTER.manifest.id: module.ADAPTER
    for module in (hackerai, nebula, cai, pentestgpt, hexstrike, halo, pentagi, strix, darkmoon)
}


def resource_budget() -> dict[str, Any]:
    cpu = os.cpu_count() or 1
    mem_kb = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    mem_kb = int(line.split()[1])
                    break
    except (OSError, ValueError):
        pass
    load = 0.0
    try:
        load = os.getloadavg()[0]
    except (OSError, AttributeError):
        pass
    ram_mb = int(mem_kb / 1024) if mem_kb else None
    parallel = bool(cpu >= 4 and (ram_mb is None or ram_mb >= 2048) and load < max(1.0, cpu * 0.8))
    return {"cpu": cpu, "mem_available_mb": ram_mb, "load1": load, "mode": "parallel" if parallel else "sequential"}


def discover() -> list[dict[str, Any]]:
    return [adapter.metadata() for adapter in ADAPTERS.values()]


def select_agents(plan: dict[str, Any]) -> list[str]:
    kind = plan.get("kind") or ""
    if kind in {"authorized_engagement", "ssh_diagnostics"}:
        preferred = ["cai", "strix", "nebula", "pentestgpt", "hexstrike", "pentagi"]
    elif kind in {"package_operation", "systemd_mutation", "container_inspection", "container_logs"}:
        preferred = ["cai", "nebula"]
    else:
        preferred = []
    available = []
    for agent_id in preferred:
        health = ADAPTERS[agent_id].health_check()
        if health.get("healthy"):
            available.append(agent_id)
        if len(available) >= 3:
            break
    return available


def critic(plan: dict[str, Any], consultations: list[dict[str, Any]]) -> dict[str, Any]:
    healthy = [item for item in consultations if item.get("state") == "responded"]
    missing = [item for item in consultations if item.get("state") in {"unavailable", "requires_configuration"}]
    if not plan.get("commands"):
        verdict = "uncertain"
        summary = "No command was proposed; the critic will not invent an outcome."
    elif not healthy:
        verdict = "uncertain"
        summary = "No external agent produced evidence. VORTEX continues with the deterministic plan and Guardian only."
    else:
        verdict = "advisory_only"
        summary = "Agent output is untrusted recommendation data, not authorization."
    return {
        "verdict": verdict,
        "summary": summary,
        "disagreement": False,
        "confidence": 0.0 if not healthy else 0.2,
        "agents_consulted": len(consultations),
        "agents_useful": len(healthy),
        "agents_unavailable": len(missing),
        "evidence": "insufficient" if not healthy else "advisory",
    }


def consult(plan: dict[str, Any], task: dict[str, Any] | None = None) -> dict[str, Any]:
    budget = resource_budget()
    selected = select_agents(plan)
    consultations = []
    for agent_id in selected:
        result = ADAPTERS[agent_id].submit_task(task or {"id": plan.get("id"), "request": plan.get("request")})
        consultations.append(result)
        if budget["mode"] == "sequential":
            continue
    for agent_id in selected:
        ADAPTERS[agent_id].cleanup()
    review = critic(plan, consultations)
    return {
        "selected": selected,
        "budget": budget,
        "consultations": consultations,
        "critic": review,
        "note": "External agents never receive process control. Guardian remains independent.",
    }
