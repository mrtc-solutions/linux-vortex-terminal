"""Lightweight terminal dashboard.

Collects live host facts plus VORTEX state (AI, sessions, tools, VPN) into a
single panel without interfering with the existing terminal.  Everything that
cannot be observed on this host is reported as ``unavailable`` rather than
fabricated; specifically VORTEX does not claim a VPN/Secure Network tunnel when
no such subsystem is implemented.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


def _mem_mb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def _loadavg() -> list[float] | None:
    try:
        parts = Path("/proc/loadavg").read_text(encoding="utf-8", errors="replace").split()[:3]
        return [float(value) for value in parts]
    except (OSError, ValueError):
        return None


def _disk_percent(raw_path: str) -> int | None:
    try:
        usage = os.statvfs(Path(raw_path or "/"))
        total = usage.f_frsize * usage.f_blocks
        free = usage.f_frsize * usage.f_bavail
        return int(round(100 * (1 - (free / total)))) if total > 0 else None
    except OSError:
        return None


def _network_name() -> str | None:
    try:
        with open("/proc/sys/kernel/hostname", encoding="utf-8") as handle:
            return handle.read().strip() or None
    except OSError:
        return None


def _count_interfaces() -> int | None:
    """Count active IPv4/IPv6 interfaces from proc, avoiding a network tool probe."""
    try:
        with open("/proc/net/dev", encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()[2:]
            return sum(1 for line in lines if ":" in line and not line.startswith("lo"))
    except OSError:
        return None


def collect(store: Any, workspace: Any, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a live dashboard.  Missing subsystems report ``unavailable``."""
    try:
        from config import load_settings
        from models.router import model_status
        from tools.registry import inventory
        from vortex_backend import detect_context, probe_executable
    except ImportError:
        from backend.config import load_settings
        from backend.models.router import model_status
        from backend.tools.registry import inventory
        from backend.vortex_backend import detect_context, probe_executable

    settings = settings or {}
    doctor = detect_context()
    model = model_status(settings)
    local_ai = model.get("local") or {}
    tools = inventory()

    installed = sum(1 for item in tools if item.get("state") == "installed")
    unavailable = sum(1 for item in tools if item.get("state") in ("absent", "unavailable"))
    blocked = sum(1 for item in tools if item.get("state") == "blocked")

    sessions = store.list_sessions()
    running_sessions = [item for item in sessions if item.get("status") == "running"]
    findings = workspace.list_findings()
    engagements = [workspace.enrich_engagement(item) for item in store.list_engagements()]
    active_engagements = [item for item in engagements if item.get("effective_status") == "active"]

    ip = probe_executable("ip", include_version=False)
    ss = probe_executable("ss", include_version=False)
    network = {
        "interfaces": _count_interfaces() or 0,
        "ip_tool": ip.get("state"),
        "socket_tool": ss.get("state"),
        "hostname": _network_name(),
        "vpn": {
            "available": False,
            "state": "unavailable",
            "detail": "No reviewed VPN/Secure Network Mode is implemented in this build. VORTEX does not claim an active or secure tunnel.",
        },
    }

    storage = _disk_percent(doctor.get("cwd") or str(Path.home()))
    ai_state = local_ai.get("state") or "disabled"
    model_pool = model.get("pool") or model
    recommended = local_ai.get("recommended") or {}

    system = {
        "cpu": {"processors": os.cpu_count() or 0, "loadavg": _loadavg()},
        "memory": {"total_mb": _mem_mb()},
        "disk": {"used_percent": storage, "path": doctor.get("cwd")},
        "network": network,
    }
    ai = {
        "state": ai_state,
        "models_installed": len(local_ai.get("installed_candidates") or []),
        "endpoint": local_ai.get("endpoint"),
        "strategy": (local_ai.get("resources") or {}).get("recommended_strategy") or "sequential",
        "multi_model": bool(recommended.get("multi_model")),
        "message": local_ai.get("reason") or local_ai.get("message"),
    }
    return {
        "host": doctor,
        "system": system,
        "ai": ai,
        "session": {
            "total": len(sessions),
            "running": len(running_sessions),
            "sessions": [{"id": item.get("id"), "name": item.get("name"), "status": item.get("status"), "shell": item.get("shell"), "cwd": item.get("cwd")} for item in sessions[:20]],
        },
        "tools": {"installed": installed, "unavailable": unavailable, "blocked": blocked, "catalog": len(tools)},
        "engagements": {"active": len(active_engagements), "total": len(engagements)},
        "findings": {"total": len(findings)},
        "offline": settings.get("offline") is True,
        "privacy_mode": settings.get("privacy_mode") or "local",
        "vpn": network["vpn"],
    }
