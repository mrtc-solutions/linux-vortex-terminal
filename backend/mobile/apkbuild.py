"""Build a signed Android APK of the VORTEX workbench client.

The APK is a real Android package:

- binary ``AndroidManifest.xml``;
- Dalvik ``classes.dex`` WebView activity;
- the current frontend synced into ``assets/www``;
- the MIT license;
- a sidecar URL baked in at sync time so the phone talks to this workbench.

Before every download the packager re-syncs the live frontend so the APK cannot
lag behind the running application. The mobile client loads the same HTTP API
the desktop renderer uses, so every workbench capability is available on the
phone (plans, Guardian, PTY, tools, reports, engagements, STOP ALL).

Signing uses OpenSSL (already required by the host) to produce a JAR/APK v1
signature. No Android SDK, Gradle, or JDK is required.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from .axml import encode_manifest
from .dexwrite import build_webview_dex

PACKAGE = "io.vortex.mobile"
APP_LABEL = "VORTEX"
VERSION_NAME = "0.2.21"
VERSION_CODE = 221


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _data_root() -> Path:
    try:
        from vortex_backend import data_root
    except ImportError:
        from backend.vortex_backend import data_root
    return data_root()


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


def _sha256_b64(data: bytes) -> str:
    import base64
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def connect_html(sidecar_url: str) -> str:
    url = sidecar_url.replace("&", "&amp;").replace('"', "&quot;")
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
    input {{ width:100%; padding:12px; background:#101015; color:#f0f0f4; border:1px solid #292a35; }}
    button {{ margin-top:12px; width:100%; padding:12px; background:#00d4aa; color:#07110f; border:0; font-weight:800; }}
    .license {{ margin-top:24px; font-size:12px; color:#5d5f70; }}
  </style>
</head>
<body>
  <main>
    <h1>VORTEX</h1>
    <p>This Android client is the same workbench. Enter the URL of the VORTEX sidecar running on your Kali/Linux host (same LAN).</p>
    <form id="f">
      <input id="u" value="{url}" aria-label="VORTEX sidecar URL">
      <button type="submit">OPEN WORKBENCH</button>
    </form>
    <p class="license">Licensed under the MIT License. Authorized use only.</p>
  </main>
  <script>
    document.getElementById('f').addEventListener('submit', function (e) {{
      e.preventDefault();
      var url = document.getElementById('u').value.trim();
      if (url) location.href = url;
    }});
  </script>
</body>
</html>
"""


def sync_payload(sidecar_url: str, dest: Path) -> dict[str, Any]:
    """Copy the live frontend, license, and connect page into ``dest``."""
    if dest.exists():
        shutil.rmtree(dest)
    www = dest / "www"
    www.mkdir(parents=True)
    frontend = repo_root() / "frontend"
    copied: list[str] = []
    for name in ("index.html", "app.js", "workspace.js", "terminal.js", "windows.js", "styles.css"):
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
    proc = subprocess.run(
        ["openssl", *args],
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace")[:400]
        raise RuntimeError(f"openssl {' '.join(args[:3])} failed: {err}")
    return proc.stdout


def _generate_signing_material(work: Path) -> tuple[Path, Path]:
    key = work / "key.pem"
    cert = work / "cert.pem"
    if key.is_file() and cert.is_file():
        return key, cert
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
    """Write a ZIP APK. DEX/ARSC/manifest stored uncompressed for device loaders."""
    store_names = {"classes.dex", "resources.arsc", "AndroidManifest.xml"}
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w") as zf:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=time.gmtime(time.time())[:6])
            info.create_system = 0
            info.external_attr = 0o644 << 16
            compress = zipfile.ZIP_STORED if name in store_names or name.startswith("META-INF/") else zipfile.ZIP_DEFLATED
            zf.writestr(info, entries[name], compress_type=compress)
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def build_apk(*, sidecar_url: str, output: Path | None = None) -> dict[str, Any]:
    """Sync live sources and produce a signed APK. Always rebuilds from current files."""
    url = (sidecar_url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("sidecar_url must be an http(s) URL")
    if any(c in url for c in "\x00\n\r"):
        raise ValueError("sidecar_url contains control characters")
    work = mobile_dir()
    assets = work / "sync"
    sync = sync_payload(url, assets)
    dex = build_webview_dex(url)
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
    apk_path = output or (work / "vortex.apk")
    apk_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _write_apk(apk_path, signed)
    return {
        "ok": True,
        "path": str(apk_path),
        "filename": apk_path.name,
        "size_bytes": apk_path.stat().st_size,
        "sha256": _sha256_bytes(apk_path.read_bytes()),
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


def apk_status() -> dict[str, Any]:
    path = mobile_dir() / "vortex.apk"
    if not path.is_file():
        return {"ok": False, "built": False, "message": "No APK has been built yet. Sync first."}
    return {
        "ok": True,
        "built": True,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_bytes(path.read_bytes()),
        "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime)),
        "license": "MIT",
    }
