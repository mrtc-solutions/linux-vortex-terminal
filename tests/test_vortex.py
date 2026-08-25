import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from backend.vortex_backend import (
    ExecutionManager, PolicyError, Store, build_plan, command_spec,
    digest, make_analysis, normalize_target, probe_executable, plan_digest, target_in_engagement,
)


class VortexCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "vortex.db"
        self.store = Store(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_planner_is_deterministic_and_read_only(self):
        plan = build_plan(self.store, "system health", self.tmp.name)
        self.assertEqual(plan["source"], "deterministic")
        self.assertEqual(plan["status"], "planned")
        self.assertTrue(plan["commands"])
        self.assertTrue(all(";" not in c["display"] for c in plan["commands"]))
        self.assertEqual(self.store.list_history(), [])

    def test_shell_metacharacters_are_rejected(self):
        with self.assertRaises(PolicyError):
            command_spec("echo", ["echo", "hello; touch /tmp/pwned"], Path(self.tmp.name))

    def test_target_normalization_rejects_injection(self):
        self.assertEqual(normalize_target("HTTPS://LAB.EXAMPLE.TEST"), "https://lab.example.test/")
        with self.assertRaises(PolicyError):
            normalize_target("lab.example.test; curl evil.example")
        with self.assertRaises(PolicyError):
            normalize_target("https://user:password@lab.example.test")

    def test_missing_tool_never_creates_fake_evidence(self):
        plan = build_plan(self.store, "nmap the authorized lab.example.test", self.tmp.name)
        # The authorization gate runs before tool probing. Either way, an absent
        # tool cannot create an executed command or fabricated scan evidence.
        self.assertIn(plan["status"], ("clarified", "unavailable"))
        self.assertEqual(plan["commands"], [])
        if probe_executable("nmap")["state"] == "absent":
            self.assertTrue("TOOL MISSING" in " ".join(plan["notes"]) or "engagement" in " ".join(plan["notes"]))

    def test_scope_gate_rejects_out_of_scope_target(self):
        engagement = {
            "id": "eng-test", "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2099-08-25T00:00:00+00:00", "name": "lab",
            "authorization": "ticket-1", "targets": ["lab.example.test"],
            "classes": ["reconnaissance"], "status": "active",
        }
        self.store.create_engagement(engagement)
        plan = build_plan(self.store, "nmap evil.example.test", self.tmp.name, "eng-test")
        self.assertEqual(plan["status"], "rejected")
        self.assertEqual(plan["commands"], [])

    def test_audit_chain_detects_tamper(self):
        self.store.append_audit("test", {"value": "original"})
        self.assertTrue(self.store.verify_audit()["valid"])
        with self.store.connect() as db:
            db.execute("UPDATE audit_events SET payload_json='{}' WHERE event_type='test'")
        self.assertFalse(self.store.verify_audit()["valid"])

    def test_real_runner_records_observed_exit_and_redacts_output(self):
        cwd = Path(self.tmp.name)
        first = command_spec("/bin/printf", ["/bin/printf", "token=secret-value\\n"], cwd, risk="low")
        second = command_spec("/bin/false", ["/bin/false"], cwd, risk="low")
        plan = {
            "schema_version": 1, "id": "plan-run", "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2099-08-25T00:00:00+00:00", "request": "test", "cwd": str(cwd),
            "status": "planned", "kind": "test", "risk": "low", "authorization": "local",
            "commands": [first, second], "notes": [], "missing_tools": [], "scope": {"cwd": str(cwd)},
            "workers": [], "approval_required": True, "approval_phrase": "APPROVE",
            "source": "deterministic", "policy_version": "safe-v1", "knowledge_version": "builtin-v1",
            "approval_token": "token-test",
        }
        plan["digest"] = plan_digest(plan)
        self.store.save_plan(plan)
        manager = ExecutionManager(self.store)
        op = manager.start(plan, True, "token-test")
        for _ in range(100):
            result = self.store.get_operation(op["id"])
            if result and result["status"] not in ("started", "running"):
                break
            time.sleep(.02)
        result = self.store.get_operation(op["id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["commands"][1]["exit_code"], 1)
        self.assertIn("token=[REDACTED]", result["commands"][0]["stdout"])
        self.assertNotIn("secret-value", result["commands"][0]["stdout"])
        self.assertEqual(result["analysis"]["lifecycle"], "FAILED")

    def test_stored_plan_integrity_and_exact_approval_token(self):
        plan = build_plan(self.store, "system health", self.tmp.name)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.connect() as db:
                raw = json.loads(db.execute("SELECT plan_json FROM plans WHERE id=?", (plan["id"],)).fetchone()[0])
                raw["commands"][0]["argv"].append("tampered")
                db.execute("UPDATE plans SET plan_json=? WHERE id=?", (json.dumps(raw), plan["id"]))
            self.store.get_plan(plan["id"])
        # Recreate a clean store/plan for the executor assertion.
        clean = Store(Path(self.tmp.name) / "clean.db")
        plan = build_plan(clean, "system health", self.tmp.name)
        manager = ExecutionManager(clean)
        with self.assertRaises(PolicyError):
            manager.start(plan, True, None)

    def test_offline_mode_never_plans_outbound_work(self):
        plan = build_plan(self.store, "nmap lab.example.test", self.tmp.name, offline=True)
        self.assertEqual(plan["status"], "unavailable")
        self.assertEqual(plan["commands"], [])
        self.assertIn("OFFLINE", " ".join(plan["notes"]))

    def test_url_scope_keeps_path_and_explicit_port(self):
        self.assertEqual(normalize_target("https://Lab.Example.test/Admin?x=1"), "https://lab.example.test/Admin?x=1")
        engagement = {"targets": ["https://lab.example.test:8443/"], "status": "active"}
        self.assertTrue(target_in_engagement("https://lab.example.test:8443/other", engagement))
        self.assertFalse(target_in_engagement("https://lab.example.test:443/other", engagement))

    def test_output_cap_terminates_unbounded_output(self):
        if not shutil.which("yes"):
            self.skipTest("yes unavailable")
        cwd = Path(self.tmp.name)
        spec = command_spec("yes", ["yes"], cwd, timeout=5)
        spec["output_cap_bytes"] = 4096
        plan = {
            "schema_version": 1, "id": "plan-output-cap", "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2099-08-25T00:00:00+00:00", "request": "bounded output test", "cwd": str(cwd),
            "status": "planned", "kind": "test", "risk": "low", "authorization": "local",
            "commands": [spec], "notes": [], "missing_tools": [], "scope": {"cwd": str(cwd)},
            "workers": [], "approval_required": True, "approval_phrase": "APPROVE", "source": "deterministic",
            "policy_version": "safe-v1", "knowledge_version": "builtin-v1", "approval_token": "cap-token",
        }
        plan["digest"] = plan_digest(plan)
        self.store.save_plan(plan)
        op = ExecutionManager(self.store).start(plan, True, "cap-token")
        for _ in range(150):
            result = self.store.get_operation(op["id"])
            if result and result["status"] not in ("started", "running"):
                break
            time.sleep(.02)
        result = self.store.get_operation(op["id"])
        self.assertEqual(result["status"], "timed_out")
        self.assertEqual(result["commands"][0]["termination_reason"], "output_truncated")

    def test_cancellation_reaches_the_process_group(self):
        cwd = Path(self.tmp.name)
        spec = command_spec("/bin/sleep", ["/bin/sleep", "10"], cwd, timeout=30)
        plan = {
            "schema_version": 1, "id": "plan-cancel", "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2099-08-25T00:00:00+00:00", "request": "cancel test", "cwd": str(cwd),
            "status": "planned", "kind": "test", "risk": "low", "authorization": "local",
            "commands": [spec], "notes": [], "missing_tools": [], "scope": {"cwd": str(cwd)},
            "workers": [], "approval_required": True, "approval_phrase": "APPROVE", "source": "deterministic",
            "policy_version": "safe-v1", "knowledge_version": "builtin-v1", "approval_token": "cancel-token",
        }
        plan["digest"] = plan_digest(plan)
        self.store.save_plan(plan)
        manager = ExecutionManager(self.store)
        op = manager.start(plan, True, "cancel-token")
        time.sleep(.05)
        self.assertTrue(manager.cancel(op["id"]))
        for _ in range(150):
            result = self.store.get_operation(op["id"])
            if result and result["status"] not in ("started", "running"):
                break
            time.sleep(.02)
        result = self.store.get_operation(op["id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["analysis"]["lifecycle"], "CANCELLED")

    def test_analysis_does_not_invent_findings(self):
        op = {"status": "succeeded", "commands": [], "workers": []}
        analysis = make_analysis({}, op)
        self.assertIn("not a security guarantee", analysis["inference"])
        self.assertIn("No command was run", analysis["fact"])


if __name__ == "__main__":
    unittest.main()
