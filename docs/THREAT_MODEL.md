# Threat model

## Security boundary

Vortex assists an authorized local operator. It does not authorize access and
cannot protect a machine whose user account, root account, kernel, terminal
emulator, or filesystem is already compromised. Hash chains detect ordinary
tampering but are not an anti-root security boundary.

## Assets

1. Operator credentials, environment values, SSH material, and local paths.
2. Engagement authorization and target scope.
3. Plan approval token/digest and executable identity.
4. Redacted command evidence, history, reports, and audit integrity.
5. Local desktop/sidecar capability token and worker/model context.

## Threats and controls

| Threat | Control |
|---|---|
| Model or output injects shell syntax | Model is advisory; typed argv; `shell=False`; metacharacter rejection; output is never re-parsed |
| PATH replacement / executable substitution | Canonical path, device, inode, mode, owner, size, SHA-256 and version are captured and rechecked |
| Plan replay or double execution | Random plan ID, expiry, exact digest/token, SQLite transactional claim |
| Out-of-scope active assessment | Engagement required; targets normalized and checked at plan and execution |
| Scope gate evaded via an unrecognised plan `kind` | Guardian recomputes the engagement requirement from typed command specs (`guardian.requires_engagement`), independently of the planner label, and a test asserts it agrees with the execution authority |
| Exclusion list silently unenforced | The scope module is resolved under every import context; if it cannot be loaded Guardian blocks the plan rather than skipping the exclusion check |
| Crash leaves an operation permanently in flight | Startup reconciliation closes abandoned operations as `unknown_after_crash` and pauses their tasks; no unobserved outcome is promoted to success |
| Unbounded automatic replanning consumes the host | Replan budget persisted on the task: max 2 iterations, executed plan digests refused, low-risk auto-approved local kinds only |
| Missing scanner creates fake findings | Actual `PATH` probe; no command/evidence/result is created when absent |
| Sudo password capture | No automatic sudo; stdin closed for managed commands; root guard; no password field or logging |
| Child survives cancellation | New process group and TERM/KILL escalation; operation records signal/termination reason |
| Secret leaks in logs/prompts | Minimal environment, structural/best-effort redaction, ANSI removal, bounded storage |
| ANSI/OSC terminal injection | Escape sequences and control bytes removed before display/storage; renderer uses text nodes for data |
| UI bypasses authority | `contextIsolation`, no Node integration, frozen preload bridge, sidecar token |
| Tampered history | Append-only hash chain and `audit verify`; limitation documented |
| Remote model exfiltration | Provider disabled by default; loopback/Unix allowlist is future provider requirement |
| Plugin persistence/backdoor | No runtime plugin execution or auto-discovery |

## Abuse boundary

Blocked capabilities include credential attacks, password spraying, exploitation,
persistence, evasion, malware, phishing, denial of service, exfiltration, raw
disk writes, unrestricted scanning, firewall/routing/DNS mutation, and arbitrary
network installers. Authorized reconnaissance requires an explicit engagement,
conservative limits, real installed tools, and approval.

## Residual risk

- Regex redaction is best effort; operators must use the private/raw-evidence
  policy planned for a later phase and should not place secrets in requests.
- An operator who controls the account can alter local data or approve commands.
- Fingerprints do not defeat a compromised root account or kernel.
- A process that changes its own descendants or uses kernel facilities needs the
  future cgroup/containment design.
- The current sidecar implementation is a vertical slice, not a security
  certification. Do not use it as a substitute for review or authorization.
- Startup reconciliation reports an interrupted operation as unknown. It cannot
  undo a host change that the interrupted command had already made; the operator
  must inspect the host.
- Several modules still use bare package-relative imports that only resolve in
  the sidecar's `sys.path` layout. Guardian's scope import was the security
  relevant one and now fails closed; the remainder are non-failing but are
  tracked as a maintainability risk of the same class.

## Reporting

Report vulnerabilities privately using the process in `SECURITY.md`. Do not
include live target data, credentials, private keys, or unredacted command output
in a report.
