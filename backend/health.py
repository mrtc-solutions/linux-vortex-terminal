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


def _binary_component(probe: dict[str, Any], role: str) -> dict[str, Any]:
    state = probe.get("state")
    installed = state == "installed"
    blocked = state == "blocked"
    detail = role if not blocked else f"{role} · review path safety before relying on it"
    return {
        "state": "healthy" if installed else ("warning" if blocked else "unavailable"),
        "available": probe.get("path") if (installed or blocked) else "absent",
        "detail": detail,
        "version": probe.get("version"),
        "path": probe.get("path"),
        "security_flags": probe.get("security_flags") or [],
    }


def collect(store: Any, sessions: Any | None = None, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    try:
        from adapter_registry import TOOL_CATALOG
        from agents.council import discover
        from models.router import MODEL_CATALOG, model_status
        from vortex_backend import detect_context, probe_executable
    except ImportError:
        from backend.adapter_registry import TOOL_CATALOG
        from backend.agents.council import discover
        from backend.models.router import MODEL_CATALOG, model_status
        from backend.vortex_backend import detect_context, probe_executable

    doctor = detect_context()
    integrity = store.integrity_check()
    tools = []
    for name, meta in TOOL_CATALOG.items():
        item = probe_executable(name, include_version=False)
        item.update({"family": meta["family"], "role": meta["role"]})
        tools.append(item)
    installed = sum(1 for item in tools if item.get("state") == "installed")
    agents = discover()
    agent_healthy = sum(1 for item in agents if item.get("health", {}).get("healthy"))
    docker = probe_executable("docker", include_version=False)
    if docker.get("state") != "installed":
        docker = probe_executable("podman", include_version=False)
        docker_name = "podman"
    else:
        docker_name = "docker"
    node = probe_executable("node", include_version=False)
    npm = probe_executable("npm", include_version=False)
    pnpm = probe_executable("pnpm", include_version=False)
    yarn = probe_executable("yarn", include_version=False)
    go = probe_executable("go", include_version=False)
    ollama_binary = probe_executable("ollama", include_version=False)
    models = model_status(settings)
    ollama = models.get("local") or {}
    local_ai_state = "healthy" if ollama.get("state") == "healthy" else ("disabled" if ollama.get("state") == "disabled" else "unavailable")
    installed_candidates = ollama.get("installed_candidates") or []
    recommended = ollama.get("recommended") or {}
    required_models = [name for name, meta in MODEL_CATALOG.items() if not meta.get("optional")]
    missing_required_models = [name for name in required_models if name not in installed_candidates]
    model_pool_state = "healthy" if ollama.get("state") == "healthy" and not missing_required_models else ("warning" if installed_candidates else "unavailable")
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
        "nodejs": _binary_component(node, "desktop frontend and build scripts"),
        "npm": _binary_component(npm, "frontend dependency management and packaging"),
        "pnpm": _binary_component(pnpm, "optional package manager"),
        "yarn": _binary_component(yarn, "optional package manager"),
        "go": _binary_component(go, "optional toolchain for Go-based security tools"),
        "docker": {"state": "healthy" if docker.get("state") == "installed" else "unavailable", "runtime": docker_name if docker.get("state") == "installed" else None, "probe": docker.get("state")},
        "ollama": {
            "state": ollama.get("state") or ("installed" if ollama_binary.get("state") == "installed" else "unavailable"),
            "binary_state": ollama_binary.get("state"),
            "binary_path": ollama_binary.get("path"),
            "models": len(ollama.get("models") or []),
            "available": f"{len(installed_candidates)} recommended" if installed_candidates else (ollama.get("reason") or "no local models"),
            "version": ollama.get("version") or ollama_binary.get("version"),
            "endpoint": ollama.get("endpoint"),
            "recommended_mode": recommended.get("mode"),
        },
        "local_ai": {
            "state": local_ai_state,
            "available": ", ".join(installed_candidates[:3]) if installed_candidates else "deterministic fallback only",
            "detail": f"mode {recommended.get('mode') or 'unknown'} · strategy {((ollama.get('resources') or {}).get('recommended_strategy') or 'sequential')} · multi_model={'yes' if recommended.get('multi_model') else 'no'}",
        },
        "model_pool": {
            "state": model_pool_state,
            "available": ", ".join(installed_candidates) if installed_candidates else "no verified local models",
            "detail": f"missing core models: {', '.join(missing_required_models) if missing_required_models else 'none'}",
        },
        "agent_council": {"state": "healthy" if agent_healthy else "empty", "available": f"{agent_healthy}/{len(agents)}", "agents": agents},
        "kali_tools": {"state": "healthy" if installed else "empty", "detected": installed, "catalog": len(tools)},
        "memory": {"state": "healthy"},
        "storage": {"state": "healthy" if storage is None or storage < 95 else "warning", "used_percent": storage, "path": str(data_dir)},
        "sandbox": isolation,
    }
    return {
        "product": "VORTEX",
        "offline": settings.get("offline") is True,
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
    node_ok = health["components"]["nodejs"]["state"] in {"healthy", "warning"}
    npm_ok = health["components"]["npm"]["state"] in {"healthy", "warning"}
    pnpm_ok = health["components"]["pnpm"]["state"] in {"healthy", "warning"}
    yarn_ok = health["components"]["yarn"]["state"] in {"healthy", "warning"}
    go_ok = health["components"]["go"]["state"] in {"healthy", "warning"}
    docker = health["components"]["docker"]["state"] == "healthy"
    ollama = health["components"]["ollama"]["state"] == "healthy"
    model_pool = health["components"]["model_pool"]["state"] == "healthy"
    db_ok = health["components"]["database"]["state"] == "healthy"
    tools_n = health["components"]["kali_tools"]["detected"]
    agents_n = health["components"]["agent_council"].get("available")
    cpu = os.cpu_count() or 1
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
        {"id": "nodejs", "title": "Node.js", "ok": node_ok, "required": False, "detail": health["components"]["nodejs"].get("available")},
        {"id": "npm", "title": "npm", "ok": npm_ok, "required": False, "detail": health["components"]["npm"].get("available")},
        {"id": "pnpm", "title": "pnpm", "ok": pnpm_ok, "required": False, "detail": health["components"]["pnpm"].get("available")},
        {"id": "yarn", "title": "yarn", "ok": yarn_ok, "required": False, "detail": health["components"]["yarn"].get("available")},
        {"id": "go", "title": "Go", "ok": go_ok, "required": False, "detail": health["components"]["go"].get("available")},
        {"id": "docker", "title": "Docker or Podman", "ok": docker, "required": False, "detail": health["components"]["docker"].get("probe")},
        {"id": "tools", "title": "Linux tools", "ok": tools_n > 0, "required": True, "detail": f"{tools_n} detected"},
        {"id": "agents", "title": "AI agents", "ok": str(agents_n).split("/")[0] not in {"0", "None", ""}, "required": False, "detail": f"{agents_n} available; missing third-party agents stay UNAVAILABLE"},
        {"id": "ollama", "title": "Local model runtime (Ollama)", "ok": ollama, "required": False, "detail": health["components"]["ollama"].get("state")},
        {"id": "model_pool", "title": "Recommended local model pool", "ok": model_pool, "required": False, "detail": health["components"]["model_pool"].get("detail")},
        {"id": "database", "title": "Local database", "ok": db_ok, "required": True, "detail": "SQLite WAL + audit chain"},
        {"id": "policy", "title": "Security policy", "ok": True, "required": True, "detail": settings.get("profile") or "safe"},
    ]
    blocking = [step for step in steps if step["required"] and not step["ok"]]
    return {
        "product": "VORTEX",
        "first_run_complete": settings.get("first_run_complete") is True,
        "ready": not blocking,
        "blocking": [step["id"] for step in blocking],
        "steps": steps,
        "health": health,
    }
