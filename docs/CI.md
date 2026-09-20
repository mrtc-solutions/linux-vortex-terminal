# CI and real acceptance

The active GitHub Actions workflow is
[`/.github/workflows/react-ui.yml`](../.github/workflows/react-ui.yml). It has
two distinct jobs because a fast green regression suite and a real graphical
acceptance run prove different things:

1. **`browser`** installs Chromium, builds the production React shell, runs the
   Playwright integration suite, then exercises both the production sidecar and
   authenticated Vite-proxy paths.
2. **`release-acceptance`** installs Chromium, Electron, Xvfb/Openbox, a real
   VNC target stack, the pinned CPU GGUF engine, and a downloaded real test
   model. It runs `scripts/release_gates.py`, which fails rather than skips any
   of its eleven real release checks, and uploads remote-desktop evidence.

The exact all-surface procedure, evidence standard, and prerequisite boundary
are maintained in
[`docs/REAL_DEBUGGING_AND_ACCEPTANCE_PLAN.md`](REAL_DEBUGGING_AND_ACCEPTANCE_PLAN.md).

## Recorded real-release result

The [2026-09-20 pull-request run 35510507043](https://github.com/mrtc-solutions/linux-vortex-terminal/actions/runs/35510507043)
for commit `b135b0c321b38cfe6f5ca2d1a599c197f18ce997` passed both jobs:

- `browser` passed after provisioned Chromium ran the build, browser tests, and
  production/dev live UI checks.
- `release-acceptance` passed after provisioning Chromium, Electron, Xvfb,
  Openbox, VNC tooling, the CPU GGUF engine, and a non-fixture GGUF model. Its
  required **All eleven release gates, no skipped checks** step succeeded.

`release_gates.py` returns success only when all eleven gates pass, so this
successful job is the recorded `FINAL RELEASE CHECKS: 11/11 (100%)` result.
The job also uploaded the remote-desktop acceptance report artifact. The
sandbox may still lack those downloadable runtimes locally; use this
provisioned workflow rather than calling an unavailable local runtime a pass.

## Local fast regression equivalent

Run these from the repository root when the graphical/model dependencies are
not available:

```bash
npm run lint
npm test
python3 scripts/final_gates.py
npm run package:deb
VORTEX_REAL_ACCEPTANCE=1 ./tests/linux_acceptance.sh
```

This validates the source, production bundle, Python/JS regression suites,
security spot checks, package construction, and real read-only host probes. It
does **not** turn a missing local browser, Electron runtime, graphical target,
or real model into a pass.

## Full local release equivalent

Use a disposable Linux VM/runner with the same prerequisites as the active
workflow. The workflow is the source of truth for pinned versions and setup;
the final command is:

```bash
xvfb-run -a sh -c 'openbox >/tmp/vortex-openbox.log 2>&1 & python3 scripts/release_gates.py'
```

Acceptance is complete only if it ends with:

```text
FINAL RELEASE CHECKS: 11/11 (100%)
```

The runner intentionally keeps unavailable prerequisites as failures, not
skips. Privileged mutations remain outside automated acceptance and must be
reviewed/run manually through an approved plan on a disposable host.
