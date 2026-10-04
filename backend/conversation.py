"""Conversation / action classifier and the conversational AI turn.

USER INPUT
  |
  +-- conversational --> AI provider layer (ProviderManager, free-only aware)
  |
  +-- action/command --> deterministic planner -> Guardian -> adapter -> execute

Ordinary conversation ("hello", "what is Docker?") must get a natural AI
answer with no Guardian commentary and no fabricated execution plan.
Anything that asks Vortex to observe or mutate the system keeps flowing
through the existing planner/Guardian/adapter authority. The classifier
only ever diverts pure conversation away from execution planning; it can
never authorize execution by itself.
"""
from __future__ import annotations

import re
from typing import Any

# Shell syntax is always routed to the planner, which refuses it honestly.
_SHELL_SYNTAX = re.compile(r"[\x00\n\r]|[|<>]|;|&&|\|\||`|\$\(")

# Bare commands and well-known binaries are actions even without a verb.
_KNOWN_BINARIES = {
    "whoami", "uname", "hostname", "uptime", "date", "df", "du", "free",
    "lsblk", "lscpu", "lsusb", "lspci", "ps", "top", "htop", "ls", "pwd",
    "ip", "ss", "netstat", "ping", "dig", "nslookup", "traceroute", "whois",
    "git", "systemctl", "journalctl", "docker", "podman", "apt", "apt-get",
    "dpkg", "snap", "nmap", "nuclei", "nikto", "gobuster", "ffuf", "amass",
    "ssh", "curl", "wget", "cat", "kill", "pkill", "killall", "mount",
    "umount", "sudo", "ifconfig", "iwconfig", "lsof", "last", "w", "who",
}

_ACTION_VERBS = (
    "show", "list", "check", "inspect", "display", "view", "read", "scan",
    "run", "execute", "find", "search", "locate", "measure", "monitor",
    "diagnose", "audit", "enumerate", "probe", "collect", "fetch", "tail",
    "kill", "stop", "start", "restart", "reload", "enable", "disable",
    "install", "remove", "uninstall", "delete", "purge", "update", "upgrade",
    "create", "open", "mount", "unmount", "block", "allow", "trace", "watch",
    "get", "grab", "dump", "print", "see",
)

_SYSTEM_NOUNS = (
    "file", "files", "directory", "directories", "folder", "folders", "disk",
    "disks", "storage", "partition", "partitions", "usage", "memory", "ram",
    "cpu", "load", "process", "processes", "pid", "service", "services",
    "daemon", "systemd", "journal", "log", "logs", "port", "ports", "socket",
    "sockets", "interface", "interfaces", "route", "routes", "dns",
    "firewall", "iptables", "nftables", "package", "packages", "repository",
    "repo", "branch", "branches", "commit", "commits", "diff", "container",
    "containers", "image", "images", "volume", "volumes", "kernel", "boot",
    "hardware", "device", "devices", "user", "users", "group", "groups",
    "login", "logins", "session", "sessions", "uptime", "hostname", "clock",
    "timezone", "temperature", "battery", "mount", "mounts", "filesystem",
    "swap", "inode", "inodes", "network", "wifi", "bluetooth", "ip",
    "address", "addresses", "dns", "gateway", "system", "health", "machine",
    "host", "server", "computer",
    # Destructive/privileged command names: "run rm -rf /"-style phrasing
    # must face the planner/Guardian (which reviews or refuses), never a
    # chat model. Educational phrasings ("explain rm", "what does dd do")
    # are caught earlier by the conversational openers.
    "rm", "rmdir", "mkfs", "dd", "reboot", "shutdown", "poweroff", "chmod",
    "chown", "sudo",
)

_SECURITY_INTENTS = (
    "nmap", "nuclei", "nikto", "gobuster", "ffuf", "amass", "pentest",
    "penetration test", "port scan", "vulnerability scan", "vuln scan",
    "exploit", "brute force", "bruteforce", "osint", "recon",
    "reconnaissance", "engagement", "security assessment", "security scan",
    "http headers of", "subdomain", "enumerate", "fuzz",
)

_GREETINGS = {
    "hello", "hi", "hey", "yo", "hiya", "howdy", "good morning",
    "good afternoon", "good evening", "good night", "thanks", "thank you",
    "ok", "okay", "cool", "nice", "bye", "goodbye", "how are you",
    "how are you?", "sup", "whats up", "what's up",
}

_CONVERSATION_OPENERS = (
    "what is", "what are", "what's", "whats ", "what does", "what do",
    "who is", "who are", "who was", "when ", "where ", "why ", "how do i",
    "how do you", "how does", "how can i", "how to", "explain", "describe",
    "tell me", "teach me", "define", "compare", "difference between",
    "summarize", "translate", "write ", "help me write", "help me with",
    "can you", "could you", "would you", "give me an example", "recommend",
    "suggest", "brainstorm", "review this", "improve this", "what should",
    "is it true", "does ", "do you", "are you", "pros and cons",
)

# Question-style phrases that still clearly target THIS machine.
_THIS_MACHINE = (
    "my ", "this machine", "this system", "this host", "this box",
    "this server", "this laptop", "this computer", "do i have", "am i",
    "is left", "are running", "is running", "are listening", "are open",
    "on here", "in here", "right now",
)


def _first_token(lower: str) -> str:
    return lower.split()[0] if lower.split() else ""


def _mentions(lower: str, needles: tuple[str, ...]) -> bool:
    return any(needle in lower for needle in needles)


def _word_match(lower: str, words: tuple[str, ...] | set[str]) -> bool:
    tokens = set(re.findall(r"[a-z0-9./@:-]+", lower))
    return any(word in tokens for word in words)


def classify(request: str) -> dict[str, Any]:
    """Classify one user input as `conversation` or `action`.

    Deterministic and auditable: the returned reason names the rule that
    fired. When genuinely ambiguous, inputs that reference this machine's
    state become actions (planner + Guardian), everything else is
    conversation — a misrouted conversation can never execute anything,
    because the planner/Guardian still review every action path.
    """
    text = (request or "").strip()
    lower = text.lower().rstrip("!. ")
    if not lower:
        return {"category": "conversation", "reason": "empty input"}
    if _SHELL_SYNTAX.search(text):
        return {"category": "action", "reason": "shell syntax routes to the planner, which reviews or refuses it"}
    if lower in _GREETINGS:
        return {"category": "conversation", "reason": "greeting/small talk"}
    first = _first_token(lower)
    if first in _KNOWN_BINARIES:
        # "who" doubles as an English interrogative: "who are you" /
        # "who invented linux" are conversation, while "who", "who -b" and
        # "who am i" remain the coreutil.
        interrogative_who = first == "who" and re.match(
            r"who\s+(?!am\s+i\b)[a-z]", lower) and not re.match(r"who\s+-", lower)
        if not interrogative_who:
            return {"category": "action", "reason": f"starts with the known command '{first}'"}
    if _mentions(lower, _SECURITY_INTENTS):
        return {"category": "action", "reason": "security operation — requires planner, Guardian, and engagement authorization"}
    if re.match(r"^(install|remove|uninstall|purge|upgrade|update)\s+\S+", lower):
        return {"category": "action", "reason": "package mutation request"}
    if re.search(r"(?:^|\s)(/etc/|/var/|/usr/|/opt/|/home/|/root/|/proc/|/sys/|~/)", text) or re.search(r"\.\./", text):
        return {"category": "action", "reason": "references a concrete filesystem path on this machine"}
    for opener in _CONVERSATION_OPENERS:
        if lower.startswith(opener):
            # "what processes are running" style questions still target the
            # host — but "why …" diagnostics stay conversational: there is no
            # deterministic plan for a "why", and the AI reply can suggest
            # concrete commands the operator then runs through the planner.
            if (not lower.startswith("why")
                    and _word_match(lower, _SYSTEM_NOUNS) and _mentions(lower, _THIS_MACHINE)):
                return {"category": "action", "reason": "question about this machine's live state"}
            return {"category": "conversation", "reason": f"conversational phrasing ('{opener.strip()}…')"}
    has_verb = bool(re.match(r"^(please\s+|can you\s+|could you\s+|go\s+)?(" + "|".join(_ACTION_VERBS) + r")\b", lower)) or _word_match(lower, set(_ACTION_VERBS))
    has_noun = _word_match(lower, _SYSTEM_NOUNS)
    if has_verb and has_noun:
        return {"category": "action", "reason": "action verb + system object"}
    if has_noun and _mentions(lower, _THIS_MACHINE):
        return {"category": "action", "reason": "references this machine's state"}
    if lower.endswith("?") or any(lower.startswith(q) for q in ("what", "why", "how", "who", "when", "where", "is ", "are ", "can ", "should ")):
        return {"category": "conversation", "reason": "question without a system action target"}
    if has_noun:
        # Bare system noun phrases ("disk usage", "listening ports") behave
        # like the legacy terminal shortcuts and stay on the planner path.
        return {"category": "action", "reason": "system object shorthand"}
    return {"category": "conversation", "reason": "no system action detected"}


def _manager():
    try:
        from backend.providers.manager import manager  # type: ignore
    except ImportError:
        from providers.manager import manager  # type: ignore
    return manager()


def _system_prompt() -> str:
    try:
        from backend.providers.manager import CONVERSATION_SYSTEM_PROMPT  # type: ignore
    except ImportError:
        from providers.manager import CONVERSATION_SYSTEM_PROMPT  # type: ignore
    return CONVERSATION_SYSTEM_PROMPT


def build_messages(request: str, history: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    """System prompt + bounded recent history + the new user turn."""
    messages: list[dict[str, str]] = [{"role": "system", "content": _system_prompt()}]
    for item in (history or [])[-10:]:
        role = str(item.get("role") or "")
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        if role in {"vortex", "assistant"}:
            messages.append({"role": "assistant", "content": content[:4000]})
        elif role == "user":
            messages.append({"role": "user", "content": content[:4000]})
    messages.append({"role": "user", "content": str(request)[:8000]})
    return messages


def _needs_consensus(request: str, settings: dict[str, Any]) -> bool:
    mode = str(settings.get("secondary_ai_mode") or "on-demand")
    if mode == "consensus":
        return True
    if mode == "auto":
        lower = str(request).lower()
        difficult = len(request) > 400 or _mentions(lower, (
            "error", "traceback", "stack trace", "segfault", "debug",
            "why does", "root cause", "compare", "trade-off", "tradeoff",
        ))
        return difficult
    return False


def respond(request: str, settings: dict[str, Any] | None = None, *,
            history: list[dict[str, Any]] | None = None,
            provider_id: str | None = None, model: str | None = None) -> dict[str, Any]:
    """Answer a conversational turn through the provider layer.

    Returns a result that either carries a natural `reply` or a precise,
    per-provider explanation of why no free provider could answer. No
    Guardian commentary is attached to conversation — the Guardian governs
    execution, and nothing here executes.
    """
    settings = settings or {}
    mgr = _manager()
    if _needs_consensus(request, settings):
        council = mgr.consensus(request, settings)
        if council.get("state") == "responded" and council.get("synthesis"):
            primary = (council.get("responses") or [{}])[0]
            return {
                "state": "responded",
                "mode": "consensus",
                "reply": str(council.get("synthesis")),
                "provider": council.get("synthesizer") or primary.get("provider"),
                "model": primary.get("model"),
                "latency_ms": primary.get("latency_ms"),
                "consensus": council,
            }
        # Council could not form — fall through to single-provider answer.
    messages = build_messages(request, history)
    result = mgr.generate(messages, settings, provider_id=provider_id, model=model, purpose="conversation")
    if result.get("state") == "responded":
        return {
            "state": "responded",
            "mode": "single",
            "reply": str(result.get("reply") or ""),
            "provider": result.get("provider"),
            "provider_name": result.get("provider_name"),
            "model": result.get("model"),
            "free": result.get("free"),
            "latency_ms": result.get("latency_ms"),
            "attempts": result.get("attempts") or [],
        }
    return {
        "state": "unavailable",
        "mode": "single",
        "reply": "",
        "message": str(result.get("message") or "All configured free AI providers are currently unavailable."),
        "attempts": result.get("attempts") or [],
        "policy": result.get("policy"),
    }
