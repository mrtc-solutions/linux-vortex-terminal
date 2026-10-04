import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.bootstrap import collect


class BootstrapTests(unittest.TestCase):
    def test_report_is_json_safe_and_has_low_memory_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dist").mkdir()
            (root / "dist" / "index.html").write_text("ok", encoding="utf-8")
            with patch("backend.bootstrap._mem_mb", return_value=(4096, 2048)), patch(
                "backend.bootstrap.os.cpu_count", return_value=2
            ), patch("backend.bootstrap._version", side_effect=lambda command, args=("--version",): f"{command} 1"):
                report = collect(root)
            self.assertEqual(report["profile"], "low-memory")
            self.assertEqual(report["hardware"]["logical_cpus"], 2)
            json.dumps(report)
            self.assertIn("javascript_dependencies", {item["name"] for item in report["checks"]})

    def test_missing_build_dependencies_explain_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("backend.bootstrap._version", return_value=None), patch(
                "backend.bootstrap._mem_mb", return_value=(4096, 2048)
            ), patch("backend.bootstrap.os.cpu_count", return_value=2):
                report = collect(Path(tmp))
            self.assertFalse(report["ready"])
            self.assertIn("npm ci", report["next"])
            missing = {item["name"]: item for item in report["checks"] if item["state"] == "missing"}
            self.assertIn("node", missing)
            self.assertIn("next_action", missing["node"])


if __name__ == "__main__":
    unittest.main()
