"""Linux desktop .deb packaging."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.debbuild import build_deb, deb_status, frontend_digest
from backend.vortex_backend import APP_VERSION


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, check=False)


class DesktopDebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name
        self.out = Path(self.tmp.name) / "deb"

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)

    def test_build_produces_real_unsigned_deb_with_live_frontend(self):
        result = build_deb(output_dir=self.out)
        self.assertTrue(result["ok"])
        self.assertEqual(result["version"], APP_VERSION)
        self.assertFalse(result["signed"], "the package is unsigned by policy")
        path = Path(result["path"])
        self.assertEqual(path.name, f"linux-vortex-terminal_{APP_VERSION}_all.deb")
        self.assertGreater(path.stat().st_size, 10000)

        info = _run("dpkg-deb", "-I", str(path))
        self.assertEqual(info.returncode, 0, info.stderr)
        self.assertIn("Package: linux-vortex-terminal", info.stdout)
        self.assertIn(f"Version: {APP_VERSION}", info.stdout)

        extract = self.out / "extract"
        extracted = _run("dpkg-deb", "-x", str(path), str(extract))
        self.assertEqual(extracted.returncode, 0, extracted.stderr)
        # The package carries the live frontend, not a stale copy.
        app_js = (extract / "usr" / "share" / "vortex" / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertIn("triggerDownload", app_js)
        self.assertIn("downloadDeb", app_js)
        # Desktop integration: menu entry + icon, operator-started only.
        desktop_entry = (extract / "usr" / "share" / "applications" / "vortex.desktop").read_text(encoding="utf-8")
        self.assertIn("Exec=vortex serve", desktop_entry)
        self.assertTrue((extract / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps" / "vortex.svg").is_file())
        # CLI entry point and man page ship.
        self.assertTrue((extract / "usr" / "bin" / "vortex").is_file())
        self.assertTrue((extract / "usr" / "share" / "man" / "man1" / "vortex.1.gz").is_file())
        # No maintainer scripts: install never starts or creates anything.
        ctrl = subprocess.run(["dpkg-deb", "--ctrl-tarfile", str(path)], capture_output=True, check=False)
        self.assertEqual(ctrl.returncode, 0, ctrl.stderr)
        for script in (b"postinst", b"preinst", b"prerm", b"postrm"):
            self.assertNotIn(script, ctrl.stdout, f"maintainer script {script.decode()} must not ship")

    def test_status_reports_build_after_build(self):
        empty = deb_status()
        self.assertFalse(empty["ok"])
        self.assertIn("message", empty)
        built = build_deb()
        self.assertTrue(built["ok"])
        status = deb_status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["filename"], built["filename"])
        self.assertEqual(status["sha256"], built["sha256"])
        self.assertEqual(status["version"], APP_VERSION)

    def test_rebuild_picks_up_frontend_changes(self):
        frontend = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
        original = frontend.read_text(encoding="utf-8")
        try:
            first = build_deb()["sha256"]
            frontend.write_text(original + "\n<!-- deb-sync-marker -->\n", encoding="utf-8")
            second = build_deb()["sha256"]
            self.assertNotEqual(first, second, "rebuild must package the live tree, not a cached artifact")
        finally:
            frontend.write_text(original, encoding="utf-8")

    def test_frontend_digest_matches_live_tree(self):
        result = build_deb()
        self.assertEqual(result["frontend_digest"], frontend_digest())

    def test_missing_dpkg_deb_is_an_honest_error(self):
        with mock.patch("backend.debbuild.shutil.which", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                build_deb(output_dir=self.out)
            self.assertIn("dpkg-deb", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
