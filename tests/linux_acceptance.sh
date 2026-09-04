#!/usr/bin/env bash
set -euo pipefail

# This is a real-host checklist, not a fixture runner. It is intentionally opt-in
# and performs only read-only probes. Privileged mutations must be reviewed and
# run manually through an approved Vortex plan on a disposable Linux host.
if [[ "${VORTEX_REAL_ACCEPTANCE:-}" != "1" ]]; then
  echo "Refusing acceptance checks: set VORTEX_REAL_ACCEPTANCE=1 on a disposable Linux host." >&2
  exit 2
fi

root=$(cd "$(dirname "$0")/.." && pwd)
if [[ -z "${VORTEX_DATA_DIR:-}" ]]; then
  export VORTEX_DATA_DIR="$(mktemp -d)"
  VORTEX_DATA_DIR_OWNED=1
else
  VORTEX_DATA_DIR_OWNED=0
fi
trap 'if [[ "$VORTEX_DATA_DIR_OWNED" == "1" ]]; then rm -rf "$VORTEX_DATA_DIR"; fi' EXIT

"$root/vortex" doctor --json
"$root/vortex" adapters --json
"$root/vortex" db integrity --json

if command -v dpkg >/dev/null 2>&1; then
  echo '[READ-ONLY] dpkg --audit'
  dpkg --audit
fi
if command -v apt-get >/dev/null 2>&1 && [[ -n "${VORTEX_ACCEPTANCE_PACKAGE:-}" ]]; then
  if [[ ! "$VORTEX_ACCEPTANCE_PACKAGE" =~ ^[a-z0-9][a-z0-9+.-]*(:[a-z0-9]+)?$ ]]; then
    echo "Invalid VORTEX_ACCEPTANCE_PACKAGE" >&2
    exit 2
  fi
  echo '[READ-ONLY] apt-get dependency preflight'
  apt-get -s --no-remove install "$VORTEX_ACCEPTANCE_PACKAGE"
fi

if command -v systemctl >/dev/null 2>&1 && [[ -n "${VORTEX_ACCEPTANCE_UNIT:-}" ]]; then
  if [[ ! "$VORTEX_ACCEPTANCE_UNIT" =~ ^[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service$ ]]; then
    echo "Invalid VORTEX_ACCEPTANCE_UNIT" >&2
    exit 2
  fi
  echo '[READ-ONLY] systemctl show'
  if ! systemctl show "$VORTEX_ACCEPTANCE_UNIT" --property=Id,Description,LoadState,ActiveState,SubState,UnitFileState --no-pager; then
    echo 'NOT TESTABLE IN SANDBOX: systemd bus is unavailable for systemctl show on this host.' >&2
  fi
fi

echo 'Real read-only acceptance checks completed. No mutation was performed.'
