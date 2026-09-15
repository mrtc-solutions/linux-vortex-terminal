#!/usr/bin/env python3
"""Ten explicit release checks. Missing dependencies FAIL; nothing is skipped.

Needs Chromium, native Electron with a display/WM, and VORTEX_REAL_MODEL plus a
real GGUF engine. CI installs those prerequisites before running this runner.
No finite suite establishes that every feature or every environment is bug-free.
"""
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
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
]


def main():
    results = []
    for index, (name, command) in enumerate(GATES, 1):
        print(f'\n::group::Gate {index}/10: {name}', flush=True)
        start = time.monotonic()
        try:
            ok = subprocess.run(command, cwd=ROOT, timeout=900).returncode == 0
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f'FAILED: {error}', flush=True)
            ok = False
        results.append((name, ok))
        print(f'::endgroup::\n[{"PASS" if ok else "FAIL"}] {index}/10 {name} ({time.monotonic() - start:.1f}s)', flush=True)
    passed = sum(ok for _, ok in results)
    summary = f'FINAL RELEASE CHECKS: {passed}/10 ({passed * 10}%)'
    print('\n' + summary, flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
            output.write('## ' + summary + '\n\n')
            output.writelines(f'- {"PASS" if ok else "FAIL"}: {name}\n' for name, ok in results)
    return 0 if passed == len(GATES) else 1


if __name__ == '__main__':
    sys.exit(main())
