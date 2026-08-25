# CI bootstrap note

The intended GitHub Actions quality workflow is documented in the implementation
plan and can be restored as `.github/workflows/quality.yml` when the repository
connection has the GitHub `workflows` permission. The local equivalent is:

```bash
python3 -m py_compile backend/vortex_backend.py cli/vortex.py
python3 -m unittest discover -s tests -v
node --check frontend/app.js
node --check desktop/main.js
node --check desktop/preload.js
sh -n vortex
```

The first push from this environment is intentionally kept free of a workflow
file because the configured GitHub App is not permitted to create or update
workflow files. This is an integration permission limitation, not a product
runtime dependency.

Terminal workspace assets are checked with `node --check`; PTY, key forwarding,
ANSI sanitization, tab/split state, and shell integration ownership are covered
by the Python test suite. Full emulator and privileged Linux acceptance still
require dedicated host/VM jobs.
