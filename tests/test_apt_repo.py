"""APT install-by-name: repository builder, source installer, and installed payload.

Covers the operator flow ``vortex desktop deb`` -> ``vortex desktop repo`` ->
``install-repo.sh`` -> ``sudo apt install linux-vortex-terminal``, including
the upgrade rule (a repo carrying several versions resolves to the newest)
and the installed-layout smoke test (the extracted .deb must boot and serve).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from backend.debbuild import PACKAGE, build_deb, build_repo, deb_status
from backend.vortex_backend import APP_VERSION

ROOT = Path(__file__).resolve().parent.parent
MAKE_REPO = ROOT / "packaging" / "deb" / "make-repo.sh"
INSTALL_REPO = ROOT / "packaging" / "deb" / "install-repo.sh"
BUILD_SH = ROOT / "packaging" / "deb" / "build.sh"
HOMEPAGE = "https://github.com/mrtc-solutions/linux-vortex-terminal"
FAKE_ARMOR = (
    "-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
    "Comment: test fixture, not a real key\n"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n"
    "-----END PGP PUBLIC KEY BLOCK-----\n"
)


def _run(*args: str, env: dict | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, check=False, env=env, timeout=timeout)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contained_env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    data = home / "data"
    env["VORTEX_DATA_DIR"] = str(data)
    env["VORTEX_CONFIG_DIR"] = str(home / "config")
    env["VORTEX_RUNTIME_DIR"] = str(home / "runtime")
    env["HOME"] = str(home)
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_CACHE_HOME"] = str(home / ".cache")
    for leaked in ("VORTEX_SIDECAR_TOKEN", "VORTEX_HOST", "VORTEX_PORT", "VORTEX_GPG_KEY", "VORTEX_DPKG_DEB"):
        env.pop(leaked, None)
    return env


def _parse_packages(path: Path) -> list[dict[str, str]]:
    stanzas = []
    for chunk in path.read_text(encoding="utf-8").split("\n\n"):
        fields: dict[str, str] = {}
        for line in chunk.splitlines():
            if line and not line.startswith((" ", "\t")) and ":" in line:
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip()
        if fields:
            stanzas.append(fields)
    return stanzas


def _parse_release_sha256(release: Path) -> dict[str, tuple[str, int]]:
    hashed: dict[str, tuple[str, int]] = {}
    in_sha256 = False
    for line in release.read_text(encoding="utf-8").splitlines():
        if line == "SHA256:":
            in_sha256 = True
            continue
        if in_sha256:
            parts = line.split()
            if len(parts) != 3 or len(parts[0]) != 64:
                in_sha256 = False
                continue
            hashed[parts[2]] = (parts[0], int(parts[1]))
    return hashed


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


class _DebCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dpkg_deb = shutil.which("dpkg-deb")
        if cls.dpkg_deb is None:
            raise unittest.SkipTest("dpkg-deb is required for APT packaging tests")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        os.environ["VORTEX_DATA_DIR"] = str(self.home / "vdata")
        self.out = self.home / "deb"
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.environ.pop, "VORTEX_DATA_DIR", None)

    def _build(self) -> Path:
        return Path(build_deb(output_dir=self.out)["path"])


class ControlFieldsTests(_DebCase):
    def test_control_carries_identity_dependency_and_homepage(self):
        path = self._build()
        fields = {}
        for name in ("Package", "Version", "Architecture", "Maintainer", "Depends", "Section", "Priority", "Homepage"):
            proc = _run(self.dpkg_deb, "--field", str(path), name)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            fields[name] = proc.stdout.strip()
        self.assertEqual(fields["Package"], PACKAGE)
        self.assertEqual(fields["Version"], APP_VERSION)
        self.assertEqual(fields["Architecture"], "all")
        self.assertEqual(fields["Maintainer"], "mrtc-solutions")
        self.assertEqual(fields["Homepage"], HOMEPAGE)
        self.assertIn("python3", fields["Depends"])

    def test_no_conffiles_member_so_upgrades_replace_every_file(self):
        path = self._build()
        proc = _run(self.dpkg_deb, "--info", str(path), "conffiles")
        self.assertNotEqual(proc.returncode, 0, "a conffiles member would preserve stale files across upgrades")

    def test_repo_tooling_ships_inside_the_package(self):
        path = self._build()
        extract = self.home / "extract"
        extract.mkdir()
        proc = _run(self.dpkg_deb, "--extract", str(path), str(extract))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for name in ("build.sh", "make-repo.sh", "install-repo.sh"):
            script = extract / "usr" / "share" / "vortex" / "packaging" / "deb" / name
            self.assertTrue(script.is_file(), name)
            self.assertTrue(script.stat().st_mode & 0o111, f"{name} must stay executable")

    def test_homepage_override_rejects_control_injection(self):
        env = dict(os.environ)
        env["VORTEX_HOMEPAGE"] = "https://example.com\nEvil: 1"
        proc = _run("bash", str(BUILD_SH), str(self.home / "evil"), env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("VORTEX_HOMEPAGE", proc.stderr or proc.stdout)
        self.assertEqual(list((self.home / "evil").glob("*.deb")) if (self.home / "evil").exists() else [], [])


class InstalledPayloadTests(_DebCase):
    def _extract(self) -> Path:
        extract = self.home / "installed"
        extract.mkdir()
        proc = _run(self.dpkg_deb, "--extract", str(self._build()), str(extract))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return extract

    def test_extracted_cli_reports_single_sourced_version(self):
        import sys

        tree = self._extract()
        # The FHS wrapper only resolves after dpkg installs it, so prove the
        # mapping statically and execute the extracted entry point directly.
        wrapper = (tree / "usr" / "bin" / "vortex").read_text(encoding="utf-8")
        self.assertIn('exec /usr/bin/python3 /usr/share/vortex/cli/vortex.py "$@"', wrapper)
        entry = tree / "usr" / "share" / "vortex" / "cli" / "vortex.py"
        self.assertTrue(entry.is_file())
        proc = _run(sys.executable, str(entry), "--version", env=_contained_env(self.home / "cli-home"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), f"vortex {APP_VERSION}")

    def test_extracted_payload_boots_and_serves_health_and_ui(self):
        import sys

        tree = self._extract()
        entry = tree / "usr" / "share" / "vortex" / "cli" / "vortex.py"
        port = _free_port()
        env = _contained_env(self.home / "serve-home")
        proc = subprocess.Popen(
            [sys.executable, str(entry), "serve", "--bind-host", "127.0.0.1", "--bind-port", str(port)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            health = None
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    self.fail(f"installed sidecar exited early with status {proc.returncode}")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as response:
                        if response.status == 200:
                            health = json.loads(response.read().decode("utf-8"))
                            break
                except Exception:
                    time.sleep(0.5)
            self.assertIsNotNone(health, "installed sidecar never answered /api/health")
            assert health is not None
            self.assertEqual(health.get("version"), APP_VERSION)
            self.assertEqual(health.get("backend"), "online")
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as response:
                body = response.read()
                self.assertEqual(response.status, 200)
                self.assertIn(b"vortex.rfb.v1", body, "installed UI must be the bundled noVNC shell")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=15)


class MakeRepoTests(_DebCase):
    def _make_repo(self, *debs: Path, extra: list[str] | None = None, env: dict | None = None) -> Path:
        repo = self.home / f"repo-{len(list(self.home.glob('repo-*')))}"
        command = ["bash", str(MAKE_REPO), "--output", str(repo)]
        for deb in debs:
            command.extend(["--deb", str(deb)])
        command.extend(extra or [])
        proc = _run(*command, env=env or dict(os.environ))
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        return repo

    def test_repo_layout_hashes_recompute(self):
        deb = self._build()
        repo = self._make_repo(deb)
        packages = repo / "dists" / "stable" / "main" / "binary-all" / "Packages"
        self.assertTrue(packages.is_file())
        self.assertTrue((packages.parent / "Packages.gz").is_file())
        stanzas = _parse_packages(packages)
        self.assertEqual(len(stanzas), 1)
        stanza = stanzas[0]
        self.assertEqual(stanza["Package"], PACKAGE)
        self.assertEqual(stanza["Version"], APP_VERSION)
        self.assertEqual(stanza["Architecture"], "all")
        payload = repo / stanza["Filename"]
        self.assertEqual(payload.resolve().parent, (repo / "pool" / "main").resolve())
        self.assertEqual(str(payload.stat().st_size), stanza["Size"])
        self.assertEqual(_sha256(payload), stanza["SHA256"])
        release = repo / "dists" / "stable" / "Release"
        text = release.read_text(encoding="utf-8")
        self.assertIn("Codename: stable", text)
        self.assertIn("Components: main", text)
        hashed = _parse_release_sha256(release)
        self.assertGreaterEqual(len(hashed), 2)
        for rel, (digest, size) in hashed.items():
            candidate = repo / "dists" / "stable" / rel
            self.assertTrue(candidate.is_file(), rel)
            self.assertEqual(candidate.stat().st_size, size, rel)
            self.assertEqual(_sha256(candidate), digest, rel)
        self.assertFalse((repo / "dists" / "stable" / "InRelease").exists(), "default repo must stay unsigned")

    def test_packages_index_is_byte_deterministic(self):
        deb = self._build()
        first = self._make_repo(deb)
        second = self._make_repo(deb)
        for name in ("Packages", "Packages.gz"):
            a = first / "dists" / "stable" / "main" / "binary-all" / name
            b = second / "dists" / "stable" / "main" / "binary-all" / name
            self.assertEqual(a.read_bytes(), b.read_bytes(), name)
        release_a = (first / "dists" / "stable" / "Release").read_text(encoding="utf-8").splitlines()
        release_b = (second / "dists" / "stable" / "Release").read_text(encoding="utf-8").splitlines()
        strip = lambda lines: [line for line in lines if not line.startswith("Date: ")]
        self.assertEqual(strip(release_a), strip(release_b), "only the Date header may differ between runs")

    def test_multi_version_repo_lists_every_version(self):
        current = self._build()
        old_out = self.home / "old-deb"
        env = dict(os.environ)
        env["VORTEX_VERSION"] = "0.2.0"
        proc = _run("bash", str(BUILD_SH), str(old_out), env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        old = next(old_out.glob(f"{PACKAGE}_0.2.0_all.deb"))
        repo = self._make_repo(old, current)
        versions = sorted(stanza["Version"] for stanza in _parse_packages(repo / "dists" / "stable" / "main" / "binary-all" / "Packages"))
        self.assertEqual(versions, ["0.2.0", APP_VERSION])

    def test_rejects_duplicates_bad_tokens_existing_output_and_missing_tools(self):
        deb = self._build()
        repo = self.home / "dup-repo"
        proc = _run("bash", str(MAKE_REPO), "--output", str(repo), "--deb", str(deb), "--deb", str(deb))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("duplicate", proc.stderr)
        proc = _run("bash", str(MAKE_REPO), "--output", str(self.home / "bad"), "--deb", str(deb), "--codename", "../x")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("codename", proc.stderr)
        target = self._make_repo(deb)
        proc = _run("bash", str(MAKE_REPO), "--output", str(target), "--deb", str(deb))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("refusing to overwrite", proc.stderr)
        env = dict(os.environ)
        env["VORTEX_DPKG_DEB"] = "/nonexistent/dpkg-deb"
        proc = _run("bash", str(MAKE_REPO), "--output", str(self.home / "notools"), "--deb", str(deb), env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("dpkg-deb", proc.stderr)

    def test_sign_without_gpg_is_an_honest_error(self):
        if shutil.which("gpg") is not None:
            self.skipTest("gpg is installed; the missing-gpg path cannot trigger here")
        deb = self._build()
        proc = _run("bash", str(MAKE_REPO), "--output", str(self.home / "sig"), "--deb", str(deb), "--sign", "testkey")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("gpg", proc.stderr)

    def test_real_apt_resolves_package_by_name_and_picks_newest(self):
        apt_get = shutil.which("apt-get")
        apt_cache = shutil.which("apt-cache")
        if apt_get is None or apt_cache is None:
            self.skipTest("apt is required for the install-by-name proof")
        current = self._build()
        env = dict(os.environ)
        env["VORTEX_VERSION"] = "0.2.0"
        old_out = self.home / "old-deb"
        proc = _run("bash", str(BUILD_SH), str(old_out), env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        old = next(old_out.glob(f"{PACKAGE}_0.2.0_all.deb"))
        repo = self._make_repo(old, current)
        apt_dir = self.home / "apt"
        (apt_dir / "lists" / "partial").mkdir(parents=True)
        (apt_dir / "archives" / "partial").mkdir(parents=True)
        (apt_dir / "sources.list").write_text(f"deb [trusted=yes] file://{repo} stable main\n", encoding="utf-8")
        base = [
            f"-o=Dir::Etc::sourcelist={apt_dir / 'sources.list'}",
            "-o=Dir::Etc::sourceparts=/dev/null",
            f"-o=Dir::State::Lists={apt_dir / 'lists'}",
            f"-o=Dir::Cache::archives={apt_dir / 'archives'}",
            "-o=Debug::NoLocking=1",
        ]
        update = _run(apt_get, *base, "update", timeout=180)
        self.assertEqual(update.returncode, 0, update.stderr)
        policy = _run(apt_cache, *base, "policy", PACKAGE, timeout=60)
        self.assertEqual(policy.returncode, 0, policy.stderr)
        self.assertIn(f"Candidate: {APP_VERSION}", policy.stdout)
        self.assertIn("0.2.0", policy.stdout)
        install = _run(apt_get, *base, "--download-only", "install", PACKAGE, timeout=180)
        self.assertEqual(install.returncode, 0, install.stderr)
        self.assertIn(f"{PACKAGE} all {APP_VERSION}", install.stdout)


class InstallRepoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.dpkg_deb = shutil.which("dpkg-deb")
        if self.dpkg_deb is None:
            raise unittest.SkipTest("dpkg-deb is required for APT packaging tests")
        os.environ["VORTEX_DATA_DIR"] = str(self.home / "vdata")
        self.addCleanup(os.environ.pop, "VORTEX_DATA_DIR", None)
        deb = Path(build_deb(output_dir=self.home / "deb")["path"])
        self.repo = self.home / "repo"
        proc = _run("bash", str(MAKE_REPO), "--output", str(self.repo), "--deb", str(deb))
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_trusted_local_repo_registers_trusted_source(self):
        root = self.home / "staged"
        proc = _run("bash", str(INSTALL_REPO), "--repo-path", str(self.repo), "--trust-unsigned", "--root", str(root))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        sources = root / "etc" / "apt" / "sources.list.d" / "vortex.sources"
        self.assertEqual(
            sources.read_text(encoding="utf-8"),
            f"Types: deb\nURIs: file://{self.repo}\nSuites: stable\nComponents: main\nTrusted: yes\n",
        )
        self.assertEqual(sources.stat().st_mode & 0o777, 0o644)
        self.assertIn("WITHOUT signature verification", proc.stderr)
        self.assertIn("sudo apt install linux-vortex-terminal", proc.stdout)

    def test_signed_repo_registers_keyring_and_signed_by(self):
        key = self.home / "key.asc"
        key.write_text(FAKE_ARMOR, encoding="utf-8")
        root = self.home / "staged"
        proc = _run("bash", str(INSTALL_REPO), "--repo-url", "https://example.com/vortex", "--key", str(key), "--root", str(root))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        sources = root / "etc" / "apt" / "sources.list.d" / "vortex.sources"
        self.assertEqual(
            sources.read_text(encoding="utf-8"),
            "Types: deb\nURIs: https://example.com/vortex\nSuites: stable\nComponents: main\nSigned-By: /usr/share/keyrings/vortex-archive-keyring.asc\n",
        )
        keyring = root / "usr" / "share" / "keyrings" / "vortex-archive-keyring.asc"
        self.assertEqual(keyring.read_bytes(), FAKE_ARMOR.encode("utf-8"))
        self.assertEqual(keyring.stat().st_mode & 0o777, 0o644)

    def test_unsigned_repo_is_refused_without_explicit_trust(self):
        root = self.home / "staged"
        proc = _run("bash", str(INSTALL_REPO), "--repo-path", str(self.repo), "--root", str(root))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("signing key is required", proc.stderr)
        self.assertFalse((root / "etc" / "apt" / "sources.list.d" / "vortex.sources").exists())

    def test_invalid_inputs_write_nothing(self):
        for args in (
            ["--repo-path", str(self.home / "missing"), "--trust-unsigned"],
            ["--repo-path", str(self.home), "--trust-unsigned"],
            ["--repo-url", "https://example.com/vortex", "--key", str(self.home / "missing.asc")],
            ["--repo-url", "ftp://example.com/vortex", "--trust-unsigned"],
            ["--repo-url", "https://example.com/vortex", "--trust-unsigned", "--codename", "a b"],
        ):
            root = self.home / f"staged-{len(list(self.home.glob('staged-*')))}"
            proc = _run("bash", str(INSTALL_REPO), *args, "--root", str(root))
            self.assertNotEqual(proc.returncode, 0, " ".join(args))
            self.assertFalse((root / "etc" / "apt" / "sources.list.d" / "vortex.sources").exists(), " ".join(args))
        garbage = self.home / "garbage.asc"
        garbage.write_text("not a key", encoding="utf-8")
        root = self.home / "staged-key"
        proc = _run("bash", str(INSTALL_REPO), "--repo-path", str(self.repo), "--key", str(garbage), "--root", str(root))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("ASCII-armored", proc.stderr)


class BackendRepoTests(unittest.TestCase):
    def setUp(self):
        if shutil.which("dpkg-deb") is None:
            raise unittest.SkipTest("dpkg-deb is required for APT packaging tests")
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        os.environ["VORTEX_DATA_DIR"] = str(self.home / "vdata")
        self.addCleanup(os.environ.pop, "VORTEX_DATA_DIR", None)

    def _tree_bytes(self, tree: Path) -> dict[str, str]:
        return {str(path.relative_to(tree)): _sha256(path) for path in sorted(tree.rglob("*")) if path.is_file()}

    def test_default_repo_builds_from_latest_deb_and_verifies(self):
        built = build_deb()
        result = build_repo()
        self.assertTrue(result["ok"])
        self.assertEqual(result["codename"], "stable")
        self.assertEqual(result["component"], "main")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["packages"][0]["version"], APP_VERSION)
        self.assertEqual(result["packages"][0]["sha256"], built["sha256"])
        self.assertFalse(result["signed"])
        tree = Path(result["path"])
        self.assertTrue((tree / "dists" / "stable" / "Release").is_file())
        self.assertIn("sudo apt install linux-vortex-terminal", result["message"])

    def test_existing_repo_requires_replace_and_replaces_cleanly(self):
        build_deb()
        first = Path(build_repo()["path"])
        sentinel = first / "sentinel.txt"
        sentinel.write_text("stale", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "pass replace=True"):
            build_repo()
        self.assertTrue(sentinel.is_file(), "refused rebuild must not touch the existing repo")
        second = build_repo(replace=True)
        self.assertTrue(second["ok"])
        self.assertEqual(second["path"], str(first))
        self.assertFalse(sentinel.exists(), "replace must publish a fresh tree")
        leftovers = list(first.parent.glob(".vortex-repo-backup-*")) + list(first.parent.glob(".vortex-repo-build-*"))
        self.assertEqual(leftovers, [])

    def test_failed_rebuild_preserves_last_verified_repo(self):
        build_deb()
        target = Path(build_repo()["path"])
        before = self._tree_bytes(target)
        with mock.patch("backend.debbuild._verify_repo", side_effect=RuntimeError("verification fixture")):
            with self.assertRaisesRegex(RuntimeError, "verification fixture"):
                build_repo(replace=True)
        self.assertEqual(self._tree_bytes(target), before)
        leftovers = list(target.parent.glob(".vortex-repo-backup-*")) + list(target.parent.glob(".vortex-repo-build-*"))
        self.assertEqual(leftovers, [])

    def test_missing_deb_and_bad_inputs_are_honest_errors(self):
        with self.assertRaisesRegex(RuntimeError, "vortex desktop deb"):
            build_repo()
        build_deb()
        with self.assertRaises(ValueError):
            build_repo(codename="../x")
        for bad_key in ("-x", "a\nb", "k" * 129, ""):
            with self.assertRaises(ValueError, msg=repr(bad_key)):
                build_repo(sign_key=bad_key)

    def test_foreign_package_and_symlink_inputs_are_rejected(self):
        build_deb()
        foreign = self.home / "foreign"
        (foreign / "DEBIAN").mkdir(parents=True)
        (foreign / "DEBIAN" / "control").write_text(
            "Package: foreign\nVersion: 1.0\nArchitecture: all\nMaintainer: test\nDescription: foreign\n", encoding="utf-8"
        )
        proc = _run(shutil.which("dpkg-deb"), "--build", "--root-owner-group", str(foreign), str(self.home / "foreign_1.0_all.deb"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with self.assertRaisesRegex(RuntimeError, "not a linux-vortex-terminal package"):
            build_repo(debs=[self.home / "foreign_1.0_all.deb"], output_dir=self.home / "repo-foreign")
        real = Path(deb_status()["path"])
        link = self.home / "linked.deb"
        link.symlink_to(real)
        with self.assertRaisesRegex(RuntimeError, "cannot be a symlink"):
            build_repo(debs=[link], output_dir=self.home / "repo-link")

    def test_verification_catches_payload_and_index_tampering(self):
        from backend.debbuild import _verify_repo

        build_deb()
        tree = Path(build_repo()["path"])
        payload = tree / "pool" / "main" / f"{PACKAGE}_{APP_VERSION}_all.deb"
        with payload.open("r+b") as handle:
            handle.seek(-1, 2)
            last = handle.read(1)
            handle.seek(-1, 2)
            handle.write(b"\x00" if last != b"\x00" else b"\x01")
        with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
            _verify_repo(tree, "stable", "main")

    def test_verification_catches_unlisted_index(self):
        from backend.debbuild import _verify_repo

        build_deb()
        tree = Path(build_repo()["path"])
        stray = tree / "dists" / "stable" / "main" / "binary-all" / "Packages.stray"
        stray.write_text("stray", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "not covered by Release"):
            _verify_repo(tree, "stable", "main")


class CliRepoTests(unittest.TestCase):
    def setUp(self):
        if shutil.which("dpkg-deb") is None:
            raise unittest.SkipTest("dpkg-deb is required for APT packaging tests")
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.env = _contained_env(self.home)

    def test_version_matches_app_version(self):
        proc = _run("python3", str(ROOT / "cli" / "vortex.py"), "--version", env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), f"vortex {APP_VERSION}")

    def test_desktop_repo_end_to_end(self):
        deb = _run("python3", str(ROOT / "cli" / "vortex.py"), "desktop", "deb", "--json", env=self.env, timeout=300)
        self.assertEqual(deb.returncode, 0, deb.stderr)
        self.assertTrue(json.loads(deb.stdout)["deb"]["ok"])
        repo = _run("python3", str(ROOT / "cli" / "vortex.py"), "desktop", "repo", "--json", env=self.env, timeout=300)
        self.assertEqual(repo.returncode, 0, repo.stderr)
        payload = json.loads(repo.stdout)["repo"]
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["packages"][0]["version"], APP_VERSION)
        again = _run("python3", str(ROOT / "cli" / "vortex.py"), "desktop", "repo", "--json", env=self.env, timeout=300)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("replace", again.stderr)


if __name__ == "__main__":
    unittest.main()
