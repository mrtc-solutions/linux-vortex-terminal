"""RuntimeCapabilityManager — the single source of truth for WHICH runtime
Vortex is executing in and WHAT that runtime can genuinely do.

Two runtimes exist:

* ``LOCAL_LINUX`` — the Python sidecar / Electron app running on the
  operator's own Linux machine. Filesystem, processes, services, Git,
  networking, local shell (PTY) and loopback Ollama are genuinely
  available (subject to the host actually having them installed).

* ``WEB_CLOUD``  — the Vercel serverless backend behind
  https://linux-vortex-terminal.vercel.app/. It has NO access to the
  visitor's Linux machine: no shell, no systemd, no processes, no local
  Ollama. It can genuinely do cloud AI (Gemini / Groq / OpenRouter /
  other verified free providers), provider discovery and health checks,
  free-model registry refreshes, and conversation handling.

A browser is never pretended to have shell access. If a future
authenticated Vortex Local Agent is connected, capabilities are widened
explicitly — never silently. Today no such agent exists, so the web
runtime always reports ``local_agent.connected = False``.
"""
from __future__ import annotations

import os
from typing import Any

RUNTIME_LOCAL = "LOCAL_LINUX"
RUNTIME_WEB = "WEB_CLOUD"

_VALID = {RUNTIME_LOCAL, RUNTIME_WEB}


def detect_runtime() -> str:
    """Detect the current runtime honestly.

    Order: explicit ``VORTEX_RUNTIME`` override, then serverless platform
    markers (Vercel sets ``VERCEL=1``; the underlying AWS Lambda sets
    ``AWS_LAMBDA_FUNCTION_NAME``), else LOCAL_LINUX.
    """
    override = str(os.environ.get("VORTEX_RUNTIME") or "").strip().upper()
    if override in _VALID:
        return override
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return RUNTIME_WEB
    return RUNTIME_LOCAL


def runtime_label(runtime: str | None = None) -> str:
    runtime = runtime or detect_runtime()
    return "● LOCAL — Linux" if runtime == RUNTIME_LOCAL else "☁ WEB — Vercel"


def local_agent_status() -> dict[str, Any]:
    """The optional authenticated Vortex Local Agent.

    It is NOT implemented yet, so this always reports not-connected.
    Nothing in the web runtime may claim local Linux reach while this
    says ``connected: False``.
    """
    return {
        "connected": False,
        "implemented": False,
        "status": "LOCAL MACHINE: NOT CONNECTED",
        "detail": (
            "The Vortex Local Agent (secure browser → Vercel → authenticated "
            "agent → local Linux bridge) is a designed but not yet implemented "
            "component. Until it exists and is authenticated, Web Mode cannot "
            "and does not touch any local Linux machine."
        ),
    }


def capabilities_for(runtime: str | None = None) -> dict[str, Any]:
    """Typed capability map. Only capabilities that genuinely exist in the
    given runtime are True. The UI must never infer a capability from the
    mere presence of a button."""
    runtime = runtime or detect_runtime()
    if runtime == RUNTIME_LOCAL:
        return {
            "filesystem": True,
            "processes": True,
            "services": True,
            "git": True,
            "network": True,
            "ollama": True,
            "localShell": True,
            "cloudAI": True,
            "providerDiscovery": True,
            "memory": True,
            "guardian": True,
            "typedAdapters": True,
            "historicalArbitration": True,
            "engagements": True,
            "artifacts": True,
            "reports": True,
        }
    return {
        # The Vercel server can only see its own sandboxed, ephemeral FS.
        "filesystem": "server-scoped-ephemeral",
        "processes": False,
        "services": False,
        "systemd": False,
        "git": False,
        "network": False,
        "ollama": False,
        "localShell": False,
        "cloudAI": True,
        "providerDiscovery": True,
        "freeModelRegistry": True,
        "providerHealthChecks": True,
        # Durable server-side memory needs a database the deployment does
        # not provision; Web Mode conversation history lives in the
        # visitor's own browser (per-user isolated by construction).
        "memory": "browser-local",
        "guardian": True,        # policy checks still run server-side
        "typedAdapters": False,  # no local adapters to execute
        "historicalArbitration": "client-supplied-candidates",
        "engagements": False,
        "artifacts": False,
        "reports": False,
        "localAgent": False,
    }


def runtime_document(runtime: str | None = None) -> dict[str, Any]:
    runtime = runtime or detect_runtime()
    doc: dict[str, Any] = {
        "runtime": runtime,
        "runtime_label": runtime_label(runtime),
        "capabilities": capabilities_for(runtime),
    }
    if runtime == RUNTIME_WEB:
        doc["local_agent"] = local_agent_status()
        doc["notes"] = [
            "Web Mode operates entirely through the Vercel backend.",
            "The browser has no Linux shell access and never will.",
            "Local Qwen is unavailable in Web Mode; cloud AI is used instead.",
            "Local Linux execution requires the Local Linux runtime or a "
            "future authenticated Vortex Local Agent.",
        ]
    return doc
