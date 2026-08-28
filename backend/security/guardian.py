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
    "linux.system.packages",
    "linux.system.storage",
    "linux.system.hardware",
    "linux.filesystem.usage",
    "linux.filesystem.list",
    "linux.filesystem.read",
    "linux.filesystem.log",
    "linux.network.sockets",
    "linux.network.interfaces",
    "linux.network.facts",
    "linux.network.routes",
    "linux.network.firewall",
    "linux.network.wifi",
    "linux.system.clock",
    "linux.system.os-release",
    "linux.system.cpu",
    "linux.system.login",
    "linux.development.git-status",
    "linux.development.git-log",
    "linux.development.git-branches",
    "linux.development.git-diff",
    "linux.systemd.inspect",
    "linux.systemd.journal",
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
    "linux.network.ping",
    "linux.network.dns",
    "linux.network.whois",
    "linux.ssh.connection",
}
LOW_NETWORK = {"no-network", "loopback-only"}
DESTRUCTIVE_WORDS = {
    "rm", "mkfs", "dd", "wipefs", "shred", "chown",
    "iptables", "nft", "reboot", "poweroff", "halt", "kexec",
}
# World-writable chmod: 777, 0777, 2777/4777/6777, and a+rwx / a=rwx.
CHMOD_WORLD_RE = re.compile(
    r"(?:^|[\s;|&])chmod(?:\s+-[A-Za-z]+)*\s+(?:0*[0-7]?777\b|a\+rwx|a=rwx|ugo\+rwx|ugo=rwx)",
    re.I,
)
TOKEN_RE = re.compile(r"[A-Za-z0-9._+/-]+")


_READONLY_FIREWALL_RE = re.compile(
    r"(?:^|[\s;|&])(?:iptables|ip6tables|iptables-restore|nft)\s+(?:-[A-Za-z]*[SLnVN][A-Za-z]*\b|\b(?:list|show|status|rule)\b)",
    re.I,
)


def looks_destructive(display: str) -> bool:
    """Match destructive command words, not accidental substrings like adduser/remove."""
    text = (display or "").lower()
    if CHMOD_WORLD_RE.search(text):
        return True
    read_only_firewall = bool(_READONLY_FIREWALL_RE.search(text))
    for part in TOKEN_RE.findall(text):
        base = part.rsplit("/", 1)[-1]
        if base in DESTRUCTIVE_WORDS:
            if base in {"iptables", "ip6tables", "nft"} and read_only_firewall:
                continue
            return True
        # mkfs.ext4 / mkfs.xfs must match mkfs without treating adduser as dd.
        stem = base.split(".", 1)[0]
        if stem in DESTRUCTIVE_WORDS:
            if stem in {"iptables", "ip6tables", "nft"} and read_only_firewall:
                continue
            return True
    return False


def _load_scope_excluded():
    """Resolve ``scope.excluded`` under every supported import context.

    The Guardian is imported both as ``backend.security.guardian`` (package
    context: CLI, tests, external consumers) and as ``security.guardian``
    (sidecar context, where ``backend/`` is on ``sys.path``). Returning ``None``
    lets the caller fail closed instead of raising past the exclusion check.
    """
    try:
        from .scope import excluded
        return excluded
    except ImportError:
        pass
    try:
        from security.scope import excluded  # type: ignore[no-redef]
        return excluded
    except ImportError:
        pass
    try:
        from backend.security.scope import excluded  # type: ignore[no-redef]
        return excluded
    except ImportError:
        return None


def requires_engagement(plan: dict[str, Any]) -> bool:
    """Recompute the scope requirement from typed commands and declared scope.

    This mirrors ``vortex_backend.plan_requires_engagement`` so the Guardian and
    the execution authority cannot drift. Assessment adapters, SSH connections,
    and outbound-read commands need an engagement regardless of the plan's
    ``kind`` label. Local package/systemd mutations are operator-administered
    host changes, not third-party network work, so they keep the root/preflight
    gate instead of the engagement gate.
    """
    if plan.get("scope", {}).get("targets"):
        return True
    for spec in plan.get("commands") or []:
        adapter = str(spec.get("adapter_id") or "")
        if adapter in MEDIUM_ADAPTERS:
            continue
        if adapter.startswith("security.") or adapter == "linux.ssh.connection":
            return True
        if adapter in HIGH_ADAPTERS:
            return True
        if str(spec.get("network_class") or "") == "outbound-read":
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
    if policy.get("profile") == "safe":
        policy["auto_low_risk"] = False
        policy["auto_medium_risk"] = False
    policy["auto_medium_risk"] = False
    policy["auto_low_risk"] = policy.get("auto_low_risk") is True and policy.get("profile") in {"standard", "expert"}
    policy["offline"] = policy.get("offline") is True
    commands = list(plan.get("commands") or [])
    risk = recompute_risk(commands)
    reasons: list[str] = []
    blocked = False
    requires_approval = True
    display = " ".join(str(spec.get("display") or "") for spec in commands)
    if looks_destructive(display):
        blocked = True
        reasons.append("Guardian blocked a potentially destructive command class.")
    if policy.get("offline") is True and any(spec.get("network_class") not in LOW_NETWORK for spec in commands):
        blocked = True
        reasons.append("Offline policy blocks network-effecting commands.")
    if any(spec.get("network_class") not in LOW_NETWORK for spec in commands):
        engagement_ok = False
        if engagement and engagement.get("status") == "active" and not engagement.get("expired"):
            engagement_ok = True
            try:
                from datetime import datetime
                import time as _time
                if _time.time() > datetime.fromisoformat(str(engagement.get("expires_at"))).timestamp():
                    engagement_ok = False
            except (TypeError, ValueError):
                engagement_ok = False
        if not engagement_ok and requires_engagement(plan):
            # Guardian recomputes the scope requirement from the typed command
            # specs, not from the planner's `kind` label. A model or a future
            # planner branch cannot avoid the engagement gate by emitting a
            # network-effecting command under an unrecognised plan kind.
            blocked = True
            reasons.append("Active network work requires an authorized engagement.")
        reasons.append("Network-effecting command; scope must remain valid at execution.")
        excluded = _load_scope_excluded()
        for target in plan.get("scope", {}).get("targets") or []:
            if excluded is None:
                blocked = True
                reasons.append("Engagement exclusion list could not be evaluated; Guardian fails closed.")
                break
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
