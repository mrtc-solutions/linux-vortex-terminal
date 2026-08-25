# Local retention and recovery policy

The intended defaults are 90 days for command history and 30 days for redacted
output. Raw evidence is opt-in and is not retained by the current vertical slice.
Pruning itself must be an audit event when retention management is expanded.

Data lives under `$XDG_DATA_HOME/vortex` (default `~/.local/share/vortex`) and is
created owner-only. Configuration lives under `$XDG_CONFIG_HOME/vortex`; the
repository and `/tmp` are never data stores. Backup/export must offer explicit
redaction and must not claim encryption at rest until an OS keyring/passphrase
recovery design is implemented.

`vortex db integrity` runs SQLite integrity and audit checks. `vortex backup
PATH` creates a mode-0600 SQLite backup and refuses to overwrite an existing
file without `--force`; the destination must be in an operator-owned directory.
`vortex migrate` reports the current compatible schema and is a no-op until a
real migration exists. The existing `audit verify` detects ordinary hash-chain
alteration. None of these controls protect data from a user/root account that
an attacker already owns.
