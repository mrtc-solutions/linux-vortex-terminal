"""Local GGUF model provider — primary on-device inference for VORTEX.

The operator keeps two curated GGUF files on their own Linux host
(``~/linux-vortex-terminal/models`` by default):

* ``Llama-3.2-3B-Instruct-Q4_K_M.gguf`` — fast conversation / explanation
* ``Qwen2.5-3B-Instruct-Q4_K_M.gguf`` — planning / analysis advisory

This module discovers, validates, and serves those files with tuning that
fits an 8 GB RAM / ~2 GHz CPU host: a single loaded model at a time,
2048-token context, bounded threads, and memory-mapped weights.

Inference engines (first available wins, honestly reported):

1. ``llama-cpp-python`` (optional pip package, in-process)
2. a ``llama-cli`` / ``llama.cpp`` style binary on the controlled PATH
   (subprocess, typed argv, timeout, process-group kill)
3. no engine → ``state == "unavailable"`` with actionable guidance.
   VORTEX never simulates model output.

Advisory-only contract: same JSON keys as the Ollama router
(``fact_summary``, ``meaning``, ``unknowns``, ``next_steps``, ``caution``,
``status_alignment``). Deterministic planning, Guardian, and the execution
authority never consume model text as instructions.
"""
from __future__ import annotations

import gc
import json
import os
import shutil
import signal
import stat
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

GGUF_MAGIC = b"GGUF"
MAX_GGUF_FILE_BYTES = 16 * 1024 ** 3  # sanity cap for a single prioritized file
MAX_GGUF_FILES = 64
MAX_FILENAME_LEN = 160

# The operator's two curated models. Discovery accepts any ``*.gguf`` file,
# but these two receive role defaults and first-class catalog entries.
KNOWN_FILES = (
    "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
)
ROLE_DEFAULTS = {
    # fast conversation + explanation
    "fast": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    "primary": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    # planning + analysis advisory
    "planner": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
    "specialist": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
}

# Conservative defaults for 8 GB RAM / ~2 GHz CPU. A 3B Q4_K_M file is
# ~2 GB on disk; resident set with mmap + 2048 ctx stays near ~2.5-3 GB,
# leaving headroom for the OS, sidecar, and one observed command.
LOW_RESOURCE_TUNING = {
    "n_ctx": 2048,
    "n_threads": 4,
    "n_batch": 128,
    "n_predict": 320,
    "temperature": 0.1,
    "use_mmap": True,
    "use_mlock": False,
    "verbose": False,
}
BALANCED_TUNING = {
    "n_ctx": 4096,
    "n_threads": 4,
    "n_batch": 256,
    "n_predict": 384,
    "temperature": 0.1,
    "use_mmap": True,
    "use_mlock": False,
    "verbose": False,
}

_CLI_CANDIDATES = ("llama-cli", "llama.cpp", "llamacpp", "llama")

_LOCK = threading.RLock()
_LOADED: dict[str, Any] = {"path": None, "handle": None, "family": None, "engine": None}
_SCAN_CACHE: dict[str, Any] = {"at": 0.0, "key": None, "value": None}
_SCAN_TTL_SECONDS = 5.0
# Explicit test-only engine hook. Production never sets this; it exists so
# the sandbox suite can exercise the provider chain without a 2 GB download.
_TEST_ENGINE: dict[str, Any] = {"handler": None}


def set_test_engine(handler: Any) -> None:
    """Install an explicit test double. ``None`` restores production behavior."""
    _TEST_ENGINE["handler"] = handler


def _minimal_env():
    try:
        from ..vortex_backend import minimal_env
    except ImportError:
        try:
            from vortex_backend import minimal_env  # type: ignore
        except ImportError:
            from backend.vortex_backend import minimal_env  # type: ignore
    return minimal_env


def _data_root() -> Path:
    try:
        from ..vortex_backend import data_root
    except ImportError:
        try:
            from vortex_backend import data_root  # type: ignore
        except ImportError:
            from backend.vortex_backend import data_root  # type: ignore
    return data_root()


def _repo_root() -> Path | None:
    try:
        here = Path(__file__).resolve()
    except OSError:
        return None
    for parent in (here.parent, *here.parents):
        if (parent / "cli" / "vortex.py").is_file() and (parent / "backend").is_dir():
            return parent
    return None


def candidate_dirs(models_dir: str | None = None) -> list[Path]:
    """Ordered GGUF search roots. Only owner-readable regular files are used."""
    ordered: list[Path] = []
    seen: set[str] = set()

    def _add(raw: str | Path | None) -> None:
        if not raw:
            return
        try:
            path = Path(str(raw)).expanduser()
        except (TypeError, ValueError, RuntimeError):
            return
        key = str(path)
        if key not in seen:
            seen.add(key)
            ordered.append(path)

    _add(models_dir)
    _add(os.environ.get("VORTEX_MODELS_DIR"))
    home = Path.home()
    _add(home / "linux-vortex-terminal" / "models")
    repo = _repo_root()
    if repo is not None:
        _add(repo / "models")
    try:
        _add(_data_root() / "models")
    except Exception:
        pass
    return ordered


def detect_family(filename: str) -> str:
    lowered = str(filename or "").lower()
    if "qwen" in lowered:
        return "qwen"
    if "llama" in lowered:
        return "llama"
    if "phi" in lowered:
        return "phi"
    if "gemma" in lowered:
        return "gemma"
    if "mistral" in lowered or "mixtral" in lowered:
        return "mistral"
    return "generic"


def detect_quant(filename: str) -> str | None:
    lowered = str(filename or "").lower()
    for token in ("q4_k_m", "q4_k_s", "q5_k_m", "q5_k_s", "q8_0", "q4_0", "q4_1", "q6_k", "f16", "q3_k_m"):
        if token in lowered:
            return token.upper()
    return None


def _read_header(path: Path) -> dict[str, Any]:
    """Validate the GGUF magic + version without loading weights.

    Real GGUF layout starts with ``GGUF`` (4 bytes), a uint32 version, then
    counts. Only the magic and version are read here; anything else is left
    to the inference engine, which reports its own load errors honestly.
    """
    try:
        details = path.stat()
    except OSError as exc:
        return {"ok": False, "reason": f"cannot stat file: {exc.strerror or exc}"}
    if not stat.S_ISREG(details.st_mode):
        return {"ok": False, "reason": "not a regular file"}
    size = int(details.st_size)
    if size <= 0:
        return {"ok": False, "reason": "file is empty"}
    if size > MAX_GGUF_FILE_BYTES:
        return {"ok": False, "reason": "file exceeds the 16 GiB sanity cap"}
    try:
        with open(path, "rb") as handle:
            magic = handle.read(4)
            version_raw = handle.read(4)
    except OSError as exc:
        return {"ok": False, "reason": f"cannot read file: {exc.strerror or exc}"}
    if magic != GGUF_MAGIC:
        return {"ok": False, "reason": "missing GGUF magic — not a GGUF file"}
    version = int.from_bytes(version_raw, "little") if len(version_raw) == 4 else None
    return {"ok": True, "size": size, "version": version}


def _mem_available_mb() -> int | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return None


def _mem_total_mb() -> int | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return None


def ram_fit(size_bytes: int | None) -> dict[str, Any]:
    """Estimate whether a GGUF file fits comfortably on this host.

    Estimate: resident ≈ file size × 1.25 + 512 MiB context/compute overhead.
    ``fits`` compares against currently available RAM; ``fits_8gb`` compares
    against the operator's 8 GB target so the UI can reassure before load.
    """
    available = _mem_available_mb()
    total = _mem_total_mb()
    if not size_bytes:
        return {"fits": None, "fits_8gb": None, "resident_mb": None,
                "available_mb": available, "total_mb": total}
    resident = int(size_bytes / (1024 * 1024) * 1.25) + 512
    return {
        "fits": (available is None) or (resident <= available),
        "fits_8gb": resident <= (8 * 1024 - 1536),
        "resident_mb": resident,
        "available_mb": available,
        "total_mb": total,
    }


def tuning_for_host(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve engine tuning: operator settings win, host profile is fallback."""
    settings = settings or {}
    total = _mem_total_mb()
    cpu = os.cpu_count() or 1
    low = (total is not None and total <= 8192) or (total is None) or cpu <= 4
    base = dict(LOW_RESOURCE_TUNING if low else BALANCED_TUNING)

    ctx = settings.get("gguf_ctx", base["n_ctx"])
    threads = settings.get("gguf_threads", min(base["n_threads"], max(1, cpu)))
    try:
        ctx = max(512, min(int(ctx), 8192))
    except (TypeError, ValueError):
        ctx = base["n_ctx"]
    try:
        threads = max(1, min(int(threads), max(1, cpu), 8))
    except (TypeError, ValueError):
        threads = min(base["n_threads"], max(1, cpu))
    if low:
        ctx = min(ctx, 2048)
        threads = min(threads, 4)
    base["n_ctx"] = ctx
    base["n_threads"] = threads
    base["profile"] = "low-resource" if low else "balanced"
    return base


def scan(models_dir: str | None = None, *, use_cache: bool = True) -> dict[str, Any]:
    """Discover and validate ``*.gguf`` files. Never raises on I/O problems."""
    import time as _time

    roots = candidate_dirs(models_dir)
    cache_key = json.dumps([str(p) for p in roots], sort_keys=True)
    now = _time.monotonic()
    if use_cache and _SCAN_CACHE.get("key") == cache_key:
        if (now - float(_SCAN_CACHE.get("at") or 0.0)) < _SCAN_TTL_SECONDS:
            cached = _SCAN_CACHE.get("value")
            if isinstance(cached, dict):
                return cached
    files: list[dict[str, Any]] = []
    searched: list[str] = []
    for root in roots:
        searched.append(str(root))
        try:
            if not root.is_dir():
                continue
        except OSError:
            continue
        try:
            entries = sorted(root.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for entry in entries:
            if len(files) >= MAX_GGUF_FILES:
                break
            try:
                name = entry.name
            except OSError:
                continue
            if not name.lower().endswith(".gguf") or len(name) > MAX_FILENAME_LEN:
                continue
            header = _read_header(entry)
            size = header.get("size")
            files.append({
                "name": name,
                "path": str(entry),
                "directory": str(root),
                "valid": bool(header.get("ok")),
                "reason": None if header.get("ok") else header.get("reason"),
                "size": size,
                "size_gb": round(size / (1024 ** 3), 2) if isinstance(size, int) else None,
                "version": header.get("version"),
                "family": detect_family(name),
                "quant": detect_quant(name),
                "curated": name in KNOWN_FILES,
                "ram": ram_fit(size if isinstance(size, int) else None),
            })
            if len(files) >= MAX_GGUF_FILES:
                break
    value = {
        "directories": searched,
        "files": files,
        "valid_files": [item for item in files if item.get("valid")],
        "curated_present": sorted({item["name"] for item in files if item.get("valid") and item.get("curated")}),
        "curated_missing": [name for name in KNOWN_FILES if name not in {item["name"] for item in files if item.get("valid")}],
    }
    _SCAN_CACHE.update({"at": now, "key": cache_key, "value": value})
    return value


def invalidate_scan_cache() -> None:
    _SCAN_CACHE.update({"at": 0.0, "key": None, "value": None})


def _trusted_cli() -> str | None:
    minimal_env = _minimal_env()
    controlled = minimal_env(False).get("PATH", "/usr/local/bin:/usr/bin:/bin")
    for name in _CLI_CANDIDATES:
        found = shutil.which(name, path=controlled)
        if not found:
            continue
        try:
            real = Path(found).resolve(strict=True)
            details = real.stat()
        except OSError:
            continue
        mode = stat.S_IMODE(details.st_mode)
        if not stat.S_ISREG(details.st_mode) or not (mode & 0o111) or (mode & 0o022):
            continue
        if details.st_mode & (stat.S_ISUID | stat.S_ISGID):
            continue
        return str(real)
    return None


def _python_engine_available() -> bool:
    try:
        import llama_cpp  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def engine_status() -> dict[str, Any]:
    """Detect real inference engines. No engine is ever faked."""
    if _TEST_ENGINE.get("handler") is not None:
        return {"state": "test-double", "python": False, "cli": None,
                "detail": "Explicit test engine is installed (sandbox tests only)."}
    python = _python_engine_available()
    cli = _trusted_cli()
    if python:
        state, detail = "ready", "llama-cpp-python is importable."
    elif cli:
        state, detail = "ready", f"CLI engine at {cli}."
    else:
        state, detail = "unavailable", (
            "No local GGUF engine was found. Install the optional "
            "'llama-cpp-python' package or a llama-cli binary to enable "
            "on-device inference; Ollama and the agent council remain as fallback."
        )
    return {"state": state, "python": python, "cli": cli, "detail": detail}


def status(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """One honest snapshot: files + engine + resolved roles + tuning."""
    settings = settings or {}
    if settings.get("gguf_enabled") is False:
        return {
            "provider": "gguf", "state": "disabled",
            "reason": "GGUF provider disabled in settings.",
            "files": [], "engine": engine_status(), "roles": {},
        }
    found = scan(settings.get("models_dir"))
    engine = engine_status()
    valid = found.get("valid_files") or []
    if not valid:
        return {
            "provider": "gguf", "state": "unavailable",
            "reason": ("No valid *.gguf file was found in: " + ", ".join(found["directories"][:3])),
            "files": found["files"], "directories": found["directories"],
            "engine": engine, "roles": {},
            "curated_present": found["curated_present"], "curated_missing": found["curated_missing"],
        }
    if engine.get("state") == "unavailable":
        return {
            "provider": "gguf", "state": "unavailable",
            "reason": str(engine.get("detail")),
            "files": found["files"], "directories": found["directories"],
            "engine": engine, "roles": _resolve_roles(settings, valid),
            "curated_present": found["curated_present"], "curated_missing": found["curated_missing"],
        }
    by_name = {item["name"]: item for item in valid}
    roles = _resolve_roles(settings, valid)
    return {
        "provider": "gguf", "state": "healthy",
        "reason": None,
        "files": found["files"], "directories": found["directories"],
        "engine": engine, "roles": roles,
        "tuning": tuning_for_host(settings),
        "loaded": _LOADED.get("path"),
        "curated_present": found["curated_present"], "curated_missing": found["curated_missing"],
        "message": f"{len(valid)} valid GGUF file(s); engine {engine.get('state')}.",
    }


def _resolve_roles(settings: dict[str, Any], valid: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    names = {item["name"] for item in valid}
    roles: dict[str, dict[str, Any]] = {}
    for role in ("primary", "planner", "fast", "specialist"):
        configured = str(settings.get(f"gguf_{role}") or ROLE_DEFAULTS.get(role) or "").strip()
        resolved = configured if configured in names else None
        if resolved is None and valid:
            # Same-family fallback inside the GGUF pool only.
            want_family = detect_family(configured)
            resolved = next((item["name"] for item in valid if item["family"] == want_family), None)
        roles[role] = {
            "configured": configured,
            "resolved": resolved,
            "state": "active" if resolved else "unavailable",
            "family_fallback": bool(resolved and resolved != configured),
        }
    return roles


def file_for_role(role: str, settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    snapshot = status(settings or {})
    if snapshot.get("state") != "healthy":
        return None
    entry = (snapshot.get("roles") or {}).get(role) or {}
    resolved = entry.get("resolved")
    if not resolved:
        return None
    for item in snapshot.get("files") or []:
        if item.get("name") == resolved and item.get("valid"):
            return item
    return None


def build_prompt(family: str, system: str, user_json: str) -> str:
    """Per-family chat template so both curated models behave correctly."""
    family = (family or "generic").lower()
    if family == "llama":
        return (
            "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n"
            f"{system}<|eot_id|><|start_header_id|>user<|end_header_id|>\n"
            f"{user_json}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n"
        )
    if family == "qwen":
        return (
            "<|im_start|>system\n" f"{system}<|im_end|>\n"
            "<|im_start|>user\n" f"{user_json}<|im_end|>\n"
            "<|im_start|>assistant\n"
        )
    return f"System: {system}\n\nUser:\n{user_json}\n\nAssistant (compact JSON only):\n"


def _load_python_engine(path: str, tuning: dict[str, Any]) -> Any:
    from llama_cpp import Llama  # type: ignore
    return Llama(
        model_path=path,
        n_ctx=int(tuning.get("n_ctx", 2048)),
        n_threads=int(tuning.get("n_threads", 4)),
        n_batch=int(tuning.get("n_batch", 128)),
        use_mmap=bool(tuning.get("use_mmap", True)),
        use_mlock=bool(tuning.get("use_mlock", False)),
        verbose=bool(tuning.get("verbose", False)),
    )


def _unload_locked() -> None:
    handle = _LOADED.get("handle")
    _LOADED.update({"path": None, "handle": None, "family": None, "engine": None})
    if handle is not None:
        try:
            closer = getattr(handle, "close", None)
            if callable(closer):
                closer()
        except Exception:
            pass
        del handle
        gc.collect()


def unload() -> None:
    """Release the loaded model (single-slot policy for 8 GB hosts)."""
    with _LOCK:
        _unload_locked()


def _ensure_loaded_locked(entry: dict[str, Any], tuning: dict[str, Any]) -> dict[str, Any]:
    engine = engine_status()
    if _TEST_ENGINE.get("handler") is not None:
        _LOADED.update({"path": entry["path"], "handle": "test-double",
                        "family": entry.get("family"), "engine": "test-double"})
        return {"engine": "test-double", "handle": "test-double"}
    if engine.get("python"):
        if _LOADED.get("path") == entry["path"] and _LOADED.get("engine") == "python":
            return {"engine": "python", "handle": _LOADED.get("handle")}
        # Single-slot policy: exactly one model resident on low-resource hosts.
        _unload_locked()
        handle = _load_python_engine(entry["path"], tuning)
        _LOADED.update({"path": entry["path"], "handle": handle,
                        "family": entry.get("family"), "engine": "python"})
        return {"engine": "python", "handle": handle}
    if engine.get("cli"):
        # CLI engines are stateless per invocation; nothing stays resident.
        if _LOADED.get("path") != entry["path"]:
            _unload_locked()
            _LOADED.update({"path": entry["path"], "handle": None,
                            "family": entry.get("family"), "engine": "cli"})
        return {"engine": "cli", "handle": None}
    raise RuntimeError(str(engine.get("detail") or "No GGUF engine available."))


def _terminate(proc: subprocess.Popen) -> None:
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


def _complete_python(handle: Any, prompt: str, tuning: dict[str, Any], timeout: float) -> str:
    from concurrent.futures import ThreadPoolExecutor

    def _call() -> str:
        out = handle(
            prompt,
            max_tokens=int(tuning.get("n_predict", 320)),
            temperature=float(tuning.get("temperature", 0.1)),
            stop=["<|eot_id|>", "<|im_end|>", "<|end_of_text|>"],
        )
        choices = (out or {}).get("choices") or []
        if not choices:
            raise ValueError("empty completion from local model")
        return str((choices[0].get("text") or ""))

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_call)
        try:
            return future.result(timeout=timeout)
        except Exception as exc:
            # llama-cpp-python has no cooperative cancel; the worker thread is
            # daemon-adjacent via the pool shutdown, and the next call unloads.
            raise TimeoutError(f"local model timed out after {timeout}s") from exc


def _complete_cli(binary: str, model_path: str, prompt: str, tuning: dict[str, Any], timeout: float) -> str:
    minimal_env = _minimal_env()
    argv = [
        binary, "-m", model_path,
        "-n", str(int(tuning.get("n_predict", 320))),
        "-c", str(int(tuning.get("n_ctx", 2048))),
        "-t", str(int(tuning.get("n_threads", 4))),
        "-temp", str(float(tuning.get("temperature", 0.1))),
        "--no-display-prompt", "-p", prompt,
    ]
    proc = subprocess.Popen(  # noqa: S603 - absolute validated binary; typed argv
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=minimal_env(False), start_new_session=True, close_fds=True,
    )
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _terminate(proc)
            raise TimeoutError(f"local model timed out after {timeout}s") from exc
        if proc.returncode != 0:
            raise RuntimeError((stderr or stdout or "llama-cli failed").strip()[:300])
        return stdout.strip()[:4000]
    finally:
        _terminate(proc)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def complete(entry: dict[str, Any], system: str, user_json: str,
             settings: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
    """Run one bounded advisory completion. Raises on any failure (no fake text)."""
    settings = settings or {}
    if timeout is None:
        try:
            timeout = max(2, min(int(settings.get("gguf_timeout_seconds", 20)), 120))
        except (TypeError, ValueError):
            timeout = 20
    tuning = tuning_for_host(settings)
    prompt = build_prompt(str(entry.get("family") or "generic"), system, user_json)
    started = time.monotonic()
    handler = _TEST_ENGINE.get("handler")
    if handler is not None:
        text = handler(entry, system, user_json)
        return {"text": str(text or ""), "latency_ms": int((time.monotonic() - started) * 1000),
                "engine": "test-double", "model": entry.get("name")}
    with _LOCK:
        loaded = _ensure_loaded_locked(entry, tuning)
        handle = loaded.get("handle")
        engine_name = str(loaded.get("engine"))
    if engine_name == "python":
        text = _complete_python(handle, prompt, tuning, float(timeout))
    elif engine_name == "cli":
        binary = str(engine_status().get("cli") or "")
        if not binary:
            raise RuntimeError("CLI engine disappeared.")
        text = _complete_cli(binary, str(entry["path"]), prompt, tuning, float(timeout))
    else:
        raise RuntimeError("No GGUF engine available.")
    return {"text": text, "latency_ms": int((time.monotonic() - started) * 1000),
            "engine": engine_name, "model": entry.get("name")}
