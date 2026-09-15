#!/usr/bin/env python3
"""Eleven explicit release checks. Missing dependencies FAIL; nothing is skipped.

Needs Chromium, native Electron with a display/WM, a real graphical target for
the authorized remote-desktop gate (Xvfb + x11vnc + xterm + xdotool, or PyQt5),
and VORTEX_REAL_MODEL plus a real GGUF engine. CI installs those prerequisites
before running this runner. No finite suite establishes that every feature or
every environment is bug-free.
"""
import os
import re
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
# Evidence file for the graphical gate. CI uploads it as a build artifact so the
# per-check result is inspectable next to the run, not only inside the log.
REPORT_PATH = Path(
    os.environ.get('VORTEX_ACCEPTANCE_REPORT') or (ROOT / 'artifacts' / 'remote-desktop-acceptance.json')
)
GATES = [
    ('Lint and TypeScript', ['npm', 'run', 'lint']),
    ('Production React build', ['npm', 'run', 'build']),
    ('Python regression suite', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q']),
    ('Legacy JavaScript regressions', ['npm', 'run', 'test:legacy']),
    ('React browser regressions', ['npm', 'run', 'test:browser']),
    ('Production UI + actual backend', [sys.executable, 'scripts/test_live_ui.py']),
    ('Authenticated dev proxy + actual backend', [sys.executable, 'scripts/test_live_ui.py', '--dev']),
    ('Extracted Debian package + actual backend', [sys.executable, 'scripts/test_live_ui.py', '--package']),
    ('Native Electron / IPC / PTY', ['node', 'tests/native_acceptance.cjs']),
    ('Real GGUF model inference', [sys.executable, 'tests/real_provider_acceptance.py']),
    # A real VNC server serving a real graphical application, driven through the
    # actual WebSocket/RFB bridge. Exit code 3 means the environment could not
    # provide a target: that is a FAILED gate, never a skip.
    ('Authorized remote desktop vs real graphical target',
     [sys.executable, 'tests/remote_desktop_acceptance.py', '--report', str(REPORT_PATH)]),
]


def main():
    results = []
    for index, (name, command) in enumerate(GATES, 1):
        print(f'\n::group::Gate {index}/{len(GATES)}: {name}', flush=True)
        start = time.monotonic()
        try:
            completed = subprocess.run(command, cwd=ROOT, timeout=900, capture_output=True, text=True)
            output = completed.stdout + completed.stderr
            print(output, flush=True)
            ok = completed.returncode == 0
            if not ok and os.environ.get('GITHUB_ACTIONS'):
                # Accessible via GitHub check annotations even if raw-log asset
                # downloads are blocked. Never publish test approval tokens.
                detail = re.sub(r'(approval_token[\"\' :]+)[^\"\'\s,}]+', r'\1[redacted]', output[-2500:])
                detail = detail.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
                print(f'::error title=Release gate {index} - {name}::{detail}', flush=True)
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f'FAILED: {error}', flush=True)
            ok = False
        results.append((name, ok))
        print(f'::endgroup::\n[{"PASS" if ok else "FAIL"}] {index}/{len(GATES)} {name} ({time.monotonic() - start:.1f}s)', flush=True)
    passed = sum(ok for _, ok in results)
    summary = f'FINAL RELEASE CHECKS: {passed}/{len(GATES)} ({passed * 100 // len(GATES)}%)'
    print('\n' + summary, flush=True)
    if os.environ.get('GITHUB_ACTIONS'):
        print('::notice title=Release acceptance result::' + summary, flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
            output.write('## ' + summary + '\n\n')
            output.writelines(f'- {"PASS" if ok else "FAIL"}: {name}\n' for name, ok in results)
    return 0 if passed == len(GATES) else 1


if __name__ == '__main__':
    sys.exit(main())
