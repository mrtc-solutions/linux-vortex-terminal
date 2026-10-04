"""Multi-dimensional Candidate Scorer for Vortex Terminal.

Evaluates candidates (historical and newly generated) across 9 dimensions:
Relevance, Correctness, Evidence, Observed Outcome, Context Match, Freshness,
Completeness, Consistency, and User Feedback.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from .types import CandidateScores, NormalizedCandidate
from .retriever import compute_lexical_similarity, _extract_technical_entities


DEFAULT_WEIGHTS = {
    "relevance": 0.20,
    "correctness": 0.25,
    "evidence": 0.15,
    "observed_outcome": 0.15,
    "context_match": 0.10,
    "freshness": 0.05,
    "completeness": 0.05,
    "user_feedback": 0.05,
}

TECHNICAL_WEIGHTS = {
    "observed_outcome": 0.25,
    "evidence": 0.20,
    "context_match": 0.15,
    "correctness": 0.15,
    "relevance": 0.15,
    "freshness": 0.05,
    "completeness": 0.03,
    "user_feedback": 0.02,
}

EXPLANATORY_WEIGHTS = {
    "correctness": 0.30,
    "relevance": 0.25,
    "completeness": 0.15,
    "evidence": 0.10,
    "freshness": 0.10,
    "context_match": 0.05,
    "observed_outcome": 0.00,
    "user_feedback": 0.05,
}


def _is_technical_request(request: str) -> bool:
    """Check if the request relates to technical, diagnostic, or environment actions."""
    lower = request.lower()
    technical_triggers = (
        "error", "slow", "fast", "optimiz", "install", "remove", "package",
        "systemd", "cgroup", "ram", "memory", "cpu", "disk", "gpu", "port",
        "socket", "service", "command", "exit", "code", "model", "qwen", "ollama",
        "gemini", "fail", "crash", "permission", "sudo", "apt", "dpkg", "vortex",
        "config", "why", "how do i", "how to", "troubleshoot", "debug",
    )
    return any(term in lower for term in technical_triggers)


def _compute_freshness(timestamp_str: str | None, text: str) -> float:
    """Compute temporal freshness score with domain-aware decay."""
    if not timestamp_str:
        return 0.85

    try:
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days = max(0.0, (now - dt).total_seconds() / 86400.0)
    except Exception:
        return 0.85

    # Check if content is fast-moving (API endpoints, provider versions) vs timeless Linux concepts
    is_volatile = bool(re.search(r"\b(api|v1|endpoint|model id|pricing|quota|beta|release|version 0\.)\b", text, re.I))

    if is_volatile:
        # Volatile API/provider info: half-life ~30 days
        decay = math.exp(-days / 30.0)
        return max(0.10, min(1.0, decay))
    else:
        # Core Linux / fundamental concept: slow decay, floor at 0.70
        decay = math.exp(-days / 180.0)
        return max(0.70, min(1.0, decay))


def _compute_evidence_score(candidate: dict[str, Any] | NormalizedCandidate) -> float:
    """Evaluate whether the candidate is backed by verifiable facts, outputs, or artifacts."""
    prov = candidate.provenance if isinstance(candidate, NormalizedCandidate) else candidate.get("provenance", {})
    text = candidate.answer if isinstance(candidate, NormalizedCandidate) else candidate.get("answer", "")

    score = 0.50  # baseline

    # Attached execution verification
    if isinstance(prov, dict):
        if prov.get("verified"):
            score += 0.35
        if prov.get("exit_code") == 0:
            score += 0.15
        if prov.get("reward") and prov.get("reward") > 0.8:
            score += 0.10
    else:
        if prov.verified:
            score += 0.35
        if prov.exit_code == 0:
            score += 0.15
        if prov.reward and prov.reward > 0.8:
            score += 0.10

    # Concrete facts and specific references in text
    if re.search(r"\b(exit code 0|succeeded|stdout|stderr|SHA256|digest|verified)\b", text, re.I):
        score += 0.10
    if re.search(r"/\w+/[^\s]+", text):  # file paths
        score += 0.05
    if re.search(r"\b\d+\s*(?:MB|GB|KB|MHz|GHz|ms|seconds)\b", text, re.I):  # concrete measurements
        score += 0.05

    return min(1.0, max(0.0, score))


def _compute_context_match(candidate: dict[str, Any] | NormalizedCandidate, host_facts: dict[str, Any] | None) -> float:
    """Evaluate compatibility with the current Linux host environment."""
    text = candidate.answer if isinstance(candidate, NormalizedCandidate) else candidate.get("answer", "")
    lower = text.lower()

    score = 0.90  # start high

    # If answer prescribes Windows-specific tools (powershell.exe, cmd.exe, regedit, C:\) for a Linux terminal
    if re.search(r"\b(powershell\.exe|cmd\.exe|regedit|c:\\|c:/|appdata)\b", lower):
        score -= 0.60

    # If answer claims a missing package or incorrect package manager for Debian (e.g. yum install, pacman -S, brew install)
    if re.search(r"\b(yum install|pacman -S|brew install|dnf install|emerge)\b", lower):
        score -= 0.35

    # If host is low-resource (e.g. <= 4GB RAM) and candidate suggests running massive 70B models
    if host_facts:
        mem_mb = host_facts.get("mem_total_mb") or 4096
        if mem_mb <= 4096 and re.search(r"\b(llama-3-70b|qwen-72b|deepseek-r1:70b|128gb ram|64gb ram)\b", lower):
            score -= 0.30

    return min(1.0, max(0.10, score))


def _compute_completeness(request: str, text: str) -> float:
    """Evaluate whether candidate directly addresses the question."""
    q_entities = _extract_technical_entities(request)
    if not q_entities:
        return 0.85 if len(text) > 40 else 0.50

    covered = sum(1 for e in q_entities if e in text.lower())
    coverage = covered / len(q_entities)
    return min(1.0, max(0.30, (coverage * 0.70) + (0.30 if len(text) > 60 else 0.15)))


def _compute_user_feedback_score(candidate: dict[str, Any] | NormalizedCandidate) -> float:
    """Extract user feedback score (1.0 = positive/working, 0.0 = rejected/broken)."""
    prov = candidate.provenance if isinstance(candidate, NormalizedCandidate) else candidate.get("provenance", {})
    if isinstance(prov, dict):
        if prov.get("user_accepted") is True:
            return 0.95
        if prov.get("user_accepted") is False:
            return 0.10
        if prov.get("feedback_rating"):
            # Rating 1 to 5 mapped to 0.1 to 1.0
            return max(0.1, min(1.0, prov["feedback_rating"] / 5.0))
    else:
        if prov.user_accepted is True:
            return 0.95
        if prov.user_accepted is False:
            return 0.10
        if prov.feedback_rating:
            return max(0.1, min(1.0, prov.feedback_rating / 5.0))
    return 0.50  # neutral


class HistoricalCandidateScorer:
    """Scores candidate answers across 9 dimensions and computes composite scores."""

    def __init__(self, host_facts: dict[str, Any] | None = None):
        self.host_facts = host_facts or {
            "os": "debian",
            "arch": "x86_64",
            "mem_total_mb": 4096,
            "distro": "Debian GNU/Linux 12 (bookworm)",
        }

    def score_candidate(
        self,
        request: str,
        candidate: dict[str, Any] | NormalizedCandidate,
        *,
        weights_override: dict[str, float] | None = None,
    ) -> CandidateScores:
        """Calculate the 9-dimensional score breakdown for a candidate."""
        text = candidate.answer if isinstance(candidate, NormalizedCandidate) else candidate.get("answer", "")
        timestamp = (
            candidate.timestamp if isinstance(candidate, NormalizedCandidate)
            else (candidate.get("timestamp") or candidate.get("provenance", {}).get("timestamp"))
        )

        # 1. Relevance
        relevance = (
            candidate.scores.relevance if isinstance(candidate, NormalizedCandidate) and candidate.scores.relevance > 0
            else candidate.get("relevance", compute_lexical_similarity(request, text))
        )

        # 2. Correctness
        correctness = 0.88
        if re.search(r"\b(error|traceback|syntaxerror|exception:)\b", text, re.I) and not re.search(r"(how to fix|solution|resolved)", text, re.I):
            correctness = 0.60
        if len(text.strip()) < 10:
            correctness = 0.20

        # 3. Evidence
        evidence = _compute_evidence_score(candidate)

        # 4. Observed Outcome
        prov = candidate.provenance if isinstance(candidate, NormalizedCandidate) else candidate.get("provenance", {})
        observed_outcome = 0.0
        if isinstance(prov, dict):
            if prov.get("verified") or (prov.get("exit_code") == 0 and prov.get("reward", 0) > 0.8):
                observed_outcome = 1.0
            elif prov.get("exit_code") == 0:
                observed_outcome = 0.85
            elif prov.get("exit_code") is not None and prov.get("exit_code") != 0:
                observed_outcome = 0.10
        else:
            if prov.verified or (prov.exit_code == 0 and (prov.reward or 0) > 0.8):
                observed_outcome = 1.0
            elif prov.exit_code == 0:
                observed_outcome = 0.85
            elif prov.exit_code is not None and prov.exit_code != 0:
                observed_outcome = 0.10

        # 5. Context Match
        context_match = _compute_context_match(candidate, self.host_facts)

        # 6. Freshness
        freshness = _compute_freshness(timestamp, text)

        # 7. Completeness
        completeness = _compute_completeness(request, text)

        # 8. Consistency
        consistency = 0.92

        # 9. User Feedback
        user_feedback = _compute_user_feedback_score(candidate)

        # Select weighting scheme
        if weights_override:
            weights = weights_override
        elif _is_technical_request(request):
            weights = TECHNICAL_WEIGHTS
        else:
            weights = EXPLANATORY_WEIGHTS

        # Calculate composite score (0 to 100)
        composite = (
            (relevance * weights.get("relevance", 0.20)) +
            (correctness * weights.get("correctness", 0.25)) +
            (evidence * weights.get("evidence", 0.15)) +
            (observed_outcome * weights.get("observed_outcome", 0.15)) +
            (context_match * weights.get("context_match", 0.10)) +
            (freshness * weights.get("freshness", 0.05)) +
            (completeness * weights.get("completeness", 0.05)) +
            (consistency * 0.00) +  # consistency folded into correctness
            (user_feedback * weights.get("user_feedback", 0.05))
        ) * 100.0

        return CandidateScores(
            relevance=round(relevance, 4),
            correctness=round(correctness, 4),
            evidence=round(evidence, 4),
            observed_outcome=round(observed_outcome, 4),
            context_match=round(context_match, 4),
            freshness=round(freshness, 4),
            completeness=round(completeness, 4),
            consistency=round(consistency, 4),
            user_feedback=round(user_feedback, 4),
            final_score=round(composite, 2),
        )
