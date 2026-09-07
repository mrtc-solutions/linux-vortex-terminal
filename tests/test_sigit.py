"""SIGIT — Simple Information Gathering Toolkit — reviewed capability catalog.

These tests pin the engagement-gated, never-auto-run, never-fabricate contract
for the 14 reviewed OSINT services and prove the planner surfaces them honestly
without creating an executable command.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.vortex_backend import Store, build_plan, capabilities_document, _load
from backend.workspace import Workspace

SIGIT = _load("tools.sigit")


class SigitCatalogTests(unittest.TestCase):
    def test_catalog_has_exactly_14_reviewed_services(self):
        self.assertEqual(len(SIGIT.SIGIT_SERVICES), 14)
        self.assertEqual(len(SIGIT.SERVICE_ORDER), 14)
        self.assertEqual(len(set(SIGIT.SERVICE_ORDER)), 14)
        for slug in SIGIT.SERVICE_ORDER:
            self.assertIn(slug, SIGIT.SIGIT_SERVICES)
            service = SIGIT.SIGIT_SERVICES[slug]
            self.assertTrue(service["name"], slug)
            self.assertTrue(service["title"], slug)
            self.assertTrue(service["number"], slug)
            self.assertIn(
                service["target_kind"],
                {"username", "phone", "email", "ip", "hostname", "hostname/ip", "url", "github-user"},
            )

    def test_service_listing_is_reviewed_and_never_auto_executed(self):
        listing = SIGIT.service_listing()
        self.assertEqual(len(listing), 14)
        for item in listing:
            self.assertTrue(item["reviewed"])
            self.assertFalse(item["auto_executed"])
            self.assertEqual(item["license"], "MIT")
            self.assertEqual(item["family"], "passive-osint")
            self.assertEqual(item["network"], "outbound-read")
            self.assertEqual(item["risk"], "high")

    def test_safe_adapter_mappings_reference_known_manifests(self):
        from backend.adapter_registry import ADAPTER_MANIFESTS
        for slug, service in SIGIT.SIGIT_SERVICES.items():
            if service["safe_adapter"]:
                self.assertIn(service["safe_adapter"], ADAPTER_MANIFESTS, slug)

    def test_classify_matches_each_service(self):
        samples = {
            "userrecon": "userrecon @octocat",
            "phoneinfo": "phone info for +265991234567",
            "mailfinder": "find email for John Doe",
            "iplocation": "ip location 8.8.8.8",
            "subdomain": "subdomain enumeration for example.com",
            "portscan": "port scanner for example.com",
            "dnsrecon": "dns recon example.com",
            "sslcheck": "ssl check example.com",
            "headers": "security header analysis for example.com",
            "github": "github recon for octocat",
            "breach": "breach check a@example.com",
            "techdetect": "detect tech stack of example.com",
            "reverseip": "reverse ip lookup 1.1.1.1",
        }
        for slug, text in samples.items():
            self.assertEqual(SIGIT.classify_sigit_request(text), slug, text)

    def test_classify_generic_toolkit_and_negatives(self):
        self.assertEqual(SIGIT.classify_sigit_request("sigit"), SIGIT.TOOLKIT)
        self.assertEqual(SIGIT.classify_sigit_request("osint"), SIGIT.TOOLKIT)
        self.assertEqual(SIGIT.classify_sigit_request("information gathering"), SIGIT.TOOLKIT)
        self.assertIsNone(SIGIT.classify_sigit_request("show system health"))
        self.assertIsNone(SIGIT.classify_sigit_request("what user am i"))
        self.assertIsNone(SIGIT.classify_sigit_request("check my nmap notes"))
        self.assertIsNone(SIGIT.classify_sigit_request(""))
        # Reverse-IP must not be misclassified as IP location.
        self.assertEqual(SIGIT.classify_sigit_request("reverse ip lookup 1.1.1.1"), "reverseip")
        self.assertEqual(SIGIT.classify_sigit_request("ip lookup 8.8.8.8"), None)

    def test_mentions_sigit(self):
        self.assertTrue(SIGIT.mentions_sigit("run sigit"))
        self.assertTrue(SIGIT.mentions_sigit("sigit.sh"))
        self.assertFalse(SIGIT.mentions_sigit("whoami"))

    def test_probe_sigit_is_presence_only(self):
        self.assertEqual(SIGIT.probe_sigit({})["state"], "absent")
        probe = SIGIT.probe_sigit({"sigit": "/usr/local/bin/sigit"})
        self.assertEqual(probe["state"], "installed")
        self.assertEqual(probe["executable"], "sigit")
        self.assertEqual(probe["path"], "/usr/local/bin/sigit")
        probe = SIGIT.probe_sigit({"sigit.sh": "/usr/local/bin/sigit.sh"})
        self.assertEqual(probe["state"], "installed")
        self.assertEqual(probe["executable"], "sigit.sh")


class SigitPlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        self.store = Store(Path(self.tmp.name) / "vortex.db")
        self.workspace = Workspace(self.store)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)

    def _engagement(self, engagement_id="sig-eng", targets=("lab.example.test",)):
        self.store.create_engagement({
            "id": engagement_id,
            "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2099-08-25T00:00:00+00:00",
            "name": "lab",
            "authorization": "ticket-1",
            "targets": list(targets),
            "classes": ["reconnaissance"],
            "status": "active",
        })

    def test_requires_engagement_and_never_creates_commands(self):
        plan = build_plan(self.store, "userrecon @octocat", self.tmp.name)
        self.assertEqual(plan["kind"], "osint_tool")
        self.assertEqual(plan["status"], "clarified")
        self.assertEqual(plan["commands"], [])
        self.assertFalse(plan["approval_required"])
        self.assertTrue(any("engagement" in note.lower() for note in plan["notes"]))

    def test_offline_blocks_sigit(self):
        plan = build_plan(self.store, "userrecon @octocat", self.tmp.name, offline=True)
        self.assertEqual(plan["status"], "unavailable")
        self.assertEqual(plan["commands"], [])
        self.assertTrue(any("offline" in note.lower() for note in plan["notes"]))

    def test_missing_sigit_reports_tool_missing(self):
        self._engagement()
        plan = build_plan(self.store, "userrecon @octocat", self.tmp.name, "sig-eng")
        self.assertEqual(plan["status"], "unavailable")
        self.assertIn("sigit", plan["missing_tools"])
        self.assertEqual(plan["commands"], [])

    def test_out_of_scope_host_target_is_rejected(self):
        self._engagement()
        plan = build_plan(self.store, "reverse ip lookup for evil.example.com", self.tmp.name, "sig-eng")
        self.assertEqual(plan["status"], "rejected")
        self.assertEqual(plan["commands"], [])
        self.assertTrue(any("scope" in note.lower() for note in plan["notes"]))

    def test_generic_osint_with_engagement_and_installed_sigit_does_not_crash(self):
        # A bare "osint" mention maps to TOOLKIT (service=None); with an active
        # engagement and an installed TUI it must still return honest PTY
        # guidance instead of dereferencing a missing service entry.
        self._engagement()
        installed = {"state": "installed", "executable": "sigit", "path": "/usr/local/bin/sigit"}
        with patch.object(SIGIT, "probe_sigit", return_value=installed):
            plan = build_plan(self.store, "osint", self.tmp.name, "sig-eng")
        self.assertEqual(plan["status"], "clarified")
        self.assertEqual(plan["commands"], [])
        self.assertTrue(any("pty" in note.lower() for note in plan["notes"]))

    def test_installed_sigit_routes_to_pty_not_fabricated_argv(self):
        self._engagement()
        installed = {"state": "installed", "executable": "sigit", "path": "/usr/local/bin/sigit"}
        with patch.object(SIGIT, "probe_sigit", return_value=installed):
            plan = build_plan(self.store, "run sigit", self.tmp.name, "sig-eng")
        self.assertEqual(plan["status"], "clarified")
        self.assertEqual(plan["commands"], [])
        self.assertTrue(any("pty" in note.lower() for note in plan["notes"]))
        self.assertFalse(plan["approval_required"])

    def test_safe_adapter_equivalent_is_suggested_not_auto_run(self):
        self._engagement()
        installed = {"state": "installed", "executable": "sigit", "path": "/usr/local/bin/sigit"}
        with patch.object(SIGIT, "probe_sigit", return_value=installed):
            plan = build_plan(self.store, "ssl check lab.example.test", self.tmp.name, "sig-eng")
        self.assertEqual(plan["status"], "clarified")
        self.assertEqual(plan["commands"], [])
        self.assertTrue(any("security.http.headers" in note for note in plan["notes"]))

    def test_existing_scanner_requests_are_unchanged(self):
        # Existing typed adapters keep winning: these must NOT become osint_tool.
        self._engagement()
        for request in ("nmap scan lab.example.test", "whois lab.example.test"):
            plan = build_plan(self.store, request, self.tmp.name, "sig-eng")
            self.assertNotEqual(plan["kind"], "osint_tool", request)
            self.assertEqual(plan["kind"], "authorized_engagement", request)

    def test_closed_engagement_is_rejected(self):
        self.store.create_engagement({
            "id": "closed-eng",
            "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2026-08-26T00:00:00+00:00",
            "name": "old", "authorization": "t2", "targets": ["lab.example.test"],
            "classes": ["reconnaissance"], "status": "active",
        })
        # Force expiry by building a plan against an already-expired engagement.
        plan = build_plan(self.store, "userrecon @octocat", self.tmp.name, "closed-eng")
        self.assertEqual(plan["status"], "rejected")
        self.assertEqual(plan["commands"], [])


class SigitCapabilitiesTests(unittest.TestCase):
    def test_capabilities_expose_sigit_catalog(self):
        caps = capabilities_document()
        self.assertIn("sigit-osint-capabilities", caps["implemented"])
        sigit = caps["sigit"]
        self.assertEqual(sigit["toolkit"], "SIGIT — Simple Information Gathering Toolkit (MIT)")
        self.assertEqual(len(sigit["services"]), 14)
        for service in sigit["services"]:
            self.assertFalse(service["auto_executed"])
        self.assertIn("sigit-interactive-tui", caps["unavailable_unless_installed"])

    def test_registry_and_tool_catalog_list_sigit(self):
        from backend.adapter_registry import TOOL_CATALOG
        self.assertIn("sigit", TOOL_CATALOG)
        self.assertEqual(TOOL_CATALOG["sigit"]["family"], "passive-osint")
        from backend.tools.registry import inventory
        sigit = next(item for item in inventory() if item["name"] == "sigit")
        self.assertEqual(sigit["license"], "MIT")
        self.assertEqual(sigit["category"], "passive-osint")
        self.assertEqual(sigit["installation_method"], "operator-manual")

    def test_knowledge_retrieval_has_osint_category(self):
        from backend.knowledge import retrieve
        results = retrieve("osint", limit=6)
        self.assertTrue(any(item["id"] == "osint" for item in results))


if __name__ == "__main__":
    unittest.main()
