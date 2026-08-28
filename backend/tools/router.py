"""Stable internal tool router. Not MCP-dependent."""
from __future__ import annotations

from typing import Any


def route(intent: str) -> dict[str, Any]:
    intent = (intent or "").lower()
    mapping = (
        (("disk", "space", "df", "du", "filesystem"), "linux.filesystem.usage"),
        (("tail", "syslog", "log file"), "linux.filesystem.log"),
        (("journal",), "linux.systemd.journal"),
        (("mac address", "arp", "neighbor", "gateway"), "linux.network.facts"),
        (("dns server", "resolv.conf"), "linux.filesystem.read"),
        (("memory", "free", "vmstat", "swap"), "linux.system.health"),
        (("cpu", "processor"), "linux.system.health"),
        (("uptime", "load"), "linux.system.health"),
        (("whoami", "hostname", "pwd", "username", "user name"), "linux.system.identity"),
        (("listen", "port", "socket"), "linux.network.sockets"),
        (("process", "pids", "process tree"), "linux.system.processes"),
        (("git log", "history"), "linux.development.git-log"),
        (("git branch",), "linux.development.git-branches"),
        (("git diff", "repository diff"), "linux.development.git-diff"),
        (("git",), "linux.development.git-status"),
        (("package", "installed package", "dpkg"), "linux.system.packages"),
        (("storage", "block device", "partition", "lsblk"), "linux.system.storage"),
        (("usb", "lsusb"), "linux.system.hardware"),
        (("route",), "linux.network.routes"),
        (("firewall",), "linux.network.firewall"),
        (("wifi", "wireless", "nmcli", "iw"), "linux.network.wifi"),
        (("dns", "nslookup", "dig"), "linux.network.dns"),
        (("whois",), "linux.network.whois"),
        (("nmap",), "security.nmap.discovery"),
        (("nuclei",), "security.nuclei.templates"),
        (("nikto",), "security.nikto.web"),
        (("amass",), "security.amass.passive"),
        (("ffuf",), "security.ffuf.discovery"),
        (("gobuster", "directory brute", "directory bust", "content discovery"), "security.gobuster.discovery"),
        (("curl", "http"), "security.http.headers"),
        (("ping",), "linux.network.ping"),
        (("docker", "podman", "container"), "linux.containers.inspect"),
        (("service", "unit", "systemd"), "linux.systemd.inspect"),
    )
    for keys, adapter in mapping:
        if any(key in intent for key in keys):
            return {"protocol": "vortex-adapter", "adapter_id": adapter, "mcp": False}
    return {"protocol": "vortex-adapter", "adapter_id": None, "mcp": False, "message": "No reviewed adapter for this intent."}
