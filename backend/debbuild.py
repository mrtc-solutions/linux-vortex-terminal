"""Build the Linux desktop (.deb) package of the Vortex Terminal workbench.

The package is a real Debian archive produced by the reviewed
``packaging/deb/build.sh`` script — the single source of truth for packaging.
This module only orchestrates it:

- runs the builder against the live repository tree (the same files the
  running sidecar serves), so a downloaded package can never lag behind the
  workbench that produced it;
- stages output under the Vortex Terminal data root (never inside the repository);
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
import re
import shutil
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
FRONTEND_FILES = ("index.html", "app.js", "workspace.js", "terminal.js", "windows.js", "models.js", "aiops.js", "agent.js", "hud.js", "styles.css")
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
        raise RuntimeError(f"A trusted {name} executable is required for packaging.")
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
    react = frontend.parent / "dist" / "index.html"
    try:
        details = react.lstat()
        if not stat.S_ISREG(details.st_mode) or details.st_size > 8 * 1024 * 1024:
            raise RuntimeError("React build is not a bounded regular file")
        payloads.append(react.read_bytes())
    except FileNotFoundError:
        if require_all:
            raise RuntimeError("React build missing: run npm run build before packaging")
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
    # Probe each control member explicitly: dpkg-deb exits 0 only when the
    # member exists, so a present maintainer script cannot hide behind output
    # formatting, and a Description that merely mentions one cannot trip us.
    for script in ("preinst", "postinst", "prerm", "postrm", "triggers"):
        probe = subprocess.run([dpkg_deb, "--info", str(path), script], capture_output=True, text=True, timeout=20, env=env)
        if probe.returncode == 0:
            raise RuntimeError(f"deb package unexpectedly contains a maintainer script ({script})")
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


_REPO_BUILD_LOCK = threading.Lock()
_REPO_TOKEN_RE = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
_MAX_REPO_BYTES = 512 * 1024 * 1024


def repo_script() -> Path:
    return repo_root() / "packaging" / "deb" / "make-repo.sh"


def repo_install_script() -> Path:
    return repo_root() / "packaging" / "deb" / "install-repo.sh"


def _repo_token(name: str, value: str) -> str:
    if not isinstance(value, str) or not _REPO_TOKEN_RE.match(value):
        raise ValueError(f"invalid repo {name}: {value!r} (bounded [A-Za-z0-9._+-] only)")
    return value


def _canonical_deb(path: Path, dpkg_deb: str, env: dict[str, Any]) -> dict[str, Any]:
    if path.is_symlink():
        raise RuntimeError(f"repo input cannot be a symlink: {path}")
    try:
        details = path.lstat()
    except OSError:
        raise RuntimeError(f"repo input is not readable: {path}")
    if not stat.S_ISREG(details.st_mode):
        raise RuntimeError(f"repo input is not a regular file: {path}")
    if details.st_size <= 0 or details.st_size > _MAX_PACKAGE_BYTES:
        raise RuntimeError(f"repo input has an invalid size: {path}")
    fields: dict[str, str] = {}
    for field in ("Package", "Version", "Architecture"):
        result = subprocess.run([dpkg_deb, "--field", str(path), field], capture_output=True, text=True, timeout=20, env=env)
        if result.returncode != 0 or not result.stdout.strip() or "\n" in result.stdout.strip():
            raise RuntimeError(f"repo input has an unreadable {field} field: {path}")
        fields[field] = result.stdout.strip()
    if fields["Package"] != PACKAGE:
        raise RuntimeError(f"repo input is not a {PACKAGE} package: {path}")
    return {"path": str(path), "filename": path.name, "version": fields["Version"], "arch": fields["Architecture"], "sha256": _sha256_file(path), "size": details.st_size}


def _resolve_repo_inputs(debs: list[str | Path] | None, dpkg_deb: str, env: dict[str, str]) -> list[dict[str, Any]]:
    if debs is not None and len(debs) == 0:
        raise ValueError("at least one repo input package is required")
    if debs:
        inputs = [_canonical_deb(Path(item).expanduser(), dpkg_deb, env) for item in debs]
    else:
        status = deb_status()
        if not status.get("built"):
            raise RuntimeError("no desktop package has been built yet; run `vortex desktop deb` first")
        inputs = [_canonical_deb(Path(status["path"]), dpkg_deb, env)]
    seen: set[tuple[str, str, str]] = set()
    names: set[str] = set()
    for item in inputs:
        key = (PACKAGE, item["version"], item["arch"])
        if key in seen:
            raise RuntimeError(f"duplicate repo input: {PACKAGE} {item['version']} ({item['arch']})")
        if item["filename"] in names:
            raise RuntimeError(f"repo input filename collision: {item['filename']}")
        seen.add(key)
        names.add(item["filename"])
    return inputs


def _contained(root: Path, rel: str, label: str) -> Path:
    """Resolve a repo-relative reference, refusing any directory escape."""
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        raise RuntimeError(f"repo {label} escapes its directory: {rel}")
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        raise RuntimeError(f"repo {label} escapes its directory: {rel}")
    return candidate


def _verify_repo(tree: Path, codename: str, component: str) -> dict[str, Any]:
    """Re-verify a staged repo tree from bytes: every hash must recompute."""
    dists = tree / "dists" / codename
    release = dists / "Release"
    if not release.is_file() or release.is_symlink():
        raise RuntimeError("repo build did not produce dists/<codename>/Release")
    total = 0
    for item in tree.rglob("*"):
        try:
            details = item.lstat()
        except OSError:
            raise RuntimeError("repo tree changed during verification; retry the build")
        if stat.S_ISLNK(details.st_mode) or not (stat.S_ISDIR(details.st_mode) or stat.S_ISREG(details.st_mode)):
            raise RuntimeError("repo tree contains an unsupported file type")
        if stat.S_ISREG(details.st_mode):
            total += details.st_size
            if total > _MAX_REPO_BYTES:
                raise RuntimeError("repo tree exceeds the verification limit")
    text = release.read_text(encoding="utf-8", errors="strict")
    if f"Codename: {codename}" not in text or f"Components: {component}" not in text:
        raise RuntimeError("repo Release names the wrong suite or component")
    hashed: dict[str, tuple[str, int]] = {}
    in_sha256 = False
    for line in text.splitlines():
        if line == "SHA256:":
            in_sha256 = True
            continue
        if in_sha256:
            match = re.match(r"^ ([0-9a-f]{64})\s+(\d+)\s+(\S+)$", line)
            if not match:
                in_sha256 = False
                continue
            hashed[match.group(3)] = (match.group(1), int(match.group(2)))
    if not hashed:
        raise RuntimeError("repo Release carries no SHA256 entries")
    indexed: list[Path] = []
    for rel, (digest, size) in sorted(hashed.items()):
        candidate = _contained(dists, rel, "Release entry")
        if not candidate.is_file() or candidate.is_symlink():
            raise RuntimeError(f"repo Release lists a missing index: {rel}")
        if candidate.stat().st_size != size or _sha256_file(candidate) != digest:
            raise RuntimeError(f"repo index hash mismatch: {rel}")
        indexed.append(candidate)
    # Every shipped index must be covered by the Release hashes: an extra
    # unsigned index file must fail verification rather than ship silently.
    for index in sorted((dists / component).rglob("Packages*")):
        if index.is_file() and index not in indexed:
            raise RuntimeError(f"repo index is not covered by Release hashes: {index.name}")
    shipped: list[dict[str, str]] = []
    for index in indexed:
        if index.name != "Packages":
            continue
        for stanza in index.read_text(encoding="utf-8", errors="strict").split("\n\n"):
            fields: dict[str, str] = {}
            for line in stanza.splitlines():
                if line and not line.startswith((" ", "\t")) and ":" in line:
                    key, _, value = line.partition(":")
                    fields[key.strip()] = value.strip()
            if not fields:
                continue
            for required in ("Package", "Version", "Filename", "Size", "SHA256"):
                if not fields.get(required):
                    raise RuntimeError("repo Packages stanza is missing " + required)
            if fields["Package"] != PACKAGE:
                raise RuntimeError(f"repo Packages stanza names a foreign package: {fields['Package']}")
            payload = _contained(tree, fields["Filename"], "payload reference")
            if not payload.is_file() or payload.is_symlink():
                raise RuntimeError(f"repo payload is missing: {fields['Filename']}")
            if str(payload.stat().st_size) != fields["Size"] or _sha256_file(payload) != fields["SHA256"]:
                raise RuntimeError(f"repo payload hash mismatch: {fields['Filename']}")
            shipped.append({"filename": payload.name, "version": fields["Version"], "sha256": fields["SHA256"]})
    if not shipped:
        raise RuntimeError("repo carries no installable packages")
    installer = tree / "install-repo.sh"
    if not installer.is_file() or installer.is_symlink() or not os.access(installer, os.X_OK):
        raise RuntimeError("repo is missing its executable installer (install-repo.sh)")
    return {
        "packages": shipped,
        "release_sha256": _sha256_file(release),
        "signed": (dists / "InRelease").is_file() and (dists / "Release.gpg").is_file(),
        "key_shipped": (tree / "vortex-archive-key.asc").is_file(),
        "installer": True,
    }


def _repo_target(output_dir: str | Path | None) -> Path:
    """Resolve the repo output path, rejecting names that cannot be a target.

    Runs before any lock or directory is touched so a bad output can never
    plant lock files or directories (e.g. under /) as a side effect.
    """
    out = Path(output_dir).expanduser() if output_dir else desktop_dir() / "repo"
    if not out.name or out.name in (".", ".."):
        raise ValueError(f"invalid repo output directory: {output_dir!r}")
    return out


def _build_repo(
    debs: list[str | Path] | None = None,
    output_dir: str | Path | None = None,
    codename: str = "stable",
    component: str = "main",
    sign_key: str | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Build an APT repository from built .debs. Caller serializes output."""
    codename = _repo_token("codename", codename)
    component = _repo_token("component", component)
    if sign_key is not None and (not isinstance(sign_key, str) or not sign_key or len(sign_key) > 128 or sign_key.startswith("-") or "\n" in sign_key):
        raise ValueError("invalid repo signing key id")
    dpkg_deb = _trusted_tool("dpkg-deb")
    bash = _trusted_tool("bash")
    # Trusted before staging: a signing request without a real gpg must fail
    # here, not after a repository was already generated.
    gpg = _trusted_tool("gpg") if sign_key else None
    script = repo_script()
    if not script.is_file():
        raise RuntimeError("packaging/deb/make-repo.sh is missing from this installation.")
    _, minimal_env, _ = _runtime_tools()
    env = minimal_env(False)
    env["VORTEX_DPKG_DEB"] = dpkg_deb
    if gpg:
        env["VORTEX_GPG"] = gpg
    inputs = _resolve_repo_inputs(debs, dpkg_deb, env)
    out = _repo_target(output_dir)
    out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = out.parent.resolve(strict=True)
    if os.geteuid() != 0 and parent.stat().st_uid != os.geteuid():
        raise PermissionError("repo output directory is not operator-owned")
    target = parent / out.name
    if os.path.lexists(target) and target.is_symlink():
        raise PermissionError("repo output cannot be a symlink")
    if os.path.lexists(target) and not replace:
        raise RuntimeError(f"a repository already exists at {target}; pass replace=True to rebuild it")
    with tempfile.TemporaryDirectory(prefix=".vortex-repo-build-", dir=str(parent)) as build_raw:
        build_dir = Path(build_raw)
        staged = build_dir / "repo"
        command = [bash, str(script), "--output", str(staged), "--codename", codename, "--component", component]
        for item in inputs:
            command.extend(["--deb", item["path"]])
        if sign_key:
            command.extend(["--sign", sign_key])
        proc = subprocess.run(command, env=env, cwd=repo_root(), capture_output=True, text=True, timeout=300, check=False)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[:400]
            raise RuntimeError(f"repo build failed: {err}")
        if not staged.is_dir() or staged.is_symlink():
            raise RuntimeError("repo build finished but the repository tree is missing.")
        verified = _verify_repo(staged, codename, component)
        backup: Path | None = None
        if os.path.lexists(target):
            if target.is_symlink():
                raise PermissionError("repo output cannot be a symlink")
            backup = parent / f".vortex-repo-backup-{os.getpid()}-{time.time_ns()}"
            os.rename(target, backup)
            try:
                os.rename(staged, target)
            except OSError:
                try:
                    os.rename(backup, target)
                except OSError:
                    pass
                raise
            try:
                shutil.rmtree(backup, ignore_errors=False)
            except OSError as exc:
                raise RuntimeError(f"repo published but the stale backup could not be removed: {backup} ({exc})")
        else:
            os.rename(staged, target)
    if verified["signed"] and verified["key_shipped"]:
        hint = (
            f"APT repository ready at {target}. Serve it over https (or copy the directory), then on the target machine, "
            "from inside the copied directory: sudo ./install-repo.sh --repo-url https://<host>/vortex --key ./vortex-archive-key.asc "
            "&& sudo apt install linux-vortex-terminal"
        )
    else:
        hint = (
            f"Unsigned APT repository ready at {target} (local testing only). On the target machine, "
            "copy the directory, then from inside it: sudo ./install-repo.sh --repo-path . --trust-unsigned "
            "&& sudo apt install linux-vortex-terminal"
        )
    return {
        "ok": True,
        "ready": True,
        "path": str(target),
        "codename": codename,
        "component": component,
        "count": len(verified["packages"]),
        "packages": verified["packages"],
        "release_sha256": verified["release_sha256"],
        "signed": verified["signed"],
        "key_shipped": verified["key_shipped"],
        "installer": verified["installer"],
        "package": PACKAGE,
        "license": "MIT",
        "message": hint,
    }


def build_repo(
    debs: list[str | Path] | None = None,
    output_dir: str | Path | None = None,
    codename: str = "stable",
    component: str = "main",
    sign_key: str | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Serialize repository staging and publication across threads/processes."""
    with _REPO_BUILD_LOCK:
        lock_root = _repo_target(output_dir).parent
        lock_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with exclusive_file_lock(lock_root / ".repo-build"):
            return _build_repo(debs, output_dir, codename, component, sign_key, replace)


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
