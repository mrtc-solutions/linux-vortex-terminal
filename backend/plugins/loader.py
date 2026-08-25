"""Load JSON manifests from plugins/. Python from that tree is never imported."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent / "plugins"


def list_manifests() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not ROOT.is_dir():
        return items
    for path in sorted(ROOT.rglob("manifest.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not data.get("id") or not data.get("kind"):
            continue
        items.append({
            "id": str(data.get("id"))[:80],
            "kind": str(data.get("kind"))[:40],
            "name": str(data.get("name") or data.get("id"))[:120],
            "version": str(data.get("version") or "0")[:32],
            "source": str(path.relative_to(ROOT)),
            "executable": False,
            "status": "manifest-only",
            "message": "Manifest recorded. VORTEX will not import or execute plugin code from this directory.",
        })
    return items
