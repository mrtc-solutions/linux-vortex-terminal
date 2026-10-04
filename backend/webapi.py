"""Vortex Web/Vercel backend router (WEB_CLOUD runtime).

This module is the server side of Web Mode at
https://linux-vortex-terminal.vercel.app/. It is deliberately:

* stdlib-only (no pip dependencies — deployable as a Vercel Python function);
* stateless across invocations (serverless) — conversation memory lives in
  the visitor's own browser, so users can never see each other's history;
* cloud-capability-honest: it NEVER claims access to the visitor's Linux
  machine. Action requests are answered with an explicit
  "LOCAL MACHINE: NOT CONNECTED" result instead of fake execution;
* the security authority for Web Mode: FREE_ONLY_MODE, provider/model
  policy, request validation, size caps and rate limits are enforced HERE,
  never only in the UI. Provider/model identifiers supplied by the browser
  are resolved against the server-side registry (ProviderManager) — the
  browser cannot invent a model or bypass the free-only policy.

It reuses the exact same provider abstraction as the Local Linux runtime
(`backend/providers/*`), the same conversation classifier
(`backend/conversation.py`) and the same arbitration engine
(`backend/arbitration/*`) — one product, two runtimes.

There is intentionally NO generic shell/execute endpoint here, and no
route ever returns an environment variable or API key. Outbound payloads
pass through the shared secret redaction before leaving the server.
"""
from __future__ import annotations

import json
import os
import re
import secrets as _secrets
import threading
import time
from typing import Any

try:  # package-style and flat-path imports both work (sidecar vs Vercel)
    from backend import conversation as _conversation
    from backend import runtime_capabilities as _rt
    from backend.providers import keys as _keys
    from backend.providers.manager import manager as _manager
except ImportError:  # backend/ is on sys.path (Vercel function, tests)
    import conversation as _conversation  # type: ignore
    import runtime_capabilities as _rt  # type: ignore
    from providers import keys as _keys  # type: ignore
    from providers.manager import manager as _manager  # type: ignore

APP_VERSION = "0.3.0"

MAX_BODY_BYTES = 64 * 1024          # request bodies above this are rejected
MAX_REQUEST_CHARS = 8000            # one user turn
MAX_HISTORY_ITEMS = 24              # recent chat turns the browser may send
MAX_HISTORY_CHARS = 4000            # per history item
MAX_HISTORICAL_CANDIDATES = 4       # browser-supplied arbitration candidates
MAX_CANDIDATE_CHARS = 6000

# Routes the Local Linux sidecar serves but the web runtime genuinely
# cannot (they need the operator's machine: adapters, PTY, systemd, …).
_WEB_UNSUPPORTED_MESSAGE = (
    "Local Linux execution is unavailable in Web Mode. "
    "LOCAL MACHINE: NOT CONNECTED — this capability needs the Local Linux "
    "runtime (run `./vortex serve` / the Electron app on your machine) or a "
    "future authenticated Vortex Local Agent, which is not implemented yet."
)


# --------------------------------------------------------------------------
# Rate limiting — best-effort per serverless instance (documented limitation:
# a cold start resets buckets; this is a brake, not a billing system).
# --------------------------------------------------------------------------
_RATE_LOCK = threading.Lock()
_RATE_BUCKETS: dict[str, list[float]] = {}
_RATE_RULES = {
    "turn": (20, 60.0),      # 20 AI turns per minute per client
    "refresh": (6, 60.0),    # registry refreshes are expensive upstream
    "default": (60, 60.0),
}


def _rate_limited(client: str, rule: str) -> bool:
    limit, window = _RATE_RULES.get(rule, _RATE_RULES["default"])
    now = time.monotonic()
    key = f"{rule}:{client or 'unknown'}"
    with _RATE_LOCK:
        bucket = [t for t in _RATE_BUCKETS.get(key, []) if now - t < window]
        if len(bucket) >= limit:
            _RATE_BUCKETS[key] = bucket
            return True
        bucket.append(now)
        _RATE_BUCKETS[key] = bucket
        # Keep the map bounded.
        if len(_RATE_BUCKETS) > 2048:
            for stale in list(_RATE_BUCKETS.keys())[:1024]:
                _RATE_BUCKETS.pop(stale, None)
    return False


# --------------------------------------------------------------------------
# Settings for the WEB_CLOUD runtime. No user-mutable server state: the
# deployment's environment variables are the only configuration source
# (multi-user safety — one visitor can never change another's providers).
# --------------------------------------------------------------------------
def web_settings() -> dict[str, Any]:
    return {
        "runtime": _rt.RUNTIME_WEB,
        # Cloud providers are the whole point of Web Mode; privacy gating
        # still redacts secrets before anything leaves the server.
        "privacy_mode": "hybrid",
        "offline": False,
        "free_only_mode": True,  # env FREE_ONLY_MODE can only confirm/strengthen
        "conversation_provider": "auto",
        "conversation_model": "",
        "secondary_ai_mode": "on-demand",
    }


def _redact(text: str) -> str:
    try:
        return _keys.redact_secrets(str(text or ""))
    except Exception:
        return str(text or "")


def _error(status: int, code: str, message: str) -> tuple[int, dict[str, Any]]:
    return status, {"error": {"code": code, "message": _redact(message)}}


def _safe_settings_view(settings: dict[str, Any]) -> dict[str, Any]:
    policy = _policy_view(settings)
    return {
        "runtime": _rt.RUNTIME_WEB,
        "free_only_mode": policy.get("free_only", True),
        "privacy_mode": settings.get("privacy_mode"),
        "conversation_provider": settings.get("conversation_provider"),
        "secondary_ai_mode": settings.get("secondary_ai_mode"),
        "note": "Web Mode configuration is per-deployment (Vercel environment variables).",
    }


def _policy_view(settings: dict[str, Any]) -> dict[str, Any]:
    try:
        try:
            from backend.providers import policy as _policy
        except ImportError:
            from providers import policy as _policy  # type: ignore
        return _policy.cost_policy(settings)
    except Exception:
        return {"free_only": True, "allow_paid_providers": False, "allow_unknown_pricing": False}


# --------------------------------------------------------------------------
# Provider snapshots (web view): identical data model as local mode, with
# the local Ollama entry honestly marked unavailable in this runtime.
# --------------------------------------------------------------------------
def _web_local_entry() -> dict[str, Any]:
    return {
        "state": "unavailable_web",
        "provider": "ollama-local",
        "model": None,
        "message": (
            "Local Qwen is unavailable in Web Mode; using cloud AI. "
            "Run Vortex on your Linux machine for local qwen2.5:3b, or wait "
            "for the authenticated Vortex Local Agent (not yet implemented)."
        ),
        "local_agent": _rt.local_agent_status(),
    }


def _providers_snapshot() -> dict[str, Any]:
    settings = web_settings()
    snapshot = _manager().providers_snapshot(settings, probe_local=False)
    snapshot["runtime"] = _rt.RUNTIME_WEB
    snapshot["runtime_label"] = _rt.runtime_label(_rt.RUNTIME_WEB)
    snapshot["local"] = _web_local_entry()
    snapshot["local_agent"] = _rt.local_agent_status()
    for entry in snapshot.get("providers", []):
        if entry.get("id") == "ollama-local":
            entry["web_state"] = "unavailable_web"
            entry["web_detail"] = "Local Ollama cannot run inside the Vercel serverless backend."
    # key_slots is already a presence map (True/False) — never values.
    return snapshot


# --------------------------------------------------------------------------
# Conversation turn (the ONLY AI entry point in Web Mode).
# --------------------------------------------------------------------------
def _clean_history(raw: Any) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return history
    for item in raw[-MAX_HISTORY_ITEMS:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        content = str(item.get("content") or "").strip()
        if role not in {"user", "vortex", "assistant"} or not content:
            continue
        history.append({"role": role, "content": content[:MAX_HISTORY_CHARS]})
    return history


def _clean_historical_candidates(raw: Any) -> list[dict[str, Any]]:
    """Browser-supplied historical answers (from ITS OWN local store) that
    may compete with fresh cloud candidates in arbitration. They are data,
    never instructions, and never executed."""
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw[:MAX_HISTORICAL_CANDIDATES]:
        if not isinstance(item, dict):
            continue
        answer = str(item.get("answer") or "").strip()
        if not answer:
            continue
        out.append({
            "answer": answer[:MAX_CANDIDATE_CHARS],
            "relevance": max(0.0, min(1.0, float(item.get("relevance") or 0.5))),
            "provenance": {
                "provider": str(item.get("provider") or "browser-history")[:64],
                "model": str(item.get("model") or "previous-turn")[:64],
                "timestamp": str(item.get("timestamp") or "")[:32] or None,
                "verified": bool(item.get("verified") is True),
                "user_accepted": True if item.get("user_accepted") is True else None,
            },
        })
    return out


def _blocked_action_turn(request: str, routing: dict[str, Any],
                         conversation_id: str | None) -> dict[str, Any]:
    reply = (
        "⛔ Local Linux host is not connected in Web Mode.\n\n"
        f"Your request was classified as a system action ({routing.get('reason')}), "
        "and the Web/Vercel runtime has no shell, filesystem, process, service or "
        "network access to YOUR machine — and Vortex will not pretend otherwise.\n\n"
        "To run this for real:\n"
        "  • Local Linux runtime: clone the repo, `npm install && npm start` "
        "(or `./vortex serve`), and ask again — the planner, Guardian and typed "
        "adapters will handle it on your own machine.\n"
        "  • A secure authenticated Vortex Local Agent (web → agent → your Linux "
        "host) is designed but NOT implemented yet, so it is not offered here.\n\n"
        "I can still explain what the action would do, or answer any question, "
        "using cloud AI."
    )
    return {
        "mode": "web_action_blocked",
        "runtime": _rt.RUNTIME_WEB,
        "routing": routing,
        "reply": reply,
        "explanation": reply,
        "local_agent": _rt.local_agent_status(),
        "conversation": {"id": conversation_id, "storage": "browser-local"} if conversation_id else None,
        "ai": {"state": "not_invoked"},
        "task": None, "plan": None, "guardian": None, "operation": None,
        "auto_executed": False,
    }


def _arbitrate_web(request: str, history: list[dict[str, str]],
                   historical: list[dict[str, Any]],
                   settings: dict[str, Any]) -> dict[str, Any] | None:
    """Real historical-vs-cloud arbitration in Web Mode.

    Candidates: browser-supplied verified history + a fresh cloud answer.
    Arbitrator: best currently available eligible provider (never claims
    local Qwen did it — arbitration_mode records CLOUD)."""
    try:
        try:
            from backend.arbitration import (
                AnswerArbitrator, CandidateComparator, CandidateNormalizer,
                HistoricalCandidateScorer,
            )
        except ImportError:
            from arbitration import (  # type: ignore
                AnswerArbitrator, CandidateComparator, CandidateNormalizer,
                HistoricalCandidateScorer,
            )
        mgr = _manager()
        messages = _conversation.build_messages(request, history)
        new_result = mgr.generate(messages, settings, purpose="conversation")
        normalizer = CandidateNormalizer(scorer=HistoricalCandidateScorer())
        candidates = [normalizer.normalize_historical(request, h) for h in historical]
        if new_result.get("state") == "responded":
            candidates.append(normalizer.normalize_cloud(request, new_result))
        if not candidates:
            return None
        arbitrator = AnswerArbitrator(provider_manager=mgr,
                                      comparator=CandidateComparator())
        arb = arbitrator.arbitrate(request, candidates, settings=settings)
        winning = next((c for c in arb.candidates
                        if c.candidate_id == arb.selected_candidate_id),
                       arb.candidates[0] if arb.candidates else None)
        arb_dict = arb.to_dict()
        return {
            "state": "responded",
            "mode": arb.decision,
            "reply": arb.final_answer,
            "provider": (winning.provider if winning else "vortex-arbitrator")
                        if arb.decision != "synthesized" else "vortex-synthesis",
            "provider_name": (winning.provider_name if winning else "Vortex Arbitrator")
                             if arb.decision != "synthesized" else "Vortex Evidence Synthesis",
            "model": winning.model if winning else arb.arbitrator_model,
            "free": True,
            "latency_ms": arb.latency_ms,
            "historical_contribution": arb.historical_contribution,
            "arbitration": arb_dict,
            "attempts": new_result.get("attempts") or [],
        }
    except Exception:
        return None


def _turn(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = body.get("request")
    if not isinstance(request, str) or not request.strip():
        return _error(400, "bad_request", "request must be a non-empty string")
    if len(request) > MAX_REQUEST_CHARS:
        return _error(400, "bad_request", "request is too long")
    request = request.strip()
    conversation_id = str(body.get("conversation_id") or "")[:128] or None
    history = _clean_history(body.get("history"))
    historical = _clean_historical_candidates(body.get("historical_candidates"))
    settings = web_settings()

    routing = _conversation.classify(request)
    if routing.get("category") != "conversation":
        return 200, _blocked_action_turn(request, routing, conversation_id)

    result: dict[str, Any] | None = None
    if historical:
        result = _arbitrate_web(request, history, historical, settings)
    if result is None:
        result = _conversation.respond(request, settings, history=history)

    conversation_id = conversation_id or f"web-{_secrets.token_hex(8)}"
    if result.get("state") == "responded":
        reply = str(result.get("reply") or "").strip()
        ok = True
    else:
        attempts = result.get("attempts") or []
        details = "; ".join(
            f"{a.get('provider')}: {a.get('detail')}" for a in attempts[:6] if a.get("detail")
        )
        configured = [k for k, v in _keys.configured_slots().items() if v]
        if not configured:
            reply = ("No eligible free AI provider is currently available: this "
                     "deployment has no cloud AI keys configured. Set GEMINI_API_KEY_1/2, "
                     "GROQ_API_KEY and/or OPENROUTER_API_KEY in the Vercel project "
                     "environment (server-side only).")
        else:
            reply = str(result.get("message") or
                        "No eligible free AI provider is currently available.")
            if details:
                reply += " (" + details + ")"
        ok = False

    arbitration = result.get("arbitration")
    source = "cloud"
    if arbitration:
        decision = str(arbitration.get("decision") or "")
        source = {"historical": "historical", "synthesized": "synthesized"}.get(decision, "cloud")
    provenance = {
        "source": source,
        "provider": result.get("provider"),
        "provider_name": result.get("provider_name"),
        "model": result.get("model"),
        "mode": _rt.RUNTIME_WEB,
        "historical_contribution": result.get("historical_contribution") or "none",
        "arbitration_mode": (arbitration or {}).get("arbitration_mode") or ("CLOUD" if arbitration else None),
    }
    ai = {
        "state": "responded" if ok else "unavailable",
        "provider": result.get("provider"),
        "provider_name": result.get("provider_name"),
        "model": result.get("model"),
        "free": result.get("free"),
        "mode": "cloud",
        "latency_ms": result.get("latency_ms"),
        "attempts": result.get("attempts") or [],
        "message": None if ok else reply,
    }
    message = {
        "id": f"webmsg-{_secrets.token_hex(8)}",
        "role": "vortex",
        "content": reply,
        "meta": {"mode": "conversation", "ai": {k: ai[k] for k in
                 ("state", "provider", "provider_name", "model", "free", "latency_ms")},
                 "provenance": provenance},
    }
    payload = {
        "mode": "conversation",
        "runtime": _rt.RUNTIME_WEB,
        "routing": routing,
        "conversation": {"id": conversation_id, "title": request[:60],
                         "storage": "browser-local"},
        "message": message,
        "reply": reply,
        "explanation": reply,
        "ai": ai,
        "arbitration": arbitration,
        "historical_contribution": result.get("historical_contribution") or "none",
        "provenance": provenance,
        "task": None, "plan": None, "guardian": None, "council": None,
        "operation": None, "auto_executed": False,
    }
    return 200, json.loads(_redact(json.dumps(payload)))


# --------------------------------------------------------------------------
# Other cloud-safe typed functions.
# --------------------------------------------------------------------------
def _provider_check(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    provider_id = str(body.get("provider_id") or "")
    if not re.fullmatch(r"[a-z0-9-]{1,64}", provider_id or ""):
        return _error(400, "bad_request", "provider_id must be a known provider identifier")
    if provider_id == "ollama-local":
        return 200, {"health": {"provider": "ollama-local", "state": "unavailable_web",
                                "detail": _web_local_entry()["message"]}}
    try:
        health = _manager().health_check(provider_id, web_settings())
    except Exception as exc:
        return _error(404, "unknown_provider", str(exc))
    return 200, {"health": json.loads(_redact(json.dumps(health)))}


def _provider_refresh(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`Refresh Free Models`: live model discovery + pricing/free status
    re-verification against the provider APIs (dynamic registry — no
    hard-coded model catalogue)."""
    settings = web_settings()
    mgr = _manager()
    provider_id = str(body.get("provider_id") or "").strip()
    targets: list[str]
    if provider_id:
        if not re.fullmatch(r"[a-z0-9-]{1,64}", provider_id):
            return _error(400, "bad_request", "invalid provider_id")
        targets = [provider_id]
    else:
        # Only providers with configured keys (plus keyless ones) can be
        # refreshed for real; everything else would just error.
        snapshot = mgr.providers_snapshot(settings, probe_local=False)
        targets = [p["id"] for p in snapshot.get("providers", [])
                   if p.get("mode") == "cloud" and p.get("enabled")
                   and (p.get("key_configured") or not p.get("requires_api_key"))][:8]
    results: dict[str, Any] = {}
    for target in targets:
        if target == "ollama-local":
            results[target] = {"state": "unavailable_web"}
            continue
        try:
            models = mgr.discover_models(target, settings)
            results[target] = {"state": "refreshed", "models": len(models)}
        except Exception as exc:
            results[target] = {"state": "error", "detail": _redact(str(exc))[:200]}
    return 200, {"refresh": {"runtime": _rt.RUNTIME_WEB, "results": results}}


def _models_view() -> dict[str, Any]:
    """Web-shaped /api/models: local engines are honestly absent."""
    unavailable = {"state": "unavailable_web",
                   "reason": "Local inference engines cannot run in the Vercel serverless backend."}
    snapshot = _providers_snapshot()
    ready = [p["id"] for p in snapshot.get("providers", [])
             if p.get("mode") == "cloud" and p.get("enabled")
             and p.get("policy_allowed") and (p.get("key_configured") or not p.get("requires_api_key"))]
    return {
        "model": {
            "runtime": _rt.RUNTIME_WEB,
            "providers": {"llamafile": dict(unavailable), "gguf": dict(unavailable),
                          "ollama": dict(unavailable)},
            "fuzzy": {"winner": "cloud-provider-chain", "confidence": "n/a",
                      "detail": "Web Mode routes conversation to the cloud fallback chain."},
            "cloud": {"eligible_providers": ready,
                      "fallback_order": [p for p in snapshot.get("fallback_order", [])
                                         if p != "ollama-local"]},
            "local_agent": _rt.local_agent_status(),
        }
    }


def _system_health() -> dict[str, Any]:
    """Honest description of the SERVER the web runtime runs on. This is
    Vercel's sandbox — explicitly NOT the visitor's machine."""
    import platform
    return {
        "health": {
            "runtime": _rt.RUNTIME_WEB,
            "offline": False,
            "host": {
                "runtime": "vercel-serverless",
                "region": os.environ.get("VERCEL_REGION") or "unknown",
                "architecture": platform.machine(),
                "kernel": platform.release(),
                "cwd": "",
                "uid": {"name": "web"},
                "distribution": {"id": "vercel",
                                 "pretty_name": "Vercel serverless (WEB / CLOUD runtime)"},
                "note": "This describes the cloud backend sandbox, not your Linux machine.",
            },
            "components": {"core": {"state": "ok", "version": APP_VERSION}},
            "local_agent": _rt.local_agent_status(),
        }
    }


def _diagnostics() -> dict[str, Any]:
    """Developer diagnostics for the WEB_CLOUD runtime. Mirrors the sidecar's
    diagnostics shape ({text, snapshot}) so the same UI renders it, but the
    text is runtime-honest: no loopback Ollama probe happens on the server
    and no credential value can appear (redaction + presence-only slots)."""
    settings = web_settings()
    snapshot = _providers_snapshot()
    policy = _policy_view(settings)
    lines = [
        "VORTEX DIAGNOSTICS — ☁ WEB / CLOUD RUNTIME (Vercel backend)",
        "",
        f"Runtime: {_rt.RUNTIME_WEB}",
        "Local machine: NOT CONNECTED (Vortex Local Agent not implemented)",
        "Local Qwen: unavailable in Web Mode — the cloud chain is primary",
        f"Free-only: {'ON ($0 enforced server-side)' if policy.get('free_only', True) else 'OFF'}",
        "Arbitration mode: CLOUD (best eligible cloud provider arbitrates)",
        f"Fallback chain: {' → '.join(snapshot.get('fallback_order', [])[:8])}",
        "Catalogue: open-free-llm-api/awesome-freellm-apis (models re-verified live per provider)",
        "",
    ]
    for provider in snapshot.get("providers") or []:
        if provider.get("id") == "ollama-local":
            lines.append(str(provider.get("name")))
            lines.append("  Status: UNAVAILABLE IN WEB MODE (no local machine attached to the server)")
            lines.append("")
            continue
        stat = provider.get("stats") or {}
        health = provider.get("health") or {}
        state = (health.get("state") or stat.get("last_error_kind")
                 or ("disabled" if not provider.get("enabled") else None)
                 or ("no_api_key" if not provider.get("key_configured") else "unchecked"))
        lines.append(str(provider.get("name")))
        lines.append(f"  Status: {str(state).upper()}")
        lines.append(f"  Model: {provider.get('default_model') or 'dynamic (discovered)'}")
        if provider.get("key_slot"):
            lines.append(f"  Key: {provider['key_slot']} ({'configured' if provider.get('key_configured') else 'NOT configured'})")
        lines.append(f"  Pricing class: {provider.get('free_status')}")
        if not provider.get("policy_allowed"):
            lines.append(f"  Blocked: {provider.get('policy_reason')}")
        if stat.get("requests"):
            lines.append(f"  Requests: {stat['requests']} ({stat.get('ok', 0)} ok, {stat.get('failures', 0)} failed, {stat.get('http_429', 0)} rate-limited)")
        lines.append("")
    doc = {
        "text": "\n".join(lines),
        "runtime": _rt.RUNTIME_WEB,
        "runtime_label": _rt.runtime_label(_rt.RUNTIME_WEB),
        "free_only": policy.get("free_only", True),
        "local_qwen": _web_local_entry(),
        "local_agent": _rt.local_agent_status(),
        "arbitration_mode": "CLOUD",
        "snapshot": snapshot,
        "catalogue": {
            "source": "https://github.com/open-free-llm-api/awesome-freellm-apis",
            "note": "Reference free-model discovery catalogue; models are re-verified live per provider.",
        },
    }
    return {"diagnostics": json.loads(_redact(json.dumps(doc)))}


# --------------------------------------------------------------------------
# Router.
# --------------------------------------------------------------------------
def handle_request(method: str, path: str, body_bytes: bytes | None,
                   client_ip: str = "") -> tuple[int, dict[str, Any]]:
    method = (method or "GET").upper()
    path = (path or "/").split("?", 1)[0].rstrip("/") or "/"

    if body_bytes and len(body_bytes) > MAX_BODY_BYTES:
        return _error(413, "payload_too_large", "request body exceeds 64 KB")
    body: dict[str, Any] = {}
    if body_bytes:
        try:
            parsed = json.loads(body_bytes.decode("utf-8"))
            if isinstance(parsed, dict):
                body = parsed
        except (ValueError, UnicodeDecodeError):
            return _error(400, "bad_request", "body must be a JSON object")

    if _rate_limited(client_ip, "turn" if path == "/api/workspace/turn"
                     else "refresh" if path == "/api/providers/refresh" else "default"):
        return _error(429, "rate_limited",
                      "Too many requests from this client — slow down and retry shortly.")

    settings = web_settings()

    if method == "GET":
        if path == "/api/health":
            return 200, {
                "ok": True, "version": APP_VERSION, "backend": "online",
                **_rt.runtime_document(_rt.RUNTIME_WEB),
                "free_only": _policy_view(settings).get("free_only", True),
            }
        if path == "/api/system/health":
            return 200, _system_health()
        if path == "/api/capabilities":
            return 200, {
                "product": "Vortex Terminal",
                "version": APP_VERSION,
                **_rt.runtime_document(_rt.RUNTIME_WEB),
            }
        if path == "/api/providers":
            return 200, json.loads(_redact(json.dumps({"providers": _providers_snapshot()})))
        if path == "/api/providers/diagnostics":
            return 200, _diagnostics()
        if path == "/api/models":
            return 200, _models_view()
        if path == "/api/settings":
            return 200, {"settings": _safe_settings_view(settings)}
        if path == "/api/conversations":
            # Stateless by design: Web Mode history is browser-local only,
            # so the server honestly has nothing to list.
            return 200, {"conversations": [], "storage": "browser-local",
                         "note": "Web Mode keeps conversation history in your browser only."}

    if method == "POST":
        if path == "/api/workspace/turn":
            return _turn(body)
        if path == "/api/providers/check":
            return _provider_check(body)
        if path == "/api/providers/refresh":
            return _provider_refresh(body)
        if path in {"/api/providers/enable", "/api/providers/select",
                    "/api/providers/gemini", "/api/providers/warmup"}:
            return _error(403, "web_readonly",
                          "Provider configuration is per-deployment in Web Mode. "
                          "Set the provider API keys and FREE_ONLY_MODE in the Vercel "
                          "project environment variables (server-side only).")

    # Everything else is a Local-Linux-runtime capability.
    return _error(404, "web_unsupported", _WEB_UNSUPPORTED_MESSAGE)
