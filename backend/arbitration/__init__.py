"""Historical Answer Candidate Retrieval and Arbitration Subsystem for Vortex Terminal."""
from __future__ import annotations

from typing import Any

from .types import (
    ArbitrationDecisionType,
    ArbitrationResult,
    CandidateScores,
    HistoricalContributionType,
    LineageNode,
    NormalizedCandidate,
    Provenance,
)
from .retriever import HistoricalCandidateRetriever, compute_lexical_similarity
from .scorer import (
    DEFAULT_WEIGHTS,
    EXPLANATORY_WEIGHTS,
    TECHNICAL_WEIGHTS,
    HistoricalCandidateScorer,
)
from .normalizer import CandidateNormalizer
from .comparator import CandidateComparator
from .arbitrator import ARBITRATOR_SYSTEM_PROMPT, AnswerArbitrator
from .lineage import ARBITRATION_SCHEMA, AnswerLineageStore


def arbitrate_turn(
    request: str,
    new_candidate: dict[str, Any] | None,
    *,
    workspace: Any = None,
    store: Any = None,
    settings: dict[str, Any] | None = None,
    host_facts: dict[str, Any] | None = None,
    conversation_id: str | None = None,
    provider_manager: Any = None,
    min_relevance: float = 0.20,
) -> ArbitrationResult:
    """Full-pipeline helper: retrieves history, scores all candidates, and arbitrates."""
    settings = settings or {}

    retriever = HistoricalCandidateRetriever(workspace=workspace, store=store)
    scorer = HistoricalCandidateScorer(host_facts=host_facts)
    normalizer = CandidateNormalizer(scorer=scorer)
    comparator = CandidateComparator(host_facts=host_facts)
    arbitrator = AnswerArbitrator(provider_manager=provider_manager, comparator=comparator)
    lineage_store = AnswerLineageStore(workspace=workspace, store=store)

    candidates: list[NormalizedCandidate] = []

    # 1. Retrieve and normalize historical candidates
    raw_history = retriever.retrieve(request, conversation_id=conversation_id, min_relevance=min_relevance)
    for raw_h in raw_history:
        candidates.append(normalizer.normalize_historical(request, raw_h))

    # 2. Normalize new candidate if provided
    if new_candidate and (new_candidate.get("reply") or new_candidate.get("content")):
        candidates.append(normalizer.normalize_cloud(request, new_candidate))

    # 3. Arbitrate
    result = arbitrator.arbitrate(request, candidates, settings=settings, host_facts=host_facts)

    # 4. Save lineage
    lineage_store.save_arbitration(request, result, conversation_id=conversation_id)

    return result


__all__ = [
    "ArbitrationDecisionType",
    "ArbitrationResult",
    "CandidateScores",
    "HistoricalContributionType",
    "LineageNode",
    "NormalizedCandidate",
    "Provenance",
    "HistoricalCandidateRetriever",
    "HistoricalCandidateScorer",
    "CandidateNormalizer",
    "CandidateComparator",
    "AnswerArbitrator",
    "AnswerLineageStore",
    "arbitrate_turn",
    "compute_lexical_similarity",
    "DEFAULT_WEIGHTS",
    "TECHNICAL_WEIGHTS",
    "EXPLANATORY_WEIGHTS",
    "ARBITRATOR_SYSTEM_PROMPT",
    "ARBITRATION_SCHEMA",
]
