import http.server
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from pathlib import Path

from backend.artifacts import ArtifactError, analyze_bytes, analyze_path
from backend.vortex_backend import sanitize_pty
from backend.facts import parse_apt_preflight, parse_container_logs, parse_package_facts, parse_package_observation, parse_ssh_connection, parse_systemd_show
from backend.network import resolve_target, resolve_targets, resolution_digest
from backend import vortex_backend as vtx_backend  # noqa: E402
from backend.vortex_backend import (
    ExecutionManager, PolicyError, SessionManager, Store, build_plan, build_undo_plan, clear_probe_caches, command_spec,
    apt_tools_ready, config_root, data_root, digest, make_analysis, normalize_target, now_iso, parse_package_request, parse_systemd_mutation, probe_executable, plan_digest, runtime_root, sanitize_pty, systemd_user_bus_state, target_in_engagement, trusted_privilege_broker,
)

ALLOW_ROOT = os.geteuid() == 0


class VortexCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "vortex.db"
        self.store = Store(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cli_raw_mode_restores_terminal_after_exception(self):
        from cli import vortex as cli
        fake_stdin = type("Input", (), {"isatty": lambda self: True, "fileno": lambda self: 7})()
        attributes = [1, 2, 3]
        with patch.object(cli.sys, "stdin", fake_stdin), \
             patch.object(cli.termios, "tcgetattr", return_value=attributes), \
             patch.object(cli.tty, "setraw") as setraw, \
             patch.object(cli.termios, "tcsetattr") as restore:
            with self.assertRaisesRegex(RuntimeError, "boom"):
                with cli.raw_stdin():
                    raise RuntimeError("boom")
        setraw.assert_called_once_with(7)
        restore.assert_called_once_with(7, cli.termios.TCSADRAIN, attributes)

    def test_cli_runtime_metadata_rejects_non_loopback_and_symlink_state(self):
        from cli import vortex as cli
        runtime = Path(self.tmp.name) / "runtime-meta"
        runtime.mkdir()
        path = runtime / "sidecar.json"
        valid = {"pid": os.getpid(), "host": "127.0.0.1", "port": 4545, "token": "local-token"}
        with patch.object(cli, "runtime_root", return_value=runtime):
            path.write_text(json.dumps({**valid, "host": "attacker.example.test"}), encoding="utf-8")
            self.assertIsNone(cli.runtime_metadata())
            path.write_text(json.dumps(valid), encoding="utf-8")
            self.assertEqual(cli.runtime_metadata()["port"], 4545)
            victim = Path(self.tmp.name) / "metadata-victim"
            victim.write_text(json.dumps(valid), encoding="utf-8")
            path.unlink()
            path.symlink_to(victim)
            self.assertIsNone(cli.runtime_metadata())

    def test_cli_remote_request_rejects_non_loopback_before_network(self):
        from cli import vortex as cli
        with patch.object(cli.urllib.request, "build_opener") as opener:
            with self.assertRaisesRegex(ValueError, "loopback"):
                cli.remote_request({"host": "attacker.example.test", "port": 80}, "/api/health")
        opener.assert_not_called()

    def test_cli_remote_attach_encodes_session_and_propagates_initial_size(self):
        from cli import vortex as cli
        calls = []
        event_reads = 0

        def remote(_metadata, route, body=None):
            nonlocal event_reads
            calls.append((route, body))
            if "/events" in route:
                event_reads += 1
                if event_reads == 1:
                    return {"events": [], "session": {"status": "running"}}
                return {"events": [], "session": {"status": "succeeded", "exit_code": 0}}
            return {"ok": True}

        with patch.object(cli, "raw_stdin", return_value=nullcontext()), \
             patch.object(cli, "remote_request", side_effect=remote), \
             patch.object(cli.shutil, "get_terminal_size", return_value=SimpleNamespace(columns=132, lines=43)), \
             patch.object(cli.select, "select", return_value=([], [], [])):
            result = cli.attach_remote_session({"port": 1}, "id/with?chars")
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(all("id%2Fwith%3Fchars" in route for route, _ in calls))
        resize = next(body for route, body in calls if route.endswith("/resize"))
        self.assertEqual(resize, {"cols": 132, "rows": 43})

    def test_cli_attach_rejects_missing_session_instead_of_spinning(self):
        from cli import vortex as cli
        with patch.object(cli, "raw_stdin", return_value=nullcontext()), \
             patch.object(cli, "remote_request", return_value={"events": [], "session": None}):
            with self.assertRaisesRegex(ValueError, "session not found"):
                cli.attach_remote_session({"port": 1}, "missing")

    def test_cli_foreground_attach_resizes_once_then_returns(self):
        from cli import vortex as cli

        class Manager:
            def __init__(self):
                self.reads = 0
                self.sizes = []
            def events_since(self, _session_id, _sequence):
                self.reads += 1
                return {"events": [], "session": {"status": "running" if self.reads == 1 else "succeeded"}}
            def resize(self, session_id, cols, rows):
                self.sizes.append((session_id, cols, rows))

        manager = Manager()
        with patch.object(cli, "raw_stdin", return_value=nullcontext()), \
             patch.object(cli.shutil, "get_terminal_size", return_value=SimpleNamespace(columns=101, lines=37)), \
             patch.object(cli.select, "select", return_value=([], [], [])):
            result = cli.attach_foreground_session(manager, "session-1")
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(manager.sizes, [("session-1", 101, 37)])

    def test_sudo_invocation_is_rejected_before_opening_user_state(self):
        from cli import vortex as cli
        with patch.object(cli.os, "getuid", return_value=0), \
             patch.dict(os.environ, {"SUDO_USER": "alice"}, clear=False), \
             patch.object(cli, "Store", side_effect=AssertionError("Store must not open under sudo")) as store:
            rc = cli.main(["doctor"])
        self.assertEqual(rc, vtx_backend.EXIT_CODES["confirmation_required"])
        store.assert_not_called()

    def test_root_data_default_ignores_sudo_user_xdg_directory(self):
        root_home = Path(self.tmp.name) / "root-home"
        user_xdg = Path(self.tmp.name) / "user-data"
        user_config = Path(self.tmp.name) / "user-config"
        user_runtime = Path(self.tmp.name) / "user-runtime"
        fake_root = type("Pw", (), {"pw_dir": str(root_home)})()
        env = {"SUDO_USER": "alice", "XDG_DATA_HOME": str(user_xdg), "XDG_CONFIG_HOME": str(user_config), "XDG_RUNTIME_DIR": str(user_runtime)}
        with patch.dict(os.environ, env, clear=False), \
             patch.object(vtx_backend.os, "getuid", return_value=0), \
             patch.object(vtx_backend.pwd, "getpwuid", return_value=fake_root):
            for key in ("VORTEX_DATA_DIR", "VORTEX_CONFIG_DIR", "VORTEX_RUNTIME_DIR"):
                os.environ.pop(key, None)
            observed = data_root()
            observed_config = config_root()
            observed_runtime = runtime_root()
        self.assertEqual(observed, root_home / ".local" / "share" / "vortex")
        self.assertEqual(observed_config, root_home / ".config" / "vortex")
        self.assertEqual(observed_runtime, observed / "runtime" / "vortex")
        self.assertFalse(str(observed).startswith(str(user_xdg)))
        self.assertFalse(str(observed_config).startswith(str(user_config)))
        self.assertFalse(str(observed_runtime).startswith(str(user_runtime)))

    def test_privileged_handoff_wraps_only_root_spec_in_pinned_noninteractive_sudo(self):
        plan = build_plan(self.store, "install package git", self.tmp.name)
        if not plan.get("commands"):
            self.skipTest("apt tooling is unavailable")
        spec = next(item for item in plan["commands"] if item.get("privilege") == "root-required")
        broker = {
            "state": "installed", "realpath": "/usr/bin/sudo", "device": 1,
            "inode": 2, "owner_uid": 0, "mode": "0o4755", "sha256": "abc",
        }
        manager = ExecutionManager(self.store)
        manager.cancel_events["op"] = threading.Event()
        manager.privilege_brokers["op"] = dict(broker)
        with patch.object(vtx_backend.os, "getuid", return_value=1001), \
             patch("backend.vortex_backend.trusted_privilege_broker", return_value=dict(broker)), \
             patch("backend.vortex_backend.subprocess.Popen", side_effect=FileNotFoundError) as popen:
            record = manager._run_one(spec, "op")
        self.assertEqual(record["status"], "unavailable")
        invoked = popen.call_args.args[0]
        self.assertEqual(invoked[:3], ["/usr/bin/sudo", "-n", "--"])
        self.assertEqual(invoked[3:], [spec["executable_identity"]["realpath"], *spec["argv"][1:]])
        self.assertNotIn("sudo", record["argv"])

    def test_privileged_handoff_fails_closed_if_broker_identity_changes(self):
        plan = build_plan(self.store, "install package git", self.tmp.name)
        if not plan.get("commands"):
            self.skipTest("apt tooling is unavailable")
        spec = next(item for item in plan["commands"] if item.get("privilege") == "root-required")
        manager = ExecutionManager(self.store)
        manager.cancel_events["op"] = threading.Event()
        manager.privilege_brokers["op"] = {"state": "installed", "realpath": "/usr/bin/sudo", "sha256": "old"}
        with patch.object(vtx_backend.os, "getuid", return_value=1001), \
             patch("backend.vortex_backend.trusted_privilege_broker", return_value={"state": "installed", "realpath": "/usr/bin/sudo", "sha256": "new"}), \
             patch("backend.vortex_backend.subprocess.Popen") as popen:
            record = manager._run_one(spec, "op")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["termination_reason"], "privilege_broker_changed")
        popen.assert_not_called()

    def test_trusted_privilege_broker_is_fixed_root_owned_binary(self):
        broker = trusted_privilege_broker()
        if broker.get("state") != "installed":
            self.skipTest("sudo is unavailable")
        self.assertEqual(broker["owner_uid"], 0)
        self.assertIn(broker["realpath"], {"/usr/bin/sudo", "/bin/sudo"})
        self.assertFalse(int(broker["mode"], 8) & 0o022)
        self.assertEqual(len(broker["sha256"]), 64)

    def test_executable_probe_can_skip_version_process_explicitly(self):
        executable = Path(self.tmp.name) / "version-tool"
        executable.write_bytes(b"deterministic executable identity")
        executable.chmod(0o755)
        completed = type("Completed", (), {"stdout": "Tool test-version\n", "stderr": "", "returncode": 0})()
        catalog_entry = {str(executable): {"probe": ["--version"]}}
        with patch.dict("backend.vortex_backend.TOOL_CATALOG", catalog_entry), patch(
            "backend.vortex_backend.subprocess.run", return_value=completed
        ) as run:
            observed = probe_executable(str(executable))
        self.assertEqual(observed["version"], "Tool test-version")
        run.assert_called_once()

        with patch.dict("backend.vortex_backend.TOOL_CATALOG", catalog_entry), patch(
            "backend.vortex_backend.subprocess.run",
            side_effect=AssertionError("include_version=False launched a process"),
        ) as run:
            inventory_probe = probe_executable(str(executable), include_version=False)
        self.assertIsNone(inventory_probe["version"])
        run.assert_not_called()
        self.assertEqual(inventory_probe["sha256"], observed["sha256"])

    def test_probe_lookup_is_briefly_shared_but_can_be_cleared(self):
        clear_probe_caches()
        name = f"vortex-absent-{id(self)}"
        with patch.object(vtx_backend, "_resolve_executable_lookup", wraps=vtx_backend._resolve_executable_lookup) as resolver:
            first = probe_executable(name, include_version=False)
            second = probe_executable(name, include_version=False)
            self.assertEqual(first["state"], "absent")
            self.assertEqual(second["state"], "absent")
            self.assertEqual(resolver.call_count, 1)
        clear_probe_caches()
        with patch.object(vtx_backend, "_resolve_executable_lookup", wraps=vtx_backend._resolve_executable_lookup) as resolver:
            probe_executable(name, include_version=False)
            self.assertEqual(resolver.call_count, 1)

    def test_container_detection_never_fabricates_runtime_state(self):
        plan = build_plan(self.store, 'inspect docker containers', self.tmp.name)
        if not any(probe_executable(name)['state'] == 'installed' for name in ('docker', 'podman')):
            self.assertEqual(plan['status'], 'unavailable')
            self.assertEqual(plan['commands'], [])
            self.assertIn('TOOL MISSING', ' '.join(plan['notes']))
        else:
            self.assertEqual(plan['commands'][0]['adapter_id'], 'linux.containers.inspect')
            self.assertEqual(plan['commands'][0]['network_class'], 'loopback-only')

    def test_ssh_config_adapter_is_read_only_and_non_networking(self):
        plan = build_plan(self.store, 'show ssh config for labhost', self.tmp.name)
        self.assertEqual(plan['status'], 'planned')
        self.assertEqual(plan['kind'], 'ssh_diagnostics')
        self.assertEqual(plan['commands'][0]['adapter_id'], 'linux.ssh.config')
        argv = plan['commands'][0]['argv']
        self.assertEqual(argv[:4], ['ssh', '-F', '/dev/null', '-G'])
        self.assertIn('ProxyCommand=none', argv)
        self.assertIn('PermitLocalCommand=no', argv)
        self.assertEqual(argv[-2:], ['--', 'labhost'])
        self.assertEqual(plan['commands'][0]['network_class'], 'no-network')

    def test_external_tool_adapters_disable_ambient_command_configs(self):
        self.store.create_engagement({
            'id': 'safe-argv', 'created_at': now_iso(), 'expires_at': '2099-08-25T00:00:00+00:00',
            'name': 'local fixture', 'authorization': 'test', 'targets': ['http://127.0.0.1:9/'],
            'classes': ['reconnaissance'], 'status': 'active',
        })
        http_plan = build_plan(self.store, 'curl http://127.0.0.1:9/', self.tmp.name, 'safe-argv')
        if http_plan['status'] == 'planned':
            argv = http_plan['commands'][0]['argv']
            self.assertEqual(argv[:2], ['curl', '--disable'])
            self.assertIn('=http,https', argv)

        git_plan = build_plan(self.store, 'show git diff', self.tmp.name)
        if git_plan['status'] == 'planned':
            argv = git_plan['commands'][0]['argv']
            env = git_plan['commands'][0]['env_additions']
            self.assertIn('--no-pager', argv)
            self.assertIn('--no-replace-objects', argv)
            self.assertIn('core.hooksPath=/dev/null', argv)
            self.assertIn('core.fsmonitor=false', argv)
            self.assertIn('diff.external=', argv)
            self.assertIn('alias.diff=', argv)
            self.assertIn('--no-ext-diff', argv)
            self.assertIn('--no-textconv', argv)
            self.assertEqual(env.get('GIT_CONFIG_GLOBAL'), '/dev/null')
            self.assertEqual(env.get('GIT_CONFIG_SYSTEM'), '/dev/null')
            self.assertEqual(env.get('GIT_CONFIG_NOSYSTEM'), '1')
            self.assertEqual(env.get('GIT_ATTR_NOSYSTEM'), '1')

    def test_pty_sanitizer_keeps_sgr_and_removes_osc(self):
        value = sanitize_pty('\x1b[31mred\x1b[0m\x1b]0;malicious-title\x07\x1b[2K\n')
        self.assertIn('\x1b[31m', value)
        self.assertIn('red', value)
        self.assertNotIn('malicious-title', value)
        self.assertIn('\x1b[2K', value)

    def test_shell_integration_is_owned_and_idempotent(self):
        from cli.vortex import shell_block, shell_proposal
        current = 'export TEST=1\n'
        installed = shell_proposal('bash', current, True)
        self.assertIn(shell_block('bash'), installed)
        self.assertEqual(shell_proposal('bash', installed, True), installed)
        self.assertNotIn('# >>> vortex shell integration >>>', shell_proposal('bash', installed, False))

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

    def test_scanner_proposal_without_adapter_id_is_safe(self):
        engagement = {
            "id": "eng-scanner", "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2099-08-25T00:00:00+00:00", "name": "lab",
            "authorization": "ticket-scanner", "targets": ["lab.example.test"],
            "classes": ["reconnaissance"], "status": "active",
        }
        self.store.create_engagement(engagement)
        scanner_module = type("Scanners", (), {
            "build_scan": lambda self, tool, targets, request: {"ok": True, "argv": ["nuclei", "-u", targets[0]], "explanation": "incomplete"}
        })()
        scope_module = type("Scope", (), {"excluded": lambda self, target, item: False})()
        original_load = vtx_backend._load
        def fake_load(name):
            if name == "security.scanners":
                return scanner_module
            if name == "security.scope":
                return scope_module
            return original_load(name)
        with patch.object(vtx_backend, "_load", side_effect=fake_load), \
             patch.object(vtx_backend, "probe_executable", return_value={"state": "installed", "path": "/usr/bin/nuclei", "version": None}), \
             patch.object(vtx_backend, "resolve_targets", return_value={"state": "observed", "targets": [{"target": "lab.example.test"}]}):
            plan = build_plan(self.store, "nuclei lab.example.test", self.tmp.name, "eng-scanner")
        self.assertEqual(plan["status"], "unavailable")
        self.assertEqual(plan["commands"], [])
        self.assertTrue(any("incomplete proposal" in note for note in plan["notes"]))

    def test_refresh_flag_distinguishes_cached_and_fresh_probes(self):
        clear_probe_caches()
        calls = {"tools": 0, "doctor": 0, "deps": 0}
        def fresh_tools():
            calls["tools"] += 1
            return [{"state": f"p{calls['tools']}"}]
        def fresh_doctor():
            calls["doctor"] += 1
            return {"cwd": f"/host-{calls['doctor']}"}
        def fresh_deps():
            calls["deps"] += 1
            return {"items": [{"id": str(calls['deps'])}]}

        cache = vtx_backend._TOOLS_CACHE
        cache.get("catalog", fresh_tools)
        cache.get("catalog", fresh_tools)
        cache.invalidate("catalog")
        cache.get("catalog", fresh_tools)
        self.assertEqual(calls["tools"], 2)

        doctor = vtx_backend._DOCTOR_CACHE
        doctor.get("context", fresh_doctor)
        doctor.get("context", fresh_doctor)
        doctor.invalidate("context")
        doctor.get("context", fresh_doctor)
        self.assertEqual(calls["doctor"], 2)

        deps = vtx_backend._DEPENDENCIES_CACHE
        deps.get("inventory", fresh_deps)
        deps.get("inventory", fresh_deps)
        deps.invalidate("inventory")
        deps.get("inventory", fresh_deps)
        self.assertEqual(calls["deps"], 2)
        clear_probe_caches()

    def test_refresh_invalidates_deep_executable_lookup_cache(self):
        clear_probe_caches()
        name = f"vortex-fresh-{id(self)}"
        probe_executable(name, include_version=False)
        self.assertTrue(vtx_backend._EXECUTABLE_LOOKUP_CACHE._data)
        with patch.object(vtx_backend, "_resolve_executable_lookup", wraps=vtx_backend._resolve_executable_lookup) as resolver:
            probe_executable(name, include_version=False)
            self.assertEqual(resolver.call_count, 0)
        vtx_backend._invalidate_probe_lookups()
        with patch.object(vtx_backend, "_resolve_executable_lookup", wraps=vtx_backend._resolve_executable_lookup) as resolver:
            probe_executable(name, include_version=False)
            self.assertEqual(resolver.call_count, 1)
        clear_probe_caches()

    def test_install_requests_route_to_package_plan_not_container_inspection(self):
        plan = build_plan(self.store, "install podman", self.tmp.name)
        self.assertEqual(plan["kind"], "package_operation")
        self.assertEqual(plan["request"], "install podman")
        self.assertNotEqual(plan["kind"], "container_inspection")
        self.assertTrue(all(command["adapter_id"] == "linux.packages.apt" for command in plan["commands"]))
        self.assertNotIn("docker", plan["commands"][0]["required_tool"])

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
        op = manager.start(plan, True, "token-test", allow_root=ALLOW_ROOT)
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

    def test_engagement_scope_supports_true_subdomains_and_cidr_without_suffix_escape(self):
        domain_scope = {"targets": ["example.test"], "status": "active"}
        self.assertTrue(target_in_engagement("api.example.test", domain_scope))
        self.assertTrue(target_in_engagement("https://deep.api.example.test:9443/path", domain_scope))
        self.assertFalse(target_in_engagement("example.test.attacker.invalid", domain_scope))
        self.assertFalse(target_in_engagement("notexample.test", domain_scope))

        cidr_scope = {"targets": ["192.0.2.0/24", "2001:db8::/48"], "status": "active"}
        self.assertTrue(target_in_engagement("192.0.2.44", cidr_scope))
        self.assertTrue(target_in_engagement("https://192.0.2.99:8443/", cidr_scope))
        self.assertTrue(target_in_engagement("192.0.2.128/25", cidr_scope))
        self.assertTrue(target_in_engagement("2001:db8::42", cidr_scope))
        self.assertFalse(target_in_engagement("192.0.3.1", cidr_scope))
        self.assertFalse(target_in_engagement("192.0.0.0/16", cidr_scope))

    def test_explicit_url_scope_pins_scheme_and_effective_default_port(self):
        scope = {"targets": ["https://lab.example.test/"], "status": "active"}
        self.assertTrue(target_in_engagement("https://lab.example.test:443/other", scope))
        self.assertFalse(target_in_engagement("http://lab.example.test/", scope))

    def test_non_loopback_bind_requires_strong_capability(self):
        vtx_backend.validate_bind_security("127.0.0.1", None)
        vtx_backend.validate_bind_security("localhost", None)
        vtx_backend.validate_bind_security("0.0.0.0", "x" * 32)
        with self.assertRaises(ValueError):
            vtx_backend.validate_bind_security("0.0.0.0", None)
        with self.assertRaises(ValueError):
            vtx_backend.validate_bind_security("192.0.2.10", "short")

    def test_completed_session_releases_all_live_runtime_buffers(self):
        sessions = SessionManager(self.store, idle_seconds=120)
        try:
            session = sessions.create(cwd_raw=self.tmp.name, command=["/bin/true"])
            for _ in range(100):
                record = sessions.info(session["id"])
                if record and record["status"] != "running":
                    break
                time.sleep(.02)
            self.assertEqual(record["status"], "succeeded")
            with sessions.lock:
                self.assertNotIn(session["id"], sessions.sessions)
                self.assertNotIn(session["id"], sessions.events)
                self.assertNotIn(session["id"], sessions.reader_done)
                self.assertNotIn(session["id"], sessions.workers)
            self.assertIsNotNone(self.store.get_session_record(session["id"]))
        finally:
            sessions.shutdown()

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
        manager = ExecutionManager(self.store)
        queues = []
        real_queue = vtx_backend.queue.Queue

        def make_queue(*args, **kwargs):
            instance = real_queue(*args, **kwargs)
            queues.append(instance)
            return instance

        try:
            with patch.object(vtx_backend.queue, "Queue", side_effect=make_queue):
                op = manager.start(plan, True, "cap-token", allow_root=ALLOW_ROOT)
                for _ in range(150):
                    result = self.store.get_operation(op["id"])
                    if result and result["status"] not in ("started", "running"):
                        break
                    time.sleep(.02)
            result = self.store.get_operation(op["id"])
            self.assertEqual(result["status"], "timed_out")
            command = result["commands"][0]
            self.assertEqual(command["termination_reason"], "output_truncated")
            self.assertEqual(len(command["stdout"].encode()), 4096)
            self.assertTrue(queues)
            self.assertTrue(all(item.maxsize > 0 for item in queues), "producer queues must be bounded")
        finally:
            manager.shutdown()

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
        op = manager.start(plan, True, "cancel-token", allow_root=ALLOW_ROOT)
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

    def test_session_output_replay_is_persisted_for_reconnect(self):
        sessions = SessionManager(self.store, idle_seconds=120)
        try:
            session = sessions.create(name='replay', cwd_raw=self.tmp.name, shell='/bin/sh', command=['/bin/sh', '-c', 'printf replay-ok'])
            for _ in range(150):
                info = sessions.info(session['id'])
                events = sessions.events_since(session['id'])['events']
                if any('replay-ok' in event['data'] for event in events) and info and info['status'] not in ('starting', 'running'):
                    break
                time.sleep(.02)
            self.assertTrue(any('replay-ok' in event['data'] for event in events))
            # The same store reopened by a new sidecar can replay the bounded
            # redacted event history even though the old PTY is no longer live.
            persisted = self.store.list_session_events(session['id'])
            self.assertTrue(any('replay-ok' in event['data'] for event in persisted))
        finally:
            sessions.shutdown()

    def test_real_pty_session_streams_resizes_and_kills(self):
        cwd = Path(self.tmp.name)
        sessions = SessionManager(self.store, idle_seconds=120)
        try:
            session = sessions.create(name="test-pty", cwd_raw=str(cwd), shell="/bin/sh", cols=80, rows=24, command=["/bin/sh", "-c", "printf '\\033[31mpty-ready\\033[0m'; sleep 10"])
            self.assertEqual(session["status"], "running")
            for _ in range(100):
                events = sessions.events_since(session["id"])["events"]
                if any("pty-ready" in event["data"] for event in events):
                    break
                time.sleep(.02)
            self.assertTrue(any("pty-ready" in event["data"] for event in events))
            self.assertTrue(any('\x1b[31m' in event['data'] for event in events))
            self.assertEqual(sessions.resize(session["id"], 120, 40)["cols"], 120)
            self.assertTrue(sessions.kill(session["id"]))
            for _ in range(150):
                result = sessions.info(session["id"])
                if result and result["status"] not in ("starting", "running"):
                    break
                time.sleep(.02)
            self.assertEqual(result["status"], "cancelled")
            self.assertEqual(result["termination_reason"], "cancelled")
        finally:
            sessions.shutdown()

    def test_session_cap_is_enforced(self):
        sessions = SessionManager(self.store, idle_seconds=120, max_sessions=1)
        try:
            first = sessions.create(name="one", cwd_raw=self.tmp.name, shell="/bin/sh", command=["/bin/sh", "-c", "sleep 8"])
            with self.assertRaises(PolicyError):
                sessions.create(name="two", cwd_raw=self.tmp.name, shell="/bin/sh", command=["/bin/sh", "-c", "true"])
            sessions.kill(first["id"])
        finally:
            sessions.shutdown()

    def test_session_cap_is_enforced_under_concurrency(self):
        # The cap check and the slot insert must be atomic. Before the fix, N
        # concurrent create() calls could all observe a running count below the
        # cap and then each fork a PTY, overshooting max_sessions.
        import concurrent.futures
        sessions = SessionManager(self.store, idle_seconds=120, max_sessions=3)
        live = []

        def create_one(_):
            try:
                info = sessions.create(name="burst", cwd_raw=self.tmp.name, shell="/bin/sh",
                                       command=["/bin/sh", "-c", "sleep 5"])
                live.append(info)
                return True
            except PolicyError:
                return False

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
                outcomes = list(ex.map(create_one, range(12)))
            created = sum(1 for ok in outcomes if ok)
            self.assertEqual(created, 3, f"expected exactly max_sessions=3 to succeed, got {created}")
            running = sum(1 for item in sessions.list() if item.get("status") == "running")
            self.assertLessEqual(running, 3, f"live running sessions overshot the cap: {running}")
        finally:
            for info in live:
                sessions.kill(info["id"])
            sessions.shutdown()

    def test_session_resolves_relative_command_to_real_binary(self):
        # A relative argv[0] is an executable identity, not shell text. It must
        # resolve to the real installed binary instead of silently running the
        # default shell in its place.
        sessions = SessionManager(self.store, idle_seconds=120)
        try:
            session = sessions.create(name="rel", cwd_raw=self.tmp.name, shell="/bin/sh", command=["printf", "relative-ok"])
            self.assertTrue(session["command"][0].endswith("printf"), f"resolved argv0 was {session['command'][0]!r}")
            for _ in range(150):
                info = sessions.info(session["id"])
                events = sessions.events_since(session["id"])["events"]
                if any("relative-ok" in event["data"] for event in events) and info and info["status"] not in ("starting", "running"):
                    break
                time.sleep(.02)
            self.assertTrue(any("relative-ok" in event["data"] for event in events), "relative command did not produce its output")
        finally:
            sessions.shutdown()

    def test_session_rejects_unknown_relative_command(self):
        # An unknown relative executable must be rejected up front, never
        # replaced with the default shell.
        sessions = SessionManager(self.store, idle_seconds=120)
        try:
            with self.assertRaises(PolicyError):
                sessions.create(name="bad", cwd_raw=self.tmp.name, shell="/bin/sh", command=["no-such-vortex-cmd-xyz"])
        finally:
            sessions.shutdown()

    def test_apt_preflight_parser_extracts_impact_counts(self):
        output = '''The following NEW packages will be installed:
  ripgrep
The following packages will be upgraded:
  libc6
0 upgraded, 1 newly installed, 0 to remove and 0 not upgraded.
'''
        facts = parse_apt_preflight(output, 0)
        self.assertEqual(facts['state'], 'observed')
        self.assertEqual(facts['newly_installed'], 1)
        self.assertEqual(facts['upgraded'], 0)
        self.assertEqual(facts['removed'], 0)
        self.assertIn('ripgrep', facts['packages_new'])

    def test_apt_preflight_parser_never_treats_error_as_success(self):
        facts = parse_apt_preflight('E: Could not get lock /var/lib/dpkg/lock-frontend', 100)
        self.assertEqual(facts['state'], 'tool_error')
        self.assertTrue(facts['errors'])

    def test_systemd_parser_extracts_state_without_inference(self):
        facts = parse_systemd_show('Id=nginx.service\nDescription=Example\nLoadState=loaded\nActiveState=active\nSubState=running\nUnitFileState=enabled\n', 0)
        self.assertEqual(facts['state'], 'observed')
        self.assertEqual(facts['unit'], 'nginx.service')
        self.assertEqual(facts['active_state'], 'active')
        self.assertEqual(facts['unit_file_state'], 'enabled')

    def test_apt_package_facts_join_command_evidence(self):
        results = [
            {'executable':'dpkg','argv':['dpkg','--audit'],'stdout':'','exit_code':0,'status':'succeeded'},
            {'executable':'apt-cache','argv':['apt-cache','policy','git'],'stdout':'Installed: 1:2.39.2\nCandidate: 1:2.39.2\n', 'exit_code':0,'status':'succeeded'},
            {'executable':'apt-get','argv':['apt-get','-s','install','git'],'stdout':'0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.\n','exit_code':0,'status':'succeeded'},
        ]
        facts = parse_package_facts(results)
        self.assertEqual(facts['state'], 'observed')
        self.assertEqual(facts['policy']['candidate'], '1:2.39.2')
        self.assertEqual(facts['preflight']['removed'], 0)

    def test_package_postcondition_parser_requires_exact_installed_state(self):
        installed = parse_package_observation('install ok installed 1.2.3 amd64\n', 0)
        self.assertEqual(installed, {'state': 'installed', 'installed': True, 'version': '1.2.3', 'architecture': 'amd64'})
        self.assertEqual(parse_package_observation('no packages found', 1)['state'], 'absent')
        self.assertEqual(parse_package_observation('surprising success', 0)['state'], 'unexpected_output')
        results = [{
            'executable': 'dpkg-query', 'argv': ['dpkg-query', '-W'],
            'stdout': 'install ok installed 1.2.3 amd64\n', 'stderr': '',
            'exit_code': 0, 'status': 'succeeded', 'package_observation': 'after',
            'expected_package_state': 'installed',
        }]
        facts = parse_package_facts(results)
        self.assertTrue(facts['verification']['verified'])
        self.assertEqual(facts['verification']['version'], '1.2.3')

    def test_package_preflight_gate_uses_root_mutation_not_trailing_verifier(self):
        manager = ExecutionManager(self.store)
        install = build_plan(self.store, "install package git", self.tmp.name)
        self.assertEqual(install["status"], "planned")
        install_op = {"commands": [{
            "executable": "apt-get", "argv": ["apt-get", "-s", "--no-remove", "install", "git"],
            "stdout": "Remv obsolete [1.0]\n0 upgraded, 1 newly installed, 1 to remove and 0 not upgraded.\n",
            "stderr": "", "exit_code": 0, "status": "succeeded",
        }]}
        self.assertIn("reported removals", manager._preflight_gate(install, install_op))

        remove = build_plan(self.store, "remove package git", self.tmp.name)
        self.assertEqual(remove["status"], "planned")
        remove_op = {"commands": [{
            "executable": "apt-get", "argv": ["apt-get", "-s", "remove", "git"],
            "stdout": "0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.\n",
            "stderr": "", "exit_code": 0, "status": "succeeded",
        }]}
        self.assertIn("no package removal", manager._preflight_gate(remove, remove_op))

    def test_execution_fails_when_package_or_dpkg_postcondition_is_not_met(self):
        for expected_key, stdout, reason in (
            ("expected_package_state", "unexpected successful output\n", "package_verification_failed"),
            ("expected_dpkg_state", "Packages are only half configured\n", "dpkg_verification_failed"),
        ):
            with self.subTest(expected_key=expected_key):
                plan = build_plan(self.store, "whoami", self.tmp.name)
                spec = dict(plan["commands"][0])
                spec.update({"adapter_id": "linux.packages.apt", expected_key: "installed" if expected_key == "expected_package_state" else "consistent"})
                plan["commands"] = [spec]
                operation = {
                    "id": f"postcondition-{expected_key}", "plan_id": plan["id"], "status": "started",
                    "commands": [], "workers": [], "settings_snapshot": {"ai_enabled": False},
                }
                manager = ExecutionManager(self.store)
                manager.cancel_events[operation["id"]] = threading.Event()
                manager._run_one = lambda _spec, _op_id, output=stdout: {
                    "argv": _spec["argv"], "display": _spec["display"], "executable": _spec["executable"],
                    "adapter_id": _spec["adapter_id"], "adapter_version": _spec["adapter_version"],
                    "cwd": _spec["cwd"], "started_at": now_iso(), "stdout": output, "stderr": "",
                    "exit_code": 0, "signal": None, "termination_reason": "completed", "status": "succeeded",
                    "version": "test", "evidence_digest": "test",
                }
                manager._run(plan, operation)
                self.assertEqual(operation["status"], "failed")
                self.assertEqual(operation["commands"][0]["termination_reason"], reason)
                verification_key = "package_verification" if expected_key == "expected_package_state" else "dpkg_verification"
                self.assertFalse(operation["commands"][0][verification_key]["verified"])

    def test_mutation_requires_a_second_approval_after_fresh_preflight(self):
        plan = build_plan(self.store, 'restart nginx', self.tmp.name)
        if plan['status'] != 'planned':
            self.skipTest('systemd is unavailable in this environment')
        manager = ExecutionManager(self.store)
        def observed_run(spec, _operation_id):
            is_show = 'show' in spec['argv']
            return {
                'argv': spec['argv'], 'display': spec['display'], 'executable': 'systemctl',
                'adapter_id': spec['adapter_id'], 'adapter_version': spec['adapter_version'],
                'cwd': spec['cwd'], 'started_at': now_iso(), 'stdout': 'Id=nginx.service\nLoadState=loaded\nActiveState=active\nSubState=running\nUnitFileState=enabled\n' if is_show else '',
                'stderr': '', 'exit_code': 0, 'signal': None, 'termination_reason': 'completed',
                'status': 'succeeded', 'version': 'test-systemctl', 'evidence_digest': 'observed',
            }
        manager._run_one = observed_run
        with patch('backend.vortex_backend.os.getuid', return_value=0):
            operation = manager.start(plan, True, plan['approval_token'], allow_root=True)
            for _ in range(100):
                operation = self.store.get_operation(operation['id'])
                if operation['status'] == 'awaiting_confirmation':
                    break
                time.sleep(.02)
            self.assertEqual(operation['status'], 'awaiting_confirmation')
            self.assertEqual(len(operation['commands']), 1)
            self.assertTrue(operation['preflight_digest'])
            resumed = manager.approve_preflight(operation['id'], True, plan['approval_token'], operation['preflight_digest'])
            self.assertIn(resumed['status'], ('started', 'running'))
            for _ in range(100):
                result = self.store.get_operation(operation['id'])
                if result['status'] not in ('started', 'running'):
                    break
                time.sleep(.02)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(len(result['commands']), 2)

    def test_preflight_gate_blocks_changed_apt_impact(self):
        plan = {
            'commands': [
                {'adapter_id':'linux.packages.apt','executable':'apt-get','argv':['apt-get','-s','--no-remove','install','git']},
                {'adapter_id':'linux.packages.apt','executable':'apt-get','argv':['apt-get','--assume-yes','--no-remove','install','git'],'privilege':'root-required'},
            ]
        }
        operation = {'commands': [
            {'adapter_id':'linux.packages.apt','executable':'apt-get','argv':plan['commands'][0]['argv'],'stdout':'1 upgraded, 2 newly installed, 1 to remove and 0 not upgraded.','stderr':'','exit_code':0,'status':'succeeded'}
        ]}
        error = ExecutionManager(self.store)._preflight_gate(plan, operation)
        self.assertIn('removals', error)

    def test_preflight_gate_blocks_missing_systemd_unit(self):
        plan = {'commands': [
            {'adapter_id':'linux.systemd.mutate','executable':'systemctl','argv':['systemctl','show','ghost.service']},
            {'adapter_id':'linux.systemd.mutate','executable':'systemctl','argv':['systemctl','restart','ghost.service']},
        ]}
        operation = {'commands': [
            {'adapter_id':'linux.systemd.mutate','executable':'systemctl','argv':plan['commands'][0]['argv'],'stdout':'Id=ghost.service\nLoadState=not-found\n','stderr':'','exit_code':0,'status':'succeeded'}
        ]}
        error = ExecutionManager(self.store)._preflight_gate(plan, operation)
        self.assertIn('not loaded', error)

    def test_apt_plan_requires_real_preflight_before_root_mutation(self):
        if not apt_tools_ready()[0]:
            self.skipTest('apt/dpkg unavailable')
        plan = build_plan(self.store, 'install package git', self.tmp.name)
        self.assertEqual(plan['status'], 'planned')
        self.assertEqual(plan['commands'][-3]['argv'][:4], ['apt-get', '-s', '--no-remove', 'install'])
        self.assertEqual(plan['commands'][-2]['privilege'], 'root-required')
        self.assertEqual(plan['commands'][-1]['expected_package_state'], 'installed')
        self.assertEqual(plan['commands'][-1]['package_observation'], 'after')
        self.assertNotIn('--allow-unauthenticated', json.dumps(plan))
        self.assertEqual(parse_package_request('install git; touch /tmp/pwned'), ('', None))
        if os.getuid() != 0:
            with self.assertRaises(PermissionError):
                ExecutionManager(self.store).start(plan, True, plan['approval_token'])

    def test_package_probe_failure_is_informational_but_mutation_is_not(self):
        plan = build_plan(self.store, 'install package git', self.tmp.name)
        self.assertEqual(plan['commands'][0]['executable'], 'dpkg')
        queries = [command for command in plan['commands'] if command['executable'] == 'dpkg-query' and '-W' in command['argv']]
        self.assertEqual(queries[0]['success_exit_codes'], [0, 1])
        self.assertEqual(queries[0]['package_observation'], 'before')
        self.assertEqual(queries[-1]['success_exit_codes'], [0])
        self.assertEqual(queries[-1]['expected_package_state'], 'installed')
        self.assertTrue(any(command['executable'] == 'apt-get' and '-s' in command['argv'] for command in plan['commands']))

    def test_systemd_user_context_is_detected_without_fallback_to_root(self):
        self.assertEqual(parse_systemd_mutation('restart --user demo.service'), ('restart', 'demo.service', True))
        bus = systemd_user_bus_state()
        self.assertIn(bus['state'], ('available', 'absent', 'unavailable'))
        plan = build_plan(self.store, 'restart --user demo.service', self.tmp.name)
        if plan['status'] == 'planned':
            self.assertEqual(plan['commands'][0]['argv'][1:3], ['--user', 'show'])
            self.assertEqual(plan['commands'][1]['privilege'], 'user')
        else:
            self.assertEqual(plan['commands'], [])

    def test_systemd_mutation_is_guarded_and_unit_typed(self):
        plan = build_plan(self.store, 'restart nginx', self.tmp.name)
        if plan['status'] == 'planned':
            self.assertEqual(plan['commands'][0]['adapter_id'], 'linux.systemd.mutate')
            self.assertEqual(plan['commands'][1]['argv'][-1], 'nginx.service')
            self.assertEqual(plan['commands'][1]['privilege'], 'root-required')
        else:
            self.assertEqual(plan['commands'], [])
        unsafe = build_plan(self.store, 'restart ../../evil; echo unsafe', self.tmp.name)
        self.assertEqual(unsafe['kind'], 'unsupported_shell_syntax')
        self.assertEqual(unsafe['status'], 'rejected')
        self.assertEqual(unsafe['commands'], [])

    def test_nmap_artifact_parser_reports_only_observed_ports(self):
        data = b'''<?xml version="1.0"?><nmaprun scanner="nmap" args="nmap -sV lab.example.test"><host><status state="up"/><address addr="192.0.2.10" addrtype="ipv4"/><hostnames><hostname name="lab.example.test"/></hostnames><ports><port protocol="tcp" portid="443"><state state="open"/><service name="https" product="Example" version="1.2"/></port></ports></host></nmaprun>'''
        artifact = analyze_bytes(data, kind='nmap-xml', source={'kind':'fixture','identity':'nmap-fixture'})
        self.assertEqual(artifact['state'], 'observed')
        self.assertEqual(artifact['observations'][0]['type'], 'open_port')
        self.assertEqual(artifact['observations'][0]['port'], '443')
        self.assertNotIn('vulnerability', json.dumps(artifact).lower())
        self.assertEqual(artifact['parser']['id'], 'nmap.xml')

    def test_artifact_parser_rejects_malformed_xml_entities_and_symlinks(self):
        malformed = analyze_bytes(b'<!DOCTYPE foo [<!ENTITY x "boom">]><nmaprun/>', kind='nmap-xml')
        self.assertEqual(malformed['state'], 'tool_error')
        malformed = analyze_bytes(b'<nmaprun>', kind='nmap-xml')
        self.assertEqual(malformed['state'], 'tool_error')
        path = Path(self.tmp.name) / 'linked.xml'
        path.symlink_to(Path(self.tmp.name) / 'missing.xml')
        with self.assertRaises(ArtifactError):
            analyze_path(str(path), 'auto')
        with self.assertRaises(ArtifactError):
            analyze_bytes(b'x' * (10 * 1024 * 1024 + 1), kind='text')

    def test_http_artifact_parser_redacts_headers_and_marks_observation(self):
        data = 'HTTP/1.1 200 OK\r\nServer: test\r\nSet-Cookie: token=super-secret\r\nLocation: https://example.test/next\r\n\r\n'
        artifact = analyze_bytes(data.encode(), kind='http-headers')
        self.assertEqual(artifact['state'], 'observed')
        self.assertEqual(artifact['status_code'], 200)
        serialized = json.dumps(artifact)
        self.assertIn('[REDACTED]', serialized)
        self.assertNotIn('super-secret', serialized)
        self.assertTrue(any(h['name'] == 'location' for h in artifact['headers']))
        self.assertTrue(artifact['redirect_requires_new_scope_check'])
        self.assertEqual(artifact['redirects'][0], 'https://example.test/next')

    def test_real_http_adapter_persists_parsed_evidence(self):
        import shutil
        if not shutil.which('curl'):
            self.skipTest('curl unavailable')
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('X-Vortex-Test', 'yes')
                self.send_header('Set-Cookie', 'token=fixture-secret')
                self.end_headers()
            def log_message(self, *_args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            target = f'http://127.0.0.1:{server.server_port}/'
            engagement = {
                'id': 'http-eng', 'created_at': now_iso(), 'expires_at': '2099-08-25T00:00:00+00:00',
                'name': 'local HTTP fixture', 'authorization': 'test fixture', 'targets': [target],
                'classes': ['reconnaissance'], 'status': 'active',
            }
            self.store.create_engagement(engagement)
            plan = build_plan(self.store, f'curl {target}', self.tmp.name, engagement['id'])
            self.assertEqual(plan['status'], 'planned')
            manager = ExecutionManager(self.store)
            operation = manager.start(plan, True, plan['approval_token'], allow_root=ALLOW_ROOT)
            for _ in range(150):
                result = self.store.get_operation(operation['id'])
                if result and result['status'] not in ('started', 'running'):
                    break
                time.sleep(.02)
            self.assertEqual(result['status'], 'succeeded')
            self.assertEqual(result['artifacts'][0]['kind'], 'http-headers')
            self.assertEqual(result['artifacts'][0]['state'], 'observed')
            self.assertNotIn('fixture-secret', json.dumps(result))
        finally:
            server.shutdown()
            server.server_close()

    def test_nmap_parser_rejects_invalid_port_observations(self):
        data = b'<nmaprun><host><address addr="192.0.2.1"/><ports><port protocol="tcp" portid="99999"><state state="open"/></port></ports></host></nmaprun>'
        artifact = analyze_bytes(data, kind='nmap-xml')
        self.assertEqual(artifact['state'], 'observed')
        self.assertEqual(artifact['observations'], [])
        self.assertTrue(artifact['parse_errors'])

    def test_container_and_ssh_parsers_are_evidence_only(self):
        logs = parse_container_logs([{'status':'succeeded','stdout':'2026-01-01T00:00:00Z ERROR failed once\nINFO ok\n','stderr':''}])
        self.assertEqual(logs['state'], 'observed')
        self.assertEqual(logs['line_count'], 2)
        ssh = parse_ssh_connection([{'status':'failed','exit_code':255,'stdout':'','stderr':'ssh: connect to host lab port 22: Connection refused'}])
        self.assertEqual(ssh['classification'], 'refused')
        self.assertNotIn('super-secret', json.dumps(ssh).lower())

    def test_dns_facts_are_real_and_digestable(self):
        fact = resolve_target('localhost')
        self.assertIn(fact['state'], ('observed', 'tool_error'))
        if fact['state'] == 'observed':
            self.assertTrue(fact['addresses'])
        facts = resolve_targets(['127.0.0.1'])
        self.assertEqual(facts['state'], 'observed')
        self.assertEqual(resolution_digest(facts), resolution_digest(facts))

    def test_dns_change_invalidates_active_plan_before_connection(self):
        import backend.vortex_backend as backend_module
        if not shutil.which('curl'):
            self.skipTest('curl unavailable')
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers()
            def log_message(self, *_args): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            target = f'http://127.0.0.1:{server.server_port}/'
            engagement = {'id':'dns-eng','created_at':now_iso(),'expires_at':'2099-08-25T00:00:00+00:00','name':'dns test','authorization':'test','targets':[target],'classes':['reconnaissance'],'status':'active'}
            self.store.create_engagement(engagement)
            plan = build_plan(self.store, f'curl {target}', self.tmp.name, engagement['id'])
            self.assertEqual(plan['status'], 'planned')
            changed = {'state':'observed','targets':[{'target':target,'host':'127.0.0.1','port':server.server_port,'state':'observed','addresses':['192.0.2.99']}]}
            with patch.object(backend_module, 'resolve_targets', return_value=changed):
                with self.assertRaises(PolicyError):
                    ExecutionManager(self.store).start(plan, True, plan['approval_token'])
        finally:
            server.shutdown(); server.server_close()

    def test_container_log_request_is_bounded_or_truthfully_unavailable(self):
        plan = build_plan(self.store, 'show logs for container web', self.tmp.name)
        if plan['status'] == 'planned':
            command = plan['commands'][0]
            self.assertEqual(command['adapter_id'], 'linux.containers.logs')
            self.assertEqual(command['argv'][-1], 'web')
            self.assertEqual(command['argv'][command['argv'].index('--tail') + 1], '200')
        else:
            self.assertEqual(plan['commands'], [])

    def test_active_ssh_requires_scope_and_offline_blocks_connection(self):
        plan = build_plan(self.store, 'test ssh connection to labhost', self.tmp.name)
        self.assertEqual(plan['kind'], 'ssh_diagnostics')
        self.assertEqual(plan['commands'], [])
        self.assertIn(plan['status'], ('clarified', 'unavailable', 'rejected'))
        offline = build_plan(self.store, 'test ssh connection to labhost', self.tmp.name, offline=True)
        self.assertEqual(offline['commands'], [])
        self.assertEqual(offline['status'], 'unavailable')

    def test_undo_creates_a_fresh_plan_only_after_verified_success(self):
        plan = build_plan(self.store, 'install package git', self.tmp.name)
        operation = {'schema_version':1,'id':'undo-op','plan_id':plan['id'],'started_at':now_iso(),'ended_at':now_iso(),'status':'succeeded','commands':[],'workers':[],'source':'deterministic','output_digest':'x','analysis':{}}
        self.store.save_operation(operation)
        rollback = build_undo_plan(self.store, operation['id'])
        self.assertEqual(rollback['kind'], 'rollback_plan')
        self.assertEqual(rollback['rollback_source_operation'], operation['id'])
        self.assertEqual(rollback['status'], 'planned')
        self.assertNotIn('operation_finished', rollback['request'])

    def test_git_status_plan_blanks_the_status_alias_and_isolates_config(self):
        plan = build_plan(self.store, "git status", self.tmp.name)
        if plan["status"] != "planned":
            self.skipTest("git is unavailable")
        spec = plan["commands"][0]
        self.assertEqual(spec["adapter_id"], "linux.development.git-status")
        self.assertIn("alias.status=", spec["argv"])
        self.assertEqual(spec["env_additions"]["GIT_CONFIG_GLOBAL"], "/dev/null")
        self.assertEqual(spec["env_additions"]["GIT_TERMINAL_PROMPT"], "0")

    def test_git_command_ignores_global_config_and_custom_aliases(self):
        if shutil.which("git") is None:
            self.skipTest("git is unavailable")
        repo = Path(self.tmp.name) / "git-isolation"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        evil = Path(self.tmp.name) / "evil.gitconfig"
        evil.write_text("[alias]\n    status = !printf PWNED\\n    pwn = !printf PWNED\\n[core]\n    sshCommand = printf PWNED\\n", encoding="utf-8")
        spec = vtx_backend.git_command("linux.development.git-status", repo, "status", "--short", "--branch")
        env = vtx_backend.minimal_env(False, spec["env_additions"])
        env["HOME"] = str(Path(self.tmp.name))
        # A hostile GIT_CONFIG_GLOBAL must not override the adapter isolation.
        env["GIT_CONFIG_GLOBAL"] = str(evil)
        env.update(spec["env_additions"])
        proc = subprocess.run(spec["argv"], cwd=str(repo), env=env, capture_output=True, text=True, timeout=10)
        combined = (proc.stdout or "") + (proc.stderr or "")
        self.assertNotIn("PWNED", combined)
        self.assertEqual(proc.returncode, 0)

    def test_preview_makefile_and_npm_preview_are_loopback(self):
        root = Path(__file__).resolve().parent.parent
        makefile = (root / "Makefile").read_text(encoding="utf-8")
        package = (root / "package.json").read_text(encoding="utf-8")
        self.assertIn("--host 127.0.0.1 --port 4173", makefile)
        self.assertNotIn("--host 0.0.0.0 --port 4173", makefile)
        self.assertIn("--host 127.0.0.1 --port 4173", package)
        self.assertNotIn("--host 0.0.0.0 --port 4173", package)

    def test_pty_scrollback_is_usable_and_byte_capped(self):
        self.assertGreaterEqual(vtx_backend.PTY_MEMORY_EVENTS, 256)
        self.assertGreaterEqual(vtx_backend.PTY_PERSISTED_EVENTS, 512)
        self.assertEqual(vtx_backend.PTY_MEMORY_BYTES, 4 * 1024 * 1024)
        self.assertLessEqual(vtx_backend.PTY_MEMORY_EVENTS * vtx_backend.PTY_READ_BYTES, 32 * 1024 * 1024)

    def test_pty_live_ring_drops_oldest_events_when_over_byte_cap(self):
        sessions = SessionManager(self.store, idle_seconds=120)
        session_id = "byte-cap"
        original = vtx_backend.PTY_MEMORY_BYTES
        started = now_iso()
        try:
            record = {
                "id": session_id, "name": "byte-cap", "shell": "/bin/sh",
                "cwd": self.tmp.name, "command": ["/bin/true"], "pid": None,
                "cols": 80, "rows": 24, "status": "running", "started_at": started,
                "ended_at": None, "last_activity": started, "exit_code": None,
                "signal": None, "termination_reason": None, "_event_seq": 0,
            }
            self.store.save_session({key: value for key, value in record.items() if not str(key).startswith("_")})
            with sessions.lock:
                sessions.sessions[session_id] = record
                sessions.events[session_id] = vtx_backend.deque(maxlen=vtx_backend.PTY_MEMORY_EVENTS)
            vtx_backend.PTY_MEMORY_BYTES = 64
            sessions._append_event(session_id, "a" * 50)
            sessions._append_event(session_id, "b" * 50)
            with sessions.lock:
                ring = list(sessions.events[session_id])
                sessions.sessions.pop(session_id, None)
                sessions.events.pop(session_id, None)
            self.assertEqual(len(ring), 1)
            self.assertTrue(ring[0]["data"].startswith("b"))
        finally:
            vtx_backend.PTY_MEMORY_BYTES = original
            sessions.shutdown()

    def test_app_version_is_consistent_across_surfaces(self):
        root = Path(__file__).resolve().parent.parent
        self.assertEqual(vtx_backend.APP_VERSION, "0.2.23")
        self.assertIn(f"version='vortex {vtx_backend.APP_VERSION}'", (root / "cli" / "vortex.py").read_text(encoding="utf-8"))
        self.assertIn(f'"version": "{vtx_backend.APP_VERSION}"', (root / "package.json").read_text(encoding="utf-8"))
        html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn(f"VORTEX {vtx_backend.APP_VERSION}", html)
        self.assertNotIn("0.2.21", html)
        from backend.mobile.apkbuild import VERSION_CODE, VERSION_NAME
        self.assertEqual(VERSION_NAME, vtx_backend.APP_VERSION)
        self.assertEqual(VERSION_CODE, 223)

    def test_privilege_handoff_documents_sudo_timestamp_window(self):
        source = Path(__file__).resolve().parent.parent.joinpath("cli", "vortex.py").read_text(encoding="utf-8")
        self.assertIn("timestamp window", source)
        self.assertIn("15 minutes", source)

    def test_analysis_does_not_invent_findings(self):
        op = {"status": "succeeded", "commands": [], "workers": []}
        analysis = make_analysis({}, op)
        self.assertIn("not a security guarantee", analysis["inference"])
        self.assertIn("No command was run", analysis["fact"])


if __name__ == "__main__":
    unittest.main()
