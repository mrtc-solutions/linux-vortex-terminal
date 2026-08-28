import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.agents.council import critic, discover, consult
from backend.reports.engine import render, to_pdf
from backend.security.guardian import evaluate, recompute_risk
from backend.vortex_backend import ExecutionManager, Store, analysis_next_steps, build_plan, cancel_task_operation, command_spec, make_analysis, plan_digest, safe_file_target, suggestion_hints
from backend.workspace import Workspace

ALLOW_ROOT = os.geteuid() == 0


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        self.store = Store(Path(self.tmp.name) / "vortex.db")
        self.workspace = Workspace(self.store)
        self.cwd = str(Path(self.tmp.name))

    def test_pass7_shell_syntax_is_rejected_but_plain_reads_route(self):
        for request in (
            "cat /etc/passwd | grep root",
            "echo hi > /tmp/x",
            "ls && whoami",
            "ls; cat /etc/passwd",
            "echo `id`",
            "echo $(id)",
        ):
            plan = build_plan(self.store, request, self.cwd)
            self.assertEqual(plan["kind"], "unsupported_shell_syntax", request)
            self.assertEqual(plan["status"], "rejected", request)
            self.assertEqual(plan["commands"], [], request)
        plain = build_plan(self.store, "cat /etc/passwd", self.cwd)
        self.assertEqual(plain["kind"], "filesystem_read")
        self.assertNotEqual(plain["status"], "rejected")

    def test_pass7_process_kill_forms_are_honest_rejections(self):
        for request in ("kill -9 1", "kill 12345", "pkill nginx", "killall nginx",
                        "kill process nginx", "stop process web"):
            plan = build_plan(self.store, request, self.cwd)
            self.assertEqual(plan["kind"], "unsupported_system_mutation", request)
            self.assertEqual(plan["status"], "rejected", request)
            self.assertEqual(plan["commands"], [], request)
            self.assertEqual(plan["risk"], "high", request)

    def test_pass7_bare_ss_routes_to_read_only_socket_plan(self):
        for request in ("ss -lntup", "ss -tulpn", "ss", "show sockets", "show listening ports"):
            plan = build_plan(self.store, request, self.cwd)
            self.assertIn(plan["kind"], ("plan", "authorized_engagement"), request)
            self.assertNotEqual(plan["status"], "rejected", request)
            if plan["status"] == "planned":
                self.assertEqual(plan["commands"][0]["executable"], "ss")
                self.assertTrue(plan["commands"][0]["privilege"] in ("user", "unknown"))
                self.assertLessEqual(plan["risk"], "low")

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

    def test_natural_language_service_and_user_routing(self):
        user = build_plan(self.store, "what is my username", self.tmp.name)
        self.assertEqual(user["kind"], "identity")
        self.assertIn(user["status"], ("planned", "unavailable"))
        service = build_plan(self.store, "show service nginx status", self.tmp.name)
        self.assertEqual(service["kind"], "plan")
        if service["status"] == "planned":
            self.assertEqual(service["commands"][0]["adapter_id"], "linux.systemd.inspect")
            self.assertIn("nginx.service", service["commands"][0]["argv"])
        running = build_plan(self.store, "check if nginx is running", self.tmp.name)
        self.assertEqual(running["kind"], "plan")
        mutation = build_plan(self.store, "restart service nginx", self.tmp.name)
        self.assertEqual(mutation["kind"], "systemd_mutation")
        if mutation["status"] == "planned":
            self.assertIn("nginx.service", mutation["commands"][-1]["argv"])
            self.assertIn("restart", mutation["commands"][-1]["argv"])

    def test_service_status_and_unit_listing_routing(self):
        service = build_plan(self.store, "is docker service active", self.tmp.name)
        self.assertEqual(service["kind"], "plan")
        if service["status"] == "planned":
            self.assertEqual(service["commands"][0]["adapter_id"], "linux.systemd.inspect")
            self.assertIn("docker.service", service["commands"][0]["argv"])
        units = build_plan(self.store, "list systemd units", self.tmp.name)
        self.assertEqual(units["kind"], "plan")
        if units["status"] == "planned":
            self.assertEqual(units["commands"][0]["adapter_id"], "linux.systemd.inspect")
            self.assertEqual(units["commands"][0]["argv"], ["systemctl", "list-units", "--type=service", "--all", "--no-pager"])
        log = build_plan(self.store, "show log for nginx", self.tmp.name)
        self.assertEqual(log["kind"], "plan")
        if log["status"] == "planned":
            self.assertEqual(log["commands"][0]["adapter_id"], "linux.systemd.inspect")
            self.assertIn("nginx.service", log["commands"][0]["argv"])
        containers = build_plan(self.store, "docker ps", self.tmp.name)
        self.assertEqual(containers["kind"], "container_inspection")

    def test_unclear_requests_return_read_only_suggestion_hints(self):
        unclear = build_plan(self.store, "make my computer faster somehow", self.tmp.name)
        self.assertIn(unclear["status"], ("clarified", "rejected", "unavailable"))
        self.assertTrue(unclear["suggestions"], "unclear plans should always carry suggestion hints")
        for hint in unclear["suggestions"]:
            self.assertIsInstance(hint, str)
            self.assertTrue(hint.strip())
        # A request already turned into a typed, executable plan must not carry
        # "try one of these" noise.
        planned = build_plan(self.store, "what user am i", self.tmp.name)
        if planned["status"] == "planned":
            self.assertEqual(planned["suggestions"], [])
        token_hits = build_plan(self.store, "what is my network doing", self.tmp.name)
        self.assertIn(token_hits["status"], ("clarified", "rejected", "unavailable"))
        self.assertIn("show listening ports", token_hits["suggestions"])

    def test_local_knowledge_is_deterministic_and_bounded(self):
        help_plan = build_plan(self.store, "help", self.tmp.name)
        self.assertTrue(help_plan["knowledge"])
        self.assertLessEqual(len(help_plan["knowledge"]), 4)
        for item in help_plan["knowledge"]:
            self.assertTrue(item["label"])
            self.assertTrue(item["examples"])
            self.assertTrue(item["adapters"])
            self.assertTrue(item["limit"])
        # A typed executable plan does not carry retrieval noise alongside the
        # reviewed command plan.
        planned = build_plan(self.store, "what user am i", self.tmp.name)
        if planned["status"] == "planned":
            self.assertEqual(planned["knowledge"], [])

    def test_analysis_next_steps_are_concrete_and_read_only(self):
        spec = command_spec("ps", ["ps", "-eo", "pid,user,pcpu,pmem,comm", "--no-headers"], Path(self.tmp.name), required="ps")
        spec["adapter_id"] = "linux.system.processes"
        plan = {
            "schema_version": 1, "id": "plan-next", "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2099-08-25T00:00:00+00:00", "request": "show processes",
            "cwd": self.tmp.name, "status": "planned", "kind": "plan", "risk": "low",
            "authorization": "local", "commands": [spec],
            "notes": [], "missing_tools": [], "scope": {"cwd": self.tmp.name},
            "workers": [], "approval_required": True, "approval_phrase": "APPROVE",
            "source": "deterministic", "policy_version": "safe-v1", "knowledge_version": "builtin-v1",
            "approval_token": "next-token",
        }
        plan["digest"] = plan_digest(plan)
        op = {"status": "succeeded", "commands": [{"status": "succeeded", "display": "ps ...", "stdout": " 1 root ..."}], "cwd": self.tmp.name, "workers": []}
        analysis = make_analysis(plan, op)
        self.assertEqual(analysis["verification"]["observed_commands"], 1)
        self.assertEqual(analysis["verification"]["total_commands"], 1)
        steps = analysis_next_steps(plan, op)
        self.assertTrue(steps)
        self.assertTrue(any(step["label"] == "process" for step in steps))
        # Follow-ups stay advisory only; no step represents a mutation.
        self.assertFalse(any(step["label"] in ("install", "remove", "restart", "stop", "start") for step in steps))
        failed = dict(op, status="failed")
        failed_steps = analysis_next_steps(plan, failed)
        self.assertTrue(any(step["label"] == "diagnose" for step in failed_steps))
        self.assertTrue(any(step["label"] == "fresh plan" for step in failed_steps))
        self.assertFalse(any(step["label"] in ("restart", "install", "remove") for step in failed_steps))

    def test_pass7_common_natural_language_phrasings_route_to_reviewed_adapters(self):
        user_phrase = build_plan(self.store, "what user am i", self.tmp.name)
        self.assertEqual(user_phrase["kind"], "identity", user_phrase["notes"])
        if user_phrase["status"] == "planned":
            self.assertEqual(user_phrase["commands"][0]["executable"], "whoami")
        host_phrase = build_plan(self.store, "what host is this", self.tmp.name)
        self.assertEqual(host_phrase["kind"], "identity", host_phrase["notes"])
        if host_phrase["status"] == "planned":
            self.assertEqual(host_phrase["commands"][0]["executable"], "hostname")
        service_logs = build_plan(self.store, "show nginx logs", self.tmp.name)
        self.assertEqual(service_logs["kind"], "plan", service_logs["notes"])
        if service_logs["status"] == "planned":
            self.assertEqual(service_logs["commands"][0]["adapter_id"], "linux.systemd.inspect")
            self.assertIn("nginx.service", service_logs["commands"][0]["argv"])
        for phrase in ("show system logs", "show systemd logs", "show all logs", "view logs"):
            generic_logs = build_plan(self.store, phrase, self.tmp.name)
            self.assertEqual(generic_logs["kind"], "plan", phrase + ": " + "; ".join(generic_logs["notes"]))
            if generic_logs["status"] == "planned":
                self.assertEqual(generic_logs["commands"][0]["adapter_id"], "linux.systemd.journal", phrase)
        ssh_config = build_plan(self.store, "test ssh connectivity to lab.example.test", self.tmp.name)
        self.assertEqual(ssh_config["kind"], "ssh_diagnostics", ssh_config["notes"])
        # Connectivity checks are engagement-gated; key assertion is that the
        # target is recognized rather than falling through as a generic abort.
        self.assertTrue(any("Provide one SSH host alias" in note for note in ssh_config["notes"]) or ssh_config["status"] in ("clarified", "rejected", "unavailable", "planned"))

    def test_ping_requires_engagement_and_plans_bounded_command(self):
        bare = build_plan(self.store, "ping google.com", self.tmp.name)
        self.assertEqual(bare["kind"], "authorized_engagement")
        self.assertEqual(bare["status"], "clarified")
        self.store.create_engagement({
            "id": "ping-eng", "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2099-08-25T00:00:00+00:00", "name": "ping lab",
            "authorization": "ticket", "targets": ["google.com"],
            "classes": ["reconnaissance"], "status": "active",
        })
        planned = build_plan(self.store, "ping google.com", self.tmp.name, "ping-eng")
        self.assertEqual(planned["status"], "planned")
        self.assertEqual(planned["commands"][0]["adapter_id"], "linux.network.ping")
        self.assertEqual(planned["commands"][0]["argv"], ["ping", "-c", "2", "-W", "2", "google.com"])

    def test_executor_finishes_linked_task(self):
        from backend.orchestrate import run_turn
        manager = ExecutionManager(self.store)
        manager.workspace = self.workspace
        result = run_turn(self.store, self.workspace, manager, "whoami", cwd=self.tmp.name, engagement_id=None, conversation_id=None, settings={"profile": "standard", "auto_low_risk": True, "offline": False}, allow_root=ALLOW_ROOT)
        op_id = result["operation"]["id"]
        task = result["task"]
        for _ in range(250):
            operation = self.store.get_operation(op_id)
            task = self.workspace.get_task(result["task"]["id"])
            report = self.workspace.get_report_by_operation(op_id)
            if operation and operation["status"] not in ("started", "running") and task and task["state"] not in ("EXECUTING", "OBSERVING", "PLANNING") and report:
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

    def test_episode_reward_is_zero_without_observed_success(self):
        from backend.episode import reward, step
        missing = {"kind": "container_diagnose", "status": "unavailable", "missing_tools": ["docker"], "request": "diagnose docker", "commands": []}
        scored = reward(missing, None)
        self.assertEqual(scored["reward"], 0.0)
        self.assertFalse(scored["achieved"])
        self.assertEqual(scored["source"], "observed-host-state")
        plan = build_plan(self.store, "whoami", self.tmp.name)
        record = step(plan, {"status": "succeeded", "commands": [{"exit_code": 0, "stdout": "user\\n"}]})
        self.assertEqual(record["evaluation"]["reward"], 1.0)
        self.assertTrue(record["observation"]["untrusted_output"])
        self.assertIn("linux.system.identity", record["observation"]["legal_adapters"])

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

    def test_cli_deps_lists_inventory(self):
        from cli import vortex as vortex_cli
        self.assertEqual(vortex_cli.main(["--json", "deps"]), 0)

    def test_cli_turn_yes_executes_with_profile(self):
        from cli import vortex as vortex_cli
        root_flag = ["--allow-root"] if ALLOW_ROOT else []
        code = vortex_cli.main(["--json", "--profile", "standard", "--yes", "--cwd", self.tmp.name, *root_flag, "turn", "whoami"])
        self.assertEqual(code, 0)
        tasks = self.workspace.list_tasks()
        self.assertTrue(tasks)
        task = tasks[0]
        self.assertTrue(task.get("operation_id"))
        for _ in range(150):
            operation = self.store.get_operation(task["operation_id"])
            if operation and operation["status"] not in ("started", "running"):
                break
            time.sleep(0.02)
        self.assertEqual(operation["status"], "succeeded")
        self.assertTrue((operation["commands"][0].get("stdout") or "").strip())

    def test_cli_turn_yes_safe_profile_still_executes(self):
        from cli import vortex as vortex_cli
        root_flag = ["--allow-root"] if ALLOW_ROOT else []
        code = vortex_cli.main(["--json", "--profile", "safe", "--yes", "--cwd", self.tmp.name, *root_flag, "turn", "whoami"])
        self.assertEqual(code, 0)
        task = self.workspace.list_tasks()[0]
        self.assertTrue(task.get("operation_id"))
        for _ in range(150):
            operation = self.store.get_operation(task["operation_id"])
            if operation and operation["status"] not in ("started", "running"):
                break
            time.sleep(0.02)
        self.assertEqual(operation["status"], "succeeded")

    def test_cli_user_install_writes_launcher(self):
        from cli.vortex import install_user
        prefix = Path(self.tmp.name) / "bin"
        result = install_user(str(prefix))
        self.assertTrue(result["ok"])
        self.assertFalse(result["auto_install_packages"])
        launcher = Path(result["path"])
        self.assertTrue(launcher.is_file())
        text = launcher.read_text(encoding="utf-8")
        self.assertIn("cli/vortex.py", text)
        self.assertNotIn("sudo", text)

    def test_reviewed_scan_builders_are_typed(self):
        from backend.security.scanners import build_scan, discover_wordlist
        nuclei = build_scan("nuclei", ["https://lab.example.test/"])
        self.assertTrue(nuclei["ok"])
        self.assertEqual(nuclei["argv"][0], "nuclei")
        self.assertIn("-ni", nuclei["argv"])
        self.assertIn("-duc", nuclei["argv"])
        nikto = build_scan("nikto", ["https://lab.example.test/"])
        self.assertEqual(nikto["argv"][:3], ["nikto", "-h", "https://lab.example.test/"])
        amass = build_scan("amass", ["lab.example.test"])
        self.assertEqual(amass["adapter_id"], "security.amass.passive")
        self.assertIn("-passive", amass["argv"])
        # The negative path must not depend on whether the test host happens to
        # have a Kali/dirb/seclists package installed under /usr/share.
        with patch("backend.security.scanners.discover_wordlist", return_value={
            "state": "absent",
            "path": None,
            "message": "No reviewed wordlist was found.",
        }):
            missing_list = build_scan("gobuster", ["https://lab.example.test/"])
        self.assertFalse(missing_list["ok"])
        wordlist = Path(self.tmp.name) / "common.txt"
        wordlist.write_text("admin\nlogin\n", encoding="utf-8")
        wordlist.chmod(0o644)
        found = discover_wordlist(f"gobuster wordlist {wordlist}")
        self.assertEqual(found["state"], "observed")
        ffuf = build_scan("ffuf", ["https://lab.example.test/"], f"ffuf wordlist {wordlist}")
        self.assertTrue(ffuf["ok"])
        self.assertEqual(ffuf["argv"][0], "ffuf")
        self.assertIn("FUZZ", ffuf["argv"][2])
        unimplemented = build_scan("msfconsole", ["https://lab.example.test/"])
        self.assertFalse(unimplemented["ok"])
        self.assertIn("NOT IMPLEMENTED", unimplemented["reason"])

    def test_aggregate_inventories_do_not_launch_version_commands(self):
        from backend.dependencies import inventory as dependency_inventory
        from backend.tools.registry import inventory as tool_inventory

        model = {"local": {"state": "unavailable", "models": [], "endpoint": "http://127.0.0.1:11434"}}
        with patch("backend.models.router.model_status", return_value=model), patch(
            "backend.vortex_backend.subprocess.run",
            side_effect=AssertionError("aggregate inventory launched a version process"),
        ) as run:
            tools = tool_inventory()
            dependencies = dependency_inventory()

        self.assertTrue(tools)
        self.assertTrue(dependencies["items"])
        run.assert_not_called()
        self.assertTrue(all(item.get("version") is None for item in tools))

    def test_expired_engagement_cannot_plan_outbound_work(self):
        from backend.vortex_backend import now_iso
        engagement = {
            "id": "expired-eng", "created_at": now_iso(), "expires_at": "2020-01-01T00:00:00+00:00",
            "name": "lab", "authorization": "t", "targets": ["https://lab.example.test"],
            "classes": ["reconnaissance"], "status": "active",
        }
        self.store.create_engagement(engagement)
        plan = build_plan(self.store, "curl https://lab.example.test", self.tmp.name, "expired-eng")
        self.assertEqual(plan["status"], "rejected")
        self.assertEqual(plan["commands"], [])
        self.assertTrue(any("expired" in note.lower() or "closed" in note.lower() for note in plan["notes"]))

    def test_unknown_engagement_cannot_plan_outbound_or_bind_local(self):
        outbound = build_plan(self.store, "curl https://lab.example.test", self.tmp.name, "does-not-exist")
        self.assertEqual(outbound["status"], "rejected")
        self.assertEqual(outbound["commands"], [])
        self.assertIsNone(outbound["engagement_id"])
        self.assertTrue(any("not found" in note.lower() for note in outbound["notes"]))
        local = build_plan(self.store, "whoami", self.tmp.name, "does-not-exist")
        self.assertEqual(local["kind"], "identity")
        self.assertIsNone(local["engagement_id"])
        self.assertEqual(local["status"], "planned")

    def test_sqlmap_and_msf_never_fabricate_a_command(self):
        sqlmap = build_plan(self.store, "sqlmap https://lab.example.test", self.tmp.name)
        self.assertEqual(sqlmap["status"], "unavailable")
        self.assertEqual(sqlmap["commands"], [])
        self.assertTrue(any("NOT IMPLEMENTED" in note for note in sqlmap["notes"]))
        msf = build_plan(self.store, "run msfconsole against lab.example.test", self.tmp.name)
        self.assertEqual(msf["status"], "unavailable")
        self.assertEqual(msf["commands"], [])

    def test_closed_engagement_cannot_plan_outbound_work(self):
        from backend.vortex_backend import now_iso
        engagement = {
            "id": "closed-eng", "created_at": now_iso(), "expires_at": "2099-08-25T00:00:00+00:00",
            "name": "lab", "authorization": "t", "targets": ["https://lab.example.test"],
            "classes": ["reconnaissance"], "status": "active",
        }
        self.store.create_engagement(engagement)
        self.assertTrue(self.store.close_engagement("closed-eng"))
        plan = build_plan(self.store, "curl https://lab.example.test", self.tmp.name, "closed-eng")
        self.assertEqual(plan["status"], "rejected")
        self.assertEqual(plan["commands"], [])
        self.assertIsNone(plan["engagement_id"])
        self.assertTrue(any("closed" in note.lower() for note in plan["notes"]))
        local = build_plan(self.store, "whoami", self.tmp.name, "closed-eng")
        self.assertEqual(local["kind"], "identity")
        self.assertIsNone(local["engagement_id"])

    def test_http_confirm_without_token_does_not_execute(self):
        from backend.orchestrate import run_turn
        result = run_turn(
            self.store, self.workspace, ExecutionManager(self.store), "whoami",
            cwd=self.tmp.name, engagement_id=None, conversation_id=None,
            settings={"profile": "safe", "auto_low_risk": False, "offline": False},
            confirm=True, approval_token=None,
        )
        self.assertFalse(result["auto_executed"])
        self.assertIsNone(result["operation"])
        self.assertEqual(result["task"]["state"], "WAITING_FOR_APPROVAL")

    def test_scan_plan_requires_engagement_and_never_fakes_missing_tool(self):
        from backend.vortex_backend import now_iso
        bare = build_plan(self.store, "nuclei https://lab.example.test", self.tmp.name)
        self.assertEqual(bare["kind"], "authorized_engagement")
        self.assertEqual(bare["commands"], [])
        self.assertIn(bare["status"], ("clarified", "unavailable"))
        engagement = {
            "id": "scan-eng", "created_at": now_iso(), "expires_at": "2099-08-25T00:00:00+00:00",
            "name": "lab", "authorization": "t", "targets": ["https://lab.example.test"],
            "classes": ["reconnaissance"], "status": "active",
        }
        self.store.create_engagement(engagement)
        planned = build_plan(self.store, "nuclei https://lab.example.test", self.tmp.name, "scan-eng")
        if planned["status"] == "planned":
            self.assertEqual(planned["commands"][0]["adapter_id"], "security.nuclei.templates")
        else:
            self.assertEqual(planned["status"], "unavailable")
            self.assertEqual(planned["commands"], [])
            self.assertTrue(planned["missing_tools"] or any("TOOL MISSING" in note or "wordlist" in note.lower() or "nuclei" in note.lower() for note in planned["notes"]))

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

    def test_task_lifecycle_cancels_live_operation_before_reuse(self):
        calls = []
        class FakeExecutor:
            def cancel(self, operation_id):
                calls.append(operation_id)
                return True
        task = {"id": "t1", "operation_id": "op-1"}
        self.assertTrue(cancel_task_operation(FakeExecutor(), task))
        self.assertEqual(calls, ["op-1"])
        self.assertFalse(cancel_task_operation(FakeExecutor(), {"id": "t2"}))
        self.assertEqual(calls, ["op-1"])
        class BrokenExecutor:
            def cancel(self, _operation_id):
                raise RuntimeError("already gone")
        self.assertFalse(cancel_task_operation(BrokenExecutor(), task))

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

    def test_reviewed_read_only_adapters_route_instead_of_abstain(self):
        packages = build_plan(self.store, "list installed packages", self.tmp.name)
        self.assertEqual(packages["kind"], "plan")
        if packages["status"] == "planned":
            self.assertEqual(packages["commands"][0]["adapter_id"], "linux.system.packages")
        hosts = build_plan(self.store, "show file /etc/hosts", self.tmp.name)
        self.assertEqual(hosts["kind"], "filesystem_read")
        if hosts["status"] == "planned":
            self.assertEqual(hosts["commands"][0]["adapter_id"], "linux.filesystem.read")
            self.assertIn("/etc/hosts", hosts["commands"][0]["argv"])
        tree = build_plan(self.store, "show process tree", self.tmp.name)
        self.assertEqual(tree["kind"], "processes")
        self.assertEqual(tree["commands"][0]["argv"], ["ps", "-ef", "--forest"])
        storage = build_plan(self.store, "show block devices", self.tmp.name)
        self.assertEqual(storage["kind"], "plan")
        if storage["status"] == "planned":
            self.assertEqual(storage["commands"][0]["adapter_id"], "linux.system.storage")
        routes = build_plan(self.store, "show route table", self.tmp.name)
        self.assertEqual(routes["kind"], "plan")
        if routes["status"] == "planned":
            self.assertEqual(routes["commands"][0]["argv"], ["ip", "route", "show"])
        self.assertIsNone(safe_file_target("/etc/shadow"))
        fw = evaluate({
            "commands": [{"adapter_id": "linux.network.firewall", "risk": "low", "privilege": "user", "network_class": "no-network", "display": "nft list ruleset", "source": "deterministic"}],
        }, {"auto_low_risk": True})
        self.assertFalse(fw["blocked"])

    def test_pass6_deterministic_routing_and_honest_rejections(self):
        # Previously these phrases abstained or routed to the wrong adapter.
        services = build_plan(self.store, "show running services", self.tmp.name)
        self.assertEqual(services["kind"], "plan")
        if services["status"] == "planned":
            self.assertEqual(services["commands"][0]["adapter_id"], "linux.systemd.inspect")
        disk = build_plan(self.store, "df -h", self.tmp.name)
        self.assertEqual(disk["kind"], "plan")
        if disk["status"] == "planned":
            self.assertEqual(disk["commands"][0]["adapter_id"], "linux.filesystem.usage")
            self.assertIn("df", disk["commands"][0]["executable"])
        reachable = build_plan(self.store, "is target.test up", self.tmp.name)
        self.assertEqual(reachable["kind"], "authorized_engagement")
        self.assertNotEqual(reachable["kind"], "plan")
        container = build_plan(self.store, "remove container web", self.tmp.name)
        self.assertEqual(container["kind"], "container_mutation")
        self.assertEqual(container["status"], "clarified")
        mutation = build_plan(self.store, "block port 22", self.tmp.name)
        self.assertEqual(mutation["kind"], "unsupported_system_mutation")
        self.assertEqual(mutation["status"], "rejected")
        self.assertEqual(mutation["commands"], [])
        journal = build_plan(self.store, "show syslog", self.tmp.name)
        self.assertEqual(journal["kind"], "plan")
        if journal["status"] == "planned":
            self.assertEqual(journal["commands"][0]["adapter_id"], "linux.systemd.journal")
        remotes = build_plan(self.store, "show git remotes", self.tmp.name)
        self.assertEqual(remotes["kind"], "plan")
        if remotes["status"] == "planned":
            self.assertIn("git", remotes["commands"][0]["argv"])
        route = build_plan(self.store, "show route", self.tmp.name)
        if route["status"] == "planned":
            self.assertIn("route", route["commands"][0]["argv"])
        mounts = build_plan(self.store, "show mounts", self.tmp.name)
        self.assertEqual(mounts["kind"], "plan")
        if mounts["status"] == "planned":
            self.assertIn("findmnt", mounts["commands"][0]["executable"])
        kernel = build_plan(self.store, "show kernel modules", self.tmp.name)
        self.assertEqual(kernel["kind"], "plan")
        self.assertNotEqual(kernel["kind"], "os_release")
        pci = build_plan(self.store, "show pci devices", self.tmp.name)
        self.assertEqual(pci["kind"], "plan")
        self.assertNotEqual(pci["kind"], "abstain")
        listing = build_plan(self.store, "show /var/log", self.tmp.name)
        self.assertEqual(listing["kind"], "filesystem_list")
        if listing["status"] == "planned":
            self.assertEqual(listing["commands"][0]["adapter_id"], "linux.filesystem.list")
        mutation2 = build_plan(self.store, "create file", self.tmp.name)
        self.assertEqual(mutation2["kind"], "filesystem_mutation")
        self.assertEqual(mutation2["status"], "rejected")
        apt_update = build_plan(self.store, "apt-get update", self.tmp.name)
        self.assertEqual(apt_update["kind"], "package_index_update")
        config = build_plan(self.store, "show nginx config", self.tmp.name)
        self.assertEqual(config["kind"], "config_file_request")
        pid_proc = build_plan(self.store, "show process 1", self.tmp.name)
        self.assertEqual(pid_proc["kind"], "processes")
        if pid_proc["status"] == "planned":
            self.assertEqual(pid_proc["commands"][0]["argv"], ["ps", "-p", "1", "-o", "pid,user,pcpu,pmem,comm"])
        login = build_plan(self.store, "who is logged in", self.tmp.name)
        self.assertEqual(login["kind"], "plan")
        if login["status"] == "planned":
            self.assertEqual(login["commands"][0]["adapter_id"], "linux.system.login")
        self.assertEqual(build_plan(self.store, "stop process 1234", self.tmp.name)["kind"], "unsupported_system_mutation")
        # A bare FQDN with a service-like word is a reachability question, not a systemd unit.
        fqdn = build_plan(self.store, "is web.online running", self.tmp.name)
        self.assertEqual(fqdn["kind"], "authorized_engagement")
        self.assertNotEqual(fqdn["kind"], "plan")
        self.assertEqual(build_plan(self.store, "is nginx running", self.tmp.name)["kind"], "plan")

    def test_agents_never_fabricate_success(self):
        items = discover()
        self.assertGreaterEqual(len(items), 10)
        local = next(item for item in items if item["id"] == "vortex-local")
        self.assertTrue(local["health"]["healthy"])
        externals = [item for item in items if item["id"] != "vortex-local"]
        self.assertEqual(len(externals), 9)
        for item in externals:
            self.assertIn(item["status"], {"missing", "installed"})
            if not item["health"]["healthy"]:
                self.assertEqual(item["status"], "missing")
                self.assertIn("UNAVAILABLE", item["health"]["message"])
        plan = {"kind": "authorized_engagement", "commands": [{"display": "nmap"}]}
        result = consult(plan, {"id": "VTX-test"})
        self.assertTrue(result["critic"]["verdict"] in {"uncertain", "advisory_only"})
        self.assertIn("vortex-local", result["selected"])
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
        result = run_turn(self.store, self.workspace, ExecutionManager(self.store), "whoami", cwd=self.tmp.name, engagement_id=None, conversation_id=None, settings={"profile": "standard", "auto_low_risk": True, "offline": False}, allow_root=ALLOW_ROOT)
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
        op = manager.start(plan, True, "stop-token", allow_root=ALLOW_ROOT)
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
