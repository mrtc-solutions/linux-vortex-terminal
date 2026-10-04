"""Answer Lineage and Arbitration Persistence Store for Vortex Terminal."""
from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from .types import ArbitrationResult, now_iso


ARBITRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS arbitrations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    conversation_id TEXT,
    message_id TEXT,
    task_id TEXT,
    request TEXT NOT NULL,
    decision TEXT NOT NULL,
    winning_candidate_id TEXT,
    historical_contribution TEXT NOT NULL,
    confidence REAL NOT NULL,
    synthesized INTEGER NOT NULL,
    rationale TEXT NOT NULL,
    candidates_json TEXT NOT NULL,
    lineage_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidate_feedback (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    message_id TEXT,
    operation_id TEXT,
    feedback_type TEXT NOT NULL,
    score_delta REAL NOT NULL,
    comment TEXT
);
CREATE INDEX IF NOT EXISTS idx_arbitrations_message ON arbitrations(message_id);
CREATE INDEX IF NOT EXISTS idx_arbitrations_conversation ON arbitrations(conversation_id);
CREATE INDEX IF NOT EXISTS idx_candidate_feedback_cand ON candidate_feedback(candidate_id);
"""


class AnswerLineageStore:
    """Manages storage and feedback updates for arbitrated decisions and lineage."""

    def __init__(self, workspace: Any = None, store: Any = None):
        self.workspace = workspace
        self.store = store or (workspace.store if workspace else None)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        if not self.store:
            return
        try:
            with self.store.connect() as db:
                db.executescript(ARBITRATION_SCHEMA)
        except Exception:
            pass

    def save_arbitration(
        self,
        request: str,
        result: ArbitrationResult,
        *,
        conversation_id: str | None = None,
        message_id: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Save an arbitration decision to SQLite."""
        if not self.store:
            return result.to_dict()

        record_id = secrets.token_hex(16)
        created_at = result.created_at or now_iso()
        candidates_json = json.dumps([c.to_dict() for c in result.candidates])
        lineage_json = json.dumps(result.lineage.to_dict() if result.lineage else {})

        try:
            with self.store.lock, self.store.connect() as db:
                db.execute(
                    "INSERT INTO arbitrations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        record_id,
                        created_at,
                        conversation_id,
                        message_id,
                        task_id,
                        request[:1000],
                        result.decision,
                        result.selected_candidate_id,
                        result.historical_contribution,
                        result.confidence,
                        1 if result.synthesized else 0,
                        result.rationale,
                        candidates_json,
                        lineage_json,
                    ),
                )
        except Exception:
            pass

        return result.to_dict()

    def get_by_message(self, message_id: str) -> dict[str, Any] | None:
        """Retrieve arbitration decision by message ID."""
        if not self.store:
            return None
        try:
            with self.store.connect() as db:
                row = db.execute(
                    "SELECT * FROM arbitrations WHERE message_id = ? ORDER BY created_at DESC LIMIT 1",
                    (message_id,),
                ).fetchone()
                if not row:
                    return None
                data = dict(row)
                data["candidates"] = json.loads(data["candidates_json"])
                data["lineage"] = json.loads(data["lineage_json"])
                return data
        except Exception:
            return None

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """List recent arbitration decisions."""
        if not self.store:
            return []
        try:
            with self.store.connect() as db:
                rows = db.execute(
                    "SELECT id, created_at, conversation_id, message_id, task_id, request, "
                    "decision, winning_candidate_id, historical_contribution, confidence, "
                    "synthesized, rationale, lineage_json FROM arbitrations ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                out = []
                for r in rows:
                    d = dict(r)
                    d["lineage"] = json.loads(d["lineage_json"]) if d.get("lineage_json") else None
                    out.append(d)
                return out
        except Exception:
            return []

    def record_feedback(
        self,
        candidate_id: str,
        feedback_type: str,  # "accepted", "rejected", "rated", "outcome_success", "outcome_failure"
        score_delta: float,
        *,
        message_id: str | None = None,
        operation_id: str | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """Record user feedback or execution outcome against a candidate."""
        record = {
            "id": secrets.token_hex(16),
            "created_at": now_iso(),
            "candidate_id": candidate_id,
            "message_id": message_id,
            "operation_id": operation_id,
            "feedback_type": feedback_type,
            "score_delta": score_delta,
            "comment": comment,
        }
        if self.store:
            try:
                with self.store.lock, self.store.connect() as db:
                    db.execute(
                        "INSERT INTO candidate_feedback VALUES (?,?,?,?,?,?,?,?)",
                        (
                            record["id"],
                            record["created_at"],
                            record["candidate_id"],
                            record["message_id"],
                            record["operation_id"],
                            record["feedback_type"],
                            record["score_delta"],
                            record["comment"],
                        ),
                    )
            except Exception:
                pass
        return record
