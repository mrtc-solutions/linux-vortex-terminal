"""Ollama runtime + model management tests.

The manager owns the operator-facing lifecycle the advisory router deliberately
does not: install, service start/stop, pull/cancel/remove, and a merged catalog.
These tests pin the safety invariants (confirmation, offline gating, name
validation, loopback-only) without ever downloading anything.
"""
import json
import os
import subprocess
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
        manager.shutdown(timeout=2)
        with manager._LOCK:
            manager._INSTALL.update({"status": "idle", "error": None, "percent": 0.0, "step": ""})
            for key in ("cancel_event", "thread", "response", "started_mono"):
                manager._INSTALL.pop(key, None)
            manager._JOBS.clear()
            manager._REMOVING.clear()
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

    def test_runtime_status_uses_configured_loopback_endpoint_even_offline(self):
        from backend.config import save_settings
        save_settings({"ollama_endpoint": "http://127.0.0.1:11459", "offline": True})
        with patch("backend.models.manager.ollama_status", return_value={"state": "healthy", "models": [], "version": "test"}) as status_probe:
            status = manager.runtime_status()
        status_probe.assert_called_once_with("http://127.0.0.1:11459", offline=True)
        self.assertEqual(status["endpoint"], "http://127.0.0.1:11459")
        self.assertEqual(status["api_state"], "healthy")
        self.assertTrue(status["platform"]["offline"])
        self.assertEqual(manager._server_env()["OLLAMA_HOST"], "127.0.0.1:11459")

    def test_start_reuses_existing_external_loopback_service(self):
        with patch("backend.models.manager._locate_binary", return_value="/bin/true"), \
             patch("backend.models.manager._api_version", return_value="0.9.9"), \
             patch("backend.models.manager.subprocess.Popen") as popen:
            result = manager.start_server()
        self.assertEqual(result["state"], "external")
        self.assertFalse(result["managed"])
        popen.assert_not_called()

    def test_activate_model_requires_live_exact_tag_and_persists_role(self):
        with patch("backend.models.manager._ollama_tags", return_value=["acme/local:7b"]):
            preference = manager.activate_model("acme/local:7b", "primary")
        self.assertEqual(preference, {"role": "primary", "setting": "model_primary", "model": "acme/local:7b", "state": "active"})
        from backend.config import load_settings
        self.assertEqual(load_settings()["model_primary"], "acme/local:7b")
        with patch("backend.models.manager._ollama_tags", return_value=["other:latest"]):
            with self.assertRaisesRegex(PolicyError, "not installed"):
                manager.activate_model("acme/local:7b", "planner")

    def test_routing_preferences_report_active_family_fallback_and_unavailable(self):
        status = {"models": [{"name": "phi4-mini:latest"}, {"name": "custom:1"}]}
        preferences = manager.routing_preferences(status, {
            "model_primary": "phi4-mini:3.8b", "model_planner": "custom:1",
            "model_fast": "missing:1", "model_specialist": "missing:2",
        })
        self.assertEqual(preferences["primary"]["resolved"], "phi4-mini:latest")
        self.assertTrue(preferences["primary"]["family_fallback"])
        self.assertEqual(preferences["planner"]["state"], "active")
        self.assertEqual(preferences["fast"]["state"], "unavailable")

    def test_install_requires_confirmation(self):
        with self.assertRaises(PermissionError):
            manager.install_ollama(confirm=False)

    def test_unreadable_settings_fail_closed_for_network_mutations(self):
        with patch("backend.models.manager.load_settings", side_effect=OSError("unreadable")):
            self.assertTrue(manager._offline())

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

    def test_remove_is_serialized_against_remove_and_pull(self):
        entered = threading.Event()
        release = threading.Event()
        result = []

        def blocked_run(*_args, **_kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return subprocess.CompletedProcess([], 0, "", "")

        def remove():
            try:
                result.append(manager.remove_model("test/model:1"))
            except Exception as exc:  # pragma: no cover - asserted below
                result.append(exc)

        with patch("backend.models.manager._locate_binary", return_value="/bin/true"), \
             patch("backend.models.manager.subprocess.run", side_effect=blocked_run):
            thread = threading.Thread(target=remove)
            thread.start()
            self.assertTrue(entered.wait(2))
            with self.assertRaisesRegex(PolicyError, "already being removed"):
                manager.remove_model("test/model:1")
            with patch("backend.models.manager._offline", return_value=False):
                with self.assertRaisesRegex(PolicyError, "being removed"):
                    manager.pull_model("test/model:1")
            release.set()
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [{"name": "test/model:1", "removed": True}])
        self.assertNotIn("test/model:1", manager._REMOVING)

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

    def test_safe_tar_members_rejects_extraction_bomb(self):
        import tarfile
        oversized = tarfile.TarInfo("lib/oversized.bin")
        oversized.size = manager._MAX_RUNTIME_EXTRACT_BYTES + 1
        with self.assertRaisesRegex(RuntimeError, "allowed size"):
            manager._safe_tar_members(iter([oversized]))

    def test_runtime_download_uses_unique_temp_and_does_not_follow_predictable_symlink(self):
        import io

        class Response:
            def __init__(self, payload):
                self.headers = {"Content-Length": str(len(payload))}
                self.stream = io.BytesIO(payload)
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, size=-1): return self.stream.read(size)

        directory = Path(self.tmp.name) / "download"
        directory.mkdir()
        destination = directory / "runtime.tgz"
        victim = Path(self.tmp.name) / "victim"
        victim.write_bytes(b"unchanged")
        predictable = destination.with_name(destination.name + ".part")
        predictable.symlink_to(victim)
        payload = b"verified archive bytes"
        job = {"cancel_event": threading.Event(), "downloaded_bytes": 0}
        with patch("backend.models.manager.urllib.request.urlopen", return_value=Response(payload)):
            digest = manager._download_to("https://github.com/ollama/ollama/releases/download/v-test/ollama-linux-amd64.tgz", destination, job)
        self.assertEqual(destination.read_bytes(), payload)
        self.assertEqual(victim.read_bytes(), b"unchanged")
        self.assertTrue(predictable.is_symlink())
        self.assertEqual(len(digest), 64)
        self.assertEqual(list(directory.glob(".runtime.tgz.*.part")), [])

    def test_runtime_download_rejects_oversized_content_length_and_cleans_temp(self):
        class Response:
            headers = {"Content-Length": "5"}
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _size=-1): return b"12345"

        directory = Path(self.tmp.name) / "bounded-download"
        destination = directory / "runtime.tgz"
        job = {"cancel_event": threading.Event()}
        with patch.object(manager, "_MAX_RUNTIME_ARCHIVE_BYTES", 4), \
             patch("backend.models.manager.urllib.request.urlopen", return_value=Response()):
            with self.assertRaisesRegex(PolicyError, "allowed download size"):
                manager._download_to("https://github.com/ollama/ollama/releases/download/v-test/ollama-linux-amd64.tgz", destination, job)
        self.assertFalse(destination.exists())
        self.assertEqual(list(directory.glob(".*.part")), [])

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

    def test_binary_lookup_ignores_ambient_writable_path(self):
        ambient = Path(self.tmp.name) / "ambient-bin"
        ambient.mkdir()
        malicious = ambient / "ollama"
        malicious.write_text("#!/bin/sh\nexit 0\n")
        malicious.chmod(0o755)
        with patch.dict(os.environ, {"PATH": str(ambient)}):
            located = manager._locate_binary()
        self.assertNotEqual(located, str(malicious.resolve()))

    def test_managed_binary_must_be_regular_owner_only_executable(self):
        managed = Path(self.tmp.name) / "managed-ollama"
        victim = Path(self.tmp.name) / "other-binary"
        victim.write_text("binary")
        victim.chmod(0o755)
        managed.symlink_to(victim)
        self.assertIsNone(manager._trusted_executable(managed, managed=True))
        managed.unlink()
        managed.write_text("binary")
        managed.chmod(0o775)
        self.assertIsNone(manager._trusted_executable(managed, managed=True))
        managed.chmod(0o755)
        self.assertEqual(manager._trusted_executable(managed, managed=True), str(managed.resolve()))

    def test_ollama_api_json_reader_rejects_oversized_response(self):
        class Response:
            headers = {"Content-Length": str(65 * 1024)}
            def read(self, _size=-1):
                raise AssertionError("oversized announced body must not be read")
        with self.assertRaisesRegex(ValueError, "allowed size"):
            manager._read_json_response(Response(), limit=64 * 1024)

    def test_latest_runtime_asset_requires_exact_official_sha256_metadata(self):
        import io

        class Response:
            def __init__(self, payload):
                self.headers = {"Content-Length": str(len(payload))}
                self.stream = io.BytesIO(payload)
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, size=-1): return self.stream.read(size)
            def geturl(self): return manager._RELEASE_API

        asset = {
            "name": "ollama-linux-amd64.tar.zst",
            "browser_download_url": "https://github.com/ollama/ollama/releases/download/v1.2.3/ollama-linux-amd64.tar.zst",
            "digest": "sha256:" + ("a" * 64), "size": 1234,
        }
        payload = json.dumps({"draft": False, "prerelease": False, "assets": [asset]}).encode()
        with patch("backend.models.manager.urllib.request.urlopen", return_value=Response(payload)):
            selected = manager._latest_runtime_asset("amd64")
        self.assertEqual(selected["name"], asset["name"])
        self.assertEqual(selected["sha256"], "a" * 64)
        self.assertEqual(selected["size"], 1234)

        asset["digest"] = None
        malformed = json.dumps({"draft": False, "prerelease": False, "assets": [asset]}).encode()
        with patch("backend.models.manager.urllib.request.urlopen", return_value=Response(malformed)):
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                manager._latest_runtime_asset("amd64")

    def test_runtime_download_rejects_unreviewed_redirect_and_truncation(self):
        import io

        class Response:
            def __init__(self, payload, final_url, content_length=None):
                self.headers = {} if content_length is None else {"Content-Length": str(content_length)}
                self.stream = io.BytesIO(payload)
                self.final_url = final_url
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, size=-1): return self.stream.read(size)
            def geturl(self): return self.final_url

        destination = Path(self.tmp.name) / "downloads" / "runtime.tgz"
        source_url = "https://github.com/ollama/ollama/releases/download/v-test/ollama-linux-amd64.tgz"
        job = {"cancel_event": threading.Event()}
        redirected = Response(b"secret", "http://169.254.169.254/latest/meta-data")
        with patch("backend.models.manager.urllib.request.urlopen", return_value=redirected):
            with self.assertRaisesRegex(PolicyError, "redirected"):
                manager._download_to(source_url, destination, job)
        self.assertFalse(destination.exists())

        truncated = Response(b"abc", source_url)
        with patch("backend.models.manager.urllib.request.urlopen", return_value=truncated):
            with self.assertRaisesRegex(RuntimeError, "ended before"):
                manager._download_to(source_url, destination, job, expected_size=4)
        self.assertFalse(destination.exists())

    def test_reviewed_runtime_install_verifies_extracts_publishes_and_rescans(self):
        import hashlib
        import io
        import shutil
        import tarfile

        source = Path(self.tmp.name) / "official.tgz"
        binary_payload = b"#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo 'ollama version test'; exit 0; fi\nsleep 30\n"
        with tarfile.open(source, "w:gz") as tar:
            info = tarfile.TarInfo("bin/ollama")
            info.size = len(binary_payload)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(binary_payload))
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        asset = {
            "name": "ollama-linux-amd64.tgz",
            "url": "https://github.com/ollama/ollama/releases/download/v-test/ollama-linux-amd64.tgz",
            "sha256": digest, "size": source.stat().st_size,
        }

        def download(_url, destination, _job, *, expected_size=None):
            self.assertEqual(expected_size, source.stat().st_size)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            return digest

        with patch("backend.models.manager._locate_binary", return_value=None), \
             patch("backend.models.manager._latest_runtime_asset", return_value=asset), \
             patch("backend.models.manager._download_to", side_effect=download), \
             patch("backend.models.manager.start_server", return_value={"state": "running"}), \
             patch("backend.models.manager._wait_for_api", return_value="test-api"):
            manager.install_ollama(confirm=True)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and manager._INSTALL.get("status") not in {"completed", "failed"}:
                time.sleep(0.02)
        status = manager._public_install()
        self.assertEqual(status["status"], "completed", status)
        self.assertIs(status["checksum_verified"], True)
        self.assertEqual(status["api_verified"], "test-api")
        published = Path(self.tmp.name) / "ollama" / "bin" / "ollama"
        self.assertTrue(published.is_file())
        self.assertIn("ollama version test", manager._short_timeout_versions(str(published)) or "")
        with patch("backend.models.manager.ollama_status", return_value={"state": "healthy", "reason": None, "models": [], "version": "test-api"}):
            rescanned = manager.runtime_status()
        self.assertTrue(rescanned["installed"])
        self.assertEqual(rescanned["path"], str(published.resolve()))
        self.assertEqual(list(Path(self.tmp.name).glob(".ollama-install-*")), [])

    def test_runtime_checksum_failure_never_replaces_existing_install(self):
        managed = Path(self.tmp.name) / "ollama"
        (managed / "bin").mkdir(parents=True)
        existing = managed / "bin" / "ollama"
        existing.write_bytes(b"existing verified runtime")
        asset = {
            "name": "ollama-linux-amd64.tgz",
            "url": "https://github.com/ollama/ollama/releases/download/v-test/ollama-linux-amd64.tgz",
            "sha256": "a" * 64, "size": 3,
        }

        def download(_url, destination, _job, **_kwargs):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"bad")
            return "b" * 64

        with patch("backend.models.manager._locate_binary", return_value=None), \
             patch("backend.models.manager._latest_runtime_asset", return_value=asset), \
             patch("backend.models.manager._download_to", side_effect=download), \
             patch("backend.models.manager._extract_runtime_archive") as extract:
            manager.install_ollama(confirm=True)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and manager._INSTALL.get("status") not in {"completed", "failed"}:
                time.sleep(0.02)
        self.assertEqual(manager._INSTALL["status"], "failed")
        self.assertIs(manager._INSTALL["checksum_verified"], False)
        extract.assert_not_called()
        self.assertEqual(existing.read_bytes(), b"existing verified runtime")

    def test_install_network_failure_is_classified(self):
        def boom(url, destination, job, **_kwargs):
            raise urllib.error.URLError("network down")

        asset = {"name": "ollama-linux-amd64.tgz", "url": "https://github.com/ollama/ollama/releases/download/v-test/ollama-linux-amd64.tgz", "sha256": "a" * 64, "size": 1024}
        with patch("backend.models.manager._latest_runtime_asset", return_value=asset), \
             patch("backend.models.manager._download_to", side_effect=boom):
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

    def test_runtime_install_can_cancel_without_leaking_internal_objects(self):
        entered = threading.Event()

        def blocked(_url, _destination, job, **_kwargs):
            entered.set()
            while not job["cancel_event"].is_set():
                time.sleep(0.01)
            raise InterruptedError("cancelled")

        asset = {"name": "ollama-linux-amd64.tgz", "url": "https://github.com/ollama/ollama/releases/download/v-test/ollama-linux-amd64.tgz", "sha256": "a" * 64, "size": 1024}
        with patch("backend.models.manager._locate_binary", return_value=None), \
             patch("backend.models.manager._latest_runtime_asset", return_value=asset), \
             patch("backend.models.manager._download_to", side_effect=blocked):
            started = manager.install_ollama(confirm=True)
            self.assertTrue(entered.wait(2))
            self.assertNotIn("cancel_event", started)
            self.assertNotIn("thread", started)
            self.assertTrue(manager.cancel_install()["cancelled"])
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                with manager._LOCK:
                    status = manager._INSTALL.get("status")
                if status == "cancelled":
                    break
                time.sleep(0.02)
            self.assertEqual(status, "cancelled")
            json.loads(canonical(manager.runtime_status()))

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

    def test_pull_start_and_catalog_state_are_json_safe(self):
        fake = Path(self.tmp.name) / "fake-ollama-json"
        fake.write_text("#!/bin/sh\nsleep 0.2\necho '{\"status\":\"success\"}' >&2\n")
        fake.chmod(0o755)
        with patch("backend.models.manager._locate_binary", return_value=str(fake)), \
             patch("backend.models.manager._ollama_tags", return_value=["test/json:1"]):
            started = manager.pull_model("test/json:1")
            encoded = json.loads(canonical({"download": started, "catalog": manager.catalog()}))
            self.assertEqual(encoded["download"]["name"], "test/json:1")
            self.assertNotIn("cancel_event", encoded["download"])
            self.assertNotIn("thread", encoded["download"])
            self._wait_job("test/json:1", {"completed", "failed"})

    def test_cancel_terminates_quiet_pull_and_worker(self):
        fake = Path(self.tmp.name) / "fake-ollama-silent"
        fake.write_text("#!/bin/sh\nsleep 30\n")
        fake.chmod(0o755)
        with patch("backend.models.manager._locate_binary", return_value=str(fake)):
            manager.pull_model("test/cancel:1")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                with manager._LOCK:
                    proc = (manager._JOBS.get("test/cancel:1") or {}).get("proc")
                if proc is not None:
                    break
                time.sleep(0.02)
            result = manager.cancel_download("test/cancel:1")
            self.assertTrue(result["cancelled"])
            job = self._wait_job("test/cancel:1", {"cancelled", "failed"}, timeout=3)
        self.assertEqual(job.get("status"), "cancelled")
        thread = job.get("thread")
        if thread is not None:
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())

    def test_cancel_during_preflight_never_launches_pull_process(self):
        entered = threading.Event()
        release = threading.Event()

        def blocked_storage(*_args):
            entered.set()
            self.assertTrue(release.wait(3))

        with patch("backend.models.manager._locate_binary", return_value="/bin/true"), \
             patch("backend.models.manager._check_storage", side_effect=blocked_storage), \
             patch("backend.models.manager.subprocess.Popen") as popen:
            manager.pull_model("phi4-mini:3.8b")
            self.assertTrue(entered.wait(2))
            result = manager.cancel_download("phi4-mini:3.8b")
            self.assertTrue(result["cancelled"])
            release.set()
            job = self._wait_job("phi4-mini:3.8b", {"cancelled", "failed"}, timeout=3)
        self.assertEqual(job.get("status"), "cancelled")
        popen.assert_not_called()

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

    def test_malformed_progress_cannot_crash_or_orphan_pull_worker(self):
        fake = Path(self.tmp.name) / "fake-ollama-malformed"
        fake.write_text(
            "#!/bin/sh\n"
            "echo '[]' >&2\n"
            "echo '{\"status\":\"downloading\",\"total\":\"not-a-number\",\"completed\":{}}' >&2\n"
            "echo '{\"status\":\"success\"}' >&2\n"
        )
        fake.chmod(0o755)
        with patch("backend.models.manager._locate_binary", return_value=str(fake)), \
             patch("backend.models.manager._ollama_tags", return_value=["test/malformed:1"]):
            manager.pull_model("test/malformed:1")
            job = self._wait_job("test/malformed:1", {"completed", "failed"})
        self.assertEqual(job.get("status"), "completed")
        self.assertNotIn("proc", job)
        self.assertNotIn("thread", job)

    def test_model_verification_rejects_prefix_collision(self):
        fake = Path(self.tmp.name) / "fake-ollama-prefix"
        fake.write_text("#!/bin/sh\necho '{\"status\":\"success\"}' >&2\n")
        fake.chmod(0o755)
        with patch("backend.models.manager._locate_binary", return_value=str(fake)), \
             patch("backend.models.manager._ollama_tags", return_value=["test/model:10"]):
            manager.pull_model("test/model:1")
            job = self._wait_job("test/model:1", {"completed", "failed"})
        self.assertEqual(job.get("status"), "failed")
        self.assertEqual(job.get("failure_reason"), "verification_failed")

    def test_model_download_concurrency_and_history_are_bounded(self):
        with manager._LOCK:
            manager._JOBS.update({
                "active/one:1": {"status": "downloading"},
                "active/two:1": {"status": "verifying"},
            })
        with patch("backend.models.manager._offline", return_value=False), \
             patch("backend.models.manager._locate_binary", return_value="/bin/true"):
            with self.assertRaisesRegex(PolicyError, "already active"):
                manager.pull_model("active/three:1")
        with manager._LOCK:
            manager._JOBS.clear()
            for index in range(manager._MAX_JOBS + 3):
                manager._JOBS[f"old/model-{index}:1"] = {"status": "completed"}
            manager._prune_jobs_locked()
            self.assertLess(len(manager._JOBS), manager._MAX_JOBS)

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
        self.handler.executor.shutdown()
        self.handler.sessions.shutdown()
        try:
            vtx_backend._load("models.manager").shutdown(timeout=2)
        except Exception:
            pass
        with manager._LOCK:
            manager._INSTALL.update({"status": "idle", "error": None, "percent": 0.0, "step": ""})
            for key in ("cancel_event", "thread", "response", "started_mono"):
                manager._INSTALL.pop(key, None)
            manager._JOBS.clear()
            manager._REMOVING.clear()
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

    def test_install_prepares_reviewed_zstd_prerequisite_before_download(self):
        handler_manager = vtx_backend._load("models.manager")
        runtime = {
            "installed": False,
            "platform": {"zstd_available": False, "offline": False},
        }
        with patch.object(handler_manager, "runtime_status", return_value=runtime), \
             patch.object(handler_manager, "install_ollama") as install:
            payload = self._json(
                "POST", "/api/ollama/install",
                {"confirm": True, "cwd": self.tmp.name}, expected=200,
            )
        install.assert_not_called()
        self.assertTrue(payload["planned"])
        self.assertEqual(payload["install"]["status"], "dependency_required")
        self.assertEqual(payload["prerequisite"]["apt_package"], "zstd")
        self.assertEqual(payload["plan"]["kind"], "package_operation")
        mutation = payload["plan"]["commands"][-2]
        self.assertEqual(mutation["argv"], ["apt-get", "--assume-yes", "--no-remove", "install", "zstd"])
        self.assertEqual(mutation["privilege"], "root-required")

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

    def test_successful_pull_route_is_json_safe_and_records_custom_role(self):
        fake = Path(self.tmp.name) / "fake-ollama-pull-http"
        fake.write_text("#!/bin/sh\nsleep 0.2\necho '{\"status\":\"success\"}' >&2\n")
        fake.chmod(0o755)
        handler_manager = vtx_backend._load("models.manager")
        with patch.object(handler_manager, "_locate_binary", return_value=str(fake)), \
             patch.object(handler_manager, "_ollama_tags", return_value=["acme/custom:7b"]):
            payload = self._json("POST", "/api/ollama/models/pull", {"name": "acme/custom:7b", "role": "planner"}, expected=202)
            self.assertEqual(payload["download"]["name"], "acme/custom:7b")
            self.assertNotIn("cancel_event", payload["download"])
            self.assertNotIn("thread", payload["download"])
            self.assertEqual(payload["preference"], {"role": "planner", "setting": "model_planner", "model": "acme/custom:7b", "state": "pending_verification"})
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                state = handler_manager.downloads().get("acme/custom:7b", {})
                if state.get("status") in {"completed", "failed"}:
                    break
                time.sleep(0.03)
            self.assertEqual(state.get("status"), "completed")
            self.assertEqual(state.get("preference_state"), "integrated")
            from backend.config import load_settings
            self.assertEqual(load_settings()["model_planner"], "acme/custom:7b")

    def test_activate_installed_model_role_route(self):
        handler_manager = vtx_backend._load("models.manager")
        with patch.object(handler_manager, "_ollama_tags", return_value=["acme/custom:7b"]):
            payload = self._json("POST", "/api/ollama/models/activate", {"name": "acme/custom:7b", "role": "specialist"})
        self.assertEqual(payload["preference"]["state"], "active")
        self.assertEqual(payload["preference"]["role"], "specialist")
        missing = self._json("POST", "/api/ollama/models/activate", {"name": "acme/custom:7b"}, expected=422)
        self.assertIn("role", missing["error"]["message"])

    def test_invalid_model_role_is_rejected_before_pull_starts(self):
        handler_manager = vtx_backend._load("models.manager")
        with patch.object(handler_manager, "pull_model", wraps=handler_manager.pull_model) as pull:
            payload = self._json("POST", "/api/ollama/models/pull", {"name": "acme/custom:7b", "role": "root"}, expected=422)
        self.assertIn("model role", payload["error"]["message"])
        pull.assert_called_once_with("acme/custom:7b", role="root")
        self.assertNotIn("acme/custom:7b", handler_manager.downloads())

    def test_install_cancel_route_is_json_safe(self):
        handler_manager = vtx_backend._load("models.manager")
        with handler_manager._LOCK:
            handler_manager._INSTALL["status"] = "downloading"
            handler_manager._INSTALL["cancel_event"] = threading.Event()
            handler_manager._INSTALL["thread"] = threading.current_thread()
        payload = self._json("POST", "/api/ollama/install/cancel", {}, expected=200)
        self.assertTrue(payload["install"]["cancelled"])
        self.assertEqual(payload["install"]["status"], "cancelling")

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
