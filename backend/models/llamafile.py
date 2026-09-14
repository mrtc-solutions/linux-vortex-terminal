"""llamafile runtime + local model management (single-binary local LLM).

llamafile (https://github.com/mozilla-ai/llamafile) distributes llama.cpp as
one executable that serves an OpenAI-compatible API on loopback
(``./llamafile -m model.gguf --server --host 127.0.0.1 --port 8080``).
Vortex Terminal treats it as the primary local advisory provider:

* install: pinned release binary, GitHub digest + size verified, SHA-256
  re-verified after download, stored privately under the data root;
* models: owner-local ``.gguf`` files referenced in place (shared with the
  GGUF scanner) plus fused ``.llamafile`` executables imported privately;
* server: one managed loopback server process at a time, argv-only spawn;
* advisory: ``/v1/chat/completions`` with short timeouts, advisory-only —
  planning and the Guardian never depend on it.

Safety invariants (mirroring ``models.manager``):

* Every download is explicitly operator-confirmed and never runs in offline
  mode. No sudo, no ``curl | sh``.
* The server binds to loopback (``127.0.0.1``) only; explicit endpoint
  overrides must also be loopback HTTP.
* Filenames are validated (no traversal, no hidden files, bounded length);
  model argv is passed as single tokens with ``shell=False``.
* Downloads run on a background thread with pollable progress + cancel, so
  the HTTP request never blocks the UI.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    from ..vortex_backend import PolicyError, data_root, minimal_env, now_iso
except ImportError:  # pragma: no cover - direct module import
    from vortex_backend import PolicyError, data_root, minimal_env, now_iso  # type: ignore

try:
    from ..config import load_settings, save_settings
except ImportError:  # pragma: no cover - direct module import
    from config import load_settings, save_settings  # type: ignore

LLAMAFILE_VERSION = "0.10.5"
_RELEASE_API = f"https://api.github.com/repos/mozilla-ai/llamafile/releases/tags/{LLAMAFILE_VERSION}"
_ASSET_NAME = f"llamafile-{LLAMAFILE_VERSION}"
_DOWNLOAD_PREFIX = "/mozilla-ai/llamafile/releases/download/"
_MAX_RELEASE_METADATA_BYTES = 512 * 1024
_MAX_BINARY_BYTES = 512 * 1024 * 1024
_MAX_MODEL_BYTES = 16 * 1024 * 1024 * 1024
_MAX_CHAT_BYTES = 256 * 1024
_GGUF_MAGIC = b"GGUF"
_APE_MAGIC = b"MZ"
_START_TIMEOUT_SECONDS = 120.0
_PROBE_TIMEOUT_SECONDS = 2.0
_USER_AGENT = "Vortex/0.3"

_LOCK = threading.RLock()
_INSTALL: dict[str, Any] = {
    "status": "idle",
    "received_bytes": 0,
    "total_bytes": None,
    "error": None,
    "asset": None,
    "cancel_event": threading.Event(),
    "thread": None,
}
_TEST: dict[str, Any] = {"binary": None, "chat": None}


def set_test_binary(path: str | None) -> None:
    """Test-only override for the managed binary. Never used in production."""
    _TEST["binary"] = path


def set_test_chat(handler: Any) -> None:
    """Test-only chat double: handler(messages, model) -> text."""
    _TEST["chat"] = handler


# --------------------------------------------------------------------------
# Paths and state
# --------------------------------------------------------------------------

def managed_root() -> Path:
    root = data_root() / "llamafile"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _binary_path() -> Path:
    override = _TEST.get("binary")
    if override:
        return Path(str(override))
    return managed_root() / "bin" / _ASSET_NAME


def _imports_dir() -> Path:
    path = managed_root() / "models"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _state_path() -> Path:
    return managed_root() / "state.json"


def _pid_path() -> Path:
    return managed_root() / "server.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError:
        return {}
    if len(raw) > 64 * 1024:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp: Path | None = None
    try:
        handle, name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
        tmp = Path(name)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if tmp is not None and tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _effective_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Saved settings overlaid with explicit overrides (explicit keys win)."""
    try:
        saved = load_settings()
        base = dict(saved) if isinstance(saved, dict) else {}
    except Exception:
        base = {}
    if isinstance(settings, dict):
        base.update(settings)
    return base


def _offline(settings: dict[str, Any] | None = None) -> bool:
    try:
        return _effective_settings(settings).get("offline") is True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def validate_model_name(name: Any) -> str:
    """Validate an imported/registered model filename (never a path)."""
    text = str(name or "").strip()
    if not text or len(text) > 160 or "/" in text or "\\" in text or text.startswith("."):
        raise ValueError("model filename is invalid")
    lowered = text.lower()
    if not (lowered.endswith(".gguf") or lowered.endswith(".llamafile")):
        raise ValueError("model must be a .gguf or .llamafile file")
    return text


def _check_gguf_magic(path: Path) -> dict[str, Any]:
    try:
        details = path.stat()
    except OSError as exc:
        return {"ok": False, "reason": f"cannot stat file: {exc.strerror or exc}"}
    if not stat.S_ISREG(details.st_mode):
        return {"ok": False, "reason": "not a regular file"}
    size = int(details.st_size)
    if size <= 0:
        return {"ok": False, "reason": "file is empty"}
    if size > _MAX_MODEL_BYTES:
        return {"ok": False, "reason": "file exceeds the 16 GiB sanity cap"}
    try:
        with open(path, "rb") as handle:
            magic = handle.read(4)
    except OSError as exc:
        return {"ok": False, "reason": f"cannot read file: {exc.strerror or exc}"}
    if magic != _GGUF_MAGIC:
        return {"ok": False, "reason": "missing GGUF magic — not a GGUF file"}
    return {"ok": True, "size": size}


def _check_fused_magic(path: Path) -> dict[str, Any]:
    """Fused llamafiles are Actually Portable Executables (MZ header)."""
    try:
        details = path.stat()
    except OSError as exc:
        return {"ok": False, "reason": f"cannot stat file: {exc.strerror or exc}"}
    if not stat.S_ISREG(details.st_mode):
        return {"ok": False, "reason": "not a regular file"}
    size = int(details.st_size)
    if size < 1024 * 1024:
        return {"ok": False, "reason": "file is too small to be a fused llamafile"}
    if size > _MAX_MODEL_BYTES:
        return {"ok": False, "reason": "file exceeds the 16 GiB sanity cap"}
    try:
        with open(path, "rb") as handle:
            magic = handle.read(2)
    except OSError as exc:
        return {"ok": False, "reason": f"cannot read file: {exc.strerror or exc}"}
    if magic != _APE_MAGIC:
        return {"ok": False, "reason": "missing executable magic — not a fused llamafile"}
    return {"ok": True, "size": size}


# --------------------------------------------------------------------------
# Release resolution + verified download
# --------------------------------------------------------------------------

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
        raise PolicyError("The llamafile download redirected outside its reviewed HTTPS origins.")


def _read_json_response(response: Any, *, limit: int) -> Any:
    announced = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
    if announced is not None:
        try:
            announced_size = int(announced)
        except (TypeError, ValueError):
            announced_size = None
        if announced_size is not None and (announced_size < 0 or announced_size > limit):
            raise ValueError("release metadata exceeds the allowed size")
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("release metadata exceeds the allowed size")
    return json.loads(raw.decode("utf-8"))


def resolve_release_asset() -> dict[str, Any]:
    """Resolve the pinned llamafile binary with GitHub's SHA-256 digest."""
    request = urllib.request.Request(
        _RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - pinned GitHub API URL
        _validate_response_origin(response, frozenset({"api.github.com"}))
        payload = _read_json_response(response, limit=_MAX_RELEASE_METADATA_BYTES)
    if not isinstance(payload, dict) or payload.get("draft") is True or payload.get("prerelease") is True:
        raise RuntimeError("GitHub did not return a stable llamafile release.")
    assets = payload.get("assets")
    if not isinstance(assets, list) or len(assets) > 256:
        raise RuntimeError("llamafile release metadata did not contain a bounded asset list.")
    for item in assets:
        if not isinstance(item, dict) or item.get("name") != _ASSET_NAME:
            continue
        url = item.get("browser_download_url")
        digest = item.get("digest")
        size = item.get("size")
        if (
            isinstance(url, str)
            and _reviewed_https_url(url, frozenset({"github.com"}))
            and urllib.parse.urlsplit(url).path.startswith(_DOWNLOAD_PREFIX)
            and isinstance(digest, str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            and isinstance(size, int)
            and not isinstance(size, bool)
            and 0 < size <= _MAX_BINARY_BYTES
        ):
            return {"name": _ASSET_NAME, "url": url, "sha256": digest.split(":", 1)[1], "size": size}
        raise RuntimeError("The official llamafile asset lacks valid URL, size, or SHA-256 metadata.")
    raise RuntimeError(f"llamafile release {LLAMAFILE_VERSION} has no {_ASSET_NAME} asset.")


def _public_install() -> dict[str, Any]:
    with _LOCK:
        snapshot = dict(_INSTALL)
    snapshot.pop("cancel_event", None)
    snapshot.pop("thread", None)
    return snapshot


def _download_binary(asset: dict[str, Any], cancel: threading.Event) -> Path:
    dest_dir = managed_root() / "bin"
    dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp_path = dest_dir / f".{_ASSET_NAME}.part"
    expected = int(asset["size"])
    want_sha = str(asset["sha256"])
    request = urllib.request.Request(str(asset["url"]), headers={"User-Agent": _USER_AGENT})
    digest = hashlib.sha256()
    received = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - verified release URL
            _validate_response_origin(response, frozenset({"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}))
            with open(tmp_path, "wb") as handle:
                while True:
                    if cancel.is_set():
                        raise InterruptedError("install cancelled by operator")
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > expected or received > _MAX_BINARY_BYTES:
                        raise RuntimeError("llamafile binary exceeds its published size")
                    digest.update(chunk)
                    handle.write(chunk)
                    with _LOCK:
                        _INSTALL["received_bytes"] = received
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    if received != expected:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise RuntimeError(f"llamafile download truncated ({received}/{expected} bytes)")
    if digest.hexdigest() != want_sha:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise RuntimeError("llamafile SHA-256 mismatch — download rejected")
    final = dest_dir / _ASSET_NAME
    os.replace(tmp_path, final)
    os.chmod(final, 0o755)
    return final


def _install_worker() -> None:
    cancel = _INSTALL["cancel_event"]
    try:
        with _LOCK:
            _INSTALL.update({"status": "resolving", "received_bytes": 0, "total_bytes": None, "error": None})
        asset = resolve_release_asset()
        with _LOCK:
            _INSTALL.update({"status": "downloading", "total_bytes": asset["size"], "asset": asset["name"]})
        _download_binary(asset, cancel)
        with _LOCK:
            _INSTALL.update({"status": "ready", "error": None})
    except InterruptedError:
        with _LOCK:
            _INSTALL.update({"status": "cancelled", "error": "Install cancelled by operator."})
    except Exception as exc:  # honest failure surface
        with _LOCK:
            _INSTALL.update({"status": "error", "error": str(exc)[:300]})


def install(confirmed: bool, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start (or report) the operator-confirmed llamafile binary install."""
    if _offline(settings):
        return {"status": "blocked", "reason": "Offline mode blocks downloads. Disable offline mode to install llamafile."}
    if not confirmed:
        return {
            "status": "confirm_required",
            "version": LLAMAFILE_VERSION,
            "asset": _ASSET_NAME,
            "step": "Confirm to download the pinned llamafile binary from github.com (SHA-256 verified).",
        }
    with _LOCK:
        thread = _INSTALL.get("thread")
        if isinstance(thread, threading.Thread) and thread.is_alive():
            return _public_install()
        _INSTALL["cancel_event"] = threading.Event()
        worker = threading.Thread(target=_install_worker, name="llamafile-install", daemon=True)
        _INSTALL["thread"] = worker
        _INSTALL.update({"status": "starting", "received_bytes": 0, "total_bytes": None, "error": None})
        worker.start()
        return _public_install()


def cancel_install() -> dict[str, Any]:
    with _LOCK:
        event = _INSTALL.get("cancel_event")
    if isinstance(event, threading.Event):
        event.set()
    return _public_install()


def binary_status() -> dict[str, Any]:
    path = _binary_path()
    try:
        details = path.stat()
    except OSError:
        return {"present": False, "version": LLAMAFILE_VERSION, "asset": _ASSET_NAME,
                "reason": "llamafile binary is not installed"}
    if not stat.S_ISREG(details.st_mode):
        return {"present": False, "version": LLAMAFILE_VERSION, "asset": _ASSET_NAME,
                "reason": "llamafile binary path is not a regular file"}
    executable = os.access(path, os.X_OK)
    return {
        "present": True,
        "version": LLAMAFILE_VERSION,
        "asset": _ASSET_NAME,
        "size": int(details.st_size),
        "executable": bool(executable),
        "reason": None if executable else "binary is present but not executable",
    }


# --------------------------------------------------------------------------
# Model registry (GGUF in place + fused imports)
# --------------------------------------------------------------------------

def _gguf_scan(settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        try:
            from .gguf import scan as gguf_scan
        except ImportError:
            try:
                from models.gguf import scan as gguf_scan  # type: ignore
            except ImportError:
                from backend.models.gguf import scan as gguf_scan  # type: ignore
        values = _effective_settings(settings)
        found = gguf_scan(values.get("models_dir"))
    except Exception:
        return []
    valid = found.get("valid_files") if isinstance(found, dict) else None
    return list(valid) if isinstance(valid, list) else []


def _fused_models() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        directory = _imports_dir()
    except OSError:
        return entries
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return entries
    for name in names[:256]:
        if not name.lower().endswith(".llamafile") or name.startswith("."):
            continue
        path = directory / name
        check = _check_fused_magic(path)
        entries.append({
            "name": name,
            "kind": "fused",
            "path": str(path),
            "size": check.get("size"),
            "valid": bool(check.get("ok")),
            "reason": None if check.get("ok") else check.get("reason"),
        })
    return entries


def list_models(settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """All models llamafile can serve: validated GGUF (in place) + fused imports."""
    models: list[dict[str, Any]] = []
    for item in _gguf_scan(settings):
        if not isinstance(item, dict) or not item.get("name"):
            continue
        models.append({
            "name": str(item["name"]),
            "kind": "gguf",
            "path": str(item.get("path") or ""),
            "size": item.get("size"),
            "valid": True,
            "reason": None,
        })
    models.extend(_fused_models())
    return models


def resolve_model_path(name: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve a validated model name to an executable serving plan."""
    validated = validate_model_name(name)
    for item in list_models(settings):
        if item.get("name") == validated and item.get("valid") and item.get("path"):
            return {"name": validated, "kind": item["kind"], "path": str(item["path"])}
    raise PolicyError(f"Model '{validated}' is not available on this host.")


def import_model(source: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Import an owner-local model: .gguf registers its directory, .llamafile copies privately."""
    raw = str(source or "").strip()
    if not raw or len(raw) > 1024 or "\x00" in raw:
        raise ValueError("model path is invalid")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("model path must be absolute")
    lowered = path.name.lower()
    if path.name.startswith(".") or "/" in path.name or "\\" in path.name:
        raise ValueError("model filename is invalid")
    if lowered.endswith(".gguf"):
        check = _check_gguf_magic(path)
        if not check.get("ok"):
            raise PolicyError(f"GGUF validation failed: {check.get('reason')}")
        try:
            try:
                from . import gguf as gguf_module
            except ImportError:
                try:
                    from models import gguf as gguf_module  # type: ignore
                except ImportError:
                    from backend.models import gguf as gguf_module  # type: ignore
            selected = gguf_module.configure_local_source([str(path)])
            saved = save_settings({"models_dir": selected["directory"]})
            gguf_module.invalidate_scan_cache()
        except (ValueError, PolicyError):
            raise
        except Exception as exc:
            raise PolicyError(f"GGUF source registration failed: {str(exc)[:160]}")
        _invalidate_router_status()
        return {
            "name": path.name, "kind": "gguf", "directory": selected["directory"],
            "models_dir": saved.get("models_dir"),
            "message": "GGUF source registered. The file stays in its original location.",
        }
    if lowered.endswith(".llamafile"):
        check = _check_fused_magic(path)
        if not check.get("ok"):
            raise PolicyError(f"fused llamafile validation failed: {check.get('reason')}")
        dest = _imports_dir() / path.name
        if dest.exists():
            raise PolicyError(f"'{path.name}' is already imported.")
        shutil.copyfile(path, dest)
        os.chmod(dest, 0o700)
        return {"name": path.name, "kind": "fused", "size": check.get("size"),
                "message": "Fused llamafile imported into private storage."}
    raise ValueError("model must be a .gguf or .llamafile file")


def activate_model(name: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    validated = validate_model_name(name)
    resolved = resolve_model_path(validated, settings)
    saved = save_settings({"llamafile_model": validated})
    _invalidate_router_status()
    return {"model": saved.get("llamafile_model"), "kind": resolved["kind"],
            "state": "active", "provider": "llamafile"}


def remove_model(name: str) -> dict[str, Any]:
    validated = validate_model_name(name)
    if validated.lower().endswith(".gguf"):
        raise PolicyError("GGUF files live in your own directories; remove the file itself to drop it.")
    target = _imports_dir() / validated
    try:
        resolved = target.resolve()
    except OSError:
        raise PolicyError(f"'{validated}' is not imported.")
    try:
        imports_root = str(_imports_dir().resolve())
        same = os.path.commonpath((str(resolved), imports_root)) == imports_root
    except ValueError:
        same = False
    if not same or not target.is_file():
        raise PolicyError(f"'{validated}' is not imported.")
    target.unlink()
    try:
        if load_settings().get("llamafile_model") == validated:
            save_settings({"llamafile_model": ""})
    except Exception:
        pass
    _invalidate_router_status()
    return {"model": validated, "state": "removed", "provider": "llamafile"}


def _invalidate_router_status() -> None:
    try:
        try:
            from .router import invalidate_status_cache
        except ImportError:
            try:
                from models.router import invalidate_status_cache  # type: ignore
            except ImportError:
                from backend.models.router import invalidate_status_cache  # type: ignore
        invalidate_status_cache()
    except Exception:
        pass


# --------------------------------------------------------------------------
# Loopback server lifecycle
# --------------------------------------------------------------------------

def _loopback_endpoint(raw: Any, default_port: int = 8080) -> str:
    text = str(raw or "").strip() or f"http://127.0.0.1:{default_port}"
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        raise ValueError("llamafile endpoint is invalid")
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("llamafile endpoint must be loopback http://127.0.0.1:port")
    if parsed.username or parsed.password:
        raise ValueError("llamafile endpoint must not embed credentials")
    port = parsed.port or default_port
    if not 1 <= port <= 65535:
        raise ValueError("llamafile endpoint port is out of range")
    return f"http://127.0.0.1:{port}"


def _free_loopback_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _loopback_open(request: urllib.request.Request, timeout: float):
    # Loopback advisory traffic must never be diverted through inherited
    # proxy settings (privacy + correctness on proxied enterprise hosts).
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout)


def probe(endpoint: str) -> dict[str, Any]:
    """Health-probe a llamafile server. Never raises; degrades honestly."""
    try:
        url = _loopback_endpoint(endpoint)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    request = urllib.request.Request(url + "/v1/models", headers={"User-Agent": _USER_AGENT})
    try:
        with _loopback_open(request, _PROBE_TIMEOUT_SECONDS) as response:
            raw = response.read(64 * 1024)
    except Exception as exc:
        return {"ok": False, "reason": f"llamafile server not answering: {str(exc)[:140]}"}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"ok": False, "reason": "llamafile server returned invalid JSON"}
    data = payload.get("data") if isinstance(payload, dict) else None
    names = [str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id")] if isinstance(data, list) else []
    return {"ok": True, "models": names}


def _pid_record() -> dict[str, Any]:
    return _read_json(_pid_path())


def _process_alive(pid: Any) -> bool:
    try:
        number = int(pid)
    except (TypeError, ValueError):
        return False
    if number <= 0:
        return False
    try:
        os.kill(number, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def server_state(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Current managed-server state: running only when the PID lives AND answers."""
    settings = _effective_settings(settings)
    record = _pid_record()
    pid = record.get("pid")
    endpoint = str(record.get("endpoint") or "")
    model = str(record.get("model") or "")
    if pid and endpoint:
        if _process_alive(pid):
            health = probe(endpoint)
            if health.get("ok"):
                return {"state": "running", "pid": int(pid), "endpoint": endpoint,
                        "model": model, "served_models": health.get("models") or []}
            return {"state": "starting", "pid": int(pid), "endpoint": endpoint,
                    "model": model, "reason": str(health.get("reason") or "server is loading the model")}
        try:
            _pid_path().unlink()
        except OSError:
            pass
        return {"state": "stopped", "pid": None, "endpoint": None, "model": None,
                "reason": "previous server process exited"}
    override = settings.get("llamafile_endpoint")
    if override:
        try:
            url = _loopback_endpoint(override)
        except ValueError as exc:
            return {"state": "unavailable", "reason": str(exc)}
        health = probe(url)
        if health.get("ok"):
            return {"state": "external", "pid": None, "endpoint": url,
                    "model": model or None, "served_models": health.get("models") or [],
                    "reason": "Using the operator-configured loopback server."}
        return {"state": "unavailable", "endpoint": url, "reason": str(health.get("reason") or "server not answering")}
    return {"state": "stopped", "pid": None, "endpoint": None, "model": None, "reason": None}


def server_start(model: str | None = None, settings: dict[str, Any] | None = None,
                 *, timeout: float | None = None) -> dict[str, Any]:
    """Start the managed loopback server for one validated model."""
    settings = _effective_settings(settings)
    current = server_state(settings)
    if current.get("state") == "running":
        return {"state": "running", "endpoint": current["endpoint"], "model": current.get("model"),
                "pid": current.get("pid"), "served_models": current.get("served_models") or []}
    if current.get("state") == "starting" and _process_alive(current.get("pid")) and current.get("endpoint"):
        # A previous start is still loading the model. Wait on it instead of
        # spawning a second server that would orphan the first process.
        endpoint = str(current["endpoint"])
        deadline = time.monotonic() + max(5.0, min(float(timeout or _START_TIMEOUT_SECONDS), 600.0))
        last_reason = "server is loading the model"
        while time.monotonic() < deadline:
            if not _process_alive(current.get("pid")):
                break
            health = probe(endpoint)
            if health.get("ok"):
                return {"state": "running", "endpoint": endpoint, "model": current.get("model"),
                        "pid": current.get("pid"), "served_models": health.get("models") or []}
            last_reason = str(health.get("reason") or last_reason)
            time.sleep(1.0)
        else:
            raise PolicyError(f"llamafile server did not answer within the startup window: {last_reason}")
        # The in-flight process died while we waited; fall through to a fresh start.
    wanted = str(model or settings.get("llamafile_model") or "").strip()
    if not wanted:
        raise PolicyError("No llamafile model selected. Import a model and activate it first.")
    resolved = resolve_model_path(validate_model_name(wanted), settings)
    binary = _binary_path()
    if resolved["kind"] == "gguf":
        info = binary_status()
        if not info.get("present") or not info.get("executable"):
            raise PolicyError(str(info.get("reason") or "llamafile binary is not installed"))
        runner = str(binary)
        model_arg = ["-m", resolved["path"]]
    else:
        runner = resolved["path"]
        model_arg = []
        try:
            os.chmod(runner, 0o700)
        except OSError as exc:
            raise PolicyError(f"imported llamafile is not executable: {exc.strerror or exc}")
    try:
        gpu = settings.get("llamafile_gpu") is True
    except Exception:
        gpu = False
    port = _free_loopback_port()
    endpoint = f"http://127.0.0.1:{port}"
    argv = [runner, *model_arg, "--server", "--host", "127.0.0.1", "--port", str(port),
           "--nobrowser", "-ngl", "99" if gpu else "0"]
    try:
        proc = subprocess.Popen(
            argv, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, env=minimal_env(False), start_new_session=True,
        )
    except OSError as exc:
        raise PolicyError(f"llamafile server failed to start: {exc.strerror or exc}")
    _write_json(_pid_path(), {"pid": proc.pid, "endpoint": endpoint, "model": resolved["name"],
                              "kind": resolved["kind"], "started_at": now_iso()})
    deadline = time.monotonic() + max(5.0, min(float(timeout or _START_TIMEOUT_SECONDS), 600.0))
    last_reason = "server is loading the model"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            try:
                _pid_path().unlink()
            except OSError:
                pass
            raise PolicyError(f"llamafile server exited during startup (code {proc.returncode}). The model may not fit this host.")
        health = probe(endpoint)
        if health.get("ok"):
            return {"state": "running", "endpoint": endpoint, "model": resolved["name"],
                    "pid": proc.pid, "served_models": health.get("models") or []}
        last_reason = str(health.get("reason") or last_reason)
        time.sleep(1.0)
    raise PolicyError(f"llamafile server did not answer within the startup window: {last_reason}")


def server_stop() -> dict[str, Any]:
    record = _pid_record()
    pid = record.get("pid")
    if not pid:
        return {"state": "stopped", "reason": "no managed server was recorded"}
    try:
        number = int(pid)
    except (TypeError, ValueError):
        try:
            _pid_path().unlink()
        except OSError:
            pass
        return {"state": "stopped", "reason": "stale server record cleared"}
    try:
        os.kill(number, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as exc:
        return {"state": "unknown", "reason": f"could not signal server PID {number}: {exc.strerror or exc}"}
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not _process_alive(number):
            break
        time.sleep(0.2)
    else:
        try:
            os.kill(number, signal.SIGKILL)
        except OSError:
            pass
    try:
        _pid_path().unlink()
    except OSError:
        pass
    return {"state": "stopped", "pid": number}


# --------------------------------------------------------------------------
# Advisory chat (OpenAI-compatible, loopback only)
# --------------------------------------------------------------------------

def chat(messages: list[dict[str, str]], model: str, settings: dict[str, Any] | None = None,
         timeout: float = 20.0) -> dict[str, Any]:
    """One bounded chat completion against the loopback llamafile server."""
    handler = _TEST.get("chat")
    if handler is not None:
        started = time.monotonic()
        text = handler(messages, model)
        return {"text": str(text), "latency_ms": int((time.monotonic() - started) * 1000), "engine": "test-double"}
    settings = _effective_settings(settings)
    state = server_state(settings)
    endpoint = state.get("endpoint")
    if state.get("state") not in {"running", "external"} or not endpoint:
        raise PolicyError(str(state.get("reason") or "llamafile server is not running"))
    clean: list[dict[str, str]] = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user")[:16]
        content = str(item.get("content") or "")[:12000]
        if role not in {"system", "user", "assistant"}:
            role = "user"
        clean.append({"role": role, "content": content})
    if not clean:
        raise ValueError("chat messages are empty")
    body = json.dumps({
        "model": str(model or state.get("model") or "llamafile")[:160],
        "messages": clean,
        "temperature": 0.2,
        "max_tokens": 600,
        "stream": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        str(endpoint) + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT}, method="POST",
    )
    started = time.monotonic()
    try:
        with _loopback_open(request, max(2.0, min(float(timeout), 180.0))) as response:
            raw = response.read(_MAX_CHAT_BYTES + 1)
    except Exception as exc:
        raise PolicyError(f"llamafile chat failed: {str(exc)[:160]}")
    latency_ms = int((time.monotonic() - started) * 1000)
    if len(raw) > _MAX_CHAT_BYTES:
        raise PolicyError("llamafile reply exceeds the allowed size")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise PolicyError("llamafile reply was not valid JSON")
    choices = payload.get("choices") if isinstance(payload, dict) else None
    text = ""
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        text = str(message.get("content") or "")
    if not text.strip():
        raise PolicyError("llamafile returned an empty reply")
    return {"text": text[:6000], "latency_ms": latency_ms, "engine": "llamafile-server"}


# --------------------------------------------------------------------------
# Status snapshot (never raises)
# --------------------------------------------------------------------------

def status(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Best-effort llamafile snapshot for routing and the Models popup."""
    settings = _effective_settings(settings)
    try:
        enabled = settings.get("ai_enabled", True) is True
    except Exception:
        enabled = True
    if not enabled:
        return {"provider": "llamafile", "state": "disabled",
                "reason": "ai disabled by setting", "models": [], "active_model": None}
    try:
        binary = binary_status()
    except Exception as exc:
        binary = {"present": False, "reason": f"binary probe failed: {str(exc)[:120]}"}
    try:
        models = list_models(settings)
    except Exception:
        models = []
    try:
        server = server_state(settings)
    except Exception as exc:
        server = {"state": "unavailable", "reason": f"server probe failed: {str(exc)[:120]}"}
    try:
        active = str(settings.get("llamafile_model") or "") or None
    except Exception:
        active = None
    if active and not any(item.get("name") == active and item.get("valid") for item in models):
        active = None
    install_state = _public_install()
    if server.get("state") == "running":
        state, reason = "healthy", None
    elif server.get("state") == "external":
        state, reason = "healthy", str(server.get("reason") or "external loopback server")
    elif server.get("state") == "starting":
        state, reason = "degraded", str(server.get("reason") or "server is starting")
    elif not binary.get("present"):
        state, reason = "unavailable", "llamafile binary is not installed"
    elif not models:
        state, reason = "unavailable", "no validated GGUF or fused llamafile model on this host"
    elif not server.get("endpoint"):
        state, reason = "unavailable", "llamafile server is not running"
    else:
        state, reason = "unavailable", str(server.get("reason") or "llamafile server not answering")
    return {
        "provider": "llamafile",
        "state": state,
        "reason": reason,
        "version": LLAMAFILE_VERSION,
        "binary": binary,
        "server": server,
        "models": models,
        "active_model": active,
        "install": install_state,
        "gpu": bool(settings.get("llamafile_gpu")) if isinstance(settings, dict) else False,
    }


def shutdown() -> None:
    """Stop the install worker tracking (the server is operator-managed)."""
    with _LOCK:
        event = _INSTALL.get("cancel_event")
    if isinstance(event, threading.Event):
        event.set()
