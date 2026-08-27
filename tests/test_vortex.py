import http.server
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from unittest.mock import patch
import unittest
from pathlib import Path

from backend.artifacts import ArtifactError, analyze_bytes, analyze_path
from backend.vortex_backend import sanitize_pty
from backend.facts import parse_apt_preflight, parse_container_logs, parse_package_facts, parse_ssh_connection, parse_systemd_show
from backend.network import resolve_target, resolve_targets, resolution_digest
from backend import vortex_backend as vtx_backend  # noqa: E402
from backend.vortex_backend import (
    ExecutionManager, PolicyError, SessionManager, Store, build_plan, build_undo_plan, clear_probe_caches, command_spec,
    apt_tools_ready, digest, make_analysis, normalize_target, now_iso, parse_package_request, parse_systemd_mutation, probe_executable, plan_digest, sanitize_pty, systemd_user_bus_state, target_in_engagement,
)

ALLOW_ROOT = os.geteuid() == 0


class VortexCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "vortex.db"
        self.store = Store(self.db)

    def tearDown(self):
        self.tmp.cleanup()

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
        self.assertEqual(plan['commands'][0]['argv'], ['ssh', '-G', '--', 'labhost'])
        self.assertEqual(plan['commands'][0]['network_class'], 'no-network')

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
        op = ExecutionManager(self.store).start(plan, True, "cap-token", allow_root=ALLOW_ROOT)
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
                {'adapter_id':'linux.packages.apt','executable':'apt-get','argv':['apt-get','--assume-yes','--no-remove','install','git']},
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
        self.assertEqual(plan['commands'][-2]['argv'][:4], ['apt-get', '-s', '--no-remove', 'install'])
        self.assertEqual(plan['commands'][-1]['privilege'], 'root-required')
        self.assertNotIn('--allow-unauthenticated', json.dumps(plan))
        self.assertEqual(parse_package_request('install git; touch /tmp/pwned'), ('', None))
        if os.getuid() != 0:
            with self.assertRaises(PermissionError):
                ExecutionManager(self.store).start(plan, True, plan['approval_token'])

    def test_package_probe_failure_is_informational_but_mutation_is_not(self):
        plan = build_plan(self.store, 'install package git', self.tmp.name)
        self.assertEqual(plan['commands'][0]['executable'], 'dpkg')
        query = next(command for command in plan['commands'] if command['executable'] == 'dpkg-query' and '-W' in command['argv'])
        self.assertTrue(query['allow_failure'])
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

    def test_analysis_does_not_invent_findings(self):
        op = {"status": "succeeded", "commands": [], "workers": []}
        analysis = make_analysis({}, op)
        self.assertIn("not a security guarantee", analysis["inference"])
        self.assertIn("No command was run", analysis["fact"])


if __name__ == "__main__":
    unittest.main()
