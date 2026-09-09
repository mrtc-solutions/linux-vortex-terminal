"""Local GGUF primary + fuzzy routing + per-function AI assistance.

Uses tiny real GGUF-magic fixture files and an explicit in-memory test engine
— production behavior without either remains honestly ``unavailable`` and is
asserted as such. Nothing here fabricates production model output.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.models import fuzzy as fuzzy_engine
from backend.models import gguf as gguf_provider


def _write_gguf(path: Path, size: int = 4096) -> None:
    path.write_bytes(b"GGUF" + (3).to_bytes(4, "little") + b"\x00" * max(0, size - 8))


def _reset_caches() -> None:
    gguf_provider.invalidate_scan_cache()
    fuzzy_engine.reset_latency()
    for name in ("backend.models.router", "models.router"):
        try:
            module = __import__(name, fromlist=["_STATUS_CACHE"])
            module._STATUS_CACHE.update({"at": 0.0, "key": None, "value": None})
        except ImportError:
            pass


class GgufDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.models = Path(self.tmp.name) / "models"
        self.models.mkdir()
        self._old_env = os.environ.get("VORTEX_MODELS_DIR")
        os.environ["VORTEX_MODELS_DIR"] = str(self.models)
        _reset_caches()

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("VORTEX_MODELS_DIR", None)
        else:
            os.environ["VORTEX_MODELS_DIR"] = self._old_env
        gguf_provider.set_test_engine(None)
        gguf_provider.unload()
        _reset_caches()
        self.tmp.cleanup()

    def test_curated_files_are_discovered_and_validated(self):
        _write_gguf(self.models / "Llama-3.2-3B-Instruct-Q4_K_M.gguf")
        _write_gguf(self.models / "Qwen2.5-3B-Instruct-Q4_K_M.gguf")
        found = gguf_provider.scan()
        self.assertEqual(len(found["valid_files"]), 2)
        self.assertEqual(found["curated_missing"], [])
        by_name = {item["name"]: item for item in found["valid_files"]}
        self.assertEqual(by_name["Llama-3.2-3B-Instruct-Q4_K_M.gguf"]["family"], "llama")
        self.assertEqual(by_name["Qwen2.5-3B-Instruct-Q4_K_M.gguf"]["family"], "qwen")
        self.assertEqual(by_name["Llama-3.2-3B-Instruct-Q4_K_M.gguf"]["quant"], "Q4_K_M")

    def test_non_gguf_bytes_are_rejected_not_trusted(self):
        (self.models / "fake.gguf").write_bytes(b"NOT!" + b"\x00" * 64)
        found = gguf_provider.scan()
        self.assertEqual(found["valid_files"], [])
        self.assertEqual(len(found["files"]), 1)
        self.assertFalse(found["files"][0]["valid"])
        self.assertIn("GGUF", found["files"][0]["reason"])

    def test_empty_directory_reports_missing_curated_models(self):
        found = gguf_provider.scan()
        self.assertEqual(found["valid_files"], [])
        self.assertIn("Llama-3.2-3B-Instruct-Q4_K_M.gguf", found["curated_missing"])
        self.assertIn("Qwen2.5-3B-Instruct-Q4_K_M.gguf", found["curated_missing"])

    def test_status_unavailable_without_engine_is_honest(self):
        _write_gguf(self.models / "Llama-3.2-3B-Instruct-Q4_K_M.gguf")
        with patch("backend.models.gguf._python_engine_available", return_value=False), \
             patch("backend.models.gguf._trusted_cli", return_value=None):
            snapshot = gguf_provider.status({"gguf_enabled": True})
        self.assertEqual(snapshot["state"], "unavailable")
        self.assertIn("engine", snapshot["reason"].lower())

    def test_status_healthy_with_test_engine_and_roles(self):
        _write_gguf(self.models / "Llama-3.2-3B-Instruct-Q4_K_M.gguf")
        _write_gguf(self.models / "Qwen2.5-3B-Instruct-Q4_K_M.gguf")
        gguf_provider.set_test_engine(lambda entry, system, user: json.dumps({
            "fact_summary": "test", "meaning": "", "unknowns": "",
            "next_steps": [], "caution": "", "status_alignment": "observed-success"}))
        snapshot = gguf_provider.status({"gguf_enabled": True})
        self.assertEqual(snapshot["state"], "healthy")
        self.assertEqual(snapshot["roles"]["fast"]["resolved"], "Llama-3.2-3B-Instruct-Q4_K_M.gguf")
        self.assertEqual(snapshot["roles"]["planner"]["resolved"], "Qwen2.5-3B-Instruct-Q4_K_M.gguf")

    def test_low_resource_tuning_caps_context_and_threads(self):
        tuning = gguf_provider.tuning_for_host({"gguf_ctx": 8192, "gguf_threads": 8})
        # Sandbox and 8 GB hosts both land on the low-resource profile cap.
        self.assertLessEqual(tuning["n_ctx"], 4096)
        self.assertLessEqual(tuning["n_threads"], 8)
        low = gguf_provider.tuning_for_host({"gguf_ctx": 2048, "gguf_threads": 4})
        self.assertEqual(low["n_ctx"], 2048)

    def test_ram_fit_reports_8gb_target(self):
        fit = gguf_provider.ram_fit(2 * 1024 ** 3)
        self.assertIn("fits_8gb", fit)
        self.assertIsNotNone(fit["resident_mb"])
        self.assertGreater(fit["resident_mb"], 2048)

    def test_prompt_templates_differ_per_family(self):
        llama = gguf_provider.build_prompt("llama", "sys", "{}")
        qwen = gguf_provider.build_prompt("qwen", "sys", "{}")
        self.assertIn("start_header_id", llama)
        self.assertIn("im_start", qwen)
        self.assertNotEqual(llama, qwen)


class FuzzyRoutingTests(unittest.TestCase):
    def setUp(self):
        _reset_caches()

    def tearDown(self):
        _reset_caches()

    def test_gguf_wins_when_healthy(self):
        decision = fuzzy_engine.decide([
            {"id": "gguf", "state": "healthy"},
            {"id": "ollama", "state": "healthy"},
        ], phase="plan")
        self.assertEqual(decision["winner"], "gguf")
        self.assertIn(decision["confidence"], {"high", "moderate"})
        self.assertTrue(decision["reason"])

    def test_ollama_is_secondary_when_gguf_down(self):
        decision = fuzzy_engine.decide([
            {"id": "gguf", "state": "unavailable"},
            {"id": "ollama", "state": "healthy"},
        ])
        self.assertEqual(decision["winner"], "ollama")

    def test_council_when_no_model_answers(self):
        decision = fuzzy_engine.decide([
            {"id": "gguf", "state": "unavailable"},
            {"id": "ollama", "state": "unavailable"},
        ])
        self.assertEqual(decision["winner"], "council")

    def test_slow_failing_primary_yields_to_secondary(self):
        fresh = fuzzy_engine.decide([
            {"id": "gguf", "state": "healthy"},
            {"id": "ollama", "state": "healthy"},
        ])
        self.assertEqual(fresh["winner"], "gguf")
        for _ in range(4):
            fuzzy_engine.record_latency("gguf", None, False)
        fuzzy_engine.record_latency("ollama", 900, True)
        degraded = fuzzy_engine.decide([
            {"id": "gguf", "state": "healthy"},
            {"id": "ollama", "state": "healthy"},
        ])
        gguf_score = next(item for item in degraded["ranking"] if item["provider"] == "gguf")["score"]
        ollama_score = next(item for item in degraded["ranking"] if item["provider"] == "ollama")["score"]
        self.assertLess(gguf_score, ollama_score)
        self.assertEqual(degraded["winner"], "ollama")

    def test_latency_membership_boundaries(self):
        fast = fuzzy_engine.latency_membership(500)
        self.assertEqual(fast["fast"], 1.0)
        slow = fuzzy_engine.latency_membership(30000)
        self.assertEqual(slow["slow"], 1.0)


class AdviseProviderChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.models = Path(self.tmp.name) / "models"
        self.models.mkdir()
        self._old_env = os.environ.get("VORTEX_MODELS_DIR")
        os.environ["VORTEX_MODELS_DIR"] = str(self.models)
        _reset_caches()

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("VORTEX_MODELS_DIR", None)
        else:
            os.environ["VORTEX_MODELS_DIR"] = self._old_env
        gguf_provider.set_test_engine(None)
        gguf_provider.unload()
        _reset_caches()
        self.tmp.cleanup()

    def _advice(self, text: str) -> str:
        return json.dumps({
            "fact_summary": text, "meaning": "Only supplied evidence was used.",
            "unknowns": "No broader conclusion.", "next_steps": ["Review timeline."],
            "caution": "Advisory only.", "status_alignment": "observed-success"})

    def test_advise_prefers_gguf_primary(self):
        from backend.models.router import advise

        _write_gguf(self.models / "Llama-3.2-3B-Instruct-Q4_K_M.gguf")
        _write_gguf(self.models / "Qwen2.5-3B-Instruct-Q4_K_M.gguf")
        gguf_provider.set_test_engine(lambda entry, system, user: self._advice(f"GGUF {entry['name']} reviewed evidence."))
        result = advise(
            "Explain this result",
            plan={"kind": "identity", "risk": "low", "status": "planned", "commands": []},
            operation={"status": "succeeded", "commands": [{"display": "whoami", "status": "succeeded", "stdout": "user"}]},
            phase="interpret",
            settings={"ai_enabled": True, "offline": True, "ollama_endpoint": "http://127.0.0.1:9"},
        )
        self.assertEqual(result["state"], "responded")
        self.assertEqual(result["provider"], "gguf")
        self.assertEqual(result["route"]["selected"][0]["provider"], "gguf")
        self.assertIn("GGUF", result["message"])

    def test_advise_unavailable_without_any_provider(self):
        from backend.models.router import advise

        result = advise(
            "Explain this result",
            plan={"kind": "identity", "risk": "low", "status": "planned", "commands": []},
            phase="conversation",
            settings={"ai_enabled": True, "offline": True, "ollama_endpoint": "http://127.0.0.1:9"},
        )
        self.assertEqual(result["state"], "unavailable")

    def test_model_status_reports_providers_and_fuzzy(self):
        from backend.models.router import model_status

        _write_gguf(self.models / "Llama-3.2-3B-Instruct-Q4_K_M.gguf")
        gguf_provider.set_test_engine(lambda entry, system, user: self._advice("x"))
        status = model_status({"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9"})
        self.assertIn("gguf", status)
        self.assertIn("providers", status)
        self.assertIn("fuzzy", status)
        self.assertEqual(status["selected"], "local-gguf")
        self.assertEqual(status["fuzzy"]["winner"], "gguf")

    def test_choose_route_tags_providers(self):
        from backend.models.router import choose_route, model_status

        _write_gguf(self.models / "Llama-3.2-3B-Instruct-Q4_K_M.gguf")
        gguf_provider.set_test_engine(lambda entry, system, user: self._advice("x"))
        status = model_status({"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9"})
        route = choose_route("hello", phase="conversation", settings={"model_max_parallel": 1}, status=status)
        self.assertEqual(route["selected"][0]["provider"], "gguf")
        self.assertEqual(route["primary_provider"], "gguf")


class AssistCoverageTests(unittest.TestCase):
    def test_registry_lists_every_assisted_function(self):
        from backend.models.assist import ASSISTED_FUNCTIONS, coverage

        for name in ("plan", "palette", "search", "dashboard", "assets", "health",
                     "deps", "replan", "report", "memory", "engagement", "session",
                     "interpret", "verify", "error", "explain"):
            self.assertIn(name, ASSISTED_FUNCTIONS)
        self.assertGreaterEqual(coverage()["count"], 16)

    def test_assist_is_honest_without_models(self):
        from backend.models.assist import assist

        result = assist("search", "find whoami", settings={"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9"})
        self.assertFalse(result["available"])
        self.assertEqual(result["hint"], "")
        self.assertEqual(result["function"], "search")

    def test_assist_never_raises(self):
        from backend.models.assist import assist

        with patch("backend.models.router.advise", side_effect=RuntimeError("boom")):
            result = assist("dashboard", "summarize", settings={})
        self.assertFalse(result["available"])

    def test_assist_returns_hint_with_test_engine(self):
        from backend.models.assist import assist

        tmp = tempfile.TemporaryDirectory()
        try:
            models = Path(tmp.name) / "models"
            models.mkdir()
            _write_gguf(models / "Llama-3.2-3B-Instruct-Q4_K_M.gguf")
            old = os.environ.get("VORTEX_MODELS_DIR")
            os.environ["VORTEX_MODELS_DIR"] = str(models)
            _reset_caches()
            gguf_provider.set_test_engine(lambda entry, system, user: json.dumps({
                "fact_summary": "Two tools installed.", "meaning": "", "unknowns": "",
                "next_steps": [], "caution": "", "status_alignment": "observed-success"}))
            try:
                result = assist("dashboard", "summarize", settings={"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9"})
            finally:
                if old is None:
                    os.environ.pop("VORTEX_MODELS_DIR", None)
                else:
                    os.environ["VORTEX_MODELS_DIR"] = old
                gguf_provider.set_test_engine(None)
                _reset_caches()
            self.assertTrue(result["available"])
            self.assertIn("Two tools", result["hint"])
            self.assertEqual(result["provider"], "gguf")
        finally:
            tmp.cleanup()


class UpstreamTrackingTests(unittest.TestCase):
    def test_table_links_every_agent_without_invention(self):
        from backend.agents.upstream import table

        data = table()
        self.assertGreaterEqual(len(data), 10)
        for agent_id in ("cai", "strix", "nebula", "pentestgpt", "hexstrike", "pentagi"):
            self.assertTrue(data[agent_id]["repository"].startswith("https://github.com/"))
        # HALO and DarkMoon have no verified repository — reported, not invented.
        self.assertEqual(data["halo"]["repository"], "")
        self.assertEqual(data["darkmoon"]["repository"], "")
        self.assertEqual(data["halo"]["sync_state"], "unverified")
        self.assertEqual(data["darkmoon"]["sync_state"], "unverified")

    def test_refresh_refuses_offline_without_network(self):
        from backend.agents.upstream import refresh

        with patch("urllib.request.urlopen", side_effect=AssertionError("no network in offline mode")):
            result = refresh(offline=True)
        self.assertEqual(result["state"], "offline")

    def test_refresh_checks_github_head(self):
        from backend.agents import upstream as upstream_module

        class FakeResponse:
            def __init__(self):
                self.payload = json.dumps([{"sha": "abc123", "commit": {"message": "feat: x"}}]).encode()

            def geturl(self):
                return "https://api.github.com/repos/aliasrobotics/cai/commits?per_page=1"

            def read(self, _size=-1):
                return self.payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            result = upstream_module.refresh("cai")
        self.assertEqual(result["state"], "checked")
        self.assertEqual(result["checked"][0]["sha"], "abc123")
        self.assertEqual(upstream_module.table()["cai"]["sync_state"], "checked")

    def test_council_discover_carries_upstream(self):
        from backend.agents.council import discover

        agents = {item["id"]: item for item in discover()}
        self.assertIn("upstream", agents["cai"])
        self.assertEqual(agents["cai"]["upstream"]["repository"], "https://github.com/aliasrobotics/cai")
        self.assertIsNone(agents["halo"]["upstream"]["repository"])

    def test_install_proposal_includes_reviewed_guide(self):
        from backend.agents.install import proposal

        result = proposal("nebula")
        self.assertFalse(result["auto_install"])
        self.assertTrue(any("nebula" in str(line).lower() for line in result["commands"]))
        self.assertIn("sync_state", result)


class FunctionAssistanceWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        old_data = os.environ.get("VORTEX_DATA_DIR")
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        self._old_data = old_data
        from backend.vortex_backend import Store
        from backend.workspace import Workspace

        self.store = Store(Path(self.tmp.name) / "vortex.db")
        self.workspace = Workspace(self.store)
        _reset_caches()

    def tearDown(self):
        if self._old_data is None:
            os.environ.pop("VORTEX_DATA_DIR", None)
        else:
            os.environ["VORTEX_DATA_DIR"] = self._old_data
        _reset_caches()
        self.tmp.cleanup()

    def test_search_and_graph_carry_ai_hint(self):
        search = self.workspace.search_all("whoami")
        self.assertIn("ai_hint", search)
        self.assertIn(search["ai_hint"]["available"], {True, False})
        graph = self.workspace.asset_graph(50)
        self.assertIn("ai_hint", graph)

    def test_dashboard_and_health_carry_ai_hint(self):
        from backend import dashboard
        from backend.health import collect

        dash = dashboard.collect(self.store, self.workspace, {"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9"})
        self.assertIn("ai_hint", dash)
        health = collect(self.store, None, {"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9"})
        self.assertIn("ai_hint", health)

    def test_palette_plan_and_query_carry_ai_hint(self):
        from backend.palette import run_palette

        planned = run_palette(self.store, self.workspace, "/whoami", settings={"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9"})
        self.assertIn("ai_hint", planned)
        queried = run_palette(self.store, self.workspace, "/history", settings={"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9"})
        self.assertIn("ai_hint", queried)

    def test_replan_verdict_carries_ai_hint(self):
        from backend.replan import evaluate_objective

        verdict = evaluate_objective(
            {"kind": "identity", "status": "planned", "request": "whoami"},
            {"status": "succeeded", "commands": []},
            {"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9"},
        )
        self.assertTrue(verdict["achieved"])
        self.assertIn("ai_hint", verdict)

    def test_dependency_proposal_carries_ai_hint(self):
        from backend.dependencies import proposal_for

        proposal = proposal_for("runtime:ollama", {"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9"})
        self.assertIn("ai_hint", proposal)

    def test_gguf_activation_persists_role(self):
        from backend.config import load_settings
        from backend.models.manager import activate_gguf

        models = Path(self.tmp.name) / "models"
        models.mkdir(exist_ok=True)
        _write_gguf(models / "Llama-3.2-3B-Instruct-Q4_K_M.gguf")
        old = os.environ.get("VORTEX_MODELS_DIR")
        os.environ["VORTEX_MODELS_DIR"] = str(models)
        _reset_caches()
        try:
            preference = activate_gguf("Llama-3.2-3B-Instruct-Q4_K_M.gguf", "fast")
            self.assertEqual(preference["state"], "active")
            self.assertEqual(preference["provider"], "gguf")
            self.assertEqual(load_settings()["gguf_fast"], "Llama-3.2-3B-Instruct-Q4_K_M.gguf")
            with self.assertRaises(ValueError):
                activate_gguf("../escape.gguf", "fast")
            with self.assertRaises(ValueError):
                activate_gguf("Llama-3.2-3B-Instruct-Q4_K_M.gguf", "nope")
        finally:
            if old is None:
                os.environ.pop("VORTEX_MODELS_DIR", None)
            else:
                os.environ["VORTEX_MODELS_DIR"] = old
            _reset_caches()


if __name__ == "__main__":
    unittest.main()
