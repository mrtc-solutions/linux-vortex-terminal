import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from backend.agents.council import critic, discover, consult
from backend.reports.engine import render, to_pdf
from backend.security.guardian import evaluate, recompute_risk
from backend.vortex_backend import ExecutionManager, Store, build_plan, command_spec, plan_digest
from backend.workspace import Workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        self.store = Store(Path(self.tmp.name) / "vortex.db")
        self.workspace = Workspace(self.store)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)

    def test_setup_checks_are_live(self):
        from backend.health import setup_checks
        setup = setup_checks(self.store, {"profile": "safe", "first_run_complete": False})
        self.assertEqual(setup["product"], "VORTEX")
        ids = [step["id"] for step in setup["steps"]]
        self.assertIn("linux", ids)
        self.assertIn("database", ids)
        linux = next(step for step in setup["steps"] if step["id"] == "linux")
        self.assertTrue(linux["ok"])
        db = next(step for step in setup["steps"] if step["id"] == "database")
        self.assertTrue(db["ok"])
        self.assertFalse(setup["first_run_complete"])

    def test_os_release_and_lscpu_plans(self):
        distro = build_plan(self.store, "what distro is this", self.tmp.name)
        self.assertEqual(distro["kind"], "os_release")
        self.assertIn(distro["status"], ("planned", "unavailable"))
        if distro["status"] == "planned":
            self.assertEqual(distro["commands"][0]["argv"], ["cat", "/etc/os-release"])
        cpu = build_plan(self.store, "lscpu", self.tmp.name)
        self.assertEqual(cpu["kind"], "cpu")

    def test_conversation_search_matches_messages(self):
        convo = self.workspace.create_conversation("alpha")
        self.workspace.add_message(convo["id"], "user", "unique-needle-vortex-xyz")
        found = self.workspace.list_conversations("unique-needle-vortex-xyz")
        self.assertTrue(any(item["id"] == convo["id"] for item in found))

    def test_clock_and_interface_plans(self):
        clock = build_plan(self.store, "what time is it", self.tmp.name)
        self.assertEqual(clock["kind"], "clock")
        self.assertIn(clock["status"], ("planned", "unavailable"))
        if clock["status"] == "planned":
            self.assertEqual(clock["commands"][0]["adapter_id"], "linux.system.clock")
        nets = build_plan(self.store, "show ip address", self.tmp.name)
        self.assertEqual(nets["kind"], "network_interfaces")
        if nets["status"] == "planned":
            self.assertEqual(nets["commands"][0]["argv"][:3], ["ip", "-br", "addr"])

    def test_executor_finishes_linked_task(self):
        from backend.orchestrate import run_turn
        manager = ExecutionManager(self.store)
        manager.workspace = self.workspace
        result = run_turn(self.store, self.workspace, manager, "whoami", cwd=self.tmp.name, engagement_id=None, conversation_id=None, settings={"profile": "standard", "auto_low_risk": True, "offline": False})
        op_id = result["operation"]["id"]
        task = result["task"]
        for _ in range(200):
            operation = self.store.get_operation(op_id)
            task = self.workspace.get_task(result["task"]["id"])
            if operation and operation["status"] not in ("started", "running") and task and task["state"] not in ("EXECUTING", "OBSERVING", "PLANNING"):
                break
            time.sleep(0.02)
        self.assertEqual(task["state"], "COMPLETED")
        self.assertTrue(self.workspace.get_report_by_operation(op_id))
        exported = self.workspace.export_conversation(result["conversation"]["id"])
        self.assertGreaterEqual(len(exported["messages"]), 2)
        self.assertTrue(any("observed" in (m["content"] or "").lower() or "whoami" in (m["content"] or "").lower() or "completed" in (m["content"] or "").lower() for m in exported["messages"]))

    def test_excluded_targets_block_guardian(self):
        from backend.security.guardian import evaluate
        engagement = {"id": "e1", "status": "active", "targets": ["lab.example.test"], "excluded_targets": ["lab.example.test"]}
        plan = {"kind": "authorized_engagement", "status": "planned", "scope": {"targets": ["lab.example.test"]}, "commands": [{"adapter_id": "security.http.headers", "risk": "high", "privilege": "user", "network_class": "outbound-read", "display": "curl https://lab.example.test/"}]}
        decision = evaluate(plan, {"auto_low_risk": True}, engagement)
        self.assertTrue(decision["blocked"])

    def test_agent_install_is_proposal_only(self):
        from backend.agents.install import proposal
        item = proposal("cai")
        self.assertFalse(item["auto_install"])
        self.assertIn(item["state"], ("missing", "installed"))

    def test_operations_for_engagement_filters(self):
        from backend.vortex_backend import now_iso
        engagement = {
            "id": "eng-filter", "created_at": now_iso(), "expires_at": "2099-08-25T00:00:00+00:00",
            "name": "lab", "authorization": "t", "targets": ["lab.example.test"],
            "classes": ["reconnaissance"], "status": "active",
        }
        self.store.create_engagement(engagement)
        in_scope = build_plan(self.store, "whoami", self.tmp.name, "eng-filter")
        out_scope = build_plan(self.store, "whoami", self.tmp.name)
        self.store.save_operation({
            "id": "op-in", "plan_id": in_scope["id"], "started_at": now_iso(), "ended_at": now_iso(),
            "status": "succeeded", "commands": [], "workers": [], "source": "deterministic",
        })
        self.store.save_operation({
            "id": "op-out", "plan_id": out_scope["id"], "started_at": now_iso(), "ended_at": now_iso(),
            "status": "succeeded", "commands": [], "workers": [], "source": "deterministic",
        })
        matched = self.workspace.operations_for_engagement("eng-filter")
        self.assertEqual([item["id"] for item in matched], ["op-in"])

    def test_cli_tasks_pause_and_reject(self):
        from cli import vortex as vortex_cli
        self.assertEqual(vortex_cli.main(["--json", "tasks", "pause"]), 1)
        plan = build_plan(self.store, "whoami", self.tmp.name)
        task = self.workspace.create_task("whoami")
        self.workspace.update_task(task["id"], plan_id=plan["id"], state="WAITING_FOR_APPROVAL")
        code = vortex_cli.main(["--json", "tasks", "pause", task["id"]])
        self.assertEqual(code, 0)
        self.assertEqual(self.workspace.get_task(task["id"])["state"], "PAUSED")
        code = vortex_cli.main(["--json", "tasks", "reject", task["id"]])
        self.assertEqual(code, 0)
        self.assertEqual(self.workspace.get_task(task["id"])["state"], "CANCELLED")

    def test_core_tools_map_to_apt_packages(self):
        from backend.dependencies import APT_PACKAGES, proposal_for
        self.assertEqual(APT_PACKAGES["ss"], "iproute2")
        item = proposal_for("tool:nmap")
        if not item.get("installed"):
            self.assertEqual(item.get("method"), "apt")
            self.assertFalse(item.get("auto_install"))

    def test_pause_and_reject_helpers(self):
        plan = build_plan(self.store, "whoami", self.tmp.name)
        task = self.workspace.create_task("whoami")
        self.workspace.update_task(task["id"], plan_id=plan["id"], state="WAITING_FOR_APPROVAL")
        paused = self.workspace.pause_task(task["id"])
        self.assertEqual(paused["state"], "PAUSED")
        rejected = self.workspace.reject_task_plan(plan["id"], task["id"])
        self.assertTrue(rejected["rejected"])
        self.assertEqual(rejected["task"]["state"], "CANCELLED")

    def test_reject_plan_and_secret_slots(self):
        from backend.secretstore import put, status
        from backend.tools.router import route
        plan = build_plan(self.store, "whoami", self.tmp.name)
        self.assertTrue(self.workspace.reject_plan(plan["id"]))
        stored = self.store.get_plan(plan["id"])
        self.assertEqual(stored["status"], "rejected")
        info = put("ollama_token", "sk-test-not-for-logs")
        self.assertIn("ollama_token", info["configured"])
        self.assertIsNone(info["values"])
        self.assertIsNone(status()["values"])
        self.assertEqual(route("check disk space")["adapter_id"], "linux.filesystem.usage")

    def test_task_ids_are_sequential(self):
        first = self.workspace.create_task("one")
        second = self.workspace.create_task("two")
        self.assertTrue(first["id"].startswith("VTX-"))
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["state"], "CREATED")

    def test_conversation_edit_branches(self):
        convo = self.workspace.create_conversation("orig")
        msg = self.workspace.add_message(convo["id"], "user", "Check Docker.")
        self.workspace.add_message(convo["id"], "vortex", "planned")
        branch = self.workspace.edit_and_branch(convo["id"], msg["id"], "Check Docker and fix it if needed.")
        self.assertEqual(branch["parent_id"], convo["id"])
        self.assertEqual(branch["version"], 2)
        original = self.workspace.list_messages(convo["id"])
        self.assertEqual(original[0]["content"], "Check Docker.")
        branched = self.workspace.list_messages(branch["id"])
        self.assertEqual(branched[0]["content"], "Check Docker and fix it if needed.")

    def test_guardian_is_independent_and_blocks_high_risk(self):
        plan = build_plan(self.store, "system health", self.tmp.name)
        decision = evaluate(plan, {"profile": "safe", "auto_low_risk": False})
        self.assertEqual(decision["authority"], "vortex-guardian")
        self.assertTrue(decision["independent_of_model"])
        self.assertTrue(decision["requires_approval"])
        auto = evaluate(plan, {"profile": "standard", "auto_low_risk": True})
        self.assertEqual(auto["decision"], "auto")
        self.assertFalse(auto["requires_approval"])
        fake = {"commands": [{"adapter_id": "security.nmap.discovery", "risk": "low", "privilege": "user", "network_class": "outbound-read", "display": "nmap"}]}
        self.assertEqual(recompute_risk(fake["commands"]), "high")
        blocked = evaluate({"commands": [{"adapter_id": "linux.system.health", "risk": "low", "privilege": "user", "network_class": "no-network", "display": "rm -rf /"}]}, {"auto_low_risk": True})
        self.assertTrue(blocked["blocked"])

    def test_identity_plan_is_real_and_low_risk(self):
        plan = build_plan(self.store, "whoami", self.tmp.name)
        self.assertEqual(plan["kind"], "identity")
        self.assertEqual(plan["status"], "planned")
        self.assertTrue(plan["commands"])
        self.assertEqual(plan["commands"][0]["adapter_id"], "linux.system.identity")

    def test_agents_never_fabricate_success(self):
        items = discover()
        self.assertEqual(len(items), 9)
        for item in items:
            self.assertIn(item["status"], {"missing", "installed"})
            if not item["health"]["healthy"]:
                self.assertEqual(item["status"], "missing")
                self.assertIn("UNAVAILABLE", item["health"]["message"])
        plan = {"kind": "authorized_engagement", "commands": [{"display": "nmap"}]}
        result = consult(plan, {"id": "VTX-test"})
        self.assertTrue(result["critic"]["verdict"] in {"uncertain", "advisory_only"})
        for row in result["consultations"]:
            self.assertNotEqual(row.get("state"), "succeeded")
            self.assertIsNone(row.get("result"))

    def test_critic_prefers_insufficient_evidence(self):
        review = critic({"commands": [{"display": "uname"}]}, [])
        self.assertEqual(review["verdict"], "uncertain")
        self.assertEqual(review["evidence"], "insufficient")

    def test_reports_contain_observed_data(self):
        operation = {
            "id": "op-1", "plan_id": "plan-1", "status": "succeeded",
            "started_at": "2026-08-25T00:00:00+00:00", "ended_at": "2026-08-25T00:00:01+00:00",
            "commands": [{"display": "/bin/echo hello", "status": "succeeded", "exit_code": 0, "signal": None, "evidence_digest": "abc", "stdout": "hello\n", "stderr": ""}],
            "analysis": {"fact": "1 real command(s) reached an observed terminal outcome.", "inference": "observations", "unknown": "limited"},
        }
        md, _, _ = render("md", operation, {"request": "echo"}, {"id": "VTX-2026-000001"})
        self.assertIn(b"hello", md)
        self.assertIn(b"VTX-2026-000001", md)
        html, _, _ = render("html", operation)
        self.assertIn(b"hello", html)
        payload, _, _ = render("json", operation)
        self.assertEqual(json.loads(payload)["operation"]["status"], "succeeded")
        pdf = to_pdf(operation)
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertIn(b"hello", pdf)

    def test_procedure_learning_from_validated_success(self):
        task = self.workspace.create_task("system health")
        self.workspace.update_task(task["id"], state="COMPLETED", result={"kind": "linux.system.health", "commands": ["uname -a", "uptime"]})
        self.workspace.record_experience(self.workspace.get_task(task["id"]), "succeeded", validated=True)
        procedures = self.workspace.list_procedures()
        self.assertTrue(procedures)
        self.assertEqual(procedures[0]["steps"][0], "uname -a")

    def test_low_risk_auto_execute_runs_real_command(self):
        from backend.orchestrate import run_turn
        result = run_turn(self.store, self.workspace, ExecutionManager(self.store), "whoami", cwd=self.tmp.name, engagement_id=None, conversation_id=None, settings={"profile": "standard", "auto_low_risk": True, "offline": False})
        self.assertTrue(result["auto_executed"])
        self.assertEqual(result["guardian"]["decision"], "auto")
        op_id = result["operation"]["id"]
        for _ in range(150):
            operation = self.store.get_operation(op_id)
            if operation and operation["status"] not in ("started", "running"):
                break
            time.sleep(0.02)
        self.assertEqual(operation["status"], "succeeded")
        self.assertTrue((operation["commands"][0].get("stdout") or "").strip())

    def test_stop_all_cancels_running_operation(self):
        from backend.orchestrate import stop_all
        cwd = Path(self.tmp.name)
        spec = command_spec("/bin/sleep", ["/bin/sleep", "8"], cwd, timeout=30)
        plan = {
            "schema_version": 1, "id": "plan-stop", "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2099-08-25T00:00:00+00:00", "request": "stop test", "cwd": str(cwd),
            "status": "planned", "kind": "test", "risk": "low", "authorization": "local",
            "commands": [spec], "notes": [], "missing_tools": [], "scope": {"cwd": str(cwd)},
            "workers": [], "approval_required": True, "approval_phrase": "APPROVE", "source": "deterministic",
            "policy_version": "safe-v1", "knowledge_version": "builtin-v1", "approval_token": "stop-token",
        }
        plan["digest"] = plan_digest(plan)
        self.store.save_plan(plan)
        manager = ExecutionManager(self.store)
        op = manager.start(plan, True, "stop-token")
        time.sleep(0.05)
        class DummySessions:
            def list(self): return []
            def kill(self, _id): return False
        stop_all(manager, DummySessions(), self.workspace)
        for _ in range(150):
            result = self.store.get_operation(op["id"])
            if result and result["status"] not in ("started", "running"):
                break
            time.sleep(0.02)
        self.assertEqual(result["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
