import io
import json
import os
import tempfile
import time
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from backend.dependencies import inventory, proposal_for
from backend.health import setup_checks
from backend.models.router import advise, ollama_status
from backend.vortex_backend import ExecutionManager, Store, build_plan
from backend.workspace import Workspace


class LocalAiRouterTests(unittest.TestCase):
    def setUp(self):
        try:
            from backend.models import router as backend_router
            backend_router._STATUS_CACHE.update({"at": 0.0, "key": None, "value": None})
        except Exception:
            pass
        try:
            from models import router as bare_router
            bare_router._STATUS_CACHE.update({"at": 0.0, "key": None, "value": None})
        except Exception:
            pass

    def test_ollama_status_detects_candidate_models_and_resources(self):
        def fake_json(endpoint, path, **_kwargs):
            if path == "/api/version":
                return {"version": "0.9.6"}
            if path == "/api/tags":
                return {
                    "models": [
                        {"name": "phi4-mini:3.8b", "size": 1},
                        {"name": "qwen3:4b", "size": 2},
                        {"name": "llama3.2:3b", "size": 3},
                    ]
                }
            raise AssertionError(path)

        with patch("backend.models.router._ollama_json", side_effect=fake_json):
            status = ollama_status("http://127.0.0.1:11434")
        self.assertEqual(status["state"], "healthy")
        self.assertEqual(status["version"], "0.9.6")
        self.assertIn("phi4-mini:3.8b", status["installed_candidates"])
        self.assertIn("qwen3:4b", status["installed_candidates"])
        self.assertEqual(status["recommended"]["planner"], "qwen3:4b")
        self.assertIn("mode", status["resources"])
        self.assertIn("context_tokens", status["resources"])

    def test_advise_synthesizes_multi_model_responses_without_execution_claims(self):
        model_state = {
            "enabled": True,
            "local": {
                "state": "healthy",
                "endpoint": "http://127.0.0.1:11434",
                "installed_candidates": ["phi4-mini:3.8b", "qwen3:4b"],
                "models": [{"name": "phi4-mini:3.8b"}, {"name": "qwen3:4b"}],
                "resources": {"mode": "balanced", "max_parallel_models": 2, "context_tokens": 2048},
                "recommended": {"fast": "phi4-mini:3.8b", "planner": "qwen3:4b", "analysis": "phi4-mini:3.8b", "specialist": "qwen3:4b"},
            },
        }

        def fake_consult(model, role, request, evidence, route, settings, endpoint):
            self.assertEqual(endpoint, "http://127.0.0.1:11434")
            self.assertEqual(route["phase"], "interpret")
            return {
                "state": "responded",
                "role": role,
                "model": model,
                "fact_summary": "Observed command output shows a bounded local diagnostic.",
                "meaning": "The evidence indicates success and no claim beyond the observed command output.",
                "unknowns": "No broader security conclusion is justified from this single command.",
                "next_steps": ["Review the command timeline."],
                "caution": "Do not treat a passing command as proof of system safety.",
                "status_alignment": "observed-success",
                "latency_ms": 5,
            }

        operation = {
            "status": "succeeded",
            "commands": [{"display": "whoami", "status": "succeeded", "stdout": "user\n", "stderr": "", "exit_code": 0}],
            "artifacts": [],
            "analysis": {"fact": "Observed output exists."},
        }
        with patch("backend.models.router.model_status", return_value=model_state), patch("backend.models.router._consult_one", side_effect=fake_consult):
            result = advise("Explain this result", plan={"kind": "identity", "risk": "low", "status": "planned", "commands": []}, operation=operation, phase="interpret", settings={})
        self.assertEqual(result["state"], "responded")
        self.assertEqual(result["fuzzy"]["confidence"], "high")
        self.assertEqual(len(result["responses"]), 2)
        self.assertIn("Observed command output", result["message"])
        self.assertIn("Unknowns:", result["message"])

    def test_dependency_inventory_includes_wordlist_dataset_proposal(self):
        with patch("backend.security.scanners.discover_wordlist", return_value={"state": "absent", "path": None, "message": "No reviewed wordlist was found."}):
            data = inventory()
            item = next(row for row in data["items"] if row["id"] == "data:wordlists")
            proposal = proposal_for("data:wordlists")
        self.assertEqual(item["apt_package"], "seclists")
        self.assertFalse(item["installed"])
        self.assertEqual(proposal["plan_request"], "install package seclists")
        self.assertIn("wordlist", proposal["message"].lower())

    def test_dependency_inventory_tracks_build_runtimes_and_model_pool(self):
        data = inventory()
        ids = {item["id"] for item in data["items"]}
        self.assertIn("runtime:nodejs", ids)
        self.assertIn("runtime:npm", ids)
        self.assertIn("runtime:ollama", ids)
        self.assertIn("data:ollama-models", ids)

    def test_ollama_runtime_proposal_guides_manual_bootstrap(self):
        fake_item = {
            "id": "runtime:ollama",
            "kind": "runtime",
            "name": "ollama",
            "title": "Ollama (loopback)",
            "installed": False,
            "binary_installed": True,
            "endpoint": "http://127.0.0.1:11434",
            "missing_required_candidates": ["phi4-mini:3.8b", "qwen3:4b", "llama3.2:3b"],
            "missing_optional_candidates": ["gemma3:4b"],
        }
        with patch("backend.dependencies.inventory", return_value={"items": [fake_item]}):
            proposal = proposal_for("runtime:ollama")
        self.assertFalse(proposal["auto_install"])
        self.assertIn("ollama serve", proposal["commands"])
        self.assertIn("ollama pull phi4-mini:3.8b", proposal["commands"])
        self.assertIn("loopback", proposal["message"].lower())

    def test_ollama_model_pool_proposal_lists_missing_models(self):
        fake_item = {
            "id": "data:ollama-models",
            "kind": "dataset",
            "name": "ollama-model-pool",
            "title": "Local AI model pool",
            "installed": False,
            "runtime_present": True,
            "runtime_api_state": "healthy",
            "endpoint": "http://127.0.0.1:11434",
            "installed_candidates": ["phi4-mini:3.8b"],
            "missing_required_candidates": ["qwen3:4b", "llama3.2:3b"],
            "missing_optional_candidates": ["gemma3:4b"],
        }
        with patch("backend.dependencies.inventory", return_value={"items": [fake_item]}):
            proposal = proposal_for("data:ollama-models")
        self.assertIn("ollama pull qwen3:4b", proposal["commands"])
        self.assertIn("ollama pull llama3.2:3b", proposal["commands"])
        self.assertIn("core local model pool is incomplete", proposal["message"].lower())

    def test_blocked_runtime_is_reported_as_present_not_missing(self):
        def fake_probe(name):
            if name == "node":
                return {"state": "blocked", "path": "/usr/local/bin/node", "version": None, "security_flags": ["writable-parent-directory"]}
            if name == "npm":
                return {"state": "blocked", "path": "/usr/local/bin/npm", "version": None, "security_flags": ["writable-parent-directory"]}
            return {"state": "absent", "path": None, "version": None, "security_flags": []}

        model = {"local": {"state": "unavailable", "endpoint": "http://127.0.0.1:11434", "installed_candidates": [], "missing_candidates": ["phi4-mini:3.8b"]}}
        with patch("backend.dependencies._probe_name", side_effect=fake_probe), \
             patch("backend.models.router.model_status", return_value=model), \
             patch("backend.agents.council.discover", return_value=[]), \
             patch("backend.sandbox.isolation_status", return_value={"state": "unavailable", "available": False, "path": None, "version": None}), \
             patch("backend.security.scanners.discover_wordlist", return_value={"state": "absent", "path": None, "message": "missing"}):
            data = inventory()
            node = next(item for item in data["items"] if item["id"] == "runtime:nodejs")
            proposal = proposal_for("runtime:nodejs")
        self.assertTrue(node["installed"])
        self.assertEqual(node["state"], "blocked")
        self.assertEqual(node["security_flags"], ["writable-parent-directory"])
        self.assertIn("flagged", proposal["message"].lower())

    def test_dependency_inventory_uses_saved_ollama_settings(self):
        observed = {}

        def fake_model_status(settings=None):
            observed["settings"] = settings
            return {
                "local": {
                    "state": "healthy",
                    "endpoint": settings.get("ollama_endpoint"),
                    "installed_candidates": ["phi4-mini:3.8b", "qwen3:4b", "llama3.2:3b"],
                    "message": "stub ready",
                }
            }

        with ExitStack() as stack:
            stack.enter_context(patch("backend.dependencies._load_runtime_settings", return_value={"ollama_endpoint": "http://127.0.0.1:11459"}))
            stack.enter_context(patch("backend.dependencies._probe_name", return_value={"state": "absent", "path": None, "version": None, "security_flags": []}))
            stack.enter_context(patch("backend.models.router.model_status", side_effect=fake_model_status))
            try:
                import models.router  # type: ignore
            except Exception:
                pass
            else:
                stack.enter_context(patch("models.router.model_status", side_effect=fake_model_status))
            stack.enter_context(patch("backend.agents.council.discover", return_value=[]))
            stack.enter_context(patch("backend.sandbox.isolation_status", return_value={"state": "unavailable", "available": False, "path": None, "version": None}))
            stack.enter_context(patch("backend.security.scanners.discover_wordlist", return_value={"state": "absent", "path": None, "message": "missing"}))
            data = inventory()
        runtime = next(item for item in data["items"] if item["id"] == "runtime:ollama")
        self.assertEqual(observed["settings"]["ollama_endpoint"], "http://127.0.0.1:11459")
        self.assertEqual(runtime["endpoint"], "http://127.0.0.1:11459")


class LocalAiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        self.store = Store(Path(self.tmp.name) / "vortex.db")
        self.workspace = Workspace(self.store)
        self.cwd = self.tmp.name
        try:
            from backend.models import router as backend_router
            backend_router._STATUS_CACHE.update({"at": 0.0, "key": None, "value": None})
        except Exception:
            pass
        try:
            from models import router as bare_router
            bare_router._STATUS_CACHE.update({"at": 0.0, "key": None, "value": None})
        except Exception:
            pass

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)

    def test_run_turn_and_execution_store_local_ai_annotations(self):
        from backend.orchestrate import run_turn

        def fake_advise(request, **kwargs):
            phase = kwargs.get("phase")
            if phase == "plan":
                return {
                    "state": "responded",
                    "message": "Plan stays low risk and read only.",
                    "route": {"selected": [{"role": "primary", "model": "phi4-mini:3.8b"}]},
                    "fuzzy": {"confidence": "moderate", "agreement": "single-model", "evidence_basis": "plan-only"},
                    "synthesis": {"fact_summary": "Plan stays low risk and read only.", "meaning": "", "unknowns": "", "next_steps": []},
                }
            return {
                "state": "responded",
                "message": "Observed evidence matches the executed command only.",
                "route": {"selected": [{"role": "primary", "model": "phi4-mini:3.8b"}]},
                "fuzzy": {"confidence": "moderate", "agreement": "single-model", "evidence_basis": "observed"},
                "synthesis": {"fact_summary": "Observed evidence matches the executed command only.", "meaning": "", "unknowns": "No broader security conclusion follows.", "next_steps": []},
            }

        with patch("backend.models.router.advise", side_effect=fake_advise), patch("models.router.advise", side_effect=fake_advise):
            result = run_turn(
                self.store,
                self.workspace,
                ExecutionManager(self.store),
                "whoami",
                cwd=self.cwd,
                engagement_id=None,
                conversation_id=None,
                settings={"profile": "standard", "auto_low_risk": True, "offline": False},
            )
            self.assertEqual(result["local_ai"]["state"], "responded")
            self.assertTrue(any(worker["id"].startswith("local-model:") for worker in result["plan"]["workers"]))
            self.assertIn("Local AI:", result["message"]["content"])
            operation_id = result["operation"]["id"]
            for _ in range(200):
                current = self.store.get_operation(operation_id)
                if current and current.get("status") not in {"started", "running"}:
                    break
                time.sleep(0.02)
        current = self.store.get_operation(operation_id)
        self.assertEqual(current["analysis"]["local_ai"]["state"], "responded")
        self.assertTrue(any(worker["id"].startswith("local-model:") for worker in current["analysis"]["workers"]))

    def test_execution_uses_per_turn_ollama_settings_snapshot(self):
        from backend.orchestrate import run_turn

        def fake_ollama_json(endpoint, path, **kwargs):
            self.assertEqual(endpoint, "http://127.0.0.1:11449")
            if path == "/api/version":
                return {"version": "stub-0.0.1"}
            if path == "/api/tags":
                return {"models": [{"name": "phi4-mini:3.8b"}, {"name": "qwen3:4b"}]}
            if path == "/api/chat":
                model = (kwargs.get("body") or {}).get("model")
                payload = {
                    "state": "responded",
                    "fact_summary": f"Stub advisory from {model}.",
                    "meaning": "Observed output stayed within the reviewed command.",
                    "unknowns": "No broader conclusion is justified.",
                    "next_steps": ["Review the command timeline."],
                    "caution": "Advisory commentary does not authorize execution.",
                    "status_alignment": "observed-success",
                }
                return {"message": {"content": json.dumps(payload)}}
            raise AssertionError(path)

        with patch("backend.models.router._ollama_json", side_effect=fake_ollama_json), patch("models.router._ollama_json", side_effect=fake_ollama_json):
            result = run_turn(
                self.store,
                self.workspace,
                ExecutionManager(self.store),
                "whoami",
                cwd=self.cwd,
                engagement_id=None,
                conversation_id=None,
                settings={"profile": "standard", "auto_low_risk": True, "offline": False, "ollama_endpoint": "http://127.0.0.1:11449"},
            )
            operation_id = result["operation"]["id"]
            for _ in range(200):
                current = self.store.get_operation(operation_id)
                if current and current.get("status") not in {"started", "running"}:
                    break
                time.sleep(0.02)
        self.assertEqual(result["local_ai"]["state"], "responded")
        self.assertEqual(current["analysis"]["local_ai"]["state"], "responded")
        self.assertEqual(current["analysis"]["local_ai"]["endpoint"], "http://127.0.0.1:11449")

    def test_setup_checks_include_build_and_local_ai_steps(self):
        setup = setup_checks(self.store, {"profile": "safe"})
        ids = [step["id"] for step in setup["steps"]]
        self.assertIn("nodejs", ids)
        self.assertIn("npm", ids)
        self.assertIn("ollama", ids)
        self.assertIn("model_pool", ids)

    def test_cli_run_existing_plan_executes_saved_plan(self):
        from cli.vortex import main

        plan = build_plan(self.store, "whoami", self.cwd)
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--json", "run", plan["id"], "--yes"])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["plan"]["id"], plan["id"])
        self.assertEqual(payload["operation"]["status"], "succeeded")
