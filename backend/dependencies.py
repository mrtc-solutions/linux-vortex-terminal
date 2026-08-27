"""Live missing-dependency inventory and operator-controlled install proposals.

VORTEX never silently installs software and never captures a sudo password.
Debian/Kali packages can become a reviewed apt plan. Third-party agents stay
proposal-only until the operator installs them outside VORTEX.
"""
from __future__ import annotations

from typing import Any

# Distro package names for tools VORTEX can actually plan through linux.packages.apt.
APT_PACKAGES: dict[str, str] = {
    "nmap": "nmap",
    "curl": "curl",
    "ping": "iputils-ping",
    "git": "git",
    "docker": "docker.io",
    "podman": "podman",
    "nikto": "nikto",
    "gobuster": "gobuster",
    "sqlmap": "sqlmap",
    "john": "john",
    "hashcat": "hashcat",
    "tshark": "tshark",
    "tcpdump": "tcpdump",
    "gcc": "gcc",
    "python3": "python3",
    "ssh": "openssh-client",
    "ffuf": "ffuf",
    "amass": "amass",
    "msfconsole": "metasploit-framework",
    "nuclei": "nuclei",
    "lscpu": "util-linux",
    "systemctl": "systemd",
    "journalctl": "systemd",
    "ss": "iproute2",
    "ip": "iproute2",
    "df": "coreutils",
    "du": "coreutils",
    "ls": "coreutils",
    "cat": "coreutils",
    "date": "coreutils",
    "whoami": "coreutils",
    "id": "coreutils",
    "pwd": "coreutils",
    "uname": "coreutils",
    "hostname": "hostname",
    "ps": "procps",
    "free": "procps",
    "uptime": "procps",
}

CORE_TOOLS = ("curl", "git", "python3", "ss", "ip", "df", "ps", "whoami")


def _probe_name(name: str) -> dict[str, Any]:
    try:
        from vortex_backend import probe_executable
    except ImportError:
        from backend.vortex_backend import probe_executable
    return probe_executable(name, include_version=False)


def _agent_proposal(agent_id: str) -> dict[str, Any]:
    try:
        from agents.install import proposal
    except ImportError:
        from backend.agents.install import proposal
    return proposal(agent_id)


def inventory() -> dict[str, Any]:
    try:
        from adapter_registry import TOOL_CATALOG
        from agents.council import discover
        from models.router import model_status
        from sandbox import isolation_status
    except ImportError:
        from backend.adapter_registry import TOOL_CATALOG
        from backend.agents.council import discover
        from backend.models.router import model_status
        from backend.sandbox import isolation_status

    items: list[dict[str, Any]] = []
    for name, meta in TOOL_CATALOG.items():
        probe = _probe_name(name)
        installed = probe.get("state") == "installed"
        apt = APT_PACKAGES.get(name)
        items.append({
            "id": f"tool:{name}",
            "kind": "tool",
            "name": name,
            "title": name,
            "role": meta.get("role"),
            "family": meta.get("family"),
            "state": probe.get("state"),
            "installed": installed,
            "required": name in CORE_TOOLS,
            "method": "apt" if apt else "operator-manual",
            "apt_package": apt,
            "path": probe.get("path"),
            "version": probe.get("version"),
        })

    for agent in discover():
        healthy = bool(agent.get("health", {}).get("healthy"))
        items.append({
            "id": f"agent:{agent['id']}",
            "kind": "agent",
            "name": agent["id"],
            "title": agent.get("name") or agent["id"],
            "role": "advisory-only",
            "family": "agent-council",
            "state": agent.get("status") or "missing",
            "installed": healthy,
            "required": False,
            "method": "operator-manual",
            "apt_package": None,
            "path": (agent.get("health") or {}).get("path"),
            "version": agent.get("version"),
            "source": agent.get("source"),
            "license": (agent.get("configuration") or {}).get("license"),
        })

    docker = isolation_status()
    items.append({
        "id": "runtime:docker",
        "kind": "runtime",
        "name": "docker-or-podman",
        "title": "Docker or Podman",
        "role": "optional isolation probe",
        "family": "containers",
        "state": docker.get("state"),
        "installed": bool(docker.get("available")),
        "required": False,
        "method": "apt",
        "apt_package": "docker.io",
        "path": docker.get("path"),
        "version": docker.get("version"),
    })

    ollama = (model_status({}) or {}).get("local") or {}
    items.append({
        "id": "runtime:ollama",
        "kind": "runtime",
        "name": "ollama",
        "title": "Ollama (loopback)",
        "role": "optional local model probe",
        "family": "models",
        "state": ollama.get("state") or "unavailable",
        "installed": ollama.get("state") == "healthy",
        "required": False,
        "method": "operator-manual",
        "apt_package": None,
        "path": ollama.get("endpoint"),
        "version": None,
        "source": "https://ollama.com (operator-installed; loopback only)",
    })

    missing = [item for item in items if not item["installed"]]
    return {
        "product": "VORTEX",
        "auto_install": False,
        "sudo": False,
        "note": "VORTEX never silently installs software and never captures a sudo password.",
        "counts": {
            "total": len(items),
            "installed": sum(1 for item in items if item["installed"]),
            "missing": len(missing),
            "required_missing": sum(1 for item in missing if item["required"]),
        },
        "items": items,
        "missing": missing,
    }


def proposal_for(item_id: str) -> dict[str, Any]:
    data = inventory()
    item = next((row for row in data["items"] if row["id"] == item_id or row["name"] == item_id), None)
    if not item:
        return {"id": item_id, "state": "unknown", "auto_install": False, "message": "Unknown dependency."}
    if item["installed"]:
        return {**item, "auto_install": False, "message": "Already present on this host. No install is required."}
    if item["kind"] == "agent":
        extra = _agent_proposal(item["name"])
        return {
            **item,
            **extra,
            "id": item["id"],
            "auto_install": False,
            "message": extra.get("message") or "Install this agent yourself after reviewing source and license.",
        }
    if item.get("method") == "apt" and item.get("apt_package"):
        pkg = item["apt_package"]
        return {
            **item,
            "auto_install": False,
            "requires_root": True,
            "source": "Debian/Kali apt",
            "license": "distro package",
            "permissions": ["root-required", "apt-network", "no-password-capture"],
            "commands": [
                f"sudo apt-get update",
                f"sudo apt-get install --assume-yes --no-remove {pkg}",
            ],
            "plan_request": f"install package {pkg}",
            "message": (
                f"{item['title']} can be installed with the reviewed apt adapter. "
                "VORTEX will build a typed plan. Root is required; no sudo password is captured. "
                "Approve the plan only on a host you administer."
            ),
        }
    return {
        **item,
        "auto_install": False,
        "commands": [
            f"# Review upstream documentation for {item['title']}.",
            "# VORTEX will not download or execute an unreviewed installer.",
        ],
        "message": "No reviewed apt package is mapped. Install remains operator-controlled.",
    }
