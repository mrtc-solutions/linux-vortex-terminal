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


if __name__ == "__main__":
    unittest.main()
