"""Universal per-function AI assistance.

Every user-facing VORTEX function can request a short advisory hint through
:func:`assist`. The hint is explanatory only — it never authorizes, never
executes, and never invents evidence. When no model answers, the function
continues deterministically with ``available == False``.

Routing reuses the fuzzy provider chain (GGUF primary → Ollama secondary →
agent council → deterministic core), so a delaying or failing primary
automatically yields to the secondary layer.
"""
from __future__ import annotations

import time
from typing import Any

# function -> advisory phase used by the router
ASSISTED_FUNCTIONS: dict[str, str] = {
    "plan": "plan",
    "explain": "conversation",
    "palette": "conversation",
    "search": "conversation",
    "dashboard": "conversation",
    "assets": "interpret",
    "health": "conversation",
    "deps": "plan",
    "replan": "interpret",
    "report": "report",
    "memory": "conversation",
    "engagement": "conversation",
    "session": "conversation",
    "interpret": "interpret",
    "verify": "verify",
    "error": "interpret",
}

_HINT_LIMIT = 600


def _advise():
    try:
        from .router import advise
        return advise
    except ImportError:
        pass
    try:
        from models.router import advise  # type: ignore
        return advise
    except ImportError:
        from backend.models.router import advise  # type: ignore
        return advise


def assist(function: str, request: str = "", *,
           plan: dict[str, Any] | None = None,
           operation: dict[str, Any] | None = None,
           context: dict[str, Any] | None = None,
           settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a short AI hint for ``function``. Never raises, never blocks long.

    The result always carries ``available`` (bool) and ``hint`` (str, empty
    when unavailable). Callers attach it as ``ai_hint`` next to their
    deterministic payload and must keep working when it is unavailable.
    """
    function = str(function or "").strip().lower() or "interpret"
    phase = ASSISTED_FUNCTIONS.get(function, "conversation")
    started = time.monotonic()
    base = {"function": function, "phase": phase, "available": False, "hint": "",
            "provider": None, "confidence": "unavailable", "latency_ms": 0}
    settings = dict(settings or {})
    if settings.get("ai_enabled") is False:
        return {**base, "reason": "AI disabled in settings."}
    prompt = str(request or "").strip()[:1200]
    if context:
        try:
            import json as _json
            extra = _json.dumps(context, sort_keys=True, default=str)[:800]
            prompt = f"{prompt}\nContext: {extra}".strip()[:1500]
        except (TypeError, ValueError):
            pass
    if not prompt:
        prompt = f"Briefly explain the current {function} state for the operator."
    try:
        advise = _advise()
        # Per-function hints stay conversational and tightly bounded so a slow
        # 2 GHz host never stalls the UI behind advisory text.
        advise_settings = dict(settings)
        try:
            current_timeout = int(advise_settings.get("model_timeout_seconds", 12))
        except (TypeError, ValueError):
            current_timeout = 12
        advise_settings["model_timeout_seconds"] = max(2, min(current_timeout, 8))
        try:
            current_gguf_timeout = int(advise_settings.get("gguf_timeout_seconds", 20))
        except (TypeError, ValueError):
            current_gguf_timeout = 20
        advise_settings["gguf_timeout_seconds"] = max(2, min(current_gguf_timeout, 10))
        result = advise(prompt, plan=plan, operation=operation, phase=phase, settings=advise_settings)
    except Exception as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        return {**base, "latency_ms": elapsed,
                "reason": f"advisory unavailable: {str(exc)[:160]}"}
    elapsed = int((time.monotonic() - started) * 1000)
    if not isinstance(result, dict) or result.get("state") != "responded":
        reason = ""
        if isinstance(result, dict):
            reason = str(result.get("message") or ((result.get("synthesis") or {}).get("unknowns")) or "")
        return {**base, "latency_ms": elapsed,
                "provider": (result or {}).get("provider") if isinstance(result, dict) else None,
                "reason": (reason or "no advisory model responded")[:240]}
    synthesis = result.get("synthesis") or {}
    hint = str(synthesis.get("fact_summary") or result.get("message") or "").strip()
    meaning = str(synthesis.get("meaning") or "").strip()
    if meaning and len(hint) + len(meaning) + 2 <= _HINT_LIMIT:
        hint = f"{hint} {meaning}".strip()
    fuzzy = result.get("fuzzy") or {}
    route = result.get("route") or {}
    selected = route.get("selected") or []
    return {
        "function": function,
        "phase": phase,
        "available": True,
        "hint": hint[:_HINT_LIMIT],
        "provider": result.get("provider"),
        "model": (selected[0].get("model") if selected else None),
        "confidence": fuzzy.get("confidence", "moderate"),
        "latency_ms": elapsed,
    }


def coverage() -> dict[str, Any]:
    """Inspectable registry: every function VORTEX assists with AI."""
    return {"assisted_functions": sorted(ASSISTED_FUNCTIONS),
            "count": len(ASSISTED_FUNCTIONS),
            "contract": ("Advisory hints only. Deterministic planning, Guardian, "
                         "and execution remain authoritative; hints degrade to "
                         "unavailable without breaking any function.")}
