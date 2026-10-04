"""Local Qwen Answer Arbitrator for Vortex Terminal.

Compares historical and newly generated candidates using evidence, observed outcomes,
freshness, and context matching to select or synthesize the winning response.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from .types import (
    ArbitrationDecisionType,
    ArbitrationResult,
    HistoricalContributionType,
    LineageNode,
    NormalizedCandidate,
)
from .comparator import CandidateComparator


ARBITRATOR_SYSTEM_PROMPT = """You are Vortex's Answer Arbitrator.

Your task is to determine which candidate answer best answers the user's CURRENT request.

You must compare:
1. historical answers (retrieved from memory/previous turns);
2. newly generated answers (from local/cloud AI models);
3. verified procedural and execution outcomes.

Do not prefer an answer merely because it is newer.
Do not prefer an answer merely because it came from a larger model.
Do not prefer historical answers merely because they previously worked.

Evaluate each candidate against:
- relevance to the current request;
- factual correctness;
- evidence & verified local hardware/OS facts;
- freshness & API currency;
- observed outcomes (exit 0 / verified state carries high weight);
- user feedback;
- completeness & absence of contradictions.

Rules:
1. When a historical answer is clearly superior (e.g. verified on this machine with successful outcome), choose "historical".
2. When a cloud answer is clearly superior (e.g. fresher API, newer accurate guidance), choose "cloud".
3. When both contain complementary verified details (e.g. historical local facts + new general guidance), choose "synthesized".

Output ONLY valid JSON with this exact schema:
{
  "decision": "historical" | "cloud" | "synthesized",
  "selected_candidate_id": "candidate_id_here",
  "confidence": 0.95,
  "historical_contribution": "none" | "supporting" | "primary" | "synthesized",
  "rationale": "Concise explanation of why this candidate or synthesis was chosen.",
  "synthesized_answer": "Combined answer text (only if decision is synthesized, else null)"
}
"""


class AnswerArbitrator:
    """Arbitrates between historical candidates and newly generated candidates."""

    def __init__(
        self,
        provider_manager: Any = None,
        comparator: CandidateComparator | None = None,
        arbitrator_model: str = "qwen2.5:3b",
    ):
        self.provider_manager = provider_manager
        self.comparator = comparator or CandidateComparator()
        self.arbitrator_model = arbitrator_model

    def arbitrate(
        self,
        request: str,
        candidates: list[NormalizedCandidate],
        *,
        settings: dict[str, Any] | None = None,
        host_facts: dict[str, Any] | None = None,
    ) -> ArbitrationResult:
        """Arbitrate between all candidate answers."""
        started = time.monotonic()
        settings = settings or {}

        if not candidates:
            return ArbitrationResult(
                decision="cloud",
                selected_candidate_id=None,
                final_answer="No candidate answers available.",
                confidence=0.0,
                historical_contribution="none",
                candidates=[],
                rationale="No candidates to arbitrate.",
                arbitrator_model=self.arbitrator_model,
                latency_ms=0,
            )

        # 1. Run contradiction and fact checking
        contradictions = self.comparator.inspect_and_penalize(candidates)

        # Sort candidates by final score descending
        candidates.sort(key=lambda c: c.scores.final_score, reverse=True)

        # If only 1 candidate exists
        if len(candidates) == 1:
            only = candidates[0]
            hist_contrib: HistoricalContributionType = (
                "primary" if only.source_type == "historical" else "none"
            )
            decision: ArbitrationDecisionType = (
                "historical" if only.source_type == "historical" else "cloud"
            )
            latency = int((time.monotonic() - started) * 1000)

            lineage = LineageNode(
                node_id=f"lineage-{only.candidate_id}",
                node_type="final_answer",
                source=only.provider,
                score=only.scores.final_score,
                description=f"Single candidate selected: {only.provider_name}",
                children=[
                    LineageNode(
                        node_id=only.candidate_id,
                        node_type=f"{only.source_type}_candidate",
                        source=only.provider,
                        score=only.scores.final_score,
                        description=only.summary or only.answer[:80],
                    )
                ],
            )

            return ArbitrationResult(
                decision=decision,
                selected_candidate_id=only.candidate_id,
                final_answer=only.answer,
                confidence=round(only.scores.final_score / 100.0, 4),
                historical_contribution=hist_contrib,
                candidates=candidates,
                rationale=f"Selected candidate {only.candidate_id} from {only.provider_name}.",
                lineage=lineage,
                arbitrator_model=self.arbitrator_model,
                latency_ms=latency,
                contradictions_detected=contradictions,
            )

        # 2. Try LLM-based arbitration with local Qwen model if available
        llm_result = self._try_llm_arbitration(request, candidates, settings)
        if llm_result is not None:
            llm_result.latency_ms = int((time.monotonic() - started) * 1000)
            llm_result.contradictions_detected = contradictions
            return llm_result

        # 3. Deterministic Multi-Criteria Decision Analysis (MCDA) fallback
        return self._deterministic_arbitration(request, candidates, started, contradictions)

    def _try_llm_arbitration(
        self,
        request: str,
        candidates: list[NormalizedCandidate],
        settings: dict[str, Any],
    ) -> ArbitrationResult | None:
        """Attempt arbitration via local Qwen (or active provider)."""
        if not self.provider_manager or not hasattr(self.provider_manager, "generate"):
            return None

        # Build candidate digest for the arbitrator prompt
        digest_lines = []
        for i, c in enumerate(candidates, 1):
            prov_str = f"verified outcome={c.provenance.verified}" if c.provenance.verified else f"source={c.source_type}"
            digest_lines.append(
                f"--- Candidate #{i} [ID: {c.candidate_id}] ({c.provider_name} / {c.model}) [{prov_str}] ---\n"
                f"Scores: Relevance={c.scores.relevance:.2f}, Correctness={c.scores.correctness:.2f}, "
                f"Evidence={c.scores.evidence:.2f}, Outcome={c.scores.observed_outcome:.2f}, "
                f"Context={c.scores.context_match:.2f}, Freshness={c.scores.freshness:.2f}, FinalScore={c.scores.final_score:.1f}\n"
                f"Answer Content:\n{c.answer[:2000]}\n"
            )

        prompt = (
            f"User Request:\n{request}\n\n"
            f"Candidates for Arbitration:\n"
            f"{''.join(digest_lines)}\n"
            f"Decide which candidate wins or synthesize a superior answer combining verified evidence. "
            f"Return JSON only."
        )

        messages = [
            {"role": "system", "content": ARBITRATOR_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            # Prefer local Qwen for arbitration. In the WEB_CLOUD runtime the
            # local model genuinely does not exist, so the best currently
            # available eligible cloud provider arbitrates instead — and the
            # result records arbitration_mode="CLOUD" rather than pretending
            # local Qwen did it.
            web_runtime = str((settings or {}).get("runtime") or "").upper() == "WEB_CLOUD"
            if web_runtime:
                resp = self.provider_manager.generate(
                    messages,
                    settings,
                    purpose="arbitration",
                    allow_fallback=True,
                )
            else:
                resp = self.provider_manager.generate(
                    messages,
                    settings,
                    provider_id="ollama-local",
                    model=self.arbitrator_model,
                    purpose="arbitration",
                    allow_fallback=True,
                )

            if resp.get("state") != "responded":
                return None

            raw_reply = str(resp.get("reply") or "").strip()
            # Extract JSON block
            json_match = re.search(r"\{.*\}", raw_reply, re.DOTALL)
            if not json_match:
                return None

            parsed = json.loads(json_match.group(0))
            decision = str(parsed.get("decision") or "cloud").lower()
            if decision not in {"historical", "cloud", "synthesized"}:
                decision = "cloud"

            selected_id = str(parsed.get("selected_candidate_id") or candidates[0].candidate_id)
            confidence = float(parsed.get("confidence") or 0.85)
            hist_contrib = str(parsed.get("historical_contribution") or "none").lower()
            if hist_contrib not in {"none", "supporting", "primary", "synthesized"}:
                hist_contrib = "none"

            rationale = str(parsed.get("rationale") or "Arbitrated by local model.")
            synthesized_answer = parsed.get("synthesized_answer")

            winning_cand = next((c for c in candidates if c.candidate_id == selected_id), candidates[0])

            final_answer = synthesized_answer if (decision == "synthesized" and synthesized_answer) else winning_cand.answer

            lineage = self._build_lineage(decision, selected_id, candidates, final_answer, confidence)

            # Honest provenance: which runtime actually arbitrated.
            arbitration_mode = "LOCAL" if str(resp.get("provider") or "") == "ollama-local" else "CLOUD"

            return ArbitrationResult(
                decision=decision,  # type: ignore
                selected_candidate_id=selected_id if decision != "synthesized" else None,
                final_answer=final_answer,
                confidence=confidence,
                historical_contribution=hist_contrib,  # type: ignore
                candidates=candidates,
                rationale=rationale,
                synthesized=(decision == "synthesized"),
                lineage=lineage,
                arbitrator_model=resp.get("model") or self.arbitrator_model,
                arbitration_mode=arbitration_mode,
            )
        except Exception:
            return None

    def _deterministic_arbitration(
        self,
        request: str,
        candidates: list[NormalizedCandidate],
        started: float,
        contradictions: list[str],
    ) -> ArbitrationResult:
        """Deterministic Multi-Criteria Decision Analysis (MCDA)."""
        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None

        hist_cands = [c for c in candidates if c.source_type == "historical"]
        cloud_cands = [c for c in candidates if c.source_type in {"cloud", "local"}]

        best_hist = hist_cands[0] if hist_cands else None
        best_cloud = cloud_cands[0] if cloud_cands else None

        decision: ArbitrationDecisionType = "cloud"
        selected_id = top.candidate_id
        final_answer = top.answer
        confidence = round(top.scores.final_score / 100.0, 4)
        hist_contrib: HistoricalContributionType = "none"
        synthesized = False
        rationale = ""

        # Case 1: Best Historical candidate clearly beats Cloud (e.g. Verified execution outcome or significantly higher score)
        if best_hist and (not best_cloud or best_hist.scores.final_score > best_cloud.scores.final_score + 5.0):
            decision = "historical"
            selected_id = best_hist.candidate_id
            final_answer = best_hist.answer
            confidence = round(best_hist.scores.final_score / 100.0, 4)
            hist_contrib = "primary"
            prov_note = "with verified execution outcome" if best_hist.provenance.verified else "from conversation history"
            rationale = f"Historical answer ({best_hist.candidate_id}) scored highest ({best_hist.scores.final_score:.1f} vs {best_cloud.scores.final_score if best_cloud else 0:.1f}) {prov_note}."

        # Case 2: Best Cloud candidate clearly beats Historical (e.g. Fresh API info or stale/mismatched history)
        elif best_cloud and (not best_hist or best_cloud.scores.final_score > best_hist.scores.final_score + 5.0):
            decision = "cloud"
            selected_id = best_cloud.candidate_id
            final_answer = best_cloud.answer
            confidence = round(best_cloud.scores.final_score / 100.0, 4)
            hist_contrib = "supporting" if (best_hist and best_hist.scores.relevance > 0.5) else "none"
            rationale = f"Cloud answer ({best_cloud.candidate_id}) from {best_cloud.provider_name} scored highest ({best_cloud.scores.final_score:.1f} vs {best_hist.scores.final_score if best_hist else 0:.1f}) with superior freshness and completeness."

        # Case 3: Near-tie (score difference <= 5.0) -> Perform evidence-based synthesis
        elif best_hist and best_cloud and abs(best_hist.scores.final_score - best_cloud.scores.final_score) <= 5.0:
            decision = "synthesized"
            selected_id = None
            synthesized = True
            hist_contrib = "synthesized"
            confidence = round(max(best_hist.scores.final_score, best_cloud.scores.final_score) / 100.0, 4)

            # Synthesize: combine verified local fact + new technical guidance
            final_answer = (
                f"{best_cloud.answer.rstrip()}\n\n"
                f"[Verified Local History & Environment Note]:\n{best_hist.answer.strip()}"
            )
            rationale = (
                f"Synthesized response: Near-tie between historical answer ({best_hist.scores.final_score:.1f}) "
                f"and cloud candidate ({best_cloud.scores.final_score:.1f}). Combined verified local context with updated guidance."
            )

        # Fallback to top scored candidate
        else:
            decision = "historical" if top.source_type == "historical" else "cloud"
            selected_id = top.candidate_id
            final_answer = top.answer
            confidence = round(top.scores.final_score / 100.0, 4)
            hist_contrib = "primary" if top.source_type == "historical" else "none"
            rationale = f"Selected candidate {top.candidate_id} based on composite evidence score ({top.scores.final_score:.1f})."

        latency = int((time.monotonic() - started) * 1000)
        lineage = self._build_lineage(decision, selected_id or top.candidate_id, candidates, final_answer, confidence)

        return ArbitrationResult(
            decision=decision,
            selected_candidate_id=selected_id,
            final_answer=final_answer,
            confidence=confidence,
            historical_contribution=hist_contrib,
            candidates=candidates,
            rationale=rationale,
            synthesized=synthesized,
            lineage=lineage,
            arbitrator_model="deterministic-mcda",
            latency_ms=latency,
            contradictions_detected=contradictions,
        )

    def _build_lineage(
        self,
        decision: str,
        winner_id: str,
        candidates: list[NormalizedCandidate],
        final_answer: str,
        confidence: float,
    ) -> LineageNode:
        """Construct a provenance & lineage tree for the final arbitrated answer."""
        children = []
        for c in candidates:
            c_node = LineageNode(
                node_id=c.candidate_id,
                node_type=f"{c.source_type}_candidate",
                source=c.provider_name or c.provider,
                score=c.scores.final_score,
                description=c.summary or c.answer[:80],
                metadata={
                    "relevance": c.scores.relevance,
                    "correctness": c.scores.correctness,
                    "evidence": c.scores.evidence,
                    "observed_outcome": c.scores.observed_outcome,
                    "context_match": c.scores.context_match,
                    "freshness": c.scores.freshness,
                    "verified": c.provenance.verified,
                    "exit_code": c.provenance.exit_code,
                    "task_id": c.provenance.task_id,
                    "operation_id": c.provenance.operation_id,
                    "message_id": c.provenance.message_id,
                },
            )
            # If candidate was backed by verified execution, attach child node
            if c.provenance.verified or c.provenance.operation_id:
                c_node.children.append(
                    LineageNode(
                        node_id=f"op-{c.provenance.operation_id or c.provenance.task_id}",
                        node_type="verified_outcome",
                        source="Vortex Execution Subsystem",
                        score=100.0 if c.provenance.verified else 85.0,
                        description=f"Verified Linux operation exit_code={c.provenance.exit_code}",
                        metadata={"task_id": c.provenance.task_id, "exit_code": c.provenance.exit_code},
                    )
                )
            children.append(c_node)

        return LineageNode(
            node_id=f"decision-{int(time.time()*1000)}",
            node_type="final_answer",
            source="Vortex Local Arbitrator (qwen2.5:3b)",
            score=confidence * 100.0,
            description=f"Arbitration Decision: {decision.upper()} (Winner: {winner_id})",
            metadata={"decision": decision, "confidence": confidence},
            children=children,
        )
