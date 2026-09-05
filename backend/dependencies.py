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
    "wordlists": "seclists",
    "node": "nodejs",
    "npm": "npm",
    "pnpm": "pnpm",
    "yarn": "yarnpkg",
    "go": "golang-go",
}

CORE_TOOLS = ("curl", "git", "python3", "ss", "ip", "df", "ps", "whoami")
EXTRA_RUNTIME_DEPENDENCIES: tuple[dict[str, Any], ...] = (
    {
        "id": "runtime:nodejs",
        "kind": "runtime",
        "name": "node",
        "title": "Node.js",
        "role": "desktop frontend and build scripts",
        "family": "development",
        "required": False,
        "method": "apt",
    },
    {
        "id": "runtime:npm",
        "kind": "runtime",
        "name": "npm",
        "title": "npm",
        "role": "frontend dependency management and packaging",
        "family": "development",
        "required": False,
        "method": "apt",
    },
    {
        "id": "runtime:pnpm",
        "kind": "runtime",
        "name": "pnpm",
        "title": "pnpm",
        "role": "optional package manager",
        "family": "development",
        "required": False,
        "method": "apt",
    },
    {
        "id": "runtime:yarn",
        "kind": "runtime",
        "name": "yarn",
        "title": "yarn",
        "role": "optional package manager",
        "family": "development",
        "required": False,
        "method": "apt",
    },
    {
        "id": "runtime:go",
        "kind": "runtime",
        "name": "go",
        "title": "Go",
        "role": "optional toolchain for Go-based security tools",
        "family": "development",
        "required": False,
        "method": "apt",
    },
)
OLLAMA_SOURCE = "https://ollama.com/download"


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


def _extra_runtime_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for meta in EXTRA_RUNTIME_DEPENDENCIES:
        probe = _probe_name(str(meta["name"]))
        installed = probe.get("state") in {"installed", "blocked"}
        items.append({
            "id": meta["id"],
            "kind": meta["kind"],
            "name": meta["name"],
            "title": meta["title"],
            "role": meta["role"],
            "family": meta["family"],
            "state": probe.get("state"),
            "installed": installed,
            "required": bool(meta.get("required")),
            "method": meta.get("method") or "operator-manual",
            "apt_package": APT_PACKAGES.get(str(meta["name"])),
            "path": probe.get("path"),
            "version": probe.get("version"),
            "security_flags": probe.get("security_flags") or [],
        })
    return items


def _load_runtime_settings() -> dict[str, Any]:
    try:
        from config import load_settings
    except ImportError:
        from backend.config import load_settings
    return load_settings()


def _ollama_items() -> list[dict[str, Any]]:
    try:
        from models.router import MODEL_CATALOG, model_status
    except ImportError:
        from backend.models.router import MODEL_CATALOG, model_status

    ollama_probe = _probe_name("ollama")
    binary_installed = ollama_probe.get("state") == "installed"
    model = model_status(_load_runtime_settings()) or {}
    local = model.get("local") or {}
    endpoint = local.get("endpoint") or "http://127.0.0.1:11434"
    api_state = local.get("state") or ("installed" if binary_installed else "absent")
    installed_candidates = set(local.get("installed_candidates") or [])
    catalog = [
        {
            "name": name,
            "optional": bool(meta.get("optional")),
            "label": meta.get("label") or name,
            "roles": list(meta.get("roles") or []),
            "installed": name in installed_candidates,
        }
        for name, meta in MODEL_CATALOG.items()
    ]
    missing_required = [item["name"] for item in catalog if not item["optional"] and not item["installed"]]
    missing_optional = [item["name"] for item in catalog if item["optional"] and not item["installed"]]
    present = sorted(installed_candidates)

    runtime_state = "healthy" if api_state == "healthy" else ("installed" if binary_installed else api_state)
    runtime_detail = local.get("message") or local.get("reason") or "Loopback runtime unavailable."
    if binary_installed and api_state != "healthy":
        runtime_detail = "Ollama CLI is installed, but the loopback API is not healthy yet."

    models_installed = api_state == "healthy" and not missing_required
    model_pool_state = "installed" if models_installed else ("partial" if present else ("unavailable" if binary_installed else "absent"))
    model_detail = (
        f"Installed: {', '.join(present) if present else 'none'} · "
        f"Missing core: {', '.join(missing_required) if missing_required else 'none'} · "
        f"Missing optional: {', '.join(missing_optional) if missing_optional else 'none'}"
    )

    return [
        {
            "id": "runtime:ollama",
            "kind": "runtime",
            "name": "ollama",
            "title": "Ollama (loopback)",
            "role": "local model runtime",
            "family": "models",
            "state": runtime_state,
            "installed": api_state == "healthy",
            "required": False,
            "method": "operator-manual",
            "apt_package": None,
            "path": ollama_probe.get("path"),
            "version": ollama_probe.get("version"),
            "endpoint": endpoint,
            "api_state": api_state,
            "binary_state": ollama_probe.get("state"),
            "binary_installed": binary_installed,
            "installed_candidates": present,
            "missing_candidates": missing_required + missing_optional,
            "missing_required_candidates": missing_required,
            "missing_optional_candidates": missing_optional,
            "source": f"{OLLAMA_SOURCE} (operator-installed; loopback only)",
            "detail": runtime_detail,
        },
        {
            "id": "data:ollama-models",
            "kind": "dataset",
            "name": "ollama-model-pool",
            "title": "Local AI model pool",
            "role": "Phi-4-mini, Qwen3, Llama 3.2, optional Gemma",
            "family": "models",
            "state": model_pool_state,
            "installed": models_installed,
            "required": False,
            "method": "operator-manual",
            "apt_package": None,
            "path": endpoint,
            "version": None,
            "endpoint": endpoint,
            "runtime_present": binary_installed,
            "runtime_api_state": api_state,
            "installed_candidates": present,
            "missing_candidates": missing_required + missing_optional,
            "missing_required_candidates": missing_required,
            "missing_optional_candidates": missing_optional,
            "detail": model_detail,
            "source": f"{OLLAMA_SOURCE} (models pulled locally through Ollama)",
        },
    ]


def inventory() -> dict[str, Any]:
    try:
        from adapter_registry import TOOL_CATALOG
        from agents.council import discover
        from sandbox import isolation_status
    except ImportError:
        from backend.adapter_registry import TOOL_CATALOG
        from backend.agents.council import discover
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
            "security_flags": probe.get("security_flags") or [],
        })

    items.extend(_extra_runtime_items())

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

    try:
        from security.scanners import discover_wordlist
    except ImportError:
        from backend.security.scanners import discover_wordlist
    wordlist = discover_wordlist("")
    wordlist_needed = any(_probe_name(name).get("state") == "installed" for name in ("ffuf", "gobuster"))
    if wordlist_needed or wordlist.get("state") != "observed":
        items.append({
            "id": "data:wordlists",
            "kind": "dataset",
            "name": "wordlists",
            "title": "Reviewed wordlists",
            "role": "ffuf/gobuster content discovery",
            "family": "authorized-content-discovery",
            "state": "installed" if wordlist.get("state") == "observed" else "absent",
            "installed": wordlist.get("state") == "observed",
            "required": False,
            "method": "apt",
            "apt_package": "seclists",
            "path": wordlist.get("path"),
            "version": None,
            "detail": wordlist.get("message") or wordlist.get("path"),
        })

    items.extend(_ollama_items())

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


def _ollama_runtime_proposal(item: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(item.get("endpoint") or "http://127.0.0.1:11434")
    missing = list(item.get("missing_required_candidates") or []) + list(item.get("missing_optional_candidates") or [])
    commands = []
    if item.get("binary_installed"):
        commands.extend([
            "# The Ollama binary is already present on this host.",
            "# Start or restart the loopback runtime, then verify the local API:",
            "ollama serve",
            f"curl {endpoint}/api/version",
        ])
        message = "Ollama is installed, but the loopback API is not healthy. Start the runtime and then verify the API before using local AI."
    else:
        commands.extend([
            f"# Review the official installer and license: {OLLAMA_SOURCE}",
            "# Install Ollama manually on this host. VORTEX will not run an unreviewed internet installer for you.",
            "# After installation, start the loopback runtime and verify it:",
            "ollama serve",
            f"curl {endpoint}/api/version",
        ])
        message = "Ollama is not installed on this host. Install it manually, keep it bound to loopback, and then verify the local API."
    if missing:
        commands.extend([
            "# Then pull the recommended local models:",
            *[f"ollama pull {name}" for name in missing],
            f"curl {endpoint}/api/tags",
        ])
    return {
        **item,
        "auto_install": False,
        "license": "Review upstream license terms",
        "permissions": ["loopback-only", "operator-manual", "no-sudo-from-vortex"],
        "commands": commands,
        "message": message,
    }


def _ollama_model_pool_proposal(item: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(item.get("endpoint") or "http://127.0.0.1:11434")
    missing_required = list(item.get("missing_required_candidates") or [])
    missing_optional = list(item.get("missing_optional_candidates") or [])
    installed = list(item.get("installed_candidates") or [])
    commands = []
    if not item.get("runtime_present"):
        commands.extend([
            "# Install Ollama first; the model pool cannot be pulled until the local runtime exists.",
            f"# Official download page: {OLLAMA_SOURCE}",
        ])
    if item.get("runtime_api_state") != "healthy":
        commands.extend([
            "# Start the local loopback API before pulling or verifying models:",
            "ollama serve",
            f"curl {endpoint}/api/version",
        ])
    if missing_required or missing_optional:
        commands.append("# Pull the missing models locally:")
        commands.extend([f"ollama pull {name}" for name in missing_required + missing_optional])
    commands.extend([
        "# Verify the installed model set:",
        f"curl {endpoint}/api/tags",
        "# Optional: inspect loaded models at runtime:",
        "ollama ps",
    ])
    if missing_required:
        message = (
            "The core local model pool is incomplete. Pull the missing recommended models before relying on local-AI-first routing."
        )
    elif missing_optional:
        message = (
            "The core local model pool is present. The optional specialist model is still missing and can be added later if needed."
        )
    elif installed:
        message = "The recommended local model pool is already installed. No additional download is required."
    else:
        message = "No verified local models are available yet. Pull the recommended models after the Ollama runtime is ready."
    return {
        **item,
        "auto_install": False,
        "license": "Per-model upstream license",
        "permissions": ["operator-manual", "local-storage", "loopback-only"],
        "commands": commands,
        "message": message,
    }


def proposal_for(item_id: str) -> dict[str, Any]:
    data = inventory()
    item = next((row for row in data["items"] if row["id"] == item_id or row["name"] == item_id), None)
    if not item:
        return {"id": item_id, "state": "unknown", "auto_install": False, "message": "Unknown dependency."}
    if item["id"] == "runtime:ollama":
        return _ollama_runtime_proposal(item)
    if item["id"] == "data:ollama-models":
        return _ollama_model_pool_proposal(item)
    if item["installed"]:
        if item.get("state") == "blocked":
            flags = ", ".join(item.get("security_flags") or ["path-safety warning"])
            return {
                **item,
                "auto_install": False,
                "message": f"Already present on this host at {item.get('path') or 'an existing path'}, but VORTEX flagged it for review ({flags}). Reinstall is not required.",
            }
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
        install_message = (
            f"{item['title']} can be installed with the reviewed apt adapter. "
            "VORTEX will build a typed plan. Root is required; no sudo password is captured. "
            "Approve the plan only on a host you administer."
        )
        if item.get("kind") == "dataset":
            install_message = (
                f"{item['title']} are used only as operator-provided scan inputs. "
                "VORTEX will build a reviewed apt plan for the distro wordlist package and will not substitute /etc/passwd or another sensitive file."
            )
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
            "message": install_message,
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
