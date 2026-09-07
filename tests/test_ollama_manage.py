"""Ollama runtime + model management tests.

The manager owns the operator-facing lifecycle the advisory router deliberately
does not: install, service start/stop, pull/cancel/remove, and a merged catalog.
These tests pin the safety invariants (confirmation, offline gating, name
validation, loopback-only) without ever downloading anything.
"""
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend import vortex_backend as vtx_backend
from backend.models import manager
from backend.vortex_backend import ExecutionManager, PolicyError, SessionManager, Store, VortexHandler, canonical
from backend.workspace import Workspace


class _FakeOllamaApi(BaseHTTPRequestHandler):
    version = "0.9.9"
    tags = ["phi4-mini:3.8b", "llama3.2:3b"]

    def log_message(self, *args):
        return

    def do_GET(self):
        if self.path.startswith("/api/version"):
            body = json.dumps({"version": self.version}).encode()
        elif self.path.startswith("/api/tags"):
            body = json.dumps({"models": [{"name": name} for name in self.tags]}).encode()
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class OllamaManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        self._previous_config_home = os.environ.get("XDG_CONFIG_HOME")
        config_home = Path(self.tmp.name) / "config"
        config_home.mkdir(parents=True, exist_ok=True)
        os.environ["XDG_CONFIG_HOME"] = str(config_home)

    def tearDown(self):
        with manager._LOCK:
            manager._INSTALL.update({"status": "idle", "error": None, "percent": 0.0, "step": ""})
            manager._JOBS.clear()
            proc = manager._SERVER.get("proc")
            manager._SERVER.update({"proc": None, "state": "stopped", "logs": __import__("collections").deque(maxlen=200)})
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)
        if self._previous_config_home is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._previous_config_home

    def test_runtime_status_is_well_formed_without_ollama(self):
        with patch("backend.models.manager.ollama_status", return_value={"state": "unavailable", "reason": "stub", "models": [], "version": None}):
            status = manager.runtime_status()
        self.assertIs(status["installed"], False)
        self.assertEqual(status["endpoint"], "http://127.0.0.1:11434")
        self.assertIn("server", status)
        self.assertIn("install", status)
        self.assertIn("platform", status)
        self.assertIsInstance(status["platform"]["supported_arch"], bool)

    def test_install_requires_confirmation(self):
        with self.assertRaises(PermissionError):
            manager.install_ollama(confirm=False)

    def test_install_is_blocked_in_offline_mode(self):
        with patch("backend.models.manager._offline", return_value=True):
            with self.assertRaises(PolicyError):
                manager.install_ollama(confirm=True)

    def test_pull_rejects_invalid_names(self):
        for bad in ("", "bad name!", "a" * 161, "foo/bar baz", "//double", "model:tag:extra"):
            with self.assertRaises(ValueError):
                manager.pull_model(bad)

    def test_pull_accepts_catalog_and_custom_names(self):
        for good in ("phi4-mini:3.8b", "llama3.2:3b", "namespace/model:tag", "gemma3:4b"):
            # Without an Ollama binary the pull is gated, which proves the name
            # passed validation rather than being rejected.
            with patch("backend.models.manager._offline", return_value=False), \
                 patch("backend.models.manager._locate_binary", return_value=None):
                with self.assertRaises(PolicyError):
                    manager.pull_model(good)

    def test_pull_is_blocked_in_offline_mode(self):
        with patch("backend.models.manager._offline", return_value=True):
            with self.assertRaises(PolicyError):
                manager.pull_model("phi4-mini:3.8b")

    def test_remove_rejects_invalid_names(self):
        for bad in ("", "bad name!", "a" * 161, "foo/bar baz"):
            with self.assertRaises(ValueError):
                manager.remove_model(bad)

    def test_remove_requires_installed_binary(self):
        with patch("backend.models.manager._locate_binary", return_value=None):
            with self.assertRaises(PolicyError):
                manager.remove_model("phi4-mini:3.8b")

    def test_catalog_merges_curated_pool_with_state(self):
        with patch("backend.models.manager.ollama_status", return_value={"state": "healthy", "reason": None, "version": "0.9.9", "models": [{"name": "phi4-mini:3.8b", "size": 1}]}):
            payload = manager.catalog()
        names = {item["name"] for item in payload["items"]}
        self.assertTrue({"phi4-mini:3.8b", "qwen3:4b", "llama3.2:3b", "gemma3:4b"} <= names)
        phi = next(item for item in payload["items"] if item["name"] == "phi4-mini:3.8b")
        self.assertTrue(phi["installed"])
        self.assertFalse(phi["optional"])
        gemma = next(item for item in payload["items"] if item["name"] == "gemma3:4b")
        self.assertTrue(gemma["optional"])
        self.assertIn("downloads", payload)

    def test_download_state_is_empty_when_idle(self):
        self.assertEqual(manager.downloads(), {})

    def test_failure_reason_classification(self):
        self.assertEqual(manager._failure_reason(PermissionError()), "permission")
        self.assertEqual(manager._failure_reason(urllib.error.URLError("boom")), "network")
        no_space = OSError(28, "No space left on device")
        self.assertEqual(manager._failure_reason(no_space), "storage")
        self.assertEqual(manager._failure_reason(RuntimeError("x")), "unknown")

    def test_safe_tar_members_filters_traversal_and_non_files(self):
        import io
        import tarfile
        root = Path(self.tmp.name) / "ollama"
        root.mkdir()
        archive = root / "pkg.tgz"
        with tarfile.open(archive, "w:gz") as tar:
            def add(name, payload=b"x", kind="file"):
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                if kind == "symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = "/etc/passwd"
                    info.size = 0
                    tar.addfile(info)
                    return
                if kind == "dir":
                    info.type = tarfile.DIRTYPE
                    info.size = 0
                    tar.addfile(info)
                    return
                tar.addfile(info, io.BytesIO(payload))
            add("bin/ollama", b"ollama-binary")
            add("lib/libggml.so", b"lib")
            add("/etc/passwd", b"absolute")
            add("../escape", b"traversal")
            add("bin/../../escape2", b"traversal2")
            add("bin/link", kind="symlink")
            add("lib", kind="dir")
        with tarfile.open(archive, "r:gz") as tar:
            members = manager._safe_tar_members(tar)
        names = {m.name for m in members}
        self.assertEqual(names, {"bin/ollama", "lib/libggml.so"}, names)
        # The resolved targets must all be accepted as inside the install root.
        self.assertEqual(len(manager._safe_extract_targets(root, members)), 2)

    def test_safe_extract_targets_rejects_sibling_prefix_escape(self):
        import tarfile
        root = Path(self.tmp.name) / "ollama"
        root.mkdir()
        # A symlinked parent directory that points to a sibling sharing the
        # root's name prefix: the resolved target is outside the install root
        # even though a naive substring check would accept it.
        sibling = Path(self.tmp.name) / "ollama-evil"
        sibling.mkdir()
        (root / "bin").symlink_to(sibling)
        escaped = tarfile.TarInfo("bin/ollama")
        with self.assertRaises(RuntimeError):
            manager._safe_extract_targets(root, [escaped])
        # A genuinely inside member is accepted.
        (root / "bin").unlink()
        (root / "bin").mkdir()
        inside = tarfile.TarInfo("bin/ollama")
        self.assertEqual(manager._safe_extract_targets(root, [inside]), [inside])

    def test_check_storage_raises_when_disk_is_too_small(self):
        with patch("backend.models.manager._disk_free_gb", return_value=0.3):
            with self.assertRaises(PolicyError):
                manager._check_storage(2.0, "model test/model:1")

    def test_check_storage_passes_when_disk_is_enough(self):
        with patch("backend.models.manager._disk_free_gb", return_value=8.0):
            manager._check_storage(2.0, "model test/model:1")

    def test_update_rate_computes_speed_and_eta(self):
        job = {"started_mono": time.monotonic() - 2.0, "downloaded_bytes": 2000, "total_bytes": 10000}
        manager._update_rate(job)
        self.assertGreaterEqual(job["speed_bps"], 500)
        self.assertLessEqual(job["speed_bps"], 1500)
        self.assertIsNotNone(job["eta_seconds"])
        self.assertGreater(job["eta_seconds"], 0)

    def test_api_version_and_tags_read_loopback(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllamaApi)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_port}"
            self.assertEqual(manager._api_version(endpoint), "0.9.9")
            tags = manager._ollama_tags(endpoint)
            self.assertIn("phi4-mini:3.8b", tags)
            self.assertIn("llama3.2:3b", tags)
        finally:
            server.shutdown()
            server.server_close()

    def test_install_network_failure_is_classified(self):
        def boom(url, destination, job):
            raise urllib.error.URLError("network down")

        with patch("backend.models.manager._download_to", side_effect=boom):
            manager.install_ollama(confirm=True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with manager._LOCK:
                status = manager._INSTALL.get("status")
            if status == "failed":
                break
            time.sleep(0.05)
        with manager._LOCK:
            self.assertEqual(manager._INSTALL["status"], "failed")
            self.assertEqual(manager._INSTALL["failure_reason"], "network")

    def _wait_job(self, name, wanted, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with manager._LOCK:
                job = dict(manager._JOBS.get(name) or {})
            if job.get("status") in wanted:
                return job
            time.sleep(0.05)
        with manager._LOCK:
            return dict(manager._JOBS.get(name) or {})

    def test_pull_parses_progress_and_verifies(self):
        fake = Path(self.tmp.name) / "fake-ollama"
        fake.write_text(
            "#!/bin/sh\n"
            "echo '{\"status\":\"pulling manifest\"}' >&2\n"
            "echo '{\"status\":\"downloading\",\"total\":100,\"completed\":50}' >&2\n"
            "echo '{\"status\":\"downloading\",\"total\":100,\"completed\":100}' >&2\n"
            "echo '{\"status\":\"success\"}' >&2\n"
            "exit 0\n"
        )
        fake.chmod(0o755)
        locate = patch("backend.models.manager._locate_binary", return_value=str(fake))
        tags = patch("backend.models.manager._ollama_tags", return_value=["test/model:1"])
        locate.start(); tags.start()
        try:
            manager.pull_model("test/model:1")
            job = self._wait_job("test/model:1", {"completed", "failed"})
        finally:
            locate.stop(); tags.stop()
        self.assertEqual(job.get("status"), "completed")
        self.assertEqual(job.get("percent"), 100.0)
        self.assertEqual(job.get("total_bytes"), 100)

    def test_server_start_stop_returns_json_safe_summary(self):
        # The HTTP surface serializes the start/stop result with canonical().
        # The raw _SERVER dict holds a live Popen and a log deque, neither of
        # which is JSON-serializable; the public result must not leak them.
        fake = Path(self.tmp.name) / "fake-ollama-serve"
        fake.write_text("#!/bin/sh\nsleep 30\n")
        fake.chmod(0o755)
        locate = patch("backend.models.manager._locate_binary", return_value=str(fake))
        locate.start()
        try:
            started = manager.start_server()
            payload = json.loads(canonical({"server": started}))
            self.assertEqual(payload["server"]["state"], "running")
            self.assertIs(payload["server"]["managed"], True)
            self.assertNotIn("proc", payload["server"])
            self.assertIsInstance(payload["server"]["logs"], list)
            stopped = manager.stop_server()
            payload = json.loads(canonical({"server": stopped}))
            self.assertEqual(payload["server"]["state"], "stopped")
            self.assertIs(payload["server"]["managed"], False)
            self.assertIsInstance(payload["server"]["logs"], list)
        finally:
            locate.stop()
            manager.stop_server()

    def test_pull_reports_verification_failure(self):
        fake = Path(self.tmp.name) / "fake-ollama-2"
        fake.write_text("#!/bin/sh\necho '{\"status\":\"success\"}' >&2\nexit 0\n")
        fake.chmod(0o755)
        locate = patch("backend.models.manager._locate_binary", return_value=str(fake))
        tags = patch("backend.models.manager._ollama_tags", return_value=["other/model:1"])
        locate.start(); tags.start()
        try:
            manager.pull_model("test/model:1")
            job = self._wait_job("test/model:1", {"failed", "completed"})
        finally:
            locate.stop(); tags.stop()
        self.assertEqual(job.get("status"), "failed")
        self.assertEqual(job.get("failure_reason"), "verification_failed")


class OllamaHttpRoutesTests(unittest.TestCase):
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
        with manager._LOCK:
            manager._INSTALL.update({"status": "idle", "error": None, "percent": 0.0, "step": ""})
            manager._JOBS.clear()
            proc = manager._SERVER.get("proc")
            manager._SERVER.update({"proc": None, "state": "stopped"})
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
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
            try:
                payload = json.loads(exc.read())
                if exc.code != expected:
                    raise AssertionError(f"{method} {path} expected {expected} got {exc.code}: {payload}") from exc
                return payload
            finally:
                exc.close()

    def test_get_ollama_status_and_catalog(self):
        with patch("backend.models.manager.ollama_status", return_value={"state": "unavailable", "reason": "stub", "models": [], "version": None}):
            payload = self._json("GET", "/api/ollama")
        self.assertIn("ollama", payload)
        self.assertIn("models", payload)
        self.assertIs(payload["ollama"]["installed"], False)
        self.assertIn("items", payload["models"])

    def test_install_without_confirm_is_denied(self):
        payload = self._json("POST", "/api/ollama/install", {"confirm": False}, expected=403)
        self.assertIn("confirmation", payload["error"]["message"].lower())

    def test_pull_without_name_is_rejected(self):
        payload = self._json("POST", "/api/ollama/models/pull", {}, expected=422)
        self.assertIn("model name", payload["error"]["message"].lower())

    def test_pull_with_invalid_name_is_rejected(self):
        payload = self._json("POST", "/api/ollama/models/pull", {"name": "bad name!"}, expected=422)
        self.assertIn("model name", payload["error"]["message"].lower())

    def test_pull_without_ollama_is_policy_denied(self):
        payload = self._json("POST", "/api/ollama/models/pull", {"name": "phi4-mini:3.8b"}, expected=422)
        self.assertIn("ollama", payload["error"]["message"].lower())

    def test_remove_without_ollama_is_policy_denied(self):
        payload = self._json("POST", "/api/ollama/models/remove", {"name": "phi4-mini:3.8b"}, expected=422)
        self.assertIn("ollama", payload["error"]["message"].lower())

    def test_cancel_without_name_is_rejected(self):
        payload = self._json("POST", "/api/ollama/models/cancel", {}, expected=422)
        self.assertIn("model name", payload["error"]["message"].lower())

    def test_server_start_stop_routes_are_json_safe(self):
        # Regression: the start/stop routes previously returned the raw
        # _SERVER dict (Popen + deque) through _json/canonical and answered
        # HTTP 500 even though the service actually started/stopped.
        fake = Path(self.tmp.name) / "fake-ollama-serve-http"
        fake.write_text("#!/bin/sh\nsleep 30\n")
        fake.chmod(0o755)
        # The HTTP handler resolves the manager via vortex_backend._load, which
        # can be a distinct module instance from backend.models.manager; patch
        # the instance the route actually uses.
        handler_manager = vtx_backend._load("models.manager")
        locate = patch.object(handler_manager, "_locate_binary", return_value=str(fake))
        locate.start()
        try:
            payload = self._json("POST", "/api/ollama/server/start", {}, expected=200)
            self.assertEqual(payload["server"]["state"], "running")
            self.assertIs(payload["server"]["managed"], True)
            payload = self._json("POST", "/api/ollama/server/stop", {}, expected=200)
            self.assertEqual(payload["server"]["state"], "stopped")
            self.assertIs(payload["server"]["managed"], False)
        finally:
            locate.stop()
            handler_manager.stop_server()


if __name__ == "__main__":
    unittest.main()
