"""VORTEX Guardian — independent of any model or external agent.

The Guardian recomputes risk from typed command specs, policy, and scope.
An LLM or agent cannot instruct it to approve itself.
"""
from __future__ import annotations

import re
from typing import Any

LOW_ADAPTERS = {
    "linux.system.health",
    "linux.system.identity",
    "linux.system.processes",
    "linux.filesystem.usage",
    "linux.filesystem.list",
    "linux.network.sockets",
    "linux.network.interfaces",
    "linux.system.clock",
    "linux.system.os-release",
    "linux.system.cpu",
    "linux.development.git-status",
    "linux.systemd.inspect",
    "linux.containers.inspect",
    "linux.containers.logs",
    "linux.containers.diagnose",
    "linux.ssh.config",
}
MEDIUM_ADAPTERS = {
    "linux.packages.apt",
    "linux.systemd.mutate",
}
HIGH_ADAPTERS = {
    "security.nmap.discovery",
    "security.http.headers",
    "security.nuclei.templates",
    "security.nikto.web",
    "security.amass.passive",
    "security.ffuf.discovery",
    "security.gobuster.discovery",
    "linux.ssh.connection",
}
LOW_NETWORK = {"no-network", "loopback-only"}
DESTRUCTIVE_WORDS = {
    "rm", "mkfs", "dd", "wipefs", "shred", "chown",
    "iptables", "nft", "reboot", "poweroff", "halt", "kexec",
}
DESTRUCTIVE_PHRASES = ("chmod 777",)
TOKEN_RE = re.compile(r"[A-Za-z0-9._+/-]+")


def looks_destructive(display: str) -> bool:
    """Match destructive command words, not accidental substrings like adduser/remove."""
    text = (display or "").lower()
    if any(phrase in text for phrase in DESTRUCTIVE_PHRASES):
        return True
    for part in TOKEN_RE.findall(text):
        base = part.rsplit("/", 1)[-1]
        if base in DESTRUCTIVE_WORDS:
            return True
        # mkfs.ext4 / mkfs.xfs must match mkfs without treating adduser as dd.
        stem = base.split(".", 1)[0]
        if stem in DESTRUCTIVE_WORDS:
            return True
    return False


def recompute_risk(commands: list[dict[str, Any]]) -> str:
    level = "low"
    rank = {"low": 0, "medium": 1, "high": 2}
    for spec in commands:
        adapter = spec.get("adapter_id") or ""
        declared = str(spec.get("risk") or "high")
        privilege = spec.get("privilege") or "user"
        network = spec.get("network_class") or "unknown"
        if adapter in HIGH_ADAPTERS or privilege == "root-required" and adapter in MEDIUM_ADAPTERS:
            candidate = "high"
        elif adapter in MEDIUM_ADAPTERS or network not in LOW_NETWORK:
            candidate = "high" if network not in LOW_NETWORK else "medium"
        elif adapter in LOW_ADAPTERS and network in LOW_NETWORK and privilege == "user":
            candidate = "low"
        else:
            candidate = "high" if declared not in rank else declared
        if spec.get("source") == "operator_direct" or not adapter:
            if declared == "low" and network in LOW_NETWORK and privilege == "user":
                candidate = declared
            else:
                candidate = "high" if not adapter else candidate
        if rank[candidate] > rank[level]:
            level = candidate
    return level if commands else "low"


def policy_defaults(profile: str = "safe") -> dict[str, Any]:
    profile = profile if profile in {"safe", "standard", "expert"} else "safe"
    return {
        "profile": profile,
        "auto_low_risk": profile in {"standard", "expert"},
        "auto_medium_risk": False,
        "offline": False,
        "privacy_mode": "local",
        "allow_root": False,
        "lab_mode": False,
    }


def evaluate(plan: dict[str, Any], policy: dict[str, Any] | None = None, engagement: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = {**policy_defaults(), **(policy or {})}
    commands = list(plan.get("commands") or [])
    risk = recompute_risk(commands)
    reasons: list[str] = []
    blocked = False
    requires_approval = True
    display = " ".join(str(spec.get("display") or "") for spec in commands)
    if looks_destructive(display):
        blocked = True
        reasons.append("Guardian blocked a potentially destructive command class.")
    if policy.get("offline") and any(spec.get("network_class") not in LOW_NETWORK for spec in commands):
        blocked = True
        reasons.append("Offline policy blocks network-effecting commands.")
    if any(spec.get("network_class") not in LOW_NETWORK for spec in commands):
        if not engagement or engagement.get("status") != "active":
            if plan.get("kind") in {"authorized_engagement", "ssh_diagnostics"} and plan.get("status") == "planned":
                blocked = True
                reasons.append("Active network work requires an authorized engagement.")
        reasons.append("Network-effecting command; scope must remain valid at execution.")
        try:
            from security.scope import excluded
        except ImportError:
            from scope import excluded
        for target in plan.get("scope", {}).get("targets") or []:
            if excluded(str(target), engagement):
                blocked = True
                reasons.append("Target is on the engagement exclusion list: " + str(target))
    if risk == "low" and policy.get("auto_low_risk") and not blocked and commands:
        requires_approval = False
        reasons.append("Low-risk local diagnostics may auto-execute under the current policy.")
    elif risk == "medium" and policy.get("auto_medium_risk") and not blocked:
        requires_approval = True
        reasons.append("Medium-risk actions still require recorded approval.")
    else:
        requires_approval = True if commands else False
        if commands:
            reasons.append(f"{risk.upper()} risk requires explicit recorded approval.")
    if not commands:
        reasons.append("No command was proposed; Guardian has nothing to authorize.")
    decision = "blocked" if blocked else ("auto" if commands and not requires_approval else ("approve" if commands else "observe"))
    return {
        "authority": "vortex-guardian",
        "independent_of_model": True,
        "risk": risk,
        "decision": decision,
        "blocked": blocked,
        "requires_approval": bool(commands) and requires_approval and not blocked,
        "reasons": reasons,
        "policy_profile": policy.get("profile", "safe"),
        "command_count": len(commands),
    }
