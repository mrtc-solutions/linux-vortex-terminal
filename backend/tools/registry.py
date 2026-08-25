"""Factual tool registry. Installed means probed on this host."""
from __future__ import annotations

from typing import Any

CATEGORIES = {
    "system": ("uname", "uptime", "free", "ps", "whoami", "id", "hostname", "pwd", "date"),
    "filesystem": ("df", "du", "ls"),
    "network": ("ss", "ip", "tshark", "tcpdump"),
    "web": ("curl", "nmap", "nuclei", "ffuf", "nikto", "gobuster", "sqlmap", "amass"),
    "analysis": ("john", "hashcat"),
    "development": ("git", "python3", "gcc"),
    "containers": ("docker", "podman"),
    "packages": ("apt-get", "apt-cache", "dpkg-query", "dpkg", "apt-mark"),
    "systemd": ("systemctl", "journalctl"),
    "ssh": ("ssh",),
    "authorized-assessment": ("msfconsole",),
}


def inventory() -> list[dict[str, Any]]:
    try:
        from adapter_registry import ADAPTER_MANIFESTS, TOOL_CATALOG
        from vortex_backend import probe_executable
    except ImportError:
        from backend.adapter_registry import ADAPTER_MANIFESTS, TOOL_CATALOG
        from backend.vortex_backend import probe_executable
    items = []
    reverse_cat = {name: category for category, names in CATEGORIES.items() for name in names}
    adapter_risk = {}
    for manifest in ADAPTER_MANIFESTS.values():
        for tool in str(manifest.get("tool") or "").split("+"):
            if tool and tool != "multiple":
                adapter_risk[tool] = {"risk": manifest.get("risk"), "network": manifest.get("network_class"), "adapter": manifest.get("operation")}
    for name, meta in TOOL_CATALOG.items():
        probe = probe_executable(name)
        extra = adapter_risk.get(name, {})
        items.append({
            "name": name,
            "binary": probe.get("path"),
            "version": probe.get("version"),
            "category": reverse_cat.get(name) or meta.get("family"),
            "capabilities": [meta.get("role")],
            "state": probe.get("state"),
            "risk_level": extra.get("risk") or ("high" if meta.get("family", "").startswith("authorized") else "low"),
            "requires_network": extra.get("network") not in (None, "no-network", "loopback-only"),
            "requires_root": False,
            "output_type": "text",
            "sha256": probe.get("sha256"),
        })
    return items


def by_category() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in inventory():
        grouped.setdefault(str(item["category"]), []).append(item)
    return grouped
