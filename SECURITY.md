# Security policy

## Authorized use

Linux Vortex Terminal is an operator-assistance tool for Linux hosts and
explicitly authorized cybersecurity work. It does not grant authorization.
Never target systems, networks, accounts, or artifacts without written or
otherwise verifiable permission and a declared scope.

The product blocks credential attacks, spraying/brute force, exploitation,
persistence, evasion, malware, phishing, denial of service, exfiltration, raw
disk writes, unrestricted scanning, firewall/routing/DNS mutation, and
unreviewed network installers. Reviewed package/runtime downloads require
explicit confirmation, fixed typed operations, integrity checks, and verification.
An engagement is not a substitute for legal authorization.

## Reporting a vulnerability

Please report vulnerabilities privately to the repository maintainers rather
than opening a public issue with exploit details. Include the affected version,
Linux distribution/architecture, reproducible steps, impact, and a minimal
redacted proof. Do not include passwords, tokens, private keys, live target data,
or unredacted terminal output.

Maintainers should acknowledge a report within 7 days, triage severity, keep the
reporter informed, prepare a signed release or mitigation, and publish a
coordinated advisory after users have a practical update. Emergency adapter
disablement and rollback are preferred over leaving an unsafe capability live.

## Privacy and data

The default mode is local, offline, and no-telemetry. Vortex writes under XDG
locations with owner-only permissions. It excludes secrets from its minimal
process environment and redacts common secret forms before storing output. Regex
redaction is best effort: operators should not put secrets in requests and
should use the future private-evidence controls for sensitive work.

No cloud model is contacted by default. Local Ollama inference is restricted to
a validated loopback HTTP endpoint, uses bounded responses and proxy-disabled
connections, and receives minimized/redacted advisory context. Model output
cannot create commands, approve a plan, or override Guardian.
