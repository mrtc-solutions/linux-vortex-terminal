#!/usr/bin/env bash
# Clone or fast-forward verified secondary-agent repositories only.
# This script intentionally does not install dependencies or execute their code.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${VORTEX_SECONDARY_AGENTS_DIR:-$root/agents/secondary}"
mkdir -p "$target"
repos=(
  "cai|https://github.com/aliasrobotics/cai.git"
  "strix|https://github.com/usestrix/strix.git"
  "nebula|https://github.com/BerylliumSec/nebula.git"
  "pentestgpt|https://github.com/GreyDGL/PentestGPT.git"
  "hexstrike|https://github.com/0x4m4/hexstrike-ai.git"
  "pentagi|https://github.com/vxcontrol/pentagi.git"
)
for entry in "${repos[@]}"; do
  IFS='|' read -r name url <<< "$entry"
  dir="$target/$name"
  if [[ -d "$dir/.git" ]]; then
    echo "Updating $name"; git -C "$dir" pull --ff-only
  elif [[ -e "$dir" ]]; then
    echo "Skipping $name: destination exists but is not a Git checkout" >&2
  else
    echo "Cloning $name"; git clone --depth 1 "$url" "$dir"
  fi
done
echo "Secondary repositories are in: $target"
echo "Review each upstream README and license before installing any dependency."
