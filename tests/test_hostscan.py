"""Host-tool discovery and operator-enabled Kali PATH access."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.tools import hostscan
from backend.vortex_backend import Store, build_plan, _load


class HostScanUnitTests(unittest.TestCase):
    def test_kali_catalog_covers_core_tools(self):
        for name in ("nmap", "nuclei", "wpscan", "lynis", "hydra", "aircrack-ng", "searchsploit"):
            self.assertIn(name, hostscan.KALI_CATALOG)
            self.assertTrue(hostscan.KALI_CATALOG[name]["family"])

    def test_parse_argv_rejects_metacharacters(self):
        self.assertIsNone(hostscan.parse_host_argv("run lynis && rm -rf /", "lynis"))
        self.assertEqual(hostscan.parse_host_argv("lynis --help", "lynis"), ["lynis", "--help"])
        self.assertEqual(hostscan.parse_host_argv("run wpscan --url https://lab.test", "wpscan"), ["wpscan", "--url", "https://lab.test"])

    def test_match_help_is_local(self):
        found = {"lynis": "/usr/bin/lynis"}
        match = hostscan.match_request("lynis --help", found)
        self.assertEqual(match["status"], "ok")
        self.assertTrue(match["help_only"])
        self.assertEqual(match["network_class"], "no-network")
        self.assertEqual(match["adapter_id"], "linux.host.help")
        self.assertFalse(match["needs_engagement"])

    def test_match_network_tool_needs_engagement(self):
        found = {"wpscan": "/usr/bin/wpscan"}
        match = hostscan.match_request("run wpscan --url https://lab.example.test", found)
        self.assertEqual(match["status"], "ok")
        self.assertTrue(match["needs_engagement"])
        self.assertEqual(match["network_class"], "outbound-read")
        self.assertEqual(match["adapter_id"], "linux.host.tool")

    def test_denylist_and_missing(self):
        denied = hostscan.match_request("run rm -rf /tmp", {"rm": "/bin/rm"})
        self.assertEqual(denied["status"], "rejected")
        missing = hostscan.match_request("run wpscan --help", {})
        self.assertEqual(missing["status"], "unavailable")

    def test_interpreter_code_is_clarified(self):
        found = {"python3": "/usr/bin/python3"}
        match = hostscan.match_request("run python3 -c print(1)", found)
        self.assertEqual(match["status"], "clarified")
        help_ok = hostscan.match_request("python3 --version", found)
        self.assertEqual(help_ok["status"], "ok")
        self.assertTrue(help_ok["help_only"])

    def test_discovered_tools_need_explicit_run(self):
        found = {"unusual-tool": "/usr/bin/unusual-tool"}
        self.assertIsNone(hostscan.match_request("check unusual-tool notes", found))
        match = hostscan.match_request("run unusual-tool --help", found)
        self.assertEqual(match["status"], "ok")

    def test_scan_sees_real_path_executables(self):
        scan = hostscan.scan_host_tools(persist=False, use_cache=False)
        self.assertGreater(scan["counts"]["path_executables"], 0)
        names = {item["name"] for item in scan["tools"]}
        self.assertTrue({"ls", "cat", "python3"} & names)


class HostToolAccessPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        os.environ["XDG_CONFIG_HOME"] = str(Path(self.tmp.name) / "config")
        Path(os.environ["XDG_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)
        self.store = Store(Path(self.tmp.name) / "vortex.db")

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)
        os.environ.pop("XDG_CONFIG_HOME", None)

    def test_disabled_access_does_not_plan_unknown_tools(self):
        from backend.config import save_settings
        save_settings({"host_tool_access": False})
        with patch("backend.tools.hostscan.list_path_executables", return_value={"lynis": "/usr/bin/lynis"}):
            plan = build_plan(self.store, "lynis --help", self.tmp.name)
        self.assertNotEqual(plan.get("kind"), "host_tool")
        self.assertFalse(plan.get("commands"))

    def test_enabled_access_plans_local_help(self):
        from backend.config import save_settings
        save_settings({"host_tool_access": True, "profile": "safe"})
        fake = {
            "name": "lynis",
            "state": "installed",
            "path": "/usr/bin/lynis",
            "realpath": "/usr/bin/lynis",
            "sha256": "abc",
            "device": 1,
            "inode": 1,
            "version": "3",
        }
        planner_hostscan = _load("tools.hostscan")
        with patch.object(planner_hostscan, "list_path_executables", return_value={"lynis": "/usr/bin/lynis"}), \
             patch("backend.vortex_backend.probe_executable", return_value=fake):
            plan = build_plan(self.store, "lynis --help", self.tmp.name)
        self.assertEqual(plan["kind"], "host_tool")
        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["commands"][0]["adapter_id"], "linux.host.help")
        self.assertEqual(plan["commands"][0]["network_class"], "no-network")
        self.assertEqual(plan["commands"][0]["argv"][0], "lynis")

    def test_enabled_network_tool_requires_engagement(self):
        from backend.config import save_settings
        save_settings({"host_tool_access": True})
        fake = {
            "name": "wpscan",
            "state": "installed",
            "path": "/usr/bin/wpscan",
            "realpath": "/usr/bin/wpscan",
            "sha256": "abc",
            "device": 1,
            "inode": 1,
            "version": "3",
        }
        planner_hostscan = _load("tools.hostscan")
        with patch.object(planner_hostscan, "list_path_executables", return_value={"wpscan": "/usr/bin/wpscan"}), \
             patch("backend.vortex_backend.probe_executable", return_value=fake):
            plan = build_plan(self.store, "run wpscan --url https://lab.example.test", self.tmp.name)
        self.assertEqual(plan["kind"], "host_tool")
        self.assertEqual(plan["status"], "clarified")
        self.assertFalse(plan.get("commands"))


if __name__ == "__main__":
    unittest.main()
