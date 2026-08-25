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

    def _json(self, method, path, body=None, expected=200):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read())
                self.assertEqual(response.status, expected)
                return payload
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read())
            if exc.code != expected:
                raise AssertionError(f"{method} {path} expected {expected} got {exc.code}: {payload}") from exc
            return payload

    def test_workspace_turn_creates_task_and_conversation(self):
        payload = self._json("POST", "/api/workspace/turn", {"request": "whoami", "cwd": self.tmp.name})
        self.assertTrue(payload["conversation"]["id"])
        self.assertTrue(payload["task"]["id"].startswith("VTX-"))
        self.assertEqual(payload["plan"]["kind"], "identity")
        self.assertIn(payload["guardian"]["authority"], ("vortex-guardian",))

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

    def test_secret_values_never_returned(self):
        saved = self._json("POST", "/api/secrets", {"slot": "ollama_token", "value": "sk-never-echo"})
        self.assertIsNone(saved["secrets"]["values"])
        self.assertIn("ollama_token", saved["secrets"]["configured"])
        listed = self._json("GET", "/api/secrets")
        self.assertIsNone(listed["secrets"]["values"])
        serialized = json.dumps(listed)
        self.assertNotIn("sk-never-echo", serialized)


if __name__ == "__main__":
    unittest.main()
