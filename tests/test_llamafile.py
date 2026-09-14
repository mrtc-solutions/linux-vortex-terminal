"""llamafile provider tests (real code paths, no network, no real weights).

Covers: honest unavailable states, filename/path validation, offline gating,
GGUF + fused import validation, endpoint loopback enforcement, chat + probe
against a real loopback stub server, managed server lifecycle with a stub
executable, model activation, and router integration (llamafile-first
advisory with honest fallback when absent).
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend.models import llamafile
from backend.vortex_backend import PolicyError


class _FakeLlamafileServer(BaseHTTPRequestHandler):
    model_id = "test-model.gguf"
    reply_text = json.dumps({
        "fact_summary": "stub summary", "meaning": "stub", "unknowns": "",
        "next_steps": [], "caution": "", "status_alignment": "observed-success",
    })
    empty_reply = False

    def log_message(self, *args):
        return

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            body = json.dumps({"data": [{"id": self.model_id}]}).encode()
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            self.send_response(404); self.end_headers(); return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(length, 1024 * 1024))
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError:
            payload = {}
        self.server.last_request = payload  # type: ignore[attr-defined]
        content = "" if self.empty_reply else self.reply_text
        body = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _free_port() -> int:
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


STUB_RUNNER = """#!/usr/bin/env python3
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
port = 18080
args = sys.argv[1:]
for index, token in enumerate(args):
    if token == "--port" and index + 1 < len(args):
        port = int(args[index + 1])
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return
    def do_GET(self):
        if self.path.startswith("/v1/models"):
            body = json.dumps({"data": [{"id": "stub-model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()
HTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""


class LlamafileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old_env = {key: os.environ.get(key) for key in ("VORTEX_DATA_DIR", "VORTEX_CONFIG_DIR", "VORTEX_MODELS_DIR")}
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        config_dir = Path(self.tmp.name) / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        os.environ["VORTEX_CONFIG_DIR"] = str(config_dir)
        models_dir = Path(self.tmp.name) / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        os.environ["VORTEX_MODELS_DIR"] = str(models_dir)
        self.addCleanup(self._restore_env)
        llamafile.set_test_binary(None)
        llamafile.set_test_chat(None)
        llamafile.cancel_install()
        self.addCleanup(llamafile.set_test_binary, None)
        self.addCleanup(llamafile.set_test_chat, None)

    def _restore_env(self):
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _write_gguf(self, name="tiny-3b-q4.gguf"):
        path = Path(self.tmp.name) / "incoming" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"GGUF" + (3).to_bytes(4, "little") + b"\x00" * 64)
        return path

    def _start_fake(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeLlamafileServer)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return server, f"http://127.0.0.1:{port}"

    # -- honest unavailable states --------------------------------------

    def test_status_without_binary_is_honest(self):
        snapshot = llamafile.status({"ai_enabled": True})
        self.assertEqual(snapshot["provider"], "llamafile")
        self.assertEqual(snapshot["state"], "unavailable")
        self.assertIn("not installed", snapshot["reason"])
        self.assertFalse(snapshot["binary"]["present"])

    def test_status_disabled(self):
        snapshot = llamafile.status({"ai_enabled": False})
        self.assertEqual(snapshot["state"], "disabled")

    # -- validation -------------------------------------------------------

    def test_hostile_filenames_rejected(self):
        for hostile in ("../x.gguf", "..\\x.gguf", ".hidden.gguf", "a/b.gguf", "", "x" * 200, "model.bin", "notes.txt"):
            with self.subTest(name=hostile[:20]):
                with self.assertRaises(ValueError):
                    llamafile.validate_model_name(hostile)
        self.assertEqual(llamafile.validate_model_name("tiny-3b-q4.gguf"), "tiny-3b-q4.gguf")
        self.assertEqual(llamafile.validate_model_name("fused-4b.llamafile"), "fused-4b.llamafile")

    def test_endpoint_must_be_loopback(self):
        for hostile in ("http://10.0.0.1:8080", "https://127.0.0.1:8080", "http://example.com:8080",
                        "http://127.0.0.1:99999", "http://user@127.0.0.1:8080", "gopher://127.0.0.1:70"):
            with self.subTest(endpoint=hostile):
                with self.assertRaises(ValueError):
                    llamafile._loopback_endpoint(hostile)
        self.assertEqual(llamafile._loopback_endpoint("http://127.0.0.1:8080"), "http://127.0.0.1:8080")
        self.assertEqual(llamafile._loopback_endpoint("http://localhost:9000"), "http://127.0.0.1:9000")

    def test_loopback_probe_and_chat_ignore_proxy_env(self):
        _, endpoint = self._start_fake()
        poison = {
            "http_proxy": "http://127.0.0.1:9/", "https_proxy": "http://127.0.0.1:9/",
            "HTTP_PROXY": "http://127.0.0.1:9/", "HTTPS_PROXY": "http://127.0.0.1:9/",
        }
        with patch.dict(os.environ, poison):
            os.environ.pop("no_proxy", None)
            os.environ.pop("NO_PROXY", None)
            health = llamafile.probe(endpoint)
            self.assertTrue(health.get("ok"), health)
            reply = llamafile.chat(
                [{"role": "user", "content": "hi"}],
                "test-model.gguf",
                {"llamafile_endpoint": endpoint},
                timeout=10.0,
            )
        self.assertIn("stub summary", reply["text"])

    # -- install gating ----------------------------------------------------

    def test_install_requires_confirmation(self):
        result = llamafile.install(False, {"offline": False})
        self.assertEqual(result["status"], "confirm_required")
        self.assertEqual(result["version"], llamafile.LLAMAFILE_VERSION)

    def test_install_blocked_offline(self):
        result = llamafile.install(True, {"offline": True})
        self.assertEqual(result["status"], "blocked")

    def test_install_offline_never_dials(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("offline must not dial")):
            result = llamafile.install(True, {"offline": True})
        self.assertEqual(result["status"], "blocked")

    # -- import -------------------------------------------------------------

    def test_import_gguf_registers_directory(self):
        source = self._write_gguf()
        result = llamafile.import_model(str(source))
        self.assertEqual(result["kind"], "gguf")
        self.assertEqual(result["name"], source.name)
        names = {item["name"] for item in llamafile.list_models()}
        self.assertIn(source.name, names)

    def test_import_rejects_corrupt_gguf(self):
        bad = Path(self.tmp.name) / "incoming" / "corrupt.gguf"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"XXXX" + b"\x00" * 64)
        with self.assertRaises(PolicyError):
            llamafile.import_model(str(bad))

    def test_import_rejects_relative_path(self):
        with self.assertRaises(ValueError):
            llamafile.import_model("relative/tiny.gguf")

    def test_import_and_remove_fused(self):
        source = Path(self.tmp.name) / "incoming" / "fused-4b.llamafile"
        source.parent.mkdir(parents=True, exist_ok=True)
        with open(source, "wb") as handle:
            handle.write(b"MZ")
            handle.write(b"\x00" * (2 * 1024 * 1024))
        result = llamafile.import_model(str(source))
        self.assertEqual(result["kind"], "fused")
        names = {item["name"] for item in llamafile.list_models() if item["kind"] == "fused"}
        self.assertIn("fused-4b.llamafile", names)
        removed = llamafile.remove_model("fused-4b.llamafile")
        self.assertEqual(removed["state"], "removed")
        names = {item["name"] for item in llamafile.list_models() if item["kind"] == "fused"}
        self.assertNotIn("fused-4b.llamafile", names)

    def test_import_rejects_tiny_fused(self):
        source = Path(self.tmp.name) / "incoming" / "tiny.llamafile"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"MZ" + b"\x00" * 100)
        with self.assertRaises(PolicyError):
            llamafile.import_model(str(source))

    def test_remove_gguf_refused_with_guidance(self):
        source = self._write_gguf()
        llamafile.import_model(str(source))
        with self.assertRaises(PolicyError):
            llamafile.remove_model(source.name)

    def test_remove_unknown_model(self):
        with self.assertRaises(PolicyError):
            llamafile.remove_model("ghost-9b.llamafile")

    # -- probe + chat against a real loopback stub ---------------------------

    def test_probe_healthy_and_down(self):
        _, endpoint = self._start_fake()
        health = llamafile.probe(endpoint)
        self.assertTrue(health["ok"])
        self.assertIn("test-model.gguf", health["models"])
        down = llamafile.probe("http://127.0.0.1:9")
        self.assertFalse(down["ok"])

    def test_chat_round_trip(self):
        _, endpoint = self._start_fake()
        settings = {"ai_enabled": True, "llamafile_endpoint": endpoint, "llamafile_model": "test-model.gguf"}
        reply = llamafile.chat([{"role": "user", "content": "hi"}], "test-model.gguf", settings, timeout=10)
        self.assertIn("stub summary", reply["text"])
        self.assertEqual(reply["engine"], "llamafile-server")
        self.assertGreaterEqual(reply["latency_ms"], 0)

    def test_chat_empty_reply_is_honest(self):
        _FakeLlamafileServer.empty_reply = True
        self.addCleanup(setattr, _FakeLlamafileServer, "empty_reply", False)
        _, endpoint = self._start_fake()
        settings = {"ai_enabled": True, "llamafile_endpoint": endpoint}
        with self.assertRaises(PolicyError):
            llamafile.chat([{"role": "user", "content": "hi"}], "test-model.gguf", settings, timeout=10)

    def test_chat_without_server_is_honest(self):
        with self.assertRaises(PolicyError):
            llamafile.chat([{"role": "user", "content": "hi"}], "x.gguf", {"ai_enabled": True}, timeout=5)

    # -- managed server lifecycle with a stub executable ----------------------

    def _write_stub_runner(self):
        stub = Path(self.tmp.name) / "stub-llamafile"
        stub.write_text(STUB_RUNNER)
        stub.chmod(0o755)
        return stub

    def test_server_lifecycle_with_stub(self):
        stub = self._write_stub_runner()
        llamafile.set_test_binary(str(stub))
        source = self._write_gguf()
        llamafile.import_model(str(source))
        llamafile.activate_model(source.name)
        started = llamafile.server_start(source.name, {"ai_enabled": True, "llamafile_model": source.name}, timeout=30)
        self.assertEqual(started["state"], "running")
        self.assertTrue(started["endpoint"].startswith("http://127.0.0.1:"))
        self.addCleanup(llamafile.server_stop)
        state = llamafile.server_state({"ai_enabled": True})
        self.assertEqual(state["state"], "running")
        # Second start reuses the running server instead of spawning another.
        again = llamafile.server_start(source.name, {"ai_enabled": True}, timeout=30)
        self.assertEqual(again["pid"], started["pid"])
        stopped = llamafile.server_stop()
        self.assertEqual(stopped["state"], "stopped")
        state = llamafile.server_state({"ai_enabled": True})
        self.assertEqual(state["state"], "stopped")

    def test_server_start_without_model_is_honest(self):
        llamafile.set_test_binary(str(self._write_stub_runner()))
        with self.assertRaises(PolicyError):
            llamafile.server_start(None, {"ai_enabled": True}, timeout=5)

    def test_server_start_without_binary_is_honest(self):
        source = self._write_gguf()
        llamafile.import_model(str(source))
        with self.assertRaises(PolicyError):
            llamafile.server_start(source.name, {"ai_enabled": True}, timeout=5)

    def test_server_start_waits_for_inflight_start(self):
        llamafile._write_json(llamafile._pid_path(), {
            "pid": os.getpid(), "endpoint": "http://127.0.0.1:9",
            "model": "slow.gguf", "kind": "gguf",
        })
        state = llamafile.server_state({"ai_enabled": True})
        self.assertEqual(state["state"], "starting")
        started = time.monotonic()
        with self.assertRaisesRegex(PolicyError, "did not answer within the startup window"):
            llamafile.server_start(None, {"ai_enabled": True}, timeout=5)
        self.assertGreaterEqual(time.monotonic() - started, 4.0)

    # -- activation -----------------------------------------------------------

    def test_activate_unknown_model(self):
        with self.assertRaises(PolicyError):
            llamafile.activate_model("ghost-9b.gguf")

    def test_activate_imported_model(self):
        source = self._write_gguf()
        llamafile.import_model(str(source))
        result = llamafile.activate_model(source.name)
        self.assertEqual(result["state"], "active")
        self.assertEqual(result["provider"], "llamafile")
        snapshot = llamafile.status({"ai_enabled": True, "llamafile_model": source.name})
        self.assertEqual(snapshot["active_model"], source.name)

    # -- router integration ----------------------------------------------------

    def test_router_prefers_healthy_llamafile(self):
        from backend.models.router import advise, choose_route, model_status
        _FakeLlamafileServer.model_id = "tiny-3b-q4.gguf"
        self.addCleanup(setattr, _FakeLlamafileServer, "model_id", "test-model.gguf")
        _, endpoint = self._start_fake()
        source = self._write_gguf()
        llamafile.import_model(str(source))
        settings = {"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9",
                    "llamafile_endpoint": endpoint, "llamafile_model": source.name}
        snapshot = model_status(settings)
        self.assertEqual(snapshot["llamafile"]["state"], "healthy")
        self.assertEqual(snapshot["fuzzy"]["winner"], "llamafile")
        route = choose_route("hello", phase="conversation", settings=settings, status=snapshot)
        self.assertEqual(route["primary_provider"], "llamafile")
        llamafile.set_test_chat(lambda messages, model: _FakeLlamafileServer.reply_text)
        result = advise("hello", phase="conversation", settings=settings)
        self.assertEqual(result["state"], "responded")
        self.assertEqual(result["provider"], "llamafile")

    def test_router_uses_external_server_without_registered_model(self):
        # No GGUF import and no binary: an operator-configured loopback
        # llamafile server alone must still serve advisory through the
        # model it actually serves. Uses the real HTTP chat path.
        from backend.models.router import advise, choose_route, model_status
        _FakeLlamafileServer.model_id = "external-3b-q4"
        self.addCleanup(setattr, _FakeLlamafileServer, "model_id", "test-model.gguf")
        _, endpoint = self._start_fake()
        settings = {"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9",
                    "llamafile_endpoint": endpoint, "model_timeout_seconds": 10}
        snapshot = model_status(settings)
        self.assertEqual(snapshot["llamafile"]["state"], "healthy")
        self.assertEqual(snapshot["fuzzy"]["winner"], "llamafile")
        route = choose_route("hello", phase="conversation", settings=settings, status=snapshot)
        self.assertEqual(route["primary_provider"], "llamafile")
        self.assertEqual(route["selected"][0]["model"], "external-3b-q4")
        result = advise("hello", phase="conversation", settings=settings)
        self.assertEqual(result["state"], "responded")
        self.assertEqual(result["provider"], "llamafile")
        self.assertEqual(result["synthesis"]["fact_summary"], "stub summary")

    def test_chat_and_server_state_merge_saved_endpoint(self):
        # Partial settings dicts (e.g. {"model_timeout_seconds": 5}) must
        # still resolve the saved llamafile_endpoint for chat + probes.
        from backend.config import save_settings
        _FakeLlamafileServer.model_id = "saved-endpoint-model"
        self.addCleanup(setattr, _FakeLlamafileServer, "model_id", "test-model.gguf")
        _, endpoint = self._start_fake()
        save_settings({"llamafile_endpoint": endpoint})
        state = llamafile.server_state({"model_timeout_seconds": 5})
        self.assertEqual(state["state"], "external")
        self.assertEqual(state["endpoint"], endpoint)
        result = llamafile.chat([{"role": "user", "content": "hi"}], "saved-endpoint-model",
                                {"model_timeout_seconds": 5}, timeout=10)
        self.assertIn("stub summary", result["text"])

    def test_router_falls_back_when_llamafile_absent(self):
        from backend.models.router import model_status
        settings = {"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9"}
        snapshot = model_status(settings)
        self.assertEqual(snapshot["llamafile"]["state"], "unavailable")
        self.assertNotEqual(snapshot["fuzzy"]["winner"], "llamafile")


if __name__ == "__main__":
    unittest.main()
