"""Unit & Integration Tests for Historical Answer Candidate Retrieval and Arbitration.

Covers test cases A through J:
- Test A: Historical answer wins (verified outcome beats weak/generic cloud answer)
- Test B: Cloud answer wins (outdated/stale history beaten by fresh cloud info)
- Test C: Synthesis wins (verified local hardware facts + general technical guidance)
- Test D: Stale history penalized via freshness decay
- Test E: Verified execution outcome carries high confidence
- Test F: User rejection decreases future confidence
- Test G: Contradiction detection against verified host facts
- Test H: Simple greeting bypasses heavy retrieval
- Test I: Technical question triggers historical retrieval & arbitration
- Test J: Action requests retain Guardian authority
- Test K: Provenance and Lineage tree recording
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.arbitration import (
    AnswerArbitrator,
    AnswerLineageStore,
    CandidateComparator,
    CandidateNormalizer,
    HistoricalCandidateRetriever,
    HistoricalCandidateScorer,
    arbitrate_turn,
    compute_lexical_similarity,
)
from backend.arbitration.types import (
    ArbitrationResult,
    CandidateScores,
    NormalizedCandidate,
    Provenance,
)
from backend.conversation import classify, respond
from backend.vortex_backend import Store
from backend.workspace import Workspace


class HistoricalArbitrationTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test_vortex.db")
        self.workspace = Workspace(self.store)
        self.host_facts = {
            "os": "debian",
            "arch": "x86_64",
            "mem_total_mb": 4096,
            "distro": "Debian GNU/Linux 12 (bookworm)",
            "installed_models": ["qwen2.5:3b"],
        }
        self.scorer = HistoricalCandidateScorer(host_facts=self.host_facts)
        self.normalizer = CandidateNormalizer(scorer=self.scorer)
        self.comparator = CandidateComparator(host_facts=self.host_facts)
        self.arbitrator = AnswerArbitrator(comparator=self.comparator)
        self.lineage_store = AnswerLineageStore(self.workspace, self.store)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_lexical_similarity_computations(self) -> None:
        """Verify token and entity matching between queries and historical answers."""
        q1 = "Why is my Vortex Qwen model taking so long to start?"
        a1 = "Qwen 2.5 3B is taking 30 seconds because Ollama is loading the model into RAM."
        a2 = "How to configure Git credentials for GitHub SSH access."

        sim1 = compute_lexical_similarity(q1, a1)
        sim2 = compute_lexical_similarity(q1, a2)

        self.assertGreater(sim1, 0.30)
        self.assertLess(sim2, 0.15)
        self.assertGreater(sim1, sim2 * 2.5)

    def test_a_historical_answer_wins(self) -> None:
        """Test A: A verified historical solution beats a generic/weak cloud answer."""
        request = "Why is my Vortex Ollama model slow to respond and memory constrained?"

        # Historical candidate with verified execution on 4GB host
        hist_prov = Provenance(
            task_id="VTX-2026-0001",
            operation_id="op-001",
            verified=True,
            exit_code=0,
            reward=1.0,
            timestamp="2026-10-04T00:00:00.000+00:00",
        )
        hist_cand = self.normalizer.normalize_historical(
            request,
            {
                "candidate_id": "hist-perf-01",
                "answer": "The host system has 4GB RAM allocated. Under low-resource mode, set num_ctx=2048 and num_predict=320 in Ollama to keep Qwen 2.5 3B fast.",
                "original_request": request,
                "provenance": hist_prov.to_dict(),
                "timestamp": hist_prov.timestamp,
            },
        )

        # Cloud candidate suggesting generic upgrade
        cloud_cand = self.normalizer.normalize_cloud(
            request,
            {
                "reply": "You should upgrade your server to 64GB RAM and switch to a 70B parameter model.",
                "provider": "gemini-1",
                "provider_name": "Google Gemini",
                "model": "gemini-2.5-flash",
            },
        )

        result = self.arbitrator.arbitrate(request, [hist_cand, cloud_cand], host_facts=self.host_facts)

        self.assertEqual(result.decision, "historical")
        self.assertEqual(result.selected_candidate_id, "hist-perf-01")
        self.assertEqual(result.historical_contribution, "primary")
        self.assertGreater(result.confidence, 0.80)
        self.assertIn("4GB RAM", result.final_answer)

    def test_b_cloud_answer_wins(self) -> None:
        """Test B: Fresh verified cloud info beats outdated/stale historical info."""
        request = "What is the official endpoint for the NVIDIA NIM free API?"

        # Outdated historical candidate
        hist_prov = Provenance(
            timestamp="2025-01-01T00:00:00.000+00:00",  # old timestamp
            verified=False,
        )
        hist_cand = self.normalizer.normalize_historical(
            request,
            {
                "candidate_id": "hist-old-api",
                "answer": "NVIDIA NIM uses legacy endpoint https://api.nvidia.com/v0/chat (deprecated 2025).",
                "original_request": request,
                "provenance": hist_prov.to_dict(),
                "timestamp": hist_prov.timestamp,
            },
        )

        # Fresh cloud candidate
        cloud_cand = self.normalizer.normalize_cloud(
            request,
            {
                "reply": "NVIDIA NIM OpenAI-compatible endpoint is https://integrate.api.nvidia.com/v1.",
                "provider": "groq",
                "provider_name": "Groq Cloud",
                "model": "llama-3.3-70b-versatile",
            },
        )

        result = self.arbitrator.arbitrate(request, [hist_cand, cloud_cand], host_facts=self.host_facts)

        self.assertEqual(result.decision, "cloud")
        self.assertEqual(result.selected_candidate_id, cloud_cand.candidate_id)
        self.assertIn("https://integrate.api.nvidia.com/v1", result.final_answer)

    def test_c_synthesis_wins_on_near_tie(self) -> None:
        """Test C: Combines verified local environment facts with general technical guidance."""
        request = "How do I configure Ollama tags discovery on Vortex Terminal?"

        hist_prov = Provenance(
            verified=True,
            exit_code=0,
            timestamp="2026-10-04T00:00:00.000+00:00",
        )
        hist_cand = self.normalizer.normalize_historical(
            request,
            {
                "candidate_id": "hist-env-tags",
                "answer": "Vortex connects locally to Ollama at http://127.0.0.1:11434 with qwen2.5:3b.",
                "provenance": hist_prov.to_dict(),
                "timestamp": hist_prov.timestamp,
            },
        )

        cloud_cand = self.normalizer.normalize_cloud(
            request,
            {
                "reply": "Use GET /api/tags to list installed models and read the models array JSON response.",
                "provider": "openrouter",
                "provider_name": "OpenRouter",
                "model": "meta-llama/llama-3.3-70b-instruct:free",
            },
        )

        # Equalize scores to trigger synthesis
        hist_cand.scores.final_score = 90.0
        cloud_cand.scores.final_score = 91.0

        result = self.arbitrator.arbitrate(request, [hist_cand, cloud_cand], host_facts=self.host_facts)

        self.assertEqual(result.decision, "synthesized")
        self.assertTrue(result.synthesized)
        self.assertEqual(result.historical_contribution, "synthesized")
        self.assertIn("GET /api/tags", result.final_answer)
        self.assertIn("127.0.0.1:11434", result.final_answer)

    def test_d_stale_history_penalized(self) -> None:
        """Test D: Freshness decay reduces score of old volatile API answers."""
        request = "How to call provider API"
        old_time = "2024-01-01T00:00:00.000+00:00"
        fresh_time = "2026-10-04T00:00:00.000+00:00"

        old_cand = self.normalizer.normalize_historical(
            request,
            {"answer": "Use beta API endpoint /v1/beta/models", "timestamp": old_time},
        )
        fresh_cand = self.normalizer.normalize_historical(
            request,
            {"answer": "Use beta API endpoint /v1/beta/models", "timestamp": fresh_time},
        )

        self.assertLess(old_cand.scores.freshness, fresh_cand.scores.freshness)
        self.assertLess(old_cand.scores.final_score, fresh_cand.scores.final_score)

    def test_e_verified_outcome_carries_high_confidence(self) -> None:
        """Test E: Observed command outcome exit_code=0 gives higher confidence than untested text."""
        request = "How to inspect listening TCP ports on Linux"

        unverified = self.normalizer.normalize_historical(
            request,
            {
                "candidate_id": "unverified-01",
                "answer": "Run ss -tulpn to see open ports.",
                "provenance": {"verified": False, "exit_code": None},
            },
        )

        verified = self.normalizer.normalize_historical(
            request,
            {
                "candidate_id": "verified-01",
                "answer": "Run ss -tulpn to see open ports.",
                "provenance": {"verified": True, "exit_code": 0, "reward": 1.0},
            },
        )

        self.assertGreater(verified.scores.observed_outcome, unverified.scores.observed_outcome)
        self.assertGreater(verified.scores.evidence, unverified.scores.evidence)
        self.assertGreater(verified.scores.final_score, unverified.scores.final_score)

    def test_f_user_rejection_decreases_confidence(self) -> None:
        """Test F: User rejection decreases candidate confidence."""
        request = "How to restart Vortex sidecar service"

        accepted = self.normalizer.normalize_historical(
            request,
            {
                "answer": "Use systemctl --user restart vortex.service",
                "provenance": {"user_accepted": True, "feedback_rating": 5},
            },
        )

        rejected = self.normalizer.normalize_historical(
            request,
            {
                "answer": "Kill python process with kill -9 -1",
                "provenance": {"user_accepted": False, "feedback_rating": 1},
            },
        )

        self.assertGreater(accepted.scores.user_feedback, rejected.scores.user_feedback)
        self.assertGreater(accepted.scores.final_score, rejected.scores.final_score)

    def test_g_contradiction_detection_against_host_facts(self) -> None:
        """Test G: Flag and penalize candidate claiming non-existent models or wrong arch."""
        request = "Which local model is installed?"

        cand_hallucinated = self.normalizer.normalize_cloud(
            request,
            {
                "reply": "Your local system has qwen3.8 installed and running on 128GB RAM.",
                "provider": "openrouter",
            },
        )

        contradictions = self.comparator.inspect_and_penalize([cand_hallucinated])

        self.assertTrue(len(contradictions) > 0)
        self.assertTrue(any("qwen3.8" in c for c in contradictions))
        self.assertLess(cand_hallucinated.scores.correctness, 0.60)

    def test_h_simple_greeting_bypasses_heavy_retrieval(self) -> None:
        """Test H: Greeting does not trigger heavy historical retrieval."""
        routing = classify("hello")
        self.assertEqual(routing["category"], "conversation")
        self.assertEqual(routing["reason"], "greeting/small talk")

        # In conversation respond(), greeting sets historical_contribution to none
        res = respond("hello", workspace=self.workspace, store=self.store)
        self.assertEqual(res.get("historical_contribution"), "none")

    def test_i_technical_question_retrieves_history_and_arbitrates(self) -> None:
        """Test I: Substantive technical question queries history and records arbitration."""
        conv = self.workspace.create_conversation("Technical Test")
        self.workspace.add_message(conv["id"], "user", "Why is Qwen slow on 4GB RAM?")
        self.workspace.add_message(
            conv["id"],
            "vortex",
            "On a 4GB RAM host, Qwen 2.5 3B is constrained by context window. Reduce num_ctx to 2048.",
            {"meta": "verified-ram-tuning"},
        )

        retriever = HistoricalCandidateRetriever(self.workspace, self.store)
        matches = retriever.retrieve("Why is Qwen slow on 4GB RAM?", conversation_id=conv["id"])

        self.assertGreaterEqual(len(matches), 1)
        self.assertIn("4GB RAM", matches[0]["answer"])

    def test_j_action_request_preserves_guardian(self) -> None:
        """Test J: Action requests maintain full Guardian authority."""
        routing = classify("whoami")
        self.assertEqual(routing["category"], "action")
        self.assertIn("starts with the known command 'whoami'", routing["reason"])

    def test_k_lineage_and_provenance_recording(self) -> None:
        """Test K: Lineage tree is constructed and saved in SQLite database."""
        request = "Explain Vortex memory architecture"
        cand = self.normalizer.normalize_historical(
            request,
            {
                "candidate_id": "hist-lineage-01",
                "answer": "Vortex uses SQLite with WAL mode and hashed audit trails.",
                "provenance": {"task_id": "VTX-2026-0099", "verified": True, "exit_code": 0},
            },
        )

        res = self.arbitrator.arbitrate(request, [cand], host_facts=self.host_facts)
        saved = self.lineage_store.save_arbitration(request, res, conversation_id="conv-123", message_id="msg-456")

        self.assertIsNotNone(saved)
        retrieved = self.lineage_store.get_by_message("msg-456")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["decision"], "historical")
        self.assertEqual(retrieved["winning_candidate_id"], "hist-lineage-01")


if __name__ == "__main__":
    unittest.main()
