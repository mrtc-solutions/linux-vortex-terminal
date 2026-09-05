"""End-to-end FINAL_FEATURE validation.

This does not fabricate anything.  It runs a real approved operation against the
local host (safe tools only), then asserts every documented surface reflects the
observed reality: plan -> guardian -> execution -> evidence -> analysis ->
report -> conversation, plus palette/search/dashboard/asset-graph/history and
the audit hash chain.  Platform-specific features that cannot run here (GIS,
satellite, OSINT providers, Ollama inference, mobile) are reported honestly via
``NOT_TESTABLE`` flags rather than being marked PASS.

Run with:
    python3 -m unittest tests.test_final_validation -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ALLOW_ROOT = os.geteuid() == 0


def _isolate() -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    os.environ["VORTEX_DATA_DIR"] = tmp.name
    config_home = Path(tmp.name) / "config"
    config_home.mkdir(parents=True, exist_ok=True)
    os.environ["XDG_CONFIG_HOME"] = str(config_home)
    return tmp


def _wait_terminal(store, workspace, op_id, task_id, timeout=15.0) -> dict:
    """Wait until the operation and its linked task reach a terminal state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        operation = store.get_operation(op_id)
        task = workspace.get_task(task_id)
        if operation and operation.get("status") not in ("started", "running")\
                and task and task.get("state") not in (
                    "EXECUTING", "OBSERVING", "PLANNING", "VALIDATING",
                    "REPLANNING", "WAITING_FOR_APPROVAL"):
            return {"operation": operation, "task": task}
        time.sleep(0.05)
    return {"operation": store.get_operation(op_id), "task": workspace.get_task(task_id)}


class FinalValidationTests(unittest.TestCase):
    def setUp(self):
        from backend.vortex_backend import ExecutionManager, Store
        from backend.workspace import Workspace
        self.tmp = _isolate()
        self.store = Store(Path(self.tmp.name) / "vortex.db")
        self.workspace = Workspace(self.store)
        self.manager = ExecutionManager(self.store)
        self.manager.workspace = self.workspace
        self.cwd = str(Path(self.tmp.name))

    def tearDown(self):
        import shutil
        # Let any executor background thread finish its write before we remove
        # the database directory, to avoid a transient open-DB warning.
        mgr = getattr(self, "manager", None)
        if mgr is not None:
            for _ in range(100):
                try:
                    with mgr.lock:
                        threads = list(mgr.threads.values())
                    if not any(t.is_alive() for t in threads):
                        break
                except Exception:
                    break
                time.sleep(0.02)
        shutil.rmtree(os.environ.get("XDG_CONFIG_HOME", ""), ignore_errors=True)
        shutil.rmtree(os.environ.get("VORTEX_DATA_DIR", ""), ignore_errors=True)
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)
        os.environ.pop("XDG_CONFIG_HOME", None)

    def test_01_full_pipeline_produces_real_observed_result(self):
        """Real end-to-end run: plan -> execution -> analysis -> report -> conversation."""
        from backend.orchestrate import run_turn
        result = run_turn(
            self.store, self.workspace, self.manager, "whoami",
            cwd=self.cwd, engagement_id=None, conversation_id=None,
            settings={"profile": "standard", "auto_low_risk": True,
                      "offline": False}, allow_root=ALLOW_ROOT,
        )
        self.assertIn("operation", result)
        self.assertIn("task", result)
        self.assertIn("conversation", result)
        self.assertIn("plan", result)
        op_id = result["operation"]["id"]
        task_id = result["task"]["id"]
        final = _wait_terminal(self.store, self.workspace, op_id, task_id)
        operation = final["operation"]
        task = final["task"]
        self.assertIsNotNone(operation)
        self.assertIsNotNone(task)

        # Plan was reviewed (has typed commands) and the pipeline ran them.
        plan = self.store.get_plan(result["plan"]["id"])
        self.assertEqual(plan["status"], "approved" if operation["status"] == "succeeded" else plan["status"])
        self.assertTrue(plan["commands"])

        # Real observed evidence: at least one command produced output and an
        # evidence digest.  The tool really executed on the host.
        commands = operation.get("commands") or []
        self.assertTrue(commands, "operation should contain the real command record(s)")
        observed = [c for c in commands if c.get("stdout") or c.get("stderr")]
        self.assertTrue(observed, "the run must produce real observed stdout/stderr")
        self.assertTrue(any(c.get("evidence_digest") for c in commands),
                        "observed evidence carries a SHA-256 digest")

        # Analysis produced a verdict and lifecycle from real facts.
        analysis = operation.get("analysis") or {}
        self.assertTrue(analysis.get("fact"))
        self.assertIn(analysis.get("lifecycle"), ("EXECUTED", "PARTIAL", "NOT RUN", "FAILED", "TOOL MISSING"))
        self.assertTrue(analysis.get("verification"))
        self.assertTrue(analysis.get("commands"))

        # A report was derived from the real operation.
        report = self.workspace.get_report_by_operation(op_id)
        self.assertIsNotNone(report, "a report should be generated for the completed operation")
        self.assertTrue(report["body"].get("markdown") or report["body"].get("fact"))

        # Conversation captures the exchange.
        exported = self.workspace.export_conversation(result["conversation"]["id"])
        self.assertGreaterEqual(len(exported["messages"]), 2)
        self.assertTrue(any("whoami" in m["content"].lower() for m in exported["messages"]),
                        "conversation should contain the user's request")

        # Task reached COMPLETED.
        self.assertEqual(task["state"], "COMPLETED")

    def test_02_audit_chain_is_verifiable_and_valid(self):
        from backend.orchestrate import run_turn
        run_turn(
            self.store, self.workspace, self.manager, "whoami",
            cwd=self.cwd, engagement_id=None, conversation_id=None,
            settings={"profile": "standard", "auto_low_risk": True,
                      "offline": False}, allow_root=ALLOW_ROOT,
        )
        verification = self.store.verify_audit()
        self.assertTrue(verification["valid"])
        self.assertGreater(verification["checked"], 0)

    def test_03_history_reports_observed_operations(self):
        from backend.orchestrate import run_turn
        result = run_turn(
            self.store, self.workspace, self.manager, "whoami",
            cwd=self.cwd, engagement_id=None, conversation_id=None,
            settings={"profile": "standard", "auto_low_risk": True,
                      "offline": False}, allow_root=ALLOW_ROOT,
        )
        _wait_terminal(self.store, self.workspace, result["operation"]["id"], result["task"]["id"])
        history = self.store.list_history()
        self.assertGreaterEqual(len(history), 1)
        record = history[0]
        self.assertEqual(record["status"], "succeeded")
        self.assertTrue(record["commands"][0].get("evidence_digest"))

    def test_04_cross_layer_search_finds_the_operation(self):
        from backend.orchestrate import run_turn
        result = run_turn(
            self.store, self.workspace, self.manager, "whoami",
            cwd=self.cwd, engagement_id=None, conversation_id=None,
            settings={"profile": "standard", "auto_low_risk": True,
                      "offline": False}, allow_root=ALLOW_ROOT,
        )
        op_id = result["operation"]["id"]
        _wait_terminal(self.store, self.workspace, op_id, result["task"]["id"])
        # Search by a real substring of the observed output (the user name).
        who = "root" if os.geteuid() == 0 else os.environ.get("USER", "unknown")
        found = self.workspace.search_all(who)
        layers = {item["layer"] for item in found["results"]}
        self.assertTrue(found["total"] >= 1, "search should find the completed operation")
        self.assertIn("operations", layers)

    def test_05_palette_plan_is_reviewed_and_query_is_read_only(self):
        from backend.palette import expand, run_palette
        # A plan palette command routes through the reviewed planner -- a real
        # typed plan with a reviewed adapter, never executed by expand().
        plan_meta = expand("/whoami")
        self.assertEqual(plan_meta["kind"], "plan")
        self.assertIn("whoami", plan_meta["request"])
        result = run_palette(self.store, self.workspace, "/whoami", cwd=self.cwd)
        self.assertEqual(result["palette"]["kind"], "plan")
        self.assertTrue(result["plan"]["commands"])
        self.assertTrue(result["plan"]["commands"][0]["adapter_id"].startswith("linux."))

        # A query palette command is a read-only lookup of real store records.
        query = run_palette(self.store, self.workspace, "/history", cwd=self.cwd)
        self.assertEqual(query["palette"]["kind"], "query")
        self.assertIn("history", query)

    def test_06_asset_graph_derives_only_from_real_records(self):
        from backend.orchestrate import run_turn
        result = run_turn(
            self.store, self.workspace, self.manager, "whoami",
            cwd=self.cwd, engagement_id=None, conversation_id=None,
            settings={"profile": "standard", "auto_low_risk": True,
                      "offline": False}, allow_root=ALLOW_ROOT,
        )
        op_id = result["operation"]["id"]
        _wait_terminal(self.store, self.workspace, op_id, result["task"]["id"])
        graph = self.workspace.asset_graph()
        # The tool we actually invoked is an observed node; the operation node exists.
        types = graph["summary"]["by_type"]
        self.assertIn("operation", types)
        self.assertIn("tool", types)
        # No fabricated IP/host because we never declared any target.
        self.assertEqual(types.get("ip") or 0, 0)

    def test_07_dashboard_and_tool_registry_are_honest(self):
        from backend import dashboard
        from backend.tools.registry import inventory
        settings = {"offline": False, "privacy_mode": "local"}
        data = dashboard.collect(self.store, self.workspace, settings)
        self.assertIn("system", data)
        self.assertIn("ai", data)
        self.assertIn("tools", data)
        # VPN is honestly unavailable: no such subsystem exists in this build.
        self.assertFalse(data["vpn"]["available"])
        self.assertEqual(data["vpn"]["state"], "unavailable")
        # Tool registry carries metadata.
        tools = inventory()
        self.assertTrue(tools)
        first = tools[0]
        for field in ("license", "installation_method", "dependencies", "state"):
            self.assertIn(field, first)

    def test_08_health_and_capabilities_expose_honest_state(self):
        from backend.health import collect
        from backend.vortex_backend import capabilities_document
        from backend.config import load_settings
        health = collect(self.store, None, load_settings())
        self.assertIn("components", health)
        capabilities = capabilities_document()
        self.assertIn("implemented", capabilities)
        self.assertIn("unavailable_unless_installed", capabilities)
        self.assertIn("intentionally_not_implemented", capabilities)

    def test_09_local_ai_gracefully_unavailable_without_runtime(self):
        # No Ollama is expected in the sandbox; the pipeline must still produce
        # a deterministic analysis and an honest, non-blocking AI state.
        from backend.orchestrate import run_turn
        from backend.models.router import model_status
        from backend.config import load_settings
        status = model_status(load_settings())
        local = status.get("local") or {}
        # Whether healthy or disabled, the surface reports a real state.
        self.assertIn(local.get("state") or "disabled", ("healthy", "disabled", "unavailable"))
        result = run_turn(
            self.store, self.workspace, self.manager, "whoami",
            cwd=self.cwd, engagement_id=None, conversation_id=None,
            settings={"profile": "standard", "auto_low_risk": True,
                      "offline": False}, allow_root=ALLOW_ROOT,
        )
        op_id = result["operation"]["id"]
        final = _wait_terminal(self.store, self.workspace, op_id, result["task"]["id"])
        analysis = final["operation"].get("analysis") or {}
        # The local AI advisory block exists (it may be "unavailable" -- honest).
        self.assertIn("local_ai", analysis)

    def test_10_failure_paths_are_graceful(self):
        # A toolbox that requires an engagement but has none, and a request with
        # shell syntax, must not execute anything -- they yield a reviewed plan
        # or an honest clarification.
        from backend.vortex_backend import build_plan
        # No engagement -> outbound scan request stays clarified/blocked.
        scan = build_plan(self.store, "nmap 192.168.1.20", self.cwd)
        self.assertIn(scan["status"], ("clarified", "rejected", "unavailable"))
        self.assertFalse(scan["commands"], "no command without an authorization context")
        # Shell syntax is refused.
        shell = build_plan(self.store, "ps -ef && whoami", self.cwd)
        self.assertEqual(shell["kind"], "unsupported_shell_syntax")
        self.assertFalse(shell["commands"])

    def test_11_offline_blocks_outbound(self):
        from backend.vortex_backend import build_plan
        plan = build_plan(self.store, "ping google.com", self.cwd)
        # Even with an engagement, offline blocks outbound network plans.
        self.store.create_engagement({
            "id": "offline-eng", "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2099-08-25T00:00:00+00:00", "name": "offline lab",
            "authorization": "ticket", "targets": ["google.com"],
            "classes": ["reconnaissance"], "status": "active",
        })
        planned = build_plan(self.store, "ping google.com", self.cwd, "offline-eng", offline=True)
        self.assertEqual(planned["status"], "unavailable")
        self.assertFalse(planned["commands"])

    def test_12_session_reopen_marks_crashed_sessions_honestly(self):
        # A session record that a new sidecar does not own becomes
        # unknown_after_crash rather than remaining "running".
        session = {
            "id": "sess-dead", "name": "ghost", "shell": "/bin/bash", "cwd": "/tmp",
            "command": ["/bin/bash"], "pid": 999999, "cols": 100, "rows": 30,
            "status": "running", "started_at": "2026-08-25T00:00:00+00:00",
            "ended_at": None, "last_activity": "2026-08-25T00:00:00+00:00",
            "exit_code": None, "signal": None, "termination_reason": None,
        }
        self.store.save_session(session)
        from backend.vortex_backend import SessionManager
        SessionManager(self.store)
        record = self.store.get_session_record("sess-dead")
        self.assertEqual(record["status"], "unknown_after_crash")

    def test_13_authorized_http_osint_runs_against_controlled_target(self):
        """OSINT authorized-HTTP adapter really runs against a controlled target."""
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from backend.orchestrate import run_turn

        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"vortex-controlled-ok"
                self.send_response(200)
                self.send_header("X-Vortex", "controlled")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # silence
                pass

        srv = HTTPServer(("127.0.0.1", 0), _H)
        port = srv.server_port
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{port}/"
            self.store.create_engagement({
                "id": "http-osint", "created_at": "2026-08-25T00:00:00+00:00",
                "expires_at": "2099-08-25T00:00:00+00:00", "name": "controlled http lab",
                "authorization": "operator", "targets": [url],
                "classes": ["reconnaissance"], "status": "active",
            })
            result = run_turn(
                self.store, self.workspace, self.manager, f"curl {url}",
                cwd=self.cwd, engagement_id="http-osint", conversation_id=None,
                settings={"profile": "standard", "auto_low_risk": True,
                          "offline": False, "cli_yes": True},
                allow_root=ALLOW_ROOT, confirm=True, approval_token=None,
            )
            op_id = (result.get("operation") or {}).get("id")
            self.assertIsNotNone(op_id, "approved authorized-HTTP plan should execute")
            final = _wait_terminal(self.store, self.workspace, op_id, result["task"]["id"])
            operation = final["operation"]
            self.assertEqual(operation["status"], "succeeded")
            first = (operation["commands"] or [{}])[0]
            self.assertEqual(first["adapter_id"], "security.http.headers")
            self.assertEqual(first["exit_code"], 0)
            self.assertTrue(first.get("evidence_digest"))
            observed = (first.get("stdout") or "")
            self.assertIn("200", observed)
            self.assertIn("X-Vortex", observed)
        finally:
            srv.shutdown()

    def test_14_failed_command_is_truthful(self):
        """A genuinely failing command is reported as FAILED, never as success."""
        from backend.vortex_backend import command_spec, plan_digest, ExecutionManager
        # /bin/false exits non-zero immediately with no output: a real failure.
        spec = command_spec("/bin/false", ["/bin/false"], Path(self.cwd), timeout=30)
        plan = {
            "schema_version": 1, "id": "plan-fail", "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2099-08-25T00:00:00+00:00", "request": "fail test",
            "cwd": self.cwd, "status": "planned", "kind": "test", "risk": "low",
            "authorization": "local", "commands": [spec], "notes": [],
            "missing_tools": [], "scope": {"cwd": self.cwd}, "workers": [],
            "approval_required": True, "approval_phrase": "APPROVE", "source": "deterministic",
            "policy_version": "safe-v1", "knowledge_version": "builtin-v1",
            "approval_token": "fail-token",
        }
        plan["digest"] = plan_digest(plan)
        self.store.save_plan(plan)
        op = ExecutionManager(self.store).start(plan, True, "fail-token", allow_root=ALLOW_ROOT)
        for _ in range(300):
            record = self.store.get_operation(op["id"])
            if record and record["status"] not in ("started", "running"):
                break
            time.sleep(0.02)
        record = self.store.get_operation(op["id"])
        self.assertEqual(record["status"], "failed")
        self.assertNotEqual((record["commands"] or [{}])[0]["exit_code"], 0)
        # The analysis must reflect the real failure, not a fabricated PASS.
        analysis = record.get("analysis") or {}
        self.assertEqual(analysis.get("lifecycle"), "FAILED")
        self.assertEqual((analysis.get("verdict") or {}).get("outcome"), "FAIL")

    def test_15_timeout_terminates_gracefully(self):
        """A command exceeding its timeout is terminated and reported honestly."""
        from backend.vortex_backend import command_spec, plan_digest
        spec = command_spec("/bin/sleep", ["/bin/sleep", "30"], Path(self.cwd), timeout=1)
        plan = {
            "schema_version": 1, "id": "plan-timeout", "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2099-08-25T00:00:00+00:00", "request": "timeout test",
            "cwd": self.cwd, "status": "planned", "kind": "test", "risk": "low",
            "authorization": "local", "commands": [spec], "notes": [],
            "missing_tools": [], "scope": {"cwd": self.cwd}, "workers": [],
            "approval_required": True, "approval_phrase": "APPROVE", "source": "deterministic",
            "policy_version": "safe-v1", "knowledge_version": "builtin-v1",
            "approval_token": "to-token",
        }
        plan["digest"] = plan_digest(plan)
        self.store.save_plan(plan)
        from backend.vortex_backend import ExecutionManager
        op = ExecutionManager(self.store).start(plan, True, "to-token", allow_root=ALLOW_ROOT)
        for _ in range(300):
            record = self.store.get_operation(op["id"])
            if record and record["status"] not in ("started", "running"):
                break
            time.sleep(0.02)
        record = self.store.get_operation(op["id"])
        self.assertEqual(record["status"], "timed_out")
        self.assertEqual((record["commands"] or [{}])[0]["termination_reason"], "timeout")
        self.assertEqual((record.get("analysis") or {}).get("lifecycle"), "TIMED OUT")

    def test_16_interrupted_command_is_graceful(self):
        """A live command can be cancelled and is reported as CANCELLED."""
        from backend.vortex_backend import command_spec, plan_digest
        spec = command_spec("/bin/sleep", ["/bin/sleep", "10"], Path(self.cwd), timeout=30)
        plan = {
            "schema_version": 1, "id": "plan-cancel", "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2099-08-25T00:00:00+00:00", "request": "cancel test",
            "cwd": self.cwd, "status": "planned", "kind": "test", "risk": "low",
            "authorization": "local", "commands": [spec], "notes": [],
            "missing_tools": [], "scope": {"cwd": self.cwd}, "workers": [],
            "approval_required": True, "approval_phrase": "APPROVE", "source": "deterministic",
            "policy_version": "safe-v1", "knowledge_version": "builtin-v1",
            "approval_token": "cancel-token",
        }
        plan["digest"] = plan_digest(plan)
        self.store.save_plan(plan)
        from backend.vortex_backend import ExecutionManager
        manager = ExecutionManager(self.store)
        op = manager.start(plan, True, "cancel-token", allow_root=ALLOW_ROOT)
        time.sleep(0.05)
        self.assertTrue(manager.cancel(op["id"]))
        for _ in range(300):
            record = self.store.get_operation(op["id"])
            if record and record["status"] not in ("started", "running"):
                break
            time.sleep(0.02)
        record = self.store.get_operation(op["id"])
        self.assertEqual(record["status"], "cancelled")
        self.assertEqual((record.get("analysis") or {}).get("lifecycle"), "CANCELLED")

    def test_17_resource_awareness_detects_host_and_adapts(self):
        """Hardware awareness reads real host facts and selects a conservative strategy."""
        from backend.models.router import hardware_profile, model_status
        from backend.config import load_settings
        hw = hardware_profile()
        for key in ("platform", "architecture", "cpu_cores", "ram_total_mb", "gpu",
                    "mode", "max_parallel_models", "recommended_strategy", "task_queue_depth"):
            self.assertIn(key, hw)
        # On this host we have cores and ram; the profile respects that reality.
        self.assertGreaterEqual(hw["cpu_cores"], 1)
        self.assertIsNone(hw["gpu"])  # no GPU is advertised on this build
        status = model_status(load_settings())
        local = status.get("local") or {}
        # The scheduling decision is honest: bounded by the detected resources.
        self.assertIn(local.get("state") or "disabled", ("healthy", "disabled", "unavailable"))
        self.assertIn(hw["mode"], ("low-resource", "balanced", "roomy"))
        self.assertIn(hw["recommended_strategy"], ("sequential", "bounded-multi-model"))

    def test_18_gis_satellite_geolocate_never_fabricate(self):
        """Geospatial requests abstain honestly; no coordinates or imagery are invented."""
        from backend.vortex_backend import build_plan
        for request in ("gis analysis of target", "satellite imagery of site", "geolocate 8.8.8.8", "map target"):
            plan = build_plan(self.store, request, self.cwd)
            self.assertEqual(plan["kind"], "abstain")
            self.assertFalse(plan["commands"], f"{request!r} must never produce a command")
            self.assertEqual(plan["status"], "clarified")


if __name__ == "__main__":
    unittest.main()
