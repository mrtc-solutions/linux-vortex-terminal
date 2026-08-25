#!/usr/bin/env python3
"""Linux Vortex local sidecar.

The sidecar is deliberately dependency-light: the checked-in implementation uses
Python's standard library so a fresh Ubuntu installation can boot the product
before optional FastAPI/Electron packaging is installed.  It owns all command
execution; the renderer is never allowed to spawn a process.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import queue
import re
import secrets
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
APP_VERSION = "0.1.0"
REDACTION_RE = re.compile(
    r"(?i)(bearer\s+|password\s*[=:]\s*|token\s*[=:]\s*|api[_-]?key\s*[=:]\s*|secret\s*[=:]\s*)([^\s,;]+)"
)
ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-_])")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service$")
PACKAGE_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?$")
HOST_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")

EXIT_CODES = {
    "success": 0,
    "failure": 1,
    "invalid_usage": 2,
    "unavailable": 3,
    "policy_denied": 4,
    "confirmation_required": 5,
    "command_failed": 6,
    "interrupted": 7,
    "timeout": 8,
    "integrity_failure": 9,
    "incompatible_state": 10,
}

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
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sanitize(text: str) -> str:
    """Make terminal output safe for display and storage."""
    text = ANSI_RE.sub("", text)
    text = CONTROL_RE.sub("", text)
    return text.replace("\r", "")


def redact(text: str) -> str:
    text = sanitize(text)
    return REDACTION_RE.sub(lambda m: m.group(1) + "[REDACTED]", text)


def safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def xdg_dir(env_name: str, fallback: Path) -> Path:
    raw = os.environ.get(env_name)
    return Path(raw).expanduser() if raw else fallback


def data_root() -> Path:
    override = os.environ.get("VORTEX_DATA_DIR")
    root = Path(override).expanduser() if override else xdg_dir("XDG_DATA_HOME", Path.home() / ".local" / "share") / "vortex"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def config_root() -> Path:
    root = xdg_dir("XDG_CONFIG_HOME", Path.home() / ".config") / "vortex"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def secure_path(path: Path) -> Path:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def read_os_release() -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                result[key] = value.strip().strip('"')
    except OSError:
        pass
    return result


def probe_executable(name: str) -> dict[str, Any]:
    found = shutil.which(name)
    if not found:
        return {"name": name, "state": "absent", "path": None, "version": None}
    path = Path(found)
    try:
        real = path.resolve(strict=True)
        st = real.stat()
        mode = stat.S_IMODE(st.st_mode)
        security_flags: list[str] = []
        if mode & 0o022:
            security_flags.append("writable-by-group-or-other")
        if st.st_mode & (stat.S_ISUID | stat.S_ISGID):
            security_flags.append("setuid-or-setgid")
        sha = hashlib.sha256()
        with real.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                sha.update(chunk)
        item = {
            "name": name,
            "state": "blocked" if security_flags else "installed",
            "path": str(real),
            "realpath": str(real),
            "device": st.st_dev,
            "inode": st.st_ino,
            "owner_uid": st.st_uid,
            "mode": oct(mode),
            "size": st.st_size,
            "sha256": sha.hexdigest(),
            "security_flags": security_flags,
            "version": None,
        }
        spec = TOOL_CATALOG.get(name)
        if spec:
            try:
                env = minimal_env(False)
                proc = subprocess.run([str(real), *spec["probe"]], capture_output=True, text=True, timeout=2, env=env)
                version_line = (proc.stdout or proc.stderr).splitlines()
                item["version"] = version_line[0][:180] if version_line else "version-unknown"
            except (OSError, subprocess.SubprocessError):
                item["version"] = "version-unknown"
        return item
    except OSError as exc:
        return {"name": name, "state": "blocked", "path": str(path), "error": str(exc), "version": None}


def minimal_env(tty: bool, additions: dict[str, str] | None = None) -> dict[str, str]:
    allowed = {"HOME", "USER", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "LC_NUMERIC", "LC_TIME", "PATH"}
    if tty:
        allowed.add("TERM")
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    if additions:
        for key, value in additions.items():
            if re.fullmatch(r"[A-Z_][A-Z0-9_]{0,63}", key) and "=" not in value and "\x00" not in value:
                env[key] = value
    return env


def detect_context() -> dict[str, Any]:
    os_release = read_os_release()
    cgroup = "unknown"
    try:
        cgroup = "v2" if "0::/" in Path("/proc/self/cgroup").read_text() else "v1"
    except OSError:
        pass
    container = False
    try:
        marker = Path("/run/systemd/container").read_text().strip()
        container = bool(marker)
    except OSError:
        try:
            container = any(x in Path("/proc/1/cgroup").read_text(errors="ignore").lower() for x in ("docker", "containerd", "kubepods", "lxc"))
        except OSError:
            pass
    systemd = bool(shutil.which("systemctl")) and Path("/run/systemd/system").exists()
    kernel_text = os.uname().release.lower()
    wsl = bool(os.environ.get("WSL_INTEROP")) or "microsoft" in kernel_text
    distro_id = os_release.get("ID", "unknown")
    if distro_id == "ubuntu" and os_release.get("VERSION_ID", "") == "24.04":
        tier = "tier-1"
    elif distro_id == "ubuntu" or distro_id == "debian":
        tier = "tier-2"
    elif distro_id in {"linuxmint", "pop", "kali"}:
        tier = "tier-3"
    else:
        tier = "deferred"
    return {
        "distribution": {"id": distro_id, "version_id": os_release.get("VERSION_ID", "unknown"), "pretty_name": os_release.get("PRETTY_NAME", distro_id)},
        "support_tier": tier,
        "kernel": os.uname().release,
        "architecture": os.uname().machine,
        "uid": os.getuid(),
        "root": os.getuid() == 0,
        "cwd": str(Path.cwd()),
        "shell": os.environ.get("SHELL", "unknown"),
        "tty": {"stdin": os.isatty(0), "stdout": os.isatty(1), "stderr": os.isatty(2)},
        "ssh": bool(os.environ.get("SSH_CONNECTION")),
        "ssh_tty": bool(os.environ.get("SSH_TTY")),
        "tmux": bool(os.environ.get("TMUX")),
        "container": container,
        "wsl": wsl,
        "virtualization": "container" if container else ("wsl" if wsl else "unknown"),
        "screen": bool(os.environ.get("STY")),
        "confinement": {"flatpak": bool(os.environ.get("FLATPAK_ID")), "snap": bool(os.environ.get("SNAP"))},
        "pid1": shutil.which("ps") and _pid1_name(),
        "systemd": systemd,
        "cgroup": cgroup,
        "package_manager": {name: probe_executable(name)["state"] for name in ("apt-get", "apt-cache", "dpkg-query", "sudo")},
        "model": {"state": "disabled by default", "endpoint": None},
    }


def _pid1_name() -> str:
    try:
        return Path("/proc/1/comm").read_text().strip()
    except OSError:
        return "unknown"


def validate_cwd(raw: str | None) -> Path:
    candidate = Path(raw or os.getcwd()).expanduser()
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("working directory is not a directory")
    return resolved


def quote_argv(argv: list[str]) -> str:
    import shlex
    return " ".join(shlex.quote(x) for x in argv)


class Store:
    def __init__(self, path: Path | None = None):
        self.root = data_root()
        self.db_path = path or (self.root / "vortex.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self._init_db()
        try:
            self.db_path.chmod(0o600)
        except OSError:
            pass

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                request TEXT NOT NULL, cwd TEXT NOT NULL, status TEXT NOT NULL,
                risk TEXT NOT NULL, digest TEXT NOT NULL, plan_json TEXT NOT NULL,
                engagement_id TEXT, approval_token TEXT, creator_uid INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, started_at TEXT,
                ended_at TEXT, status TEXT NOT NULL, result_json TEXT NOT NULL,
                FOREIGN KEY(plan_id) REFERENCES plans(id)
            );
            CREATE TABLE IF NOT EXISTS engagements (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                name TEXT NOT NULL, authorization TEXT NOT NULL, targets_json TEXT NOT NULL,
                classes_json TEXT NOT NULL, status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
                at TEXT NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY, operation_id TEXT, rating INTEGER, correction TEXT,
                created_at TEXT NOT NULL
            );
            INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '1');
            """)

    def append_audit(self, event_type: str, payload: dict[str, Any]) -> str:
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            last = db.execute("SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1").fetchone()
            previous = last[0] if last else "0" * 64
            event_id = secrets.token_hex(16)
            at = now_iso()
            body = {"event_id": event_id, "at": at, "event_type": event_type, "payload": payload, "previous_hash": previous}
            event_hash = hashlib.sha256((previous + canonical(body)).encode()).hexdigest()
            db.execute("INSERT INTO audit_events(event_id, at, event_type, payload_json, previous_hash, event_hash) VALUES (?,?,?,?,?,?)", (event_id, at, event_type, canonical(payload), previous, event_hash))
            db.execute("COMMIT")
            return event_id

    def verify_audit(self) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
        previous = "0" * 64
        for row in rows:
            payload = json.loads(row["payload_json"])
            body = {"event_id": row["event_id"], "at": row["at"], "event_type": row["event_type"], "payload": payload, "previous_hash": previous}
            expected = hashlib.sha256((previous + canonical(body)).encode()).hexdigest()
            if row["previous_hash"] != previous or row["event_hash"] != expected:
                return {"valid": False, "checked": row["sequence"], "error": "audit hash mismatch"}
            previous = row["event_hash"]
        return {"valid": True, "checked": len(rows), "head": previous}

    def save_plan(self, plan: dict[str, Any]) -> None:
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO plans VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (plan["id"], plan["created_at"], plan["expires_at"], plan["request"], plan["cwd"], plan["status"], plan["risk"], plan["digest"], canonical(plan), plan.get("engagement_id"), plan["approval_token"], os.getuid()))
        self.append_audit("plan_created", {"plan_id": plan["id"], "digest": plan["digest"], "status": plan["status"]})

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT plan_json FROM plans WHERE id=?", (plan_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def claim_plan(self, plan_id: str) -> tuple[bool, str]:
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM plans WHERE id=?", (plan_id,)).fetchone()
            if not row:
                db.execute("ROLLBACK")
                return False, "not_found"
            if row[0] not in ("planned", "approved"):
                db.execute("ROLLBACK")
                return False, "already_started"
            db.execute("UPDATE plans SET status='approved' WHERE id=?", (plan_id,))
            db.execute("COMMIT")
            return True, "claimed"

    def save_operation(self, operation: dict[str, Any]) -> None:
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO operations VALUES (?,?,?,?,?,?)", (operation["id"], operation["plan_id"], operation.get("started_at"), operation.get("ended_at"), operation["status"], canonical(operation),))

    def update_operation(self, operation: dict[str, Any]) -> None:
        with self.lock, self.connect() as db:
            db.execute("UPDATE operations SET started_at=?, ended_at=?, status=?, result_json=? WHERE id=?", (operation.get("started_at"), operation.get("ended_at"), operation["status"], canonical(operation), operation["id"]))

    def get_operation(self, op_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT result_json FROM operations WHERE id=?", (op_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT result_json FROM operations ORDER BY COALESCE(ended_at, started_at) DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def create_engagement(self, item: dict[str, Any]) -> None:
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO engagements VALUES (?,?,?,?,?,?,?,?)", (item["id"], item["created_at"], item["expires_at"], item["name"], item["authorization"], canonical(item["targets"]), canonical(item["classes"]), item["status"]))
        self.append_audit("engagement_created", {"engagement_id": item["id"], "targets": item["targets"]})

    def list_engagements(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM engagements ORDER BY created_at DESC").fetchall()
        return [{"id": r["id"], "created_at": r["created_at"], "expires_at": r["expires_at"], "name": r["name"], "authorization": r["authorization"], "targets": json.loads(r["targets_json"]), "classes": json.loads(r["classes_json"]), "status": r["status"]} for r in rows]

    def get_engagement(self, engagement_id: str) -> dict[str, Any] | None:
        return next((x for x in self.list_engagements() if x["id"] == engagement_id), None)


class PolicyError(ValueError):
    pass


def normalize_target(raw: str) -> str:
    value = raw.strip()
    if not value or any(c in value for c in "\x00\n\r;|&`$()<>\\"):
        raise PolicyError("target contains unsafe characters")
    if value.lower().startswith(("http://", "https://")):
        value = value.lower()
        parsed = urllib.parse.urlparse(value)
        if parsed.hostname is None or parsed.username or parsed.password or parsed.fragment:
            raise PolicyError("URL must have a host and no credentials or fragment")
        if parsed.path == "":
            value += "/"
        return value
    if "/" in value and not value.startswith(("http://", "https://")):
        # bounded CIDR notation, not arbitrary path input
        host, _, prefix = value.partition("/")
        if not prefix.isdigit() or int(prefix) < 0 or int(prefix) > 128:
            raise PolicyError("invalid CIDR target")
        value = f"{host}/{int(prefix)}"
    if not (HOST_RE.fullmatch(value) or re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", value) or re.fullmatch(r"[0-9a-fA-F:]+", value)):
        raise PolicyError("target is not a hostname, IP, or URL")
    return value.lower()


def target_in_engagement(target: str, engagement: dict[str, Any]) -> bool:
    normalized = normalize_target(target)
    for allowed in engagement["targets"]:
        allowed_n = normalize_target(str(allowed))
        if normalized == allowed_n:
            return True
        # A declared bare domain authorizes subdomains, but not an unrelated suffix.
        if not normalized.startswith(("http://", "https://")) and normalized.endswith("." + allowed_n):
            return True
        if normalized.startswith(("http://", "https://")) and urllib.parse.urlparse(normalized).hostname == urllib.parse.urlparse(allowed_n).hostname:
            return True
    return False


def command_spec(executable: str, argv: list[str], cwd: Path, *, risk: str = "low", network: str = "no-network", required: str | None = None, scope: list[str] | None = None, explanation: str = "", timeout: int = 30) -> dict[str, Any]:
    if not argv or argv[0] != executable or any("\x00" in arg for arg in argv):
        raise PolicyError("invalid argv")
    if any(token in arg for arg in argv for token in (";", "&&", "||", "|", ">", "<", "`", "$(")):
        raise PolicyError("shell metacharacters are not permitted in managed argv")
    identity = probe_executable(executable)
    if identity["state"] == "absent":
        state = "unavailable"
    elif identity["state"] == "blocked":
        state = "blocked"
    else:
        state = "ready"
    return {
        "executable": executable,
        "argv": argv,
        "display": quote_argv(argv),
        "cwd": str(cwd),
        "env_additions": {},
        "stdin_policy": "closed",
        "timeout_seconds": timeout,
        "output_cap_bytes": 512 * 1024,
        "risk": risk,
        "network_class": network,
        "required_tool": required or executable,
        "tool_state_at_plan": state,
        "executable_identity": identity,
        "scope": scope or [],
        "explanation": explanation,
        "evidence": "redacted stdout/stderr and exit status",
    }


def parse_service(text: str) -> str | None:
    match = re.search(r"(?:service|unit)\s+([A-Za-z0-9][A-Za-z0-9_.@:-]*\.service)", text, re.I)
    return match.group(1) if match else None


def build_plan(store: Store, request: str, cwd_raw: str | None = None, engagement_id: str | None = None) -> dict[str, Any]:
    request = (request or "").strip()
    if not request:
        raise ValueError("request is required")
    cwd = validate_cwd(cwd_raw)
    lower = request.lower()
    specs: list[dict[str, Any]] = []
    notes: list[str] = []
    missing: list[str] = []
    kind = "plan"
    risk = "low"
    authorization = "local diagnostic capability"
    engagement = store.get_engagement(engagement_id) if engagement_id else None

    if lower.startswith("explain ") or lower.startswith("what does ") or lower.startswith("why does "):
        kind = "explanation"
        command = request.split(" ", 1)[1] if " " in request else ""
        try:
            import shlex
            argv = shlex.split(command)
        except ValueError:
            argv = []
        if not argv or any(x in command for x in (";", "&&", "||", "|", ">", "<")):
            notes.append("This request contains shell syntax or is incomplete; Vortex will explain concepts without executing it.")
        else:
            notes.append(f"{argv[0]} would be invoked with {len(argv) - 1} argument(s). No command will be executed by ask or plan.")
        status = "clarified"
    elif any(word in lower for word in ("nmap", "nuclei", "ffuf", "nikto", "amass", "enumerate the web", "scan ")):
        kind = "authorized_engagement"
        risk = "high"
        authorization = "active engagement required"
        tool = next((name for name in ("nmap", "nuclei", "ffuf", "nikto", "amass") if name in lower), "nmap")
        targets = re.findall(r"https?://[^\s,]+|\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b|\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b", request)
        if not engagement:
            status = "clarified"
            notes += ["Active cybersecurity work requires an engagement before a target or network tool can run.", "Create an engagement with an owner/authorization reference, canonical targets, limits, and an expiry."]
        elif not targets:
            status = "clarified"
            notes.append("Tell Vortex the exact authorized hostname, URL, IP, or CIDR target.")
        else:
            try:
                normalized = [normalize_target(t.rstrip(".,")) for t in targets]
            except PolicyError as exc:
                raise PolicyError(str(exc)) from exc
            out_scope = [target for target in normalized if not target_in_engagement(target, engagement)]
            if out_scope:
                status = "rejected"
                notes.append("Target is outside the active engagement scope: " + ", ".join(out_scope))
            elif probe_executable(tool)["state"] != "installed":
                status = "unavailable"
                missing.append(tool)
                notes.append(f"TOOL MISSING: {tool}. The host probe found no executable; no scan output exists.")
            else:
                if tool == "nmap":
                    args = ["nmap", "-sV", "--version-light", "--max-retries", "2", "-T2", "-oX", str(store.root / ("evidence-" + secrets.token_hex(8) + ".xml")), normalized[0]]
                elif tool == "curl":
                    args = ["curl", "--fail", "--silent", "--show-error", "--location", "--max-time", "15", normalized[0]]
                else:
                    args = [tool, normalized[0]]
                specs.append(command_spec(tool, args, cwd, risk=risk, network="outbound-read", required=tool, scope=normalized, explanation=f"Run the installed {tool} adapter with conservative limits against the approved target."))
                status = "planned"
                notes += ["This is active authorized assessment, not a generic shell command.", "DNS, redirects, resolved addresses, limits, and engagement expiry must be checked again at execution."]
    elif any(word in lower for word in ("port", "listen", "socket")):
        if probe_executable("ss")["state"] != "installed":
            status = "unavailable"; missing.append("ss"); notes.append("TOOL MISSING: ss. Install instructions may be shown separately; no socket facts were observed.")
        else:
            specs.append(command_spec("ss", ["ss", "-lntup"], cwd, required="ss", explanation="List listening TCP and UDP sockets; process details may require elevated permissions."))
            status = "planned"; notes += ["Read-only local socket inspection.", "The command reports observed sockets only; it does not establish that a service is secure."]
    elif parse_service(lower):
        unit = parse_service(lower)
        assert unit is not None
        if not probe_executable("systemctl")["state"] == "installed" or not detect_context()["systemd"]:
            status = "unavailable"; missing.append("systemd"); notes.append("Systemd is not usable in this context; no service command was run.")
        else:
            specs.extend([
                command_spec("systemctl", ["systemctl", "show", unit, "--property=Id,Description,ActiveState,SubState,UnitFileState", "--no-pager"], cwd, required="systemctl", explanation=f"Read the factual state and persistence of {unit}."),
                command_spec("journalctl", ["journalctl", "-u", unit, "-n", "80", "--no-pager", "--output=short-iso"], cwd, required="journalctl", explanation=f"Read the last bounded journal lines for {unit}; no service mutation is requested."),
            ])
            status = "planned"; notes.append("Read-only systemd and journal inspection. Restart/enable/disable require a separate fresh plan and confirmation.")
    elif any(word in lower for word in ("git status", "repository status", "git hygiene", "check my repo")):
        if probe_executable("git")["state"] != "installed":
            status = "unavailable"; missing.append("git"); notes.append("TOOL MISSING: git; no repository state was observed.")
        else:
            specs.append(command_spec("git", ["git", "status", "--short", "--branch"], cwd, required="git", explanation="Show the current branch and working-tree changes without modifying the repository."))
            status = "planned"; notes.append("Read-only Git status; no hooks, checkout, reset, clean, push, or network operation is included.")
    elif any(word in lower for word in ("disk", "space", "large file", "cache")):
        specs.append(command_spec("df", ["df", "-h", str(cwd)], cwd, required="df", explanation="Show human-readable filesystem capacity for the current scope."))
        specs.append(command_spec("du", ["du", "-x", "-h", "-d", "1", str(cwd)], cwd, required="du", explanation="Measure immediate directory usage on the same filesystem; it does not delete anything."))
        status = "planned" if all(x["tool_state_at_plan"] == "ready" for x in specs) else "unavailable"
        if status == "unavailable":
            missing = [x["required_tool"] for x in specs if x["tool_state_at_plan"] != "ready"]
        notes += ["Read-only disk inspection. Cleanup is not bundled into a discovery plan.", "No files are removed or moved by these commands."]
    elif any(word in lower for word in ("system", "health", "cpu", "memory", "ram", "diagnos")):
        for executable, argv, explanation in [
            ("uname", ["uname", "-a"], "Identify the running kernel and architecture."),
            ("uptime", ["uptime"], "Report observed uptime and load averages."),
            ("free", ["free", "-h"], "Report memory and swap counters from the host."),
            ("df", ["df", "-h", str(cwd)], "Report filesystem capacity for the current working directory."),
        ]:
            if probe_executable(executable)["state"] == "installed":
                specs.append(command_spec(executable, argv, cwd, required=executable, explanation=explanation))
            else:
                missing.append(executable)
        status = "planned" if specs else "unavailable"
        notes += ["Deterministic local diagnostic mode is active; no model or network is required.", "Facts are probed only after approval and will be labelled observed in the analysis."]
    else:
        kind = "abstain"
        status = "clarified"
        notes += ["Vortex does not have a reviewed adapter for this request yet.", "Try system health, disk usage, listening ports, Git status, a service status query, or create an authorized engagement for supported reconnaissance."]

    created = now_iso()
    expires = datetime.fromtimestamp(time.time() + 15 * 60, tz=timezone.utc).isoformat(timespec="milliseconds")
    plan = {
        "schema_version": SCHEMA_VERSION,
        "id": secrets.token_hex(32),
        "created_at": created,
        "expires_at": expires,
        "request": request,
        "cwd": str(cwd),
        "status": status,
        "kind": kind,
        "risk": risk,
        "authorization": authorization,
        "commands": specs,
        "notes": notes,
        "missing_tools": sorted(set(missing)),
        "scope": {"cwd": str(cwd), "engagement_id": engagement_id, "targets": specs[0].get("scope", []) if specs else []},
        "workers": [{"id": "vortex-deterministic-planner", "state": "responded", "evidence_used": bool(specs), "role": "reviewed local adapter"}, {"id": "local-model", "state": "disabled", "evidence_used": False, "role": "advisory only"}],
        "approval_required": bool(specs),
        "approval_phrase": "APPROVE " + (specs[0]["display"] if specs else "NO EXECUTION"),
        "source": "deterministic",
        "policy_version": "safe-v1",
        "knowledge_version": "builtin-v1",
    }
    plan["digest"] = digest({"commands": plan["commands"], "cwd": plan["cwd"], "scope": plan["scope"], "policy_version": plan["policy_version"], "expires_at": plan["expires_at"]})
    plan["approval_token"] = secrets.token_urlsafe(32)
    store.save_plan(plan)
    return plan


class ExecutionManager:
    def __init__(self, store: Store):
        self.store = store
        self.threads: dict[str, threading.Thread] = {}
        self.lock = threading.Lock()

    def start(self, plan: dict[str, Any], confirm: bool, approval_token: str | None = None, allow_root: bool = False) -> dict[str, Any]:
        if not confirm:
            raise PermissionError("confirmation required")
        if plan["status"] != "planned":
            raise PolicyError("plan is not executable in its current state")
        if time.time() > datetime.fromisoformat(plan["expires_at"]).timestamp():
            raise TimeoutError("plan expired")
        if approval_token is not None and not secrets.compare_digest(approval_token, plan["approval_token"]):
            raise PolicyError("approval token does not match this plan")
        if os.getuid() == 0 and not allow_root:
            raise PermissionError("refusing UID 0 execution without an explicit root override")
        for spec in plan["commands"]:
            current = probe_executable(spec["executable"])
            if current.get("state") != "installed" or current.get("sha256") != spec["executable_identity"].get("sha256") or current.get("device") != spec["executable_identity"].get("device") or current.get("inode") != spec["executable_identity"].get("inode"):
                raise PolicyError(f"executable identity changed for {spec['executable']}; reprobe and reapprove")
        claimed, reason = self.store.claim_plan(plan["id"])
        if not claimed:
            raise PolicyError(reason)
        op = {"schema_version": SCHEMA_VERSION, "id": secrets.token_hex(16), "plan_id": plan["id"], "status": "started", "started_at": now_iso(), "ended_at": None, "commands": [], "workers": plan["workers"], "source": plan["source"], "output_digest": None, "analysis": None}
        self.store.save_operation(op)
        self.store.append_audit("operation_started", {"operation_id": op["id"], "plan_id": plan["id"], "digest": plan["digest"], "privilege": "root-override" if allow_root else "user"})
        thread = threading.Thread(target=self._run, args=(plan, op), daemon=True)
        with self.lock:
            self.threads[op["id"]] = thread
        thread.start()
        return op

    def _run_one(self, spec: dict[str, Any]) -> dict[str, Any]:
        started = now_iso(); started_mono = time.monotonic()
        argv = list(spec["argv"])
        record: dict[str, Any] = {"argv": argv, "display": spec["display"], "executable": spec["executable"], "cwd": spec["cwd"], "started_at": started, "stdout": "", "stderr": "", "exit_code": None, "signal": None, "termination_reason": None, "status": "running", "version": spec["executable_identity"].get("version"), "evidence_digest": None}
        try:
            proc = subprocess.Popen(argv, cwd=spec["cwd"], env=minimal_env(False, spec.get("env_additions")), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, start_new_session=True, close_fds=True)
        except FileNotFoundError:
            record.update(status="unavailable", termination_reason="tool_missing", ended_at=now_iso())
            return record
        except OSError as exc:
            record.update(status="failed", termination_reason=redact(str(exc)), ended_at=now_iso())
            return record
        chunks: queue.Queue[tuple[str, bytes]] = queue.Queue()
        def reader(stream: Any, label: str) -> None:
            try:
                for chunk in iter(stream.readline, b""):
                    chunks.put((label, chunk))
            finally:
                stream.close()
        threads = [threading.Thread(target=reader, args=(proc.stdout, "stdout"), daemon=True), threading.Thread(target=reader, args=(proc.stderr, "stderr"), daemon=True)]
        for t in threads: t.start()
        total = 0; truncated = False
        while proc.poll() is None or any(t.is_alive() for t in threads) or not chunks.empty():
            try:
                label, raw = chunks.get(timeout=0.05)
            except queue.Empty:
                label = ""; raw = b""
            if raw:
                total += len(raw)
                if total <= spec["output_cap_bytes"]:
                    text = raw.decode("utf-8", errors="replace")
                    record[label] += redact(text)
                else:
                    truncated = True
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    break
            if time.monotonic() - started_mono > spec["timeout_seconds"]:
                record["termination_reason"] = "timeout"
                try: os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                time.sleep(0.2)
                if proc.poll() is None:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                break
        if proc.poll() is None:
            try: proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try: os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                proc.wait()
        for t in threads: t.join(timeout=1)
        record["exit_code"] = proc.returncode if proc.returncode is not None and proc.returncode >= 0 else None
        record["signal"] = -proc.returncode if proc.returncode is not None and proc.returncode < 0 else None
        record["ended_at"] = now_iso()
        if truncated:
            record["status"] = "timed_out"; record["termination_reason"] = "output_truncated"
        elif record["termination_reason"] == "timeout":
            record["status"] = "timed_out"
        elif record["signal"] in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            record["status"] = "interrupted"; record["termination_reason"] = "signal"
        elif record["exit_code"] == 0:
            record["status"] = "succeeded"; record["termination_reason"] = "completed"
        else:
            record["status"] = "failed"; record["termination_reason"] = "non_zero_exit"
        record["duration_ms"] = int((time.monotonic() - started_mono) * 1000)
        record["evidence_digest"] = hashlib.sha256((record["stdout"] + "\n" + record["stderr"]).encode()).hexdigest()
        return record

    def _run(self, plan: dict[str, Any], op: dict[str, Any]) -> None:
        try:
            op["status"] = "running"; self.store.update_operation(op)
            for spec in plan["commands"]:
                result = self._run_one(spec)
                op["commands"].append(result)
                self.store.update_operation(op)
                if result["status"] != "succeeded":
                    break
            statuses = [x["status"] for x in op["commands"]]
            if any(s == "timed_out" for s in statuses): op["status"] = "timed_out"
            elif any(s == "interrupted" for s in statuses): op["status"] = "interrupted"
            elif any(s == "unavailable" for s in statuses): op["status"] = "unavailable"
            elif all(s == "succeeded" for s in statuses) and statuses: op["status"] = "succeeded"
            else: op["status"] = "failed"
        except Exception as exc:
            op["status"] = "unknown_after_crash"; op["error"] = redact(str(exc))
        op["ended_at"] = now_iso()
        op["output_digest"] = hashlib.sha256(canonical(op["commands"]).encode()).hexdigest()
        op["analysis"] = make_analysis(plan, op)
        self.store.update_operation(op)
        self.store.append_audit("operation_finished", {"operation_id": op["id"], "plan_id": plan["id"], "status": op["status"], "output_digest": op["output_digest"]})


def make_analysis(plan: dict[str, Any], op: dict[str, Any]) -> dict[str, Any]:
    facts = []
    for command in op["commands"]:
        lines = [line for line in (command.get("stdout", "") + command.get("stderr", "")).splitlines() if line.strip()]
        facts.append({"command": command["display"], "status": command["status"], "observed_lines": len(lines), "evidence_digest": command.get("evidence_digest"), "summary": (lines[0][:220] if lines else "No output was observed; this is not evidence of a clean result.")})
    return {
        "lifecycle": {"succeeded": "EXECUTED", "failed": "FAILED", "interrupted": "INTERRUPTED", "timed_out": "TIMED OUT", "unavailable": "TOOL MISSING", "unknown_after_crash": "BACKEND OFFLINE"}.get(op["status"], "NOT RUN"),
        "fact": f"{len(op['commands'])} real command(s) reached an observed terminal outcome." if op["commands"] else "No command was run.",
        "inference": "Output summaries are bounded and redacted. They are observations, not a security guarantee.",
        "unknown": "Parser confidence is limited because this vertical slice stores raw text evidence; no vulnerability is confirmed without a reviewed parser and matching rule.",
        "commands": facts,
        "next_steps": [{"label": "explain", "text": "Review the observed command timeline and evidence digests."}, {"label": "plan only", "text": "Ask a new question for a narrower, reviewed follow-up."}],
        "workers": op["workers"],
    }


class VortexHandler(BaseHTTPRequestHandler):
    store: Store
    executor: ExecutionManager
    frontend: Path
    token: str | None = None
    server_version = "VortexSidecar/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Do not log request bodies, prompts, or credentials.
        sys.stderr.write("[vortex-sidecar] " + (fmt % args) + "\n")

    def _authorized(self) -> bool:
        if not self.token:
            return True
        return secrets.compare_digest(self.headers.get("X-Vortex-Token", ""), self.token)

    def _headers(self, content_type: str = "application/json") -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Vortex-Token")

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        raw = (canonical({"schema_version": SCHEMA_VERSION, **payload}) + "\n").encode()
        self.send_response(code); self._headers(); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 256 * 1024: raise ValueError("request too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT); self._headers(); self.end_headers()

    def do_GET(self) -> None:
        if not self._authorized(): return self._json(HTTPStatus.UNAUTHORIZED, {"error": {"code": "unauthorized", "message": "invalid sidecar capability"}})
        parsed = urllib.parse.urlparse(self.path); path = parsed.path
        try:
            if path == "/api/health": return self._json(200, {"ok": True, "version": APP_VERSION, "backend": "online"})
            if path == "/api/doctor": return self._json(200, {"doctor": detect_context()})
            if path == "/api/tools": return self._json(200, {"tools": [probe_executable(name) | {"family": meta["family"], "role": meta["role"]} for name, meta in TOOL_CATALOG.items()]})
            if path == "/api/history": return self._json(200, {"history": self.store.list_history()})
            if path == "/api/engagements": return self._json(200, {"engagements": self.store.list_engagements()})
            if path == "/api/audit/verify": return self._json(200, {"audit": self.store.verify_audit()})
            if path.startswith("/api/plans/"):
                plan = self.store.get_plan(path.rsplit("/", 1)[-1]); return self._json(200 if plan else 404, {"plan": plan} if plan else {"error": {"code": "not_found", "message": "plan not found"}})
            if path.startswith("/api/operations/"):
                op = self.store.get_operation(path.rsplit("/", 1)[-1]); return self._json(200 if op else 404, {"operation": op} if op else {"error": {"code": "not_found", "message": "operation not found"}})
            if path == "/" or path == "/index.html":
                return self._static(self.frontend / "index.html", "text/html; charset=utf-8")
            if path.startswith("/assets/"):
                relative = Path(path.removeprefix("/assets/")).as_posix()
                # Renderer code lives beside index.html; licensed artwork lives
                # in the repository assets directory. Both remain read-only.
                asset = (self.frontend / relative).resolve()
                if not asset.is_file(): asset = (self.frontend.parent / "assets" / relative).resolve()
                allowed = (self.frontend.resolve(), (self.frontend.parent / "assets").resolve())
                mime = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}.get(asset.suffix, "application/octet-stream")
                if any(str(asset).startswith(str(root)) for root in allowed) and asset.is_file(): return self._static(asset, mime)
            return self._json(404, {"error": {"code": "not_found", "message": "route not found"}})
        except Exception as exc:
            return self._json(500, {"error": {"code": "internal_error", "message": redact(str(exc))}})

    def _static(self, path: Path, content_type: str) -> None:
        data = path.read_bytes(); self.send_response(200); self._headers(content_type); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_POST(self) -> None:
        if not self._authorized(): return self._json(HTTPStatus.UNAUTHORIZED, {"error": {"code": "unauthorized", "message": "invalid sidecar capability"}})
        path = urllib.parse.urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/plan":
                plan = build_plan(self.store, str(body.get("request", "")), body.get("cwd"), body.get("engagement_id")); return self._json(200, {"plan": plan})
            if path == "/api/execute":
                plan = self.store.get_plan(str(body.get("plan_id", "")))
                if not plan: return self._json(404, {"error": {"code": "not_found", "message": "plan not found"}})
                op = self.executor.start(plan, bool(body.get("confirm")), body.get("approval_token"), bool(body.get("allow_root", False))); return self._json(202, {"operation": op})
            if path == "/api/engagements":
                targets = [normalize_target(str(x)) for x in body.get("targets", [])]
                if not targets: raise PolicyError("at least one canonical target is required")
                expires = body.get("expires_at") or datetime.fromtimestamp(time.time() + 24 * 3600, tz=timezone.utc).isoformat(timespec="milliseconds")
                item = {"schema_version": SCHEMA_VERSION, "id": secrets.token_hex(16), "created_at": now_iso(), "expires_at": expires, "name": str(body.get("name") or "Authorized assessment"), "authorization": str(body.get("authorization") or "operator-declared authorization"), "targets": targets, "classes": body.get("classes") or ["reconnaissance"], "status": "active"}
                self.store.create_engagement(item); return self._json(201, {"engagement": item})
            if path == "/api/feedback":
                rating = int(body.get("rating", 0)); correction = redact(str(body.get("correction", "")))[:2000]
                self.store.append_audit("feedback_recorded", {"operation_id": body.get("operation_id"), "rating": max(1, min(5, rating)), "correction": correction}); return self._json(201, {"saved": True})
            return self._json(404, {"error": {"code": "not_found", "message": "route not found"}})
        except PermissionError as exc:
            return self._json(403, {"error": {"code": "confirmation_or_privilege", "message": str(exc), "exit_code": EXIT_CODES["confirmation_required"]}})
        except TimeoutError as exc:
            return self._json(409, {"error": {"code": "expired", "message": str(exc), "exit_code": EXIT_CODES["timeout"]}})
        except (ValueError, PolicyError, json.JSONDecodeError) as exc:
            return self._json(422, {"error": {"code": "invalid_plan", "message": redact(str(exc)), "exit_code": EXIT_CODES["policy_denied"]}})
        except Exception as exc:
            return self._json(500, {"error": {"code": "internal_error", "message": redact(str(exc))}})


def serve(host: str = "127.0.0.1", port: int = 8765, token: str | None = None) -> None:
    store = Store()
    handler = VortexHandler
    handler.store = store; handler.executor = ExecutionManager(store); handler.frontend = Path(__file__).resolve().parent.parent / "frontend"; handler.token = token
    server = ThreadingHTTPServer((host, port), handler)
    print(json.dumps({"backend": "online", "host": host, "port": server.server_port, "version": APP_VERSION}), flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vortex local Linux sidecar")
    parser.add_argument("--host", default=os.environ.get("VORTEX_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("VORTEX_PORT", "8765")))
    parser.add_argument("--token", default=os.environ.get("VORTEX_SIDECAR_TOKEN"))
    args = parser.parse_args()
    serve(args.host, args.port, args.token)
