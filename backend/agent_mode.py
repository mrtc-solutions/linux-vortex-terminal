"""Goal-directed Agent Mode: think -> plan -> Guardian -> execute -> observe.

An agent run is a bounded, fully visible loop over the existing reviewed
orchestration (:func:`orchestrate.run_turn`). Each step:

1. THINK consults local models llamafile-first via ``models.router.advise``
   (phase ``plan``: one primary model, tight timeouts). The transcript shows
   which provider and model thought, and what it concluded.
2. PROPOSE grounds the model's next-step text through deterministic
   ``build_plan``. Model text never becomes shell; unplannable proposals are
   recorded and the run moves on or stops honestly.
3. GUARDIAN decides per step. Steps the Guardian marks ``auto`` execute
   immediately; anything else pauses the run as ``awaiting_approval`` until
   the operator approves that exact step (or stops the run).
4. OBSERVE waits for the real operation, records truncated output plus the
   deterministic objective verdict, and loops until the goal is achieved or
   a budget (steps, time, digest loop-guard) stops the run.

No local model means no run: the preflight refuses with concrete guidance
toward the Models view (llamafile model file, GGUF files, Ollama
install/pull/start) instead of fabricating thought.
"""
from __future__ import annotations

import re
import secrets
import sys as _sys
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

# The sidecar imports this module top-level (``agent_mode``) while tests and
# package imports use ``backend.agent_mode``. Without an alias those are two
# module objects with two worker registries, so whichever loads first wins
# and both names resolve to it.
for _alias in ("agent_mode", "backend.agent_mode"):
    _sys.modules.setdefault(_alias, _sys.modules[__name__])

RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
TERMINAL_RUN_STATUSES = ("finished",)
WAITING_RUN_STATUSES = ("awaiting_approval",)
TERMINAL_OP_STATUSES = (
    "succeeded", "failed", "cancelled", "timed_out", "unavailable",
    "interrupted", "unknown_after_crash",
)
DEFAULT_MAX_STEPS = 5
MAX_STEPS_LIMIT = 10
RUN_BUDGET_SECONDS = 600
OP_WAIT_SECONDS = 600
OP_POLL_SECONDS = 0.25
THINK_TEXT_LIMIT = 800
OUTPUT_TAIL_LIMIT = 1500
TRANSCRIPT_CONTEXT_LIMIT = 1500

_DEPS: SimpleNamespace | None = None
_DEPS_LOCK = threading.Lock()
_REGISTRY: dict[str, dict[str, Any]] = {}
_REGISTRY_LOCK = threading.Lock()


def _deps() -> SimpleNamespace:
    """Resolve orchestration dependencies once (sidecar and test layouts).

    Tests replace ``backend.agent_mode._DEPS`` with stubs; production code
    must always go through this accessor so both import layouts work.
    """
    global _DEPS
    if _DEPS is None:
        with _DEPS_LOCK:
            if _DEPS is None:
                try:
                    from models.router import advise, model_status
                    from orchestrate import run_turn
                    from replan import evaluate_objective
                    from config import load_settings
                except ImportError:
                    from backend.models.router import advise, model_status
                    from backend.orchestrate import run_turn
                    from backend.replan import evaluate_objective
                    from backend.config import load_settings
                _DEPS = SimpleNamespace(
                    advise=advise, model_status=model_status, run_turn=run_turn,
                    evaluate_objective=evaluate_objective, load_settings=load_settings,
                )
    return _DEPS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_fingerprint(plan: dict[str, Any]) -> str:
    """Repeat-detection key over the executable content of a plan.

    ``plan_digest`` covers ``expires_at``, so two identical requests never
    share it. The loop guard needs the opposite: same commands + context =
    same key, so a re-proposed step is recognized and the run stops.
    """
    import hashlib
    import json

    specs = [
        {"adapter": spec.get("adapter_id"), "executable": spec.get("executable"),
         "argv": spec.get("argv"), "privilege": spec.get("privilege")}
        for spec in plan.get("commands") or []
    ]
    payload = {"kind": plan.get("kind"), "cwd": plan.get("cwd"),
               "engagement": plan.get("engagement_id"), "commands": specs}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _clip(value: Any, limit: int = THINK_TEXT_LIMIT) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def ensure_schema(store: Any) -> None:
    with store.lock, store.connect() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS agent_mode_runs (
                id TEXT PRIMARY KEY, goal TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                config_json TEXT NOT NULL, summary_json TEXT NOT NULL
            )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS agent_mode_events (
                run_id TEXT NOT NULL, seq INTEGER NOT NULL, at TEXT NOT NULL,
                kind TEXT NOT NULL, payload_json TEXT NOT NULL,
                PRIMARY KEY (run_id, seq),
                FOREIGN KEY(run_id) REFERENCES agent_mode_runs(id)
            )"""
        )


def _decode_run(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    import json

    return {
        "id": row["id"],
        "goal": row["goal"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "config": json.loads(row["config_json"] or "{}"),
        "summary": json.loads(row["summary_json"] or "{}"),
    }


def get_run(store: Any, run_id: str) -> dict[str, Any] | None:
    if not RUN_ID_RE.match(run_id or ""):
        return None
    ensure_schema(store)
    with store.connect() as db:
        row = db.execute(
            "SELECT id, goal, status, created_at, updated_at, config_json, summary_json"
            " FROM agent_mode_runs WHERE id=?", (run_id,)).fetchone()
    return _decode_run(row)


def list_runs(store: Any, limit: int = 20) -> list[dict[str, Any]]:
    ensure_schema(store)
    reconcile(store)
    with store.connect() as db:
        rows = db.execute(
            "SELECT id, goal, status, created_at, updated_at, config_json, summary_json"
            " FROM agent_mode_runs ORDER BY updated_at DESC LIMIT ?", (max(1, min(int(limit), 100)),)).fetchall()
    return [item for item in (_decode_run(row) for row in rows) if item]


def _save_run(store: Any, run: dict[str, Any]) -> None:
    import json

    run["updated_at"] = _now_iso()
    with store.lock, store.connect() as db:
        db.execute(
            "UPDATE agent_mode_runs SET status=?, updated_at=?, config_json=?, summary_json=? WHERE id=?",
            (run["status"], run["updated_at"], json.dumps(run["config"]),
             json.dumps(run["summary"]), run["id"]),
        )


def record_event(store: Any, run_id: str, kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    import json

    payload = payload or {}
    with store.lock, store.connect() as db:
        row = db.execute("SELECT COALESCE(MAX(seq), 0) FROM agent_mode_events WHERE run_id=?", (run_id,)).fetchone()
        seq = int(row[0] or 0) + 1
        event = {"run_id": run_id, "seq": seq, "at": _now_iso(), "kind": kind, "payload": payload}
        db.execute(
            "INSERT INTO agent_mode_events(run_id, seq, at, kind, payload_json) VALUES (?,?,?,?,?)",
            (run_id, seq, event["at"], kind, json.dumps(payload)),
        )
        db.execute("UPDATE agent_mode_runs SET updated_at=? WHERE id=?", (event["at"], run_id))
    return event


def events_since(store: Any, run_id: str, since: Any = 0) -> dict[str, Any]:
    import json

    try:
        since_seq = max(0, int(since))
    except (TypeError, ValueError):
        since_seq = 0
    run = get_run(store, run_id)
    if not run:
        return {"run": None, "events": []}
    with store.connect() as db:
        rows = db.execute(
            "SELECT seq, at, kind, payload_json FROM agent_mode_events"
            " WHERE run_id=? AND seq>? ORDER BY seq ASC LIMIT 500", (run_id, since_seq)).fetchall()
    events = [
        {"run_id": run_id, "seq": row["seq"], "at": row["at"], "kind": row["kind"],
         "payload": json.loads(row["payload_json"] or "{}")}
        for row in rows
    ]
    return {"run": run, "events": events}


def _live_entry(run_id: str) -> dict[str, Any] | None:
    with _REGISTRY_LOCK:
        entry = _REGISTRY.get(run_id)
        if not entry:
            return None
        thread = entry.get("thread")
        if thread is not None and not thread.is_alive():
            _REGISTRY.pop(run_id, None)
            return None
        return entry


def reconcile(store: Any) -> list[str]:
    """Mark runs whose worker died (e.g. sidecar restart) as interrupted."""
    ensure_schema(store)
    changed: list[str] = []
    with store.connect() as db:
        rows = db.execute("SELECT id FROM agent_mode_runs WHERE status=?", ("running",)).fetchall()
    for row in rows:
        if _live_entry(row["id"]) is None:
            run = get_run(store, row["id"])
            if run and run["status"] == "running":
                run["status"] = "finished"
                run["summary"] = {**(run.get("summary") or {}), "outcome": "interrupted",
                                  "reason": "The sidecar restarted while this run was active. Start a new run to continue."}
                _save_run(store, run)
                record_event(store, run["id"], "finished", {"outcome": "interrupted"})
                changed.append(run["id"])
    return changed


def model_preflight(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Check that a local model can think, with download guidance if not."""
    settings = settings or {}
    try:
        status = _deps().model_status(settings)
    except Exception as exc:
        status = {"enabled": False, "error": str(exc)[:200]}
    enabled = status.get("enabled") is True
    local = status.get("local") or {}
    gguf = status.get("gguf") or {}
    llamafile = status.get("llamafile") or {}
    providers = {
        "llamafile": {"state": llamafile.get("state") or "unavailable",
                      "reason": llamafile.get("reason") or ""},
        "gguf": {"state": gguf.get("state") or "unavailable",
                 "reason": gguf.get("reason") or gguf.get("message") or ""},
        "ollama": {"state": local.get("state") or "unavailable",
                   "reason": local.get("reason") or ""},
    }
    healthy = [name for name, info in providers.items() if info["state"] == "healthy"]
    if enabled and healthy:
        return {"ok": True, "enabled": True, "providers": providers, "healthy": healthy,
                "message": f"Local thinking is available via {', '.join(healthy)} (llamafile answers first when healthy)."}
    guidance = []
    if not enabled:
        guidance.append({"provider": "settings", "action": "Turn on Local AI in Settings, then open the Models view.",
                         "detail": "Agent Mode thinks with on-device models only; it stays off while Local AI is disabled."})
    guidance.append({"provider": "llamafile", "action": "Open the Models view and register a GGUF model file for llamafile.",
                     "detail": f"llamafile state: {providers['llamafile']['state']}. {providers['llamafile']['reason']}".strip()})
    guidance.append({"provider": "gguf", "action": "Open the Models view and download GGUF model files into the models directory.",
                     "detail": f"GGUF state: {providers['gguf']['state']}. {providers['gguf']['reason']}".strip()})
    guidance.append({"provider": "ollama", "action": "Open the Models view to install Ollama, pull a catalog model, and start the service.",
                     "detail": f"Ollama state: {providers['ollama']['state']}. {providers['ollama']['reason']}".strip()})
    return {"ok": False, "enabled": enabled, "providers": providers, "healthy": [],
            "open_view": "models",
            "message": "Agent Mode needs a local model to think with, and none is healthy. Download or start one in the Models view, then start the run again.",
            "guidance": guidance}


def _transcript_context(store: Any, run_id: str) -> str:
    data = events_since(store, run_id, 0)
    lines: list[str] = []
    for event in data.get("events") or []:
        kind, payload = event.get("kind"), event.get("payload") or {}
        if kind == "step_finished":
            lines.append(f"step {payload.get('step')}: {payload.get('status')} — {_clip(payload.get('commands_text'), 160)}")
        elif kind == "verdict":
            lines.append(f"verdict: achieved={payload.get('achieved')} replanned={payload.get('replan')} — {_clip(payload.get('reason'), 160)}")
        elif kind == "think":
            for item in (payload.get("next_steps") or [])[:2]:
                lines.append(f"thought: {_clip(item, 160)}")
    return "\n".join(lines[-12:])[-TRANSCRIPT_CONTEXT_LIMIT:]


def _think(store: Any, run: dict[str, Any], goal: str, settings: dict[str, Any],
           last_plan: dict[str, Any] | None, last_op: dict[str, Any] | None) -> dict[str, Any]:
    context = _transcript_context(store, run["id"])
    request = f"Goal: {goal}\nProgress so far:\n{context or '(no steps yet)'}\nPropose the single next shell-groundable investigation step, or state the goal is met with evidence."
    started = time.monotonic()
    try:
        result = _deps().advise(request, plan=last_plan, operation=last_op, phase="plan", settings=settings)
    except Exception as exc:
        return {"state": "error", "error": str(exc)[:200], "latency_ms": int((time.monotonic() - started) * 1000)}
    synthesis = result.get("synthesis") or {}
    route = result.get("route") or {}
    return {
        "state": result.get("state") or "unavailable",
        "provider": result.get("provider") or "unknown",
        "model": route.get("primary") or route.get("requested_primary"),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "fact_summary": _clip(synthesis.get("fact_summary")),
        "unknowns": _clip(synthesis.get("unknowns")),
        "caution": _clip(synthesis.get("caution")),
        "next_steps": [_clip(item, 500) for item in synthesis.get("next_steps") or []][:3],
        "done_claimed": bool(synthesis.get("status_alignment") == "observed-success" and not (synthesis.get("next_steps") or [])),
        "message": _clip(result.get("message"), 300),
    }


def _op_summary(operation: dict[str, Any]) -> dict[str, Any]:
    commands = []
    displays: list[str] = []
    for item in (operation.get("commands") or [])[:8]:
        displays.append(str(item.get("display") or item.get("executable") or "?"))
        commands.append({
            "display": str(item.get("display") or "")[:200],
            "status": item.get("status"),
            "exit_code": item.get("exit_code"),
            "stdout_tail": _clip(item.get("stdout") or "", OUTPUT_TAIL_LIMIT),
            "stderr_tail": _clip(item.get("stderr") or "", OUTPUT_TAIL_LIMIT),
        })
    return {"status": operation.get("status"), "commands_text": "; ".join(displays)[:400], "commands": commands,
            "output_digest": operation.get("output_digest")}


def _wait_operation(store: Any, operation_id: str, stop: threading.Event) -> dict[str, Any] | None:
    deadline = time.monotonic() + OP_WAIT_SECONDS
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline and not stop.is_set():
        last = store.get_operation(operation_id)
        if not last or last.get("status") in TERMINAL_OP_STATUSES or last.get("status") == "awaiting_confirmation":
            return last
        time.sleep(OP_POLL_SECONDS)
    return last


def _finish(store: Any, run: dict[str, Any], outcome: str, reason: str) -> dict[str, Any]:
    run = get_run(store, run["id"]) or run
    run["status"] = "finished"
    summary = run.get("summary") or {}
    summary.update({"outcome": outcome, "reason": reason, "steps": (run.get("config") or {}).get("step_index", 0)})
    run["summary"] = summary
    _save_run(store, run)
    record_event(store, run["id"], "finished", {"outcome": outcome, "reason": _clip(reason, 500)})
    try:
        store.append_audit("agent_run_finished", {"run_id": run["id"], "outcome": outcome})
    except Exception:
        pass
    with _REGISTRY_LOCK:
        _REGISTRY.pop(run["id"], None)
    return run


def _park_until_resume(store: Any, run_id: str, stop: threading.Event, resume: threading.Event) -> str:
    """Park the worker on a paused run until resume, stop, or external finish."""
    resume.clear()
    while True:
        if stop.wait(timeout=1.0):
            return "stop"
        if resume.is_set():
            resume.clear()
            return "resume"
        try:
            run = get_run(store, run_id)
        except Exception:
            run = None
        if not run or run["status"] == "finished":
            return "stop"


def _drive(store: Any, workspace: Any, executor: Any, run_id: str) -> None:
    deps = _deps()
    entry = _live_entry(run_id)
    stop = entry["stop"] if entry else threading.Event()
    resume = entry["resume"] if entry else threading.Event()
    run = get_run(store, run_id)
    if not run:
        return
    config = run.get("config") or {}
    goal = run.get("goal") or ""
    settings = config.get("settings") or {}
    deadline = time.monotonic() + RUN_BUDGET_SECONDS
    last_plan: dict[str, Any] | None = None
    last_op: dict[str, Any] | None = None
    try:
        while True:
            if stop.is_set() or time.monotonic() > deadline:
                _finish(store, run, "stopped" if stop.is_set() else "exhausted",
                        "Stopped by the operator." if stop.is_set() else f"Run budget of {RUN_BUDGET_SECONDS}s elapsed. Start a new run to continue.")
                return
            run = get_run(store, run_id) or run
            if run["status"] == "finished":
                return
            config = run.get("config") or {}
            step_index = int(config.get("step_index") or 0)
            max_steps = int(config.get("max_steps") or DEFAULT_MAX_STEPS)

            # Resume path: a preflight-paused operation the operator reviewed in
            # the Tasks view keeps being observed by this run.
            pending_op_id = config.get("pending_operation_id")
            pending_plan_id = config.get("pending_plan_id")
            if pending_op_id and run["status"] == "running" and not pending_plan_id:
                operation = store.get_operation(pending_op_id)
                if operation is None:
                    _finish(store, run, "error", "The waiting operation disappeared; the run stops.")
                    return
                if operation.get("status") == "awaiting_confirmation":
                    run["status"] = "awaiting_approval"
                    _save_run(store, run)
                    record_event(store, run_id, "paused", {"reason": "The mutation preflight is still waiting in the Tasks view.", "operation_id": pending_op_id})
                    if _park_until_resume(store, run_id, stop, resume) == "stop":
                        _finish(store, run, "stopped", "Stopped by the operator.")
                        return
                    continue
                plan = store.get_plan(operation.get("plan_id") or "") if operation.get("plan_id") else None
                record_event(store, run_id, "resumed", {"operation_id": pending_op_id})
                last_plan, last_op = plan, _wait_operation(store, pending_op_id, stop)
                config["pending_operation_id"] = None
                if last_op is None or stop.is_set():
                    _finish(store, run, "stopped", "Stopped by the operator.")
                    return
                if last_op.get("status") == "awaiting_confirmation":
                    config["pending_operation_id"] = last_op["id"]
                    run["status"] = "awaiting_approval"
                    run["config"] = config
                    _save_run(store, run)
                    record_event(store, run_id, "paused", {"reason": "A mutation preflight needs operator review in the Tasks view before this run can continue.", "operation_id": last_op["id"]})
                    if _park_until_resume(store, run_id, stop, resume) == "stop":
                        _finish(store, run, "stopped", "Stopped by the operator.")
                        return
                    continue
                _record_step_outcome(store, deps, run, config, step_index, last_plan, last_op, settings)
                advanced = _step_advance(store, run, config, step_index, last_plan, last_op, deps, settings, goal)
                if advanced == "halt":
                    return
                last_plan, last_op = advanced
                continue

            # Resume path: an approved pending plan executes now.
            if pending_plan_id and run["status"] == "running":
                plan = store.get_plan(pending_plan_id)
                if not plan or plan.get("status") != "planned":
                    record_event(store, run_id, "error", {"message": "The approved step is no longer executable; the run stops."})
                    _finish(store, run, "error", "Approved step expired before execution.")
                    return
                record_event(store, run_id, "resumed", {"plan_id": plan["id"]})
                operation = executor.start(plan, True, plan["approval_token"], False,
                                           settings.get("offline") is True, settings=settings)
                config["pending_plan_id"] = None
                config["pending_operation_id"] = operation["id"]
                run["config"] = config
                _save_run(store, run)
                record_event(store, run_id, "step_started", {"step": step_index + 1, "operation_id": operation["id"], "approved": True})
                last_plan, last_op = plan, _wait_operation(store, operation["id"], stop)
                config["pending_operation_id"] = None
                if last_op is None or stop.is_set():
                    _finish(store, run, "stopped", "Stopped by the operator.")
                    return
                if last_op.get("status") == "awaiting_confirmation":
                    config["pending_operation_id"] = last_op["id"]
                    run["status"] = "awaiting_approval"
                    run["config"] = config
                    _save_run(store, run)
                    record_event(store, run_id, "paused", {"reason": "A mutation preflight needs operator review in the Tasks view before this run can continue.", "operation_id": last_op["id"]})
                    if _park_until_resume(store, run_id, stop, resume) == "stop":
                        _finish(store, run, "stopped", "Stopped by the operator.")
                        return
                    continue
                _record_step_outcome(store, deps, run, config, step_index, last_plan, last_op, settings)
                advanced = _step_advance(store, run, config, step_index, last_plan, last_op, deps, settings, goal)
                if advanced == "halt":
                    return
                last_plan, last_op = advanced
                continue

            if step_index >= max_steps:
                _finish(store, run, "exhausted", f"Step budget of {max_steps} reached without a verified goal. Review the transcript and start a narrower run.")
                return

            thought = _think(store, run, goal, settings, last_plan, last_op)
            record_event(store, run_id, "think", {"step": step_index + 1, **thought})
            if thought["state"] != "responded":
                if step_index == 0:
                    record_event(store, run_id, "note", {"message": "Local thinking is unavailable; the run still grounds the goal itself deterministically for one evidence step."})
                else:
                    _finish(store, run, "unresolved", f"Local advisory became unavailable mid-run ({thought.get('state')}). Partial evidence stays in the transcript.")
                    return
            if thought.get("done_claimed") and last_op is not None:
                verdict = deps.evaluate_objective(last_plan or {}, last_op, settings)
                if verdict.get("achieved"):
                    _finish(store, run, "achieved", verdict.get("reason") or "Objective verified against observed output.")
                    return
                record_event(store, run_id, "note", {"message": "The model claims the goal is met, but observed evidence does not verify it. Gathering one more evidence step."})

            if step_index == 0:
                request_text = goal
            else:
                candidates = [item for item in thought.get("next_steps") or [] if item]
                if not candidates:
                    _finish(store, run, "unresolved", "The model proposed no next step. Partial evidence stays in the transcript.")
                    return
                request_text = candidates[0]

            try:
                turn = deps.run_turn(store, workspace, executor, request_text, cwd=config.get("cwd"),
                                     engagement_id=config.get("engagement_id"),
                                     conversation_id=config.get("conversation_id"), settings=settings)
            except Exception as exc:
                record_event(store, run_id, "error", {"message": _clip(exc, 300)})
                _finish(store, run, "error", f"A step failed to plan: {str(exc)[:200]}")
                return
            plan = turn.get("plan") or {}
            guardian = turn.get("guardian") or {}
            task = turn.get("task") or {}
            seen = config.get("seen_digests") or []
            fingerprint = _stable_fingerprint(plan)
            if fingerprint in seen:
                _finish(store, run, "loop_guard", "The next step repeats a plan this run already executed. Vortex Terminal stops instead of looping.")
                return
            config["seen_digests"] = (seen + [fingerprint])[-32:]
            if not config.get("conversation_id") and (turn.get("conversation") or {}).get("id"):
                config["conversation_id"] = turn["conversation"]["id"]
            run["config"] = config
            _save_run(store, run)
            record_event(store, run_id, "step_planned", {
                "step": step_index + 1, "task_id": task.get("id"), "plan_id": plan.get("id"),
                "request": _clip(request_text, 300), "kind": plan.get("kind"), "risk": plan.get("risk"),
                "status": plan.get("status"),
                "commands": [str(spec.get("display") or "")[:200] for spec in (plan.get("commands") or [])[:8]],
                "notes": [_clip(note, 300) for note in (plan.get("notes") or [])[:4]],
                "approval_phrase": plan.get("approval_phrase"),
            })
            record_event(store, run_id, "guardian", {
                "step": step_index + 1, "decision": guardian.get("decision"), "risk": guardian.get("risk"),
                "reasons": [str(item)[:200] for item in (guardian.get("reasons") or [])[:4]],
            })
            operation = turn.get("operation")
            if not turn.get("auto_executed") or not operation:
                config["pending_plan_id"] = plan.get("id")
                run["status"] = "awaiting_approval"
                run["config"] = config
                _save_run(store, run)
                record_event(store, run_id, "paused", {
                    "step": step_index + 1, "plan_id": plan.get("id"),
                    "reason": "Guardian requires explicit approval for this exact step. Approve it in Agent Mode, or stop the run."})
                try:
                    store.append_audit("agent_run_paused", {"run_id": run_id, "plan_id": plan.get("id")})
                except Exception:
                    pass
                if _park_until_resume(store, run_id, stop, resume) == "stop":
                    _finish(store, run, "stopped", "Stopped by the operator.")
                    return
                continue
            record_event(store, run_id, "step_started", {"step": step_index + 1, "operation_id": operation["id"], "plan_id": plan.get("id")})
            config["pending_operation_id"] = operation["id"]
            run["config"] = config
            _save_run(store, run)
            last_plan, last_op = plan, _wait_operation(store, operation["id"], stop)
            config["pending_operation_id"] = None
            if last_op is None or stop.is_set():
                if last_op is not None:
                    try:
                        executor.cancel(operation["id"])
                    except Exception:
                        pass
                _finish(store, run, "stopped", "Stopped by the operator.")
                return
            if last_op.get("status") == "awaiting_confirmation":
                config["pending_operation_id"] = last_op["id"]
                run["status"] = "awaiting_approval"
                run["config"] = config
                _save_run(store, run)
                record_event(store, run_id, "paused", {"reason": "A mutation preflight needs operator review in the Tasks view before this run can continue.", "operation_id": last_op["id"]})
                if _park_until_resume(store, run_id, stop, resume) == "stop":
                    _finish(store, run, "stopped", "Stopped by the operator.")
                    return
                continue
            _record_step_outcome(store, deps, run, config, step_index, last_plan, last_op, settings)
            advanced = _step_advance(store, run, config, step_index, last_plan, last_op, deps, settings, goal)
            if advanced == "halt":
                return
            last_plan, last_op = advanced
    except Exception as exc:
        try:
            record_event(store, run_id, "error", {"message": _clip(exc, 300)})
        except Exception:
            pass
        try:
            _finish(store, run, "error", f"The run worker failed: {str(exc)[:200]}")
        except Exception:
            pass


def _record_step_outcome(store: Any, deps: SimpleNamespace, run: dict[str, Any], config: dict[str, Any],
                         step_index: int, plan: dict[str, Any] | None, operation: dict[str, Any] | None,
                         settings: dict[str, Any]) -> dict[str, Any]:
    summary = _op_summary(operation or {})
    record_event(store, run["id"], "step_finished", {"step": step_index + 1, **summary})
    try:
        verdict = deps.evaluate_objective(plan or {}, operation, settings)
    except Exception as exc:
        verdict = {"achieved": False, "replan": False, "reason": f"Verdict failed: {str(exc)[:160]}", "next_request": None}
    record_event(store, run["id"], "verdict", {
        "step": step_index + 1, "achieved": bool(verdict.get("achieved")), "replan": bool(verdict.get("replan")),
        "reason": _clip(verdict.get("reason"), 400), "next_request": _clip(verdict.get("next_request"), 300) if verdict.get("next_request") else None,
    })
    return verdict


def _step_advance(store: Any, run: dict[str, Any], config: dict[str, Any], step_index: int,
                  plan: dict[str, Any] | None, operation: dict[str, Any] | None,
                  deps: SimpleNamespace, settings: dict[str, Any], goal: str) -> Any:
    try:
        verdict = deps.evaluate_objective(plan or {}, operation, settings)
    except Exception:
        verdict = {"achieved": False}
    config["step_index"] = step_index + 1
    run["config"] = config
    _save_run(store, run)
    if verdict.get("achieved"):
        _finish(store, run, "achieved", verdict.get("reason") or "Objective verified against observed output.")
        return "halt"
    return plan, operation


def start_run(store: Any, workspace: Any, executor: Any, goal: str, *, max_steps: int = DEFAULT_MAX_STEPS,
              cwd: str | None = None, engagement_id: str | None = None,
              conversation_id: str | None = None, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    ensure_schema(store)
    reconcile(store)
    goal = (goal or "").strip()
    if not goal:
        raise ValueError("goal is required")
    if len(goal) > 2000:
        raise ValueError("goal is too long")
    try:
        max_steps = max(1, min(int(max_steps), MAX_STEPS_LIMIT))
    except (TypeError, ValueError):
        max_steps = DEFAULT_MAX_STEPS
    with _REGISTRY_LOCK:
        for run_id, entry in list(_REGISTRY.items()):
            thread = entry.get("thread")
            if thread is not None and thread.is_alive():
                raise RuntimeError(f"Agent run {run_id} is already active. Stop it before starting another.")
    deps = _deps()
    settings = dict(settings or deps.load_settings())
    preflight = model_preflight(settings)
    import json

    run_id = secrets.token_hex(16)
    created = _now_iso()
    config = {"max_steps": max_steps, "cwd": cwd, "engagement_id": engagement_id,
              "conversation_id": conversation_id, "step_index": 0, "seen_digests": [],
              "pending_plan_id": None, "pending_operation_id": None, "settings": settings}
    status = "running" if preflight.get("ok") else "finished"
    summary: dict[str, Any] = {}
    if not preflight.get("ok"):
        summary = {"outcome": "needs_model", "reason": preflight.get("message"), "steps": 0}
    with store.lock, store.connect() as db:
        db.execute(
            "INSERT INTO agent_mode_runs(id, goal, status, created_at, updated_at, config_json, summary_json)"
            " VALUES (?,?,?,?,?,?,?)",
            (run_id, goal, status, created, created, json.dumps(config), json.dumps(summary)),
        )
    run = get_run(store, run_id) or {"id": run_id, "goal": goal, "status": status,
                                     "created_at": created, "updated_at": created,
                                     "config": config, "summary": summary}
    record_event(store, run_id, "run_started", {"goal": _clip(goal, 500), "max_steps": max_steps,
                                                "preflight": {key: preflight.get(key) for key in ("ok", "healthy", "message")}})
    try:
        store.append_audit("agent_run_started", {"run_id": run_id, "goal": goal[:200], "preflight_ok": bool(preflight.get("ok"))})
    except Exception:
        pass
    if not preflight.get("ok"):
        record_event(store, run_id, "finished", {"outcome": "needs_model", "reason": preflight.get("message"),
                                                 "guidance": preflight.get("guidance"), "open_view": "models"})
        run = get_run(store, run_id) or run
        return {"run": run, "preflight": preflight}
    stop = threading.Event()
    resume = threading.Event()
    thread = threading.Thread(target=_drive, args=(store, workspace, executor, run_id), daemon=True)
    with _REGISTRY_LOCK:
        _REGISTRY[run_id] = {"stop": stop, "resume": resume, "thread": thread}
    thread.start()
    return {"run": get_run(store, run_id) or run, "preflight": preflight}


def approve_run(store: Any, workspace: Any, executor: Any, run_id: str, plan_id: str | None, confirm: bool) -> dict[str, Any]:
    ensure_schema(store)
    run = get_run(store, run_id)
    if not run:
        raise LookupError("agent run not found")
    if run["status"] != "awaiting_approval":
        raise RuntimeError(f"run is {run['status']}; nothing is waiting for approval")
    if confirm is not True:
        raise ValueError("explicit confirmation is required")
    config = run.get("config") or {}
    pending_plan = config.get("pending_plan_id")
    pending_op = config.get("pending_operation_id")
    if pending_plan:
        if not plan_id or plan_id != pending_plan:
            raise ValueError("approval must name the exact waiting plan")
        plan = store.get_plan(pending_plan)
        if not plan or plan.get("status") != "planned":
            raise RuntimeError("the waiting plan is no longer executable")
        run["status"] = "running"
        run["config"] = config
        _save_run(store, run)
        record_event(store, run_id, "approved", {"plan_id": plan["id"], "approval_phrase": plan.get("approval_phrase")})
        try:
            store.append_audit("agent_run_approved", {"run_id": run_id, "plan_id": plan["id"]})
        except Exception:
            pass
    elif pending_op:
        operation = store.get_operation(pending_op)
        if operation is None:
            raise RuntimeError("the waiting operation is gone; the run cannot resume")
        if operation.get("status") == "awaiting_confirmation":
            raise RuntimeError("approve the mutation preflight in the Tasks view first, then resume this run")
        # The worker keeps observing this operation; the pending id stays set.
        run["status"] = "running"
        run["config"] = config
        _save_run(store, run)
        record_event(store, run_id, "resumed", {"operation_id": pending_op})
    else:
        raise RuntimeError("run is paused without a waiting step; stop it and start a new run")
    entry = _live_entry(run_id)
    if entry is None:
        stop = threading.Event()
        resume = threading.Event()
        thread = threading.Thread(target=_drive, args=(store, workspace, executor, run_id), daemon=True)
        with _REGISTRY_LOCK:
            _REGISTRY[run_id] = {"stop": stop, "resume": resume, "thread": thread}
        thread.start()
    else:
        try:
            entry["resume"].set()
        except Exception:
            pass
    return {"run": get_run(store, run_id) or run}


def stop_run(store: Any, executor: Any, run_id: str) -> dict[str, Any]:
    ensure_schema(store)
    run = get_run(store, run_id)
    if not run:
        raise LookupError("agent run not found")
    if run["status"] == "finished":
        return {"run": run, "stopped": False}
    entry = _live_entry(run_id)
    if entry is not None:
        try:
            entry["stop"].set()
        except Exception:
            pass
    config = run.get("config") or {}
    pending_op = config.get("pending_operation_id")
    if pending_op:
        try:
            executor.cancel(pending_op)
        except Exception:
            pass
    if entry is None:
        # No live worker (e.g. sidecar restarted while paused): finish now.
        record_event(store, run_id, "stopped", {"message": "Stopped by the operator."})
        run = _finish(store, run, "stopped", "Stopped by the operator.")
        return {"run": run, "stopped": True}
    thread = entry.get("thread")
    if thread is not None:
        thread.join(timeout=10)
    return {"run": get_run(store, run_id) or run, "stopped": True}
