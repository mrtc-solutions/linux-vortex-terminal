"""Load JSON manifests from plugins/. Python from that tree is never imported."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent / "plugins"


def list_manifests() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        root = ROOT.resolve()
    except OSError:
        return items
    if not root.is_dir():
        return items
    for path in sorted(root.rglob("manifest.json")):
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
            if resolved.is_symlink() or not resolved.is_file():
                continue
            data = json.loads(resolved.read_text(encoding="utf-8"))
            source = str(resolved.relative_to(root))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not data.get("id") or not data.get("kind"):
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
