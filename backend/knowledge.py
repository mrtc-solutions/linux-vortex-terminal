"""Local, deterministic capability retrieval.

This is intentionally not an external RAG system. It returns bounded, reviewed
examples from the adapter catalog so an unclear request can be answered with
something useful before execution. It never calls a network endpoint and never
executes anything.
"""
from __future__ import annotations

from typing import Any

try:
    from .adapter_registry import ADAPTER_MANIFESTS
except ImportError:  # direct `python backend/vortex_backend.py` puts backend/ on PATH
    from adapter_registry import ADAPTER_MANIFESTS

CATEGORIES: list[dict[str, Any]] = [
    {
        "id": "identity",
        "label": "Identity & host",
        "keywords": ("user", "username", "whoami", "hostname", "host", "machine", "machine name"),
        "examples": ("what user am i", "what host is this"),
        "adapters": ("linux.system.identity",),
        "limit": "read-only",
    },
    {
        "id": "clock",
        "label": "Clock & system time",
        "keywords": ("time", "date", "clock", "current date"),
        "examples": ("what time is it", "show the current date and time"),
        "adapters": ("linux.system.clock",),
        "limit": "read-only",
    },
    {
        "id": "filesystem",
        "label": "Files, directories & logs",
        "keywords": ("file", "files", "directory", "folder", "path", "log", "logs", "journal", "os-release", "os release"),
        "examples": ("list files in /var/log", "show /etc/os-release", "show system logs"),
        "adapters": ("linux.filesystem.list", "linux.filesystem.read", "linux.systemd.journal", "linux.filesystem.log"),
        "limit": "read-only",
    },
    {
        "id": "processes",
        "label": "Processes & login sessions",
        "keywords": ("process", "processes", "pid", "login", "logged in", "session"),
        "examples": ("show processes", "show process tree", "who is logged in"),
        "adapters": ("linux.system.processes", "linux.system.login"),
        "limit": "read-only",
    },
    {
        "id": "network",
        "label": "Network, interfaces, sockets & routes",
        "keywords": ("network", "socket", "sockets", "listening", "port", "interface", "ip address", "route"),
        "examples": ("show listening ports", "show ip address", "show route table"),
        "adapters": ("linux.network.sockets", "linux.network.interfaces", "linux.network.routes", "linux.network.facts"),
        "limit": "read-only / no-network",
    },
    {
        "id": "systemd",
        "label": "Services & systemd",
        "keywords": ("service", "services", "unit", "systemd", "nginx", "running services"),
        "examples": ("show running services", "check if nginx is running", "show systemd logs"),
        "adapters": ("linux.systemd.inspect", "linux.systemd.journal"),
        "limit": "read-only",
    },
    {
        "id": "health",
        "label": "Health, memory, CPU, disk & storage",
        "keywords": ("health", "memory", "ram", "swap", "cpu", "load", "disk", "storage", "space", "uptime", "system"),
        "examples": ("show system health", "show disk usage", "show memory", "show uptime"),
        "adapters": ("linux.system.health", "linux.filesystem.usage"),
        "limit": "read-only",
    },
    {
        "id": "packages",
        "label": "Installed packages",
        "keywords": ("package", "packages", "installed", "apt", "dpkg"),
        "examples": ("list installed packages",),
        "adapters": ("linux.system.packages",),
        "limit": "read-only",
    },
    {
        "id": "git",
        "label": "Git repository facts",
        "keywords": ("git", "commit", "branch", "remotes", "diff", "repository"),
        "examples": ("git status", "show git remotes", "show recent commits"),
        "adapters": ("linux.development.git-status", "linux.development.git-log", "linux.development.git-branches"),
        "limit": "read-only",
    },
    {
        "id": "containers",
        "label": "Container inspection",
        "keywords": ("container", "containers", "docker", "podman"),
        "examples": ("docker ps", "inspect docker containers"),
        "adapters": ("linux.containers.inspect", "linux.containers.logs"),
        "limit": "read-only",
    },
]

CATEGORY_BY_ID = {item["id"]: item for item in CATEGORIES}


def _adapter_known(adapter_id: str) -> bool:
    return adapter_id in ADAPTER_MANIFESTS


def retrieve(request: str | None = None, *, limit: int = 6) -> list[dict[str, Any]]:
    """Return bounded local capability entries that match the request keywords.

    Every result is read-only guidance. No command is created here; callers keep
    the deterministic plan/Guardian path authoritative.
    """
    lower = (request or "").lower()
    matched = []
    for item in CATEGORIES:
        matched_keywords = [kw for kw in item["keywords"] if kw in lower]
        if not matched_keywords:
            continue
        known_adapters = [adapter_id for adapter_id in item["adapters"] if _adapter_known(adapter_id)]
        if not known_adapters:
            continue
        matched.append({
            "id": item["id"],
            "label": item["label"],
            "match": matched_keywords[:3],
            "examples": list(item["examples"])[:3],
            "adapters": known_adapters,
            "limit": item["limit"],
        })
    if not matched:
        matched = [
            {"id": item["id"], "label": item["label"], "match": [], "examples": list(item["examples"])[:3], "adapters": [a for a in item["adapters"] if _adapter_known(a)], "limit": item["limit"]}
            for item in CATEGORIES
            if any(_adapter_known(adapter_id) for adapter_id in item["adapters"])
        ][:limit]
    return matched[:limit]
