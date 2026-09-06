"""Isolation capability probe. No container is started unless Docker is installed and the operator requests a reviewed sandbox plan."""
from __future__ import annotations

from typing import Any


def isolation_status() -> dict[str, Any]:
    try:
        from vortex_backend import probe_executable
    except ImportError:
        from backend.vortex_backend import probe_executable
    docker = probe_executable("docker", include_version=False)
    podman = probe_executable("podman", include_version=False)
    runtime = docker if docker.get("state") == "installed" else podman if podman.get("state") == "installed" else None
    if not runtime:
        # A runtime found in an untrusted PATH directory is present-but-blocked.
        # Reporting that as "not installed" would send the operator to reinstall
        # software that is already there, so the two states stay distinct.
        blocked = [probe for probe in (docker, podman) if probe.get("state") == "blocked"]
        if blocked:
            detail = "; ".join(f"{probe.get('name')} at {probe.get('path')} ({', '.join(probe.get('security_flags') or []) or 'unsafe location'})" for probe in blocked)
            return {
                "available": False,
                "runtime": None,
                "state": "blocked",
                "path": blocked[0].get("path"),
                "message": (
                    "A container runtime is installed but sits in a user-writable PATH directory, so VORTEX "
                    f"will not execute it: {detail}. Move it to a root-owned directory such as /usr/bin, or fix "
                    "the directory permissions. Isolated execution is UNAVAILABLE; host PTY/process execution remains the authority."
                ),
            }
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
