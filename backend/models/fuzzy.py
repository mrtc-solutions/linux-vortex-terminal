"""Fuzzy provider routing — primary local LLM with honest secondary fallback.

Decision chain (highest priority first):

1. local GGUF files (``Llama-3.2-3B`` fast, ``Qwen2.5-3B`` planner) — primary
2. Ollama loopback pool — secondary when GGUF is slow, missing, or failing
3. agent council — deterministic secondary when no model responds
4. deterministic VORTEX core — always available, never fabricated

The fuzzy engine blends four signals per provider into a 0..1 score:

* availability (up / degraded / down)
* latency EWMA (fast / ok / slow) — a delaying primary loses weight
* RAM fit (free / tight / critical) — protects the 8 GB host
* phase fit (how well the provider suits this advisory phase)

``record_latency`` feeds every real call back into the engine, so a primary
that starts delaying or failing automatically yields to the secondary on the
next decision. Nothing here generates text; it only ranks providers.
"""
from __future__ import annotations

import threading
import time
from typing import Any

_LOCK = threading.RLock()
# provider -> {"ewma_ms": float, "fails": int, "calls": int, "at": float}
_LATENCY: dict[str, dict[str, Any]] = {}
_LATENCY_TTL_SECONDS = 600.0
_EWMA_ALPHA = 0.35

PROVIDER_ORDER = ("gguf", "ollama", "council", "deterministic")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def latency_membership(ewma_ms: float | None) -> dict[str, float]:
    """Fast < 4s, ok 4–15s, slow > 15s (2 GHz CPU answers 3B models slowly)."""
    if ewma_ms is None:
        return {"fast": 0.5, "ok": 0.5, "slow": 0.0}
    ms = max(0.0, float(ewma_ms))
    if ms <= 4000:
        return {"fast": 1.0, "ok": 0.0, "slow": 0.0}
    if ms <= 8000:
        blend = (ms - 4000) / 4000
        return {"fast": 1.0 - blend, "ok": blend, "slow": 0.0}
    if ms <= 15000:
        blend = (ms - 8000) / 7000
        return {"fast": 0.0, "ok": 1.0 - blend, "slow": blend}
    return {"fast": 0.0, "ok": 0.0, "slow": 1.0}


def ram_membership() -> dict[str, float]:
    """Free > 3 GB, tight 1.5–3 GB, critical < 1.5 GB available."""
    available: int | None = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    available = int(line.split()[1]) // 1024
                    break
    except (OSError, ValueError):
        pass
    if available is None:
        return {"free": 0.5, "tight": 0.5, "critical": 0.0}
    if available >= 3072:
        return {"free": 1.0, "tight": 0.0, "critical": 0.0}
    if available >= 1536:
        blend = (available - 1536) / 1536
        return {"free": blend, "tight": 1.0 - blend, "critical": 0.0}
    return {"free": 0.0, "tight": 0.25, "critical": 0.75}


def availability_degree(state: str | None) -> float:
    return {"healthy": 1.0, "responded": 1.0, "ready": 1.0, "test-double": 1.0,
            "degraded": 0.55, "fallback": 0.4}.get(str(state or ""), 0.0)


def record_latency(provider: str, latency_ms: float | None, ok: bool) -> None:
    """Feed a real call outcome back into routing. Failures decay the score."""
    provider = str(provider or "").strip() or "unknown"
    now = time.monotonic()
    with _LOCK:
        entry = _LATENCY.get(provider) or {"ewma_ms": None, "fails": 0, "calls": 0, "at": now}
        entry["calls"] = int(entry.get("calls") or 0) + 1
        entry["at"] = now
        if ok and latency_ms is not None:
            try:
                sample = max(0.0, float(latency_ms))
            except (TypeError, ValueError):
                sample = None
            if sample is not None:
                previous = entry.get("ewma_ms")
                entry["ewma_ms"] = sample if previous is None else (
                    _EWMA_ALPHA * sample + (1.0 - _EWMA_ALPHA) * float(previous))
                entry["fails"] = max(0, int(entry.get("fails") or 0) - 1)
        else:
            entry["fails"] = int(entry.get("fails") or 0) + 1
            # A failing provider is treated as slow until it recovers.
            previous = entry.get("ewma_ms")
            entry["ewma_ms"] = 20000.0 if previous is None else max(float(previous), 12000.0)
        _LATENCY[provider] = entry


def latency_snapshot() -> dict[str, dict[str, Any]]:
    now = time.monotonic()
    with _LOCK:
        return {name: dict(entry) for name, entry in _LATENCY.items()
                if (now - float(entry.get("at") or 0.0)) < _LATENCY_TTL_SECONDS}


def reset_latency() -> None:
    with _LOCK:
        _LATENCY.clear()


def _phase_fit(provider: str, phase: str) -> float:
    provider, phase = str(provider), str(phase)
    table = {
        ("gguf", "conversation"): 1.0,
        ("gguf", "plan"): 1.0,
        ("gguf", "interpret"): 1.0,
        ("gguf", "report"): 0.9,
        ("gguf", "verify"): 0.9,
        ("ollama", "conversation"): 0.9,
        ("ollama", "plan"): 0.95,
        ("ollama", "interpret"): 0.95,
        ("ollama", "report"): 0.9,
        ("ollama", "verify"): 0.9,
        ("council", "conversation"): 0.3,
        ("council", "plan"): 0.35,
        ("council", "interpret"): 0.35,
        ("council", "report"): 0.3,
        ("council", "verify"): 0.3,
        ("deterministic", "conversation"): 0.2,
        ("deterministic", "plan"): 0.2,
        ("deterministic", "interpret"): 0.2,
        ("deterministic", "report"): 0.2,
        ("deterministic", "verify"): 0.2,
    }
    return table.get((provider, phase), 0.5)


def score_provider(provider: str, state: str | None, phase: str,
                   latency_ms: float | None = None) -> dict[str, Any]:
    """Fuzzy score in 0..1 with the fired-rule trace for inspectability."""
    avail = availability_degree(state)
    if latency_ms is None:
        latency_ms = (latency_snapshot().get(provider) or {}).get("ewma_ms")
    latency = latency_membership(latency_ms)
    ram = ram_membership()
    phase_fit = _phase_fit(provider, phase)
    # Defuzzified crisp inputs.
    latency_crisp = latency["fast"] * 1.0 + latency["ok"] * 0.55 + latency["slow"] * 0.1
    ram_crisp = ram["free"] * 1.0 + ram["tight"] * 0.6 + ram["critical"] * 0.25
    # Rule weights: availability dominates; a down provider can never win.
    if avail <= 0.0:
        score = 0.0
    else:
        score = _clamp01(0.45 * avail + 0.25 * latency_crisp + 0.15 * ram_crisp + 0.15 * phase_fit)
        if provider in {"council", "deterministic"}:
            # Secondary layers stay below any healthy model provider.
            score = min(score, 0.35 if provider == "council" else 0.15)
    trace = {
        "availability": round(avail, 3),
        "latency": {key: round(value, 3) for key, value in latency.items()},
        "ram": {key: round(value, 3) for key, value in ram.items()},
        "phase_fit": round(phase_fit, 3),
    }
    return {"provider": provider, "score": round(score, 3), "trace": trace,
            "latency_ms": latency_ms}


def decide(providers: list[dict[str, Any]], phase: str = "conversation") -> dict[str, Any]:
    """Rank providers fuzzy-first, deterministic order as tie-break.

    ``providers`` items: ``{"id": str, "state": str, "latency_ms": optional}``.
    Always returns a winner (deterministic core at minimum) plus the full
    ranking and a human-readable reason. Council/deterministic entries are
    appended automatically when the caller omits them.
    """
    phase = str(phase or "conversation")
    seen = {str(item.get("id")) for item in (providers or [])}
    items = list(providers or [])
    if "council" not in seen:
        items.append({"id": "council", "state": "ready"})
    if "deterministic" not in seen:
        items.append({"id": "deterministic", "state": "ready"})
    scored = [score_provider(str(item.get("id")), item.get("state"), phase, item.get("latency_ms"))
              for item in items]
    order = {name: index for index, name in enumerate(PROVIDER_ORDER)}
    scored.sort(key=lambda entry: (-entry["score"], order.get(entry["provider"], 99)))
    winner = scored[0]
    if winner["provider"] == "gguf":
        reason = "Primary local GGUF model is healthy and fits this host; it answers first."
    elif winner["provider"] == "ollama":
        reason = "Ollama loopback pool answers (GGUF primary unavailable, slow, or failing)."
    elif winner["provider"] == "council":
        reason = "No local model is answering; the deterministic agent council advises without generating text."
    else:
        reason = "No advisory layer is available; deterministic VORTEX core continues alone."
    confidence = "high" if winner["score"] >= 0.7 else (
        "moderate" if winner["score"] >= 0.4 else (
            "low" if winner["score"] > 0.0 else "unavailable"))
    return {
        "winner": winner["provider"],
        "confidence": confidence,
        "reason": reason,
        "phase": phase,
        "ranking": scored,
    }


def provider_confidence(decision: dict[str, Any], responded: bool) -> dict[str, Any]:
    """Qualitative confidence for the chosen provider (not a probability)."""
    decision = decision or {}
    if not responded:
        return {"confidence": "unavailable", "agreement": "none",
                "note": "The selected provider did not respond; secondary layers take over."}
    return {"confidence": decision.get("confidence", "moderate"),
            "agreement": "single-provider" if decision.get("winner") in {"gguf", "ollama"} else "deterministic",
            "provider": decision.get("winner"),
            "note": str(decision.get("reason") or "")}
