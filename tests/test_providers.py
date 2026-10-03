"""Multi-provider AI layer tests.

Every network interaction is served by local mock HTTP servers — no real
provider is contacted. The tests cover: free-only cost protection,
dynamic model discovery with pricing metadata, quota (429) fallback and
cooldown, the three independent Gemini entries sharing two key slots,
local Qwen state reporting, and credential masking.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend.providers import catalog as prov_catalog
from backend.providers import keys as prov_keys
from backend.providers import policy as prov_policy
from backend.providers import registry as prov_registry
from backend.providers.manager import ProviderManager, ProviderError


class MockProvider(BaseHTTPRequestHandler):
    """Programmable provider endpoint: routes -> (status, payload)."""

    routes: dict[str, tuple[int, dict]] = {}
    calls: list[str] = []

    def _reply(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        type(self).calls.append("GET " + self.path)
        for prefix, (code, payload) in type(self).routes.items():
            if self.path.split("?")[0] == prefix or self.path.startswith(prefix):
                return self._reply(code, payload)
        return self._reply(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        type(self).calls.append("POST " + self.path)
        for prefix, (code, payload) in type(self).routes.items():
            if self.path.split("?")[0] == prefix or self.path.startswith(prefix):
                return self._reply(code, payload)
        return self._reply(404, {"error": "not found"})

    def log_message(self, *args):  # silence
        pass


def start_mock(routes: dict[str, tuple[int, dict]]):
    handler = type("Handler", (MockProvider,), {"routes": routes, "calls": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, handler, f"http://127.0.0.1:{server.server_address[1]}"


def chat_payload(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


HYBRID = {"privacy_mode": "hybrid", "free_only_mode": True, "cloud_timeout_seconds": 10,
          "local_chat_timeout_seconds": 15}


class ProviderTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["VORTEX_CONFIG_DIR"] = self.tmp.name
        # Fresh registry + key cache per test.
        prov_registry._REGISTRY = prov_registry.ModelRegistry()
        prov_keys.invalidate_cache()
        self.servers = []
        self.manager = ProviderManager()

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        os.environ.pop("VORTEX_CONFIG_DIR", None)
        for slot in list(prov_keys.KNOWN_KEY_SLOTS):
            os.environ.pop(slot, None)
        prov_keys.invalidate_cache()
        self.tmp.cleanup()

    def mock(self, routes):
        server, handler, url = start_mock(routes)
        self.servers.append(server)
        return handler, url

    def patch_base(self, provider_id: str, url: str):
        patcher = patch.dict(prov_catalog.PROVIDERS_BY_ID[provider_id], {"base_url": url})
        patcher.start()
        self.addCleanup(patcher.stop)

    def set_key(self, slot: str, value: str = "test-secret-key-123456"):
        os.environ[slot] = value
        prov_keys.invalidate_cache()


class PolicyTests(ProviderTestCase):
    def test_free_only_blocks_paid_model(self):
        policy = prov_policy.cost_policy({"free_only_mode": True})
        definition = prov_catalog.provider_def("openrouter")
        allowed, reason = prov_policy.model_allowed(policy, definition, {"id": "x", "free": False}, {})
        self.assertFalse(allowed)
        self.assertIn("free-only", reason)

    def test_free_only_blocks_unknown_pricing(self):
        policy = prov_policy.cost_policy({"free_only_mode": True})
        definition = prov_catalog.provider_def("openrouter")
        allowed, reason = prov_policy.model_allowed(policy, definition, {"id": "x", "free": None}, {})
        self.assertFalse(allowed)

    def test_free_only_allows_verified_zero_dollar_model(self):
        policy = prov_policy.cost_policy({"free_only_mode": True})
        definition = prov_catalog.provider_def("openrouter")
        allowed, _ = prov_policy.model_allowed(policy, definition, {"id": "x:free", "free": True}, {})
        self.assertTrue(allowed)

    def test_unknown_provider_blocked_until_operator_override(self):
        policy = prov_policy.cost_policy({"free_only_mode": True})
        definition = prov_catalog.provider_def("zai")  # free_status unknown
        allowed, reason = prov_policy.provider_allowed(policy, definition, {})
        self.assertFalse(allowed)
        self.assertIn("UNKNOWN", reason)
        allowed, _ = prov_policy.provider_allowed(policy, definition, {"allow_in_free_mode": True})
        self.assertTrue(allowed)

    def test_free_only_setting_cannot_be_bypassed_by_allow_paid(self):
        policy = prov_policy.cost_policy({"free_only_mode": True, "allow_paid_providers": True})
        self.assertFalse(policy["allow_paid_providers"])

    def test_local_models_always_allowed(self):
        policy = prov_policy.cost_policy({"free_only_mode": True})
        definition = prov_catalog.provider_def("ollama-local")
        allowed, _ = prov_policy.model_allowed(policy, definition, None, {})
        self.assertTrue(allowed)


class DiscoveryTests(ProviderTestCase):
    def test_openrouter_pricing_metadata_marks_free_and_paid(self):
        handler, url = self.mock({"/models": (200, {"data": [
            {"id": "qwen/qwen3-coder:free", "name": "Qwen3 Coder (free)",
             "pricing": {"prompt": "0", "completion": "0"}, "context_length": 32768},
            {"id": "openai/gpt-4o", "name": "GPT-4o",
             "pricing": {"prompt": "0.0000025", "completion": "0.00001"}},
        ]})})
        self.patch_base("openrouter", url)
        self.set_key("OPENROUTER_API_KEY")
        models = self.manager.discover_models("openrouter", HYBRID)
        by_id = {item["id"]: item for item in models}
        self.assertTrue(by_id["qwen/qwen3-coder:free"]["free"])
        self.assertFalse(by_id["openai/gpt-4o"]["free"])
        self.assertIn("openrouter/free", by_id)   # pseudo auto-free entry
        self.assertTrue(by_id["openrouter/free"]["free"])
        self.assertTrue(by_id["qwen/qwen3-coder:free"]["verified_at"])

    def test_model_removed_from_catalog_is_marked_retired(self):
        handler, url = self.mock({"/models": (200, {"data": [
            {"id": "old-model:free", "pricing": {"prompt": "0", "completion": "0"}},
        ]})})
        self.patch_base("openrouter", url)
        self.set_key("OPENROUTER_API_KEY")
        self.manager.discover_models("openrouter", HYBRID)
        handler.routes = {"/models": (200, {"data": [
            {"id": "new-model:free", "pricing": {"prompt": "0", "completion": "0"}},
        ]})}
        self.manager.discover_models("openrouter", HYBRID)
        models = prov_registry.registry().get_models("openrouter")
        old = next(item for item in models if item["id"] == "old-model:free")
        self.assertFalse(old["available"])
        self.assertTrue(old["deprecated"])

    def test_groq_models_discovered_dynamically(self):
        handler, url = self.mock({"/models": (200, {"data": [
            {"id": "llama-3.3-70b-versatile", "context_window": 131072},
            {"id": "whisper-large-v3"},
        ]})})
        self.patch_base("groq", url)
        self.set_key("GROQ_API_KEY")
        models = self.manager.discover_models("groq", HYBRID)
        by_id = {item["id"]: item for item in models}
        self.assertIn("llama-3.3-70b-versatile", by_id)
        self.assertIn("chat", by_id["llama-3.3-70b-versatile"]["capabilities"])
        self.assertNotIn("chat", by_id["whisper-large-v3"]["capabilities"])

    def test_gemini_discovery_marks_flash_free_and_pro_paid(self):
        handler, url = self.mock({"/models": (200, {"models": [
            {"name": "models/gemini-3.8-flash", "displayName": "Gemini 3.8 Flash",
             "supportedGenerationMethods": ["generateContent"], "inputTokenLimit": 1000000},
            {"name": "models/gemini-3.1-pro", "displayName": "Gemini 3.1 Pro",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
        ]})})
        self.patch_base("gemini-1", url)
        self.set_key("GEMINI_API_KEY_1")
        models = self.manager.discover_models("gemini-1", HYBRID)
        by_id = {item["id"]: item for item in models}
        self.assertTrue(by_id["gemini-3.8-flash"]["free"])
        self.assertFalse(by_id["gemini-3.1-pro"]["free"])
        self.assertNotIn("embedding-001", by_id)

    def test_discovery_without_key_reports_no_api_key(self):
        with self.assertRaises(ProviderError) as ctx:
            self.manager.discover_models("groq", HYBRID)
        self.assertEqual(ctx.exception.kind, "no_api_key")


class GenerateTests(ProviderTestCase):
    def test_quota_429_causes_cooldown_and_fallback_to_next_free_provider(self):
        groq_handler, groq_url = self.mock({
            "/models": (200, {"data": [{"id": "llama-3.3-70b-versatile"}]}),
            "/chat/completions": (429, {"error": {"message": "rate limit reached"}}),
        })
        or_handler, or_url = self.mock({
            "/models": (200, {"data": [
                {"id": "qwen/qwen3:free", "pricing": {"prompt": "0", "completion": "0"}},
            ]}),
            "/chat/completions": (200, chat_payload("Hello from the free pool.")),
        })
        self.patch_base("groq", groq_url)
        self.patch_base("openrouter", or_url)
        self.set_key("GROQ_API_KEY")
        self.set_key("OPENROUTER_API_KEY")
        result = self.manager.generate([{"role": "user", "content": "hello"}], HYBRID,
                                       provider_id="groq")
        self.assertEqual(result["state"], "responded")
        self.assertEqual(result["provider"], "openrouter")
        kinds = {item["provider"]: item["state"] for item in result["attempts"]}
        self.assertEqual(kinds.get("groq"), "rate_limited")
        self.assertGreater(self.manager._in_cooldown("groq"), 0)
        # Second call: groq is skipped while cooling down.
        result2 = self.manager.generate([{"role": "user", "content": "again"}], HYBRID,
                                        provider_id="groq")
        kinds2 = {item["provider"]: item["state"] for item in result2["attempts"]}
        self.assertEqual(kinds2.get("groq"), "cooling_down")

    def test_free_only_mode_refuses_provider_with_only_paid_models(self):
        handler, url = self.mock({
            "/models": (200, {"data": [
                {"id": "paid-model", "pricing": {"prompt": "0.002", "completion": "0.01"}},
            ]}),
            "/chat/completions": (200, chat_payload("should never be reached")),
        })
        self.patch_base("openrouter", url)
        self.set_key("OPENROUTER_API_KEY")
        self.manager.discover_models("openrouter", HYBRID)
        result = self.manager.generate([{"role": "user", "content": "hi"}], HYBRID,
                                       provider_id="openrouter", allow_fallback=False)
        self.assertEqual(result["state"], "unavailable")
        self.assertIn("All configured free AI providers are currently unavailable.", result["message"])
        # The paid endpoint was never called with a chat request.
        self.assertFalse(any("chat" in call for call in handler.calls))

    def test_explicitly_selected_paid_model_is_blocked(self):
        handler, url = self.mock({
            "/models": (200, {"data": [
                {"id": "paid-model", "pricing": {"prompt": "0.002", "completion": "0.01"}},
                {"id": "ok:free", "pricing": {"prompt": "0", "completion": "0"}},
            ]}),
            "/chat/completions": (200, chat_payload("nope")),
        })
        self.patch_base("openrouter", url)
        self.set_key("OPENROUTER_API_KEY")
        self.manager.discover_models("openrouter", HYBRID)
        result = self.manager.generate([{"role": "user", "content": "hi"}], HYBRID,
                                       provider_id="openrouter", model="paid-model",
                                       allow_fallback=False)
        self.assertEqual(result["state"], "unavailable")
        states = [item["state"] for item in result["attempts"]]
        self.assertIn("blocked_policy", states)
        self.assertFalse(any("chat" in call for call in handler.calls))

    def test_offline_mode_blocks_all_cloud_providers(self):
        self.set_key("OPENROUTER_API_KEY")
        result = self.manager.generate([{"role": "user", "content": "hi"}],
                                       {**HYBRID, "offline": True}, provider_id="openrouter",
                                       allow_fallback=False)
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(result["attempts"][0]["state"], "network_blocked")

    def test_privacy_local_blocks_cloud_with_clear_reason(self):
        self.set_key("OPENROUTER_API_KEY")
        result = self.manager.generate([{"role": "user", "content": "hi"}],
                                       {"privacy_mode": "local"}, provider_id="openrouter",
                                       allow_fallback=False)
        self.assertEqual(result["attempts"][0]["state"], "network_blocked")
        self.assertIn("privacy mode", result["attempts"][0]["detail"])

    def test_disabled_provider_is_never_called(self):
        handler, url = self.mock({"/chat/completions": (200, chat_payload("hi"))})
        self.patch_base("mistral", url)   # mistral is disabled by default
        self.set_key("MISTRAL_API_KEY")
        result = self.manager.generate([{"role": "user", "content": "hi"}], HYBRID,
                                       provider_id="mistral", allow_fallback=False)
        self.assertEqual(result["attempts"][0]["state"], "disabled")
        self.assertEqual(handler.calls, [])


class GeminiTests(ProviderTestCase):
    def _mock_gemini(self, text="Gemini says hi", fail_entry_1=False):
        routes = {
            "/models/": (200, {"candidates": [{"content": {"parts": [{"text": text}]}}]}),
            "/models": (200, {"models": [
                {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            ]}),
        }
        return self.mock(routes)

    def test_three_distinct_entries_share_two_key_slots(self):
        config = self.manager.gemini_config()
        self.assertEqual(len(config), 3)
        self.assertEqual(config["gemini-1"]["key_slot"], "GEMINI_API_KEY_1")
        self.assertEqual(config["gemini-2"]["key_slot"], "GEMINI_API_KEY_2")
        self.assertEqual(config["gemini-3"]["key_slot"], "GEMINI_API_KEY_1")
        # Three distinct model IDs out of the box.
        models = {entry["model"] for entry in config.values()}
        self.assertEqual(len(models), 3)

    def test_key_slot_reassignment_is_persisted(self):
        result = self.manager.configure_gemini("gemini-3", key_slot="GEMINI_API_KEY_2")
        self.assertEqual(result["key_slot"], "GEMINI_API_KEY_2")
        fresh = ProviderManager()
        self.assertEqual(fresh.gemini_config()["gemini-3"]["key_slot"], "GEMINI_API_KEY_2")

    def test_quota_on_entry_one_falls_over_to_entry_two(self):
        discovery = (200, {"models": [
            {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
        ]})
        fail_handler, fail_url = self.mock({
            "/models/": (429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota exceeded"}}),
            "/models": discovery,
        })
        ok_handler, ok_url = self.mock({
            "/models/": (200, {"candidates": [{"content": {"parts": [{"text": "answer from entry two"}]}}]}),
            "/models": discovery,
        })
        self.patch_base("gemini-1", fail_url)
        self.patch_base("gemini-2", ok_url)
        self.set_key("GEMINI_API_KEY_1")
        self.set_key("GEMINI_API_KEY_2", "other-secret-value-654321")
        result = self.manager.generate([{"role": "user", "content": "hi"}], HYBRID,
                                       provider_id="gemini-1")
        self.assertEqual(result["state"], "responded")
        self.assertEqual(result["provider"], "gemini-2")
        self.assertEqual(result["reply"], "answer from entry two")
        # Entry stats are tracked independently.
        self.assertEqual(self.manager._stat("gemini-1")["http_429"], 1)
        self.assertEqual(self.manager._stat("gemini-2")["http_429"], 0)
        self.assertGreater(self.manager._in_cooldown("gemini-1"), 0)
        self.assertEqual(self.manager._in_cooldown("gemini-2"), 0)

    def test_invalid_entry_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.configure_gemini("gemini-9", model="gemini-3.8-flash")
        with self.assertRaises(ValueError):
            self.manager.configure_gemini("gemini-1", key_slot="OPENROUTER_API_KEY")


class LocalQwenTests(ProviderTestCase):
    def test_model_missing_is_distinguished_from_not_running(self):
        handler, url = self.mock({
            "/api/tags": (200, {"models": [{"name": "llama3.2:3b"}]}),
            "/api/ps": (200, {"models": []}),
        })
        status = self.manager.local_status({"ollama_endpoint": url, "local_primary_model": "qwen2.5:3b"})
        self.assertEqual(status["state"], "model_missing")
        self.assertIn("ollama pull qwen2.5:3b", status["message"])

    def test_cold_and_ready_states(self):
        handler, url = self.mock({
            "/api/tags": (200, {"models": [{"name": "qwen2.5:3b"}]}),
            "/api/ps": (200, {"models": []}),
        })
        status = self.manager.local_status({"ollama_endpoint": url})
        self.assertEqual(status["state"], "cold")
        self.assertIn("cold", status["message"])
        handler.routes = dict(handler.routes)
        handler.routes["/api/ps"] = (200, {"models": [{"name": "qwen2.5:3b"}]})
        status = self.manager.local_status({"ollama_endpoint": url})
        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["message"], "Local Qwen ready")

    def test_not_running_reported_distinctly(self):
        status = self.manager.local_status({"ollama_endpoint": "http://127.0.0.1:9"})
        self.assertIn(status["state"], {"ollama_not_running", "ollama_not_installed"})

    def test_local_chat_answers_through_mock_ollama(self):
        handler, url = self.mock({
            "/api/tags": (200, {"models": [{"name": "qwen2.5:3b"}]}),
            "/api/ps": (200, {"models": [{"name": "qwen2.5:3b"}]}),
            "/api/chat": (200, {"message": {"role": "assistant", "content": "sudo elevates privileges."}}),
        })
        result = self.manager.generate([{"role": "user", "content": "Explain what sudo does"}],
                                       {"ollama_endpoint": url, "privacy_mode": "local",
                                        "free_only_mode": True},
                                       provider_id="ollama-local", allow_fallback=False)
        self.assertEqual(result["state"], "responded")
        self.assertEqual(result["provider"], "ollama-local")
        self.assertEqual(result["model"], "qwen2.5:3b")
        self.assertIn("sudo", result["reply"])


class SecurityTests(ProviderTestCase):
    def test_secrets_never_appear_in_snapshot_or_diagnostics(self):
        secret = "sk-very-secret-value-abcdef123456"
        self.set_key("OPENROUTER_API_KEY", secret)
        self.set_key("GEMINI_API_KEY_1", "gm-" + secret)
        snapshot = self.manager.providers_snapshot(HYBRID, probe_local=False)
        diagnostics = self.manager.diagnostics({**HYBRID})
        for blob in (json.dumps(snapshot), diagnostics["text"], json.dumps(diagnostics["snapshot"])):
            self.assertNotIn(secret, blob)
        # Presence booleans only.
        self.assertTrue(snapshot["key_slots"]["OPENROUTER_API_KEY"])
        self.assertFalse(snapshot["key_slots"]["GROQ_API_KEY"])

    def test_redact_secrets_masks_keys_in_error_text(self):
        secret = "super-secret-token-98765"
        self.set_key("GROQ_API_KEY", secret)
        masked = prov_keys.redact_secrets(f"401 unauthorized for Bearer {secret} at ?key={secret}")
        self.assertNotIn(secret, masked)

    def test_provider_error_detail_is_redacted(self):
        secret = "leaky-key-aaaa5555"
        self.set_key("GROQ_API_KEY", secret)
        err = ProviderError("invalid_api_key", f"bad key {secret}")
        self.assertNotIn(secret, err.detail)


class RegistryTests(ProviderTestCase):
    def test_stale_free_verification_degrades_to_unknown(self):
        reg = prov_registry.registry()
        reg.update_models("openrouter", [{"id": "m:free", "free": True,
                                          "verified_at": "2020-01-01T00:00:00Z"}])
        entry = reg.get_models("openrouter")[0]
        entry["verified_at"] = "2020-01-01T00:00:00Z"
        self.assertIsNone(reg.effective_free(entry))

    def test_fresh_free_verification_is_trusted(self):
        reg = prov_registry.registry()
        models = reg.update_models("openrouter", [{"id": "m:free", "free": True}])
        self.assertTrue(reg.effective_free(models[0]))


if __name__ == "__main__":
    unittest.main()
