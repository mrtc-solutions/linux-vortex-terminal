"""Conversation turn: intent → plan → council → Guardian → optional execution."""
from __future__ import annotations

import time
from typing import Any


def interpret_operation(plan: dict[str, Any], operation: dict[str, Any]) -> str:
    if not operation:
        return "No operation ran."
    status = operation.get("status")
    commands = operation.get("commands") or []
    if status == "succeeded":
        bits = []
        for command in commands:
            summary = (command.get("stdout") or command.get("stderr") or "").strip().splitlines()
            head = summary[0][:220] if summary else "no output"
            bits.append(f"{command.get('display')}: {head}")
        return "Objective completed with observed command output. " + " | ".join(bits[:6])
    if status == "awaiting_confirmation":
        return "Fresh preflight facts were observed. Review them before approving the mutation."
    if status == "unavailable":
        return "A required tool was missing. No fabricated result was stored."
    if status in {"cancelled", "interrupted"}:
        return "Execution stopped before completion."
    if status == "timed_out":
        return "A command hit its timeout or output cap."
    return f"Operation ended as {status}. Review the command timeline for observed evidence."


def run_turn(store: Any, workspace: Any, executor: Any, request: str, *, cwd: str | None, engagement_id: str | None, conversation_id: str | None, settings: dict[str, Any], confirm: bool = False, approval_token: str | None = None) -> dict[str, Any]:
    try:
        from agents.council import consult
        from security.guardian import evaluate
        from vortex_backend import build_plan
    except ImportError:
        from backend.agents.council import consult
        from backend.security.guardian import evaluate
        from backend.vortex_backend import build_plan

    settings = settings or {}
    offline = bool(settings.get("offline"))
    conversation = workspace.get_conversation(conversation_id) if conversation_id else None
    if conversation_id and not conversation:
        raise ValueError("conversation not found")
    if not conversation:
        conversation = workspace.create_conversation(request[:60] or "New conversation")
    workspace.add_message(conversation["id"], "user", request)
    task = workspace.create_task(request, conversation["id"], engagement_id)
    workspace.update_task(task["id"], state="PLANNING")
    workspace.add_task_event(task["id"], "created", {"request": request[:200]})
    plan = build_plan(store, request, cwd, engagement_id, offline=offline)
    try:
        from episode import observe
    except ImportError:
        from backend.episode import observe
    observation = observe(plan)
    procedure = workspace.matching_procedure(plan.get("kind") or request)
    if procedure:
        plan.setdefault("notes", []).insert(0, f"Retrieved validated procedure {procedure['name']} (used {procedure.get('uses', 1)} time(s)). Commands still come from reviewed adapters.")
    started = time.monotonic()
    council = consult(plan, task, observation=observation)
    latency = int((time.monotonic() - started) * 1000)
    for item in council.get("consultations") or []:
        workspace.record_agent_run(str(item.get("agent") or "unknown"), str(item.get("state") or "unavailable"), task["id"], latency, {"message": item.get("message")})
    engagement = workspace.enrich_engagement(store.get_engagement(engagement_id)) if engagement_id else None
    guardian = evaluate(plan, settings, engagement)
    try:
        from observe import log_event
        log_event(store, "turn", {"task_id": task["id"], "kind": plan.get("kind"), "guardian": guardian.get("decision"), "risk": guardian.get("risk")})
    except Exception:
        pass
    workspace.update_task(task["id"], plan_id=plan["id"], risk=guardian["risk"], result={"kind": plan.get("kind"), "plan_status": plan.get("status"), "guardian": guardian, "council": council, "procedure": procedure["name"] if procedure else None, "observation": observation})
    operation = None
    auto = False
    if guardian["blocked"] or plan["status"] in {"clarified", "unavailable", "rejected"} or not plan.get("commands"):
        workspace.update_task(task["id"], state="COMPLETED" if plan["status"] == "clarified" else ("FAILED" if plan["status"] in {"rejected", "unavailable"} else "COMPLETED"))
        workspace.record_approval("observe", plan["id"], task["id"], guardian.get("risk"), {"status": plan["status"]})
        explanation = " ".join(plan.get("notes") or [guardian["reasons"][0] if guardian["reasons"] else "No command was planned."])
    elif guardian["decision"] == "auto" and plan["status"] == "planned":
        workspace.update_task(task["id"], state="EXECUTING")
        workspace.record_approval("auto", plan["id"], task["id"], guardian.get("risk"), {"policy": settings.get("profile")})
        operation = executor.start(plan, True, plan["approval_token"], False, offline)
        auto = True
        workspace.update_task(task["id"], state="OBSERVING", operation_id=operation["id"])
        explanation = "Guardian authorized a low-risk local diagnostic under the current policy. Real execution started."
    elif confirm:
        token = approval_token or plan.get("approval_token")
        if not token:
            workspace.update_task(task["id"], state="WAITING_FOR_APPROVAL")
            explanation = "A typed plan is ready. Guardian requires recorded approval before execution."
        else:
            workspace.update_task(task["id"], state="EXECUTING")
            workspace.record_approval("approve", plan["id"], task["id"], guardian.get("risk"), {"cli_yes": True})
            operation = executor.start(plan, True, token, False, offline)
            workspace.update_task(task["id"], state="OBSERVING", operation_id=operation["id"])
            explanation = "Approved plan execution started."
    else:
        workspace.update_task(task["id"], state="WAITING_FOR_APPROVAL")
        explanation = "A typed plan is ready. Guardian requires recorded approval before execution."
    assistant = workspace.add_message(conversation["id"], "vortex", explanation, {"task_id": task["id"], "plan_id": plan["id"], "guardian": guardian, "operation_id": operation["id"] if operation else None})
    return {
        "conversation": workspace.get_conversation(conversation["id"]),
        "message": assistant,
        "task": workspace.get_task(task["id"]),
        "plan": plan,
        "guardian": guardian,
        "council": council,
        "operation": operation,
        "auto_executed": auto,
        "explanation": explanation,
        "observation": observation,
    }


def finish_task(workspace: Any, task_id: str, operation: dict[str, Any], plan: dict[str, Any], executor: Any = None, store: Any = None, depth: int = 0) -> dict[str, Any] | None:
    try:
        from reports.engine import markdown
        from replan import evaluate_objective
        from episode import step as episode_step
    except ImportError:
        from backend.reports.engine import markdown
        from backend.replan import evaluate_objective
        from backend.episode import step as episode_step

    task = workspace.get_task(task_id)
    if not task:
        return None
    status = operation.get("status")
    mapping = {"succeeded": "COMPLETED", "failed": "FAILED", "cancelled": "CANCELLED", "timed_out": "FAILED", "unavailable": "FAILED", "interrupted": "CANCELLED", "awaiting_confirmation": "WAITING_FOR_APPROVAL", "unknown_after_crash": "PAUSED"}
    state = mapping.get(status, "FAILED")
    explanation = interpret_operation(plan, operation)
    result = dict(task.get("result") or {})
    episode = episode_step(plan, operation)
    result.update({
        "operation_status": status,
        "commands": [item.get("display") for item in operation.get("commands") or []],
        "kind": plan.get("kind"),
        "explanation": explanation,
        "episode": episode,
        "observation": episode.get("observation") or result.get("observation"),
    })
    workspace.add_task_event(task_id, "operation_finished", {"status": status, "operation_id": operation.get("id")})
    workspace.add_task_event(task_id, "episode_step", {"reward": (episode.get("evaluation") or {}).get("reward"), "done": (episode.get("evaluation") or {}).get("done")})
    objective = evaluate_objective(plan, operation)
    result["objective"] = objective
    for artifact in operation.get("artifacts") or []:
        for observation in (artifact.get("observations") or [])[:20]:
            if observation.get("type") == "open_port":
                workspace.add_finding(task_id, plan.get("engagement_id"), f"Open port observed {observation.get('port')}", "info", observation, "observed")
    validated = status == "succeeded" and bool(objective.get("achieved"))
    workspace.record_experience(workspace.get_task(task_id), status or "unknown", validated=validated)
    report = None
    if operation.get("id"):
        existing = workspace.get_report_by_operation(operation["id"])
        if existing:
            report = existing
        else:
            report = workspace.save_report({
                "task_id": task_id,
                "operation_id": operation.get("id"),
                "kind": "task" if plan.get("kind") not in {"authorized_engagement"} else "security",
                "title": f"{task_id} {plan.get('kind') or 'task'}",
                "body": {"markdown": markdown(operation, plan, workspace.get_task(task_id)), "status": status, "request": plan.get("request")},
            })
            workspace.add_memory("task", task_id, explanation, {"operation_id": operation.get("id")})
    final_state = "REPLANNING" if objective.get("replan") and not objective.get("achieved") else state
    workspace.update_task(task_id, state=final_state, operation_id=operation.get("id"), result=result)
    if task.get("conversation_id") and status not in {"started", "running"}:
        extra = " Report generated." if report else ""
        workspace.add_message(task["conversation_id"], "vortex", explanation + extra, {
            "task_id": task_id,
            "operation_id": operation.get("id"),
            "report_id": report.get("id") if report else None,
            "status": status,
        })
    if depth < 2 and executor is not None and store is not None and objective.get("next_request") and not objective.get("achieved"):
        try:
            try:
                from config import load_settings
                from security.guardian import evaluate
                from vortex_backend import build_plan
            except ImportError:
                from backend.config import load_settings
                from backend.security.guardian import evaluate
                from backend.vortex_backend import build_plan
            settings = load_settings()
            nxt = build_plan(store, objective["next_request"], plan.get("cwd"), plan.get("engagement_id"), offline=bool(settings.get("offline")))
            engagement = workspace.enrich_engagement(store.get_engagement(plan.get("engagement_id"))) if plan.get("engagement_id") else None
            guardian = evaluate(nxt, settings, engagement)
            if guardian.get("decision") == "auto" and nxt.get("status") == "planned":
                workspace.add_task_event(task_id, "replan", {"request": objective["next_request"], "plan_id": nxt["id"]})
                if task.get("conversation_id"):
                    workspace.add_message(task["conversation_id"], "vortex", f"Objective not fully met. Starting a reviewed follow-up: {objective['next_request']}")
                workspace.update_task(task_id, plan_id=nxt["id"], state="EXECUTING")
                executor.start(nxt, True, nxt["approval_token"], False, bool(settings.get("offline")))
        except Exception:
            pass
    return report


def stop_all(executor: Any, sessions: Any, workspace: Any | None = None) -> dict[str, Any]:
    cancelled_ops = 0
    for op_id in list(getattr(executor, "cancel_events", {}) or {}):
        if executor.cancel(op_id):
            cancelled_ops += 1
    killed_sessions = 0
    for session in sessions.list():
        if session.get("status") == "running" and sessions.kill(session["id"]):
            killed_sessions += 1
    paused = 0
    if workspace:
        for task in workspace.interrupted_tasks():
            workspace.update_task(task["id"], state="PAUSED")
            paused += 1
    return {"operations_cancelled": cancelled_ops, "sessions_killed": killed_sessions, "tasks_paused": paused}
