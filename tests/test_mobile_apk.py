"""Android APK sync and packaging."""
from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from unittest import mock
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
        raw = encode_manifest(version_name="0.2.22")
        self.assertEqual(raw[:4], b"\x03\x00\x08\x00")
        self.assertIn("io.vortex.mobile".encode("utf-16le"), raw)
        self.assertIn("Vortex Terminal".encode("utf-16le"), raw)

    def test_axml_config_changes_survives_rotation(self):
        raw = encode_manifest()
        # orientation|keyboardHidden|screenSize so API 13+ rotation does not
        # destroy the WebView activity.
        self.assertIn(b"\xa0\x04\x00\x00", raw)

    def test_axml_elements_decode_per_android_spec(self):
        # Independent structural decode following AOSP's ResXMLTree layout
        # (ResourceTypes.h): chunk headers, UTF-16 string pool, resource map,
        # then namespace/element nodes with ResXMLTree_attrExt headers. A
        # manifest whose attributes only exist as unreachable bytes installs
        # nowhere, so every launch-critical attribute is read back the way
        # Android's PackageParser would read it.
        import struct
        raw = encode_manifest()
        self.assertEqual(struct.unpack_from("<HHI", raw, 0), (0x0003, 8, len(raw)))
        off = 8
        ptype, pheader, psize = struct.unpack_from("<HHI", raw, off)
        self.assertEqual((ptype, pheader), (0x0001, 28))
        count, styles, flags, strings_start, _styles_start = struct.unpack_from("<IIIII", raw, off + 8)
        self.assertEqual(styles, 0)
        self.assertEqual(flags, 0)
        offsets = struct.unpack_from("<%dI" % count, raw, off + 28)
        strings = []
        for item in offsets:
            base = off + strings_start + item
            (nchars,) = struct.unpack_from("<H", raw, base)
            text = raw[base + 2:base + 2 + nchars * 2].decode("utf-16le")
            strings.append(text)
        off += psize
        mtype, mheader, msize = struct.unpack_from("<HHI", raw, off)
        self.assertEqual((mtype, mheader), (0x0180, 8))
        off += msize
        stack: list[str] = []
        seen: dict[str, list[dict]] = {}
        while off < len(raw):
            ctype, cheader, csize = struct.unpack_from("<HHI", raw, off)
            self.assertEqual(cheader, 16)
            self.assertGreater(csize, 16)
            if ctype == 0x0102:  # START_ELEMENT
                ns, name = struct.unpack_from("<iI", raw, off + 16)
                astart, asize, acount, _id, _cls, _style = struct.unpack_from("<HHHHHH", raw, off + 24)
                self.assertEqual((astart, asize), (20, 20), "attrExt must describe 20-byte attributes")
                attrs = []
                for i in range(acount):
                    base = off + 16 + astart + i * asize
                    ans, aname, araw, _size, _res0, dtype, data = struct.unpack_from("<iIiHBBI", raw, base)
                    attrs.append({
                        "ns": strings[ans] if ans >= 0 else None,
                        "name": strings[aname],
                        "raw": strings[araw] if araw >= 0 else None,
                        "type": dtype,
                        "data": data,
                    })
                tag = strings[name]
                stack.append(tag)
                seen.setdefault(tag, []).append({a["name"]: a for a in attrs})
            elif ctype == 0x0103:  # END_ELEMENT
                _ns, name = struct.unpack_from("<iI", raw, off + 16)
                self.assertEqual(stack.pop(), strings[name])
            off += csize
        self.assertEqual(stack, [])
        manifest = seen["manifest"][0]
        self.assertEqual(manifest["package"]["raw"], "io.vortex.mobile")
        self.assertEqual((manifest["versionCode"]["type"], manifest["versionCode"]["data"]), (0x10, 230))
        self.assertEqual(manifest["versionName"]["raw"], "0.3.0")
        sdk = seen["uses-sdk"][0]
        self.assertEqual((sdk["minSdkVersion"]["data"], sdk["targetSdkVersion"]["data"]), (21, 34))
        app = seen["application"][0]
        self.assertEqual(app["label"]["raw"], "Vortex Terminal")
        self.assertEqual(app["usesCleartextTraffic"]["data"], 0xFFFFFFFF)
        activity = seen["activity"][0]
        self.assertEqual(activity["name"]["raw"], "io.vortex.mobile.MainActivity")
        self.assertEqual(activity["exported"]["data"], 0xFFFFFFFF)
        self.assertEqual(activity["configChanges"]["data"], 0x04A0)
        self.assertEqual(seen["action"][0]["name"]["raw"], "android.intent.action.MAIN")
        self.assertEqual(seen["category"][0]["name"]["raw"], "android.intent.category.LAUNCHER")

    def test_dex_header_checksum(self):
        dex = build_webview_dex("http://192.0.2.10:8765/")
        self.assertTrue(dex.startswith(b"dex\n035\x00"))
        self.assertGreater(len(dex), 0x70)
        self.assertIn(b"io/vortex/mobile/MainActivity", dex)
        self.assertIn(b"http://192.0.2.10:8765/", dex)

    def test_dex_structure_decodes_per_dalvik_spec(self):
        # Independent structural decode following the Dalvik executable format:
        # header coherence, checksum/signature recomputation, string/type/
        # proto/method tables, class_data index sequences, and the onCreate
        # bytecode. A dex whose bytes merely contain the right substrings can
        # still fail verification on device; this reads it the way ART does.
        import hashlib
        import struct
        import zlib
        url = "http://192.0.2.10:8765/"
        dex = build_webview_dex(url)

        def u32(off):
            return struct.unpack_from("<I", dex, off)[0]

        def read_uleb(off):
            result = shift = 0
            while True:
                byte = dex[off]
                off += 1
                result |= (byte & 0x7F) << shift
                if not byte & 0x80:
                    return result, off
                shift += 7

        self.assertEqual(u32(8), zlib.adler32(dex[12:]) & 0xFFFFFFFF)
        self.assertEqual(dex[12:32], hashlib.sha1(dex[32:]).digest())
        self.assertEqual(u32(32), len(dex))  # file_size
        self.assertEqual(u32(36), 0x70)  # header_size
        self.assertEqual(u32(40), 0x12345678)  # endian_tag

        n_strings, strings_off = u32(56), u32(60)
        n_types, types_off = u32(64), u32(68)
        n_protos, protos_off = u32(72), u32(76)
        n_methods, methods_off = u32(88), u32(92)
        n_classes, classes_off = u32(96), u32(100)
        self.assertEqual(n_classes, 1)
        strings = []
        for i in range(n_strings):
            size, pos = read_uleb(u32(strings_off + 4 * i))
            text = dex[pos:pos + size].decode("utf-8")
            self.assertEqual(dex[pos + size], 0)
            strings.append(text)
        self.assertIn(url, strings)
        types = [strings[u32(types_off + 4 * i)] for i in range(n_types)]
        protos = []
        for i in range(n_protos):
            shorty, ret, params_off = (u32(protos_off + 12 * i + 4 * j) for j in range(3))
            params = []
            if params_off:
                count = u32(params_off)
                params = [types[struct.unpack_from("<H", dex, params_off + 4 + 2 * k)[0]] for k in range(count)]
            protos.append((strings[shorty], types[ret], params))
        methods = []
        for i in range(n_methods):
            cls, proto = struct.unpack_from("<HH", dex, methods_off + 8 * i)
            name = u32(methods_off + 8 * i + 4)
            methods.append((types[cls], protos[proto], strings[name]))
        self.assertEqual(methods[10][:1] + methods[10][2:], ("Lio/vortex/mobile/MainActivity;", "<init>"))
        self.assertEqual(methods[11][:1] + methods[11][2:], ("Lio/vortex/mobile/MainActivity;", "onCreate"))

        cls_type, _flags, super_type, _, _, _, class_data_off, _ = (
            u32(classes_off + 4 * j) for j in range(8))
        self.assertEqual(types[cls_type], "Lio/vortex/mobile/MainActivity;")
        self.assertEqual(types[super_type], "Landroid/app/Activity;")
        pos = class_data_off
        counts = []
        for _ in range(4):
            value, pos = read_uleb(pos)
            counts.append(value)
        self.assertEqual(counts, [0, 0, 1, 1])
        direct_idx, pos = read_uleb(pos)
        _direct_flags, pos = read_uleb(pos)
        _direct_code, pos = read_uleb(pos)
        virtual_idx, pos = read_uleb(pos)
        virtual_flags, pos = read_uleb(pos)
        virtual_code, _pos = read_uleb(pos)
        # First index of each list is absolute: MainActivity.<init> is method
        # 10 and MainActivity.onCreate is method 11.
        self.assertEqual(direct_idx, 10)
        self.assertEqual(virtual_idx, 11)
        self.assertEqual(virtual_flags, 0x4)

        regs, ins, _outs, tries, _debug, units = struct.unpack_from("<HHHHII", dex, virtual_code)
        self.assertEqual((regs, ins, tries), (6, 2, 0))
        insns = dex[virtual_code + 16:virtual_code + 16 + units * 2]
        self.assertEqual(insns[0], 0x6F)  # invoke-super
        self.assertEqual(insns[2] | (insns[3] << 8), 1)  # Activity.onCreate
        url_idx = strings.index(url)
        const_strings = [insns[i + 2] | (insns[i + 3] << 8)
                         for i in range(len(insns) - 3) if insns[i] == 0x1A]
        self.assertIn(url_idx, const_strings)  # const-string loads the startup URL
        self.assertEqual(insns[-2:], bytes([0x0E, 0x00]))  # return-void

    def test_dex_rejects_non_ascii_url(self):
        with self.assertRaises(ValueError):
            build_webview_dex("http://exämple.test/")

    def test_sync_copies_live_frontend_and_license(self):
        dest = Path(self.tmp.name) / "sync"
        result = sync_payload("http://127.0.0.1:8765/", dest)
        self.assertIn("index.html", result["copied"])
        self.assertTrue((dest / "www" / "index.html").is_file())
        self.assertTrue((dest / "www" / "app.js").is_file())
        # Every asset the embedded index.html references must be synced, or the
        # offline fallback snapshot inside the APK loads a broken shell.
        import re
        refs = sorted(set(re.findall(
            r"/assets/([A-Za-z0-9_.-]+\.(?:js|css))",
            (dest / "www" / "index.html").read_text(encoding="utf-8"))))
        self.assertTrue(refs, "index.html must reference its assets")
        for name in refs:
            self.assertIn(name, result["copied"])
            self.assertTrue((dest / "www" / name).is_file(), f"{name} must sync into the APK")
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
                "assets/www/models.js",
                "assets/www/hud.js",
                "assets/LICENSE",
                "META-INF/MANIFEST.MF",
                "META-INF/CERT.SF",
                "META-INF/CERT.RSA",
            ):
                self.assertIn(required, names, required)
            dex = zf.read("classes.dex")
            self.assertTrue(dex.startswith(b"dex\n035\x00"))
            self.assertIn(b"file:///android_asset/www/connect.html", dex)
            self.assertNotIn(b"http://192.0.2.8:4173/", dex)
            self.assertEqual(zf.read("assets/sidecar.txt"), b"http://192.0.2.8:4173/\n")
            connect = zf.read("assets/www/connect.html").decode("utf-8")
            self.assertIn("Sidecar capability", connect)
            self.assertIn("vortex-token", connect)
            self.assertIn("url.pathname !== '/'", connect)
            self.assertIn("url.search || url.hash", connect)
            self.assertIn("token.length > 256", connect)
            self.assertIn("document.getElementById('t').value = ''", connect)
            license_text = zf.read("assets/LICENSE").decode("utf-8")
            self.assertIn("MIT License", license_text)
            index = zf.read("assets/www/index.html").decode("utf-8")
            self.assertIn("DOWNLOAD APK", index)

    def test_apk_rejects_non_origin_or_credentialed_sidecar_urls(self):
        for invalid in (
            "javascript:alert(1)", "http://user:secret@example.test/",
            "http://example.test/path", "http://example.test/?token=secret",
            "http://example.test/#fragment", "http://bad host/",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                build_apk(sidecar_url=invalid, output=Path(self.tmp.name) / "invalid.apk")

    def test_apk_verifier_rejects_payload_tampering_and_unsigned_entries(self):
        from backend.mobile.apkbuild import _verify_apk
        original = Path(self.tmp.name) / "original.apk"
        build_apk(sidecar_url="http://127.0.0.1:8765/", output=original)
        with zipfile.ZipFile(original) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        for suffix, mutation in (
            ("tampered", {"assets/www/app.js": entries["assets/www/app.js"] + b"\n// tampered\n"}),
            ("unsigned", {"assets/unsigned.txt": b"not covered by the signature"}),
        ):
            candidate = Path(self.tmp.name) / f"{suffix}.apk"
            with zipfile.ZipFile(candidate, "w") as archive:
                for name, payload in (entries | mutation).items():
                    archive.writestr(name, payload)
            with self.subTest(suffix=suffix), self.assertRaisesRegex(RuntimeError, "APK"):
                _verify_apk(candidate)

    def test_failed_apk_verification_preserves_last_published_build(self):
        from backend.mobile import apkbuild
        output = Path(self.tmp.name) / "stable.apk"
        built = build_apk(sidecar_url="http://127.0.0.1:8765/", output=output)
        before = output.read_bytes()
        with mock.patch.object(apkbuild, "_verify_apk", side_effect=RuntimeError("verification fixture")):
            with self.assertRaisesRegex(RuntimeError, "verification fixture"):
                build_apk(sidecar_url="http://127.0.0.1:8765/", output=output)
        self.assertEqual(output.read_bytes(), before)
        self.assertEqual(apkbuild._sha256_file(output), built["sha256"])
        self.assertEqual(list(output.parent.glob(".vortex-apk-build-*")), [])

    def test_apk_status_does_not_follow_symlink(self):
        from backend.mobile.apkbuild import apk_status, mobile_dir
        victim = Path(self.tmp.name) / "not-an-apk"
        victim.write_bytes(b"PK\x03\x04secret")
        path = mobile_dir() / "vortex.apk"
        path.symlink_to(victim)
        self.assertFalse(apk_status()["built"])

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
