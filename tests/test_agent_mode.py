"""Agent Mode: goal-directed think/plan/Guardian/execute/observe runs."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from backend import agent_mode
from backend import vortex_backend as vtx_backend
from backend.models.router import advise as _real_advise  # noqa: F401 (documents stubbed seam)
from backend.orchestrate import run_turn as real_run_turn
from backend.replan import evaluate_objective as real_evaluate
from backend.vortex_backend import ExecutionManager, SessionManager, Store, VortexHandler
from backend.workspace import Workspace

AUTO_SETTINGS = {"profile": "standard", "auto_low_risk": True, "offline": False}
SAFE_SETTINGS = {"profile": "safe", "offline": False}


def _healthy_status(settings=None):
    return {
        "enabled": True,
        "local": {"state": "unavailable", "reason": "stub"},
        "gguf": {"state": "unavailable", "reason": "stub"},
        "llamafile": {"state": "healthy", "reason": ""},
    }


def _dark_status(settings=None):
    return {
        "enabled": True,
        "local": {"state": "unavailable", "reason": "stub offline"},
        "gguf": {"state": "unavailable", "reason": "stub offline"},
        "llamafile": {"state": "unavailable", "reason": "stub offline"},
    }


def _advise_stub(next_steps_per_call, state="responded"):
    calls = []

    def advise(request, *, plan=None, operation=None, phase="conversation", settings=None):
        calls.append(request)
        steps = next_steps_per_call[len(calls) - 1] if len(calls) <= len(next_steps_per_call) else []
        return {
            "state": state,
            "provider": "llamafile",
            "route": {"primary": "stub-model", "requested_primary": "stub-model"},
            "synthesis": {
                "fact_summary": f"stub thought {len(calls)}",
                "meaning": "",
                "unknowns": "",
                "next_steps": steps,
                "caution": "",
                "status_alignment": "unknown",
            },
            "message": "",
        }

    advise.calls = calls
    return advise


def _deps_for(advise=None, model_status=None, evaluate=None):
    return SimpleNamespace(
        advise=advise or _advise_stub([[]]),
        model_status=model_status or _healthy_status,
        run_turn=real_run_turn,
        evaluate_objective=evaluate or real_evaluate,
        load_settings=lambda: dict(SAFE_SETTINGS),
    )


def _wait_run(store, run_id, timeout=90):
    deadline = time.monotonic() + timeout
    run = None
    while time.monotonic() < deadline:
        run = agent_mode.get_run(store, run_id)
        if run and run["status"] == "finished":
            return run
        time.sleep(0.2)
    return agent_mode.get_run(store, run_id)


def _wait_status(store, run_id, status, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = agent_mode.get_run(store, run_id)
        if run and run["status"] == status:
            return run
        if run and run["status"] == "finished":
            return run
        time.sleep(0.2)
    return agent_mode.get_run(store, run_id)


class AgentModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        self.store = Store(Path(self.tmp.name) / "vortex.db")
        self.workspace = Workspace(self.store)
        self.executor = ExecutionManager(self.store)
        self.executor.workspace = self.workspace
        self._saved_deps = agent_mode._DEPS
        agent_mode._DEPS = _deps_for()
        self._runs: list[str] = []

    def tearDown(self):
        for run_id in self._runs:
            try:
                agent_mode.stop_run(self.store, self.executor, run_id)
            except Exception:
                pass
        agent_mode._DEPS = self._saved_deps
        try:
            self.executor.shutdown()
        except Exception:
            pass
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)

    def _start(self, goal, **kwargs):
        kwargs.setdefault("settings", dict(AUTO_SETTINGS))
        result = agent_mode.start_run(self.store, self.workspace, self.executor, goal, **kwargs)
        self._runs.append(result["run"]["id"])
        return result

    def test_preflight_healthy_names_llamafile_first(self):
        preflight = agent_mode.model_preflight(dict(AUTO_SETTINGS))
        self.assertTrue(preflight["ok"])
        self.assertIn("llamafile", preflight["healthy"])
        self.assertIn("llamafile", preflight["message"])

    def test_preflight_dark_lists_download_guidance(self):
        agent_mode._DEPS = _deps_for(model_status=_dark_status)
        preflight = agent_mode.model_preflight(dict(AUTO_SETTINGS))
        self.assertFalse(preflight["ok"])
        self.assertEqual(preflight["open_view"], "models")
        actions = " ".join(item["action"] for item in preflight["guidance"])
        self.assertIn("Models view", actions)
        self.assertIn("llamafile", actions)
        self.assertIn("GGUF", actions)
        self.assertIn("Ollama", actions)

    def test_start_rejects_empty_goal(self):
        with self.assertRaises(ValueError):
            agent_mode.start_run(self.store, self.workspace, self.executor, "   ", settings=dict(AUTO_SETTINGS))

    def test_run_without_model_records_honest_refusal(self):
        agent_mode._DEPS = _deps_for(model_status=_dark_status)
        result = self._start("show my username")
        run = result["run"]
        self.assertEqual(run["status"], "finished")
        self.assertEqual(run["summary"]["outcome"], "needs_model")
        kinds = [event["kind"] for event in agent_mode.events_since(self.store, run["id"], 0)["events"]]
        self.assertEqual(kinds, ["run_started", "finished"])
        finished = agent_mode.events_since(self.store, run["id"], 0)["events"][-1]["payload"]
        self.assertTrue(finished["guidance"])
        self.assertEqual(finished["open_view"], "models")

    def test_auto_run_achieves_real_identity_goal(self):
        result = self._start("show my username", max_steps=3)
        run_id = result["run"]["id"]
        run = _wait_run(self.store, run_id)
        self.assertEqual(run["status"], "finished")
        self.assertEqual(run["summary"]["outcome"], "achieved", run["summary"])
        data = agent_mode.events_since(self.store, run_id, 0)
        kinds = [event["kind"] for event in data["events"]]
        for expected in ("run_started", "think", "step_planned", "guardian", "step_started", "step_finished", "verdict", "finished"):
            self.assertIn(expected, kinds)
        think = next(event for event in data["events"] if event["kind"] == "think")
        self.assertEqual(think["payload"]["provider"], "llamafile")
        finished_step = next(event for event in data["events"] if event["kind"] == "step_finished")
        self.assertEqual(finished_step["payload"]["status"], "succeeded")
        # Real execution: the identity command really ran and produced output.
        outputs = "".join((cmd.get("stdout_tail") or "") for cmd in finished_step["payload"]["commands"])
        self.assertTrue(outputs.strip(), "the operation must carry real command output")

    def test_pause_requires_exact_plan_approval_then_resumes(self):
        result = self._start("show my username", max_steps=3, settings=dict(SAFE_SETTINGS))
        run_id = result["run"]["id"]
        paused = _wait_status(self.store, run_id, "awaiting_approval")
        self.assertEqual(paused["status"], "awaiting_approval")
        pending = paused["config"]["pending_plan_id"]
        self.assertTrue(pending)
        with self.assertRaises(ValueError):
            agent_mode.approve_run(self.store, self.workspace, self.executor, run_id, "0" * 32, True)
        with self.assertRaises(ValueError):
            agent_mode.approve_run(self.store, self.workspace, self.executor, run_id, pending, False)
        approved = agent_mode.approve_run(self.store, self.workspace, self.executor, run_id, pending, True)
        self.assertEqual(approved["run"]["status"], "running")
        run = _wait_run(self.store, run_id)
        self.assertEqual(run["summary"]["outcome"], "achieved", run["summary"])
        kinds = [event["kind"] for event in agent_mode.events_since(self.store, run_id, 0)["events"]]
        self.assertIn("approved", kinds)
        self.assertIn("resumed", kinds)

    def test_stop_parked_run_finishes_stopped(self):
        result = self._start("show my username", settings=dict(SAFE_SETTINGS))
        run_id = result["run"]["id"]
        paused = _wait_status(self.store, run_id, "awaiting_approval")
        self.assertEqual(paused["status"], "awaiting_approval")
        stopped = agent_mode.stop_run(self.store, self.executor, run_id)
        self.assertTrue(stopped["stopped"])
        run = agent_mode.get_run(self.store, run_id)
        self.assertEqual(run["status"], "finished")
        self.assertEqual(run["summary"]["outcome"], "stopped")

    def test_second_start_rejected_while_run_active(self):
        first = self._start("show my username", settings=dict(SAFE_SETTINGS))
        _wait_status(self.store, first["run"]["id"], "awaiting_approval")
        with self.assertRaises(RuntimeError):
            self._start("show disk usage")

    def test_repeated_plan_digest_stops_instead_of_looping(self):
        agent_mode._DEPS = _deps_for(
            advise=_advise_stub([["show my username"], ["show my username"]]),
            evaluate=lambda plan, operation, settings=None: {
                "achieved": False, "replan": False, "reason": "stub never satisfied", "next_request": None},
        )
        result = self._start("show my username", max_steps=5)
        run = _wait_run(self.store, result["run"]["id"])
        self.assertEqual(run["summary"]["outcome"], "loop_guard", run["summary"])

    def test_garbage_goal_never_parks_for_approval(self):
        # A goal that cannot plan must loop-guard on its repeated proposal,
        # never strand the run as "awaiting approval" of a dead plan.
        result = self._start("tell me a joke", max_steps=5)
        run = _wait_run(self.store, result["run"]["id"])
        self.assertEqual(run["status"], "finished")
        self.assertEqual(run["summary"]["outcome"], "loop_guard", run["summary"])
        kinds = [event["kind"] for event in agent_mode.events_since(self.store, run["id"], 0)["events"]]
        self.assertNotIn("paused", kinds)
        self.assertIn("note", kinds)

    def test_varied_garbage_exhausts_idle_rounds(self):
        agent_mode._DEPS = _deps_for(
            advise=_advise_stub([["tell me a joke"], ["reboot the machine"], ["list files | sort"]]),
            evaluate=lambda plan, operation, settings=None: {
                "achieved": False, "replan": False, "reason": "stub never satisfied", "next_request": None},
        )
        result = self._start("show my username", max_steps=5)
        run = _wait_run(self.store, result["run"]["id"])
        self.assertEqual(run["summary"]["outcome"], "unresolved", run["summary"])
        kinds = [event["kind"] for event in agent_mode.events_since(self.store, run["id"], 0)["events"]]
        self.assertNotIn("paused", kinds)

    def test_verdict_evaluated_once_per_step(self):
        calls = []
        real = real_evaluate

        def counting(plan, operation, settings=None):
            calls.append(1)
            return real(plan, operation, settings)

        agent_mode._DEPS = _deps_for(evaluate=counting)
        result = self._start("show my username", max_steps=3)
        run = _wait_run(self.store, result["run"]["id"])
        self.assertEqual(run["summary"]["outcome"], "achieved", run["summary"])
        self.assertEqual(len(calls), 1, "one executed step must evaluate the verdict exactly once")

    def test_approved_step_refused_at_execution_is_honest(self):
        from backend.vortex_backend import PolicyError
        result = self._start("show my username", settings=dict(SAFE_SETTINGS))
        run_id = result["run"]["id"]
        paused = _wait_status(self.store, run_id, "awaiting_approval")
        pending = paused["config"]["pending_plan_id"]
        original_start = self.executor.start
        calls = []

        def flaky(plan, *args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise PolicyError("fixture refusal")
            return original_start(plan, *args, **kwargs)

        self.executor.start = flaky
        try:
            agent_mode.approve_run(self.store, self.workspace, self.executor, run_id, pending, True)
            run = _wait_run(self.store, run_id)
        finally:
            self.executor.start = original_start
        self.assertEqual(run["summary"]["outcome"], "error", run["summary"])
        self.assertIn("refused at execution", run["summary"]["reason"])
        kinds = [event["kind"] for event in agent_mode.events_since(self.store, run_id, 0)["events"]]
        self.assertIn("step_refused", kinds)

    def test_events_paginate_and_reject_bad_ids(self):
        agent_mode._DEPS = _deps_for(model_status=_dark_status)
        result = self._start("show my username")
        run_id = result["run"]["id"]
        full = agent_mode.events_since(self.store, run_id, 0)
        self.assertEqual([event["seq"] for event in full["events"]], [1, 2])
        tail = agent_mode.events_since(self.store, run_id, 1)
        self.assertEqual([event["seq"] for event in tail["events"]], [2])
        self.assertIsNone(agent_mode.get_run(self.store, "not-a-run-id"))
        self.assertEqual(agent_mode.events_since(self.store, "0" * 31 + "z", 0)["events"], [])


class AgentModeHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        self._previous_config_dir = os.environ.get("VORTEX_CONFIG_DIR")
        config_dir = Path(self.tmp.name) / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        os.environ["VORTEX_CONFIG_DIR"] = str(config_dir)
        self.store = Store(Path(self.tmp.name) / "vortex.db")
        handler = VortexHandler
        handler.store = self.store
        handler.executor = ExecutionManager(self.store)
        handler.sessions = SessionManager(self.store, idle_seconds=120)
        handler.workspace = Workspace(self.store)
        handler.executor.workspace = handler.workspace
        handler.frontend = Path(__file__).resolve().parent.parent / "frontend"
        handler.token = None
        handler.allow_remote_host = False
        with handler.browser_sessions_lock:
            handler.browser_sessions.clear()
        self.handler = handler
        self.server = vtx_backend.BoundedThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self._saved_deps = agent_mode._DEPS
        agent_mode._DEPS = _deps_for()
        self._runs: list[str] = []

    def tearDown(self):
        for run_id in self._runs:
            try:
                agent_mode.stop_run(self.store, self.handler.executor, run_id)
            except Exception:
                pass
        agent_mode._DEPS = self._saved_deps
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.handler.executor.shutdown()
        self.handler.sessions.shutdown()
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)
        if self._previous_config_dir is None:
            os.environ.pop("VORTEX_CONFIG_DIR", None)
        else:
            os.environ["VORTEX_CONFIG_DIR"] = self._previous_config_dir

    def _post(self, path, body):
        request = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode() or "{}")
            except ValueError:
                return exc.code, {}

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=30) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode() or "{}")
            except ValueError:
                return exc.code, {}

    def test_agent_routes_pause_approve_and_finish_over_http(self):
        code, started = self._post("/api/agent/runs", {"goal": "show my username", "max_steps": 3})
        self.assertEqual(code, 202, started)
        run_id = started["run"]["id"]
        self._runs.append(run_id)
        # A second start collides with the parked worker.
        code, _ = self._post("/api/agent/runs", {"goal": "show disk usage"})
        self.assertEqual(code, 409)
        paused = _wait_status(self.store, run_id, "awaiting_approval")
        self.assertEqual(paused["status"], "awaiting_approval")
        pending = paused["config"]["pending_plan_id"]
        code, payload = self._get(f"/api/agent/runs/{run_id}")
        self.assertEqual(code, 200)
        self.assertTrue(payload["events"])
        code, wrong = self._post(f"/api/agent/runs/{run_id}/approve", {"plan_id": "0" * 32, "confirm": True})
        self.assertEqual(code, 422, wrong)
        code, approved = self._post(f"/api/agent/runs/{run_id}/approve", {"plan_id": pending, "confirm": True})
        self.assertEqual(code, 200, approved)
        run = _wait_run(self.store, run_id)
        self.assertEqual(run["summary"]["outcome"], "achieved", run["summary"])
        code, listed = self._get("/api/agent/runs")
        self.assertEqual(code, 200)
        self.assertTrue(any(item["id"] == run_id for item in listed["runs"]))

    def test_agent_routes_reject_unknown_runs(self):
        code, _ = self._get("/api/agent/runs/" + "f" * 32)
        self.assertEqual(code, 404)
        code, _ = self._get("/api/agent/runs/not-a-run-id")
        self.assertEqual(code, 404)
        code, _ = self._post("/api/agent/runs/" + "f" * 32 + "/approve", {"plan_id": "f" * 32, "confirm": True})
        self.assertEqual(code, 404)
        code, _ = self._post("/api/agent/runs/" + "f" * 32 + "/stop", {})
        self.assertEqual(code, 404)
        code, _ = self._post("/api/agent/runs", {"goal": "   "})
        self.assertEqual(code, 422)

    def test_agent_stream_serves_recorded_transcript(self):
        agent_mode._DEPS = _deps_for(model_status=_dark_status)
        code, started = self._post("/api/agent/runs", {"goal": "show my username"})
        self.assertEqual(code, 202, started)
        run_id = started["run"]["id"]
        self._runs.append(run_id)
        request = urllib.request.Request(self.base + f"/api/agent/runs/{run_id}/stream?since=0")
        with urllib.request.urlopen(request, timeout=30) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/event-stream", response.headers.get("Content-Type", ""))
            body = response.read().decode()
        self.assertIn("data: ", body)
        self.assertIn("needs_model", body)


if __name__ == "__main__":
    unittest.main()
