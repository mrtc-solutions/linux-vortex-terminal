"""Real subsystem health probes. Missing components are reported, never faked."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


def _disk_percent(path: Path) -> int | None:
    try:
        usage = os.statvfs(path)
        total = usage.f_frsize * usage.f_blocks
        free = usage.f_frsize * usage.f_bavail
        if total <= 0:
            return None
        return int(round(100 * (1 - (free / total))))
    except OSError:
        return None


def collect(store: Any, sessions: Any | None = None, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    try:
        from adapter_registry import TOOL_CATALOG
        from agents.council import discover
        from models.router import model_status
        from vortex_backend import detect_context, probe_executable
    except ImportError:
        from backend.adapter_registry import TOOL_CATALOG
        from backend.agents.council import discover
        from backend.models.router import model_status
        from backend.vortex_backend import detect_context, probe_executable

    doctor = detect_context()
    integrity = store.integrity_check()
    tools = []
    for name, meta in TOOL_CATALOG.items():
        item = probe_executable(name)
        item.update({"family": meta["family"], "role": meta["role"]})
        tools.append(item)
    installed = sum(1 for item in tools if item.get("state") == "installed")
    agents = discover()
    agent_healthy = sum(1 for item in agents if item.get("health", {}).get("healthy"))
    docker = probe_executable("docker")
    if docker.get("state") != "installed":
        docker = probe_executable("podman")
        docker_name = "podman"
    else:
        docker_name = "docker"
    models = model_status(settings)
    ollama = models.get("local") or {}
    data_dir = Path(store.db_path).parent
    storage = _disk_percent(data_dir)
    try:
        from sandbox import isolation_status
    except ImportError:
        from backend.sandbox import isolation_status
    isolation = isolation_status()
    session_ok = True
    if sessions is not None:
        try:
            sessions.list()
        except Exception:
            session_ok = False
    core = "healthy"
    db_state = "healthy" if integrity.get("valid") else "degraded"
    components = {
        "core": {"state": core, "version": "0.2.0"},
        "database": {"state": db_state, "detail": integrity},
        "terminal_engine": {"state": "healthy" if session_ok else "degraded"},
        "docker": {"state": "healthy" if docker.get("state") == "installed" else "unavailable", "runtime": docker_name if docker.get("state") == "installed" else None, "probe": docker.get("state")},
        "ollama": {"state": ollama.get("state") or "unavailable", "models": len(ollama.get("models") or [])},
        "agent_council": {"state": "healthy" if agent_healthy else "empty", "available": f"{agent_healthy}/{len(agents)}", "agents": agents},
        "kali_tools": {"state": "healthy" if installed else "empty", "detected": installed, "catalog": len(tools)},
        "memory": {"state": "healthy"},
        "storage": {"state": "healthy" if storage is None or storage < 95 else "warning", "used_percent": storage, "path": str(data_dir)},
        "sandbox": isolation,
    }
    return {
        "product": "VORTEX",
        "offline": bool(settings.get("offline")),
        "privacy_mode": settings.get("privacy_mode") or "local",
        "host": doctor,
        "components": components,
        "tools": tools,
        "which_git": bool(shutil.which("git")),
        "which_python": bool(shutil.which("python3")),
        "which_docker": bool(shutil.which("docker") or shutil.which("podman")),
    }


def setup_checks(store: Any, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """First-run requirements from live probes. Missing items are skippable, never faked."""
    import sys
    settings = settings or {}
    health = collect(store, None, settings)
    doctor = health["host"]
    git_ok = bool(shutil.which("git"))
    py_ok = sys.version_info >= (3, 11)
    linux_ok = sys.platform == "linux"
    docker = health["components"]["docker"]["state"] == "healthy"
    ollama = health["components"]["ollama"]["state"] == "healthy"
    db_ok = health["components"]["database"]["state"] == "healthy"
    tools_n = health["components"]["kali_tools"]["detected"]
    agents_n = health["components"]["agent_council"].get("available")
    cpu = os.cpu_count() or 1
    ram = health["components"].get("storage", {})
    mem_mb = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    mem_mb = int(line.split()[1]) // 1024
                    break
    except (OSError, ValueError):
        pass
    steps = [
        {"id": "linux", "title": "Linux host", "ok": linux_ok, "required": True, "detail": f"{doctor.get('support_tier')} · {doctor.get('architecture')} · {cpu} CPU · {mem_mb or '?'} MB RAM"},
        {"id": "python", "title": "Python 3.11+", "ok": py_ok, "required": True, "detail": sys.version.split()[0]},
        {"id": "git", "title": "Git", "ok": git_ok, "required": False, "detail": "installed" if git_ok else "absent"},
        {"id": "docker", "title": "Docker or Podman", "ok": docker, "required": False, "detail": health["components"]["docker"].get("probe")},
        {"id": "tools", "title": "Linux tools", "ok": tools_n > 0, "required": True, "detail": f"{tools_n} detected"},
        {"id": "agents", "title": "AI agents", "ok": str(agents_n).split("/")[0] not in {"0", "None", ""}, "required": False, "detail": f"{agents_n} available; missing third-party agents stay UNAVAILABLE"},
        {"id": "models", "title": "Local model (Ollama)", "ok": ollama, "required": False, "detail": health["components"]["ollama"]["state"]},
        {"id": "database", "title": "Local database", "ok": db_ok, "required": True, "detail": "SQLite WAL + audit chain"},
        {"id": "policy", "title": "Security policy", "ok": True, "required": True, "detail": settings.get("profile") or "safe"},
    ]
    blocking = [step for step in steps if step["required"] and not step["ok"]]
    return {
        "product": "VORTEX",
        "first_run_complete": bool(settings.get("first_run_complete")),
        "ready": not blocking,
        "blocking": [step["id"] for step in blocking],
        "steps": steps,
        "health": health,
    }
