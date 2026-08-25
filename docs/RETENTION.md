# Local retention and recovery policy

The intended defaults are 90 days for command history and 30 days for redacted
output. Raw evidence is opt-in and is not retained by the current vertical slice.
Pruning itself must be an audit event when retention management is expanded.

Data lives under `$XDG_DATA_HOME/vortex` (default `~/.local/share/vortex`) and is
created owner-only. Configuration lives under `$XDG_CONFIG_HOME/vortex`; the
repository and `/tmp` are never data stores. Backup/export must offer explicit
redaction and must not claim encryption at rest until an OS keyring/passphrase
recovery design is implemented.

`PRAGMA integrity_check` and a safe SQLite backup/recovery flow are Phase 4
work. The existing `audit verify` detects ordinary hash-chain alteration. It does
not protect data from a user/root account that an attacker already owns.
