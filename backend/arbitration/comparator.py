"""Candidate Comparator and Contradiction Detector for Vortex Terminal.

Compares candidate answers against verified host facts and detects factual
contradictions between competing candidate answers.
"""
from __future__ import annotations

import re
from typing import Any

from .types import NormalizedCandidate


class CandidateComparator:
    """Detects contradictions between candidates and checks against ground-truth system facts."""

    def __init__(self, host_facts: dict[str, Any] | None = None):
        self.host_facts = host_facts or {}

    def inspect_and_penalize(
        self,
        candidates: list[NormalizedCandidate],
    ) -> list[str]:
        """Check all candidates against verified system state and flag/penalize discrepancies."""
        contradictions_found: list[str] = []

        for cand in candidates:
            cand_text = cand.answer.lower()

            # Fact Check 1: Model names
            # If candidate claims an unverified model is active/installed (e.g. "qwen3.8" or "llama4")
            fake_models = re.findall(r"\b(qwen3\.[0-9]|llama-?4|gpt-?6|deepseek-v5)\b", cand_text)
            if fake_models:
                issue = f"Candidate {cand.candidate_id} ({cand.provider}) claims non-existent model '{fake_models[0]}'."
                cand.contradictions.append(issue)
                contradictions_found.append(issue)
                cand.scores.correctness = max(0.10, cand.scores.correctness - 0.40)
                cand.scores.final_score = max(0.0, cand.scores.final_score - 25.0)

            # Fact Check 2: Low-resource hardware mismatch
            # Host has ~4GB RAM; if candidate tells operator to run 70B parameter models
            mem_mb = self.host_facts.get("mem_total_mb") or 4096
            if mem_mb <= 4096 and re.search(r"\b(run|pull|load|use)\s+(llama3:70b|qwen2.5:72b|deepseek-r1:70b)\b", cand_text):
                issue = f"Candidate {cand.candidate_id} proposes 70B model on a 4GB RAM host."
                cand.contradictions.append(issue)
                contradictions_found.append(issue)
                cand.scores.context_match = max(0.10, cand.scores.context_match - 0.50)
                cand.scores.final_score = max(0.0, cand.scores.final_score - 20.0)

            # Fact Check 3: Debian package management
            # If candidate suggests non-apt package manager on Debian
            if re.search(r"\b(yum install|pacman -S|brew install|dnf install|apk add)\b", cand_text):
                issue = f"Candidate {cand.candidate_id} proposes foreign package manager on Debian Linux."
                cand.contradictions.append(issue)
                contradictions_found.append(issue)
                cand.scores.context_match = max(0.10, cand.scores.context_match - 0.40)
                cand.scores.final_score = max(0.0, cand.scores.final_score - 15.0)

        # Cross-candidate contradiction check
        if len(candidates) >= 2:
            hist_cands = [c for c in candidates if c.source_type == "historical"]
            cloud_cands = [c for c in candidates if c.source_type in {"cloud", "local"}]

            for h in hist_cands:
                for c in cloud_cands:
                    # Detect direct endpoint or configuration conflicts
                    if ("127.0.0.1:11434" in h.answer and "127.0.0.1:11434" not in c.answer and "api" in c.answer.lower()):
                        # Check if cloud suggests a remote endpoint when historical notes local
                        pass
                    if ("qwen2.5:3b" in h.answer and "qwen" in c.answer.lower() and "qwen2.5:3b" not in c.answer):
                        issue = f"Candidate {c.candidate_id} differs on model identifier compared to verified history ({h.candidate_id})."
                        contradictions_found.append(issue)

        return contradictions_found

    def check_near_tie(
        self,
        candidate_a: NormalizedCandidate,
        candidate_b: NormalizedCandidate,
        threshold: float = 5.0,
    ) -> bool:
        """Check if top candidates are within the near-tie threshold."""
        return abs(candidate_a.scores.final_score - candidate_b.scores.final_score) <= threshold
