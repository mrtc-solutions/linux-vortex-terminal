"""First-run diagnostics for low-resource Linux hosts.

This module deliberately does not install packages or download models. It gives
an operator one deterministic report explaining what is ready, what is optional,
and the exact next action for anything missing.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _version(command: str, args: tuple[str, ...] = ("--version",)) -> str | None:
    path = shutil.which(command)
    if not path:
        return None
    try:
        result = subprocess.run([path, *args], capture_output=True, text=True, timeout=4, check=False)
        text = (result.stdout or result.stderr or "").strip().splitlines()
        return text[0][:160] if result.returncode == 0 and text else None
    except (OSError, subprocess.SubprocessError):
        return None


def _mem_mb() -> tuple[int | None, int | None]:
    total = available = None
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, raw = line.partition(":")
            value = raw.strip().split()[0] if raw.strip() else ""
            if not value.isdigit():
                continue
            if key == "MemTotal":
                total = int(value) // 1024
            elif key == "MemAvailable":
                available = int(value) // 1024
    except (OSError, ValueError):
        pass
    return total, available


def _check(name: str, state: str, detail: str, action: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"name": name, "state": state, "detail": detail}
    if action:
        item["next_action"] = action
    return item


def collect(root: Path | None = None) -> dict[str, Any]:
    root = (root or Path(__file__).resolve().parent.parent).resolve()
    total_mb, available_mb = _mem_mb()
    cpu_count = os.cpu_count() or 1
    disk = shutil.disk_usage(root)
    checks: list[dict[str, Any]] = []

    py_ok = sys.version_info >= (3, 10)
    checks.append(_check(
        "python", "ready" if py_ok else "blocked",
        platform.python_version(),
        None if py_ok else "Install Python 3.10 or newer; do not use sudo to run Vortex.",
    ))

    node = _version("node")
    npm = _version("npm")
    checks.append(_check("node", "ready" if node else "missing", node or "Node.js is not installed.", "Install Node.js 22.12+ before building the React UI." if not node else None))
    checks.append(_check("npm", "ready" if npm else "missing", npm or "npm is not installed.", "Install npm with Node.js, then run npm ci." if not npm else None))

    vite = (root / "node_modules" / "vite" / "bin" / "vite.js").is_file()
    dist = (root / "dist" / "index.html").is_file()
    checks.append(_check("javascript_dependencies", "ready" if vite else "missing", "Vite is installed." if vite else "node_modules/vite is missing.", None if vite else "Run npm ci from the repository root."))
    checks.append(_check("react_bundle", "ready" if dist else "missing", str(root / "dist" / "index.html") if dist else "No production React bundle found.", None if dist else "Run npm run build after npm ci."))

    ollama = _version("ollama", ("--version",))
    checks.append(_check("ollama", "optional_ready" if ollama else "optional_missing", ollama or "Ollama is not installed; deterministic and non-model features remain available.", "Install Ollama and pull a reviewed local model only if local AI is wanted." if not ollama else None))

    minimum_ram = total_mb is not None and total_mb >= 2048
    minimum_cpu = cpu_count >= 2
    checks.append(_check("memory", "ready" if minimum_ram else "warning", f"{total_mb or 'unknown'} MiB total; {available_mb or 'unknown'} MiB available", "Use the low-memory profile and close other applications before building." if not minimum_ram else None))
    checks.append(_check("cpu", "ready" if minimum_cpu else "warning", f"{cpu_count} logical CPU(s); frequency is reported by the kernel and is not used as a safety gate", "A 2+ core host is recommended for the desktop build." if not minimum_cpu else None))
    checks.append(_check("disk", "ready" if disk.free >= 512 * 1024 * 1024 else "warning", f"{disk.free // (1024 * 1024)} MiB free at {root}", "Free at least 512 MiB before building or packaging." if disk.free < 512 * 1024 * 1024 else None))

    blocking = [item["name"] for item in checks if item["state"] in {"missing", "blocked"} and item["name"] in {"python", "node", "npm", "javascript_dependencies"}]
    build_ready = not blocking and vite
    return {
        "schema_version": 1,
        "root": str(root),
        "platform": {"system": platform.system(), "release": platform.release(), "architecture": platform.machine()},
        "hardware": {"ram_total_mb": total_mb, "ram_available_mb": available_mb, "logical_cpus": cpu_count, "disk_free_bytes": disk.free},
        "checks": checks,
        "profile": "low-memory" if total_mb is not None and total_mb <= 4096 else "standard",
        "build_ready": build_ready,
        "ready": not blocking,
        "next": "Run npm ci, then npm run build." if not build_ready else "Run npm start or vortex serve.",
    }
