import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend import vortex_backend as vtx_backend
from backend.vortex_backend import ExecutionManager, SessionManager, Store, VortexHandler
from backend.workspace import Workspace


class HttpApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
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

    def _json(self, method, path, body=None, expected=200, timeout=8):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read())
                self.assertEqual(response.status, expected)
                return payload
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read())
                if exc.code != expected:
                    raise AssertionError(f"{method} {path} expected {expected} got {exc.code}: {payload}") from exc
                return payload
            finally:
                exc.close()

    def test_workspace_turn_creates_task_and_conversation(self):
        payload = self._json("POST", "/api/workspace/turn", {"request": "whoami", "cwd": self.tmp.name})
        self.assertTrue(payload["conversation"]["id"])
        self.assertTrue(payload["task"]["id"].startswith("VTX-"))
        self.assertEqual(payload["plan"]["kind"], "identity")
        self.assertIn(payload["guardian"]["authority"], ("vortex-guardian",))

    def test_conversation_edit_branch_route(self):
        created = self._json("POST", "/api/conversations", {"title": "branch-source"}, expected=201)
        conv_id = created["conversation"]["id"]
        turn = self._json("POST", "/api/workspace/turn", {"request": "whoami", "cwd": self.tmp.name, "conversation_id": conv_id})
        self.assertEqual(turn["conversation"]["id"], conv_id)
        messages = self._json("GET", f"/api/conversations/{conv_id}")["messages"]
        user_msg = next(item for item in messages if item["role"] == "user")
        branch = self._json("POST", f"/api/conversations/{conv_id}/messages/{user_msg['id']}/edit", {"content": "whoami please"}, expected=201)
        self.assertEqual(branch["conversation"]["parent_id"], conv_id)
        self.assertEqual(branch["messages"][0]["content"], "whoami please")

    def test_reject_and_pause_routes(self):
        turn = self._json("POST", "/api/workspace/turn", {"request": "whoami", "cwd": self.tmp.name})
        plan_id = turn["plan"]["id"]
        task_id = turn["task"]["id"]
        rejected = self._json("POST", f"/api/plans/{plan_id}/reject", {"task_id": task_id})
        self.assertTrue(rejected["rejected"])
        self.assertEqual(rejected["task"]["state"], "CANCELLED")
        missing = self._json("POST", "/api/plans/does-not-exist/reject", {}, expected=404)
        self.assertEqual(missing["error"]["code"], "not_found")
        again = self._json("POST", "/api/workspace/turn", {"request": "system health", "cwd": self.tmp.name})
        paused = self._json("POST", f"/api/tasks/{again['task']['id']}/pause", {})
        self.assertEqual(paused["task"]["state"], "PAUSED")

    def test_assessment_only_includes_engagement_operations(self):
        created = self._json("POST", "/api/engagements", {
            "name": "lab",
            "authorization": "ticket-1",
            "targets": ["lab.example.test"],
            "excluded_targets": ["prod.example.test"],
            "owner": "operator",
            "environment": "authorized-lab",
        }, expected=201)
        eng_id = created["engagement"]["id"]
        self.assertEqual(created["engagement"]["excluded_targets"], ["prod.example.test"])
        report = self._json("GET", f"/api/reports/assessment/{eng_id}")
        self.assertEqual(report["report"]["operations"], 0)
        self.assertEqual(report["report"]["engagement"]["id"], eng_id)
        denied = self._json("GET", f"/api/reports/assessment/{eng_id}?format=exe", expected=422)
        self.assertEqual(denied["error"]["code"], "invalid_plan")

    def test_capabilities_and_close_engagement(self):
        caps = self._json("GET", "/api/capabilities")
        self.assertEqual(caps["product"], "VORTEX")
        self.assertIn("typed-plan-execution", caps["implemented"])
        self.assertIn("nuclei-ffuf-nikto-amass-gobuster-adapters", caps["implemented"])
        self.assertIn("plugin-code-execution", caps["intentionally_not_implemented"])
        self.assertIn("sqlmap-msfconsole-execution", caps["unavailable_unless_installed"])
        created = self._json("POST", "/api/engagements", {
            "name": "lab-close", "authorization": "ticket-2", "targets": ["lab.example.test"],
        }, expected=201)
        closed = self._json("POST", f"/api/engagements/{created['engagement']['id']}/close", {})
        self.assertEqual(closed["engagement"]["status"], "closed")

    def test_refresh_health_and_agents_invalidate_deep_lookup_cache(self):
        vtx_backend.clear_probe_caches()
        with patch.object(vtx_backend, "_invalidate_probe_lookups", wraps=vtx_backend._invalidate_probe_lookups) as health_inv:
            self._json("GET", "/api/system/health?fresh=1")
        self.assertGreaterEqual(health_inv.call_count, 1, "health refresh must clear low-level probe caches")
        with patch.object(vtx_backend, "_invalidate_probe_lookups", wraps=vtx_backend._invalidate_probe_lookups) as agents_inv:
            self._json("GET", "/api/agents?fresh=1")
        self.assertGreaterEqual(agents_inv.call_count, 1, "agents refresh must clear low-level probe caches")
        vtx_backend.clear_probe_caches()

    def test_head_static_asset_returns_headers_without_body(self):
        request = urllib.request.Request(self.base + "/assets/app.js", method="HEAD")
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"")
            self.assertGreater(int(response.headers["Content-Length"] or 0), 0)
            self.assertTrue(response.headers.get("Content-Type", "").startswith("text/javascript"))

    def test_static_path_traversal_rejected(self):
        request = urllib.request.Request(self.base + "/assets/../backend/vortex_backend.py")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status = response.status
                body = response.read()
        except urllib.error.HTTPError as exc:
            try:
                status = exc.code
                body = exc.read()
            finally:
                exc.close()
        self.assertIn(status, (404, 400))
        self.assertNotIn(b"ExecutionManager", body)

    def test_task_events_route(self):
        turn = self._json("POST", "/api/workspace/turn", {"request": "whoami", "cwd": self.tmp.name})
        events = self._json("GET", f"/api/tasks/{turn['task']['id']}/events")
        self.assertTrue(events["events"])
        self.assertEqual(events["task"]["id"], turn["task"]["id"])

    def test_dependencies_inventory_and_agent_proposal(self):
        data = self._json("GET", "/api/dependencies")
        deps = data["dependencies"]
        self.assertFalse(deps["auto_install"])
        self.assertGreater(deps["counts"]["missing"], 0)
        self.assertTrue(any(item["id"] == "agent:cai" for item in deps["missing"]))
        proposal = self._json("GET", "/api/dependencies/proposal?id=agent:cai")
        self.assertFalse(proposal["install"]["auto_install"])
        self.assertTrue(proposal["install"].get("message"))
        planned = self._json("POST", "/api/dependencies/plan", {"id": "agent:cai", "cwd": self.tmp.name})
        self.assertFalse(planned["planned"])
        self.assertFalse(planned["auto_install"])
        nmap = self._json("GET", "/api/dependencies/proposal?id=tool:nmap")
        if not nmap["install"].get("installed"):
            apt = self._json("POST", "/api/dependencies/plan", {"id": "tool:nmap", "cwd": self.tmp.name})
            self.assertTrue(apt["planned"])
            self.assertEqual(apt["plan"]["kind"], "package_operation")
            self.assertFalse(apt["auto_install"])

    def test_turn_includes_observation_and_episode_route(self):
        turn = self._json("POST", "/api/workspace/turn", {"request": "whoami", "cwd": self.tmp.name})
        self.assertTrue(turn.get("observation"))
        self.assertTrue(turn["observation"].get("untrusted_output"))
        self.assertIn("vortex-local", (turn.get("council") or {}).get("selected") or [])
        episode = self._json("GET", f"/api/tasks/{turn['task']['id']}/episode")
        self.assertEqual(episode["task"]["id"], turn["task"]["id"])
        self.assertIsNotNone(episode.get("observation"))

    def test_get_plan_redacts_approval_token(self):
        planned = self._json("POST", "/api/plan", {"request": "whoami", "cwd": self.tmp.name})
        self.assertTrue(planned["plan"]["approval_token"])
        fetched = self._json("GET", f"/api/plans/{planned['plan']['id']}")
        self.assertNotIn("approval_token", fetched["plan"])

    def test_execute_without_token_is_rejected(self):
        planned = self._json("POST", "/api/plan", {"request": "whoami", "cwd": self.tmp.name})
        denied = self._json("POST", "/api/execute", {"plan_id": planned["plan"]["id"], "confirm": True, "allow_root": True}, expected=422)
        self.assertEqual(denied["error"]["code"], "invalid_plan")

    def test_http_execute_cannot_grant_root_override(self):
        planned = self._json("POST", "/api/plan", {"request": "whoami", "cwd": self.tmp.name})["plan"]
        with patch("backend.vortex_backend.os.getuid", return_value=0):
            denied = self._json("POST", "/api/execute", {
                "plan_id": planned["id"],
                "confirm": True,
                "approval_token": planned["approval_token"],
                "allow_root": True,
            }, expected=403)
        self.assertEqual(denied["error"]["code"], "confirmation_or_privilege")

    def test_http_backup_stays_inside_data_root(self):
        outside = self._json("POST", "/api/store/backup", {"destination": "/tmp/vortex-exfil.db"}, expected=201)
        path = Path(outside["backup"]["path"])
        self.assertTrue(str(path).startswith(self.tmp.name))
        self.assertIn("/backups/", str(path) + "/")
        self.assertEqual(path.name, "vortex-exfil.db")
        self.assertNotEqual(path.resolve(), Path("/tmp/vortex-exfil.db").resolve())
        self.assertTrue(path.is_file())

    def test_http_rejects_non_object_json_and_string_confirm(self):
        data = json.dumps(["whoami"]).encode()
        request = urllib.request.Request(self.base + "/api/workspace/turn", data=data, method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                status = response.status
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                status = exc.code
                payload = json.loads(exc.read())
            finally:
                exc.close()
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "invalid_plan")
        planned = self._json("POST", "/api/plan", {"request": "whoami", "cwd": self.tmp.name})
        denied = self._json("POST", "/api/execute", {
            "plan_id": planned["plan"]["id"],
            "confirm": "true",
            "approval_token": planned["plan"]["approval_token"],
        }, expected=403)
        self.assertEqual(denied["error"]["code"], "confirmation_or_privilege")

    def test_http_rejects_non_string_cwd_and_non_integer_prune(self):
        bad_cwd = self._json("POST", "/api/workspace/turn", {"request": "whoami", "cwd": 1}, expected=422)
        self.assertEqual(bad_cwd["error"]["code"], "invalid_plan")
        bad_prune = self._json("POST", "/api/store/prune", {"history_days": ["forever"]}, expected=422)
        self.assertEqual(bad_prune["error"]["code"], "invalid_plan")
        ok_prune = self._json("POST", "/api/store/prune", {"history_days": 30, "output_days": 7})
        self.assertEqual(ok_prune["prune"]["history_days"], 30)

    def test_session_rejects_missing_cwd_as_invalid_plan(self):
        payload = self._json("POST", "/api/sessions", {
            "name": "bad-cwd",
            "cwd": "/definitely/missing/vortex-session-dir",
            "cols": 80,
            "rows": 24,
        }, expected=422)
        self.assertEqual(payload["error"]["code"], "invalid_plan")
        self.assertIn("working directory", payload["error"]["message"].lower())

    def test_http_artifact_analyze_stays_inside_data_root(self):
        outside = Path("/etc/hosts")
        if not outside.is_file():
            self.skipTest("/etc/hosts is not present")
        payload = self._json("POST", "/api/artifacts/analyze", {"path": str(outside), "kind": "text"}, expected=422)
        self.assertEqual(payload["error"]["code"], "invalid_plan")
        self.assertIn("allowed", payload["error"]["message"].lower())

    def test_secret_values_never_returned(self):
        saved = self._json("POST", "/api/secrets", {"slot": "ollama_token", "value": "sk-never-echo"})
        self.assertIsNone(saved["secrets"]["values"])
        self.assertIn("ollama_token", saved["secrets"]["configured"])
        listed = self._json("GET", "/api/secrets")
        self.assertIsNone(listed["secrets"]["values"])
        serialized = json.dumps(listed)
        self.assertNotIn("sk-never-echo", serialized)

    def test_http_rejects_non_string_session_input_and_bool_size(self):
        bad_input = self._json("POST", "/api/sessions/deadbeef/input", {"data": ["whoami"]}, expected=422)
        self.assertEqual(bad_input["error"]["code"], "invalid_plan")
        missing = self._json("POST", "/api/sessions/deadbeef/input", {}, expected=422)
        self.assertEqual(missing["error"]["code"], "invalid_plan")
        bad_cols = self._json("POST", "/api/sessions", {"name": "x", "cwd": self.tmp.name, "cols": True, "rows": 30}, expected=422)
        self.assertEqual(bad_cols["error"]["code"], "invalid_plan")
        bad_slot = self._json("POST", "/api/secrets", {"slot": 1, "value": "x"}, expected=422)
        self.assertEqual(bad_slot["error"]["code"], "invalid_plan")

    def test_http_settings_reject_string_booleans(self):
        config_home = Path(self.tmp.name) / "config"
        config_home.mkdir()
        previous = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = str(config_home)
        try:
            denied = self._json("POST", "/api/settings", {"offline": "false"}, expected=422)
            self.assertEqual(denied["error"]["code"], "invalid_plan")
            saved = self._json("POST", "/api/settings", {"offline": True, "profile": "safe"})
            self.assertTrue(saved["settings"]["offline"])
            self.assertFalse(saved["settings"]["auto_low_risk"])
        finally:
            if previous is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = previous

    def test_http_rejects_coerced_plan_id_targets_and_artifact_path(self):
        planned = self._json("POST", "/api/plan", {"request": "whoami", "cwd": self.tmp.name})
        bad_plan = self._json("POST", "/api/execute", {"plan_id": 1, "confirm": True, "approval_token": planned["plan"]["approval_token"]}, expected=422)
        self.assertEqual(bad_plan["error"]["code"], "invalid_plan")
        bad_targets = self._json("POST", "/api/engagements", {"name": "lab", "authorization": "t", "targets": [1]}, expected=422)
        self.assertEqual(bad_targets["error"]["code"], "invalid_plan")
        bad_path = self._json("POST", "/api/artifacts/analyze", {"path": 1, "kind": "text"}, expected=422)
        self.assertEqual(bad_path["error"]["code"], "invalid_plan")

    def test_http_rejects_oversized_request_text(self):
        denied = self._json("POST", "/api/workspace/turn", {"request": "whoami " + ("x" * 8000), "cwd": self.tmp.name}, expected=422)
        self.assertEqual(denied["error"]["code"], "invalid_plan")

    def test_http_rejects_oversized_query_strings(self):
        huge = "a" * 201
        denied = self._json("GET", f"/api/tools/route?q={huge}", expected=422)
        self.assertEqual(denied["error"]["code"], "invalid_plan")
        ok = self._json("GET", "/api/tools/route?q=disk")
        self.assertEqual(ok["route"]["adapter_id"], "linux.filesystem.usage")

    def test_http_rejects_non_integer_session_since(self):
        denied = self._json("GET", "/api/sessions/deadbeef/events?since=abc", expected=422)
        self.assertEqual(denied["error"]["code"], "invalid_plan")
        negative = self._json("GET", "/api/sessions/deadbeef/events?since=-1", expected=422)
        self.assertEqual(negative["error"]["code"], "invalid_plan")
        huge = self._json("GET", "/api/sessions/deadbeef/events?since=" + ("9" * 17), expected=422)
        self.assertEqual(huge["error"]["code"], "invalid_plan")

    def test_http_rejects_unknown_report_format(self):
        denied = self._json("GET", "/api/reports/system?format=exe", expected=422)
        self.assertEqual(denied["error"]["code"], "invalid_plan")
        ok = self._json("GET", "/api/reports/system?format=json")
        self.assertEqual(ok["product"], "VORTEX")
        self.assertEqual(ok["kind"], "system")

    def test_host_tools_and_license_routes(self):
        data = self._json("GET", "/api/tools/host")
        self.assertIn("host_tools", data)
        self.assertIn("counts", data["host_tools"])
        self.assertGreater(data["host_tools"]["counts"]["path_executables"], 0)
        self.assertFalse(data["host_tool_access"])
        license_doc = self._json("GET", "/api/license")
        self.assertEqual(license_doc["spdx"], "MIT")
        self.assertIn("MIT License", license_doc["license"])
        caps = self._json("GET", "/api/capabilities")
        self.assertIn("host-tool-discovery", caps["implemented"])
        self.assertIn("android-apk-client", caps["implemented"])
        self.assertEqual(caps["license"], "MIT")
        rescanned = self._json("POST", "/api/tools/host/rescan", {}, expected=200, timeout=20)
        self.assertIn("host_tools", rescanned)
        self.assertGreaterEqual(rescanned["host_tools"]["counts"]["path_executables"], data["host_tools"]["counts"]["path_executables"])

    def test_mobile_apk_sync_then_download(self):
        built = self._json("POST", "/api/mobile/apk", {}, expected=201, timeout=30)
        self.assertTrue(built["apk"]["ok"])
        self.assertEqual(built["apk"]["license"], "MIT")
        self.assertIn("classes.dex", built["apk"]["contents"])
        request = urllib.request.Request(self.base + "/api/mobile/apk/download")
        with urllib.request.urlopen(request, timeout=20) as response:
            self.assertEqual(response.status, 200)
            body = response.read()
            self.assertGreater(len(body), 1000)
            self.assertTrue(response.headers.get("Content-Type", "").startswith("application/vnd.android.package-archive"))
            self.assertEqual(body[:4], b"PK\x03\x04")

    def test_complete_task_requires_bound_task(self):
        denied = self._json("POST", "/api/operations/missing/complete-task", {"task_id": "VTX-none"}, expected=404)
        self.assertEqual(denied["error"]["code"], "not_found")
        missing_id = self._json("POST", "/api/operations/missing/complete-task", {}, expected=422)
        self.assertEqual(missing_id["error"]["code"], "invalid_plan")


if __name__ == "__main__":
    unittest.main()
