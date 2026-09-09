"""Upstream tracking for secondary AI assistants.

Each third-party agent stays linked to its original repository so operator
updates flow into VORTEX honestly: :func:`table` reports the link, license,
install guide, and consult-interface status, while :func:`refresh` (only ever
operator-triggered, never automatic) checks the upstream HEAD commit through
the public GitHub API.

VORTEX never downloads, executes, or auto-installs third-party code. Agents
without a uniquely verified repository (HALO, DarkMoon) are reported as
``unverified`` — no URL is invented for them.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_MAX_API_BYTES = 256 * 1024

UPSTREAM: dict[str, dict[str, Any]] = {
    "vortex-local": {
        "repository": "builtin",
        "docs": "builtin",
        "license": "MIT",
        "branch": "builtin",
        "consult": "responded",
        "install": ["Built in. No install required."],
        "notes": "Deterministic local advisor. Always present; never executes.",
    },
    "cai": {
        "repository": "https://github.com/aliasrobotics/cai",
        "docs": "https://github.com/aliasrobotics/cai#readme",
        "license": "MIT",
        "branch": "main",
        "consult": "requires_configuration",
        "install": ["Review https://github.com/aliasrobotics/cai and its MIT license.",
                    "Install with the upstream README (pipx or source checkout).",
                    "Ensure the `cai` binary is on PATH, then rescan agents."],
        "notes": "Advisory only. No reviewed non-interactive consult interface is configured.",
    },
    "strix": {
        "repository": "https://github.com/usestrix/strix",
        "docs": "https://github.com/usestrix/strix#readme",
        "license": "Apache-2.0",
        "branch": "main",
        "consult": "requires_configuration",
        "install": ["Review https://github.com/usestrix/strix and its Apache-2.0 license.",
                    "Follow the upstream install guide for your platform.",
                    "Ensure the `strix` binary is on PATH, then rescan agents."],
        "notes": "Advisory only. No reviewed non-interactive consult interface is configured.",
    },
    "nebula": {
        "repository": "https://github.com/BerylliumSec/nebula",
        "docs": "https://github.com/BerylliumSec/nebula#readme",
        "license": "BSD-2-Clause",
        "branch": "main",
        "consult": "requires_configuration",
        "install": ["Review https://github.com/BerylliumSec/nebula and its BSD-2-Clause license.",
                    "Install per the upstream README (Go toolchain).",
                    "Ensure the `nebula` binary is on PATH, then rescan agents."],
        "notes": "Advisory only. No reviewed non-interactive consult interface is configured.",
    },
    "pentestgpt": {
        "repository": "https://github.com/GreyDGL/PentestGPT",
        "docs": "https://github.com/GreyDGL/PentestGPT#readme",
        "license": "MIT",
        "branch": "main",
        "consult": "requires_configuration",
        "install": ["Review https://github.com/GreyDGL/PentestGPT and its MIT license.",
                    "Install per the upstream README (Python).",
                    "Ensure `pentestgpt` is on PATH, then rescan agents."],
        "notes": "Advisory only. No reviewed non-interactive consult interface is configured.",
    },
    "hexstrike": {
        "repository": "https://github.com/0x4m4/hexstrike-ai",
        "docs": "https://github.com/0x4m4/hexstrike-ai#readme",
        "license": "MIT",
        "branch": "main",
        "consult": "requires_configuration",
        "install": ["Review https://github.com/0x4m4/hexstrike-ai and its MIT license.",
                    "Install per the upstream README.",
                    "Ensure `hexstrike` is on PATH, then rescan agents."],
        "notes": "Advisory only. No reviewed non-interactive consult interface is configured.",
    },
    "pentagi": {
        "repository": "https://github.com/vxcontrol/pentagi",
        "docs": "https://github.com/vxcontrol/pentagi#readme",
        "license": "MIT",
        "branch": "main",
        "consult": "requires_configuration",
        "install": ["Review https://github.com/vxcontrol/pentagi and its MIT license.",
                    "Install per the upstream README.",
                    "Ensure `pentagi` is on PATH, then rescan agents."],
        "notes": "Advisory only. No reviewed non-interactive consult interface is configured.",
    },
    "hackerai": {
        "repository": "https://hackerai.co",
        "docs": "https://hackerai.co",
        "license": "proprietary/unknown",
        "branch": "unknown",
        "consult": "requires_configuration",
        "install": ["No public local CLI was verified for HackerAI.",
                    "If upstream publishes one, review its terms before installing."],
        "notes": "No public local CLI was verified. Health check looks only for a local binary.",
    },
    "halo": {
        "repository": "",
        "docs": "",
        "license": "unknown",
        "branch": "unknown",
        "consult": "requires_configuration",
        "install": ["No uniquely verified repository is configured for HALO.",
                    "Do not install similarly-named packages without verifying the publisher."],
        "notes": "No uniquely verified repository is configured.",
    },
    "darkmoon": {
        "repository": "",
        "docs": "",
        "license": "unknown",
        "branch": "unknown",
        "consult": "requires_configuration",
        "install": ["No uniquely verified repository is configured for DarkMoon.",
                    "Do not install similarly-named packages without verifying the publisher."],
        "notes": "No uniquely verified repository is configured.",
    },
}

_LOCK = threading.RLock()
# agent_id -> {"state": str, "sha": str|None, "checked_at": str|None, "message": str}
_SYNC: dict[str, dict[str, Any]] = {}


def _github_api_path(repository: str) -> str | None:
    try:
        parsed = urllib.parse.urlsplit(repository)
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        return None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1].removesuffix(".git")
    return f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=1"


def table() -> dict[str, dict[str, Any]]:
    """Offline-safe upstream table merged with the last refresh state."""
    with _LOCK:
        sync = {key: dict(value) for key, value in _SYNC.items()}
    out: dict[str, dict[str, Any]] = {}
    for agent_id, meta in UPSTREAM.items():
        entry = dict(meta)
        entry["install"] = list(meta.get("install") or [])
        last = sync.get(agent_id) or {}
        if not entry.get("repository") or entry["repository"] in {"builtin", "unverified"}:
            entry["sync_state"] = "builtin" if entry["repository"] == "builtin" else "unverified"
        elif not _github_api_path(str(entry["repository"])):
            entry["sync_state"] = last.get("state") or "not_tracked"
        else:
            entry["sync_state"] = last.get("state") or "not_checked"
        entry["sync"] = last or None
        out[agent_id] = entry
    return out


def enrich(agent_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Attach upstream info to a council metadata dict (pure, offline-safe)."""
    upstream = table().get(agent_id) or {}
    enriched = dict(metadata)
    enriched["upstream"] = {
        "repository": upstream.get("repository") or None,
        "docs": upstream.get("docs") or None,
        "license": upstream.get("license") or "unknown",
        "consult": upstream.get("consult") or "requires_configuration",
        "sync_state": upstream.get("sync_state") or "not_checked",
        "sync": upstream.get("sync"),
        "notes": upstream.get("notes") or "",
    }
    return enriched


def install_guide(agent_id: str) -> list[str]:
    return list((UPSTREAM.get(agent_id) or {}).get("install") or ["No install guide is configured."])


def _fetch_head(api_url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        api_url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Vortex/0.2 (operator-triggered upstream check)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - reviewed github API URL
        final = str(response.geturl()) if callable(getattr(response, "geturl", None)) else api_url
        if urllib.parse.urlsplit(final).hostname != "api.github.com":
            raise ValueError("upstream check redirected outside api.github.com")
        raw = response.read(_MAX_API_BYTES + 1)
        if len(raw) > _MAX_API_BYTES:
            raise ValueError("upstream response exceeded the allowed size")
    payload = json.loads(raw.decode("utf-8", "replace") or "[]")
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ValueError("upstream did not return a commit list")
    head = payload[0]
    sha = str(head.get("sha") or "")[:40]
    commit = head.get("commit") or {}
    message = str((commit.get("message") or "").splitlines()[0][:160]) if isinstance(commit, dict) else ""
    return {"sha": sha, "message": message}


def _now_iso() -> str:
    try:
        from ..vortex_backend import now_iso
    except ImportError:
        try:
            from vortex_backend import now_iso  # type: ignore
        except ImportError:
            from backend.vortex_backend import now_iso  # type: ignore
    return now_iso()


def refresh(agent_id: str | None = None, *, timeout: float = 8.0, offline: bool = False) -> dict[str, Any]:
    """Operator-triggered upstream HEAD check. Network only when called.

    ``agent_id`` limits the check to one agent; ``None`` checks every
    GitHub-backed agent. Offline mode refuses without touching the network.
    Failures are recorded per agent, never raised past the caller.
    """
    if offline:
        return {"state": "offline", "checked": [], "message": "Offline mode blocks upstream checks."}
    targets = [agent_id] if agent_id else [key for key in UPSTREAM if _github_api_path(str(UPSTREAM[key].get("repository") or ""))]
    if agent_id and agent_id not in UPSTREAM:
        return {"state": "unknown_agent", "checked": [], "message": f"Unknown agent: {agent_id}"}
    checked: list[dict[str, Any]] = []
    for target in targets:
        meta = UPSTREAM.get(target) or {}
        api_url = _github_api_path(str(meta.get("repository") or ""))
        if not api_url:
            continue
        try:
            head = _fetch_head(api_url, timeout)
            record = {"state": "checked", "sha": head["sha"], "message": head["message"],
                      "checked_at": _now_iso(), "repository": meta.get("repository")}
        except Exception as exc:
            record = {"state": "error", "sha": None, "message": str(exc)[:200],
                      "checked_at": _now_iso(), "repository": meta.get("repository")}
        with _LOCK:
            _SYNC[target] = record
        checked.append({"agent": target, **record})
    return {"state": "checked" if checked else "nothing_tracked",
            "checked": checked,
            "message": f"Checked {len(checked)} upstream repositorie(s)." if checked else "No GitHub-backed agents to check."}
