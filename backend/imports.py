"""Import helper so the sidecar works as a script and as backend.*."""
from __future__ import annotations

import importlib
from typing import Any


def load(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError:
        return importlib.import_module("backend." + name)
