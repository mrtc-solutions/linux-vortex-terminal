# CLI and JSON contract

Every JSON response contains `schema_version: 1`. JSON data is written to
stdout; diagnostics and interactive prompts are written to stderr. No progress
or ANSI output is mixed into JSON.

| Code | Name | Meaning |
|---:|---|---|
| 0 | success | Request completed successfully; a command only gets this after observed exit 0 |
| 1 | failure | Unexpected/general failure |
| 2 | invalid_usage | Invalid CLI arguments |
| 3 | unavailable | Tool, backend, model, context, or capability unavailable |
| 4 | policy_denied | Scope, policy, identity, or authorization denied |
| 5 | confirmation_required | Confirmation missing or declined |
| 6 | command_failed | Approved command returned non-zero |
| 7 | interrupted | Operator interrupt or signal |
| 8 | timeout | Wall-clock or output bound reached |
| 9 | integrity_failure | Audit/database/package integrity failed |
| 10 | incompatible_state | State or migration is incompatible |

The map is intentionally stable. Breaking JSON, policy, database, or direct
command behavior requires a major semantic-version release. Non-interactive
execution requires the plan ID, exact digest, and approval token; `--yes` alone
never universally authorizes a plan. Guarded apt/systemd mutations also require
an exact second approval of the observed preflight digest.
