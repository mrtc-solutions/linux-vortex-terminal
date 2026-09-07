"""Build the Linux desktop (.deb) package of the VORTEX workbench.

The package is a real Debian archive produced by the reviewed
``packaging/deb/build.sh`` script — the single source of truth for packaging.
This module only orchestrates it:

- runs the builder against the live repository tree (the same files the
  running sidecar serves), so a downloaded package can never lag behind the
  workbench that produced it;
- stages output under the VORTEX data root (never inside the repository);
- reports size/sha256 plus a frontend digest proving which UI the package
  carries.

Policy (see ``packaging/README.md``): the package is unsigned — signing is a
release-VM gate — installs no daemon, runs no maintainer scripts, and creates
no user data. The Electron shell is deliberately not bundled; it stays
optional and runs from a checkout.
"""
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

try:
    from .fileio import exclusive_file_lock, open_owner_binary
except ImportError:  # pragma: no cover - top-level backend import
    from fileio import exclusive_file_lock, open_owner_binary  # type: ignore

PACKAGE = "linux-vortex-terminal"
FRONTEND_FILES = ("index.html", "app.js", "workspace.js", "terminal.js", "windows.js", "models.js", "hud.js", "styles.css")
_BUILD_LOCK = threading.Lock()
_MAX_PACKAGE_BYTES = 256 * 1024 * 1024


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _app_version() -> str:
    try:
        from vortex_backend import APP_VERSION
    except ImportError:
        from backend.vortex_backend import APP_VERSION
    return APP_VERSION


def _runtime_tools():
    try:
        from vortex_backend import data_root, minimal_env, probe_executable
    except ImportError:
        from backend.vortex_backend import data_root, minimal_env, probe_executable
    return data_root, minimal_env, probe_executable


def _data_root() -> Path:
    data_root, _, _ = _runtime_tools()
    return data_root()


def _trusted_tool(name: str) -> str:
    _, _, probe_executable = _runtime_tools()
    identity = probe_executable(name, include_version=False)
    if identity.get("state") != "installed" or not identity.get("realpath"):
        raise RuntimeError(f"A trusted {name} executable is required to build the desktop package.")
    return str(identity["realpath"])


def desktop_dir() -> Path:
    root = _data_root() / "desktop"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trusted_package_metadata(path: Path) -> tuple[os.stat_result, str]:
    digest = hashlib.sha256()
    with open_owner_binary(path, max_bytes=_MAX_PACKAGE_BYTES) as (handle, details):
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return details, digest.hexdigest()


def _frontend_tree_digest(frontend: Path, *, require_all: bool = False) -> str:
    payloads: list[bytes] = []
    for name in FRONTEND_FILES:
        path = frontend / name
        try:
            details = path.lstat()
        except OSError:
            if require_all:
                raise RuntimeError(f"deb package is missing frontend/{name}")
            continue
        if not stat.S_ISREG(details.st_mode) or details.st_size > 8 * 1024 * 1024:
            raise RuntimeError(f"frontend/{name} is not a bounded regular file")
        payloads.append(path.read_bytes())
    return _sha256_bytes(b"".join(sorted(payloads)))


def _verify_deb(path: Path, version: str, dpkg_deb: str, env: dict[str, str]) -> str:
    details = path.lstat()
    if not stat.S_ISREG(details.st_mode):
        raise RuntimeError("deb build did not produce a regular package file")
    if details.st_size <= 0 or details.st_size > _MAX_PACKAGE_BYTES:
        raise RuntimeError("deb build produced an invalid package size")
    expected = {"Package": PACKAGE, "Version": version, "Architecture": "all"}
    for field, wanted in expected.items():
        result = subprocess.run([dpkg_deb, "--field", str(path), field], capture_output=True, text=True, timeout=20, env=env)
        if result.returncode != 0 or result.stdout.strip() != wanted:
            raise RuntimeError(f"deb package verification failed for {field}")
    info = subprocess.run([dpkg_deb, "--info", str(path)], capture_output=True, text=True, timeout=20, env=env)
    if info.returncode != 0:
        raise RuntimeError("dpkg-deb could not verify the built package")
    if any(marker in info.stdout.lower() for marker in (" preinst", " postinst", " prerm", " postrm", " triggers")):
        raise RuntimeError("deb package unexpectedly contains a maintainer script")

    # Inspect the actual payload rather than trusting only source-side intent.
    # This also gives the caller a digest of the frontend that really shipped.
    with tempfile.TemporaryDirectory(prefix=".vortex-deb-verify-", dir=str(path.parent)) as extract_raw:
        extract = Path(extract_raw)
        unpack = subprocess.run([dpkg_deb, "--extract", str(path), str(extract)], capture_output=True, text=True, timeout=60, env=env)
        if unpack.returncode != 0:
            raise RuntimeError("dpkg-deb could not extract the built package for verification")
        total = 0
        for item in extract.rglob("*"):
            item_details = item.lstat()
            if stat.S_ISLNK(item_details.st_mode) or not (stat.S_ISDIR(item_details.st_mode) or stat.S_ISREG(item_details.st_mode)):
                raise RuntimeError("deb package contains an unsupported payload file type")
            if stat.S_ISREG(item_details.st_mode):
                total += item_details.st_size
                if total > _MAX_PACKAGE_BYTES:
                    raise RuntimeError("deb package payload exceeds the verification limit")
        packaged_frontend = extract / "usr" / "share" / "vortex" / "frontend"
        return _frontend_tree_digest(packaged_frontend, require_all=True)


def frontend_digest() -> str:
    """Digest over the live frontend files, matching apkbuild.sync_payload."""
    return _frontend_tree_digest(repo_root() / "frontend", require_all=True)


def deb_script() -> Path:
    return repo_root() / "packaging" / "deb" / "build.sh"


def _build_deb(output_dir: Path | None = None) -> dict[str, Any]:
    """Build a real .deb from the live tree. Caller serializes shared output."""
    dpkg_deb = _trusted_tool("dpkg-deb")
    bash = _trusted_tool("bash")
    script = deb_script()
    if not script.is_file():
        raise RuntimeError("packaging/deb/build.sh is missing from this installation.")
    out = Path(output_dir).expanduser() if output_dir else desktop_dir()
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    out = out.resolve(strict=True)
    if os.geteuid() != 0 and out.stat().st_uid != os.geteuid():
        raise PermissionError("desktop package output directory is not operator-owned")
    version = _app_version()
    package_path = out / f"{PACKAGE}_{version}_all.deb"
    if os.path.lexists(package_path) and package_path.is_symlink():
        raise PermissionError("desktop package output cannot be a symlink")
    _, minimal_env, _ = _runtime_tools()
    env = minimal_env(False)
    env["VORTEX_VERSION"] = version
    env["VORTEX_DPKG_DEB"] = dpkg_deb
    source_frontend_digest = frontend_digest()
    with tempfile.TemporaryDirectory(prefix=".vortex-deb-build-", dir=str(out)) as build_raw:
        build_dir = Path(build_raw)
        staged_package = build_dir / package_path.name
        proc = subprocess.run(
            [bash, str(script), str(build_dir)],
            env=env, cwd=repo_root(), capture_output=True, text=True, timeout=300, check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[:400]
            raise RuntimeError(f"deb build failed: {err}")
        if not staged_package.is_file() or staged_package.is_symlink():
            raise RuntimeError("deb build finished but the package file is missing.")
        packaged_frontend_digest = _verify_deb(staged_package, version, dpkg_deb, env)
        if packaged_frontend_digest != source_frontend_digest or frontend_digest() != source_frontend_digest:
            raise RuntimeError("frontend changed during the desktop package build; retry from a stable source tree")
        staged_package.chmod(0o600)
        with staged_package.open("rb") as handle:
            os.fsync(handle.fileno())
        # A pre-existing symlink is treated as an unsafe operator-visible state,
        # while a race after this check remains safe because os.replace replaces
        # the directory entry itself rather than following it.
        if os.path.lexists(package_path) and package_path.is_symlink():
            raise PermissionError("desktop package output cannot be a symlink")
        os.replace(staged_package, package_path)
        try:
            directory_fd = os.open(out, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    details, package_sha256 = _trusted_package_metadata(package_path)
    return {
        "ok": True,
        "built": True,
        "path": str(package_path),
        "filename": package_path.name,
        "size_bytes": details.st_size,
        "sha256": package_sha256,
        "package": PACKAGE,
        "version": version,
        "license": "MIT",
        "signed": False,
        "frontend_digest": packaged_frontend_digest,
        "contents": "vortex CLI, Python sidecar, live frontend, man page, shell completions, desktop entry",
        "message": "Unsigned .deb built from the live workbench. Review it, then install with: sudo apt install ./<file>. The Electron shell is not bundled; run it from a checkout.",
    }


def build_deb(output_dir: Path | None = None) -> dict[str, Any]:
    """Serialize staging and publication across threads and sidecar processes."""
    with _BUILD_LOCK:
        lock_root = Path(output_dir).expanduser() if output_dir is not None else desktop_dir()
        lock_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with exclusive_file_lock(lock_root / ".deb-build"):
            return _build_deb(output_dir)


def deb_status() -> dict[str, Any]:
    directory = desktop_dir()
    candidates: list[tuple[Path, os.stat_result]] = []
    for path in directory.glob(f"{PACKAGE}_*_all.deb"):
        try:
            details = path.lstat()
            if stat.S_ISREG(details.st_mode) and details.st_uid == os.geteuid() and 0 < details.st_size <= _MAX_PACKAGE_BYTES:
                candidates.append((path, details))
        except OSError:
            continue
    candidates.sort(key=lambda item: item[1].st_mtime, reverse=True)
    for path, _observed in candidates[:100]:
        try:
            details, package_sha256 = _trusted_package_metadata(path)
        except (OSError, ValueError):
            continue
        return {
            "ok": True,
            "built": True,
            "path": str(path),
            "filename": path.name,
            "size_bytes": details.st_size,
            "sha256": package_sha256,
            "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(details.st_mtime)),
            "package": PACKAGE,
            "version": path.stem.split("_")[1] if "_" in path.stem else _app_version(),
            "license": "MIT",
            "signed": False,
        }
    return {"ok": False, "built": False, "message": "No desktop package has been built yet. Build first."}
