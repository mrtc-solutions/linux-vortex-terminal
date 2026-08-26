#!/usr/bin/env bash
# Operator-controlled user-local install. No sudo. No apt. No agent download.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
prefix="${1:-$HOME/.local/bin}"
mkdir -p "$prefix"
cat > "$prefix/vortex" <<WRAPPER
#!/usr/bin/env sh
exec python3 "$root/cli/vortex.py" "\$@"
WRAPPER
chmod 0755 "$prefix/vortex"
printf 'Installed user-local launcher: %s/vortex\n' "$prefix"
printf 'Source tree: %s\n' "$root"
printf 'No packages, agents, Docker, or models were installed.\n'
printf 'Add %s to PATH if needed, then run: vortex doctor\n' "$prefix"
