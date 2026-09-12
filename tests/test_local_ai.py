import io
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from backend.dependencies import custom_package_proposal, inventory, proposal_for
from backend.health import setup_checks
from backend.models import router
from backend.models.router import advise, choose_route, ollama_status
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

    def test_offline_mode_keeps_loopback_local_inference_available(self):
        def fake_json(_endpoint, path, **_kwargs):
            if path == "/api/version":
                return {"version": "test"}
            if path == "/api/tags":
                return {"models": [{"name": "phi4-mini:3.8b"}]}
            raise AssertionError(path)
        with patch("backend.models.router._ollama_json", side_effect=fake_json):
            status = router.model_status({"offline": True, "ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:11434"})
        self.assertTrue(status["offline"])
        self.assertEqual(status["local"]["state"], "healthy")
        self.assertEqual(status["selected"], "local-ollama")

    def test_exact_configured_tag_wins_before_family_fallback(self):
        self.assertEqual(router._pick_available("phi4-mini:3.8b", ["phi4-mini:latest", "phi4-mini:3.8b"]), "phi4-mini:3.8b")

    def test_variant_model_routes_to_actual_installed_tag_without_prefix_collision(self):
        def fake_json(_endpoint, path, **_kwargs):
            if path == "/api/version":
                return {"version": "test"}
            return {"models": [
                {"name": "phi4-mini:latest", "size": 1},
                {"name": "phi4-miniature:3.8b", "size": 1},
            ]}

        with patch("backend.models.router._ollama_json", side_effect=fake_json):
            local = ollama_status("http://127.0.0.1:11434")
        phi = next(item for item in local["candidates"] if item["name"] == "phi4-mini:3.8b")
        self.assertTrue(phi["installed"])
        self.assertEqual(phi["installed_name"], "phi4-mini:latest")
        self.assertTrue(any(item["name"] == "phi4-miniature:3.8b" for item in local["extras"]))
        route = choose_route(
            "interpret evidence", phase="interpret",
            settings={"model_primary": "phi4-mini:3.8b"},
            status={"enabled": True, "local": local},
        )
        self.assertEqual(route["primary"], "phi4-mini:latest")

    def test_ollama_json_rejects_oversized_response_before_reading(self):
        class Response:
            headers = {"Content-Length": str(router._MAX_OLLAMA_STATUS_BYTES + 1)}
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _size=-1):
                raise AssertionError("announced oversized response must not be read")
        class Opener:
            def open(self, _request, timeout):
                self.timeout = timeout
                return Response()
        with patch("backend.models.router._opener", return_value=Opener()):
            with self.assertRaisesRegex(ValueError, "allowed size"):
                router._ollama_json("http://127.0.0.1:11434", "/api/tags")

    def test_evidence_payload_bounds_nested_observations(self):
        payload = router.evidence_payload(
            "request",
            operation={"artifacts": [{"kind": "text", "observations": ["x" * 5000] * 20}]},
        )
        observations = payload["operation"]["artifacts"][0]["observations"]
        self.assertEqual(len(observations), 5)
        self.assertTrue(all(len(item) == 180 for item in observations))

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

    def test_failed_primary_falls_back_to_verifier_and_labels_effective_model(self):
        model_state = {
            "enabled": True,
            "local": {
                "state": "healthy", "endpoint": "http://127.0.0.1:11434",
                "installed_candidates": ["phi4-mini:3.8b", "qwen3:4b"],
                "models": [{"name": "phi4-mini:3.8b"}, {"name": "qwen3:4b"}],
                "resources": {"mode": "balanced", "max_parallel_models": 2, "context_tokens": 2048},
                "recommended": {"analysis": "phi4-mini:3.8b", "planner": "qwen3:4b", "fast": "phi4-mini:3.8b"},
            },
        }

        def consult(model, role, *_args):
            if role == "primary":
                raise TimeoutError("primary timed out")
            return {
                "state": "responded", "role": role, "model": model,
                "fact_summary": "Verifier used only observed evidence.", "meaning": "Narrow result.",
                "unknowns": "Primary response unavailable.", "next_steps": [], "caution": "Advisory only.",
                "status_alignment": "observed-success",
            }

        operation = {"status": "succeeded", "commands": [{"display": "whoami", "stdout": "user", "status": "succeeded"}]}
        with patch("backend.models.router.model_status", return_value=model_state), patch("backend.models.router._consult_one", side_effect=consult):
            result = advise("interpret", operation=operation, phase="interpret", settings={})
        self.assertEqual(result["state"], "responded")
        self.assertTrue(result["fallback"]["used"])
        self.assertEqual(result["fallback"]["selected_model"], "phi4-mini:3.8b")
        self.assertEqual(result["fallback"]["effective_model"], "qwen3:4b")
        self.assertEqual(result["synthesis"]["model"], "qwen3:4b")
        self.assertEqual(result["route"]["strategy"], "multi-parallel")

    def test_real_loopback_fake_ollama_invokes_primary_and_secondary_roles(self):
        calls = []
        calls_lock = threading.Lock()

        class FakeOllama(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def _send(self, payload):
                raw = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/api/version":
                    return self._send({"version": "fake-e2e"})
                if self.path == "/api/tags":
                    return self._send({"models": [{"name": "phi4-mini:3.8b"}, {"name": "qwen3:4b"}]})
                self.send_error(404)

            def do_POST(self):
                if self.path != "/api/chat":
                    return self.send_error(404)
                size = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(size))
                user = json.loads(request["messages"][1]["content"])
                with calls_lock:
                    calls.append((request["model"], user["role"]))
                self._send({"done": True, "message": {"content": json.dumps({
                    "fact_summary": f"{user['role']} reviewed supplied evidence.",
                    "meaning": "Only the supplied command result was considered.",
                    "unknowns": "No broader conclusion.", "next_steps": ["Review timeline."],
                    "caution": "Advisory only.", "status_alignment": "observed-success",
                })}})

        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        resources = {"mode": "balanced", "max_parallel_models": 2, "context_tokens": 2048}
        try:
            router.invalidate_status_cache()
            with patch("backend.models.router.hardware_profile", return_value=resources):
                result = advise(
                    "Interpret actual evidence", phase="interpret",
                    operation={"status": "succeeded", "commands": [{"display": "whoami", "status": "succeeded", "stdout": "user"}]},
                    settings={
                        "ai_enabled": True, "offline": True, "ollama_endpoint": endpoint,
                        "model_primary": "phi4-mini:3.8b", "model_planner": "qwen3:4b",
                        "model_fast": "phi4-mini:3.8b", "model_specialist": "qwen3:4b",
                        "model_max_parallel": 2,
                    },
                )
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)
        self.assertEqual(result["state"], "responded")
        self.assertEqual(result["route"]["strategy"], "multi-parallel")
        self.assertCountEqual(calls, [("phi4-mini:3.8b", "primary"), ("qwen3:4b", "verifier")])
        self.assertEqual(result["fuzzy"]["models_responded"], 2)
        self.assertFalse(result["fallback"]["used"])

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

    def test_custom_package_proposal_accepts_only_exact_distro_identifiers(self):
        proposal = custom_package_proposal("  RipGrep  ")
        self.assertEqual(proposal["apt_package"], "ripgrep")
        self.assertEqual(proposal["plan_request"], "install package ripgrep")
        self.assertTrue(proposal["requires_root"])
        for hostile in ("", "packages", "curl | sh", "foo bar", "../pkg", "http://example.test/x", "x;id", "a" * 129, "pkg:amd64:evil"):
            with self.subTest(hostile=hostile), self.assertRaises(ValueError):
                custom_package_proposal(hostile)
        with self.assertRaises(ValueError):
            custom_package_proposal(42)  # type: ignore[arg-type]

    def test_explicit_custom_model_preference_routes_installed_extra(self):
        status = {
            "local": {
                "state": "healthy",
                "installed_candidates": ["phi4-mini:3.8b", "qwen3:4b"],
                "extras": [{"name": "acme/custom-model:7b"}],
                "resources": {"mode": "balanced", "max_parallel_models": 2},
                "recommended": {},
            }
        }
        route = choose_route(
            "plan a safe operation", phase="plan", status=status,
            settings={"model_planner": "acme/custom-model:7b"},
        )
        self.assertEqual(route["primary"], "acme/custom-model:7b")
        self.assertEqual(route["selected"][0]["model"], "acme/custom-model:7b")


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


class SecondaryAdvisorFallbackTests(unittest.TestCase):
    """The agent council must act as the honest secondary layer when the primary
    local model is unavailable. Nothing here is fabricated model output."""

    def _unavailable_primary(self):
        return {
            "state": "unavailable",
            "provider": "ollama",
            "endpoint": "http://127.0.0.1:11434",
            "message": "Local AI unavailable: connection refused. Deterministic VORTEX planning remains authoritative.",
            "responses": [],
            "route": {"selected": []},
            "fuzzy": {"confidence": "unavailable", "agreement": "none", "models_responded": 0},
            "synthesis": {"state": "unavailable", "fact_summary": "", "meaning": "", "unknowns": "Local advisory models are unavailable.", "next_steps": [], "caution": "Deterministic planning still works.", "model": None},
        }

    def test_fallback_engages_when_primary_unavailable(self):
        from backend.agents.council import consult
        from backend.orchestrate import compose_secondary_advisory

        council = consult({"kind": "plan", "commands": [{"display": "whoami"}]}, {"id": "VTX-test"})
        result = compose_secondary_advisory(self._unavailable_primary(), council)
        self.assertEqual(result["state"], "fallback")
        self.assertEqual(result["provider"], "agent-council")
        self.assertTrue(result["fallback"]["used"])
        self.assertEqual(result["fallback"]["primary_state"], "unavailable")
        self.assertEqual(result["fallback"]["agents_checked"], 1, "only the built-in advisor ships")
        agents = result["agents"]
        self.assertEqual(len(agents), 1)
        local = next(a for a in agents if a["id"] == "vortex-local")
        self.assertTrue(local["healthy"])
        self.assertEqual(local["state"], "installed")
        for agent in agents:
            self.assertFalse(agent["fabricated"])
            self.assertTrue(agent["contribution"])
        # Only the deterministic advisor contributes substantive text.
        self.assertIn("deterministic", result["synthesis"]["caution"].lower())
        self.assertIsNone(result["synthesis"]["model"])
        self.assertIn("secondary", result["message"].lower())

    def test_fallback_lists_only_the_working_builtin_advisor(self):
        from backend.orchestrate import compose_secondary_advisory

        result = compose_secondary_advisory(self._unavailable_primary(), {"consultations": []})
        ids = [agent["id"] for agent in result["agents"]]
        self.assertEqual(ids, ["vortex-local"], "only working advisors are available")
        advisor = result["agents"][0]
        self.assertTrue(advisor["healthy"])
        self.assertEqual(advisor["state"], "installed")
        self.assertFalse(advisor["fabricated"])
        self.assertEqual(result["fallback"]["agents_missing"], 0)
        # The fallback must never claim a model produced text.
        self.assertIsNone(result["synthesis"]["model"])
        self.assertEqual(result["synthesis"]["state"], "deterministic-fallback")

    def test_no_fallback_when_primary_responded(self):
        from backend.orchestrate import compose_secondary_advisory

        primary = {
            "state": "responded",
            "provider": "ollama",
            "message": "all good",
            "route": {"selected": [{"role": "primary", "model": "phi4-mini:3.8b"}]},
            "synthesis": {"state": "responded", "fact_summary": "x"},
        }
        result = compose_secondary_advisory(primary, None)
        self.assertEqual(result["state"], "responded")
        self.assertFalse(result["fallback"]["used"])
        self.assertNotIn("agents", result)
