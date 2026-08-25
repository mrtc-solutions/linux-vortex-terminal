"""Isolation capability probe. No container is started unless Docker is installed and the operator requests a reviewed sandbox plan."""
from __future__ import annotations

from typing import Any


def isolation_status() -> dict[str, Any]:
    try:
        from vortex_backend import probe_executable
    except ImportError:
        from backend.vortex_backend import probe_executable
    docker = probe_executable("docker")
    podman = probe_executable("podman")
    runtime = docker if docker.get("state") == "installed" else podman if podman.get("state") == "installed" else None
    if not runtime:
        return {
            "available": False,
            "runtime": None,
            "state": "unavailable",
            "message": "Neither Docker nor Podman is installed. Isolated execution is UNAVAILABLE; host PTY/process execution remains the authority.",
        }
    return {
        "available": True,
        "runtime": runtime.get("name"),
        "state": "installed",
        "version": runtime.get("version"),
        "path": runtime.get("path"),
        "message": "A container runtime is installed. VORTEX does not start unreviewed images or grant host privileges to sandboxes.",
    }
