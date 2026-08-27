#!/usr/bin/env python3
"""Linux Vortex local sidecar.

The sidecar is deliberately dependency-light: the checked-in implementation uses
Python's standard library so a fresh Linux installation can boot the product
before optional FastAPI/Electron packaging is installed.  It owns all command
execution; the renderer is never allowed to spawn a process.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import ipaddress
import json
import os
import pwd
import pty
import queue
import re
import secrets
import shutil
import signal
import sqlite3
import stat
import struct
import subprocess
import sys
import termios
import threading
import time
import urllib.parse
from collections import deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _load(name: str):
    try:
        return __import__(name, fromlist=["*"])
    except ImportError:
        return __import__("backend." + name, fromlist=["*"])

try:
    from .adapter_registry import ADAPTER_MANIFESTS, TOOL_CATALOG
    from .artifacts import ArtifactError, analyze_operation_http, analyze_path
    from .facts import parse_container_logs, parse_package_facts, parse_ssh_connection, parse_systemd_facts
    from .network import resolve_targets, resolution_digest
except ImportError:  # direct `python backend/vortex_backend.py`
    from adapter_registry import ADAPTER_MANIFESTS, TOOL_CATALOG
    from artifacts import ArtifactError, analyze_operation_http, analyze_path
    from facts import parse_container_logs, parse_package_facts, parse_ssh_connection, parse_systemd_facts
    from network import resolve_targets, resolution_digest

SCHEMA_VERSION = 1
APP_VERSION = "0.2.0"
REDACTION_RE = re.compile(
    r"(?i)(bearer\s+|password\s*[=:]\s*|token\s*[=:]\s*|api[_-]?key\s*[=:]\s*|secret\s*[=:]\s*)([^\s,;]+)"
)
ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-_])")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
BIDI_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
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

CONTROLLED_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

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
    text = BIDI_RE.sub("[BIDI]", text)
    return text.replace("\r", "")


def redact(text: str) -> str:
    text = sanitize(text)
    return REDACTION_RE.sub(lambda m: m.group(1) + "[REDACTED]", text)


def sanitize_pty(text: str) -> str:
    """Preserve only harmless terminal CSI controls for the local PTY renderer.

    SGR/cursor/erase controls are kept for terminal presentation; OSC, device
    control strings, and unknown escapes are removed so PTY output cannot set a
    title, open a hyperlink, copy clipboard data, or inject terminal commands.
    """
    allowed_finals = set("mABCDEFGHfJKsuUlG@`hrPXLM")
    out: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char != "\x1b":
            if char in "\n\r\t\b" or ord(char) >= 0x20:
                out.append(char)
            i += 1
            continue
        if i + 1 >= len(text):
            break
        kind = text[i + 1]
        if kind == "[":
            end = i + 2
            while end < len(text) and not ("@" <= text[end] <= "~"):
                end += 1
            if end < len(text) and text[end] in allowed_finals:
                out.append(text[i:end + 1])
            i = end + 1
        elif kind == "]":
            # OSC ends at BEL or ST; neither payload nor terminator is kept.
            end = i + 2
            while end < len(text):
                if text[end] == "\x07":
                    end += 1; break
                if text[end] == "\x1b" and end + 1 < len(text) and text[end + 1] == "\\":
                    end += 2; break
                end += 1
            i = end
        else:
            i += 2
    return BIDI_RE.sub("[BIDI]", REDACTION_RE.sub(lambda m: m.group(1) + "[REDACTED]", "".join(out))).replace("\x00", "")


def safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def xdg_dir(env_name: str, fallback: Path) -> Path:
    raw = os.environ.get(env_name)
    return Path(raw).expanduser() if raw else fallback


def data_root() -> Path:
    override = os.environ.get("VORTEX_DATA_DIR")
    if override:
        root = Path(override).expanduser()
    elif os.getuid() == 0 and os.environ.get("SUDO_USER"):
        try:
            invoking_user = pwd.getpwnam(os.environ["SUDO_USER"])
            root = Path(os.environ.get("XDG_DATA_HOME", Path(invoking_user.pw_dir) / ".local" / "share")).expanduser() / "vortex"
        except KeyError:
            root = xdg_dir("XDG_DATA_HOME", Path.home() / ".local" / "share") / "vortex"
    else:
        root = xdg_dir("XDG_DATA_HOME", Path.home() / ".local" / "share") / "vortex"
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


def runtime_root() -> Path:
    base = Path(os.environ.get("XDG_RUNTIME_DIR", str(data_root() / "runtime"))).expanduser()
    root = base / "vortex"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try: root.chmod(0o700)
    except OSError: pass
    return root


def write_runtime_metadata(host: str, port: int, token: str | None) -> Path:
    path = runtime_root() / "sidecar.json"
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(canonical({"pid": os.getpid(), "host": host, "port": port, "token": token, "created_at": now_iso()}), encoding="utf-8")
    temp.chmod(0o600)
    os.replace(temp, path)
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


def _is_user_writable_directory(path: Path, st: os.stat_result | None = None) -> bool:
    st = st or path.stat()
    mode = stat.S_IMODE(st.st_mode)
    return bool(mode & 0o022) or (os.getuid() != 0 and st.st_uid == os.getuid() and bool(mode & 0o200))


def _safe_executable_dirs() -> tuple[list[str], list[str]]:
    """Return PATH directories safe for managed plans and rejected entries.

    An empty PATH component means the current directory and is deliberately
    never accepted for managed execution. User-writable directories are also
    excluded to reduce PATH replacement risk.
    """
    safe: list[str] = []
    rejected: list[str] = []
    raw_path = os.environ.get("PATH") or CONTROLLED_PATH
    for raw in raw_path.split(os.pathsep):
        directory = raw or "."
        try:
            resolved = Path(directory).expanduser().resolve(strict=True)
            st = resolved.stat()
            mode = stat.S_IMODE(st.st_mode)
            if not resolved.is_dir() or _is_user_writable_directory(resolved, st):
                rejected.append(str(resolved))
            else:
                safe.append(str(resolved))
        except OSError:
            rejected.append(directory)
    return safe, rejected


def probe_executable(name: str) -> dict[str, Any]:
    if not name or "\x00" in name or (not os.path.isabs(name) and os.sep in name):
        return {"name": name, "state": "blocked", "path": None, "version": None, "security_flags": ["invalid-executable-name"]}
    if os.path.isabs(name):
        found = name
    else:
        safe_dirs, rejected_dirs = _safe_executable_dirs()
        found = shutil.which(name, path=os.pathsep.join(safe_dirs)) if safe_dirs else None
        if not found:
            # Distinguish absence from a tool that only exists in an unsafe PATH
            # location; callers must not silently execute the latter.
            unsafe_found = shutil.which(name)
            if unsafe_found and rejected_dirs:
                return {"name": name, "state": "blocked", "path": unsafe_found, "version": None, "security_flags": ["unsafe-path-directory"]}
    if not found:
        return {"name": name, "state": "absent", "path": None, "version": None}
    path = Path(found)
    try:
        real = path.resolve(strict=True)
        st = real.stat()
        mode = stat.S_IMODE(st.st_mode)
        security_flags: list[str] = []
        parent = real.parent
        try:
            if _is_user_writable_directory(parent):
                security_flags.append("writable-parent-directory")
        except OSError:
            security_flags.append("parent-stat-failed")
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
                item["version"] = redact(version_line[0][:180]) if version_line else "version-unknown"
            except (OSError, subprocess.SubprocessError, UnicodeError):
                item["version"] = "version-unknown"
        return item
    except OSError as exc:
        return {"name": name, "state": "blocked", "path": str(path), "error": str(exc), "version": None}


def minimal_env(tty: bool, additions: dict[str, str] | None = None) -> dict[str, str]:
    allowed = {"HOME", "USER", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "LC_NUMERIC", "LC_TIME", "PATH"}
    if tty:
        allowed.add("TERM")
    env = {key: value for key, value in os.environ.items() if key in allowed}
    # Never inherit a user-controlled PATH into a managed child.
    env["PATH"] = CONTROLLED_PATH
    if additions:
        for key, value in additions.items():
            if key == "PATH":
                continue
            if re.fullmatch(r"[A-Z_][A-Z0-9_]{0,63}", key) and "=" not in value and "\x00" not in value:
                env[key] = value
    return env


def systemd_user_bus_state() -> dict[str, Any]:
    """Probe the current user's real systemd user bus without exposing env output."""
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    bus = runtime / "bus"
    result: dict[str, Any] = {"state": "absent", "socket": str(bus), "probe_exit": None}
    try:
        if not stat.S_ISSOCK(bus.stat().st_mode):
            return result
    except OSError:
        return result
    systemctl = probe_executable("systemctl")
    if systemctl.get("state") != "installed":
        result["state"] = "unavailable"
        return result
    env = minimal_env(False)
    env["XDG_RUNTIME_DIR"] = str(runtime)
    env["DBUS_SESSION_BUS_ADDRESS"] = os.environ.get("DBUS_SESSION_BUS_ADDRESS", f"unix:path={bus}")
    try:
        probe = subprocess.run([systemctl["realpath"], "--user", "--no-pager", "is-system-running"], capture_output=True, text=True, timeout=3, env=env)
        result["probe_exit"] = probe.returncode
        error_text = sanitize(probe.stderr or "")
        if "failed to connect to bus" in error_text.lower() or "no medium found" in error_text.lower():
            result["state"] = "unavailable"
            result["error"] = error_text[:240]
        else:
            result["state"] = "available"
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        result["state"] = "unavailable"
        result["error"] = redact(str(exc))[:240]
    return result


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
    user_bus = systemd_user_bus_state()
    kernel_text = os.uname().release.lower()
    wsl = bool(os.environ.get("WSL_INTEROP")) or "microsoft" in kernel_text
    distro_id = os_release.get("ID", "unknown").lower()
    distro_like = set(os_release.get("ID_LIKE", "").lower().split())
    if distro_id in {"kali", "debian", "linuxmint", "pop"} or "debian" in distro_like or Path("/etc/debian_version").exists():
        support_tier = "linux-debian-family"
    else:
        support_tier = "linux-best-effort"
    if sys.platform != "linux":
        support_tier = "unsupported-non-linux"
    return {
        "distribution": {"id": distro_id, "version_id": os_release.get("VERSION_ID", "unknown"), "pretty_name": os_release.get("PRETTY_NAME", distro_id)},
        "support_tier": support_tier,
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
        "systemd_context": {"system_bus": "available" if systemd else "unavailable", "user_bus": user_bus},
        "cgroup": cgroup,
        "package_manager": {name: probe_executable(name)["state"] for name in ("apt-get", "apt-cache", "dpkg-query", "dpkg", "apt-mark", "sudo")},
        "model": {"state": "disabled by default", "endpoint": None},
    }


def _pid1_name() -> str:
    try:
        return Path("/proc/1/comm").read_text().strip()
    except OSError:
        return "unknown"


def validate_cwd(raw: str | None) -> Path:
    if raw is not None and not isinstance(raw, str):
        raise ValueError("working directory must be a string")
    candidate = Path(raw or os.getcwd()).expanduser()
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("working directory is not a directory")
    return resolved


def quote_argv(argv: list[str]) -> str:
    import shlex
    # Display escaping is intentionally separate from execution argv. Newlines,
    # tabs, and bidi markers must never reshape a plan card or terminal log.
    safe = [sanitize(x).replace("\n", "\\n").replace("\t", "\\t") for x in argv]
    return " ".join(shlex.quote(x) for x in safe)


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
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, shell TEXT NOT NULL,
                cwd TEXT NOT NULL, command_json TEXT NOT NULL, pid INTEGER,
                cols INTEGER NOT NULL, rows INTEGER NOT NULL, status TEXT NOT NULL,
                started_at TEXT NOT NULL, ended_at TEXT, last_activity TEXT,
                exit_code INTEGER, signal INTEGER, termination_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY, operation_id TEXT, kind TEXT NOT NULL,
                source_json TEXT NOT NULL, size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL, parser_json TEXT NOT NULL,
                state TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_events (
                session_id TEXT NOT NULL, seq INTEGER NOT NULL, at TEXT NOT NULL,
                stream TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY (session_id, seq),
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '1');
            """)
        try:
            from .workspace import ensure_schema
        except ImportError:
            from workspace import ensure_schema
        ensure_schema(self)
    def mark_stale_sessions(self) -> None:
        # A sidecar restart cannot prove that an old PTY is still alive. This is
        # called by the session authority at startup, not by every read-only
        # Store client, so a concurrent CLI inspection cannot invalidate a live
        # desktop session.
        with self.lock, self.connect() as db:
            db.execute("UPDATE sessions SET status='unknown_after_crash', termination_reason='sidecar_restart' WHERE status IN ('starting','running')")

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
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, ValueError):
                return {"valid": False, "checked": row["sequence"], "error": "audit payload is not valid JSON"}
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
            row = db.execute("SELECT id, digest, status, approval_token, plan_json FROM plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            return None
        plan = json.loads(row["plan_json"])
        if plan.get("id") != row["id"] or plan.get("digest") != row["digest"] or plan.get("approval_token") != row["approval_token"] or plan_digest(plan) != row["digest"]:
            raise sqlite3.IntegrityError("plan integrity mismatch")
        # The normalized JSON is immutable; lifecycle status lives in the
        # relational column so a claimed plan cannot be replayed via stale JSON.
        plan["status"] = row["status"]
        return plan

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

    def integrity_check(self) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("PRAGMA integrity_check").fetchone()
            result = str(row[0]) if row else "unknown"
        audit = self.verify_audit()
        return {"sqlite": result, "sqlite_valid": result.lower() == "ok", "audit": audit, "valid": result.lower() == "ok" and audit.get("valid", False)}

    def backup(self, destination: str | Path, overwrite: bool = False) -> Path:
        dest = Path(destination).expanduser()
        if not dest.is_absolute():
            dest = Path.cwd() / dest
        dest = dest.resolve()
        if dest == self.db_path.resolve():
            raise ValueError("backup destination must differ from the active database")
        if dest.parent.exists():
            parent_stat = dest.parent.stat()
            if not dest.parent.is_dir() or (os.getuid() != 0 and parent_stat.st_uid != os.getuid()):
                raise PermissionError("backup parent directory is not operator-owned")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if dest.exists() and not overwrite:
            raise FileExistsError("backup destination exists; use --force to replace it")
        if dest.exists() and dest.is_symlink():
            raise ValueError("backup destination symlink is not accepted")
        self.append_audit("database_backup_requested", {"destination": redact(str(dest))})
        source = self.connect()
        target = sqlite3.connect(dest)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
        try:
            dest.chmod(0o600)
        except OSError:
            pass
        return dest

    def save_session_event(self, session_id: str, event: dict[str, Any], keep: int = 5000) -> None:
        with self.lock, self.connect() as db:
            db.execute("INSERT OR REPLACE INTO session_events(session_id,seq,at,stream,data) VALUES (?,?,?,?,?)", (session_id, event["seq"], event["at"], event.get("stream", "pty"), event.get("data", "")))
            db.execute("DELETE FROM session_events WHERE session_id=? AND seq <= (SELECT MAX(seq)-? FROM session_events WHERE session_id=?)", (session_id, keep, session_id))

    def list_session_events(self, session_id: str, since: int = 0) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT seq,at,stream,data FROM session_events WHERE session_id=? AND seq>? ORDER BY seq LIMIT 5000", (session_id, max(0, int(since)))).fetchall()
        return [{"seq": row["seq"], "at": row["at"], "stream": row["stream"], "data": row["data"]} for row in rows]

    def prune(self, history_days: int = 90, output_days: int = 30) -> dict[str, Any]:
        history_days = max(1, min(int(history_days), 3650)); output_days = max(1, min(int(output_days), 3650))
        history_cutoff = datetime.fromtimestamp(time.time() - history_days * 86400, tz=timezone.utc).isoformat()
        output_cutoff = datetime.fromtimestamp(time.time() - output_days * 86400, tz=timezone.utc).isoformat()
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            output_rows = db.execute("SELECT id,result_json FROM operations WHERE ended_at IS NOT NULL AND ended_at < ?", (output_cutoff,)).fetchall()
            output_pruned = 0
            for row in output_rows:
                item = json.loads(row["result_json"])
                changed = False
                for command in item.get("commands", []):
                    if command.get("stdout") or command.get("stderr"):
                        command["stdout"] = ""; command["stderr"] = ""; changed = True
                if changed:
                    db.execute("UPDATE operations SET result_json=? WHERE id=?", (canonical(item), row["id"])); output_pruned += 1
            old_ops = [row[0] for row in db.execute("SELECT id FROM operations WHERE COALESCE(ended_at,started_at) < ?", (history_cutoff,)).fetchall()]
            if old_ops:
                db.executemany("DELETE FROM artifacts WHERE operation_id=?", [(item,) for item in old_ops])
                db.executemany("DELETE FROM operations WHERE id=?", [(item,) for item in old_ops])
            db.execute("DELETE FROM plans WHERE id NOT IN (SELECT plan_id FROM operations) AND created_at < ?", (history_cutoff,))
            db.execute("DELETE FROM session_events WHERE at < ?", (history_cutoff,))
            db.execute("COMMIT")
        result = {"history_deleted": len(old_ops), "operation_outputs_redacted": output_pruned, "history_days": history_days, "output_days": output_days}
        self.append_audit("retention_pruned", result)
        return result

    def save_session(self, session: dict[str, Any]) -> None:
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO sessions(id,name,shell,cwd,command_json,pid,cols,rows,status,started_at,ended_at,last_activity,exit_code,signal,termination_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (session["id"], session["name"], session["shell"], session["cwd"], canonical(session.get("command", [])), session.get("pid"), session["cols"], session["rows"], session["status"], session["started_at"], session.get("ended_at"), session.get("last_activity"), session.get("exit_code"), session.get("signal"), session.get("termination_reason")))

    def update_session(self, session: dict[str, Any]) -> None:
        with self.lock, self.connect() as db:
            db.execute("UPDATE sessions SET name=?, shell=?, cwd=?, command_json=?, pid=?, cols=?, rows=?, status=?, started_at=?, ended_at=?, last_activity=?, exit_code=?, signal=?, termination_reason=? WHERE id=?", (session["name"], session["shell"], session["cwd"], canonical(session.get("command", [])), session.get("pid"), session["cols"], session["rows"], session["status"], session["started_at"], session.get("ended_at"), session.get("last_activity"), session.get("exit_code"), session.get("signal"), session.get("termination_reason"), session["id"]))

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT 100").fetchall()
        return [{"id": r["id"], "name": r["name"], "shell": r["shell"], "cwd": r["cwd"], "command": json.loads(r["command_json"]), "pid": r["pid"], "cols": r["cols"], "rows": r["rows"], "status": r["status"], "started_at": r["started_at"], "ended_at": r["ended_at"], "last_activity": r["last_activity"], "exit_code": r["exit_code"], "signal": r["signal"], "termination_reason": r["termination_reason"]} for r in rows]

    def get_session_record(self, session_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list_sessions() if item["id"] == session_id), None)


    def save_artifact(self, artifact: dict[str, Any], operation_id: str | None = None) -> None:
        with self.lock, self.connect() as db:
            db.execute("INSERT OR REPLACE INTO artifacts(id,operation_id,kind,source_json,size_bytes,sha256,parser_json,state,result_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (artifact["artifact_id"], operation_id or artifact.get("operation_id"), artifact.get("kind", "unknown"), canonical(artifact.get("source", {})), artifact.get("size_bytes", 0), artifact.get("sha256", ""), canonical(artifact.get("parser", {})), artifact.get("state", "inconclusive"), canonical(artifact), now_iso()))

    def list_artifacts(self, operation_id: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as db:
            if operation_id:
                rows = db.execute("SELECT result_json FROM artifacts WHERE operation_id=? ORDER BY created_at DESC", (operation_id,)).fetchall()
            else:
                rows = db.execute("SELECT result_json FROM artifacts ORDER BY created_at DESC LIMIT 100").fetchall()
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

    def close_engagement(self, engagement_id: str) -> bool:
        with self.lock, self.connect() as db:
            cur = db.execute("UPDATE engagements SET status='closed' WHERE id=? AND status='active'", (engagement_id,))
            changed = cur.rowcount > 0
        if changed:
            self.append_audit("engagement_closed", {"engagement_id": engagement_id})
        return changed


class SessionManager:
    """Own Linux PTYs, process groups, live event buffers, and idle cleanup."""

    def __init__(self, store: Store, idle_seconds: int | None = None, max_sessions: int | None = None):
        self.store = store
        self.store.mark_stale_sessions()
        self.idle_seconds = idle_seconds if idle_seconds is not None else int(os.environ.get("VORTEX_SESSION_IDLE_SECONDS", "1800"))
        self.max_sessions = max_sessions if max_sessions is not None else int(os.environ.get("VORTEX_MAX_SESSIONS", "8"))
        self.sessions: dict[str, dict[str, Any]] = {}
        self.events: dict[str, deque[dict[str, Any]]] = {}
        self.conditions: dict[str, threading.Condition] = {}
        self.reader_done: dict[str, threading.Event] = {}
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._reaper = threading.Thread(target=self._reap_idle, name="vortex-session-reaper", daemon=True)
        self._reaper.start()

    @staticmethod
    def _size(value: Any, default: int) -> int:
        if value is None:
            value = default
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise PolicyError("terminal size must be an integer")
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise PolicyError("terminal size must be an integer") from exc
        return max(2, min(value, 500))

    def _shell_path(self, requested: str | None) -> str:
        value = requested or os.environ.get("SHELL") or "/bin/sh"
        if not isinstance(value, str) or "\x00" in value:
            raise PolicyError("invalid shell")
        # Shells are executable identities, not shell text. Only a real
        # installed executable can become the child argv[0].
        identity = probe_executable(value)
        if identity.get("state") != "installed" or not identity.get("realpath"):
            raise PolicyError("requested shell is unavailable or blocked")
        return identity["realpath"]

    def create(self, name: str | None = None, cwd_raw: str | None = None, shell: str | None = None, cols: Any = 100, rows: Any = 30, command: list[str] | None = None) -> dict[str, Any]:
        running = sum(1 for item in self.list() if item.get("status") == "running")
        if running >= max(1, min(self.max_sessions, 32)):
            raise PolicyError("too many concurrent PTY sessions")
        cwd = validate_cwd(cwd_raw)
        shell_path = self._shell_path(shell)
        cols_i, rows_i = self._size(cols, 100), self._size(rows, 30)
        argv = command or [shell_path]
        if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
            raise PolicyError("invalid session argv")
        if not os.path.isabs(argv[0]):
            argv[0] = shell_path
        identity = probe_executable(argv[0])
        if identity.get("state") != "installed":
            raise PolicyError("session executable is unavailable or blocked")
        session_id = secrets.token_hex(16)
        started = now_iso()
        session: dict[str, Any] = {"id": session_id, "name": redact(str(name or "local shell"))[:120], "shell": shell_path, "cwd": str(cwd), "command": argv, "pid": None, "cols": cols_i, "rows": rows_i, "status": "starting", "started_at": started, "ended_at": None, "last_activity": started, "exit_code": None, "signal": None, "termination_reason": None}
        # pty.fork creates a controlling terminal for the child. The child
        # executes immediately with argv/env and never interprets a command
        # string; the parent retains the master for streaming and resize.
        env = minimal_env(True)
        env.setdefault("TERM", "xterm-256color")
        env["COLUMNS"], env["LINES"] = str(cols_i), str(rows_i)
        pid, master = pty.fork()
        if pid == 0:
            try:
                os.chdir(str(cwd))
                os.execve(argv[0], argv, env)
            except BaseException as exc:
                try: os.write(2, (f"Vortex session exec failed: {exc}\n").encode("utf-8", "replace"))
                except OSError: pass
                os._exit(127)
        os.set_blocking(master, False)
        session["pid"] = pid
        session["status"] = "running"
        session["_pid"] = pid
        session["_master"] = master
        session["_event_seq"] = 0
        with self.lock:
            self.sessions[session_id] = session
            self.events[session_id] = deque(maxlen=2000)
            self.conditions[session_id] = threading.Condition(self.lock)
            self.reader_done[session_id] = threading.Event()
            self.store.save_session(session)
        self._resize_fd(master, cols_i, rows_i)
        threading.Thread(target=self._read_loop, args=(session_id,), name=f"vortex-pty-read-{session_id[:6]}", daemon=True).start()
        threading.Thread(target=self._wait_loop, args=(session_id,), name=f"vortex-pty-wait-{session_id[:6]}", daemon=True).start()
        self.store.append_audit("session_started", {"session_id": session_id, "shell": shell_path, "cwd": str(cwd)})
        return self.info(session_id)

    def _resize_fd(self, fd: int, cols: int, rows: int) -> None:
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def _append_event(self, session_id: str, text: str, stream: str = "pty") -> None:
        text = sanitize_pty(text)
        if not text:
            return
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return
            session["_event_seq"] += 1
            session["last_activity"] = now_iso()
            event = {"seq": session["_event_seq"], "at": session["last_activity"], "stream": stream, "data": text}
            self.events[session_id].append(event)
            self.store.save_session_event(session_id, event)
            self.store.update_session(session)
            self.conditions[session_id].notify_all()

    def _read_loop(self, session_id: str) -> None:
        try:
            while True:
                with self.lock:
                    session = self.sessions.get(session_id)
                    fd = session.get("_master") if session else None
                if fd is None:
                    return
                try:
                    raw = os.read(fd, 65536)
                    if not raw:
                        return
                    self._append_event(session_id, raw.decode("utf-8", errors="replace"))
                except OSError as exc:
                    if exc.errno in (errno.EIO, errno.EBADF):
                        return
                    if exc.errno == errno.EAGAIN:
                        time.sleep(0.02)
                        continue
                    self._append_event(session_id, f"PTY read error: {exc}", "system")
                    return
        finally:
            done = self.reader_done.get(session_id)
            if done:
                done.set()


    def _wait_loop(self, session_id: str) -> None:
        with self.lock:
            session = self.sessions.get(session_id)
            pid = session.get("_pid") if session else None
        if not pid:
            return
        try:
            _, wait_status = os.waitpid(pid, 0)
            returncode = os.waitstatus_to_exitcode(wait_status)
        except ChildProcessError:
            returncode = 255
        reader_done = self.reader_done.get(session_id)
        if reader_done:
            reader_done.wait(timeout=1.0)
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return
            session["ended_at"] = now_iso()
            session["exit_code"] = returncode if returncode >= 0 else None
            session["signal"] = -returncode if returncode < 0 else None
            if session.get("termination_reason") == "cancelled":
                session["status"] = "cancelled"
            elif returncode == 0:
                session["status"] = "succeeded"; session["termination_reason"] = "completed"
            elif returncode < 0:
                session["status"] = "interrupted"; session["termination_reason"] = "signal"
            else:
                session["status"] = "failed"; session["termination_reason"] = "non_zero_exit"
            self.store.update_session(session)
            self._append_event(session_id, f"\n[SESSION {session['status'].upper()}] exit={returncode}\n", "system")
            fd = session.pop("_master", None)
            session.pop("_pid", None)
            self.reader_done.pop(session_id, None)
            if fd is not None:
                try: os.close(fd)
                except OSError: pass
            # Keep audit completion inside the lifecycle lock. Shutdown waits
            # on the same lock, so it cannot remove a test/runtime data root
            # between the terminal state update and its finish event.
            self.store.append_audit("session_finished", {"session_id": session_id, "status": session["status"], "exit_code": session["exit_code"], "signal": session["signal"]})
            self.conditions[session_id].notify_all()

    def info(self, session_id: str) -> dict[str, Any] | None:
        with self.lock:
            session = self.sessions.get(session_id)
            if session:
                return {key: value for key, value in session.items() if not key.startswith("_")}
        return self.store.get_session_record(session_id)

    def list(self) -> list[dict[str, Any]]:
        persisted = {item["id"]: item for item in self.store.list_sessions()}
        with self.lock:
            for session_id in list(self.sessions):
                item = self.info(session_id)
                if item: persisted[session_id] = item
        return sorted(persisted.values(), key=lambda x: x.get("started_at") or "", reverse=True)[:100]

    def events_since(self, session_id: str, since: Any = 0) -> dict[str, Any]:
        try: since_i = max(0, int(since))
        except (TypeError, ValueError): since_i = 0
        with self.lock:
            if session_id not in self.sessions:
                record = self.store.get_session_record(session_id)
                events = self.store.list_session_events(session_id, since_i) if record else []
                return {"session": record, "events": events, "next_seq": events[-1]["seq"] if events else 0, "replay": True} if record else {"session": None, "events": [], "next_seq": 0, "replay": False}
            session = self.sessions[session_id]
            events = [event for event in self.events[session_id] if event["seq"] > since_i]
            return {"session": self.info(session_id), "events": events, "next_seq": session["_event_seq"], "replay": False}

    def write(self, session_id: str, data: str) -> dict[str, Any]:
        if not isinstance(data, str) or len(data) > 65536 or "\x00" in data:
            raise PolicyError("session input must be text under 64 KiB")
        with self.lock:
            session = self.sessions.get(session_id)
            if not session or session.get("status") != "running" or session.get("_master") is None:
                raise PolicyError("session is not running")
            try:
                os.write(session["_master"], data.encode("utf-8"))
            except OSError as exc:
                raise PolicyError(f"session input failed: {exc}") from exc
            session["last_activity"] = now_iso()
            self.store.update_session(session)
            return self.info(session_id)  # type: ignore[return-value]

    def resize(self, session_id: str, cols: Any, rows: Any) -> dict[str, Any]:
        cols_i, rows_i = self._size(cols, 100), self._size(rows, 30)
        with self.lock:
            session = self.sessions.get(session_id)
            if not session or session.get("_master") is None:
                raise PolicyError("session is not available")
            self._resize_fd(session["_master"], cols_i, rows_i)
            session["cols"], session["rows"] = cols_i, rows_i
            self.store.update_session(session)
            return self.info(session_id)  # type: ignore[return-value]

    def kill(self, session_id: str) -> bool:
        with self.lock:
            session = self.sessions.get(session_id)
            if not session or session.get("status") != "running":
                return False
            session["termination_reason"] = "cancelled"
            pid = session.get("_pid") or session.get("pid")
            if pid:
                try: os.killpg(pid, signal.SIGINT)
                except ProcessLookupError: pass
            self.store.update_session(session)
        # Interactive shells commonly handle SIGINT as an input event instead
        # of exiting. Escalate the whole session group so kill/idle cleanup never
        # leaves a descendant behind.
        threading.Thread(target=self._escalate_kill, args=(session_id, pid), daemon=True).start()
        return True

    def _escalate_kill(self, session_id: str, pid: int | None) -> None:
        if not pid:
            return
        for sig, delay in ((signal.SIGTERM, 0.4), (signal.SIGKILL, 0.8)):
            time.sleep(delay)
            with self.lock:
                session = self.sessions.get(session_id)
                if not session or session.get("status") != "running":
                    return
            try: os.killpg(pid, sig)
            except ProcessLookupError: return

    def _reap_idle(self) -> None:
        while not self._stop.wait(15):
            cutoff = time.time() - self.idle_seconds
            for item in self.list():
                if item.get("status") != "running":
                    continue
                try: last = datetime.fromisoformat(item["last_activity"]).timestamp()
                except (KeyError, TypeError, ValueError): continue
                if last < cutoff:
                    self.kill(item["id"])
                    self.store.append_audit("session_idle_reaped", {"session_id": item["id"]})

    def shutdown(self) -> None:
        self._stop.set()
        active = [item["id"] for item in self.list() if item.get("status") == "running"]
        for session_id in active:
            self.kill(session_id)
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline:
            if not any((self.info(session_id) or {}).get("status") == "running" for session_id in active):
                break
            time.sleep(.05)


class PolicyError(ValueError):
    pass


def normalize_target(raw: str) -> str:
    value = raw.strip()
    if not value or any(c in value for c in "\x00\n\r;|&`$()<>\\"):
        raise PolicyError("target contains unsafe characters")
    if value.lower().startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname is None or parsed.username or parsed.password or parsed.fragment:
            raise PolicyError("URL must have an HTTP(S) host and no credentials or fragment")
        try:
            port = parsed.port
        except ValueError as exc:
            raise PolicyError("URL has an invalid port") from exc
        hostname = parsed.hostname.lower()
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        netloc = hostname + (f":{port}" if port is not None else "")
        return urllib.parse.urlunparse((parsed.scheme.lower(), netloc, parsed.path or "/", "", parsed.query, ""))
    if "/" in value:
        # Validate CIDR with the standard library instead of accepting arbitrary
        # numeric-looking strings or an IPv4 /128.
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise PolicyError("invalid IP/CIDR target") from exc
        return str(network)
    try:
        address = ipaddress.ip_address(value)
        return str(address)
    except ValueError:
        pass
    if not HOST_RE.fullmatch(value) or ".." in value or any(len(label) > 63 or label.startswith("-") or label.endswith("-") for label in value.split(".")):
        raise PolicyError("target is not a hostname, IP, or URL")
    return value.lower()


def target_in_engagement(target: str, engagement: dict[str, Any]) -> bool:
    normalized = normalize_target(target)
    parsed_target = urllib.parse.urlparse(normalized)
    target_host = parsed_target.hostname if parsed_target.scheme else normalized.split("/", 1)[0]
    target_port = parsed_target.port if parsed_target.scheme else None
    for allowed in engagement["targets"]:
        allowed_n = normalize_target(str(allowed))
        parsed_allowed = urllib.parse.urlparse(allowed_n)
        allowed_host = parsed_allowed.hostname if parsed_allowed.scheme else allowed_n.split("/", 1)[0]
        allowed_port = parsed_allowed.port if parsed_allowed.scheme else None
        if normalized == allowed_n:
            return True
        if target_host != allowed_host:
            continue
        # An explicitly scoped URL port must remain the same. A bare hostname
        # intentionally leaves the port open for a declared host assessment.
        if parsed_target.scheme and parsed_allowed.scheme and target_port != allowed_port:
            continue
        # A declared bare domain authorizes subdomains, but not an unrelated suffix.
        if not parsed_target.scheme and not parsed_allowed.scheme and target_host.endswith("." + allowed_host):
            return True
        if parsed_target.scheme and parsed_allowed.scheme:
            return True
        if parsed_target.scheme and not parsed_allowed.scheme:
            return True
    return False


def command_spec(executable: str, argv: list[str], cwd: Path, *, risk: str = "low", network: str = "no-network", required: str | None = None, scope: list[str] | None = None, explanation: str = "", timeout: int = 30, reject_shell_syntax: bool = True) -> dict[str, Any]:
    if not argv or argv[0] != executable or any("\x00" in arg for arg in argv):
        raise PolicyError("invalid argv")
    if reject_shell_syntax and any(token in arg for arg in argv for token in (";", "&&", "||", "|", ">", "<", "`", "$(")):
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
        "display": redact(quote_argv(argv)),
        "cwd": str(cwd),
        "env_additions": {},
        "stdin_policy": "closed",
        "timeout_seconds": timeout,
        "output_cap_bytes": 512 * 1024,
        "risk": risk,
        "network_class": network,
        "privilege": "user",
        "required_tool": required or executable,
        "tool_state_at_plan": state,
        "executable_identity": identity,
        "scope": scope or [],
        "explanation": explanation,
        "evidence": "redacted stdout/stderr and exit status",
    }


def adapter_command(adapter_id: str, executable: str, argv: list[str], cwd: Path, *, required: str | None = None, scope: list[str] | None = None, explanation: str = "", timeout: int | None = None, privilege: str | None = None) -> dict[str, Any]:
    manifest = ADAPTER_MANIFESTS[adapter_id]
    spec = command_spec(executable, argv, cwd, risk=manifest["risk"], network=manifest["network_class"], required=required or executable, scope=scope, explanation=explanation, timeout=timeout or int(manifest["limits"].get("timeout_seconds", 30)))
    spec["adapter_id"] = adapter_id
    spec["adapter_version"] = manifest["version"]
    spec["adapter_limits"] = manifest["limits"]
    spec["privilege"] = privilege or manifest.get("privilege", "user")
    return spec


def parse_package_request(text: str) -> tuple[str, str | None]:
    lower = text.lower()
    if any(char in text for char in "\x00\n\r;|&`$()<>\\"):
        return "", None
    if re.search(r"\b(?:do not|don't|never)\s+(?:install|remove|upgrade)\b", lower):
        return "", None
    operation = next((item for item in ("install", "remove", "upgrade") if re.search(rf"\b{item}\b", lower)), None)
    if not operation:
        return "", None
    if operation == "upgrade":
        return operation, None
    match = re.search(rf"\b{operation}\s+(?:packages?\s+)?([a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?)\b", lower)
    package = match.group(1) if match else None
    if package and not PACKAGE_RE.fullmatch(package):
        raise PolicyError("invalid apt package name")
    return operation, package


def apt_lock_state() -> dict[str, Any]:
    locks = ("/var/lib/dpkg/lock-frontend", "/var/lib/dpkg/lock", "/var/cache/apt/archives/lock")
    result: dict[str, str] = {}
    for raw_path in locks:
        path = Path(raw_path)
        if not path.exists():
            result[raw_path] = "absent"
            continue
        try:
            fd = os.open(str(path), os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result[raw_path] = "available"
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        except BlockingIOError:
            result[raw_path] = "held"
        except OSError:
            result[raw_path] = "unknown"
    return {"locks": result, "blocked": any(value == "held" for value in result.values()), "unknown": any(value == "unknown" for value in result.values())}


def apt_tools_ready() -> tuple[bool, list[str]]:
    required = ["apt-get", "apt-cache", "dpkg-query", "dpkg"]
    missing = [tool for tool in required if probe_executable(tool)["state"] != "installed"]
    return not missing, missing


def reboot_required_state() -> dict[str, Any]:
    marker = Path("/var/run/reboot-required")
    packages = Path("/var/run/reboot-required.pkgs")
    required = marker.exists()
    return {"required": required, "packages": packages.read_text(encoding="utf-8", errors="replace").splitlines()[:50] if packages.exists() else [], "source": str(marker)}


def parse_service(text: str) -> str | None:
    match = re.search(r"(?:service|unit)\s+([A-Za-z0-9][A-Za-z0-9_.@:-]*\.service)", text, re.I)
    return match.group(1) if match else None


def parse_systemd_mutation(text: str) -> tuple[str, str, bool] | None:
    if any(char in text for char in "\x00\n\r;|&`$()<>\\"):
        raise PolicyError("systemd request contains unsafe shell syntax")
    user_mode = bool(re.search(r"(?:--user\b|\buser\s+(?:service|unit)\b)", text, re.I))
    match = re.search(r"(?:--user\s+)?\b(restart|start|stop|enable|disable)\s+(?:--user\s+)?([^\s,;|&`$()<>]+)", text, re.I)
    if not match:
        return None
    action, raw_unit = match.group(1).lower(), match.group(2)
    if raw_unit.endswith(".service"):
        unit = raw_unit
    elif re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*", raw_unit):
        unit = raw_unit + ".service"
    else:
        raise PolicyError("invalid systemd unit name; path-like units are not allowed")
    if not UNIT_RE.fullmatch(unit):
        raise PolicyError("invalid systemd unit name")
    return action, unit, user_mode


def plan_digest(plan: dict[str, Any]) -> str:
    return digest({
        "commands": plan.get("commands", []),
        "cwd": plan.get("cwd"),
        "scope": plan.get("scope", {}),
        "policy_version": plan.get("policy_version"),
        "knowledge_version": plan.get("knowledge_version"),
        "source": plan.get("source"),
        "risk": plan.get("risk"),
        "rollback": plan.get("rollback", {}),
        "network_facts": plan.get("network_facts", {}),
        "expires_at": plan.get("expires_at"),
    })


def build_plan(store: Store, request: str, cwd_raw: str | None = None, engagement_id: str | None = None, offline: bool = False) -> dict[str, Any]:
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
    rollback: dict[str, Any] = {"available": False, "advice": "No automatic rollback metadata is available for this plan."}
    network_facts: dict[str, Any] = {}
    engagement = store.get_engagement(engagement_id) if engagement_id else None
    closed_engagement = False
    unknown_engagement = bool(engagement_id) and engagement is None
    if engagement:
        expired = False
        try:
            expired = time.time() > datetime.fromisoformat(str(engagement.get("expires_at"))).timestamp()
        except (TypeError, ValueError):
            expired = True
        if engagement.get("status") != "active" or expired:
            closed_engagement = True
            engagement = None
    bound_engagement_id = engagement["id"] if engagement else None

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
    elif re.search(r"\bssh\b", lower) and any(word in lower for word in ("diagnos", "config", "connection", "connect")):
        kind = "ssh_diagnostics"
        active_connection = bool(re.search(r"\b(?:test|check|diagnose)\b.*\bssh\b.*\b(?:connection|connect|connectivity)\b", lower) or re.search(r"\bssh\s+connectivity\b", lower))
        target_match = (
            re.search(r"\bssh\s+(?:config|diagnostics?|connection)\s+(?:for|to)\s+([A-Za-z0-9][A-Za-z0-9_.-]*)", lower)
            or re.search(r"\bssh\s+(?:to|for)\s+([A-Za-z0-9][A-Za-z0-9_.-]*)", lower)
            or re.search(r"\bssh\s+(?:config|diagnostics?|connection)\s+([A-Za-z0-9][A-Za-z0-9_.-]*)", lower)
        )
        target = target_match.group(1) if target_match else None
        if not target:
            status = "clarified"
            notes.append("Provide one SSH host alias or hostname. Vortex will not read key contents or guess a target.")
        elif probe_executable("ssh")["state"] != "installed":
            status = "unavailable"; missing.append("ssh"); notes.append("TOOL MISSING: ssh; no SSH facts were observed.")
        elif active_connection:
            risk = "high"; authorization = "authorized SSH diagnostic required"
            if offline:
                status = "unavailable"; notes.append("OFFLINE mode blocks outbound SSH diagnostics; no connection was attempted.")
            elif not engagement:
                if closed_engagement:
                    status = "rejected"; notes.append("Engagement is closed or expired; no SSH connection was planned.")
                elif unknown_engagement:
                    status = "rejected"; notes.append("Engagement not found; no SSH connection was planned.")
                else:
                    status = "clarified"; notes += ["An active SSH connection diagnostic requires an engagement with the exact authorized host.", "Create an engagement before connecting; Vortex never bypasses host verification."]
            elif not target_in_engagement(target, engagement):
                status = "rejected"; notes.append("SSH target is outside the active engagement scope: " + target)
            else:
                network_facts = resolve_targets([target])
                if network_facts["state"] != "observed":
                    status = "unavailable"; notes.append("SSH target DNS could not be resolved; no connection was attempted.")
                else:
                    specs.append(adapter_command("linux.ssh.connection", "ssh", ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ConnectionAttempts=1", "-o", "StrictHostKeyChecking=yes", "--", target, "true"], cwd, required="ssh", scope=[target], explanation=f"Perform a bounded, non-interactive SSH connectivity check to {target}; no password prompt or host-key bypass is allowed."))
                    status = "planned"
                    notes += ["This is an outbound connectivity diagnostic and requires explicit approval.", "BatchMode prevents password capture; StrictHostKeyChecking=yes prevents host-verification bypass."]
        else:
            specs.append(adapter_command("linux.ssh.config", "ssh", ["ssh", "-G", "--", target], cwd, required="ssh", explanation=f"Resolve the effective SSH configuration for {target}; -G does not open a network connection or authenticate."))
            status = "planned"
            notes += ["Read-only SSH configuration diagnostics; private key contents, passwords, and agent secrets are not read.", "This adapter does not connect to the target. A real connection requires a separate explicitly approved plan."]
    elif any(word in lower for word in ("docker", "podman", "container")) and any(word in lower for word in ("log", "logs")):
        kind = "container_logs"
        runtime = next((name for name in ("docker", "podman") if probe_executable(name)["state"] == "installed"), None)
        match = re.search(r"(?:logs?|container)\s+(?:for\s+)?(?:container\s+)?([A-Za-z0-9][A-Za-z0-9_.-]{0,127})", lower)
        container_id = match.group(1) if match else None
        if not runtime:
            status = "unavailable"; missing.extend([name for name in ("docker", "podman") if probe_executable(name)["state"] != "installed"]); notes.append("TOOL MISSING: neither Docker nor Podman was found; no container logs exist.")
        elif not container_id or container_id in {"logs", "container"}:
            status = "clarified"; notes.append("Provide one container name or ID; log collection is bounded to 200 lines.")
        else:
            specs.append(adapter_command("linux.containers.logs", runtime, [runtime, "logs", "--tail", "200", "--timestamps", container_id], cwd, required=runtime, explanation=f"Collect at most 200 timestamped lines from the real {runtime} container {container_id}; no container state changes."))
            status = "planned"; notes += [f"Detected runtime: {runtime}. Logs are read-only and bounded.", "Log content is untrusted evidence; no vulnerability finding is inferred."]
    elif any(word in lower for word in ("docker", "podman")) and any(word in lower for word in ("diagnos", "not working", "broken", "failing")):
        kind = "container_diagnose"
        runtime = next((name for name in ("docker", "podman") if probe_executable(name)["state"] == "installed"), None)
        if not runtime:
            status = "unavailable"
            missing.extend([name for name in ("docker", "podman") if probe_executable(name)["state"] != "installed"])
            notes.append("TOOL MISSING: neither Docker nor Podman was found; diagnosis cannot continue.")
        else:
            specs.append(adapter_command("linux.containers.diagnose", runtime, [runtime, "--version"], cwd, required=runtime, explanation=f"Confirm the installed {runtime} client version."))
            specs.append(adapter_command("linux.containers.diagnose", runtime, [runtime, "info"], cwd, required=runtime, explanation=f"Inspect the real {runtime} daemon/user context without changing containers."))
            specs.append(adapter_command("linux.containers.diagnose", runtime, [runtime, "ps", "--all", "--no-trunc"], cwd, required=runtime, explanation=f"List real {runtime} containers after daemon facts are observed."))
            status = "planned"
            notes += [f"Multi-step read-only diagnosis using {runtime}.", "VORTEX stops when daemon facts and container lists are observed; it does not apply a fix unless a separate approved plan is created."]
    elif any(word in lower for word in ("docker", "podman", "container")):
        kind = "container_inspection"
        runtime = next((name for name in ("docker", "podman") if probe_executable(name)["state"] == "installed"), None)
        if not runtime:
            status = "unavailable"
            missing.extend([name for name in ("docker", "podman") if probe_executable(name)["state"] != "installed"])
            notes.append("TOOL MISSING: neither Docker nor Podman was found; no container state was observed.")
        else:
            specs.append(adapter_command("linux.containers.inspect", runtime, [runtime, "ps", "--all", "--no-trunc"], cwd, required=runtime, explanation=f"List real {runtime} containers without changing their state."))
            status = "planned"
            notes += [f"Detected runtime: {runtime}. The command is read-only and does not start, stop, remove, or prune containers.", "Container daemon output is observed only; no image or vulnerability conclusion is inferred."]
    elif parse_package_request(lower)[0]:
        package_operation, package_name = parse_package_request(lower)
        kind = "package_operation"
        risk = "high"
        authorization = "privileged package operation"
        if package_operation == "install" and package_name:
            rollback = {"available": True, "strategy": "fresh-plan-required", "inverse": ["remove", package_name], "warning": "Removal may not restore dependency state; create and review a fresh plan."}
        elif package_operation == "remove" and package_name:
            rollback = {"available": True, "strategy": "fresh-plan-required", "inverse": ["install", package_name], "warning": "The original version/source may not be restored."}
        else:
            rollback = {"available": False, "strategy": "snapshot-or-distro-recovery", "warning": "Upgrades have no automatic rollback; use a tested snapshot or package downgrade plan."}
        ready, apt_missing = apt_tools_ready()
        locks = apt_lock_state()
        reboot = reboot_required_state()
        if not ready:
            status = "unavailable"
            missing.extend(apt_missing)
            notes.append("Required apt/dpkg executables are unavailable; no package command was created.")
        elif locks["blocked"]:
            status = "unavailable"
            notes.append("An apt/dpkg lock is currently held; no package command was created.")
            notes.append(json.dumps(locks, sort_keys=True))
        elif package_operation in ("install", "remove") and not package_name:
            status = "clarified"
            notes.append(f"Tell Vortex the exact package to {package_operation}; package names are parsed, not concatenated shell text.")
        else:
            specs.append(adapter_command("linux.packages.apt", "dpkg", ["dpkg", "--audit"], cwd, required="dpkg", explanation="Check for incomplete dpkg state before any package operation.", privilege="user"))
            if package_name:
                specs.append(adapter_command("linux.packages.apt", "apt-cache", ["apt-cache", "policy", package_name], cwd, required="apt-cache", explanation=f"Show the installed/candidate version, architecture, and repository policy for {package_name}.", privilege="user"))
                specs.append(adapter_command("linux.packages.apt", "apt-cache", ["apt-cache", "show", package_name], cwd, required="apt-cache", explanation=f"Show package metadata and declared dependencies for {package_name}.", privilege="user"))
                specs.append(adapter_command("linux.packages.apt", "dpkg-query", ["dpkg-query", "-W", "-f=${Status} ${Version} ${Architecture}\n", package_name], cwd, required="dpkg-query", explanation=f"Report the locally installed state of {package_name}; a missing installed package is informational.", privilege="user"))
                specs[-1]["allow_failure"] = True
            if probe_executable("apt-mark")["state"] == "installed":
                specs.append(adapter_command("linux.packages.apt", "apt-mark", ["apt-mark", "showhold"], cwd, required="apt-mark", explanation="Report held packages that may affect the requested operation.", privilege="user"))
            if package_operation == "install":
                preflight = ["apt-get", "-s", "--no-remove", "install", package_name]
                mutation = ["apt-get", "--assume-yes", "--no-remove", "install", package_name]
            elif package_operation == "remove":
                preflight = ["apt-get", "-s", "remove", package_name]
                mutation = ["apt-get", "--assume-yes", "remove", package_name]
            else:
                preflight = ["apt-get", "-s", "--no-remove", "upgrade"]
                mutation = ["apt-get", "--assume-yes", "--no-remove", "upgrade"]
            specs.append(adapter_command("linux.packages.apt", "apt-get", preflight, cwd, required="apt-get", explanation="Run a fresh apt preflight immediately before mutation; dependency changes and removals are observed, not assumed.", privilege="user", timeout=900))
            specs.append(adapter_command("linux.packages.apt", "apt-get", mutation, cwd, required="apt-get", explanation="Apply only the exact package operation after the preceding preflight and explicit approval. No repository trust bypass or auto-update is included.", privilege="root-required", timeout=900))
            status = "planned"
            notes += ["Package source, candidate/installed version, dependency impact, held state, and preflight output must be reviewed before execution.", json.dumps(locks, sort_keys=True) if locks["unknown"] else "apt/dpkg locks were available during planning and are rechecked by apt at execution.", f"Reboot required marker: {reboot['required']}" + (f" ({', '.join(reboot['packages'])})" if reboot['packages'] else ""), "The final apt command requires root; Vortex never invokes sudo or captures a password.", "No apt update, PPA, third-party repository, unauthenticated package, curl-piped installer, or arbitrary .deb is allowed."]
    elif parse_systemd_mutation(lower):
        action, unit, user_mode = parse_systemd_mutation(lower) or ("", "", False)
        kind = "systemd_mutation"
        risk = "high"
        authorization = "user-scoped service operation" if user_mode else "privileged service operation"
        inverse = {"start": "stop", "stop": "start", "enable": "disable", "disable": "enable"}.get(action)
        rollback = {"available": bool(inverse), "strategy": "fresh-plan-required", "inverse": [inverse, unit] if inverse else [], "warning": "Restart has no automatic inverse; inspect service state and create a fresh plan." if not inverse else "Inverse action still requires a fresh plan and confirmation."}
        context = detect_context()
        user_bus_available = context.get("systemd_context", {}).get("user_bus", {}).get("state") == "available"
        systemd_available = user_bus_available if user_mode else context["systemd"]
        if not systemd_available or probe_executable("systemctl")["state"] != "installed":
            status = "unavailable"
            missing.append("systemd-user-bus" if user_mode else "systemd")
            notes.append("The requested systemd context is not usable; no service mutation was created.")
        else:
            prefix = ["systemctl", "--user"] if user_mode else ["systemctl"]
            privilege = "user" if user_mode else "root-required"
            specs.append(adapter_command("linux.systemd.mutate", "systemctl", [*prefix, "show", unit, "--property=Id,Description,LoadState,ActiveState,SubState,UnitFileState", "--no-pager"], cwd, required="systemctl", explanation=f"Freshly verify the {('user ' if user_mode else '')}description, active state, and persistence state of {unit} before mutation.", privilege="user"))
            specs.append(adapter_command("linux.systemd.mutate", "systemctl", [*prefix, "--no-pager", "--no-ask-password", action, unit], cwd, required="systemctl", explanation=f"Perform the explicitly approved {('user ' if user_mode else '')}{action} operation on {unit}; no sudo escalation is inferred.", privilege=privilege))
            status = "planned"
            notes += [f"Fresh systemd {('user-bus ' if user_mode else '')}state for {unit} is required immediately before {action}.", "This is a service mutation and may interrupt workloads; Vortex will not run it without explicit approval.", "enable/disable are persistent changes. daemon-reload, mask, vacuum, and default-target changes are not supported."]
    elif any(word in lower for word in ("sqlmap", "msfconsole", "metasploit")):
        kind = "authorized_engagement"
        risk = "high"
        authorization = "active engagement required"
        status = "unavailable"
        notes.append("ADAPTER NOT IMPLEMENTED: sqlmap/msfconsole remain catalog probes only. No command was created and no output was fabricated.")
    elif any(word in lower for word in ("nmap", "nuclei", "ffuf", "nikto", "amass", "gobuster", "curl", "http headers", "web application", "enumerate the web", "scan ")):
        kind = "authorized_engagement"
        risk = "high"
        authorization = "active engagement required"
        tool = next((name for name in ("nmap", "nuclei", "ffuf", "nikto", "amass", "gobuster", "curl") if name in lower), "nmap")
        targets = re.findall(r"https?://[^\s,]+|\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b|\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b", request)
        if offline:
            status = "unavailable"
            notes += ["OFFLINE mode blocks outbound network operations; no assessment command was planned."]
        elif not engagement:
            if closed_engagement:
                status = "rejected"
                notes.append("Engagement is closed or expired; no assessment command was created.")
            elif unknown_engagement:
                status = "rejected"
                notes.append("Engagement not found; no assessment command was created.")
            else:
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
                network_facts = resolve_targets(normalized)
                if network_facts["state"] != "observed":
                    status = "unavailable"
                    notes.append("Target DNS resolution was not observed; no network command was created.")
                elif tool == "nmap":
                    for target in normalized:
                        if "/" in target:
                            try:
                                if ipaddress.ip_network(target, strict=False).num_addresses > ADAPTER_MANIFESTS["security.nmap.discovery"]["limits"]["max_cidr_hosts"]:
                                    raise PolicyError("nmap CIDR is larger than the 256-host adapter limit")
                            except ValueError as exc:
                                raise PolicyError("nmap target must be a valid host or bounded CIDR") from exc
                    ports_match = re.search(r"(?:ports?|tcp)\s+([0-9][0-9, -]*)", lower)
                    port_args: list[str] = []
                    if ports_match:
                        raw_ports = [piece for piece in re.split(r"[,\s-]+", ports_match.group(1)) if piece]
                        ports = sorted({int(piece) for piece in raw_ports})
                        if any(port < 1 or port > 65535 for port in ports) or len(ports) > 32:
                            raise PolicyError("nmap port list must contain at most 32 valid ports")
                        port_args = ["-p", ",".join(str(port) for port in ports)]
                    args = ["nmap", "-sV", "--version-light", "--max-retries", "2", "-T2", "--host-timeout", "120s", *port_args, "-oX", str(store.root / ("evidence-" + secrets.token_hex(8) + ".xml")), normalized[0]]
                    adapter_id = "security.nmap.discovery"
                    explanation = "Run the installed nmap adapter with conservative timing, bounded targets/ports, and XML evidence output."
                elif tool == "curl":
                    if not all(target.lower().startswith(("http://", "https://")) for target in normalized):
                        raise PolicyError("curl adapter requires an explicit HTTP(S) URL")
                    args = ["curl", "--fail", "--silent", "--show-error", "--max-time", "15", "--dump-header", "-", "--output", "/dev/null", normalized[0]]
                    adapter_id = "security.http.headers"
                    explanation = "Inspect real HTTP response headers without following redirects; any Location target requires a fresh scope check."
                else:
                    try:
                        scanners = _load("security.scanners")
                    except Exception:
                        scanners = None
                    proposal = scanners.build_scan(tool, normalized, request) if scanners else {"ok": False, "reason": f"ADAPTER NOT IMPLEMENTED: {tool}; no command was created."}
                    if proposal.get("ok"):
                        args = list(proposal["argv"])
                        adapter_id = proposal["adapter_id"]
                        explanation = proposal["explanation"]
                    else:
                        status = "unavailable"
                        if proposal.get("missing"):
                            missing.append(str(proposal["missing"]))
                        notes.append(str(proposal.get("reason") or f"ADAPTER NOT IMPLEMENTED: {tool}; no command was created."))
                        adapter_id = None
                if adapter_id:
                    specs.append(adapter_command(adapter_id, tool, args, cwd, required=tool, scope=normalized, explanation=explanation))
                    status = "planned"
                notes += ["This is active authorized assessment, not a generic shell command.", "Targets, DNS, redirects, limits, and engagement expiry must be checked again at execution."]
    elif any(phrase in lower for phrase in ("ip address", "network interface", "show interfaces", "list interfaces")) or lower.strip() in {"ip addr", "ip address"}:
        kind = "network_interfaces"
        if probe_executable("ip")["state"] != "installed":
            status = "unavailable"; missing.append("ip"); notes.append("TOOL MISSING: ip; no interface facts were observed.")
        else:
            specs.append(adapter_command("linux.network.interfaces", "ip", ["ip", "-br", "addr"], cwd, required="ip", explanation="List observed network interfaces and addresses without changing configuration."))
            status = "planned"; notes.append("Read-only interface inspection. No routes, firewall, or DNS are modified.")
    elif lower.strip() in {"date", "time"} or "what time" in lower or "current date" in lower:
        kind = "clock"
        if probe_executable("date")["state"] != "installed":
            status = "unavailable"; missing.append("date"); notes.append("TOOL MISSING: date; no clock fact was observed.")
        else:
            specs.append(adapter_command("linux.system.clock", "date", ["date", "--iso-8601=seconds"], cwd, required="date", explanation="Report the host clock as observed."))
            status = "planned"; notes.append("Read-only clock observation.")
    elif any(phrase in lower for phrase in ("os-release", "what distro", "which distro", "linux distribution", "os release")):
        kind = "os_release"
        if probe_executable("cat")["state"] != "installed" or not Path("/etc/os-release").is_file():
            status = "unavailable"; missing.append("cat"); notes.append("TOOL MISSING: cannot observe /etc/os-release.")
        else:
            specs.append(adapter_command("linux.system.os-release", "cat", ["cat", "/etc/os-release"], cwd, required="cat", explanation="Read the observed /etc/os-release file only."))
            status = "planned"; notes.append("Read-only distribution identification. No packages are changed.")
    elif "lscpu" in lower or "cpu details" in lower or "processor details" in lower:
        kind = "cpu"
        if probe_executable("lscpu")["state"] != "installed":
            status = "unavailable"; missing.append("lscpu"); notes.append("TOOL MISSING: lscpu; no processor table was observed.")
        else:
            specs.append(adapter_command("linux.system.cpu", "lscpu", ["lscpu"], cwd, required="lscpu", explanation="Report observed CPU topology from the host."))
            status = "planned"; notes.append("Read-only processor inspection.")
    elif any(word in lower for word in ("port", "listen", "socket")):
        if probe_executable("ss")["state"] != "installed":
            status = "unavailable"; missing.append("ss"); notes.append("TOOL MISSING: ss. Install instructions may be shown separately; no socket facts were observed.")
        else:
            specs.append(adapter_command("linux.network.sockets", "ss", ["ss", "-lntup"], cwd, required="ss", explanation="List listening TCP and UDP sockets; process details may require elevated permissions."))
            status = "planned"; notes += ["Read-only local socket inspection.", "The command reports observed sockets only; it does not establish that a service is secure."]
    elif parse_service(lower):
        unit = parse_service(lower)
        assert unit is not None
        user_mode = bool(re.search(r"(?:--user\b|\buser\s+(?:service|unit)\b)", lower))
        context = detect_context()
        user_bus_available = context.get("systemd_context", {}).get("user_bus", {}).get("state") == "available"
        systemd_available = user_bus_available if user_mode else context["systemd"]
        if (not systemd_available or any(probe_executable(tool)["state"] != "installed" for tool in ("systemctl", "journalctl"))):
            status = "unavailable"; missing.extend([tool for tool in ("systemctl", "journalctl") if probe_executable(tool)["state"] != "installed"]); notes.append("The requested systemd context is not usable; no service command was run.")
        else:
            prefix = ["systemctl", "--user"] if user_mode else ["systemctl"]
            journal_prefix = ["journalctl", "--user"] if user_mode else ["journalctl"]
            specs.extend([
                adapter_command("linux.systemd.inspect", "systemctl", [*prefix, "show", unit, "--property=Id,Description,LoadState,ActiveState,SubState,UnitFileState", "--no-pager"], cwd, required="systemctl", explanation=f"Read the factual {('user ' if user_mode else '')}state and persistence of {unit}."),
                adapter_command("linux.systemd.inspect", "journalctl", [*journal_prefix, "-u", unit, "-n", "80", "--no-pager", "--output=short-iso"], cwd, required="journalctl", explanation=f"Read the last bounded {('user ' if user_mode else '')}journal lines for {unit}; no service mutation is requested."),
            ])
            status = "planned"; notes.append("Read-only systemd and journal inspection. Restart/enable/disable require a separate fresh plan and confirmation.")
    elif any(word in lower for word in ("whoami", "who am i", "current user", "hostname")) or lower.strip() in {"pwd", "id"}:
        kind = "identity"
        catalog = [
            ("whoami", ["whoami"], "Report the current user name."),
            ("id", ["id"], "Report user and group identifiers."),
            ("hostname", ["hostname"], "Report the local hostname."),
            ("pwd", ["pwd"], "Report the working directory."),
        ]
        wanted = {lower.strip()} if lower.strip() in {"whoami", "id", "pwd", "hostname"} else {item[0] for item in catalog}
        for executable, argv, explanation in catalog:
            if executable not in wanted:
                continue
            if probe_executable(executable)["state"] == "installed":
                specs.append(adapter_command("linux.system.identity", executable, argv, cwd, required=executable, explanation=explanation))
            else:
                missing.append(executable)
        status = "planned" if specs else "unavailable"
        notes.append("Read-only identity facts from the local host.")
    elif lower.strip() in {"ls", "list files", "list directory"} or any(phrase in lower for phrase in ("list files", "list the directory", "show files in")):
        kind = "filesystem_list"
        if probe_executable("ls")["state"] != "installed":
            status = "unavailable"; missing.append("ls"); notes.append("TOOL MISSING: ls; no directory listing was observed.")
        else:
            specs.append(adapter_command("linux.filesystem.list", "ls", ["ls", "-la", str(cwd)], cwd, required="ls", explanation="List files in the current working-directory scope only."))
            status = "planned"; notes.append("Read-only directory listing; no files are modified.")
    elif any(word in lower for word in ("process list", "running processes", "list processes")) or lower.strip() in {"ps", "show processes"}:
        kind = "processes"
        if probe_executable("ps")["state"] != "installed":
            status = "unavailable"; missing.append("ps"); notes.append("TOOL MISSING: ps; no process table was observed.")
        else:
            specs.append(adapter_command("linux.system.processes", "ps", ["ps", "-eo", "pid,user,pcpu,pmem,comm", "--no-headers"], cwd, required="ps", explanation="List observed processes without sending signals."))
            status = "planned"; notes.append("Read-only process inspection. Output is untrusted data, not instructions.")
    elif any(word in lower for word in ("git status", "repository status", "git hygiene", "check my repo")):
        if probe_executable("git")["state"] != "installed":
            status = "unavailable"; missing.append("git"); notes.append("TOOL MISSING: git; no repository state was observed.")
        else:
            specs.append(adapter_command("linux.development.git-status", "git", ["git", "status", "--short", "--branch"], cwd, required="git", explanation="Show the current branch and working-tree changes without modifying the repository."))
            status = "planned"; notes.append("Read-only Git status; no hooks, checkout, reset, clean, push, or network operation is included.")
    elif any(word in lower for word in ("disk", "space", "large file", "cache")):
        specs.append(adapter_command("linux.filesystem.usage", "df", ["df", "-h", str(cwd)], cwd, required="df", explanation="Show human-readable filesystem capacity for the current scope."))
        specs.append(adapter_command("linux.filesystem.usage", "du", ["du", "-x", "-h", "-d", "1", str(cwd)], cwd, required="du", explanation="Measure immediate directory usage on the same filesystem; it does not delete anything."))
        status = "planned" if all(x["tool_state_at_plan"] == "ready" for x in specs) else "unavailable"
        if status == "unavailable":
            missing = [x["required_tool"] for x in specs if x["tool_state_at_plan"] != "ready"]
        notes += ["Read-only disk inspection. Cleanup is not bundled into a discovery plan.", "No files are removed or moved by these commands."]
    elif any(word in lower for word in ("system", "health", "cpu", "memory", "ram", "diagnos", "kernel")):
        for executable, argv, explanation in [
            ("uname", ["uname", "-a"], "Identify the running kernel and architecture."),
            ("uptime", ["uptime"], "Report observed uptime and load averages."),
            ("free", ["free", "-h"], "Report memory and swap counters from the host."),
            ("df", ["df", "-h", str(cwd)], "Report filesystem capacity for the current working directory."),
        ]:
            if probe_executable(executable)["state"] == "installed":
                specs.append(adapter_command("linux.system.health", executable, argv, cwd, required=executable, explanation=explanation))
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
        "request": redact(request),
        "cwd": str(cwd),
        "status": status,
        "kind": kind,
        "risk": risk,
        "authorization": authorization,
        "rollback": rollback,
        "commands": specs,
        "notes": notes,
        "missing_tools": sorted(set(missing)),
        "engagement_id": bound_engagement_id,
        "network_facts": network_facts,
        "scope": {"cwd": str(cwd), "engagement_id": bound_engagement_id, "targets": specs[0].get("scope", []) if specs else []},
        "workers": [{"id": "vortex-deterministic-planner", "state": "responded", "evidence_used": bool(specs), "role": "reviewed local adapter"}, {"id": "local-model", "state": "disabled", "evidence_used": False, "role": "advisory only"}],
        "approval_required": bool(specs),
        "approval_phrase": "APPROVE " + (specs[0]["display"] if specs else "NO EXECUTION"),
        "source": "deterministic",
        "policy_version": "safe-v1",
        "knowledge_version": "builtin-v1",
    }
    plan["digest"] = plan_digest(plan)
    plan["approval_token"] = secrets.token_urlsafe(32)
    store.save_plan(plan)
    return plan


class ExecutionManager:
    def __init__(self, store: Store):
        self.store = store
        self.threads: dict[str, threading.Thread] = {}
        self.cancel_events: dict[str, threading.Event] = {}
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.lock = threading.Lock()

    def start(self, plan: dict[str, Any], confirm: bool, approval_token: str | None = None, allow_root: bool = False, offline: bool = False) -> dict[str, Any]:
        if not confirm:
            raise PermissionError("confirmation required")
        # Re-read the canonical row. A caller must not be able to mutate an
        # in-memory plan or substitute a different command after planning.
        authoritative = self.store.get_plan(str(plan.get("id", "")))
        if not authoritative:
            raise PolicyError("plan not found")
        if authoritative.get("digest") != plan.get("digest") or plan_digest(plan) != plan.get("digest"):
            raise PolicyError("plan digest does not match its command and execution context")
        plan = authoritative
        if plan["status"] != "planned":
            raise PolicyError("plan is not executable in its current state")
        if offline and any(spec.get("network_class") not in ("no-network", "loopback-only") for spec in plan.get("commands", [])):
            raise PolicyError("offline mode blocks this network-effecting plan")
        planned_network = plan.get("network_facts", {})
        if planned_network.get("state") == "observed":
            current_network = resolve_targets([item.get("target") for item in planned_network.get("targets", []) if item.get("target")])
            if current_network.get("state") != "observed" or resolution_digest(current_network) != resolution_digest(planned_network):
                raise PolicyError("DNS resolution changed or could not be revalidated; create a fresh plan")
        if any(spec.get("privilege") == "root-required" for spec in plan.get("commands", [])) and os.getuid() != 0:
            raise PermissionError("this plan requires root; rerun the reviewed plan with sudo vortex --allow-root run <plan-id>")
        if time.time() > datetime.fromisoformat(plan["expires_at"]).timestamp():
            raise TimeoutError("plan expired")
        needs_scope = any(spec.get("network_class") not in ("no-network", "loopback-only") for spec in plan.get("commands", []))
        if needs_scope:
            engagement = self.store.get_engagement(plan["engagement_id"]) if plan.get("engagement_id") else None
            workspace = getattr(self, "workspace", None)
            if workspace is not None:
                engagement = workspace.enrich_engagement(engagement)
            if not engagement or engagement.get("status") != "active":
                raise PolicyError("engagement is unavailable or closed")
            if time.time() > datetime.fromisoformat(engagement["expires_at"]).timestamp():
                raise TimeoutError("engagement expired")
            for target in plan.get("scope", {}).get("targets", []):
                if not target_in_engagement(target, engagement):
                    raise PolicyError("plan target is no longer inside the engagement scope")
        if not isinstance(approval_token, str) or not approval_token or not secrets.compare_digest(approval_token, plan["approval_token"]):
            raise PolicyError("exact approval token is required for this plan")
        if os.getuid() == 0 and not allow_root:
            raise PermissionError("refusing UID 0 execution without an explicit root override")
        for spec in plan["commands"]:
            current = probe_executable(spec["executable"])
            if current.get("state") != "installed" or current.get("sha256") != spec["executable_identity"].get("sha256") or current.get("device") != spec["executable_identity"].get("device") or current.get("inode") != spec["executable_identity"].get("inode"):
                raise PolicyError(f"executable identity changed for {spec['executable']}; reprobe and reapprove")
        claimed, reason = self.store.claim_plan(plan["id"])
        if not claimed:
            raise PolicyError(reason)
        self.store.append_audit("plan_approved", {"plan_id": plan["id"], "digest": plan["digest"]})
        op = {"schema_version": SCHEMA_VERSION, "id": secrets.token_hex(16), "plan_id": plan["id"], "status": "started", "started_at": now_iso(), "ended_at": None, "commands": [], "workers": plan["workers"], "source": plan["source"], "network_facts": plan.get("network_facts", {}), "output_digest": None, "analysis": None}
        self.store.save_operation(op)
        self.store.append_audit("operation_started", {"operation_id": op["id"], "plan_id": plan["id"], "digest": plan["digest"], "privilege": "root-override" if allow_root else "user"})
        thread = threading.Thread(target=self._run, args=(plan, op, 0), daemon=True)
        with self.lock:
            self.threads[op["id"]] = thread
            self.cancel_events[op["id"]] = threading.Event()
        thread.start()
        return op

    def cancel(self, operation_id: str) -> bool:
        """Request cancellation and interrupt the currently running group."""
        with self.lock:
            event = self.cancel_events.get(operation_id)
            process = self.processes.get(operation_id)
        if not event:
            return False
        operation = self.store.get_operation(operation_id)
        if operation and operation.get("status") == "awaiting_confirmation":
            event.set()
            operation["status"] = "cancelled"
            operation["ended_at"] = now_iso()
            operation["analysis"] = make_analysis({}, operation)
            self.store.update_operation(operation)
            with self.lock: self.cancel_events.pop(operation_id, None)
            self.store.append_audit("operation_cancelled", {"operation_id": operation_id, "reason": "preflight_declined"})
            return True
        event.set()
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        self.store.append_audit("operation_cancel_requested", {"operation_id": operation_id})
        return True

    @staticmethod
    def _has_guarded_mutation(plan: dict[str, Any]) -> bool:
        return any(spec.get("privilege") == "root-required" and spec.get("adapter_id") in ("linux.packages.apt", "linux.systemd.mutate") for spec in plan.get("commands", []))

    def approve_preflight(self, operation_id: str, confirm: bool, approval_token: str | None, preflight_digest: str | None) -> dict[str, Any]:
        if not confirm:
            raise PermissionError("mutation confirmation required")
        operation = self.store.get_operation(operation_id)
        if not operation:
            raise PolicyError("operation not found")
        if operation.get("status") != "awaiting_confirmation":
            raise PolicyError("operation is not awaiting mutation confirmation")
        plan = self.store.get_plan(operation["plan_id"])
        if not plan:
            raise PolicyError("plan not found")
        if time.time() > datetime.fromisoformat(plan["expires_at"]).timestamp():
            raise TimeoutError("plan expired before mutation approval")
        for spec in plan.get("commands", []):
            current = probe_executable(spec["executable"])
            identity = spec.get("executable_identity", {})
            if current.get("state") != "installed" or current.get("sha256") != identity.get("sha256") or current.get("device") != identity.get("device") or current.get("inode") != identity.get("inode"):
                raise PolicyError(f"executable identity changed for {spec['executable']}; fresh plan required")
        needs_scope = any(spec.get("network_class") not in ("no-network", "loopback-only") for spec in plan.get("commands", []))
        if needs_scope:
            engagement = self.store.get_engagement(plan["engagement_id"]) if plan.get("engagement_id") else None
            workspace = getattr(self, "workspace", None)
            if workspace is not None:
                engagement = workspace.enrich_engagement(engagement)
            if not engagement or engagement.get("status") != "active":
                raise PolicyError("engagement is unavailable or closed")
            if time.time() > datetime.fromisoformat(engagement["expires_at"]).timestamp():
                raise TimeoutError("engagement expired before mutation approval")
        if not isinstance(approval_token, str) or not approval_token or not secrets.compare_digest(approval_token, plan["approval_token"]):
            raise PolicyError("exact approval token is required for mutation confirmation")
        if not isinstance(preflight_digest, str) or not preflight_digest or not secrets.compare_digest(preflight_digest, operation.get("preflight_digest", "")):
            raise PolicyError("fresh preflight digest does not match this operation")
        with self.lock:
            if operation_id in self.threads:
                raise PolicyError("operation is already resuming")
            event = self.cancel_events.get(operation_id)
            if not event or event.is_set():
                raise PolicyError("operation has been cancelled")
            operation["status"] = "started"
            operation["mutation_approval"] = {"at": now_iso(), "preflight_digest": operation["preflight_digest"]}
            self.store.update_operation(operation)
            self.store.append_audit("mutation_approved", {"operation_id": operation_id, "plan_id": plan["id"], "preflight_digest": operation["preflight_digest"]})
            thread = threading.Thread(target=self._run, args=(plan, operation, len(operation.get("commands", []))), daemon=True)
            self.threads[operation_id] = thread
            thread.start()
        return operation

    def _run_one(self, spec: dict[str, Any], operation_id: str) -> dict[str, Any]:
        started = now_iso(); started_mono = time.monotonic()
        argv = list(spec["argv"])
        execution_argv = list(argv)
        identity_path = spec.get("executable_identity", {}).get("realpath")
        if identity_path:
            execution_argv[0] = identity_path
        record: dict[str, Any] = {"argv": [redact(arg) for arg in argv], "display": redact(spec["display"]), "executable": spec["executable"], "adapter_id": spec.get("adapter_id"), "adapter_version": spec.get("adapter_version"), "cwd": spec["cwd"], "started_at": started, "stdout": "", "stderr": "", "exit_code": None, "signal": None, "termination_reason": None, "status": "running", "version": spec["executable_identity"].get("version"), "evidence_digest": None}
        cancel_event = self.cancel_events.get(operation_id)
        try:
            proc = subprocess.Popen(execution_argv, cwd=spec["cwd"], env=minimal_env(False, spec.get("env_additions")), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, start_new_session=True, close_fds=True)
            with self.lock:
                self.processes[operation_id] = proc
            if cancel_event and cancel_event.is_set():
                try: os.killpg(proc.pid, signal.SIGINT)
                except ProcessLookupError: pass
        except FileNotFoundError:
            record.update(status="unavailable", termination_reason="tool_missing", ended_at=now_iso())
            return record
        except OSError as exc:
            record.update(status="failed", termination_reason=redact(str(exc)), ended_at=now_iso())
            return record
        chunks: queue.Queue[tuple[str, bytes]] = queue.Queue()
        def reader(stream: Any, label: str) -> None:
            try:
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        break
                    chunks.put((label, chunk))
            finally:
                stream.close()
        threads = [threading.Thread(target=reader, args=(proc.stdout, "stdout"), daemon=True), threading.Thread(target=reader, args=(proc.stderr, "stderr"), daemon=True)]
        for t in threads: t.start()
        total = 0; truncated = False
        while proc.poll() is None or any(t.is_alive() for t in threads) or not chunks.empty():
            if cancel_event and cancel_event.is_set() and proc.poll() is None:
                record["termination_reason"] = "cancelled"
                try: os.killpg(proc.pid, signal.SIGINT)
                except ProcessLookupError: pass
                time.sleep(0.15)
                if proc.poll() is None:
                    try: os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError: pass
                break
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
        with self.lock:
            self.processes.pop(operation_id, None)
        record["exit_code"] = proc.returncode if proc.returncode is not None and proc.returncode >= 0 else None
        record["signal"] = -proc.returncode if proc.returncode is not None and proc.returncode < 0 else None
        record["ended_at"] = now_iso()
        if truncated:
            record["status"] = "timed_out"; record["termination_reason"] = "output_truncated"
        elif record["termination_reason"] == "cancelled" or (cancel_event and cancel_event.is_set()):
            record["status"] = "cancelled"; record["termination_reason"] = "cancelled"
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

    def _preflight_gate(self, plan: dict[str, Any], op: dict[str, Any]) -> str | None:
        """Validate fresh read-only facts before a guarded mutation."""
        adapters = {spec.get("adapter_id") for spec in plan.get("commands", [])}
        if "linux.packages.apt" in adapters:
            facts = parse_package_facts(op.get("commands", []))
            preflight = facts.get("preflight") or {}
            if preflight.get("state") != "observed":
                return "fresh apt preflight was not observed; mutation was not run"
            # Install/upgrade preflights explicitly carry --no-remove. If a
            # backend nevertheless reports removals, stop rather than accepting
            # a changed dependency impact after approval.
            mutation = plan.get("commands", [])[-1].get("argv", [])
            if any(action in mutation for action in ("install", "upgrade")) and preflight.get("removed", 0) > 0:
                return "fresh apt preflight reported removals; mutation was not run"
            if mutation and "remove" in mutation and preflight.get("removed", 0) == 0:
                return "fresh apt preflight reported no package removal; mutation was not run"
        if "linux.systemd.mutate" in adapters:
            facts = parse_systemd_facts(op.get("commands", []))
            unit = facts.get("unit") or {}
            if unit.get("state") != "observed":
                return "fresh systemd state was not observed; mutation was not run"
            if unit.get("load_state") in (None, "not-found", "bad-setting"):
                return "systemd unit is not loaded; mutation was not run"
        return None

    def _collect_adapter_facts(self, plan: dict[str, Any], op: dict[str, Any]) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for spec, command in zip(plan.get("commands", []), op.get("commands", [])):
            adapter_id = spec.get("adapter_id")
            if adapter_id:
                grouped.setdefault(adapter_id, []).append(command)
        facts: dict[str, Any] = {}
        for adapter_id, results in grouped.items():
            if adapter_id == "linux.packages.apt": facts[adapter_id] = parse_package_facts(results)
            elif adapter_id in ("linux.systemd.inspect", "linux.systemd.mutate"): facts[adapter_id] = parse_systemd_facts(results)
            elif adapter_id == "linux.containers.logs": facts[adapter_id] = parse_container_logs(results)
            elif adapter_id == "linux.ssh.connection": facts[adapter_id] = parse_ssh_connection(results)
        return facts

    def _collect_artifacts(self, plan: dict[str, Any], op: dict[str, Any]) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for spec, command in zip(plan.get("commands", []), op.get("commands", [])):
            adapter_id = spec.get("adapter_id")
            try:
                if adapter_id == "security.http.headers":
                    artifact = analyze_operation_http(command.get("stdout", ""), op["id"])
                elif adapter_id == "security.nmap.discovery":
                    argv = spec.get("argv", [])
                    output_path = argv[argv.index("-oX") + 1] if "-oX" in argv and argv.index("-oX") + 1 < len(argv) else None
                    if not output_path or not Path(output_path).exists():
                        artifact = {"schema_version": 1, "artifact_id": secrets.token_hex(16), "kind": "nmap-xml", "source": {"kind": "generated_file", "path": output_path}, "size_bytes": 0, "sha256": "", "parser": {"id": "nmap.xml", "version": "1"}, "state": "not_run", "error": "nmap produced no XML artifact", "observations": [], "summary": "No Nmap XML artifact was available to parse."}
                        artifact["operation_id"] = op["id"]
                        self.store.save_artifact(artifact, op["id"])
                        artifacts.append(artifact)
                        continue
                    artifact = analyze_path(output_path, "nmap-xml")
                    if os.environ.get("VORTEX_RETAIN_RAW_EVIDENCE") != "1":
                        try: os.unlink(output_path)
                        except OSError: pass
                    else:
                        try: Path(output_path).chmod(0o600)
                        except OSError: pass
                else:
                    continue
                artifact["operation_id"] = op["id"]
                self.store.save_artifact(artifact, op["id"])
                artifacts.append(artifact)
            except ArtifactError as exc:
                artifact = {"schema_version": 1, "artifact_id": secrets.token_hex(16), "kind": "unknown", "source": {"kind": "operation_output", "operation_id": op["id"]}, "size_bytes": 0, "sha256": "", "parser": {"id": adapter_id or "unknown", "version": "1"}, "state": "tool_error", "error": redact(str(exc)), "observations": [], "operation_id": op["id"]}
                self.store.save_artifact(artifact, op["id"])
                artifacts.append(artifact)
        return artifacts

    def _run(self, plan: dict[str, Any], op: dict[str, Any], start_index: int = 0) -> None:
        try:
            op["status"] = "running"; self.store.update_operation(op)
            for index in range(start_index, len(plan["commands"])):
                spec = plan["commands"][index]
                if self.cancel_events.get(op["id"], threading.Event()).is_set():
                    break
                result = self._run_one(spec, op["id"])
                op["commands"].append(result)
                self.store.update_operation(op)
                current_spec = plan["commands"][index]
                if result["status"] != "succeeded" and not current_spec.get("allow_failure", False):
                    break
                if len(op["commands"]) < len(plan.get("commands", [])):
                    completed_spec = plan["commands"][len(op["commands"]) - 1]
                    is_fresh_apt_preflight = completed_spec.get("adapter_id") == "linux.packages.apt" and completed_spec.get("executable") == "apt-get" and "-s" in completed_spec.get("argv", [])
                    is_fresh_systemd_state = completed_spec.get("adapter_id") == "linux.systemd.mutate" and completed_spec.get("executable") == "systemctl" and "show" in completed_spec.get("argv", [])
                    if is_fresh_apt_preflight or is_fresh_systemd_state:
                        gate_error = self._preflight_gate(plan, op)
                        if gate_error:
                            op["execution_gate"] = {"state": "blocked", "reason": gate_error}
                            break
                        if self._has_guarded_mutation(plan):
                            op["facts"] = self._collect_adapter_facts(plan, op)
                            op["preflight_digest"] = hashlib.sha256(canonical(op["commands"]).encode()).hexdigest()
                            op["preflight"] = {"state": "ready", "next_command": plan["commands"][len(op["commands"])] ["display"], "digest": op["preflight_digest"]}
                            op["status"] = "awaiting_confirmation"
                            op["analysis"] = make_analysis(plan, op)
                            self.store.update_operation(op)
                            self.store.append_audit("preflight_ready", {"operation_id": op["id"], "plan_id": plan["id"], "preflight_digest": op["preflight_digest"]})
                            with self.lock:
                                self.threads.pop(op["id"], None)
                            return
            statuses = [x["status"] for x in op["commands"]]
            if op.get("execution_gate", {}).get("state") == "blocked": op["status"] = "failed"
            elif self.cancel_events.get(op["id"], threading.Event()).is_set(): op["status"] = "cancelled"
            elif any(s == "timed_out" for s in statuses): op["status"] = "timed_out"
            elif any(s == "interrupted" for s in statuses): op["status"] = "interrupted"
            elif any(s == "unavailable" for s in statuses): op["status"] = "unavailable"
            elif all(s == "succeeded" for s in statuses) and statuses: op["status"] = "succeeded"
            else: op["status"] = "failed"
        except Exception as exc:
            op["status"] = "unknown_after_crash"; op["error"] = redact(str(exc))
        op["ended_at"] = now_iso()
        op["output_digest"] = hashlib.sha256(canonical(op["commands"]).encode()).hexdigest()
        op["facts"] = self._collect_adapter_facts(plan, op)
        op["artifacts"] = self._collect_artifacts(plan, op)
        op["analysis"] = make_analysis(plan, op)
        self.store.update_operation(op)
        self.store.append_audit("operation_finished", {"operation_id": op["id"], "plan_id": plan["id"], "status": op["status"], "output_digest": op["output_digest"]})
        workspace = getattr(self, "workspace", None)
        if workspace is not None:
            try:
                finish_task = _load("orchestrate").finish_task
                task = workspace.find_task_by_plan(plan["id"])
                if task:
                    finish_task(workspace, task["id"], op, plan, executor=self, store=self.store)
            except Exception as exc:
                try:
                    self.store.append_audit("task_finish_failed", {"plan_id": plan.get("id"), "operation_id": op.get("id"), "error": redact(str(exc))[:240]})
                except Exception:
                    pass
        with self.lock:
            self.cancel_events.pop(op["id"], None)
            self.threads.pop(op["id"], None)


def build_undo_plan(store: Store, operation_id: str) -> dict[str, Any]:
    operation = store.get_operation(operation_id)
    if not operation:
        raise PolicyError("history id not found")
    if operation.get("status") != "succeeded":
        raise PolicyError("only a verified successful operation can produce rollback guidance")
    original = store.get_plan(operation["plan_id"])
    if not original:
        raise PolicyError("original plan is unavailable")
    rollback = original.get("rollback", {})
    inverse = rollback.get("inverse", [])
    if not rollback.get("available") or len(inverse) != 2:
        raise PolicyError("no verified inverse operation exists; use a snapshot or create a manual plan")
    action, target = inverse
    if action in {"install", "remove"}:
        request = f"{action} package {target}"
    else:
        request = f"{action} {target}"
    plan = build_plan(store, request, original.get("cwd"), original.get("engagement_id"))
    plan["kind"] = "rollback_plan"
    plan["notes"].insert(0, f"Rollback proposal derived from verified operation {operation_id}; it has not been executed.")
    plan["rollback_source_operation"] = operation_id
    # Recompute identity because the provenance annotation is part of the saved
    # plan, while command/scope/policy digest remains bound to the exact action.
    plan["digest"] = plan_digest(plan)
    with store.lock, store.connect() as db:
        db.execute("UPDATE plans SET plan_json=?, digest=? WHERE id=?", (canonical(plan), plan["digest"], plan["id"]))
    store.append_audit("rollback_plan_created", {"operation_id": operation_id, "plan_id": plan["id"], "digest": plan["digest"]})
    return plan


def report_markdown(operation: dict[str, Any]) -> str:
    analysis = operation.get("analysis") or {}
    lines = ["# Linux Vortex operation report", "", f"- Status: **{operation.get('status', 'unknown')}**", f"- Operation: `{operation.get('id', '')}`", f"- Plan: `{operation.get('plan_id', '')}`", f"- Started: `{operation.get('started_at', '')}`", f"- Ended: `{operation.get('ended_at', '')}`", "", "## Observed analysis", "", str(analysis.get("fact", "No analysis was recorded.")), "", "## Command timeline", ""]
    for index, command in enumerate(operation.get("commands", []), 1):
        lines += [f"### {index}. `{command.get('display', '')}`", "", f"- Status: `{command.get('status')}`", f"- Exit code: `{command.get('exit_code')}`", f"- Signal: `{command.get('signal')}`", f"- Evidence digest: `{command.get('evidence_digest')}`", ""]
        if command.get("stdout"): lines += ["```text", command["stdout"], "```", ""]
        if command.get("stderr"): lines += ["### stderr", "", "```text", command["stderr"], "```", ""]
    if analysis.get("rollback"): lines += ["## Rollback guidance", "", str(analysis["rollback"]), ""]
    return "\n".join(lines)


def make_analysis(plan: dict[str, Any], op: dict[str, Any]) -> dict[str, Any]:
    facts = []
    for command in op["commands"]:
        lines = [line for line in (command.get("stdout", "") + command.get("stderr", "")).splitlines() if line.strip()]
        facts.append({"command": command["display"], "status": command["status"], "observed_lines": len(lines), "evidence_digest": command.get("evidence_digest"), "summary": (lines[0][:220] if lines else "No output was observed; this is not evidence of a clean result.")})
    return {
        "lifecycle": {"succeeded": "EXECUTED", "failed": "FAILED", "cancelled": "CANCELLED", "awaiting_confirmation": "PREFLIGHT COMPLETE", "interrupted": "INTERRUPTED", "timed_out": "TIMED OUT", "unavailable": "TOOL MISSING", "unknown_after_crash": "BACKEND OFFLINE"}.get(op["status"], "NOT RUN"),
        "fact": f"{len(op['commands'])} real command(s) reached an observed terminal outcome." if op["commands"] else "No command was run.",
        "inference": "Output summaries are bounded and redacted. They are observations, not a security guarantee.",
        "unknown": "Parser confidence is limited because this vertical slice stores raw text evidence; no vulnerability is confirmed without a reviewed parser and matching rule. Tool output is untrusted data and never overrides Guardian policy.",
        "untrusted_output": True,
        "commands": facts,
        "adapter_facts": op.get("facts", {}),
        "execution_gate": op.get("execution_gate"),
        "rollback": plan.get("rollback"),
        "network_facts": op.get("network_facts", plan.get("network_facts", {})),
        "artifacts": [{"artifact_id": item.get("artifact_id"), "kind": item.get("kind"), "state": item.get("state"), "sha256": item.get("sha256"), "summary": item.get("summary"), "observations": item.get("observations", [])[:20]} for item in op.get("artifacts", [])],
        "next_steps": [{"label": "explain", "text": "Review the observed command timeline and evidence digests."}, {"label": "plan only", "text": "Ask a new question for a narrower, reviewed follow-up."}],
        "workers": op["workers"],
    }


def parse_expiry(raw: Any, *, default_seconds: int) -> str:
    if raw is None or raw == "":
        value = datetime.fromtimestamp(time.time() + default_seconds, tz=timezone.utc)
    elif not isinstance(raw, str):
        raise ValueError("expires_at must be an ISO-8601 string")
    else:
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("expires_at must be valid ISO-8601") from exc
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
    if value.timestamp() <= time.time():
        raise ValueError("expires_at must be in the future")
    return value.isoformat(timespec="milliseconds")


def capabilities_document() -> dict[str, Any]:
    docker = probe_executable("docker")
    podman = probe_executable("podman")
    nmap = probe_executable("nmap")
    try:
        agents = _load("agents.council").discover()
    except Exception:
        agents = []
    installed_agents = [item["id"] for item in agents if item.get("health", {}).get("healthy")]
    return {
        "product": "VORTEX",
        "version": APP_VERSION,
        "implemented": [
            "typed-plan-execution", "pty-sessions", "guardian", "engagements",
            "workspace-turn", "tasks", "conversations", "reports", "assessment-reports",
            "secret-slots", "sse-operations", "sse-sessions", "stop-all", "audit-chain",
            "episode-observe-act-evaluate",
            "nuclei-ffuf-nikto-amass-gobuster-adapters",
        ],
        "host_probes": {
            "docker": docker.get("state"),
            "podman": podman.get("state"),
            "nmap": nmap.get("state"),
            "agents_installed": installed_agents,
            "agents_catalog": [item.get("id") for item in agents],
        },
        "unavailable_unless_installed": [
            "docker-sandbox-execution",
            "ollama-inference",
            "external-agent-consult",
            "sqlmap-msfconsole-execution",
        ],
        "intentionally_not_implemented": [
            "fastapi-postgresql-pgvector",
            "plugin-code-execution",
            "silent-third-party-install",
            "unrestricted-llm-os-control",
        ],
    }


class VortexHandler(BaseHTTPRequestHandler):
    store: Store
    executor: ExecutionManager
    sessions: SessionManager
    workspace: Any
    frontend: Path
    token: str | None = None
    server_version = "VortexSidecar/0.2"

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
        raw_len = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_len)
        except (TypeError, ValueError):
            raise ValueError("invalid content length")
        if length < 0 or length > 256 * 1024:
            raise ValueError("request too large")
        payload = json.loads(self.rfile.read(length) or b"{}")
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        return payload

    @staticmethod
    def _flag(body: dict[str, Any], key: str) -> bool:
        return body.get(key) is True

    @staticmethod
    def _text(body: dict[str, Any], key: str) -> str | None:
        value = body.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        return value

    @staticmethod
    def _optional_str(body: dict[str, Any], key: str) -> str | None:
        value = body.get(key)
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        return value

    @staticmethod
    def _report_format(query: dict[str, list[str]], default: str = "json") -> str:
        fmt = (query.get("format") or [default])[0]
        if not isinstance(fmt, str) or fmt.lower() not in {"md", "html", "json", "pdf"}:
            raise ValueError("report format must be md, html, json, or pdf")
        return fmt.lower()

    @staticmethod
    def _bounded_int(body: dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
        value = body.get(key, default)
        if value is None:
            value = default
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError(f"{key} must be an integer")
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be an integer") from exc
        return max(lo, min(number, hi))

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT); self._headers(); self.end_headers()

    def do_GET(self) -> None:
        if not self._authorized(): return self._json(HTTPStatus.UNAUTHORIZED, {"error": {"code": "unauthorized", "message": "invalid sidecar capability"}})
        parsed = urllib.parse.urlparse(self.path); path = parsed.path
        try:
            if path == "/api/health":
                try:
                    load_settings = _load("config").load_settings
                    collect = _load("health").collect
                    payload = collect(self.store, self.sessions, load_settings())
                    return self._json(200, {"ok": True, "version": APP_VERSION, "backend": "online", "health": payload, "offline": payload.get("offline"), "interrupted_tasks": self.workspace.interrupted_tasks()})
                except Exception as exc:
                    return self._json(200, {"ok": False, "version": APP_VERSION, "backend": "online", "health_error": redact(str(exc))})
            if path == "/api/system/health":
                load_settings = _load("config").load_settings
                collect = _load("health").collect
                return self._json(200, {"health": collect(self.store, self.sessions, load_settings())})
            if path == "/api/capabilities":
                return self._json(200, capabilities_document())
            if path == "/api/agents":
                from agents.council import discover
                return self._json(200, {"agents": discover()})
            if path == "/api/models":
                load_settings = _load("config").load_settings
                from models.router import model_status
                return self._json(200, {"model": model_status(load_settings())})
            if path == "/api/settings":
                load_settings = _load("config").load_settings
                return self._json(200, {"settings": load_settings()})
            if path == "/api/setup":
                load_settings = _load("config").load_settings
                setup_checks = _load("health").setup_checks
                return self._json(200, {"setup": setup_checks(self.store, load_settings())})
            if path == "/api/dependencies":
                deps = _load("dependencies")
                return self._json(200, {"dependencies": deps.inventory()})
            if path == "/api/dependencies/proposal":
                deps = _load("dependencies")
                query = urllib.parse.parse_qs(parsed.query)
                item_id = (query.get("id") or [""])[0]
                return self._json(200, {"install": deps.proposal_for(item_id)})
            if path == "/api/sandbox":
                from sandbox import isolation_status
                return self._json(200, {"sandbox": isolation_status()})
            if path == "/api/secrets":
                secret_status = _load("secretstore").status
                return self._json(200, {"secrets": secret_status()})
            if path.startswith("/api/operations/") and path.endswith("/stream"):
                op_id = path.split("/")[-2]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                for _ in range(300):
                    op = self.store.get_operation(op_id)
                    payload = json.dumps({"schema_version": SCHEMA_VERSION, "operation": op})
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    if not op or op.get("status") not in ("started", "running"):
                        break
                    time.sleep(0.2)
                return
            if path == "/api/findings":
                return self._json(200, {"findings": self.workspace.list_findings()})
            if path == "/api/learning/agents":
                return self._json(200, {"scores": self.workspace.agent_scores()})
            if path == "/api/tools/route":
                from tools.router import route
                query = urllib.parse.parse_qs(parsed.query)
                return self._json(200, {"route": route((query.get("q") or [""])[0])})
            if path == "/api/plugins":
                from plugins.loader import list_manifests
                return self._json(200, {"plugins": list_manifests()})
            if path == "/api/tools/registry":
                from tools.registry import by_category, inventory
                return self._json(200, {"tools": inventory(), "categories": by_category()})
            if path == "/api/reports/system":
                render_system = _load("reports.engine").render_system
                from tools.registry import inventory
                query = urllib.parse.parse_qs(parsed.query)
                fmt = self._report_format(query, "json")
                data, content_type, ext = render_system(fmt, detect_context(), inventory())
                self.send_response(200)
                self._headers(content_type)
                self.send_header("Content-Disposition", f'attachment; filename="vortex-system.{ext}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/conversations":
                query = urllib.parse.parse_qs(parsed.query)
                return self._json(200, {"conversations": self.workspace.list_conversations((query.get("q") or [None])[0])})
            if path.startswith("/api/conversations/") and path.endswith("/export"):
                cid = path.split("/")[-2]
                payload = {"schema_version": SCHEMA_VERSION, "export": self.workspace.export_conversation(cid)}
                raw = (canonical(payload) + "\n").encode()
                self.send_response(200)
                self._headers("application/json")
                self.send_header("Content-Disposition", f'attachment; filename="conversation-{cid[:12]}.json"')
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            if path.startswith("/api/conversations/"):
                cid = path.rsplit("/", 1)[-1]
                item = self.workspace.get_conversation(cid)
                if not item:
                    return self._json(404, {"error": {"code": "not_found", "message": "conversation not found"}})
                return self._json(200, {"conversation": item, "messages": self.workspace.list_messages(cid)})
            if path == "/api/tasks":
                return self._json(200, {"tasks": self.workspace.list_tasks(), "interrupted": self.workspace.interrupted_tasks()})
            if path.startswith("/api/tasks/") and path.endswith("/events"):
                task_id = path.split("/")[-2]
                item = self.workspace.get_task(task_id)
                if not item:
                    return self._json(404, {"error": {"code": "not_found", "message": "task not found"}})
                return self._json(200, {"task": item, "events": self.workspace.list_task_events(task_id)})
            if path.startswith("/api/tasks/") and path.endswith("/episode"):
                task_id = path.split("/")[-2]
                item = self.workspace.get_task(task_id)
                if not item:
                    return self._json(404, {"error": {"code": "not_found", "message": "task not found"}})
                return self._json(200, {
                    "task": item,
                    "observation": (item.get("result") or {}).get("observation"),
                    "episode": (item.get("result") or {}).get("episode"),
                    "events": [row for row in self.workspace.list_task_events(task_id) if row.get("kind") == "episode_step"],
                })
            if path.startswith("/api/tasks/") and path.count("/") == 3:
                item = self.workspace.get_task(path.rsplit("/", 1)[-1])
                return self._json(200 if item else 404, {"task": item} if item else {"error": {"code": "not_found", "message": "task not found"}})
            if path == "/api/memory":
                return self._json(200, {"memories": self.workspace.list_memories()})
            if path == "/api/learning":
                return self._json(200, {"experiences": self.workspace.list_experiences(), "procedures": self.workspace.list_procedures()})
            if path == "/api/reports":
                return self._json(200, {"reports": self.workspace.list_reports()})
            if path.startswith("/api/reports/") and path.endswith("/download"):
                report_id = path.split("/")[-2]
                query = urllib.parse.parse_qs(parsed.query)
                fmt = self._report_format(query, "md")
                report = self.workspace.get_report(report_id)
                if not report:
                    return self._json(404, {"error": {"code": "not_found", "message": "report not found"}})
                operation = self.store.get_operation(report.get("operation_id") or "") or {"status": report.get("body", {}).get("status"), "commands": [], "id": report.get("operation_id"), "plan_id": "", "analysis": {"fact": report.get("body", {}).get("markdown", "")}}
                plan = self.store.get_plan(operation.get("plan_id") or "") if operation.get("plan_id") else {}
                task = self.workspace.get_task(report.get("task_id") or "") if report.get("task_id") else None
                render = _load("reports.engine").render
                data, content_type, ext = render(fmt, operation, plan or {}, task)
                self.send_response(200)
                self._headers(content_type)
                self.send_header("Content-Disposition", f'attachment; filename="{report_id}.{ext}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/doctor": return self._json(200, {"doctor": detect_context()})
            if path == "/api/tools": return self._json(200, {"tools": [probe_executable(name) | {"family": meta["family"], "role": meta["role"]} for name, meta in TOOL_CATALOG.items()]})
            if path == "/api/adapters": return self._json(200, {"adapters": [{"id": adapter_id, **manifest, "tool_state": [probe_executable(tool)["state"] for tool in manifest["tool"].split("+") if tool != "multiple"]} for adapter_id, manifest in ADAPTER_MANIFESTS.items()]})
            if path == "/api/sessions": return self._json(200, {"sessions": self.sessions.list()})
            if path.startswith("/api/sessions/"):
                parts = path.split("/")
                if len(parts) == 5 and parts[-1] == "stream":
                    session_id = parts[-2]
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Accel-Buffering", "no")
                    self.end_headers()
                    since = 0
                    for _ in range(300):
                        payload = self.sessions.events_since(session_id, since)
                        self.wfile.write(f"data: {json.dumps({'schema_version': SCHEMA_VERSION, **payload})}\n\n".encode())
                        self.wfile.flush()
                        events = payload.get("events") or []
                        if events:
                            since = events[-1]["seq"]
                        status = (payload.get("session") or {}).get("status")
                        if not payload.get("session") or status not in ("starting", "running"):
                            break
                        time.sleep(0.2)
                    return
                if len(parts) == 5 and parts[-1] == "events":
                    query = urllib.parse.parse_qs(parsed.query)
                    return self._json(200, self.sessions.events_since(parts[-2], query.get("since", [0])[0]))
                if len(parts) == 4:
                    session = self.sessions.info(parts[-1])
                    return self._json(200 if session else 404, {"session": session} if session else {"error": {"code": "not_found", "message": "session not found"}})
            if path == "/api/artifacts": return self._json(200, {"artifacts": self.store.list_artifacts()})
            if path == "/api/history": return self._json(200, {"history": self.store.list_history()})
            if path == "/api/engagements":
                items = [self.workspace.enrich_engagement(item) for item in self.store.list_engagements()]
                return self._json(200, {"engagements": items})
            if path.startswith("/api/agents/") and path.endswith("/install"):
                from agents.install import proposal
                return self._json(200, {"install": proposal(path.split("/")[-2])})
            if path.startswith("/api/reports/assessment/"):
                from reports.assessment import as_operation_view, build
                from reports.engine import render
                eng_id = path.rsplit("/", 1)[-1]
                engagement = self.workspace.enrich_engagement(self.store.get_engagement(eng_id))
                if not engagement:
                    return self._json(404, {"error": {"code": "not_found", "message": "engagement not found"}})
                findings = [item for item in self.workspace.list_findings() if item.get("engagement_id") == eng_id]
                operations = self.workspace.operations_for_engagement(eng_id)
                document = build(engagement, findings, operations)
                query = urllib.parse.parse_qs(parsed.query)
                fmt = (query.get("format") or ["json"])[0]
                if fmt == "json":
                    return self._json(200, {"report": document})
                data, content_type, ext = render(fmt, as_operation_view(document), {"request": "assessment"}, {"id": eng_id})
                self.send_response(200)
                self._headers(content_type)
                self.send_header("Content-Disposition", f'attachment; filename="assessment-{eng_id[:8]}.{ext}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/audit/verify": return self._json(200, {"audit": self.store.verify_audit()})
            if path == "/api/store/integrity": return self._json(200, {"integrity": self.store.integrity_check()})
            if path.startswith("/api/plans/"):
                plan = self.store.get_plan(path.rsplit("/", 1)[-1])
                if not plan:
                    return self._json(404, {"error": {"code": "not_found", "message": "plan not found"}})
                public = dict(plan)
                public.pop("approval_token", None)
                return self._json(200, {"plan": public})
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
                def is_under(candidate: Path, root: Path) -> bool:
                    try:
                        return os.path.commonpath((str(candidate), str(root))) == str(root)
                    except ValueError:
                        return False
                if any(is_under(asset, root) for root in allowed) and asset.is_file(): return self._static(asset, mime)
            return self._json(404, {"error": {"code": "not_found", "message": "route not found"}})
        except (ValueError, PolicyError) as exc:
            return self._json(422, {"error": {"code": "invalid_plan", "message": redact(str(exc)), "exit_code": EXIT_CODES["policy_denied"]}})
        except (sqlite3.IntegrityError, sqlite3.DatabaseError) as exc:
            return self._json(409, {"error": {"code": "persistence_integrity", "message": redact(str(exc)), "exit_code": EXIT_CODES["integrity_failure"]}})
        except Exception as exc:
            return self._json(500, {"error": {"code": "internal_error", "message": redact(str(exc))}})

    def _static(self, path: Path, content_type: str) -> None:
        data = path.read_bytes(); self.send_response(200); self._headers(content_type); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_POST(self) -> None:
        if not self._authorized(): return self._json(HTTPStatus.UNAUTHORIZED, {"error": {"code": "unauthorized", "message": "invalid sidecar capability"}})
        path = urllib.parse.urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/sessions":
                session = self.sessions.create(self._optional_str(body, "name"), self._optional_str(body, "cwd"), self._optional_str(body, "shell"), self._bounded_int(body, "cols", 100, 2, 500), self._bounded_int(body, "rows", 30, 2, 500))
                return self._json(201, {"session": session})
            if path.startswith("/api/sessions/"):
                parts = path.split("/")
                if len(parts) == 5 and parts[-1] == "input":
                    data = self._text(body, "data")
                    if data is None:
                        raise ValueError("session input data is required")
                    session = self.sessions.write(parts[-2], data)
                    return self._json(200, {"session": session})
                if len(parts) == 5 and parts[-1] == "resize":
                    session = self.sessions.resize(parts[-2], self._bounded_int(body, "cols", 100, 2, 500), self._bounded_int(body, "rows", 30, 2, 500))
                    return self._json(200, {"session": session})
                if len(parts) == 5 and parts[-1] == "kill":
                    if not self.sessions.kill(parts[-2]):
                        return self._json(404, {"error": {"code": "not_running", "message": "session is not running"}})
                    return self._json(202, {"kill_requested": True, "session_id": parts[-2]})
            if path == "/api/store/prune":
                result = self.store.prune(self._bounded_int(body, "history_days", 90, 1, 3650), self._bounded_int(body, "output_days", 30, 1, 3650))
                return self._json(200, {"prune": result})
            if path == "/api/store/backup":
                destination = body.get("destination")
                if not isinstance(destination, str) or not destination.strip(): raise ValueError("backup destination is required")
                name = Path(destination.strip()).name
                if not name or name.startswith("."):
                    raise PolicyError("backup filename is required")
                if not name.endswith(".db"):
                    name += ".db"
                dest = self.store.root / "backups" / name
                backup_path = self.store.backup(str(dest), self._flag(body, "overwrite"))
                return self._json(201, {"backup": {"path": str(backup_path), "mode": oct(backup_path.stat().st_mode & 0o777)}})
            if path == "/api/artifacts/analyze":
                path_value = self._text(body, "path")
                if not path_value:
                    raise ValueError("artifact path is required")
                artifact = analyze_path(path_value, self._optional_str(body, "kind") or "auto", allowed_roots=[self.store.root])
                self.store.save_artifact(artifact)
                return self._json(201, {"artifact": artifact})
            if path == "/api/plan":
                request = body.get("request")
                if not isinstance(request, str):
                    raise ValueError("request must be a string")
                plan = build_plan(self.store, request, self._optional_str(body, "cwd"), self._optional_str(body, "engagement_id"), self._flag(body, "offline")); return self._json(200, {"plan": plan})
            if path == "/api/execute":
                plan_id = self._optional_str(body, "plan_id")
                if not plan_id:
                    raise ValueError("plan_id is required")
                plan = self.store.get_plan(plan_id)
                if not plan: return self._json(404, {"error": {"code": "not_found", "message": "plan not found"}})
                settings = _load("config").load_settings()
                offline = settings.get("offline") is True or self._flag(body, "offline")
                # HTTP never grants UID 0 override; only an explicit CLI --allow-root may.
                op = self.executor.start(plan, self._flag(body, "confirm"), self._text(body, "approval_token"), False, offline); return self._json(202, {"operation": op})
            if path == "/api/engagements":
                raw_targets = body.get("targets", [])
                if raw_targets is None:
                    raw_targets = []
                if not isinstance(raw_targets, list) or not all(isinstance(x, str) and x.strip() for x in raw_targets):
                    raise ValueError("targets must be a list of non-empty strings")
                targets = [normalize_target(x) for x in raw_targets]
                if not targets or len(targets) > 100: raise PolicyError("provide between 1 and 100 canonical targets")
                raw_classes = body.get("classes")
                if raw_classes is None:
                    raw_classes = ["reconnaissance"]
                if not isinstance(raw_classes, list) or not all(isinstance(x, str) and x for x in raw_classes):
                    raise ValueError("classes must be a list of non-empty strings")
                expires = parse_expiry(body.get("expires_at"), default_seconds=24 * 3600)
                item = {"schema_version": SCHEMA_VERSION, "id": secrets.token_hex(16), "created_at": now_iso(), "expires_at": expires, "name": redact(self._optional_str(body, "name") or "Authorized assessment")[:160], "authorization": redact(self._optional_str(body, "authorization") or "operator-declared authorization")[:500], "targets": targets, "classes": [redact(x)[:80] for x in raw_classes[:20]], "status": "active"}
                self.store.create_engagement(item)
                excluded = body.get("excluded_targets")
                if excluded is None:
                    excluded = []
                if not isinstance(excluded, list) or not all(isinstance(x, str) and x for x in excluded):
                    raise ValueError("excluded_targets must be a list of non-empty strings")
                self.workspace.save_engagement_scope(item["id"], excluded[:100], self._optional_str(body, "environment") or "", self._optional_str(body, "owner") or "")
                item = self.workspace.enrich_engagement(item)
                return self._json(201, {"engagement": item})
            if path.startswith("/api/operations/") and path.endswith("/approve"):
                operation_id = path.split("/")[-2]
                operation = self.executor.approve_preflight(operation_id, self._flag(body, "confirm"), self._text(body, "approval_token"), self._text(body, "preflight_digest"))
                return self._json(202, {"operation": operation})
            if path.startswith("/api/operations/") and path.endswith("/cancel"):
                operation_id = path.split("/")[-2]
                if not self.executor.cancel(operation_id):
                    return self._json(404, {"error": {"code": "not_running", "message": "operation is not running"}})
                return self._json(202, {"cancel_requested": True, "operation_id": operation_id})
            if path == "/api/feedback":
                rating = self._bounded_int(body, "rating", 1, 1, 5); correction = redact(self._optional_str(body, "correction") or "")[:2000]
                self.store.append_audit("feedback_recorded", {"operation_id": self._optional_str(body, "operation_id"), "rating": rating, "correction": correction}); return self._json(201, {"saved": True})
            if path == "/api/workspace/turn":
                load_settings = _load("config").load_settings
                run_turn = _load("orchestrate").run_turn
                request = body.get("request")
                if not isinstance(request, str) or not request.strip():
                    raise ValueError("request must be a string")
                settings = load_settings()
                if self._flag(body, "offline"):
                    settings["offline"] = True
                result = run_turn(self.store, self.workspace, self.executor, request.strip(), cwd=self._optional_str(body, "cwd"), engagement_id=self._optional_str(body, "engagement_id"), conversation_id=self._optional_str(body, "conversation_id"), settings=settings, confirm=self._flag(body, "confirm"), approval_token=self._text(body, "approval_token"))
                return self._json(200, result)
            if path == "/api/conversations":
                title = self._optional_str(body, "title") or "New conversation"
                return self._json(201, {"conversation": self.workspace.create_conversation(title)})
            if path.startswith("/api/conversations/") and path.endswith("/rename"):
                item = self.workspace.rename_conversation(path.split("/")[-2], self._text(body, "title") or "")
                if not item:
                    return self._json(404, {"error": {"code": "not_found", "message": "conversation not found"}})
                return self._json(200, {"conversation": item})
            if path.startswith("/api/conversations/") and path.endswith("/archive"):
                self.workspace.archive_conversation(path.split("/")[-2]); return self._json(200, {"archived": True})
            if path.startswith("/api/conversations/") and path.endswith("/delete"):
                self.workspace.delete_conversation(path.split("/")[-2]); return self._json(200, {"deleted": True})
            if path.startswith("/api/conversations/") and path.endswith("/edit"):
                parts = path.split("/")
                if len(parts) != 6 or parts[1] != "api" or parts[2] != "conversations" or parts[4] != "messages":
                    return self._json(404, {"error": {"code": "not_found", "message": "route not found"}})
                branch = self.workspace.edit_and_branch(parts[3], parts[5], self._text(body, "content") or "")
                return self._json(201, {"conversation": branch, "messages": self.workspace.list_messages(branch["id"])})
            if path.startswith("/api/engagements/") and path.endswith("/close"):
                eng_id = path.split("/")[-2]
                if not self.store.close_engagement(eng_id):
                    return self._json(404, {"error": {"code": "not_found", "message": "engagement not found or already closed"}})
                return self._json(200, {"engagement": self.workspace.enrich_engagement(self.store.get_engagement(eng_id))})
            if path.startswith("/api/plans/") and path.endswith("/reject"):
                plan_id = path.split("/")[-2]
                result = self.workspace.reject_task_plan(plan_id, self._optional_str(body, "task_id"), self.executor)
                if not result.get("rejected") and not result.get("task"):
                    return self._json(404, {"error": {"code": "not_found", "message": "plan not found or not rejectable"}})
                return self._json(200, {"rejected": True, "plan_id": plan_id, "task": result.get("task")})
            if path.startswith("/api/tasks/") and path.endswith("/pause"):
                task = self.workspace.pause_task(path.split("/")[-2], self.executor)
                if not task:
                    return self._json(404, {"error": {"code": "not_found", "message": "task not found"}})
                return self._json(200, {"task": task})
            if path == "/api/secrets":
                put = _load("secretstore").put
                slot = self._text(body, "slot")
                value = self._text(body, "value")
                if not slot:
                    raise ValueError("slot is required")
                return self._json(200, {"secrets": put(slot, value or "")})
            if path == "/api/control/stop-all":
                stop_all = _load("orchestrate").stop_all
                result = stop_all(self.executor, self.sessions, self.workspace)
                self.store.append_audit("stop_all", result)
                return self._json(202, {"stop": result})
            if path == "/api/settings":
                save_settings = _load("config").save_settings
                return self._json(200, {"settings": save_settings(body if isinstance(body, dict) else {})})
            if path == "/api/setup/complete":
                save_settings = _load("config").save_settings
                return self._json(200, {"settings": save_settings({"first_run_complete": True})})
            if path == "/api/dependencies/plan":
                deps = _load("dependencies")
                item_id = self._optional_str(body, "id") or ""
                proposal = deps.proposal_for(item_id)
                if proposal.get("installed") or proposal.get("method") != "apt" or not proposal.get("plan_request"):
                    return self._json(200, {"install": proposal, "planned": False, "auto_install": False})
                result = _load("orchestrate").run_turn(
                    self.store, self.workspace, self.executor, proposal["plan_request"],
                    cwd=self._optional_str(body, "cwd"), engagement_id=None, conversation_id=self._optional_str(body, "conversation_id"),
                    settings=_load("config").load_settings(),
                )
                return self._json(200, {"install": proposal, "planned": True, "auto_install": False, **result})
            if path.startswith("/api/tasks/") and path.endswith("/resume"):
                load_settings = _load("config").load_settings
                run_turn = _load("orchestrate").run_turn
                task = self.workspace.get_task(path.split("/")[-2])
                if not task:
                    return self._json(404, {"error": {"code": "not_found", "message": "task not found"}})
                result = run_turn(self.store, self.workspace, self.executor, task["request"], cwd=self._optional_str(body, "cwd"), engagement_id=task.get("engagement_id"), conversation_id=task.get("conversation_id"), settings=load_settings())
                return self._json(200, result)
            if path.startswith("/api/tasks/") and path.endswith("/restart"):
                load_settings = _load("config").load_settings
                run_turn = _load("orchestrate").run_turn
                task = self.workspace.get_task(path.split("/")[-2])
                if not task:
                    return self._json(404, {"error": {"code": "not_found", "message": "task not found"}})
                self.workspace.update_task(task["id"], state="CANCELLED")
                result = run_turn(self.store, self.workspace, self.executor, task["request"], cwd=self._optional_str(body, "cwd"), engagement_id=task.get("engagement_id"), conversation_id=task.get("conversation_id"), settings=load_settings())
                return self._json(200, result)
            if path.startswith("/api/tasks/") and path.endswith("/delete"):
                task = self.workspace.delete_task(path.split("/")[-2])
                if not task:
                    return self._json(404, {"error": {"code": "not_found", "message": "task not found"}})
                return self._json(200, {"task": task})
            if path.startswith("/api/operations/") and path.endswith("/complete-task"):
                finish_task = _load("orchestrate").finish_task
                operation_id = path.split("/")[-2]
                task_id = self._optional_str(body, "task_id")
                if not task_id:
                    raise ValueError("task_id is required")
                operation = self.store.get_operation(operation_id)
                if not operation:
                    return self._json(404, {"error": {"code": "not_found", "message": "operation not found"}})
                task = self.workspace.get_task(task_id)
                if not task:
                    return self._json(404, {"error": {"code": "not_found", "message": "task not found"}})
                if task.get("operation_id") and task["operation_id"] != operation_id:
                    raise PolicyError("task is not bound to this operation")
                if task.get("plan_id") and operation.get("plan_id") and task["plan_id"] != operation["plan_id"]:
                    raise PolicyError("task is not bound to this plan")
                plan = self.store.get_plan(operation.get("plan_id") or "") or {}
                report = finish_task(self.workspace, task_id, operation, plan)
                return self._json(200, {"operation": operation, "report": report, "task": self.workspace.get_task(task_id)})
            if path == "/api/benchmark":
                from benchmark import run_suite
                return self._json(200, {"benchmark": run_suite(self.store, self.workspace, self.executor, self._optional_str(body, "cwd"))})
            return self._json(404, {"error": {"code": "not_found", "message": "route not found"}})
        except PermissionError as exc:
            return self._json(403, {"error": {"code": "confirmation_or_privilege", "message": str(exc), "exit_code": EXIT_CODES["confirmation_required"]}})
        except FileExistsError as exc:
            return self._json(409, {"error": {"code": "already_exists", "message": redact(str(exc)), "exit_code": EXIT_CODES["incompatible_state"]}})
        except TimeoutError as exc:
            return self._json(409, {"error": {"code": "expired", "message": str(exc), "exit_code": EXIT_CODES["timeout"]}})
        except (ValueError, PolicyError, json.JSONDecodeError) as exc:
            return self._json(422, {"error": {"code": "invalid_plan", "message": redact(str(exc)), "exit_code": EXIT_CODES["policy_denied"]}})
        except (sqlite3.IntegrityError, sqlite3.DatabaseError) as exc:
            return self._json(409, {"error": {"code": "persistence_integrity", "message": redact(str(exc)), "exit_code": EXIT_CODES["integrity_failure"]}})
        except Exception as exc:
            return self._json(500, {"error": {"code": "internal_error", "message": redact(str(exc))}})


def serve(host: str = "127.0.0.1", port: int = 8765, token: str | None = None) -> None:
    store = Store()
    try:
        from .workspace import Workspace
    except ImportError:
        from workspace import Workspace
    handler = VortexHandler
    handler.store = store; handler.executor = ExecutionManager(store); handler.sessions = SessionManager(store); handler.workspace = Workspace(store); handler.executor.workspace = handler.workspace; handler.frontend = Path(__file__).resolve().parent.parent / "frontend"; handler.token = token
    server = ThreadingHTTPServer((host, port), handler)
    def stop_on_term(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop_on_term)
    signal.signal(signal.SIGHUP, stop_on_term)
    runtime_file = write_runtime_metadata(host, server.server_port, token)
    print(json.dumps({"backend": "online", "host": host, "port": server.server_port, "version": APP_VERSION}), flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        handler.sessions.shutdown()
        server.server_close()
        try:
            if json.loads(runtime_file.read_text(encoding="utf-8")).get("pid") == os.getpid(): runtime_file.unlink()
        except (OSError, ValueError): pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vortex local Linux sidecar")
    parser.add_argument("--host", default=os.environ.get("VORTEX_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("VORTEX_PORT", "8765")))
    parser.add_argument("--token", default=os.environ.get("VORTEX_SIDECAR_TOKEN"))
    args = parser.parse_args()
    serve(args.host, args.port, args.token)
