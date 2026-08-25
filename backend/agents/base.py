"""Common adapter contract for external AI/security agents."""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from typing import Any


def _probe(name: str) -> dict[str, Any]:
    if not name or "\x00" in name:
        return {"state": "blocked", "path": None, "version": None}
    found = name if os.path.isabs(name) else shutil.which(name)
    if not found:
        return {"state": "absent", "path": None, "version": None}
    try:
        real = os.path.realpath(found)
        info = os.stat(real)
        if not stat.S_ISREG(info.st_mode) or not os.access(real, os.X_OK):
            return {"state": "blocked", "path": real, "version": None}
        sha = hashlib.sha256()
        with open(real, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                sha.update(chunk)
        version = None
        try:
            proc = subprocess.run([real, "--version"], capture_output=True, text=True, timeout=2, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
            line = (proc.stdout or proc.stderr).splitlines()
            version = (line[0][:160] if line else None)
        except (OSError, subprocess.SubprocessError, UnicodeError):
            version = None
        return {"state": "installed", "path": real, "version": version, "sha256": sha.hexdigest()}
    except OSError:
        return {"state": "blocked", "path": found, "version": None}


@dataclass
class AgentManifest:
    id: str
    name: str
    repository: str
    license: str
    binaries: tuple[str, ...]
    capabilities: tuple[str, ...]
    risk_level: str = "high"
    trust_level: str = "untrusted"
    notes: str = ""
    execution_mode: str = "advisory"


@dataclass
class AgentAdapter:
    manifest: AgentManifest
    extra: dict[str, Any] = field(default_factory=dict)

    def metadata(self) -> dict[str, Any]:
        health = self.health_check()
        return {
            "id": self.manifest.id,
            "name": self.manifest.name,
            "version": health.get("version") or None,
            "status": health.get("status"),
            "availability": health.get("availability"),
            "capabilities": list(self.manifest.capabilities),
            "supported_models": [],
            "execution_mode": self.manifest.execution_mode,
            "configuration": {"binaries": list(self.manifest.binaries), "repository": self.manifest.repository, "license": self.manifest.license},
            "health": health,
            "risk_level": self.manifest.risk_level,
            "trust_level": self.manifest.trust_level,
            "source": self.manifest.repository,
            "notes": self.manifest.notes,
        }

    def initialize(self) -> dict[str, Any]:
        return self.health_check()

    def health_check(self) -> dict[str, Any]:
        found = None
        identity = None
        for name in self.manifest.binaries:
            identity = _probe(name)
            if identity.get("state") == "installed":
                found = name
                break
        if not found or not identity:
            return {
                "status": "missing",
                "availability": "unavailable",
                "healthy": False,
                "version": None,
                "path": None,
                "message": f"{self.manifest.name} is not installed. Integration status: UNAVAILABLE / REQUIRES CONFIGURATION.",
            }
        return {
            "status": "installed",
            "availability": "installed",
            "healthy": True,
            "version": identity.get("version") or "version-unknown",
            "path": identity.get("path"),
            "sha256": identity.get("sha256"),
            "message": f"{self.manifest.name} executable was probed on this host. Advisory only; Guardian still authorizes every action.",
        }

    def capabilities(self) -> list[str]:
        return list(self.manifest.capabilities)

    def submit_task(self, task: dict[str, Any]) -> dict[str, Any]:
        health = self.health_check()
        if not health.get("healthy"):
            return {"agent": self.manifest.id, "state": "unavailable", "result": None, "message": health.get("message")}
        return {
            "agent": self.manifest.id,
            "state": "requires_configuration",
            "result": None,
            "message": (
                f"{self.manifest.name} is installed, but VORTEX will not invoke its interactive or model-backed "
                "workflow until a reviewed non-executing consult interface is configured. "
                "No agent output was fabricated."
            ),
            "task_id": task.get("id"),
        }

    def receive_result(self, handle: str) -> dict[str, Any]:
        return {"agent": self.manifest.id, "state": "not_run", "handle": handle}

    def stop_task(self, handle: str) -> dict[str, Any]:
        return {"agent": self.manifest.id, "state": "idle", "handle": handle}

    def cleanup(self) -> None:
        return None
