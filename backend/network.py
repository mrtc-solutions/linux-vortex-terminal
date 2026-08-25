"""Small real network-fact helpers used by scoped adapters.

This module only resolves operator-declared targets. It never scans, connects,
sends payloads, follows redirects, or invents reachability.
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.parse
from typing import Any


def target_endpoint(target: str) -> tuple[str | None, int | None]:
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme:
        return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    if "/" in target:
        try:
            network = ipaddress.ip_network(target, strict=False)
            return None, None if network.num_addresses > 1 else None
        except ValueError:
            pass
    try:
        ipaddress.ip_address(target)
        return target, None
    except ValueError:
        return target.split("/", 1)[0], None


def resolve_target(target: str) -> dict[str, Any]:
    host, port = target_endpoint(target)
    if not host:
        return {"target": target, "state": "not_applicable", "addresses": []}
    try:
        ipaddress.ip_address(host)
        return {"target": target, "host": host, "port": port, "state": "observed", "addresses": [host]}
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError) as exc:
        return {"target": target, "host": host, "port": port, "state": "tool_error", "addresses": [], "error": str(exc)[:240]}
    addresses = sorted({item[4][0] for item in infos if item[4] and item[4][0]})[:32]
    return {"target": target, "host": host, "port": port, "state": "observed" if addresses else "inconclusive", "addresses": addresses}


def resolve_targets(targets: list[str]) -> dict[str, Any]:
    facts = [resolve_target(target) for target in targets]
    return {"state": "observed" if facts and all(item["state"] in ("observed", "not_applicable") for item in facts) else "tool_error", "targets": facts}


def resolution_digest(facts: dict[str, Any]) -> str:
    import hashlib
    import json
    stable = [{"target": item.get("target"), "addresses": item.get("addresses", []), "state": item.get("state")} for item in facts.get("targets", [])]
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
