"""Android APK sync and packaging."""
from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from backend.mobile.apkbuild import build_apk, sync_payload
from backend.mobile.axml import encode_manifest
from backend.mobile.dexwrite import build_webview_dex


class ApkBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VORTEX_DATA_DIR"] = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("VORTEX_DATA_DIR", None)

    def test_axml_magic_and_package(self):
        raw = encode_manifest(version_name="0.2.20")
        self.assertEqual(raw[:4], b"\x03\x00\x08\x00")
        self.assertIn("io.vortex.mobile".encode("utf-16le"), raw)
        self.assertIn("VORTEX".encode("utf-16le"), raw)

    def test_dex_header_checksum(self):
        dex = build_webview_dex("http://192.0.2.10:8765/")
        self.assertTrue(dex.startswith(b"dex\n035\x00"))
        self.assertGreater(len(dex), 0x70)
        self.assertIn(b"io/vortex/mobile/MainActivity", dex)
        self.assertIn(b"http://192.0.2.10:8765/", dex)

    def test_sync_copies_live_frontend_and_license(self):
        dest = Path(self.tmp.name) / "sync"
        result = sync_payload("http://127.0.0.1:8765/", dest)
        self.assertIn("index.html", result["copied"])
        self.assertTrue((dest / "www" / "index.html").is_file())
        self.assertTrue((dest / "www" / "app.js").is_file())
        self.assertTrue((dest / "LICENSE").is_file())
        self.assertIn("MIT", (dest / "LICENSE").read_text(encoding="utf-8"))
        self.assertEqual((dest / "sidecar.txt").read_text(encoding="utf-8").strip(), "http://127.0.0.1:8765/")

    def test_build_apk_is_signed_zip_with_synced_frontend(self):
        out = Path(self.tmp.name) / "vortex.apk"
        result = build_apk(sidecar_url="http://192.0.2.8:4173/", output=out)
        self.assertTrue(result["ok"])
        self.assertTrue(out.is_file())
        self.assertGreater(result["size_bytes"], 1000)
        self.assertEqual(result["license"], "MIT")
        self.assertTrue(result["signed"])
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
            for required in (
                "AndroidManifest.xml",
                "classes.dex",
                "assets/www/index.html",
                "assets/www/app.js",
                "assets/www/workspace.js",
                "assets/LICENSE",
                "META-INF/MANIFEST.MF",
                "META-INF/CERT.SF",
                "META-INF/CERT.RSA",
            ):
                self.assertIn(required, names, required)
            dex = zf.read("classes.dex")
            self.assertTrue(dex.startswith(b"dex\n035\x00"))
            self.assertIn(b"http://192.0.2.8:4173/", dex)
            license_text = zf.read("assets/LICENSE").decode("utf-8")
            self.assertIn("MIT License", license_text)
            index = zf.read("assets/www/index.html").decode("utf-8")
            self.assertIn("DOWNLOAD APK", index)

    def test_rebuild_picks_up_frontend_changes(self):
        frontend = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
        original = frontend.read_text(encoding="utf-8")
        out = Path(self.tmp.name) / "a.apk"
        try:
            first = build_apk(sidecar_url="http://127.0.0.1:8765/", output=out)["sha256"]
            frontend.write_text(original + "\n<!-- apk-sync-marker -->\n", encoding="utf-8")
            second = build_apk(sidecar_url="http://127.0.0.1:8765/", output=out)["sha256"]
            self.assertNotEqual(first, second)
        finally:
            frontend.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
