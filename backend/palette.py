"""Intelligent terminal command palette.

Slash commands are convenience shortcuts that expand to the existing reviewed
natural-language planning path or to read-only local workspace queries.  They
are the terminal copilot surface described by the feature specification, but
they are *not* a replacement for the Linux shell and they never bypass the
Guardian, the engagement gate, or the execution authority.  Every command that
produces a plan still comes from a reviewed adapter and still requires approval;
everything else here is a local, read-only lookup.
"""
from __future__ import annotations

from typing import Any


# Each palette entry maps a slash command to a kind:
#   "plan"    -> expand to a natural-language request and route through build_plan
#   "explain" -> expand to an "explain <args>" request (reviewed, non-executing)
#   "query"   -> read-only local workspace lookup (history/findings/evidence/...)
#
# Aliases are deliberately kept small; the spec asks for convenience commands,
# not a parallel shell.  Keep the set reviewed and finite.
PALETTE: dict[str, dict[str, Any]] = {
    "/help": {"kind": "plan", "request": "help"},
    "/health": {"kind": "plan", "request": "system health"},
    "/status": {"kind": "plan", "request": "system health"},
    "/processes": {"kind": "plan", "request": "show processes"},
    "/ports": {"kind": "plan", "request": "show listening ports"},
    "/network": {"kind": "plan", "request": "show ip address"},
    "/interfaces": {"kind": "plan", "request": "show network interfaces"},
    "/services": {"kind": "plan", "request": "show running services"},
    "/packages": {"kind": "plan", "request": "list installed packages"},
    "/disk": {"kind": "plan", "request": "show disk usage"},
    "/memory": {"kind": "plan", "request": "show memory"},
    "/cpu": {"kind": "plan", "request": "show cpu"},
    "/uptime": {"kind": "plan", "request": "show uptime"},
    "/os": {"kind": "plan", "request": "show os-release"},
    "/whoami": {"kind": "plan", "request": "whoami"},
    "/identity": {"kind": "plan", "request": "whoami"},
    "/git": {"kind": "plan", "request": "git status"},
    "/mounts": {"kind": "plan", "request": "show mounts"},
    "/usb": {"kind": "plan", "request": "show usb devices"},
    "/device": {"kind": "plan", "request": "show usb devices"},
    "/dns": {"kind": "plan", "request": "show dns servers"},
    "/containers": {"kind": "plan", "request": "inspect docker containers"},
    # Authorized-security and external-intelligence domains.  These route
    # through the reviewed planner so a missing binary, missing engagement, or
    # absent adapter is reported honestly as clarified/unavailable -- never a
    # fabricated scan or location.  A trailing arg supplies the target/host.
    "/scan": {"kind": "plan", "request": "scan"},
    "/osint": {"kind": "plan", "request": "osint"},
    "/gis": {"kind": "plan", "request": "gis"},
    "/satellite": {"kind": "plan", "request": "satellite"},
    "/analyze": {"kind": "plan", "request": "analyze"},
}

# Read-only /query-style commands.  Each maps to a workspace/store lookup; the
# optional argument (the text after the command) is the search term for /search.
QUERY_PALETTE: dict[str, str] = {
    "/history": "history",
    "/sessions": "sessions",
    "/session": "sessions",
    "/findings": "findings",
    "/evidence": "evidence",
    "/reports": "reports",
    "/report": "reports",
    "/tasks": "tasks",
    "/engagements": "engagements",
    "/search": "search",
    "/dashboard": "dashboard",
    "/ai": "model",
}


def _available_commands() -> list[str]:
    return sorted(list(PALETTE) + list(QUERY_PALETTE) + ["/explain <command>"])


def expand(request: str) -> dict[str, Any]:
    """Classify a slash command into a reviewed plan request or a read-only query.

    Returns ``{kind, command, args, ...}``.  Unknown commands return a ``help``
    meta object so the terminal can show the reviewed palette rather than a dead
    button or a fabricated plan.
    """
    request = (request or "").strip()
    if not request.startswith("/"):
        return {"kind": "error", "command": None, "args": request, "message": "A palette command starts with '/'. Send natural language to the planner instead."}

    body = request[1:].strip()
    tokens = body.split(maxsplit=1)
    command = ("/" + tokens[0]).lower() if tokens else ""
    args = tokens[1].strip() if len(tokens) > 1 else ""

    if command in PALETTE:
        base = str(PALETTE[command]["request"])
        if not args:
            return {"kind": "plan", "command": command, "args": args, "request": base}
        # A trailing argument narrows the reviewed adapter, e.g. "/ports 8080".
        # It remains a natural-language request and still routes through the
        # planner, so the argument is never executed verbatim as shell text.
        return {"kind": "plan", "command": command, "args": args, "request": f"{base} {args}"}

    if command == "/explain":
        if not args:
            return {"kind": "help", "command": command, "args": args, "message": "Provide a command to explain, e.g. '/explain ls -la'. Nothing is executed."}
        return {"kind": "plan", "command": command, "args": args, "request": f"explain {args}"}

    if command in QUERY_PALETTE:
        query = QUERY_PALETTE[command]
        if query == "search" and not args:
            return {"kind": "search_help", "command": command, "args": args, "message": "Provide a term to search across operations, conversations, findings, evidence, reports, sessions, and tasks, e.g. '/search 192.168.1.20'."}
        return {"kind": "query", "command": command, "args": args, "query": query, "term": args}

    return {
        "kind": "help",
        "command": command or "/",
        "args": args,
        "message": f"'{command or '/'}' is not a reviewed palette command.",
        "available": _available_commands(),
    }


def _run_query(store: Any, workspace: Any, query: str, term: str) -> tuple[str, Any]:
    """Execute a read-only palette query.  Returns (key, value) for the result."""
    if query == "history":
        return "history", store.list_history(100)
    if query == "sessions":
        return "sessions", store.list_sessions()
    if query == "findings":
        return "findings", workspace.list_findings()
    if query == "evidence":
        return "artifacts", store.list_artifacts()
    if query == "reports":
        return "reports", workspace.list_reports()
    if query == "tasks":
        return "tasks", workspace.list_tasks(100)
    if query == "engagements":
        return "engagements", [workspace.enrich_engagement(item) for item in store.list_engagements()]
    if query == "search":
        return "search", workspace.search_all(term)
    if query == "dashboard":
        try:
            from dashboard import collect as dashboard_collect
        except ImportError:
            from backend.dashboard import collect as dashboard_collect
        return "dashboard", dashboard_collect(store, workspace)
    if query == "model":
        try:
            from config import load_settings
            from models.router import model_status
        except ImportError:
            from backend.config import load_settings
            from backend.models.router import model_status
        return "model", model_status(load_settings())
    return query, []


def run_palette(
    store: Any,
    workspace: Any,
    request: str,
    *,
    cwd: str | None = None,
    engagement_id: str | None = None,
    offline: bool = False,
) -> dict[str, Any]:
    """Execute a palette command and return an inspectable result.

    Plan commands are built through ``build_plan`` so they keep exactly the same
    Guardian/engagement/approval semantics as a natural-language request; they
    are *not* executed here.  Query commands are read-only local lookups.
    """
    meta = expand(request)
    kind = meta.get("kind")

    if kind == "error":
        return {"palette": meta, "error": {"code": "invalid_palette", "message": meta.get("message")}}

    if kind == "plan":
        try:
            from vortex_backend import build_plan
        except ImportError:
            from backend.vortex_backend import build_plan
        plan = build_plan(store, meta["request"], cwd, engagement_id, offline=offline)
        return {"palette": meta, "plan": plan}

    if kind == "query":
        key, value = _run_query(store, workspace, meta["query"], meta.get("term") or "")
        return {"palette": meta, key: value}

    # help / unknown / search_help: show the reviewed palette, optionally with a
    # read-only help plan.
    if kind == "help":
        try:
            from vortex_backend import build_plan
        except ImportError:
            from backend.vortex_backend import build_plan
        plan = build_plan(store, "help", cwd, engagement_id, offline=offline)
        meta.setdefault("available", _available_commands())
        return {"palette": meta, "plan": plan}

    if kind == "search_help":
        meta.setdefault("available", _available_commands())
        return {"palette": meta}

    return {"palette": meta, "error": {"code": "invalid_palette", "message": "Unhandled palette command."}}
