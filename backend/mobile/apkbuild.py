"""Build a signed Android APK of the VORTEX workbench client.

The APK is a real Android package:

- binary ``AndroidManifest.xml``;
- Dalvik ``classes.dex`` WebView activity;
- the current frontend synced into ``assets/www``;
- the MIT license;
- a bundled connection screen with a validated default sidecar origin.

Before every download the packager re-syncs the live frontend so the APK cannot
lag behind the running application. The activity always starts on that bundled
screen, so an address or capability can be changed without rebuilding. The
mobile client loads the same HTTP API
the desktop renderer uses, so every workbench capability is available on the
phone (plans, Guardian, PTY, tools, reports, engagements, STOP ALL).

Signing uses OpenSSL (already required by the host) to produce a JAR/APK v1
signature. No Android SDK, Gradle, or JDK is required.
"""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

from .axml import encode_manifest
from .dexwrite import build_webview_dex
try:
    from ..fileio import exclusive_file_lock, open_owner_binary
except ImportError:  # pragma: no cover - top-level mobile package import
    from fileio import exclusive_file_lock, open_owner_binary  # type: ignore

PACKAGE = "io.vortex.mobile"
APP_LABEL = "VORTEX"
VERSION_NAME = "0.2.23"
VERSION_CODE = 223
_BUILD_LOCK = threading.Lock()
_MAX_APK_BYTES = 128 * 1024 * 1024


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _backend_runtime():
    try:
        from vortex_backend import data_root, minimal_env, probe_executable
    except ImportError:
        from backend.vortex_backend import data_root, minimal_env, probe_executable
    return data_root, minimal_env, probe_executable


def _data_root() -> Path:
    data_root, _, _ = _backend_runtime()
    return data_root()


def _trusted_tool(name: str) -> str:
    _, _, probe_executable = _backend_runtime()
    identity = probe_executable(name, include_version=False)
    if identity.get("state") != "installed" or not identity.get("realpath"):
        raise RuntimeError(f"A trusted {name} executable is required for APK signing.")
    return str(identity["realpath"])


def mobile_dir() -> Path:
    root = _data_root() / "mobile"
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


def _trusted_apk_metadata(path: Path) -> tuple[os.stat_result, str]:
    digest = hashlib.sha256()
    with open_owner_binary(path, max_bytes=_MAX_APK_BYTES) as (handle, details):
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return details, digest.hexdigest()


def _sha256_b64(data: bytes) -> str:
    import base64
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def _validated_sidecar_url(sidecar_url: str) -> str:
    raw = (sidecar_url or "").strip()
    if not raw or len(raw) > 400 or any(ord(char) < 0x20 or ord(char) == 0x7f for char in raw):
        raise ValueError("sidecar_url is invalid")
    try:
        parsed = urllib.parse.urlsplit(raw)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("sidecar_url has an invalid host or port") from exc
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise ValueError("sidecar_url must be an HTTP(S) origin without credentials")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("sidecar_url must not contain a path, query, or fragment")
    try:
        ip = ipaddress.ip_address(host)
        canonical_host = f"[{ip}]" if ip.version == 6 else str(ip)
    except ValueError:
        try:
            canonical_host = host.encode("idna").decode("ascii").lower().rstrip(".")
        except UnicodeError as exc:
            raise ValueError("sidecar_url hostname is invalid") from exc
        labels = canonical_host.split(".")
        if not canonical_host or len(canonical_host) > 253 or any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            or any(not (char.isalnum() or char == "-") for char in label)
            for label in labels
        ):
            raise ValueError("sidecar_url hostname is invalid")
    netloc = canonical_host + (f":{port}" if port is not None else "")
    return urllib.parse.urlunsplit((parsed.scheme, netloc, "/", "", ""))


def connect_html(sidecar_url: str) -> str:
    url = html.escape(_validated_sidecar_url(sidecar_url), quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VORTEX</title>
  <style>
    body {{ margin:0; font-family: system-ui, sans-serif; background:#0a0a0c; color:#f0f0f4; }}
    main {{ max-width: 420px; margin: 12vh auto; padding: 24px; }}
    h1 {{ letter-spacing: 3px; font-size: 22px; }}
    p {{ color:#888a99; line-height:1.5; }}
    label {{ display:block; margin:14px 0 6px; color:#b6b7c2; font-size:13px; }}
    input {{ box-sizing:border-box; width:100%; padding:12px; background:#101015; color:#f0f0f4; border:1px solid #292a35; }}
    button {{ margin-top:12px; width:100%; padding:12px; background:#00d4aa; color:#07110f; border:0; font-weight:800; }}
    .license {{ margin-top:24px; font-size:12px; color:#5d5f70; }}
  </style>
</head>
<body>
  <main>
    <h1>VORTEX</h1>
    <p>This Android client is the same workbench. Enter the URL of the VORTEX sidecar running on your Kali/Linux host (same LAN).</p>
    <form id="f">
      <label for="u">Sidecar URL</label>
      <input id="u" value="{url}" aria-label="VORTEX sidecar URL" inputmode="url">
      <label for="t">Sidecar capability</label>
      <input id="t" type="password" autocomplete="off" aria-label="VORTEX sidecar capability" placeholder="Shown when the remote sidecar starts">
      <button type="submit">OPEN WORKBENCH</button>
    </form>
    <p id="error" role="alert" aria-live="assertive"></p>
    <p class="license">Licensed under the MIT License. Authorized use only. The capability is carried in a URL fragment, which is not sent in the initial HTTP request or written to sidecar logs.</p>
  </main>
  <script>
    document.getElementById('f').addEventListener('submit', function (e) {{
      e.preventDefault();
      var raw = document.getElementById('u').value.trim();
      var token = document.getElementById('t').value.trim();
      try {{
        var url = new URL(raw);
        if ((url.protocol !== 'http:' && url.protocol !== 'https:') || url.username || url.password || !url.hostname) throw new Error('Use an HTTP(S) URL without embedded credentials.');
        if ((url.pathname && url.pathname !== '/') || url.search || url.hash) throw new Error('Use only the sidecar origin — no path, query, or fragment.');
        if (raw.length > 400 || /[\\x00-\\x1f\\x7f]/.test(raw)) throw new Error('The sidecar URL is invalid.');
        if (token.length > 256 || /[\\x00-\\x1f\\x7f]/.test(token)) throw new Error('The capability must be at most 256 characters without control characters.');
        url.pathname = '/';
        url.hash = token ? 'vortex-token=' + encodeURIComponent(token) : '';
        document.getElementById('t').value = '';
        location.href = url.toString();
      }} catch (error) {{ document.getElementById('error').textContent = error.message || 'Enter a valid sidecar URL.'; }}
    }});
  </script>
</body>
</html>
"""


def sync_payload(sidecar_url: str, dest: Path) -> dict[str, Any]:
    """Copy the live frontend, license, and connect page into ``dest``."""
    sidecar_url = _validated_sidecar_url(sidecar_url)
    if dest.exists():
        shutil.rmtree(dest)
    www = dest / "www"
    www.mkdir(parents=True)
    frontend = repo_root() / "frontend"
    copied: list[str] = []
    for name in ("index.html", "app.js", "workspace.js", "terminal.js", "windows.js", "models.js", "hud.js", "styles.css"):
        src = frontend / name
        if src.is_file():
            shutil.copy2(src, www / name)
            copied.append(name)
    (www / "connect.html").write_text(connect_html(sidecar_url), encoding="utf-8")
    copied.append("connect.html")
    license_src = repo_root() / "LICENSE"
    if license_src.is_file():
        shutil.copy2(license_src, dest / "LICENSE")
    notice_src = repo_root() / "NOTICE"
    if notice_src.is_file():
        shutil.copy2(notice_src, dest / "NOTICE")
    (dest / "sidecar.txt").write_text(sidecar_url.strip() + "\n", encoding="utf-8")
    (dest / "build.json").write_text(json.dumps({
        "package": PACKAGE,
        "version": VERSION_NAME,
        "version_code": VERSION_CODE,
        "sidecar_url": sidecar_url,
        "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": copied,
        "license": "MIT",
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    digest_src = b"".join(sorted((www / name).read_bytes() for name in copied if (www / name).is_file()))
    return {
        "copied": copied,
        "sidecar_url": sidecar_url,
        "frontend_digest": _sha256_bytes(digest_src),
        "dest": str(dest),
    }


def _openssl(*args: str, input_bytes: bytes | None = None) -> bytes:
    _, minimal_env, _ = _backend_runtime()
    proc = subprocess.run(
        [_trusted_tool("openssl"), *args],
        input=input_bytes,
        capture_output=True,
        check=False,
        timeout=30,
        env=minimal_env(False),
    )
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace")[:400]
        raise RuntimeError(f"openssl {' '.join(args[:3])} failed: {err}")
    return proc.stdout


def _generate_signing_material(work: Path) -> tuple[Path, Path]:
    key = work / "key.pem"
    cert = work / "cert.pem"
    if key.is_file() and cert.is_file() and not key.is_symlink() and not cert.is_symlink():
        if key.stat().st_uid != os.geteuid() or cert.stat().st_uid != os.geteuid():
            raise PermissionError("APK signing material has a different owner")
        key.chmod(0o600)
        cert.chmod(0o600)
        return key, cert
    existing = [candidate for candidate in (key, cert) if os.path.lexists(candidate)]
    for candidate in existing:
        if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_uid != os.geteuid():
            raise PermissionError("unsafe APK signing material path")
    for candidate in existing:
        candidate.unlink()
    _openssl(
        "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-days", "3650",
        "-nodes", "-keyout", str(key), "-out", str(cert),
        "-subj", "/CN=VORTEX Mobile/O=VORTEX/OU=MIT-License",
    )
    try:
        key.chmod(0o600)
        cert.chmod(0o600)
    except OSError:
        pass
    return key, cert


def _jar_sign(entries: dict[str, bytes], key: Path, cert: Path) -> dict[str, bytes]:
    """APK signature scheme v1 (JAR signing) using OpenSSL CMS."""
    mf_lines = ["Manifest-Version: 1.0", "Created-By: VORTEX apkbuild", ""]
    sf_entries: list[tuple[str, str]] = []
    for name in sorted(entries):
        digest = _sha256_b64(entries[name])
        section = f"Name: {name}\nSHA-256-Digest: {digest}\n"
        mf_lines.append(section)
        sf_entries.append((name, _sha256_b64(section.encode("utf-8") + b"\n")))
    manifest = ("\n".join(mf_lines) + "\n").encode("utf-8")
    sf_lines = [
        "Signature-Version: 1.0",
        "Created-By: VORTEX apkbuild",
        f"SHA-256-Digest-Manifest: {_sha256_b64(manifest)}",
        "",
    ]
    for name, digest in sf_entries:
        sf_lines.append(f"Name: {name}")
        sf_lines.append(f"SHA-256-Digest: {digest}")
        sf_lines.append("")
    sf = ("\n".join(sf_lines) + "\n").encode("utf-8")
    rsa = _openssl(
        "cms", "-sign", "-binary", "-noattr", "-nodetach",
        "-outform", "DER",
        "-signer", str(cert),
        "-inkey", str(key),
        "-md", "sha256",
        input_bytes=sf,
    )
    signed = dict(entries)
    signed["META-INF/MANIFEST.MF"] = manifest
    signed["META-INF/CERT.SF"] = sf
    signed["META-INF/CERT.RSA"] = rsa
    return signed


def _write_apk(path: Path, entries: dict[str, bytes]) -> None:
    """Write a ZIP APK to a unique owner-only temporary file, then replace."""
    store_names = {"classes.dex", "resources.arsc", "AndroidManifest.xml"}
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    temp = Path(temp_name)
    try:
        with zipfile.ZipFile(temp, "w") as zf:
            for name in sorted(entries):
                info = zipfile.ZipInfo(name, date_time=time.gmtime(time.time())[:6])
                info.create_system = 0
                info.external_attr = 0o644 << 16
                compress = zipfile.ZIP_STORED if name in store_names or name.startswith("META-INF/") else zipfile.ZIP_DEFLATED
                zf.writestr(info, entries[name], compress_type=compress)
        with temp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _jar_sections(data: bytes) -> list[tuple[dict[str, str], bytes]]:
    """Parse the simple LF-delimited JAR sections emitted by this builder."""
    if b"\r" in data or b"\x00" in data:
        raise RuntimeError("APK signature metadata has invalid line encoding")
    parsed: list[tuple[dict[str, str], bytes]] = []
    for raw in data.split(b"\n\n"):
        if not raw:
            continue
        fields: dict[str, str] = {}
        for encoded_line in raw.split(b"\n"):
            try:
                line = encoded_line.decode("utf-8")
            except UnicodeError as exc:
                raise RuntimeError("APK signature metadata is not UTF-8") from exc
            if ": " not in line or line.startswith(" "):
                raise RuntimeError("APK signature metadata contains an unsupported field")
            key, value = line.split(": ", 1)
            if key in fields or not key or not value:
                raise RuntimeError("APK signature metadata contains a duplicate or empty field")
            fields[key] = value
        parsed.append((fields, raw + b"\n\n"))
    return parsed


def _verify_apk(path: Path) -> None:
    details = path.lstat()
    if not stat.S_ISREG(details.st_mode) or details.st_size <= 0 or details.st_size > _MAX_APK_BYTES:
        raise RuntimeError("APK output is not a bounded regular file")
    signature_names = {"META-INF/MANIFEST.MF", "META-INF/CERT.SF", "META-INF/CERT.RSA"}
    required = {
        "AndroidManifest.xml", "classes.dex", "assets/www/connect.html",
        "assets/www/index.html", "assets/www/app.js", *signature_names,
    }
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or not required.issubset(names):
            raise RuntimeError("APK output is missing required unique entries")
        if any(
            not name or name.startswith(("/", "\\")) or "\\" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))
            for name in names
        ):
            raise RuntimeError("APK output contains an unsafe entry name")
        total_uncompressed = sum(item.file_size for item in infos)
        if total_uncompressed > _MAX_APK_BYTES or any(item.file_size > _MAX_APK_BYTES for item in infos):
            raise RuntimeError("APK output exceeds the uncompressed verification limit")
        if archive.testzip() is not None:
            raise RuntimeError("APK output failed ZIP integrity verification")
        contents = {name: archive.read(name) for name in names}

    signature = contents["META-INF/CERT.RSA"]
    signature_file = contents["META-INF/CERT.SF"]
    manifest = contents["META-INF/MANIFEST.MF"]
    verified_content = _openssl("cms", "-verify", "-binary", "-inform", "DER", "-noverify", input_bytes=signature)
    if verified_content != signature_file:
        raise RuntimeError("APK signature did not verify against CERT.SF")

    manifest_sections = _jar_sections(manifest)
    signature_sections = _jar_sections(signature_file)
    if not manifest_sections or not signature_sections:
        raise RuntimeError("APK signature metadata is incomplete")
    signature_main = signature_sections[0][0]
    if signature_main.get("SHA-256-Digest-Manifest") != _sha256_b64(manifest):
        raise RuntimeError("APK manifest digest does not match CERT.SF")

    manifest_entries: dict[str, tuple[str, bytes]] = {}
    for fields, raw_section in manifest_sections[1:]:
        name = fields.get("Name")
        entry_digest = fields.get("SHA-256-Digest")
        if not name or not entry_digest or name in manifest_entries:
            raise RuntimeError("APK manifest contains an invalid entry section")
        manifest_entries[name] = (entry_digest, raw_section)
    signature_entries: dict[str, str] = {}
    for fields, _raw_section in signature_sections[1:]:
        name = fields.get("Name")
        section_digest = fields.get("SHA-256-Digest")
        if not name or not section_digest or name in signature_entries:
            raise RuntimeError("APK signature file contains an invalid entry section")
        signature_entries[name] = section_digest

    payload_names = set(contents) - signature_names
    if set(manifest_entries) != payload_names or set(signature_entries) != payload_names:
        raise RuntimeError("APK contains unsigned, missing, or extra manifest entries")
    for name in sorted(payload_names):
        expected_content, manifest_section = manifest_entries[name]
        if expected_content != _sha256_b64(contents[name]):
            raise RuntimeError(f"APK payload digest mismatch for {name}")
        if signature_entries[name] != _sha256_b64(manifest_section):
            raise RuntimeError(f"APK manifest-section digest mismatch for {name}")


def _build_apk(*, sidecar_url: str, output: Path | None = None) -> dict[str, Any]:
    """Sync live sources and produce a signed APK. Caller serializes shared staging."""
    url = _validated_sidecar_url(sidecar_url)
    work = mobile_dir()
    assets = work / "sync"
    sync = sync_payload(url, assets)
    # Always start on the bundled connection screen. Loading the baked URL
    # directly made a secured remote sidecar impossible to authenticate and
    # left users stranded whenever the host address changed.
    dex = build_webview_dex("file:///android_asset/www/connect.html")
    manifest = encode_manifest(
        package=PACKAGE,
        version_code=VERSION_CODE,
        version_name=VERSION_NAME,
        label=APP_LABEL,
        activity="io.vortex.mobile.MainActivity",
    )
    entries: dict[str, bytes] = {
        "AndroidManifest.xml": manifest,
        "classes.dex": dex,
        "assets/sidecar.txt": (url + "\n").encode("utf-8"),
        "assets/www/connect.html": (assets / "www" / "connect.html").read_bytes(),
    }
    www = assets / "www"
    for child in www.iterdir():
        if child.is_file():
            entries[f"assets/www/{child.name}"] = child.read_bytes()
    if (assets / "LICENSE").is_file():
        entries["assets/LICENSE"] = (assets / "LICENSE").read_bytes()
    if (assets / "NOTICE").is_file():
        entries["assets/NOTICE"] = (assets / "NOTICE").read_bytes()
    entries["assets/build.json"] = (assets / "build.json").read_bytes()
    sign_dir = work / "signing"
    sign_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    key, cert = _generate_signing_material(sign_dir)
    signed = _jar_sign(entries, key, cert)
    apk_path = Path(output).expanduser() if output is not None else (work / "vortex.apk")
    apk_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = apk_path.parent.resolve(strict=True)
    if os.geteuid() != 0 and parent.stat().st_uid != os.geteuid():
        raise PermissionError("APK output directory is not operator-owned")
    apk_path = parent / apk_path.name
    if os.path.lexists(apk_path) and apk_path.is_symlink():
        raise PermissionError("APK output cannot be a symlink")
    with tempfile.TemporaryDirectory(prefix=".vortex-apk-build-", dir=str(parent)) as stage_raw:
        staged_apk = Path(stage_raw) / apk_path.name
        _write_apk(staged_apk, signed)
        _verify_apk(staged_apk)
        if os.path.lexists(apk_path) and apk_path.is_symlink():
            raise PermissionError("APK output cannot be a symlink")
        os.replace(staged_apk, apk_path)
        try:
            directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    details, apk_sha256 = _trusted_apk_metadata(apk_path)
    return {
        "ok": True,
        "path": str(apk_path),
        "filename": apk_path.name,
        "size_bytes": details.st_size,
        "sha256": apk_sha256,
        "package": PACKAGE,
        "version": VERSION_NAME,
        "version_code": VERSION_CODE,
        "license": "MIT",
        "sidecar_url": url,
        "synced": sync,
        "contents": sorted(signed),
        "signed": True,
        "signature": "apk-v1-jar",
        "message": "APK synced from the live workbench and signed. Install on Android (allow unknown sources). The app loads this VORTEX sidecar.",
    }


def build_apk(*, sidecar_url: str, output: Path | None = None) -> dict[str, Any]:
    """Serialize signing/staging across threads and local sidecar processes."""
    with _BUILD_LOCK:
        with exclusive_file_lock(mobile_dir() / ".apk-build"):
            return _build_apk(sidecar_url=sidecar_url, output=output)


def apk_status() -> dict[str, Any]:
    path = mobile_dir() / "vortex.apk"
    try:
        details, apk_sha256 = _trusted_apk_metadata(path)
    except (OSError, ValueError):
        return {"ok": False, "built": False, "message": "No trusted APK has been built yet. Sync first."}
    return {
        "ok": True,
        "built": True,
        "path": str(path),
        "size_bytes": details.st_size,
        "sha256": apk_sha256,
        "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(details.st_mtime)),
        "license": "MIT",
    }
