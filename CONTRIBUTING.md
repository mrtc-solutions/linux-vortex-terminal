# Contributing

## Development

Linux and Python 3.11+ are required for the current slice. Electron is optional
for renderer work.

```bash
npm run lint
npm test
npm run preview
```

Do not commit build output, `node_modules`, SQLite databases, reports, evidence,
credentials, or local model files. Keep changes small and use conventional
commit messages such as `feat: add bounded system health planner`.

## Design rules

- Keep command spawning inside the Python execution authority.
- Never use `shell=True` or concatenate untrusted targets, paths, units, package
  names, model output, or terminal output into a command.
- Add a typed schema, policy decision, negative test, and factual unavailable
  path for every capability.
- Preserve versioned JSON, exit codes, plan expiry, exact approval, redaction,
  and truthful failure/unavailable states.
- Do not add a cloud endpoint, runtime plugin loader, automatic sudo, package
  install, shell RC mutation, or fabricated result without a new threat review.
- Clearly mark fixture/practice/reference data; never mix it with live evidence.

Pull requests must explain the threat-model impact, tests run, data retention,
and any new third-party license or asset provenance.
