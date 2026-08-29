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
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

PACKAGE = "linux-vortex-terminal"
FRONTEND_FILES = ("index.html", "app.js", "workspace.js", "terminal.js", "windows.js", "styles.css")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _app_version() -> str:
    try:
        from vortex_backend import APP_VERSION
    except ImportError:
        from backend.vortex_backend import APP_VERSION
    return APP_VERSION


def _data_root() -> Path:
    try:
        from vortex_backend import data_root
    except ImportError:
        from backend.vortex_backend import data_root
    return data_root()


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


def frontend_digest() -> str:
    """Digest over the live frontend files, matching apkbuild.sync_payload."""
    frontend = repo_root() / "frontend"
    digest_src = b"".join(sorted(
        (frontend / name).read_bytes() for name in FRONTEND_FILES if (frontend / name).is_file()
    ))
    return _sha256_bytes(digest_src)


def deb_script() -> Path:
    return repo_root() / "packaging" / "deb" / "build.sh"


def build_deb(output_dir: Path | None = None) -> dict[str, Any]:
    """Build a real .deb from the live tree. Always rebuilds from current files."""
    if shutil.which("dpkg-deb") is None:
        raise RuntimeError("dpkg-deb is required to build the desktop package. Install dpkg tools on this host first.")
    script = deb_script()
    if not script.is_file():
        raise RuntimeError("packaging/deb/build.sh is missing from this installation.")
    out = Path(output_dir).expanduser() if output_dir else desktop_dir()
    out.mkdir(parents=True, exist_ok=True)
    version = _app_version()
    env = dict(os.environ, VORTEX_VERSION=version)
    proc = subprocess.run(
        ["bash", str(script), str(out)],
        env=env, cwd=repo_root(), capture_output=True, text=True, timeout=300, check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")[:400]
        raise RuntimeError(f"deb build failed: {err}")
    package_path = out / f"{PACKAGE}_{version}_all.deb"
    if not package_path.is_file():
        raise RuntimeError("deb build finished but the package file is missing.")
    try:
        package_path.chmod(0o600)
    except OSError:
        pass
    return {
        "ok": True,
        "built": True,
        "path": str(package_path),
        "filename": package_path.name,
        "size_bytes": package_path.stat().st_size,
        "sha256": _sha256_bytes(package_path.read_bytes()),
        "package": PACKAGE,
        "version": version,
        "license": "MIT",
        "signed": False,
        "frontend_digest": frontend_digest(),
        "contents": "vortex CLI, Python sidecar, live frontend, man page, shell completions, desktop entry",
        "message": "Unsigned .deb built from the live workbench. Review it, then install with: sudo apt install ./<file>. The Electron shell is not bundled; run it from a checkout.",
    }


def deb_status() -> dict[str, Any]:
    directory = desktop_dir()
    candidates = sorted(
        (p for p in directory.glob(f"{PACKAGE}_*_all.deb") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return {"ok": False, "built": False, "message": "No desktop package has been built yet. Build first."}
    path = candidates[0]
    stat = path.stat()
    return {
        "ok": True,
        "built": True,
        "path": str(path),
        "filename": path.name,
        "size_bytes": stat.st_size,
        "sha256": _sha256_bytes(path.read_bytes()),
        "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
        "package": PACKAGE,
        "version": path.stem.split("_")[1] if "_" in path.stem else _app_version(),
        "license": "MIT",
        "signed": False,
    }
