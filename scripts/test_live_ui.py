#!/usr/bin/env python3
"""Run unmocked browser acceptance against an isolated production sidecar.

Build first with npm run build. --dev exercises the authenticated Vite proxy too.
The runner owns and terminates all child processes and temporary state.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import select
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def stop(child):
    if child and child.poll() is None:
        # Kill the entire process group (including Vite launched through npm).
        import signal
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dev', action='store_true')
    parser.add_argument('--package', action='store_true', help='Test the actual extracted Debian package')
    args = parser.parse_args()
    if not (ROOT / 'dist/index.html').is_file():
        raise SystemExit('React build missing: npm run build')
    with tempfile.TemporaryDirectory(prefix='vortex-live-') as tmp:
        token = secrets.token_hex(32)
        token_file = Path(tmp) / 'token'
        token_file.write_text(token)
        token_file.chmod(0o600)
        env = {**os.environ, 'VORTEX_DATA_DIR': tmp + '/data', 'VORTEX_CONFIG_DIR': tmp + '/config',
               'VORTEX_RUNTIME_DIR': tmp + '/runtime', 'VORTEX_SIDECAR_TOKEN': token,
               'VORTEX_REAL_ACCEPTANCE': '1', 'VORTEX_TEST_TOKEN_FILE': str(token_file)}
        env.pop('VORTEX_UI', None)
        app_root = ROOT
        if args.package:
            package_dir = Path(tmp) / 'packages'
            subprocess.run(['bash', 'packaging/deb/build.sh', str(package_dir)], cwd=ROOT, check=True)
            packages = list(package_dir.glob('*.deb'))
            if len(packages) != 1:
                raise RuntimeError('Expected exactly one built package')
            extract = Path(tmp) / 'installed'
            subprocess.run(['dpkg-deb', '-x', str(packages[0]), str(extract)], check=True)
            app_root = extract / 'usr/share/vortex'
            if (app_root / 'dist/index.html').read_bytes() != (ROOT / 'dist/index.html').read_bytes():
                raise RuntimeError('Packaged React build differs from source build')
        backend = dev = None
        try:
            with open(Path(tmp) / 'backend.log', 'w') as log, open(Path(tmp) / 'vite.log', 'w') as vite_log:
                backend = subprocess.Popen([sys.executable, str(app_root / 'backend/vortex_backend.py'), '--host', '0.0.0.0', '--port', '0'],
                                           cwd=app_root, env=env, stdout=subprocess.PIPE, stderr=log, text=True, start_new_session=True)
                if not select.select([backend.stdout], [], [], 20)[0]:
                    raise RuntimeError('Sidecar did not report readiness')
                info = json.loads(backend.stdout.readline())
                url = 'http://127.0.0.1:' + str(info['port'])
                if args.dev:
                    # Vite uses the explicit sidecar target only in this isolated runner.
                    env['VORTEX_DEV_SIDECAR'] = url
                    dev = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--port', '5175', '--strictPort'],
                                           cwd=ROOT, env=env, stdout=vite_log, stderr=vite_log, start_new_session=True)
                    url = 'http://127.0.0.1:5175'
                    deadline = time.monotonic() + 20
                    while True:
                        try:
                            urllib.request.urlopen(url, timeout=1).close()
                            break
                        except OSError:
                            if dev.poll() is not None or time.monotonic() > deadline:
                                raise RuntimeError('Vite did not become ready')
                            time.sleep(.1)
                env['VORTEX_LIVE_URL'] = url
                result = subprocess.run(['npx', 'playwright', 'test', '--config', 'playwright.live.config.ts'], cwd=ROOT, env=env)
                return result.returncode
        finally:
            stop(dev)
            stop(backend)


if __name__ == '__main__':
    sys.exit(main())
