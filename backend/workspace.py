"""Conversations, tasks, memory, and generated reports on the local Store."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any

TASK_STATES = (
    "CREATED", "PLANNING", "WAITING_FOR_APPROVAL", "EXECUTING", "OBSERVING",
    "VALIDATING", "REPLANNING", "COMPLETED", "FAILED", "CANCELLED", "PAUSED",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    title TEXT NOT NULL, status TEXT NOT NULL, parent_id TEXT, version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL,
    role TEXT NOT NULL, content TEXT NOT NULL, meta_json TEXT NOT NULL, superseded_by TEXT,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    conversation_id TEXT, request TEXT NOT NULL, state TEXT NOT NULL,
    plan_id TEXT, operation_id TEXT, engagement_id TEXT, risk TEXT,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_seq (year INTEGER PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_at TEXT NOT NULL,
    title TEXT NOT NULL, body TEXT NOT NULL, meta_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiences (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, task_id TEXT, kind TEXT NOT NULL,
    outcome TEXT NOT NULL, validated INTEGER NOT NULL, body_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS procedures (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, name TEXT NOT NULL,
    environment TEXT NOT NULL, steps_json TEXT NOT NULL, source_task TEXT, uses INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, task_id TEXT, operation_id TEXT,
    kind TEXT NOT NULL, title TEXT NOT NULL, formats_json TEXT NOT NULL, body_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_events (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, at TEXT NOT NULL,
    kind TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY, at TEXT NOT NULL, plan_id TEXT, task_id TEXT,
    decision TEXT NOT NULL, risk TEXT, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, task_id TEXT, engagement_id TEXT,
    severity TEXT NOT NULL, title TEXT NOT NULL, evidence_json TEXT NOT NULL,
    validation TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY, at TEXT NOT NULL, agent_id TEXT NOT NULL, task_id TEXT,
    state TEXT NOT NULL, latency_ms INTEGER, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS engagement_scope (
    engagement_id TEXT PRIMARY KEY,
    excluded_json TEXT NOT NULL,
    environment TEXT,
    owner TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state, updated_at);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def ensure_schema(store: Any) -> None:
    with store.connect() as db:
        db.executescript(SCHEMA)


class Workspace:
    def __init__(self, store: Any):
        self.store = store
        ensure_schema(store)

    def create_conversation(self, title: str = "New conversation") -> dict[str, Any]:
        item = {"id": secrets.token_hex(16), "created_at": now_iso(), "updated_at": now_iso(), "title": (title or "New conversation")[:160], "status": "active", "parent_id": None, "version": 1}
        with self.store.lock, self.store.connect() as db:
            db.execute("INSERT INTO conversations VALUES (?,?,?,?,?,?,?)", (item["id"], item["created_at"], item["updated_at"], item["title"], item["status"], item["parent_id"], item["version"]))
        self.store.append_audit("conversation_created", {"conversation_id": item["id"]})
        return item

    def list_conversations(self, query: str | None = None) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM conversations WHERE status != 'deleted' ORDER BY updated_at DESC LIMIT 200").fetchall()
        items = [dict(row) for row in rows]
        if query:
            needle = query.lower()
            matched_ids = set()
            safe = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            with self.store.connect() as db:
                hits = db.execute(
                    "SELECT DISTINCT conversation_id FROM messages WHERE content LIKE ? ESCAPE '\\'",
                    (f"%{safe}%",),
                ).fetchall()
                matched_ids = {row[0] for row in hits}
            items = [item for item in items if needle in json.dumps(item).lower() or item["id"] in matched_ids]
        return items

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        return dict(row) if row else None

    def rename_conversation(self, conversation_id: str, title: str) -> dict[str, Any] | None:
        title = (title or "").strip()[:160]
        if not title:
            raise ValueError("title is required")
        with self.store.lock, self.store.connect() as db:
            db.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (title, now_iso(), conversation_id))
            # Reports of this conversation's tasks follow the new name so the
            # Reports view stays identifiable with its history conversation.
            db.execute(
                "UPDATE reports SET title=? WHERE task_id IN (SELECT id FROM tasks WHERE conversation_id=?)",
                (title, conversation_id),
            )
        return self.get_conversation(conversation_id)

    def archive_conversation(self, conversation_id: str) -> None:
        with self.store.lock, self.store.connect() as db:
            db.execute("UPDATE conversations SET status='archived', updated_at=? WHERE id=?", (now_iso(), conversation_id))

    def delete_conversation(self, conversation_id: str) -> None:
        with self.store.lock, self.store.connect() as db:
            db.execute("UPDATE conversations SET status='deleted', updated_at=? WHERE id=?", (now_iso(), conversation_id))

    def add_message(self, conversation_id: str, role: str, content: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        if role not in {"user", "vortex", "system"}:
            raise ValueError("invalid message role")
        item = {"id": secrets.token_hex(16), "conversation_id": conversation_id, "created_at": now_iso(), "role": role, "content": content[:20000], "meta": meta or {}, "superseded_by": None}
        with self.store.lock, self.store.connect() as db:
            db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", (item["id"], conversation_id, item["created_at"], role, item["content"], canonical(item["meta"]), None))
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (item["created_at"], conversation_id))
        return item

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at", (conversation_id,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["meta"] = json.loads(item.pop("meta_json"))
            result.append(item)
        return result

    def edit_and_branch(self, conversation_id: str, message_id: str, content: str) -> dict[str, Any]:
        original = self.get_conversation(conversation_id)
        if not original:
            raise ValueError("conversation not found")
        messages = self.list_messages(conversation_id)
        target = next((item for item in messages if item["id"] == message_id), None)
        if not target or target["role"] != "user":
            raise ValueError("only a user message can be edited")
        branch = {"id": secrets.token_hex(16), "created_at": now_iso(), "updated_at": now_iso(), "title": original["title"] + " (edit)", "status": "active", "parent_id": conversation_id, "version": int(original["version"]) + 1}
        with self.store.lock, self.store.connect() as db:
            db.execute("INSERT INTO conversations VALUES (?,?,?,?,?,?,?)", (branch["id"], branch["created_at"], branch["updated_at"], branch["title"], branch["status"], branch["parent_id"], branch["version"]))
            for item in messages:
                if item["created_at"] > target["created_at"]:
                    break
                text = content[:20000] if item["id"] == message_id else item["content"]
                meta = dict(item.get("meta") or {})
                if item["id"] == message_id:
                    meta["edited_from"] = message_id
                db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", (secrets.token_hex(16), branch["id"], item["created_at"], item["role"], text, canonical(meta), None))
            db.execute("UPDATE messages SET superseded_by=? WHERE id=?", (branch["id"], message_id))
        self.store.append_audit("conversation_branched", {"from": conversation_id, "to": branch["id"], "message_id": message_id})
        return branch

    def next_task_id(self) -> str:
        year = datetime.now(timezone.utc).year
        with self.store.lock, self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM task_seq WHERE year=?", (year,)).fetchone()
            value = int(row[0]) + 1 if row else 1
            db.execute("INSERT INTO task_seq(year, value) VALUES (?,?) ON CONFLICT(year) DO UPDATE SET value=excluded.value", (year, value))
            db.execute("COMMIT")
        return f"VTX-{year}-{value:06d}"

    def create_task(self, request: str, conversation_id: str | None = None, engagement_id: str | None = None) -> dict[str, Any]:
        item = {
            "id": self.next_task_id(),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "conversation_id": conversation_id,
            "request": request[:4000],
            "state": "CREATED",
            "plan_id": None,
            "operation_id": None,
            "engagement_id": engagement_id,
            "risk": None,
            "result": {},
        }
        self._save_task(item)
        self.store.append_audit("task_created", {"task_id": item["id"]})
        return item

    def _save_task(self, item: dict[str, Any]) -> None:
        with self.store.lock, self.store.connect() as db:
            db.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?)", (item["id"], item["created_at"], item["updated_at"], item.get("conversation_id"), item["request"], item["state"], item.get("plan_id"), item.get("operation_id"), item.get("engagement_id"), item.get("risk"), canonical(item.get("result") or {})))

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any] | None:
        item = self.get_task(task_id)
        if not item:
            return None
        if "state" in fields and fields["state"] not in TASK_STATES:
            raise ValueError("invalid task state")
        item.update(fields)
        item["updated_at"] = now_iso()
        with self.store.lock, self.store.connect() as db:
            db.execute("UPDATE tasks SET updated_at=?, conversation_id=?, request=?, state=?, plan_id=?, operation_id=?, engagement_id=?, risk=?, result_json=? WHERE id=?", (item["updated_at"], item.get("conversation_id"), item["request"], item["state"], item.get("plan_id"), item.get("operation_id"), item.get("engagement_id"), item.get("risk"), canonical(item.get("result") or {}), task_id))
        return item

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["result"] = json.loads(item.pop("result_json"))
        return item

    def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["result"] = json.loads(item.pop("result_json"))
            result.append(item)
        return result

    def interrupted_tasks(self) -> list[dict[str, Any]]:
        return [item for item in self.list_tasks(200) if item["state"] in {"EXECUTING", "OBSERVING", "WAITING_FOR_APPROVAL", "PLANNING", "PAUSED", "VALIDATING", "REPLANNING"}]

    def reconcile_orphaned_tasks(self) -> list[str]:
        """Move tasks whose operation died with a previous sidecar to PAUSED.

        A task in EXECUTING/OBSERVING is only advanced by the thread running its
        operation. Once the store has marked that operation
        ``unknown_after_crash`` no such thread exists, so the task is paused and
        the honest unknown outcome is recorded. The task is never marked
        COMPLETED: VORTEX does not claim an outcome it did not observe.
        """
        recovered: list[str] = []
        for task in self.list_tasks(200):
            if task["state"] not in {"EXECUTING", "OBSERVING", "VALIDATING", "REPLANNING"}:
                continue
            operation_id = task.get("operation_id")
            operation = self.store.get_operation(operation_id) if operation_id else None
            if operation_id and operation and operation.get("status") in {"started", "running"}:
                continue
            if operation_id and operation and operation.get("status") not in {"unknown_after_crash"}:
                continue
            result = dict(task.get("result") or {})
            result["recovery"] = {
                "state": "unknown_after_crash",
                "detail": "The sidecar stopped while this task was in flight. The real host outcome was not observed.",
            }
            self.update_task(task["id"], state="PAUSED", result=result)
            self.add_task_event(task["id"], "recovered_after_restart", {"previous_state": task["state"], "operation_id": operation_id})
            recovered.append(task["id"])
        return recovered

    def delete_task(self, task_id: str) -> dict[str, Any] | None:
        return self.update_task(task_id, state="CANCELLED")

    def reject_plan(self, plan_id: str) -> bool:
        with self.store.lock, self.store.connect() as db:
            cur = db.execute("UPDATE plans SET status='rejected' WHERE id=? AND status IN ('planned','approved')", (plan_id,))
            return cur.rowcount > 0

    def reject_task_plan(self, plan_id: str, task_id: str | None = None, executor: Any = None) -> dict[str, Any]:
        ok = self.reject_plan(plan_id)
        task = self.get_task(task_id) if task_id else self.find_task_by_plan(plan_id)
        if task:
            if executor and task.get("operation_id"):
                try:
                    executor.cancel(task["operation_id"])
                except Exception:
                    pass
            task = self.update_task(task["id"], state="CANCELLED")
            self.record_approval("reject", plan_id, task["id"], task.get("risk"), {})
            self.add_task_event(task["id"], "rejected", {"plan_id": plan_id})
        return {"rejected": ok, "task": task}

    def pause_task(self, task_id: str, executor: Any = None) -> dict[str, Any] | None:
        item = self.get_task(task_id)
        if not item:
            return None
        if executor and item.get("operation_id"):
            try:
                executor.cancel(item["operation_id"])
            except Exception:
                pass
        updated = self.update_task(task_id, state="PAUSED")
        self.add_task_event(task_id, "paused", {"operation_id": item.get("operation_id")})
        return updated

    def operations_for_engagement(self, engagement_id: str) -> list[dict[str, Any]]:
        matched: list[dict[str, Any]] = []
        if not engagement_id:
            return matched
        for item in self.store.list_history(200):
            try:
                plan = self.store.get_plan(item.get("plan_id") or "")
            except Exception:
                plan = None
            if plan and plan.get("engagement_id") == engagement_id:
                matched.append(item)
        return matched

    def add_memory(self, kind: str, title: str, body: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        if kind not in {"conversation", "task", "knowledge", "tool", "agent", "experience", "procedure"}:
            raise ValueError("invalid memory kind")
        item = {"id": secrets.token_hex(16), "kind": kind, "created_at": now_iso(), "title": title[:200], "body": body[:8000], "meta": meta or {}}
        with self.store.lock, self.store.connect() as db:
            db.execute("INSERT INTO memories VALUES (?,?,?,?,?,?)", (item["id"], kind, item["created_at"], item["title"], item["body"], canonical(item["meta"])))
        return item

    def list_memories(self, kind: str | None = None) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            if kind:
                rows = db.execute("SELECT * FROM memories WHERE kind=? ORDER BY created_at DESC LIMIT 200", (kind,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM memories ORDER BY created_at DESC LIMIT 200").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["meta"] = json.loads(item.pop("meta_json"))
            result.append(item)
        return result

    def record_experience(self, task: dict[str, Any], outcome: str, validated: bool = False) -> dict[str, Any]:
        item = {"id": secrets.token_hex(16), "created_at": now_iso(), "task_id": task.get("id"), "kind": task.get("result", {}).get("kind") or "task", "outcome": outcome, "validated": int(bool(validated)), "body": {"request": task.get("request"), "state": task.get("state"), "risk": task.get("risk")}}
        with self.store.lock, self.store.connect() as db:
            db.execute("INSERT INTO experiences VALUES (?,?,?,?,?,?,?)", (item["id"], item["created_at"], item["task_id"], item["kind"], outcome, item["validated"], canonical(item["body"])))
        if validated and outcome == "succeeded":
            self.upsert_procedure(task)
        return item

    def upsert_procedure(self, task: dict[str, Any]) -> dict[str, Any] | None:
        commands = (task.get("result") or {}).get("commands") or []
        if not commands:
            return None
        name = (task.get("result") or {}).get("kind") or task.get("request", "")[:80]
        item = {"id": secrets.token_hex(16), "created_at": now_iso(), "name": str(name)[:160], "environment": "Linux", "steps": commands, "source_task": task.get("id"), "uses": 1}
        existing = self.find_procedure(item["name"])
        with self.store.lock, self.store.connect() as db:
            if existing:
                db.execute("UPDATE procedures SET uses=uses+1, steps_json=?, source_task=? WHERE id=?", (canonical(commands), task.get("id"), existing["id"]))
                existing["uses"] += 1
                existing["steps"] = commands
                return existing
            db.execute("INSERT INTO procedures VALUES (?,?,?,?,?,?,?)", (item["id"], item["created_at"], item["name"], item["environment"], canonical(item["steps"]), item["source_task"], item["uses"]))
        return item

    def find_procedure(self, name: str) -> dict[str, Any] | None:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM procedures WHERE name=?", (name,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["steps"] = json.loads(item.pop("steps_json"))
        return item

    def list_procedures(self) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM procedures ORDER BY uses DESC, created_at DESC LIMIT 100").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["steps"] = json.loads(item.pop("steps_json"))
            result.append(item)
        return result

    def list_experiences(self) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM experiences ORDER BY created_at DESC LIMIT 200").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["body"] = json.loads(item.pop("body_json"))
            item["validated"] = bool(item["validated"])
            result.append(item)
        return result

    def report_title(self, task_id: str | None, fallback: str) -> str:
        """Name reports after their conversation so one thread = one named report set."""
        if not task_id:
            return fallback
        task = self.get_task(task_id)
        conversation_id = task.get("conversation_id") if task else None
        conversation = self.get_conversation(conversation_id) if conversation_id else None
        if conversation and conversation.get("title"):
            return f"{conversation['title']} · {task_id}"
        return fallback

    def save_report(self, record: dict[str, Any]) -> dict[str, Any]:
        item = {
            "id": record.get("id") or secrets.token_hex(16),
            "created_at": now_iso(),
            "task_id": record.get("task_id"),
            "operation_id": record.get("operation_id"),
            "kind": record.get("kind") or "task",
            "title": record.get("title") or "VORTEX report",
            "formats": record.get("formats") or ["md", "html", "json", "pdf"],
            "body": record.get("body") or {},
        }
        with self.store.lock, self.store.connect() as db:
            db.execute("INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)", (item["id"], item["created_at"], item["task_id"], item["operation_id"], item["kind"], item["title"], canonical(item["formats"]), canonical(item["body"])))
        return item

    def list_reports(self) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM reports ORDER BY created_at DESC LIMIT 200").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["formats"] = json.loads(item.pop("formats_json"))
            item["body"] = json.loads(item.pop("body_json"))
            result.append(item)
        return result

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list_reports() if item["id"] == report_id), None)

    def delete_report(self, report_id: str) -> bool:
        """Remove a derived report. History, operations, and the audit chain are untouched."""
        with self.store.lock, self.store.connect() as db:
            cursor = db.execute("DELETE FROM reports WHERE id=?", (report_id,))
            return cursor.rowcount > 0

    def find_task_by_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE plan_id=? ORDER BY updated_at DESC LIMIT 1", (plan_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["result"] = json.loads(item.pop("result_json"))
        return item

    def get_report_by_operation(self, operation_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list_reports() if item.get("operation_id") == operation_id), None)

    def export_conversation(self, conversation_id: str) -> dict[str, Any]:
        item = self.get_conversation(conversation_id)
        if not item:
            raise ValueError("conversation not found")
        return {"conversation": item, "messages": self.list_messages(conversation_id), "tasks": [task for task in self.list_tasks() if task.get("conversation_id") == conversation_id]}

    def matching_procedure(self, request: str) -> dict[str, Any] | None:
        lowered = (request or "").lower()
        for item in self.list_procedures():
            if item["name"] and item["name"].replace("_", " ") in lowered:
                return item
        return None

    def add_task_event(self, task_id: str, kind: str, payload: dict[str, Any] | None = None) -> None:
        with self.store.lock, self.store.connect() as db:
            db.execute("INSERT INTO task_events VALUES (?,?,?,?,?)", (secrets.token_hex(16), task_id, now_iso(), kind, canonical(payload or {})))

    def list_task_events(self, task_id: str) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM task_events WHERE task_id=? ORDER BY at", (task_id,)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            items.append(item)
        return items

    def record_approval(self, decision: str, plan_id: str | None, task_id: str | None, risk: str | None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        item = {"id": secrets.token_hex(16), "at": now_iso(), "plan_id": plan_id, "task_id": task_id, "decision": decision, "risk": risk, "payload": payload or {}}
        with self.store.lock, self.store.connect() as db:
            db.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?)", (item["id"], item["at"], plan_id, task_id, decision, risk or "", canonical(item["payload"])))
        self.store.append_audit("approval_recorded", {"approval_id": item["id"], "decision": decision, "plan_id": plan_id, "task_id": task_id})
        return item

    def add_finding(self, task_id: str | None, engagement_id: str | None, title: str, severity: str, evidence: dict[str, Any], validation: str = "observed") -> dict[str, Any]:
        if severity not in {"info", "low", "medium", "high", "critical"}:
            severity = "info"
        if validation not in {"observed", "inconclusive", "rejected", "unvalidated"}:
            validation = "unvalidated"
        item = {"id": secrets.token_hex(16), "created_at": now_iso(), "task_id": task_id, "engagement_id": engagement_id, "severity": severity, "title": title[:240], "evidence": evidence, "validation": validation}
        with self.store.lock, self.store.connect() as db:
            db.execute("INSERT INTO findings VALUES (?,?,?,?,?,?,?,?)", (item["id"], item["created_at"], task_id, engagement_id, severity, item["title"], canonical(evidence), validation))
        return item

    def list_findings(self, task_id: str | None = None) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            if task_id:
                rows = db.execute("SELECT * FROM findings WHERE task_id=? ORDER BY created_at DESC", (task_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM findings ORDER BY created_at DESC LIMIT 200").fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            items.append(item)
        return items

    def record_agent_run(self, agent_id: str, state: str, task_id: str | None, latency_ms: int, payload: dict[str, Any] | None = None) -> None:
        with self.store.lock, self.store.connect() as db:
            db.execute("INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?)", (secrets.token_hex(16), now_iso(), agent_id, task_id, state, int(latency_ms), canonical(payload or {})))

    def agent_scores(self) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            rows = db.execute("SELECT agent_id, COUNT(*) AS runs, SUM(CASE WHEN state='responded' THEN 1 ELSE 0 END) AS useful, AVG(latency_ms) AS avg_ms FROM agent_runs GROUP BY agent_id").fetchall()
        return [dict(row) for row in rows]

    def save_engagement_scope(self, engagement_id: str, excluded: list[str] | None, environment: str | None = None, owner: str | None = None) -> None:
        with self.store.lock, self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO engagement_scope VALUES (?,?,?,?)", (engagement_id, canonical(excluded or []), (environment or "")[:80], (owner or "")[:80]))

    def engagement_scope(self, engagement_id: str) -> dict[str, Any]:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM engagement_scope WHERE engagement_id=?", (engagement_id,)).fetchone()
        if not row:
            return {"excluded_targets": [], "environment": None, "owner": None}
        return {"excluded_targets": json.loads(row["excluded_json"]), "environment": row["environment"] or None, "owner": row["owner"] or None}

    def search_all(self, term: str, limit: int = 100) -> dict[str, Any]:
        """Cross-layer global search (history, conversation, findings, evidence,
        reports, sessions, tasks, memory).

        ``term`` is matched as a case-insensitive substring over the canonical
        JSON of each stored record.  Results are grouped by layer, bounded, and
        never fabricated: an empty match simply returns an empty group.
        """
        term = (term or "").strip()
        if not term:
            return {"term": term, "total": 0, "results": []}
        needle = term.lower()
        results: list[dict[str, Any]] = []

        def matches(item: Any) -> bool:
            try:
                return needle in canonical(item).lower() or needle in str(item).lower()
            except (TypeError, ValueError):
                return needle in str(item).lower()

        def add(layer: str, item_id: str | None, label: str, at: str | None, summary: str, data: Any) -> None:
            if len(results) >= limit * 5:
                return
            results.append({
                "layer": layer,
                "id": item_id,
                "label": label[:160],
                "at": at,
                "summary": summary[:240],
                "data": data,
            })

        for op in self.store.list_history(200):
            if matches(op):
                first = (op.get("commands") or [{}])[0]
                label = first.get("display") if first.get("display") else op.get("id")
                fact = (op.get("analysis") or {}).get("fact") or ""
                add("operations", op.get("id"), label, op.get("ended_at") or op.get("started_at"), fact, {"status": op.get("status"), "plan_id": op.get("plan_id"), "id": op.get("id")})

        for conversation in self.list_conversations():
            if matches(conversation):
                add("conversations", conversation.get("id"), conversation.get("title"), conversation.get("updated_at"), conversation.get("status"), {"id": conversation.get("id"), "title": conversation.get("title"), "status": conversation.get("status")})
            for message in self.list_messages(conversation["id"]):
                if matches(message):
                    add("messages", message.get("id"), f"{conversation.get('title')} · {message.get('role')}", message.get("created_at"), message.get("content")[:240], {"conversation_id": conversation.get("id"), "role": message.get("role"), "content": message.get("content")[:400]})

        for finding in self.list_findings():
            if matches(finding):
                add("findings", finding.get("id"), finding.get("title"), finding.get("created_at"), finding.get("severity"), {"id": finding.get("id"), "severity": finding.get("severity"), "validation": finding.get("validation"), "task_id": finding.get("task_id")})

        for artifact in self.store.list_artifacts():
            if matches(artifact):
                add("evidence", artifact.get("artifact_id"), artifact.get("kind"), artifact.get("created_at"), artifact.get("summary"), {"id": artifact.get("artifact_id"), "kind": artifact.get("kind"), "state": artifact.get("state"), "sha256": artifact.get("sha256")})

        for report in self.list_reports():
            if matches(report):
                add("reports", report.get("id"), report.get("title"), report.get("created_at"), report.get("kind"), {"id": report.get("id"), "kind": report.get("kind"), "formats": report.get("formats")})

        for session in self.store.list_sessions():
            if matches(session):
                add("sessions", session.get("id"), session.get("name"), session.get("started_at"), session.get("status"), {"id": session.get("id"), "shell": session.get("shell"), "status": session.get("status"), "cwd": session.get("cwd")})

        for task in self.list_tasks(200):
            if matches(task):
                add("tasks", task.get("id"), task.get("request"), task.get("updated_at"), task.get("state"), {"id": task.get("id"), "state": task.get("state"), "risk": task.get("risk"), "kind": (task.get("result") or {}).get("kind")})

        for memory in self.list_memories():
            if matches(memory):
                add("memory", memory.get("id"), memory.get("title"), memory.get("created_at"), memory.get("kind"), {"id": memory.get("id"), "kind": memory.get("kind")})

        results.sort(key=lambda item: item.get("at") or "", reverse=True)
        results = results[:limit]
        return {"term": term, "total": len(results), "results": results}

    def enrich_engagement(self, item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None
        item = dict(item)
        item.update(self.engagement_scope(item["id"]))
        expired = False
        try:
            from datetime import datetime
            import time as _time
            expired = _time.time() > datetime.fromisoformat(str(item.get("expires_at"))).timestamp()
        except (TypeError, ValueError):
            expired = True
        item["expired"] = expired
        if expired and item.get("status") == "active":
            item["effective_status"] = "expired"
        else:
            item["effective_status"] = item.get("status")
        return item
