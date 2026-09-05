"""Tests for the intelligent terminal palette, cross-layer search, and dashboard.

These cover the terminal-copilot surfaces from the feature specification: the
slash-command palette, the global search across layers, the live dashboard, and
honest tool metadata.  Everything is exercised on real local storage/probes; no
external tool, model, or network is required.
"""
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend.vortex_backend import ExecutionManager, SessionManager, Store, VortexHandler, build_plan, now_iso
from backend.workspace import Workspace
from backend.palette import expand, run_palette, _available_commands
from backend import dashboard


class PaletteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        config_home = Path(self.tmp.name) / "config"
        config_home.mkdir(parents=True, exist_ok=True)
        os.environ["XDG_CONFIG_HOME"] = str(config_home)
        self.store = Store(Path(self.tmp.name) / "vortex.db")
        self.workspace = Workspace(self.store)
        self.cwd = str(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)
        os.environ.pop("XDG_CONFIG_HOME", None)

    def test_expand_plan_command(self):
        meta = expand("/ports")
        self.assertEqual(meta["kind"], "plan")
        self.assertEqual(meta["command"], "/ports")
        self.assertIn("listening ports", meta["request"])

    def test_expand_explain_command(self):
        meta = expand("/explain ls -la")
        self.assertEqual(meta["kind"], "plan")
        self.assertTrue(meta["request"].startswith("explain ls -la"))

    def test_expand_query_command(self):
        meta = expand("/findings")
        self.assertEqual(meta["kind"], "query")
        self.assertEqual(meta["query"], "findings")

    def test_expand_search_requires_term(self):
        meta = expand("/search")
        self.assertEqual(meta["kind"], "search_help")
        self.assertIn("Provide a term", meta["message"])

    def test_unknown_command_returns_help_with_available(self):
        meta = expand("/not-a-command")
        self.assertEqual(meta["kind"], "help")
        self.assertIn("/ports", meta["available"])

    def test_palette_plan_route_goes_through_reviewed_planner(self):
        res = run_palette(self.store, self.workspace, "/health", cwd=self.cwd)
        self.assertEqual(res["palette"]["kind"], "plan")
        plan = res["plan"]
        self.assertEqual(plan["kind"], "plan")
        self.assertNotEqual(plan["status"], "rejected")
        # The plan has an approval token and a digest, so it is a real reviewed plan.
        self.assertTrue(plan.get("approval_token"))
        self.assertTrue(plan.get("digest"))

    def test_palette_query_history_is_read_only(self):
        res = run_palette(self.store, self.workspace, "/history", cwd=self.cwd)
        self.assertEqual(res["palette"]["kind"], "query")
        self.assertEqual(res["palette"]["query"], "history")
        self.assertIn("history", res)
        # A read-only query must not create a plan or start an operation.
        self.assertNotIn("plan", res)
        self.assertNotIn("operation", res)

    def test_palette_does_not_execute(self):
        # /health produces a plan; run_palette must never start an operation.
        res = run_palette(self.store, self.workspace, "/health", cwd=self.cwd)
        self.assertNotIn("operation", res)
        self.assertIsNone(res.get("operation"))

    def test_available_commands_are_reviewed(self):
        # Every palette plan command must map to a friendly, reviewed request.
        for cmd in _available_commands():
            if cmd == "/explain <command>":
                continue
            if cmd in ("/history", "/sessions", "/findings", "/evidence", "/reports", "/tasks", "/engagements", "/search", "/dashboard"):
                continue
            meta = expand(cmd)
            self.assertEqual(meta["kind"], "plan", cmd)
            self.assertTrue(meta.get("request"), cmd)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        config_home = Path(self.tmp.name) / "config"
        config_home.mkdir(parents=True, exist_ok=True)
        os.environ["XDG_CONFIG_HOME"] = str(config_home)
        self.store = Store(Path(self.tmp.name) / "vortex.db")
        self.workspace = Workspace(self.store)
        self.cwd = str(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)
        os.environ.pop("XDG_CONFIG_HOME", None)

    def test_search_matches_messages_across_conversations(self):
        convo = self.workspace.create_conversation("Target search")
        self.workspace.add_message(convo["id"], "user", "show me 192.168.1.20")
        result = self.workspace.search_all("192.168.1.20")
        self.assertGreaterEqual(result["total"], 1)
        layers = {item["layer"] for item in result["results"]}
        self.assertIn("messages", layers)

    def test_search_matches_findings_and_reports(self):
        self.workspace.add_finding(None, None, "Open port 443 observed", "info", {"port": 443}, "observed")
        self.workspace.save_report({"title": "Apache on 443", "kind": "security"})
        result = self.workspace.search_all("443")
        layers = {item["layer"] for item in result["results"]}
        self.assertIn("findings", layers)
        self.assertIn("reports", layers)

    def test_search_empty_term_returns_no_results(self):
        result = self.workspace.search_all("")
        self.assertEqual(result["total"], 0)

    def test_search_matches_operations_and_evidence(self):
        # A stored operation (history) and an artifact are both searched.
        plan = build_plan(self.store, "show system health", self.cwd)
        now = now_iso()
        operation = {
            "id": "op-1", "plan_id": plan["id"], "status": "succeeded",
            "started_at": now, "ended_at": now,
            "commands": [{"display": "nmap -sV example.com", "status": "succeeded",
                          "stdout": "", "stderr": "", "exit_code": 0}],
            "analysis": {"fact": "Observed example.com."},
        }
        self.store.save_operation(operation)
        artifact = {
            "schema_version": 1, "artifact_id": "a-1", "kind": "nmap-xml", "operation_id": "op-1",
            "source": {"kind": "generated_file", "path": "/tmp/x.xml"}, "size_bytes": 10, "sha256": "abc",
            "parser": {"id": "nmap.xml", "version": "1"}, "state": "observed",
            "observations": [], "summary": "example.com",
        }
        self.store.save_artifact(artifact, "op-1")
        result = self.workspace.search_all("example.com")
        layers = {item["layer"] for item in result["results"]}
        self.assertIn("operations", layers)
        self.assertIn("evidence", layers)

    def test_search_matches_tasks(self):
        task = self.workspace.create_task("inspect authorized server example.com")
        result = self.workspace.search_all("example.com")
        layers = {item["layer"] for item in result["results"]}
        self.assertIn("tasks", layers)
        self.assertTrue(any(item["id"] == task["id"] for item in result["results"]))


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        config_home = Path(self.tmp.name) / "config"
        config_home.mkdir(parents=True, exist_ok=True)
        os.environ["XDG_CONFIG_HOME"] = str(config_home)
        self.store = Store(Path(self.tmp.name) / "vortex.db")
        self.workspace = Workspace(self.store)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)
        os.environ.pop("XDG_CONFIG_HOME", None)

    def test_dashboard_returns_honest_sections(self):
        data = dashboard.collect(self.store, self.workspace)
        for key in ("host", "system", "ai", "session", "tools", "engagements", "findings", "vpn"):
            self.assertIn(key, data)
        self.assertEqual(data["vpn"]["state"], "unavailable")
        self.assertFalse(data["vpn"]["available"])
        self.assertIn("installed", data["tools"])
        self.assertIn("total_mb", data["system"]["memory"])

    def test_dashboard_never_claims_vpn(self):
        data = dashboard.collect(self.store, self.workspace)
        self.assertIn("No reviewed VPN", data["vpn"]["detail"])


class RegistryMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)

    def test_registry_carries_license_and_install_method(self):
        from backend.tools.registry import inventory
        items = {item["name"]: item for item in inventory()}
        for name in ("git", "curl", "nmap", "ssh"):
            self.assertIn(name, items)
            self.assertIn("license", items[name])
            self.assertIn("installation_method", items[name])
            self.assertTrue(items[name]["license"])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        config_home = Path(self.tmp.name) / "config"
        config_home.mkdir(parents=True, exist_ok=True)
        os.environ["XDG_CONFIG_HOME"] = str(config_home)
        self.store = Store(Path(self.tmp.name) / "vortex.db")
        self.workspace = Workspace(self.store)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)
        os.environ.pop("XDG_CONFIG_HOME", None)

    def _cli(self, *argv):
        from cli.vortex import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--json", *argv])
        return code, json.loads(buf.getvalue())

    def test_cli_palette_plan(self):
        code, payload = self._cli("palette", "/health")
        self.assertEqual(code, 0)
        self.assertEqual(payload["palette"]["kind"], "plan")
        self.assertIn("plan", payload)

    def test_cli_palette_query(self):
        code, payload = self._cli("palette", "/history")
        self.assertEqual(code, 0)
        self.assertEqual(payload["palette"]["kind"], "query")
        self.assertIn("history", payload)

    def test_cli_search(self):
        self.workspace.add_message(self.workspace.create_conversation("s")["id"], "user", "asset 10.0.0.5")
        code, payload = self._cli("search", "10.0.0.5")
        self.assertEqual(code, 0)
        self.assertGreaterEqual(payload["search"]["total"], 1)

    def test_cli_dashboard(self):
        code, payload = self._cli("dashboard")
        self.assertEqual(code, 0)
        self.assertEqual(payload["dashboard"]["vpn"]["state"], "unavailable")


class HttpApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        self._previous_config_home = os.environ.get("XDG_CONFIG_HOME")
        config_home = Path(self.tmp.name) / "config"
        config_home.mkdir(parents=True, exist_ok=True)
        os.environ["XDG_CONFIG_HOME"] = str(config_home)
        self.store = Store(Path(self.tmp.name) / "vortex.db")
        handler = VortexHandler
        handler.store = self.store
        handler.executor = ExecutionManager(self.store)
        handler.sessions = SessionManager(self.store, idle_seconds=120)
        handler.workspace = Workspace(self.store)
        handler.executor.workspace = handler.workspace
        handler.frontend = Path(__file__).resolve().parent.parent / "frontend"
        handler.token = None
        self.handler = handler
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.handler.sessions.shutdown()
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)
        if self._previous_config_home is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._previous_config_home

    def _json(self, method, path, body=None, expected=200, timeout=8):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read())
                self.assertEqual(response.status, expected)
                return payload
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read())
            if exc.code != expected:
                raise AssertionError(f"{method} {path} expected {expected} got {exc.code}: {payload}") from exc
            return payload

    def test_palette_route_plan(self):
        payload = self._json("POST", "/api/palette", {"request": "/health"})
        self.assertEqual(payload["palette"]["kind"], "plan")
        self.assertIn("plan", payload)

    def test_palette_route_query(self):
        payload = self._json("POST", "/api/palette", {"request": "/history"})
        self.assertEqual(payload["palette"]["kind"], "query")
        self.assertIn("history", payload)

    def test_search_route(self):
        self.handler.workspace.add_message(self.handler.workspace.create_conversation("x")["id"], "user", "target 10.0.0.5")
        import urllib.parse
        payload = self._json("GET", "/api/search?q=" + urllib.parse.quote("10.0.0.5"))
        self.assertGreaterEqual(payload["search"]["total"], 1)

    def test_dashboard_route(self):
        payload = self._json("GET", "/api/dashboard")
        self.assertEqual(payload["dashboard"]["vpn"]["state"], "unavailable")
        self.assertIn("system", payload["dashboard"])

    def test_palette_requires_request(self):
        self._json("POST", "/api/palette", {}, expected=422)


if __name__ == "__main__":
    unittest.main()
