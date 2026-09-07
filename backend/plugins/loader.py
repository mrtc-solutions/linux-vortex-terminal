"""Load bounded JSON manifests from plugins/. Python is never imported."""
from __future__ import annotations

import itertools
import json
import os
from pathlib import Path
import stat
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent / "plugins"
_MAX_MANIFESTS = 256
_MAX_MANIFEST_BYTES = 64 * 1024


def _read_manifest(path: Path, root: Path) -> tuple[dict[str, Any], str] | None:
    try:
        if path.is_symlink():
            return None
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        observed = path.lstat()
        if not stat.S_ISREG(observed.st_mode) or not 0 < observed.st_size <= _MAX_MANIFEST_BYTES:
            return None
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            details = os.fstat(fd)
            if not stat.S_ISREG(details.st_mode) or details.st_dev != observed.st_dev or details.st_ino != observed.st_ino:
                return None
            chunks = bytearray()
            while len(chunks) <= _MAX_MANIFEST_BYTES:
                chunk = os.read(fd, min(65536, _MAX_MANIFEST_BYTES + 1 - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
        finally:
            os.close(fd)
        if len(chunks) > _MAX_MANIFEST_BYTES:
            return None
        data = json.loads(bytes(chunks).decode("utf-8"))
        source = str(resolved.relative_to(root))
    except (OSError, UnicodeError, ValueError):
        return None
    return (data, source) if isinstance(data, dict) else None


def list_manifests() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        root = ROOT.resolve(strict=True)
    except OSError:
        return items
    if not root.is_dir():
        return items
    # Stop traversal once the public result budget is full; do not materialize
    # an attacker-sized glob merely to sort it.
    paths = sorted(itertools.islice(root.rglob("manifest.json"), _MAX_MANIFESTS), key=lambda item: str(item))
    for path in paths:
        loaded = _read_manifest(path, root)
        if loaded is None:
            continue
        data, source = loaded
        if not data.get("id") or not data.get("kind"):
            continue
        items.append({
            "id": str(data.get("id"))[:80],
            "kind": str(data.get("kind"))[:40],
            "name": str(data.get("name") or data.get("id"))[:120],
            "version": str(data.get("version") or "0")[:32],
            "source": source,
            "executable": False,
            "status": "manifest-only",
            "message": "Manifest recorded. VORTEX will not import or execute plugin code from this directory.",
        })
    return items
