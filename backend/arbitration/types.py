"""Types and data structures for Historical Answer Candidate Retrieval and Arbitration."""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


CandidateSourceType = Literal["historical", "cloud", "local", "synthetic"]
ArbitrationDecisionType = Literal["historical", "cloud", "synthesized"]
HistoricalContributionType = Literal["none", "supporting", "primary", "synthesized"]


@dataclass
class CandidateScores:
    relevance: float = 0.0          # 0.0 - 1.0 (Query intent & semantic/lexical overlap)
    correctness: float = 0.0        # 0.0 - 1.0 (Factual accuracy & syntax validity)
    evidence: float = 0.0           # 0.0 - 1.0 (Backed by observed output digests & verified facts)
    observed_outcome: float = 0.0   # 0.0 - 1.0 (Execution exit 0 / verified state / reward)
    context_match: float = 0.0      # 0.0 - 1.0 (Hardware, OS, package versions, environment match)
    freshness: float = 0.0          # 0.0 - 1.0 (Temporal validity & API currency)
    completeness: float = 0.0       # 0.0 - 1.0 (Coverage of specific user requirements)
    consistency: float = 0.0        # 0.0 - 1.0 (Internal coherence & non-contradiction)
    user_feedback: float = 0.5      # 0.0 - 1.0 (User acceptance/positive rating vs rejection)
    final_score: float = 0.0        # 0.0 - 100.0 (Weighted composite score)

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class Provenance:
    conversation_id: str | None = None
    message_id: str | None = None
    task_id: str | None = None
    operation_id: str | None = None
    plan_id: str | None = None
    timestamp: str = field(default_factory=now_iso)
    provider: str | None = None
    model: str | None = None
    exit_code: int | None = None
    verified: bool = False
    reward: float | None = None
    user_accepted: bool | None = None
    feedback_rating: int | None = None
    title: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedCandidate:
    candidate_id: str
    source_type: CandidateSourceType
    provider: str
    model: str
    answer: str
    timestamp: str = field(default_factory=now_iso)
    provider_name: str | None = None
    summary: str | None = None
    scores: CandidateScores = field(default_factory=CandidateScores)
    confidence: float = 0.0
    provenance: Provenance = field(default_factory=Provenance)
    facts: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scores"] = self.scores.to_dict()
        data["provenance"] = self.provenance.to_dict()
        return data


@dataclass
class LineageNode:
    node_id: str
    node_type: str  # "final_answer", "historical_candidate", "cloud_candidate", "operation", "verified_outcome"
    source: str
    score: float
    description: str
    children: list[LineageNode] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "source": self.source,
            "score": round(self.score, 2),
            "description": self.description,
            "metadata": self.metadata,
            "children": [child.to_dict() for child in self.children],
        }


@dataclass
class ArbitrationResult:
    decision: ArbitrationDecisionType
    selected_candidate_id: str | None
    final_answer: str
    confidence: float
    historical_contribution: HistoricalContributionType
    candidates: list[NormalizedCandidate]
    rationale: str
    needs_verification: bool = False
    needs_more_candidates: bool = False
    synthesized: bool = False
    lineage: LineageNode | None = None
    arbitrator_model: str = "qwen2.5:3b"
    latency_ms: int = 0
    contradictions_detected: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "selected_candidate_id": self.selected_candidate_id,
            "final_answer": self.final_answer,
            "confidence": round(self.confidence, 4),
            "historical_contribution": self.historical_contribution,
            "candidates": [c.to_dict() for c in self.candidates],
            "rationale": self.rationale,
            "needs_verification": self.needs_verification,
            "needs_more_candidates": self.needs_more_candidates,
            "synthesized": self.synthesized,
            "lineage": self.lineage.to_dict() if self.lineage else None,
            "arbitrator_model": self.arbitrator_model,
            "latency_ms": self.latency_ms,
            "contradictions_detected": self.contradictions_detected,
            "created_at": self.created_at,
        }
