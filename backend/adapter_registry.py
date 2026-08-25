"""Reviewed built-in Linux adapter and tool manifests.

The registry is data-only. Adapter builders and the execution authority remain
separate so a model or project directory cannot add capabilities at runtime.
"""
from __future__ import annotations

from typing import Any

TOOL_CATALOG: dict[str, dict[str, Any]] = {
    "git": {"family": "development", "probe": ["--version"], "role": "version-control"},
    "ss": {"family": "network", "probe": ["-V"], "role": "socket inspection"},
    "ip": {"family": "network", "probe": ["-Version"], "role": "network facts"},
    "systemctl": {"family": "systemd", "probe": ["--version"], "role": "service inspection"},
    "journalctl": {"family": "systemd", "probe": ["--version"], "role": "bounded logs"},
    "df": {"family": "filesystem", "probe": ["--version"], "role": "filesystem usage"},
    "du": {"family": "filesystem", "probe": ["--version"], "role": "directory usage"},
    "free": {"family": "system", "probe": ["--version"], "role": "memory facts"},
    "uname": {"family": "system", "probe": ["-a"], "role": "kernel facts"},
    "uptime": {"family": "system", "probe": ["--version"], "role": "load facts"},
    "nmap": {"family": "authorized-reconnaissance", "probe": ["--version"], "role": "scoped service discovery"},
    "nuclei": {"family": "authorized-assessment", "probe": ["-version"], "role": "reviewed template checks"},
    "curl": {"family": "authorized-http", "probe": ["--version"], "role": "HTTP/TLS discovery"},
    "ffuf": {"family": "authorized-content-discovery", "probe": ["-V"], "role": "bounded content discovery"},
    "nikto": {"family": "authorized-assessment", "probe": ["-Version"], "role": "web server assessment"},
    "amass": {"family": "passive-osint", "probe": ["-version"], "role": "passive domain discovery"},
    "ssh": {"family": "ssh-diagnostics", "probe": ["-V"], "role": "connection diagnostics"},
    "apt-get": {"family": "packages", "probe": ["--version"], "role": "package planning and mutation"},
    "apt-cache": {"family": "packages", "probe": ["--version"], "role": "package metadata"},
    "dpkg-query": {"family": "packages", "probe": ["--version"], "role": "installed package facts"},
    "dpkg": {"family": "packages", "probe": ["--version"], "role": "dpkg consistency facts"},
    "apt-mark": {"family": "packages", "probe": ["--version"], "role": "held package facts"},
    "docker": {"family": "containers", "probe": ["--version"], "role": "container inspection"},
    "podman": {"family": "containers", "probe": ["--version"], "role": "container inspection"},
}


ADAPTER_MANIFESTS: dict[str, dict[str, Any]] = {
    "linux.system.health": {"version": "1", "family": "system", "tool": "multiple", "risk": "low", "network_class": "no-network", "operation": "read-only host facts", "limits": {"commands": 4, "timeout_seconds": 30}},
    "linux.filesystem.usage": {"version": "1", "family": "filesystem", "tool": "df+du", "risk": "low", "network_class": "no-network", "operation": "read-only filesystem facts", "limits": {"depth": 1, "timeout_seconds": 30}},
    "linux.network.sockets": {"version": "1", "family": "network", "tool": "ss", "risk": "low", "network_class": "no-network", "operation": "read-only local socket facts", "limits": {"timeout_seconds": 30}},
    "linux.development.git-status": {"version": "1", "family": "development", "tool": "git", "risk": "low", "network_class": "no-network", "operation": "read-only repository facts", "limits": {"timeout_seconds": 30}},
    "linux.systemd.inspect": {"version": "1", "family": "systemd", "tool": "systemctl+journalctl", "risk": "low", "network_class": "no-network", "operation": "read-only unit and journal facts", "limits": {"journal_lines": 80, "timeout_seconds": 30}},
    "linux.systemd.mutate": {"version": "1", "family": "systemd", "tool": "systemctl", "risk": "high", "network_class": "no-network", "operation": "guarded service mutation", "privilege": "root-required", "limits": {"timeout_seconds": 60}},
    "linux.packages.apt": {"version": "1", "family": "packages", "tool": "apt-get+apt-cache+dpkg-query+dpkg+apt-mark", "risk": "high", "network_class": "outbound-mutation", "operation": "guarded apt package operation", "privilege": "root-required", "limits": {"timeout_seconds": 900}},
    "linux.containers.inspect": {"version": "1", "family": "containers", "tool": "docker+podman", "risk": "low", "network_class": "loopback-only", "operation": "read-only container inspection", "limits": {"output_cap_bytes": 524288, "timeout_seconds": 30}},
    "linux.containers.logs": {"version": "1", "family": "containers", "tool": "docker+podman", "risk": "low", "network_class": "loopback-only", "operation": "bounded container logs", "limits": {"tail_lines": 200, "timeout_seconds": 30}},
    "linux.ssh.config": {"version": "1", "family": "ssh-diagnostics", "tool": "ssh", "risk": "low", "network_class": "no-network", "operation": "read-only SSH configuration resolution", "limits": {"timeout_seconds": 15}},
    "linux.ssh.connection": {"version": "1", "family": "ssh-diagnostics", "tool": "ssh", "risk": "high", "network_class": "outbound-read", "operation": "bounded SSH connectivity diagnostic", "limits": {"connect_timeout_seconds": 5, "timeout_seconds": 15}},
    "security.nmap.discovery": {"version": "1", "family": "authorized-reconnaissance", "tool": "nmap", "risk": "high", "network_class": "outbound-read", "operation": "scoped service discovery", "limits": {"max_cidr_hosts": 256, "max_ports": 32, "timing": "T2", "timeout_seconds": 120}},
    "security.http.headers": {"version": "1", "family": "authorized-http", "tool": "curl", "risk": "high", "network_class": "outbound-read", "operation": "bounded HTTP/TLS header discovery", "limits": {"max_time_seconds": 15, "max_redirects": 0}},
}

