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
import shutil
import signal
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any

try:
    from ..vortex_backend import PolicyError, data_root, minimal_env, now_iso
except ImportError:  # pragma: no cover - direct module import
    from vortex_backend import PolicyError, data_root, minimal_env, now_iso  # type: ignore

try:
    from .router import ollama_status
except ImportError:  # pragma: no cover
    from models.router import ollama_status  # type: ignore

try:
    from ..config import load_settings
except ImportError:  # pragma: no cover
    from config import load_settings  # type: ignore

_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+(?::[A-Za-z0-9._-]+)?$|^[A-Za-z0-9][A-Za-z0-9._-]*(?::[A-Za-z0-9._-]+)?$")
_OLLAMA_HOST = "127.0.0.1"
_ARCH_MAP = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
_DOWNLOAD_URL = "https://ollama.com/download/ollama-linux-{arch}.tgz"

_LOCK = threading.RLock()
# name -> in-memory download job state (a pull or the runtime install).
_JOBS: dict[str, dict[str, Any]] = {}
_SERVER: dict[str, Any] = {"proc": None, "state": "stopped", "binary": None, "logs": deque(maxlen=200)}
_INSTALL: dict[str, Any] = {
    "status": "idle", "step": "", "percent": 0.0, "downloaded_bytes": 0,
    "total_bytes": None, "error": None, "failure_reason": None, "sha256": None,
    "checksum_verified": None, "executable_verified": None, "api_verified": None,
    "speed_bps": None, "eta_seconds": None, "started_at": None, "ended_at": None,
}


def _managed_root() -> Path:
    return data_root() / "ollama"


def _managed_binary() -> Path:
    return _managed_root() / "bin" / "ollama"


def _locate_binary() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    managed = _managed_binary()
    if managed.is_file():
        return str(managed)
    return None


def _offline() -> bool:
    try:
        return load_settings().get("offline") is True
    except Exception:
        return False


def _server_env() -> dict[str, str]:
    env = minimal_env(False)
    env["OLLAMA_HOST"] = f"{_OLLAMA_HOST}:11434"
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


def _api_version(endpoint: str | None = None, timeout: float = 0.8) -> str | None:
    url = (endpoint or f"http://{_OLLAMA_HOST}:11434").rstrip("/")
    try:
        request = urllib.request.Request(url + "/api/version", headers={"User-Agent": "Vortex/0.2"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback
            payload = json.loads(response.read().decode("utf-8", "replace") or "{}")
        version = payload.get("version") if isinstance(payload, dict) else None
        return version if isinstance(version, str) else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _ollama_tags(endpoint: str | None = None, timeout: float = 2.0) -> list[str] | None:
    """Return the live local model names, or None when the loopback API is down."""
    url = (endpoint or f"http://{_OLLAMA_HOST}:11434").rstrip("/")
    try:
        request = urllib.request.Request(url + "/api/tags", headers={"User-Agent": "Vortex/0.2"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback
            payload = json.loads(response.read().decode("utf-8", "replace") or "{}")
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return None
        return [str(item.get("name")) for item in models if isinstance(item, dict) and item.get("name")]
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
    # Reuse the router's loopback health probe for API/model facts.
    api = ollama_status() if not _offline() else {"state": "disabled", "reason": "offline mode", "version": None, "models": []}
    with _LOCK:
        server_proc = _SERVER.get("proc")
        server_state = _SERVER.get("state") or "stopped"
        if server_proc is not None and server_proc.poll() is None and server_state == "stopped":
            server_state = "running"
        logs = list(_SERVER.get("logs") or deque())
    arch = os.uname().machine
    supported_arch = arch in _ARCH_MAP
    return {
        "installed": bool(binary),
        "path": binary,
        "version": version,
        "endpoint": f"http://{_OLLAMA_HOST}:11434",
        "api_state": api.get("state"),
        "api_reason": api.get("reason"),
        "api_version": api.get("version"),
        "models": api.get("models") or [],
        "installed_candidates": api.get("installed_candidates") or [],
        "server": {
            "state": server_state,
            "managed": bool(server_proc is not None),
            "logs": logs[-8:],
        },
        "install": dict(_INSTALL),
        "platform": {
            "arch": arch,
            "supported_arch": supported_arch,
            "offline": _offline(),
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


def _safe_tar_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    for member in tar.getmembers():
        name = member.name.lstrip("./")
        if name.startswith("/") or ".." in Path(name).parts or not name:
            continue
        if not (name.startswith("bin/") or name.startswith("lib/")):
            continue
        if member.issym() or member.islnk():
            continue
        if not member.isfile():
            continue
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
        target = (root / member.name.lstrip("./")).resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError:
            raise RuntimeError("Archive contained an unsafe extraction path.")
    return members


def _download_to(url: str, destination: Path, job: dict[str, Any]) -> str | None:
    """Stream a URL to disk, updating job progress. Returns the sha256 hex."""
    job["started_mono"] = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": "Vortex/0.2 (operator-confirmed local install)"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed https URL
        total = response.headers.get("Content-Length")
        job["total_bytes"] = int(total) if total and total.isdigit() else None
        sha = hashlib.sha256()
        downloaded = 0
        temp = destination.with_name(destination.name + ".part")
        with temp.open("wb") as handle:
            while True:
                chunk = response.read(1 << 16)
                if not chunk:
                    break
                handle.write(chunk)
                sha.update(chunk)
                downloaded += len(chunk)
                job["downloaded_bytes"] = downloaded
                if job["total_bytes"]:
                    job["percent"] = round(min(99.0, downloaded * 100.0 / job["total_bytes"]), 1)
                _update_rate(job)
        temp.replace(destination)
    job.pop("started_mono", None)
    return sha.hexdigest()


def _verify_checksum(url: str, computed: str, job: dict[str, Any]) -> bool | None:
    """Return True when an official checksum matches, False on mismatch, None when unavailable."""
    try:
        request = urllib.request.Request(url + ".sha256", headers={"User-Agent": "Vortex/0.2"})
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            raw = response.read().decode("utf-8", "replace").strip().split()
        expected = raw[0].lower() if raw else ""
        if len(expected) == 64 and all(c in "0123456789abcdef" for c in expected):
            return computed == expected
        return None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _drain_log(proc: subprocess.Popen, name: str) -> None:
    try:
        for raw in proc.stdout:
            line = str(raw).rstrip()
            if len(line) > 400:
                line = line[:400] + "…"
            with _LOCK:
                _SERVER["logs"].append(line)
                _INSTALL["step"] = line if name == "install" else _INSTALL.get("step")
    except (OSError, ValueError):
        return
    finally:
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
        running = proc is not None and proc.poll() is None
        state = _SERVER.get("state") or ("running" if running else "stopped")
        return {
            "state": "running" if running else state,
            "managed": proc is not None,
            "binary": _SERVER.get("binary"),
            "logs": list(_SERVER.get("logs") or deque())[-8:],
        }


def start_server() -> dict[str, Any]:
    binary = _locate_binary()
    if not binary:
        raise PolicyError("Ollama is not installed on this host.")
    with _LOCK:
        proc = _SERVER.get("proc")
        if proc is not None and proc.poll() is None:
            _SERVER["state"] = "running"
            return _server_summary()
    env = _server_env()
    proc = subprocess.Popen(  # noqa: S603 - absolute, validated binary; argv typed
        [binary, "serve"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env=env, start_new_session=True,
    )
    with _LOCK:
        _SERVER["proc"] = proc
        _SERVER["state"] = "running"
        _SERVER["binary"] = binary
        _SERVER["logs"].append(f"[vortex] started ollama serve pid={proc.pid}")
    threading.Thread(target=_drain_log, args=(proc, "server"), daemon=True).start()
    return _server_summary()


def stop_server() -> dict[str, Any]:
    with _LOCK:
        proc = _SERVER.get("proc")
        _SERVER["state"] = "stopped"
        if proc is None or proc.poll() is not None:
            _SERVER["proc"] = None
            return _server_summary()
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
    with _LOCK:
        _SERVER["proc"] = None
        _SERVER["logs"].append("[vortex] stopped ollama serve")
    # Close the captured pipe even if the drain thread is still winding down;
    # closing is idempotent and prevents a per-cycle fd leak.
    try:
        if proc.stdout is not None:
            proc.stdout.close()
    except OSError:
        pass
    try:
        if proc.stderr is not None and proc.stderr is not proc.stdout:
            proc.stderr.close()
    except OSError:
        pass
    return _server_summary()


def _install_worker() -> None:
    job = _INSTALL
    try:
        arch = _install_arch()
        url = _DOWNLOAD_URL.format(arch=arch)
        root = _managed_root()
        bin_dir = root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            bin_dir.chmod(0o700)
        except OSError:
            pass
        _check_storage(1.5, "the Ollama runtime")
        job["status"] = "downloading"
        job["step"] = "Downloading the official Ollama tarball…"
        archive = root / f"ollama-linux-{arch}.tgz"
        computed = _download_to(url, archive, job)
        job["sha256"] = computed
        job["step"] = "Verifying archive integrity…"
        job["status"] = "verifying"
        verified = _verify_checksum(url, computed, job)
        job["checksum_verified"] = verified
        if verified is False:
            raise RuntimeError("Downloaded Ollama archive failed its checksum verification. The file was not installed.")
        job["step"] = "Extracting user-space Ollama…"
        job["status"] = "installing"
        job["percent"] = 99.0
        with tarfile.open(archive, "r:gz") as tar:
            members = _safe_tar_members(tar)
            if not any(m.name.lstrip("./").startswith("bin/") for m in members):
                raise RuntimeError("The downloaded archive did not contain the expected bin/ollama payload.")
            # Resolve every target and refuse traversal before extracting, then
            # extract with an absolute destination so tar does not join to cwd.
            members = _safe_extract_targets(root, members)
            tar.extractall(path=root, members=members)
        binary = _managed_binary()
        if not binary.is_file():
            raise RuntimeError("Ollama binary was not produced by the extraction.")
        binary.chmod(0o755)
        try:
            archive.unlink()
        except OSError:
            pass
        # Verify the executable before claiming anything.
        job["step"] = "Verifying the installed executable…"
        version = _short_timeout_versions(str(binary))
        if version is None:
            raise RuntimeError("The installed Ollama binary did not answer `--version`. Install aborted.")
        job["executable_verified"] = version
        job["step"] = "Starting the loopback service…"
        job["status"] = "starting"
        start_server()
        # Verify the loopback API before reporting success.
        job["step"] = "Verifying the loopback API…"
        api_version = _api_version()
        if api_version is None:
            raise RuntimeError("Ollama installed but its loopback API did not answer. It is not marked ready.")
        job["api_verified"] = api_version
        job["status"] = "completed"
        job["step"] = "Ollama installed, verified, and the loopback service is responding."
        job["percent"] = 100.0
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)[:300]
        job["failure_reason"] = _failure_reason(exc)
    finally:
        job.pop("started_mono", None)
        job["ended_at"] = now_iso()


def install_ollama(confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise PermissionError("operator confirmation is required to install Ollama")
    if _offline():
        raise PolicyError("Offline mode blocks the Ollama download. Disable offline mode to install.")
    binary = _locate_binary()
    if binary:
        _INSTALL["status"] = "completed"
        _INSTALL["step"] = "Ollama is already installed on this host."
        _INSTALL["percent"] = 100.0
        _INSTALL["error"] = None
        _INSTALL["failure_reason"] = None
        return dict(_INSTALL)
    with _LOCK:
        if _INSTALL.get("status") in {"preparing", "downloading", "verifying", "installing", "starting"}:
            return dict(_INSTALL)
        for key in ("status", "step", "percent", "downloaded_bytes", "total_bytes", "error", "failure_reason", "sha256", "checksum_verified", "executable_verified", "api_verified", "speed_bps", "eta_seconds"):
            _INSTALL[key] = None
        _INSTALL["status"] = "preparing"
        _INSTALL["step"] = "Preparing user-space install…"
        _INSTALL["percent"] = 0.0
        _INSTALL["downloaded_bytes"] = 0
        _INSTALL["total_bytes"] = None
        _INSTALL["started_at"] = now_iso()
        _INSTALL["ended_at"] = None
    threading.Thread(target=_install_worker, name="vortex-ollama-install", daemon=True).start()
    return dict(_INSTALL)


def _parse_progress_line(raw: str) -> dict[str, Any]:
    line = raw.strip()
    if not line:
        return {}
    try:
        return json.loads(line)
    except ValueError:
        return {"_raw": line[:200]}


def _pull_worker(name: str, job: dict[str, Any]) -> None:
    binary = _locate_binary()
    if not binary:
        job["status"] = "failed"
        job["error"] = "Ollama is not installed on this host."
        job["failure_reason"] = "runtime_missing"
        return
    env = _server_env()
    try:
        approx = _approx_size_gb(name)
        if approx is not None:
            _check_storage(approx + 0.5, f"model {name}")
        proc = subprocess.Popen(  # noqa: S603 - name validated by _MODEL_RE; shell=False
            [binary, "pull", name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=env, start_new_session=True,
        )
        job["pid"] = proc.pid
        job["started_mono"] = time.monotonic()
        job["status"] = "downloading"
        saw_success = False
        for line in proc.stderr:
            if job.get("cancel_event", threading.Event()).is_set():
                break
            payload = _parse_progress_line(line)
            if not payload:
                continue
            status = str(payload.get("status") or "")
            if status:
                job["last_status"] = status[:200]
            total = payload.get("total")
            completed = payload.get("completed")
            if status.startswith("downloading") and total:
                job["total_bytes"] = int(total)
                job["downloaded_bytes"] = int(completed or 0)
                job["percent"] = round(min(99.0, (int(completed or 0) * 100.0) / max(1, int(total))), 1)
                _update_rate(job)
            elif status == "success":
                saw_success = True
                job["percent"] = 100.0
            elif status == "pulling manifest" and job.get("percent", 0) < 2:
                job["percent"] = 2.0
        if job.get("cancel_event", threading.Event()).is_set():
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        proc.wait()
        try:
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stderr is not None:
                proc.stderr.close()
        except OSError:
            pass
        if job.get("cancel_event", threading.Event()).is_set():
            job["status"] = "cancelled"
            job["step"] = "Download cancelled."
        elif not saw_success or proc.returncode != 0:
            job["status"] = "failed"
            job["error"] = (job.get("last_status") or "ollama pull failed")[:300]
            job["failure_reason"] = "pull_failed"
        else:
            # Verify the model actually exists on the loopback API before
            # reporting completion; a clean exit alone is not proof.
            job["status"] = "verifying"
            job["step"] = "Verifying the downloaded model…"
            tags = _ollama_tags()
            if tags is None:
                job["status"] = "failed"
                job["error"] = "Download finished, but the loopback API did not confirm the model. It is not marked installed."
                job["failure_reason"] = "verification_failed"
            elif not any(t == name or t.startswith(name) for t in tags):
                job["status"] = "failed"
                job["error"] = f"Download finished, but the expected model `{name}` was not reported by Ollama."
                job["failure_reason"] = "verification_failed"
            else:
                job["status"] = "completed"
                job["step"] = "Model downloaded and verified."
                job["percent"] = 100.0
    except (OSError, subprocess.SubprocessError) as exc:
        job["status"] = "failed"
        job["error"] = str(exc)[:300]
        job["failure_reason"] = _failure_reason(exc)
    finally:
        job.pop("started_mono", None)
        job["ended_at"] = now_iso()
        job.pop("pid", None)


def pull_model(name: str) -> dict[str, Any]:
    name = (name or "").strip()
    if not name or len(name) > 160 or not _MODEL_RE.fullmatch(name):
        raise ValueError("model name must look like `model`, `model:tag`, or `namespace/model:tag`")
    if _offline():
        raise PolicyError("Offline mode blocks model downloads. Disable offline mode to download models.")
    binary = _locate_binary()
    if not binary:
        raise PolicyError("Ollama is not installed on this host. Install Ollama before downloading models.")
    with _LOCK:
        existing = _JOBS.get(name)
        if existing and existing.get("status") in {"preparing", "downloading", "verifying"}:
            return existing
        job = {
            "name": name, "status": "preparing", "percent": 0.0, "downloaded_bytes": 0,
            "total_bytes": None, "last_status": "preparing", "step": "Preparing download…",
            "error": None, "failure_reason": None, "speed_bps": None, "eta_seconds": None,
            "started_at": now_iso(), "ended_at": None, "cancel_event": threading.Event(),
        }
        _JOBS[name] = job
    threading.Thread(target=_pull_worker, args=(name, job), name=f"vortex-ollama-pull-{name[:16]}", daemon=True).start()
    return job


def cancel_download(name: str) -> dict[str, Any]:
    name = (name or "").strip()
    with _LOCK:
        job = _JOBS.get(name)
        if not job or job.get("status") not in {"preparing", "downloading", "verifying"}:
            return {"name": name, "status": job.get("status") if job else "not_found", "cancelled": False}
        job["cancel_event"].set()
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
        if job and job.get("status") in {"preparing", "downloading", "verifying"}:
            raise PolicyError("This model is downloading; cancel it before removing.")
    proc = subprocess.run([binary, "rm", name], capture_output=True, text=True, timeout=120, env=_server_env())  # noqa: S603
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "ollama rm failed").strip()[:300])
    return {"name": name, "removed": True}


def downloads() -> dict[str, Any]:
    with _LOCK:
        return {name: {k: v for k, v in job.items() if k != "cancel_event"} for name, job in _JOBS.items()}


def catalog() -> dict[str, Any]:
    """Curated catalog merged with the live Ollama tag list and download state."""
    try:
        from .router import MODEL_CATALOG
    except ImportError:  # pragma: no cover
        from models.router import MODEL_CATALOG  # type: ignore

    status = runtime_status()
    installed_names = {str(m.get("name") or "") for m in status.get("models", [])}
    installed_map = {str(m.get("name") or ""): m for m in status.get("models", [])}
    with _LOCK:
        live_jobs = {name: {k: v for k, v in job.items() if k != "cancel_event"} for name, job in _JOBS.items()}

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
            "download": job,
        })
    extras = []
    for name in installed_names:
        if not any(item["name"] == name or item["installed_name"] == name for item in items):
            extras.append({"name": name, "installed": True, "installed_detail": installed_map.get(name), "description": "Model installed on this host, outside the curated catalog."})
    return {
        "items": items,
        "extras": extras,
        "downloads": live_jobs,
        "runtime": status,
    }


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


def shutdown() -> None:
    """Stop the managed service and cancel any in-flight downloads."""
    with _LOCK:
        jobs = list(_JOBS.values())
    for job in jobs:
        event = job.get("cancel_event")
        if event:
            event.set()
    try:
        stop_server()
    except Exception:
        pass
