"""Ollama runtime + local model management.

This module owns the operator-facing lifecycle that the advisory router
(``models.router``) deliberately does not: detecting the runtime, installing a
user-space Ollama, starting/stopping the loopback service, and downloading,
cancelling, and removing local models.

Safety invariants:

* Every install/download is explicitly operator-confirmed and never runs in
  offline mode. VORTEX never captures a sudo password: the install path is a
  user-space tarball, not ``curl | sh``.
* The service binds to loopback (``127.0.0.1``) only.
* Model names are validated before ``ollama pull``; they are passed as a
  single argv token with ``shell=False`` so a name can never become a command.
* Downloads run on background threads and are surfaced as pollable state, so
  the HTTP request never blocks the UI.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from ..vortex_backend import PolicyError, data_root, minimal_env, now_iso, redact
except ImportError:  # pragma: no cover - direct module import
    from vortex_backend import PolicyError, data_root, minimal_env, now_iso, redact  # type: ignore

try:
    from .router import DEFAULT_OLLAMA, loopback_http_endpoint, ollama_status
except ImportError:  # pragma: no cover
    from models.router import DEFAULT_OLLAMA, loopback_http_endpoint, ollama_status  # type: ignore

try:
    from ..config import load_settings, save_settings
except ImportError:  # pragma: no cover
    from config import load_settings, save_settings  # type: ignore

try:
    from ..fileio import exclusive_file_lock
except ImportError:  # pragma: no cover
    from fileio import exclusive_file_lock  # type: ignore

_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+(?::[A-Za-z0-9._-]+)?$|^[A-Za-z0-9][A-Za-z0-9._-]*(?::[A-Za-z0-9._-]+)?$")
_ROLE_SETTINGS = {
    "primary": "model_primary", "planner": "model_planner",
    "fast": "model_fast", "specialist": "model_specialist",
}
_OLLAMA_HOST = "127.0.0.1"
_ARCH_MAP = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
_RELEASE_API = "https://api.github.com/repos/ollama/ollama/releases/latest"
_RELEASE_DOWNLOAD_PREFIX = "/ollama/ollama/releases/download/"
_DOWNLOAD_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"})
_MAX_RELEASE_METADATA_BYTES = 2 * 1024 * 1024
_MAX_RUNTIME_ARCHIVE_BYTES = 4 * 1024 ** 3
_MAX_RUNTIME_EXTRACT_BYTES = 8 * 1024 ** 3
_MAX_RUNTIME_MEMBERS = 8192
_MAX_JOBS = 64
_MAX_ACTIVE_DOWNLOADS = 2

_LOCK = threading.RLock()
# name -> in-memory download job state (a pull or the runtime install).
_JOBS: dict[str, dict[str, Any]] = {}
_REMOVING: set[str] = set()
_SERVER: dict[str, Any] = {"proc": None, "state": "stopped", "binary": None, "logs": deque(maxlen=200)}
_INSTALL: dict[str, Any] = {
    "status": "idle", "step": "", "percent": 0.0, "downloaded_bytes": 0,
    "total_bytes": None, "error": None, "failure_reason": None, "sha256": None,
    "checksum_verified": None, "executable_verified": None, "api_verified": None,
    "speed_bps": None, "eta_seconds": None, "started_at": None, "ended_at": None,
}


def _invalidate_router_status() -> None:
    try:
        from .router import invalidate_status_cache
    except ImportError:  # pragma: no cover
        from models.router import invalidate_status_cache  # type: ignore
    invalidate_status_cache()


def import_local_models(paths: list[str]) -> dict[str, Any]:
    """Persist an operator-selected GGUF source after validation only."""
    try:
        from . import gguf
    except ImportError:  # pragma: no cover
        from models import gguf  # type: ignore
    selected = gguf.configure_local_source(paths)
    settings = save_settings({"models_dir": selected["directory"]})
    gguf.invalidate_scan_cache()
    _invalidate_router_status()
    snapshot = gguf.status(settings)
    return {
        "directory": selected["directory"],
        "models": selected["models"],
        "gguf": snapshot,
        "message": "Local model source added. Files remain in their original location.",
    }


def _public_install() -> dict[str, Any]:
    with _LOCK:
        snapshot = _INSTALL.copy()
    return {key: value for key, value in snapshot.items() if key not in {"cancel_event", "started_mono", "thread", "response", "decompressor"}}


def _managed_root() -> Path:
    return data_root() / "ollama"


def _managed_binary() -> Path:
    return _managed_root() / "bin" / "ollama"


def _trusted_executable(path: Path, *, managed: bool = False) -> str | None:
    """Return a canonical executable without following an attacker-made leaf symlink."""
    try:
        leaf = path.lstat()
        if stat.S_ISLNK(leaf.st_mode) or not stat.S_ISREG(leaf.st_mode):
            return None
        real = path.resolve(strict=True)
        details = real.stat()
        mode = stat.S_IMODE(details.st_mode)
        if not (mode & 0o111) or mode & 0o022 or details.st_mode & (stat.S_ISUID | stat.S_ISGID):
            return None
        if managed and details.st_uid != os.getuid():
            return None
        return str(real)
    except OSError:
        return None


def _locate_binary() -> str | None:
    # Never execute an ambient PATH entry from a writable project/virtualenv.
    # System binaries come only from the controlled runtime PATH; the one
    # user-owned exception is VORTEX's fixed, mode-0700 managed data tree.
    controlled_path = minimal_env(False).get("PATH", "/usr/local/bin:/usr/bin:/bin")
    found = shutil.which("ollama", path=controlled_path)
    trusted = _trusted_executable(Path(found)) if found else None
    if trusted:
        return trusted
    return _trusted_executable(_managed_binary(), managed=True)


def _offline() -> bool:
    try:
        return load_settings().get("offline") is True
    except Exception:
        # Network mutations fail closed when policy state cannot be read.
        return True


def _configured_endpoint() -> str:
    try:
        raw = load_settings().get("ollama_endpoint")
    except (OSError, ValueError):
        raw = None
    return loopback_http_endpoint(str(raw or ""), default=DEFAULT_OLLAMA)


def _server_env(endpoint: str | None = None) -> dict[str, str]:
    env = minimal_env(False)
    parsed = urllib.parse.urlsplit(loopback_http_endpoint(endpoint or _configured_endpoint(), default=DEFAULT_OLLAMA))
    host = parsed.hostname or _OLLAMA_HOST
    port = parsed.port or 11434
    env["OLLAMA_HOST"] = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    env["HOME"] = os.environ.get("HOME") or str(Path.home())
    return env


def _short_timeout_versions(binary: str) -> str | None:
    try:
        proc = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=5, env=_server_env())
        line = ((proc.stdout or "") + "\n" + (proc.stderr or "")).splitlines()
        if not line:
            return None
        text = line[0].strip()
        return text[:120]
    except (OSError, subprocess.SubprocessError):
        return None


def _disk_free_gb(path: Path) -> float | None:
    try:
        stats = os.statvfs(path)
        return round((stats.f_frsize * stats.f_bavail) / (1024 ** 3), 2)
    except OSError:
        return None


def _read_json_response(response: Any, *, limit: int) -> Any:
    announced = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
    if announced:
        try:
            announced_size = int(announced)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid Ollama API Content-Length") from exc
        if announced_size < 0 or announced_size > limit:
            raise ValueError("Ollama API response exceeds the allowed size")
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Ollama API response exceeds the allowed size")
    return json.loads(raw.decode("utf-8", "replace") or "{}")


def _loopback_open(request: urllib.request.Request, timeout: float):
    # A local model request must never be diverted through inherited proxy
    # settings, even when the operator has omitted NO_PROXY.
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout)


def _api_version(endpoint: str | None = None, timeout: float = 0.8) -> str | None:
    url = (endpoint or _configured_endpoint()).rstrip("/")
    try:
        request = urllib.request.Request(url + "/api/version", headers={"User-Agent": "Vortex/0.2"})
        with _loopback_open(request, timeout) as response:
            payload = _read_json_response(response, limit=64 * 1024)
        version = payload.get("version") if isinstance(payload, dict) else None
        return redact(version[:120]) if isinstance(version, str) else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _ollama_tags(endpoint: str | None = None, timeout: float = 2.0) -> list[str] | None:
    """Return the live local model names, or None when the loopback API is down."""
    url = (endpoint or _configured_endpoint()).rstrip("/")
    try:
        request = urllib.request.Request(url + "/api/tags", headers={"User-Agent": "Vortex/0.2"})
        with _loopback_open(request, timeout) as response:
            payload = _read_json_response(response, limit=2 * 1024 * 1024)
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return None
        names = []
        for item in models[:2048]:
            name = item.get("name") if isinstance(item, dict) else None
            if isinstance(name, str) and 0 < len(name) <= 160 and _MODEL_RE.fullmatch(name):
                names.append(name)
        return names
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _failure_reason(exc: BaseException) -> str:
    """Classify an install/download failure into an operator-facing reason."""
    if isinstance(exc, PermissionError):
        return "permission"
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "network"
    if isinstance(exc, OSError):
        if exc.errno == 28:  # ENOSPC
            return "storage"
        if exc.errno in (1, 13):  # EPERM, EACCES
            return "permission"
    return "unknown"


def _check_storage(required_gb: float, label: str) -> None:
    """Refuse to start a download when the data disk cannot plausibly hold it."""
    free = _disk_free_gb(data_root())
    if free is None:
        return
    if free < required_gb:
        raise PolicyError(
            f"Insufficient storage for {label}: {free} GB free, "
            f"about {required_gb} GB estimated required. Free space and retry."
        )


def _update_rate(job: dict[str, Any]) -> None:
    """Derive honest speed/ETA from elapsed time and bytes already received."""
    started = job.get("started_mono")
    downloaded = int(job.get("downloaded_bytes") or 0)
    total = job.get("total_bytes")
    if not started:
        return
    elapsed = time.monotonic() - float(started)
    if elapsed <= 0:
        return
    speed = downloaded / elapsed
    job["speed_bps"] = int(speed)
    if total and speed > 0:
        remaining = max(0, int(total) - downloaded)
        job["eta_seconds"] = int(remaining / speed)
    else:
        job["eta_seconds"] = None


def runtime_status() -> dict[str, Any]:
    binary = _locate_binary()
    version = _short_timeout_versions(binary) if binary else None
    settings = load_settings()
    endpoint = loopback_http_endpoint(str(settings.get("ollama_endpoint") or ""), default=DEFAULT_OLLAMA)
    offline = settings.get("offline") is True
    # Reuse the router's loopback health probe for API/model facts. Offline
    # mode blocks install/pull network traffic, but loopback inference remains
    # available and must not be reported as disabled.
    api = ollama_status(endpoint, offline=offline)
    server = _server_summary()
    arch = os.uname().machine
    supported_arch = arch in _ARCH_MAP
    return {
        "installed": bool(binary),
        "path": binary,
        "version": version,
        "endpoint": endpoint,
        "api_state": api.get("state"),
        "api_reason": api.get("reason"),
        "api_version": api.get("version"),
        "models": api.get("models") or [],
        "installed_candidates": api.get("installed_candidates") or [],
        "server": server,
        "install": _public_install(),
        "platform": {
            "arch": arch,
            "supported_arch": supported_arch,
            "zstd_available": _find_trusted_zstd() is not None,
            "offline": offline,
        },
        "disk_free_gb": _disk_free_gb(data_root()),
        "sizes": {name: _approx_size_gb(name) for name in _APPROX_SIZES},
    }


# Approximate download sizes (GiB) for the curated catalog. These are honest
# approximations for display only; the real size is reported by Ollama during
# the pull and may differ by quantization/hardware.
_APPROX_SIZES: dict[str, float] = {
    "phi4-mini:3.8b": 2.5,
    "qwen3:4b": 2.6,
    "llama3.2:3b": 2.0,
    "gemma3:4b": 3.3,
}


def _approx_size_gb(name: str) -> float | None:
    return _APPROX_SIZES.get(name)


def _install_arch() -> str:
    arch = os.uname().machine
    mapped = _ARCH_MAP.get(arch)
    if not mapped:
        raise ValueError(f"Ollama does not publish a user-space build for this architecture ({arch}).")
    return mapped


def _reviewed_https_url(url: str, hosts: frozenset[str]) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in hosts
            and parsed.port in {None, 443}
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
            and all(char not in url for char in "\x00\r\n")
        )
    except (TypeError, ValueError):
        return False


def _validate_response_origin(response: Any, hosts: frozenset[str]) -> None:
    geturl = getattr(response, "geturl", None)
    if callable(geturl) and not _reviewed_https_url(str(geturl()), hosts):
        raise PolicyError("The Ollama download redirected outside its reviewed HTTPS origins.")


def _latest_runtime_asset(arch: str) -> dict[str, Any]:
    """Resolve one exact official release asset with GitHub's SHA-256 digest."""
    request = urllib.request.Request(
        _RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Vortex/0.2"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed GitHub API URL
        _validate_response_origin(response, frozenset({"api.github.com"}))
        payload = _read_json_response(response, limit=_MAX_RELEASE_METADATA_BYTES)
    if not isinstance(payload, dict) or payload.get("draft") is True or payload.get("prerelease") is True:
        raise RuntimeError("GitHub did not return a stable Ollama release.")
    assets = payload.get("assets")
    if not isinstance(assets, list) or len(assets) > 256:
        raise RuntimeError("Ollama release metadata did not contain a bounded asset list.")
    preferred = (f"ollama-linux-{arch}.tar.zst", f"ollama-linux-{arch}.tgz")
    by_name: dict[str, dict[str, Any]] = {}
    for item in assets:
        name = item.get("name") if isinstance(item, dict) else None
        if isinstance(name, str) and name in preferred:
            if name in by_name:
                raise RuntimeError("Ollama release metadata contains a duplicate runtime asset.")
            by_name[name] = item
    for name in preferred:
        item = by_name.get(name)
        if not isinstance(item, dict):
            continue
        url = item.get("browser_download_url")
        digest = item.get("digest")
        size = item.get("size")
        if (
            isinstance(url, str)
            and _reviewed_https_url(url, frozenset({"github.com"}))
            and urllib.parse.urlsplit(url).path.startswith(_RELEASE_DOWNLOAD_PREFIX)
            and isinstance(digest, str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            and isinstance(size, int)
            and not isinstance(size, bool)
            and 0 < size <= _MAX_RUNTIME_ARCHIVE_BYTES
        ):
            return {"name": name, "url": url, "sha256": digest.split(":", 1)[1], "size": size}
        raise RuntimeError("The official Ollama asset lacks valid URL, size, or SHA-256 metadata.")
    raise RuntimeError(f"The latest Ollama release has no supported Linux {arch} archive.")


def _runtime_member_name(raw_name: str) -> str | None:
    if not isinstance(raw_name, str) or not raw_name or "\x00" in raw_name or "\\" in raw_name or raw_name.startswith("/"):
        return None
    name = raw_name
    while name.startswith("./"):
        name = name[2:]
    parts = PurePosixPath(name).parts
    if len(parts) < 2 or any(part in {"", ".", ".."} for part in parts) or parts[0] not in {"bin", "lib"}:
        return None
    return "/".join(parts)


def _safe_tar_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    selected_names: set[str] = set()
    extracted_bytes = 0
    for index, member in enumerate(tar):
        if index >= _MAX_RUNTIME_MEMBERS:
            raise RuntimeError("The Ollama archive contains too many entries.")
        name = _runtime_member_name(member.name)
        if name is None or member.issym() or member.islnk() or not member.isfile():
            continue
        if name in selected_names:
            raise RuntimeError("The Ollama archive contains duplicate runtime paths.")
        selected_names.add(name)
        if member.size < 0:
            raise RuntimeError("The Ollama archive contains an invalid member size.")
        extracted_bytes += int(member.size)
        if extracted_bytes > _MAX_RUNTIME_EXTRACT_BYTES:
            raise RuntimeError("The Ollama archive expands beyond the allowed size.")
        members.append(member)
    return members


def _safe_extract_targets(root: Path, members: list[tarfile.TarInfo]) -> list[tarfile.TarInfo]:
    """Refuse any archive member whose resolved target escapes the install root.

    ``_safe_tar_members`` already drops absolute, symlink, and ``..`` members,
    so this is defense in depth: before a single byte is written, every target
    is resolved and must be a true descendant of the install root. A substring
    comparison is not enough — a sibling directory like ``ollama2`` shares the
    root's prefix without being inside it — so containment uses an explicit
    relative-path check.
    """
    root_resolved = root.resolve()
    for member in members:
        name = _runtime_member_name(member.name)
        if name is None:
            raise RuntimeError("Archive contained an unsafe extraction path.")
        target = (root / name).resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError:
            raise RuntimeError("Archive contained an unsafe extraction path.")
    return members


def _find_trusted_zstd() -> str | None:
    for candidate in (Path("/usr/bin/zstd"), Path("/bin/zstd")):
        trusted = _trusted_executable(candidate)
        if trusted:
            try:
                if Path(trusted).stat().st_uid == 0:
                    return trusted
            except OSError:
                continue
    return None


def _trusted_zstd() -> str:
    trusted = _find_trusted_zstd()
    if trusted:
        return trusted
    raise PolicyError("The latest Ollama archive requires the reviewed `zstd` system package. Install zstd through Dependencies, then retry.")


@contextmanager
def _open_runtime_tar(archive: Path, asset_name: str, job: dict[str, Any]):
    if asset_name.endswith(".tgz"):
        with tarfile.open(archive, "r|gz") as tar:
            yield tar
        return
    if not asset_name.endswith(".tar.zst"):
        raise RuntimeError("Ollama release metadata selected an unsupported archive format.")
    binary = _trusted_zstd()
    proc = subprocess.Popen(  # noqa: S603 - fixed root-owned decompressor; argv is typed
        [binary, "--decompress", "--stdout", "--quiet", str(archive)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=minimal_env(False), start_new_session=True, close_fds=True,
    )
    job["decompressor"] = proc
    try:
        if proc.stdout is None:
            raise RuntimeError("Could not open the zstd decompression stream.")
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            yield tar
        proc.stdout.close()
        try:
            code = proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            _terminate_pull_process(proc)
            raise RuntimeError("The zstd decompressor did not finish cleanly.")
        error = proc.stderr.read(4097) if proc.stderr is not None else b""
        if code != 0:
            raise RuntimeError("The verified Ollama archive could not be decompressed: " + redact(error.decode("utf-8", "replace")[:300]))
    finally:
        if proc.poll() is None:
            _terminate_pull_process(proc)
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()
        job.pop("decompressor", None)


def _extract_runtime_archive(archive: Path, asset_name: str, root: Path, job: dict[str, Any]) -> dict[str, int]:
    """Stream selected regular files into a private staging tree."""
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    root_resolved = root.resolve(strict=True)
    selected: set[str] = set()
    extracted_bytes = 0
    entry_count = 0
    with _open_runtime_tar(archive, asset_name, job) as tar:
        for entry_count, member in enumerate(tar, start=1):
            _check_install_cancelled(job)
            if entry_count > _MAX_RUNTIME_MEMBERS:
                raise RuntimeError("The Ollama archive contains too many entries.")
            name = _runtime_member_name(member.name)
            if name is None or member.issym() or member.islnk() or not member.isfile():
                continue
            if name in selected:
                raise RuntimeError("The Ollama archive contains duplicate runtime paths.")
            if member.size < 0 or member.size > _MAX_RUNTIME_EXTRACT_BYTES - extracted_bytes:
                raise RuntimeError("The Ollama archive expands beyond the allowed size.")
            selected.add(name)
            extracted_bytes += int(member.size)
            target = root.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                target.parent.resolve(strict=True).relative_to(root_resolved)
            except (OSError, ValueError) as exc:
                raise RuntimeError("Archive contained an unsafe extraction path.") from exc
            source = tar.extractfile(member)
            if source is None:
                raise RuntimeError("The Ollama archive contained an unreadable runtime file.")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            mode = (stat.S_IMODE(member.mode) & 0o755) or 0o600
            fd = os.open(target, flags, mode)
            remaining = int(member.size)
            try:
                with os.fdopen(fd, "wb") as output:
                    fd = -1
                    while remaining:
                        _check_install_cancelled(job)
                        chunk = source.read(min(1 << 20, remaining))
                        if not chunk:
                            raise RuntimeError("The Ollama archive ended before a runtime file was complete.")
                        output.write(chunk)
                        remaining -= len(chunk)
            finally:
                source.close()
                if fd >= 0:
                    os.close(fd)
    if "bin/ollama" not in selected:
        raise RuntimeError("The downloaded archive did not contain the expected bin/ollama payload.")
    return {"entries": len(selected), "bytes": extracted_bytes}


def _download_to(url: str, destination: Path, job: dict[str, Any], *, expected_size: int | None = None) -> str:
    """Stream a bounded URL to a unique owner-only file and return its sha256."""
    if not _reviewed_https_url(url, _DOWNLOAD_HOSTS) or not urllib.parse.urlsplit(url).path.startswith(_RELEASE_DOWNLOAD_PREFIX):
        raise PolicyError("Ollama runtime downloads are restricted to reviewed official release URLs.")
    if expected_size is not None and (not isinstance(expected_size, int) or isinstance(expected_size, bool) or not 0 < expected_size <= _MAX_RUNTIME_ARCHIVE_BYTES):
        raise PolicyError("Ollama release metadata declared an invalid archive size.")
    job["started_mono"] = time.monotonic()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".part", dir=str(destination.parent))
    temp = Path(temp_name)
    request = urllib.request.Request(url, headers={"User-Agent": "Vortex/0.2 (operator-confirmed local install)"})
    cancel_event = job.get("cancel_event")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - reviewed GitHub release URL
            _validate_response_origin(response, _DOWNLOAD_HOSTS)
            job["response"] = response
            total_header = response.headers.get("Content-Length")
            try:
                total = int(total_header) if total_header is not None else None
            except (TypeError, ValueError) as exc:
                raise PolicyError("The Ollama download returned an invalid Content-Length.") from exc
            if total is not None and (total < 0 or total > _MAX_RUNTIME_ARCHIVE_BYTES):
                raise PolicyError("The Ollama runtime archive exceeds the allowed download size.")
            if expected_size is not None and total is not None and total != expected_size:
                raise RuntimeError("The Ollama archive size differs from the reviewed release metadata.")
            job["total_bytes"] = total
            sha = hashlib.sha256()
            downloaded = 0
            with os.fdopen(fd, "wb", closefd=True) as handle:
                fd = -1
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("Ollama install cancelled")
                    chunk = response.read(1 << 16)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > _MAX_RUNTIME_ARCHIVE_BYTES:
                        raise PolicyError("The Ollama runtime archive exceeded the allowed download size.")
                    handle.write(chunk)
                    sha.update(chunk)
                    job["downloaded_bytes"] = downloaded
                    if total:
                        job["percent"] = round(min(99.0, downloaded * 100.0 / total), 1)
                    _update_rate(job)
                handle.flush()
                os.fsync(handle.fileno())
            if expected_size is not None and downloaded != expected_size:
                raise RuntimeError("The Ollama archive ended before the reviewed release size was received.")
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Ollama install cancelled")
            os.replace(temp, destination)
            directory_fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return sha.hexdigest()
    except BaseException:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        if fd >= 0:
            os.close(fd)
        job.pop("started_mono", None)
        job.pop("response", None)


def _drain_log(proc: subprocess.Popen, name: str) -> None:
    try:
        while proc.stdout is not None:
            raw = proc.stdout.readline(4097)
            if not raw:
                break
            line = redact(str(raw).rstrip()[:400])
            if len(raw) > 400:
                line += "…"
            with _LOCK:
                _SERVER["logs"].append(line)
                _INSTALL["step"] = line if name == "install" else _INSTALL.get("step")
    except (OSError, ValueError):
        return
    finally:
        with _LOCK:
            if _SERVER.get("proc") is proc and _SERVER.get("state") == "running":
                return_code = proc.poll()
                if return_code is not None:
                    _SERVER["state"] = "exited" if return_code == 0 else "failed"
        # The pipe is owned here once the process exits; close it so repeated
        # start/stop cycles cannot accumulate file descriptors.
        try:
            if proc.stdout is not None:
                proc.stdout.close()
        except OSError:
            pass


def _server_summary() -> dict[str, Any]:
    """JSON-safe view of the managed service.

    ``_SERVER`` also holds the live ``subprocess.Popen`` and its bounded log
    ``deque`` for internal bookkeeping. Neither is JSON-serializable, so the
    HTTP surface must never return the raw dict; it returns this summary.
    """
    with _LOCK:
        proc = _SERVER.get("proc")
        return_code = proc.poll() if proc is not None else None
        running = proc is not None and return_code is None
        state = _SERVER.get("state") or ("running" if running else "stopped")
        if proc is not None and not running and state in {"starting", "running"}:
            state = "exited" if return_code == 0 else "failed"
            _SERVER["state"] = state
        return {
            "state": "running" if running else state,
            "managed": running,
            "binary": _SERVER.get("binary"),
            "logs": list(_SERVER.get("logs") or deque())[-8:],
        }


def start_server() -> dict[str, Any]:
    binary = _locate_binary()
    if not binary:
        raise PolicyError("Ollama is not installed on this host.")
    # A system/user service may already own the configured loopback endpoint.
    # Do not start a competing `ollama serve` process (which just exits on the
    # occupied port) and make the successful external runtime explicit.
    existing_version = _api_version(timeout=0.8)
    if existing_version:
        with _LOCK:
            if _SERVER.get("proc") is None or _SERVER["proc"].poll() is not None:
                _SERVER["state"] = "external"
                _SERVER["binary"] = binary
                _SERVER["logs"].append("[vortex] using existing loopback Ollama service")
        _invalidate_router_status()
        return {**_server_summary(), "state": "external", "managed": False, "api_version": existing_version}
    with _LOCK:
        proc = _SERVER.get("proc")
        if proc is not None and proc.poll() is None:
            if _SERVER.get("state") == "stopping":
                raise PolicyError("Ollama is still stopping; retry after it exits.")
            _SERVER["state"] = "running"
            _invalidate_router_status()
            return _server_summary()
        env = _server_env()
        try:
            proc = subprocess.Popen(  # noqa: S603 - absolute, validated binary; argv typed
                [binary, "serve"], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                env=env, start_new_session=True, close_fds=True,
            )
        except Exception:
            _SERVER["state"] = "failed"
            raise
        drain_thread = threading.Thread(
            target=_drain_log, args=(proc, "server"), name="vortex-ollama-server-log", daemon=True,
        )
        _SERVER["proc"] = proc
        _SERVER["thread"] = drain_thread
        # Report a transitional state until the process has survived its first
        # scheduler turn. This keeps the UI responsive without pretending that
        # a port-conflict or bad runtime is a running service.
        _SERVER["state"] = "starting"
        _SERVER["binary"] = binary
        _SERVER["logs"].append(f"[vortex] started ollama serve pid={proc.pid}")
        drain_thread.start()
        _invalidate_router_status()
    time.sleep(0.15)
    with _LOCK:
        still_running = _SERVER.get("proc") is proc and proc.poll() is None
        if still_running:
            _SERVER["state"] = "running"
    summary = _server_summary()
    if not still_running:
        raise PolicyError("Ollama exited while starting: " + (summary.get("logs") or ["no diagnostic output"])[-1])
    _invalidate_router_status()
    return _server_summary()


def stop_server() -> dict[str, Any]:
    with _LOCK:
        proc = _SERVER.get("proc")
        drain_thread = _SERVER.get("thread")
        _SERVER["state"] = "stopping" if proc is not None and proc.poll() is None else "stopped"
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    # Close the captured pipe even if the drain thread is still winding down;
    # closing is idempotent and prevents a per-cycle fd leak.
    if proc is not None:
        for stream in (proc.stdout, proc.stderr):
            if stream is None or (stream is proc.stderr and stream is proc.stdout):
                continue
            try:
                stream.close()
            except OSError:
                pass
    if drain_thread is not None and drain_thread is not threading.current_thread() and drain_thread.is_alive():
        drain_thread.join(timeout=1)
    with _LOCK:
        if _SERVER.get("proc") is proc:
            _SERVER["proc"] = None
            _SERVER["thread"] = None
        _SERVER["state"] = "stopped"
        if proc is not None:
            _SERVER["logs"].append("[vortex] stopped ollama serve")
        _invalidate_router_status()
        return _server_summary()


def _check_install_cancelled(job: dict[str, Any]) -> None:
    event = job.get("cancel_event")
    if event is not None and event.is_set():
        raise InterruptedError("Ollama install cancelled")


def _wait_for_api(job: dict[str, Any], timeout: float = 12.0) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _check_install_cancelled(job)
        version = _api_version(timeout=0.5)
        if version:
            return version
        with _LOCK:
            proc = _SERVER.get("proc")
        if proc is not None and proc.poll() is not None:
            return None
        time.sleep(0.2)
    return None


def _publish_managed_root(staged: Path, managed: Path) -> None:
    """Atomically publish a verified runtime tree, rolling back on failure."""
    backup = managed.with_name(f".{managed.name}.old-{secrets.token_hex(8)}")
    had_previous = False
    try:
        details = managed.lstat()
        if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode) or details.st_uid != os.geteuid():
            raise PermissionError("The managed Ollama path is not an owner-local directory.")
        os.replace(managed, backup)
        had_previous = True
    except FileNotFoundError:
        pass
    try:
        os.replace(staged, managed)
    except BaseException:
        if had_previous:
            os.replace(backup, managed)
        raise
    if had_previous:
        shutil.rmtree(backup)
    directory_fd = os.open(managed.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _install_worker() -> None:
    try:
        with exclusive_file_lock(data_root() / "locks" / "ollama-install", timeout=5.0):
            _check_install_cancelled(_INSTALL)
            _install_worker_locked()
    except InterruptedError:
        _INSTALL["status"] = "cancelled"
        _INSTALL["step"] = "Ollama install cancelled."
        _INSTALL["error"] = None
        _INSTALL["failure_reason"] = None
        _INSTALL["ended_at"] = now_iso()
        _INSTALL.pop("thread", None)
    except Exception as exc:
        _INSTALL["status"] = "failed"
        _INSTALL["error"] = str(exc)[:300]
        _INSTALL["failure_reason"] = _failure_reason(exc)
        _INSTALL["ended_at"] = now_iso()
        _INSTALL.pop("thread", None)


def _install_worker_locked() -> None:
    job = _INSTALL
    succeeded = False
    archive: Path | None = None
    stage_parent: Path | None = None
    try:
        _check_install_cancelled(job)
        arch = _install_arch()
        job["step"] = "Resolving the latest signed release metadata…"
        job["status"] = "verifying"
        asset = _latest_runtime_asset(arch)
        _check_install_cancelled(job)
        if str(asset["name"]).endswith(".tar.zst"):
            _trusted_zstd()  # Fail before a multi-gigabyte download.
        required_gb = max(1.5, (int(asset["size"]) / (1024 ** 3)) * 3.0 + 0.5)
        _check_storage(required_gb, "the Ollama runtime and private extraction stage")
        downloads = data_root() / "downloads"
        downloads.mkdir(parents=True, exist_ok=True, mode=0o700)
        archive = downloads / str(asset["name"])
        job["asset"] = str(asset["name"])
        job["status"] = "downloading"
        job["step"] = "Downloading the reviewed official Ollama release…"
        computed = _download_to(str(asset["url"]), archive, job, expected_size=int(asset["size"]))
        _check_install_cancelled(job)
        job["sha256"] = computed
        job["step"] = "Verifying the release SHA-256 digest…"
        job["status"] = "verifying"
        if not secrets.compare_digest(computed, str(asset["sha256"])):
            job["checksum_verified"] = False
            raise RuntimeError("Downloaded Ollama archive failed its release SHA-256 verification. The file was not installed.")
        job["checksum_verified"] = True

        job["step"] = "Extracting into a private staging directory…"
        job["status"] = "installing"
        job["percent"] = 99.0
        stage_parent = Path(tempfile.mkdtemp(prefix=".ollama-install-", dir=str(data_root())))
        stage_parent.chmod(0o700)
        staged_root = stage_parent / "ollama"
        extraction = _extract_runtime_archive(archive, str(asset["name"]), staged_root, job)
        job["extracted_bytes"] = extraction["bytes"]
        job["extracted_entries"] = extraction["entries"]
        _check_install_cancelled(job)

        staged_binary = staged_root / "bin" / "ollama"
        trusted_staged_binary = _trusted_executable(staged_binary, managed=True)
        if trusted_staged_binary is None:
            raise RuntimeError("The staged Ollama binary is not a trusted owner-local executable.")
        staged_binary.chmod(0o755)
        job["step"] = "Verifying the staged executable…"
        version = _short_timeout_versions(str(staged_binary))
        _check_install_cancelled(job)
        if version is None:
            raise RuntimeError("The staged Ollama binary did not answer `--version`. Install aborted.")
        job["executable_verified"] = version
        _publish_managed_root(staged_root, _managed_root())

        try:
            archive.unlink()
        except OSError:
            pass
        job["step"] = "Starting the loopback service…"
        job["status"] = "starting"
        start_server()
        _check_install_cancelled(job)
        job["step"] = "Verifying the loopback API…"
        api_version = _wait_for_api(job)
        _check_install_cancelled(job)
        if api_version is None:
            raise RuntimeError("Ollama installed but its loopback API did not answer. It is not marked ready.")
        job["api_verified"] = api_version
        job["status"] = "completed"
        job["step"] = "Ollama installed, cryptographically verified, and the loopback service is responding."
        job["percent"] = 100.0
        _invalidate_router_status()
        succeeded = True
    except InterruptedError:
        job["status"] = "cancelled"
        job["step"] = "Ollama install cancelled."
        job["error"] = None
        job["failure_reason"] = None
        try:
            stop_server()
        except Exception:
            pass
    except Exception as exc:
        event = job.get("cancel_event")
        if event is not None and event.is_set():
            job["status"] = "cancelled"
            job["step"] = "Ollama install cancelled."
            job["error"] = None
            job["failure_reason"] = None
        else:
            job["status"] = "failed"
            job["error"] = str(exc)[:300]
            job["failure_reason"] = _failure_reason(exc)
    finally:
        decompressor = job.pop("decompressor", None)
        if decompressor is not None and decompressor.poll() is None:
            _terminate_pull_process(decompressor)
        if archive is not None:
            try:
                archive.unlink()
            except OSError:
                pass
        if stage_parent is not None:
            try:
                shutil.rmtree(stage_parent)
            except OSError:
                pass
        # A published but nonresponsive runtime remains available for operator
        # diagnosis; no unverified stage is ever published.
        if not succeeded and job.get("checksum_verified") is not True:
            job["executable_verified"] = None
        job.pop("started_mono", None)
        job["ended_at"] = now_iso()
        job.pop("thread", None)

def _activate_existing_worker(binary: str) -> None:
    job = _INSTALL
    try:
        _check_install_cancelled(job)
        version = _short_timeout_versions(binary)
        if version is None:
            raise RuntimeError("The installed Ollama binary did not answer `--version`.")
        job["executable_verified"] = version
        api_version = _api_version(timeout=0.8)
        if api_version is None:
            job["status"] = "starting"
            job["step"] = "Starting the loopback service…"
            start_server()
            job["status"] = "verifying"
            job["step"] = "Verifying the loopback API…"
            api_version = _wait_for_api(job)
        else:
            job["status"] = "verifying"
            job["step"] = "Verifying the existing loopback service…"
        if api_version is None:
            raise RuntimeError("Ollama exists, but its loopback API did not answer. It is not marked ready.")
        job["api_verified"] = api_version
        job["status"] = "completed"
        job["step"] = "Ollama is installed, verified, and responding on loopback."
        job["percent"] = 100.0
        _invalidate_router_status()
    except InterruptedError:
        job["status"] = "cancelled"
        job["step"] = "Ollama activation cancelled."
        try:
            stop_server()
        except Exception:
            pass
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)[:300]
        job["failure_reason"] = _failure_reason(exc)
    finally:
        job["ended_at"] = now_iso()
        job.pop("thread", None)


def install_ollama(confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise PermissionError("operator confirmation is required to install Ollama")
    if _offline():
        raise PolicyError("Offline mode blocks the Ollama download. Disable offline mode to install.")
    binary = _locate_binary()
    with _LOCK:
        if _INSTALL.get("status") in {"preparing", "downloading", "verifying", "installing", "starting", "cancelling"}:
            return _public_install()
        for key in ("status", "step", "percent", "downloaded_bytes", "total_bytes", "error", "failure_reason", "sha256", "checksum_verified", "executable_verified", "api_verified", "speed_bps", "eta_seconds", "asset", "extracted_bytes", "extracted_entries"):
            _INSTALL[key] = None
        _INSTALL["status"] = "verifying" if binary else "preparing"
        _INSTALL["step"] = "Verifying existing Ollama…" if binary else "Preparing user-space install…"
        _INSTALL["percent"] = 0.0
        _INSTALL["downloaded_bytes"] = 0
        _INSTALL["total_bytes"] = None
        _INSTALL["started_at"] = now_iso()
        _INSTALL["ended_at"] = None
        _INSTALL["cancel_event"] = threading.Event()
        target = (lambda: _activate_existing_worker(binary)) if binary else _install_worker
        thread = threading.Thread(target=target, name="vortex-ollama-activate" if binary else "vortex-ollama-install", daemon=True)
        _INSTALL["thread"] = thread
        thread.start()
        return _public_install()


def cancel_install() -> dict[str, Any]:
    with _LOCK:
        status = str(_INSTALL.get("status") or "idle")
        if status not in {"preparing", "downloading", "verifying", "installing", "starting", "cancelling"}:
            return {"status": status, "cancelled": False}
        event = _INSTALL.get("cancel_event")
        if event is not None:
            event.set()
        response = _INSTALL.get("response")
        decompressor = _INSTALL.get("decompressor")
        _INSTALL["status"] = "cancelling"
        _INSTALL["step"] = "Cancelling Ollama install…"
    if response is not None:
        try:
            response.close()
        except OSError:
            pass
    if decompressor is not None and decompressor.poll() is None:
        _terminate_pull_process(decompressor)
    return {"status": "cancelling", "cancelled": True}


def _parse_progress_line(raw: str) -> dict[str, Any]:
    line = raw.strip()
    if not line:
        return {}
    try:
        payload = json.loads(line)
        return payload if isinstance(payload, dict) else {}
    except ValueError:
        return {"_raw": redact(line[:200])}


def _progress_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if 0 <= number <= (16 * 1024 ** 4) else None


def _model_is_reported(requested: str, installed: str) -> bool:
    if installed == requested:
        return True
    # Ollama canonicalizes an omitted tag to (for example) `name:latest`.
    return ":" not in requested.rsplit("/", 1)[-1] and installed.startswith(requested + ":")


def _terminate_pull_process(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass


def _pull_worker(name: str, job: dict[str, Any]) -> None:
    proc: subprocess.Popen | None = None
    cancel_event = job.get("cancel_event")
    if cancel_event is not None and cancel_event.is_set():
        job["status"] = "cancelled"
        job["step"] = "Download cancelled."
        job["ended_at"] = now_iso()
        job.pop("thread", None)
        return
    binary = _locate_binary()
    if not binary:
        job["status"] = "failed"
        job["error"] = "Ollama is not installed on this host."
        job["failure_reason"] = "runtime_missing"
        job["ended_at"] = now_iso()
        job.pop("thread", None)
        return
    env = _server_env()
    try:
        approx = _approx_size_gb(name)
        if approx is not None:
            _check_storage(approx + 0.5, f"model {name}")
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Model download cancelled before launch")
        proc = subprocess.Popen(  # noqa: S603 - name validated by _MODEL_RE; shell=False
            [binary, "pull", name], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            env=env, start_new_session=True, close_fds=True,
        )
        with _LOCK:
            job["pid"] = proc.pid
            job["proc"] = proc
        if cancel_event is not None and cancel_event.is_set():
            _terminate_pull_process(proc)
        job["started_mono"] = time.monotonic()
        job["status"] = "downloading"
        saw_success = False
        while proc.stderr is not None:
            line = proc.stderr.readline(65537)
            if not line:
                break
            if cancel_event is not None and cancel_event.is_set():
                break
            payload = _parse_progress_line(line)
            if not payload:
                continue
            raw_status = payload.get("status")
            status = redact(str(raw_status)[:200]) if raw_status is not None else ""
            if status:
                job["last_status"] = status
            total = _progress_integer(payload.get("total"))
            completed = _progress_integer(payload.get("completed"))
            if status.startswith("downloading") and total:
                downloaded = min(total, completed or 0)
                job["total_bytes"] = total
                job["downloaded_bytes"] = downloaded
                job["percent"] = round(min(99.0, downloaded * 100.0 / total), 1)
                _update_rate(job)
            elif status == "success":
                saw_success = True
                job["percent"] = 100.0
            elif status == "pulling manifest" and job.get("percent", 0) < 2:
                job["percent"] = 2.0
        if cancel_event is not None and cancel_event.is_set():
            _terminate_pull_process(proc)
        else:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired as exc:
                _terminate_pull_process(proc)
                raise RuntimeError("Ollama closed its progress stream but did not exit.") from exc
        if cancel_event is not None and cancel_event.is_set():
            job["status"] = "cancelled"
            job["step"] = "Download cancelled."
        elif not saw_success or proc.returncode != 0:
            job["status"] = "failed"
            job["error"] = str(job.get("last_status") or "ollama pull failed")[:300]
            job["failure_reason"] = "pull_failed"
        else:
            # Verify the exact model (or its canonical default tag) exists on
            # the loopback API; a prefix match could accept a different model.
            job["status"] = "verifying"
            job["step"] = "Verifying the downloaded model…"
            tags = _ollama_tags()
            if tags is None:
                job["status"] = "failed"
                job["error"] = "Download finished, but the loopback API did not confirm the model. It is not marked installed."
                job["failure_reason"] = "verification_failed"
            elif not any(_model_is_reported(name, tag) for tag in tags):
                job["status"] = "failed"
                job["error"] = f"Download finished, but the expected model `{name}` was not reported by Ollama."
                job["failure_reason"] = "verification_failed"
            else:
                role = str(job.get("requested_role") or "none")
                if role != "none":
                    try:
                        setting = _ROLE_SETTINGS[role]
                        saved = save_settings({setting: name})
                        job["preference"] = {"role": role, "setting": setting, "model": saved[setting]}
                        job["preference_state"] = "integrated"
                    except Exception as exc:
                        job["status"] = "failed"
                        job["step"] = "Model was downloaded and verified, but its advisory preference could not be saved."
                        job["error"] = redact(str(exc)[:300])
                        job["failure_reason"] = "integration_failed"
                        return
                job["status"] = "completed"
                job["step"] = "Model downloaded, verified, and integrated." if role != "none" else "Model downloaded and verified."
                job["percent"] = 100.0
                _invalidate_router_status()
    except Exception as exc:
        if cancel_event is not None and cancel_event.is_set():
            job["status"] = "cancelled"
            job["step"] = "Download cancelled."
            job["error"] = None
            job["failure_reason"] = None
        else:
            job["status"] = "failed"
            job["error"] = redact(str(exc)[:300])
            job["failure_reason"] = _failure_reason(exc)
    finally:
        if proc is not None:
            _terminate_pull_process(proc)
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
        job.pop("started_mono", None)
        job["ended_at"] = now_iso()
        job.pop("pid", None)
        job.pop("proc", None)
        job.pop("thread", None)


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    """Return an atomic JSON-safe snapshot without live process objects."""
    snapshot = job.copy()
    return {key: value for key, value in snapshot.items() if key not in {"cancel_event", "started_mono", "pid", "thread", "proc"}}


def _prune_jobs_locked() -> None:
    terminal = {"completed", "failed", "cancelled"}
    for old_name in list(_JOBS):
        if len(_JOBS) < _MAX_JOBS:
            break
        if _JOBS[old_name].get("status") in terminal:
            _JOBS.pop(old_name, None)


def pull_model(name: str, role: str | None = None) -> dict[str, Any]:
    name = (name or "").strip()
    if not name or len(name) > 160 or not _MODEL_RE.fullmatch(name):
        raise ValueError("model name must look like `model`, `model:tag`, or `namespace/model:tag`")
    role = (role or "none").strip().lower()
    if role != "none" and role not in _ROLE_SETTINGS:
        raise ValueError("model role must be primary, planner, fast, specialist, or none")
    if _offline():
        raise PolicyError("Offline mode blocks model downloads. Disable offline mode to download models.")
    binary = _locate_binary()
    if not binary:
        raise PolicyError("Ollama is not installed on this host. Install Ollama before downloading models.")
    with _LOCK:
        if name in _REMOVING:
            raise PolicyError("This model is being removed; retry after removal finishes.")
        existing = _JOBS.get(name)
        if existing and existing.get("status") in {"preparing", "downloading", "verifying", "cancelling"}:
            if role != "none" and existing.get("requested_role") not in (None, "none", role):
                raise PolicyError("This model download already has a different pending advisory role.")
            if role != "none" and existing.get("requested_role") in (None, "none"):
                existing["requested_role"] = role
                existing["preference_state"] = "pending_verification"
            return _public_job(existing)
        active_states = {"preparing", "downloading", "verifying", "cancelling"}
        if sum(1 for item in _JOBS.values() if item.get("status") in active_states) >= _MAX_ACTIVE_DOWNLOADS:
            raise PolicyError("Two model downloads are already active; wait for one to finish or cancel it.")
        _prune_jobs_locked()
        if len(_JOBS) >= _MAX_JOBS and name not in _JOBS:
            raise PolicyError("The model download history is full; retry after active jobs finish.")
        job = {
            "name": name, "status": "preparing", "percent": 0.0, "downloaded_bytes": 0,
            "total_bytes": None, "last_status": "preparing", "step": "Preparing download…",
            "error": None, "failure_reason": None, "speed_bps": None, "eta_seconds": None,
            "requested_role": role, "preference_state": "pending_verification" if role != "none" else "download_only",
            "started_at": now_iso(), "ended_at": None, "cancel_event": threading.Event(),
        }
        _JOBS[name] = job
    thread = threading.Thread(target=_pull_worker, args=(name, job), name=f"vortex-ollama-pull-{name[:16]}", daemon=True)
    job["thread"] = thread
    thread.start()
    return _public_job(job)


def cancel_download(name: str) -> dict[str, Any]:
    name = (name or "").strip()
    with _LOCK:
        job = _JOBS.get(name)
        if not job or job.get("status") not in {"preparing", "downloading", "verifying"}:
            return {"name": name, "status": job.get("status") if job else "not_found", "cancelled": False}
        job["cancel_event"].set()
        proc = job.get("proc")
        job["status"] = "cancelling"
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    return {"name": name, "status": "cancelling", "cancelled": True}


def remove_model(name: str) -> dict[str, Any]:
    name = (name or "").strip()
    if not name or len(name) > 160 or not _MODEL_RE.fullmatch(name):
        raise ValueError("model name is invalid")
    binary = _locate_binary()
    if not binary:
        raise PolicyError("Ollama is not installed on this host.")
    with _LOCK:
        job = _JOBS.get(name)
        if job and job.get("status") in {"preparing", "downloading", "verifying", "cancelling"}:
            raise PolicyError("This model is downloading; cancel it before removing.")
        if name in _REMOVING:
            raise PolicyError("This model is already being removed.")
        _REMOVING.add(name)
    try:
        proc = subprocess.run(
            [binary, "rm", name], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=120, env=_server_env(), check=False,
        )  # noqa: S603
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "ollama rm failed").strip()[:300])
        _invalidate_router_status()
        return {"name": name, "removed": True}
    finally:
        with _LOCK:
            _REMOVING.discard(name)


def downloads() -> dict[str, Any]:
    with _LOCK:
        return {name: _public_job(job) for name, job in _JOBS.items()}


def _model_family(name: str) -> str:
    leaf = str(name or "").strip().lower()
    prefix, slash, tail = leaf.rpartition("/")
    family = tail.split(":", 1)[0]
    return f"{prefix}/{family}" if slash else family


def routing_preferences(status: dict[str, Any] | None = None, settings: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Resolve each configured advisory role against live, verified tags."""
    status = status or runtime_status()
    settings = settings or load_settings()
    installed = [str(item.get("name") or "") for item in status.get("models") or [] if item.get("name")]
    preferences: dict[str, dict[str, Any]] = {}
    for role, setting in _ROLE_SETTINGS.items():
        configured = str(settings.get(setting) or "").strip()
        exact = next((name for name in installed if name == configured), None)
        if exact is None and configured and ":" not in configured.rsplit("/", 1)[-1]:
            exact = next((name for name in installed if _model_is_reported(configured, name)), None)
        resolved = exact or next((name for name in installed if _model_family(name) == _model_family(configured)), None)
        preferences[role] = {
            "setting": setting,
            "configured": configured,
            "resolved": resolved,
            "state": "active" if resolved else "unavailable",
            "family_fallback": bool(resolved and resolved != configured),
        }
    return preferences


def activate_model(name: str, role: str) -> dict[str, Any]:
    """Persist a role only after the exact local model is confirmed by Ollama."""
    name = str(name or "").strip()
    role = str(role or "").strip().lower()
    if not name or len(name) > 160 or not _MODEL_RE.fullmatch(name):
        raise ValueError("model name is invalid")
    if role not in _ROLE_SETTINGS:
        raise ValueError("model role must be primary, planner, fast, or specialist")
    tags = _ollama_tags()
    if tags is None:
        raise PolicyError("The loopback Ollama API is unavailable; start it before activating a model.")
    resolved = next((tag for tag in tags if _model_is_reported(name, tag)), None)
    if resolved is None:
        raise PolicyError("The requested model is not installed according to the loopback Ollama API.")
    setting = _ROLE_SETTINGS[role]
    saved = save_settings({setting: resolved})
    _invalidate_router_status()
    return {"role": role, "setting": setting, "model": saved[setting], "state": "active"}


def catalog(status: dict[str, Any] | None = None, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Curated catalog merged with one coherent live Ollama status snapshot."""
    try:
        from .router import MODEL_CATALOG
    except ImportError:  # pragma: no cover
        from models.router import MODEL_CATALOG  # type: ignore

    status = status or runtime_status()
    preferences = routing_preferences(status, settings)
    installed_names = {str(m.get("name") or "") for m in status.get("models", [])}
    installed_map = {str(m.get("name") or ""): m for m in status.get("models", [])}
    with _LOCK:
        live_jobs = {name: _public_job(job) for name, job in _JOBS.items()}

    items: list[dict[str, Any]] = []
    for canonical_name, meta in MODEL_CATALOG.items():
        installed = canonical_name in installed_names or any(
            n == canonical_name or n.startswith(meta["family"] + ":") for n in installed_names
        )
        installed_name = canonical_name if canonical_name in installed_names else next(
            (n for n in installed_names if n.startswith(meta["family"] + ":")), None
        )
        job = live_jobs.get(canonical_name)
        items.append({
            "name": canonical_name,
            "label": meta["label"],
            "family": meta["family"],
            "description": _describe(meta),
            "roles": list(meta["roles"]),
            "primary_for": list(meta["primary_for"]),
            "optional": bool(meta["optional"]),
            "recommended": not bool(meta["optional"]),
            "approx_size_gb": _approx_size_gb(canonical_name),
            "installed": bool(installed),
            "installed_name": installed_name,
            "installed_detail": installed_map.get(installed_name) if installed_name else None,
            "active_roles": [role for role, pref in preferences.items() if installed_name and pref.get("resolved") == installed_name],
            "download": job,
        })
    extras = []
    for name in installed_names:
        if not any(item["name"] == name or item["installed_name"] == name for item in items):
            extras.append({
                "name": name,
                "installed": True,
                "installed_detail": installed_map.get(name),
                "active_roles": [role for role, pref in preferences.items() if pref.get("resolved") == name],
                "description": "Model installed on this host, outside the curated catalog.",
            })
    try:
        try:
            from .gguf import status as gguf_status
        except ImportError:
            try:
                from models.gguf import status as gguf_status  # type: ignore
            except ImportError:
                from backend.models.gguf import status as gguf_status  # type: ignore
        gguf = gguf_status(settings or load_settings())
    except Exception as exc:
        gguf = {"provider": "gguf", "state": "unavailable", "reason": f"gguf probe failed: {str(exc)[:160]}"}
    return {
        "items": items,
        "extras": extras,
        "downloads": live_jobs,
        "runtime": status,
        "routing_preferences": preferences,
        "gguf": gguf,
    }


_GGUF_ROLE_SETTINGS = {
    "primary": "gguf_primary", "planner": "gguf_planner",
    "fast": "gguf_fast", "specialist": "gguf_specialist",
}


def activate_gguf(filename: str, role: str) -> dict[str, Any]:
    """Persist a GGUF advisory role after verifying the exact local file."""
    filename = str(filename or "").strip()
    role = str(role or "").strip().lower()
    if not filename or len(filename) > 160 or "/" in filename or "\\" in filename or filename.startswith("."):
        raise ValueError("GGUF filename is invalid")
    if role not in _GGUF_ROLE_SETTINGS:
        raise ValueError("model role must be primary, planner, fast, or specialist")
    try:
        try:
            from .gguf import scan as gguf_scan
        except ImportError:
            try:
                from models.gguf import scan as gguf_scan  # type: ignore
            except ImportError:
                from backend.models.gguf import scan as gguf_scan  # type: ignore
        found = gguf_scan(load_settings().get("models_dir"))
    except Exception as exc:
        raise PolicyError(f"GGUF scan failed: {str(exc)[:160]}")
    entry = next((item for item in (found.get("valid_files") or []) if item.get("name") == filename), None)
    if entry is None:
        raise PolicyError("The requested GGUF file was not found or failed validation on this host.")
    setting = _GGUF_ROLE_SETTINGS[role]
    saved = save_settings({setting: filename})
    _invalidate_router_status()
    return {"role": role, "setting": setting, "model": saved[setting], "state": "active", "provider": "gguf"}


def _describe(meta: dict[str, Any]) -> str:
    primary = {str(p) for p in meta.get("primary_for", [])}
    if "conversation" in primary:
        return "General explanation and conversation. A strong default for everyday advisory answers."
    if "plan" in primary:
        return "Planning and tool selection. Used for command-plan explanation and verification."
    if "fast" in primary:
        return "Fast summaries and fallback. Smallest and quickest local model in the pool."
    if "specialist" in primary:
        return "Optional specialist model, used when extra multimodal or domain support is available."
    return "Local advisory model."


def shutdown(timeout: float = 5.0) -> None:
    """Cancel, terminate, and join every managed install/download worker."""
    timeout = max(0.2, min(float(timeout), 30.0))
    with _LOCK:
        jobs = list(_JOBS.values())
        install_event = _INSTALL.get("cancel_event")
        install_thread = _INSTALL.get("thread")
    if install_event is not None:
        install_event.set()
    with _LOCK:
        install_response = _INSTALL.get("response")
    if install_response is not None:
        try:
            install_response.close()
        except OSError:
            pass
    for job in jobs:
        event = job.get("cancel_event")
        if event is not None:
            event.set()
        proc = job.get("proc")
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    try:
        stop_server()
    except Exception:
        pass
    deadline = time.monotonic() + timeout
    threads = [job.get("thread") for job in jobs]
    if install_thread is not None:
        threads.append(install_thread)
    for thread in threads:
        if thread is not None and thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
    # Escalate a pull process that ignored TERM, then give its reader a final
    # short join. A network read in the runtime installer has a fixed timeout
    # and may outlive this graceful budget, but it owns no child process.
    for job in jobs:
        proc = job.get("proc")
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    for thread in threads:
        if thread is not None and thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=0.5)
