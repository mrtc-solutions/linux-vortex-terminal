"""Candidate Normalizer for Vortex Terminal.

Normalizes historical, cloud, and local candidate responses into a unified
representation for fair, evidence-based arbitration.
"""
from __future__ import annotations

import secrets
from typing import Any

from .types import CandidateScores, NormalizedCandidate, Provenance
from .scorer import HistoricalCandidateScorer


class CandidateNormalizer:
    """Transforms heterogeneous candidate sources into standard NormalizedCandidate objects."""

    def __init__(self, scorer: HistoricalCandidateScorer | None = None):
        self.scorer = scorer or HistoricalCandidateScorer()

    def normalize_historical(
        self,
        request: str,
        raw_hist: dict[str, Any],
    ) -> NormalizedCandidate:
        """Normalize a historical candidate dictionary."""
        candidate_id = raw_hist.get("candidate_id") or f"hist-{secrets.token_hex(6)}"
        prov_dict = raw_hist.get("provenance") or {}
        prov = Provenance(**prov_dict) if isinstance(prov_dict, dict) else prov_dict

        text = str(raw_hist.get("answer") or "").strip()
        timestamp = raw_hist.get("timestamp") or prov.timestamp

        scores = self.scorer.score_candidate(request, raw_hist)

        return NormalizedCandidate(
            candidate_id=candidate_id,
            source_type="historical",
            provider=prov.provider or "vortex-history",
            provider_name="Vortex Memory / History",
            model=prov.model or "previous-turn",
            answer=text,
            timestamp=timestamp,
            summary=text[:160] + "..." if len(text) > 160 else text,
            scores=scores,
            confidence=round(scores.final_score / 100.0, 4),
            provenance=prov,
            facts=[],
            tags=["historical", "memory"],
        )

    def normalize_cloud(
        self,
        request: str,
        raw_cloud: dict[str, Any],
        *,
        provider_id: str | None = None,
        model: str | None = None,
    ) -> NormalizedCandidate:
        """Normalize a newly generated cloud response."""
        candidate_id = f"cloud-{secrets.token_hex(6)}"
        text = str(raw_cloud.get("reply") or raw_cloud.get("content") or "").strip()
        prov_name = raw_cloud.get("provider_name") or provider_id or "cloud"
        p_id = raw_cloud.get("provider") or provider_id or "cloud-provider"
        m_id = raw_cloud.get("model") or model or "cloud-model"

        prov = Provenance(
            provider=p_id,
            model=m_id,
            verified=False,
            exit_code=None,
        )

        cand_dict = {
            "candidate_id": candidate_id,
            "source_type": "cloud",
            "answer": text,
            "provenance": prov.to_dict(),
            "relevance": 0.92,
        }

        scores = self.scorer.score_candidate(request, cand_dict)

        return NormalizedCandidate(
            candidate_id=candidate_id,
            source_type="cloud",
            provider=p_id,
            provider_name=prov_name,
            model=m_id,
            answer=text,
            timestamp=prov.timestamp,
            summary=text[:160] + "..." if len(text) > 160 else text,
            scores=scores,
            confidence=round(scores.final_score / 100.0, 4),
            provenance=prov,
            facts=[],
            tags=["cloud", "new-generation"],
        )

    def normalize_local(
        self,
        request: str,
        raw_local: dict[str, Any],
        *,
        model: str = "qwen2.5:3b",
    ) -> NormalizedCandidate:
        """Normalize a local model response."""
        candidate_id = f"local-{secrets.token_hex(6)}"
        text = str(raw_local.get("reply") or raw_local.get("content") or "").strip()

        prov = Provenance(
            provider="ollama-local",
            model=model,
            verified=False,
        )

        cand_dict = {
            "candidate_id": candidate_id,
            "source_type": "local",
            "answer": text,
            "provenance": prov.to_dict(),
            "relevance": 0.90,
        }

        scores = self.scorer.score_candidate(request, cand_dict)

        return NormalizedCandidate(
            candidate_id=candidate_id,
            source_type="local",
            provider="ollama-local",
            provider_name="Local Ollama (Qwen)",
            model=model,
            answer=text,
            timestamp=prov.timestamp,
            summary=text[:160] + "..." if len(text) > 160 else text,
            scores=scores,
            confidence=round(scores.final_score / 100.0, 4),
            provenance=prov,
            facts=[],
            tags=["local", "ollama"],
        )
