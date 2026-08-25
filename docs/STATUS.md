# Current implementation status

This project is a real Linux application. Production code uses real installed
Linux tools and observed output only. Test doubles and fixture files exist only
inside tests; they cannot become production findings or tool health.

## Priority status

| Priority | State | Remaining release gate |
|---|---|---|
| 1. Terminal workspace | Functional slice implemented | Full xterm compatibility, durable daemon attachment across sidecar restarts, tmux/SSH/non-TTY acceptance |
| 2. Adapter hardening | Functional slice implemented | Deeper runtime-specific schemas, Nmap/HTTP acceptance, fuzzing and host coverage |
| 3. Privileged Linux acceptance | Code and preflight implemented | Must run real package/service mutations only on a dedicated disposable Linux/Kali host |
| 4. Persistence and release | Local backups, integrity, retention, reports, and `.deb` CLI build implemented | Schema upgrade migrations, scheduled retention, signed artifacts and install/upgrade/uninstall VM evidence |
| 5. Optional intelligence | Deliberately disabled | Local model and worker implementations are optional; no LLM is required |

## Honest limitations

The repository does not contain a VM, a second Linux host, an installed Docker/
Podman runtime, an installed Nmap binary, or configured local model workers. It
therefore does not claim those environment-specific acceptance gates passed.
`tests/linux_acceptance.sh` is a guarded real-host checklist; it refuses to run
privileged mutations unless the operator explicitly supplies the required
environment variables on a disposable host.
