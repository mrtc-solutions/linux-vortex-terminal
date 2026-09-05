"""Factual tool registry. Installed means probed on this host."""
from __future__ import annotations

from typing import Any

# SPDX identifiers for well-known builtin tools.  ``unknown`` is used honestly
# where the registry does not carry a verified license; VORTEX never bundles or
# relabels third-party code.
_BUILTIN_LICENSES: dict[str, str] = {
    "git": "GPL-2.0",
    "curl": "MIT",
    "nmap": "NPSL",
    "nuclei": "MIT",
    "ffuf": "MIT",
    "nikto": "GPL-2.0",
    "gobuster": "Apache-2.0",
    "amass": "Apache-2.0",
    "sqlmap": "GPL-2.0",
    "msfconsole": "BSD-3-Clause",
    "docker": "Apache-2.0",
    "podman": "Apache-2.0",
    "nslookup": "MPL-2.0",
    "dig": "MPL-2.0",
    "whois": "GPL-2.0",
    "ssh": "BSD-3-Clause",
    "systemctl": "LGPL-2.1",
    "journalctl": "LGPL-2.1",
}

# Where a tool is addressed, how it is typically installed on a Debian-family
# host.  This is guidance for the operator, not an automatic installer.
_INSTALL_METHODS: dict[str, str] = {
    "git": "apt",
    "curl": "apt",
    "nmap": "apt",
    "nuclei": "release-tarball",
    "ffuf": "release-binary",
    "nikto": "apt",
    "gobuster": "release-binary",
    "amass": "release-binary",
    "sqlmap": "apt",
    "msfconsole": "apt",
    "docker": "apt",
    "podman": "apt",
    "nslookup": "apt",
    "dig": "apt",
    "whois": "apt",
    "ssh": "apt",
    "systemctl": "apt",
    "journalctl": "apt",
}

CATEGORIES = {
    "system": ("uname", "uptime", "free", "ps", "whoami", "id", "hostname", "pwd", "date", "cat", "lscpu", "lsblk", "lsusb", "who", "last", "vmstat"),
    "filesystem": ("df", "du", "ls", "tail", "findmnt"),
    "network": ("ss", "ip", "tshark", "tcpdump", "nft", "iptables", "nmcli", "iw", "nslookup", "dig", "whois"),
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
        probe = probe_executable(name, include_version=False)
        extra = adapter_risk.get(name, {})
        license_name = _BUILTIN_LICENSES.get(name) or _classify_license(name)
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
            "source": "builtin-catalog",
            "license": license_name,
            "installation_method": _INSTALL_METHODS.get(name, "system-or-distro"),
            "dependencies": meta.get("dependencies") or [],
        })
    return items


def _classify_license(name: str) -> str:
    """Best-effort license for a known tool without making a host probe."""
    try:
        from backend.tools.hostscan import KALI_CATALOG
    except ImportError:
        try:
            from tools.hostscan import KALI_CATALOG
        except ImportError:
            return "unknown"
    return (KALI_CATALOG.get(name) or {}).get("license") or "unknown"


def by_category(items: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Group a supplied inventory, avoiding a second full host probe when available."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items if items is not None else inventory():
        grouped.setdefault(str(item["category"]), []).append(item)
    return grouped
