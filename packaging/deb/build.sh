#!/usr/bin/env bash
set -euo pipefail

# Build a real, local CLI .deb. It never installs data, starts a service, or
# emits a placeholder artifact. Run this on a Linux builder with dpkg-deb.
root=$(cd "$(dirname "$0")/../.." && pwd)
out="${1:-$root/dist/deb}"
version="${VORTEX_VERSION:-0.2.0}"
package="linux-vortex-terminal"
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "dpkg-deb is required to build a Debian package" >&2
  exit 2
fi
mkdir -p "$out" "$stage/DEBIAN" "$stage/usr/share/vortex" "$stage/usr/share/man/man1" \
  "$stage/usr/share/bash-completion/completions" "$stage/usr/share/zsh/vendor-completions" \
  "$stage/usr/share/fish/vendor_completions.d" "$stage/usr/bin" "$stage/usr/share/doc/$package"

# Ship the source modules needed by the dependency-free CLI. Electron remains
# optional and is deliberately not auto-installed by the OS package.
cp -a "$root/backend" "$root/cli" "$root/frontend" "$root/assets" "$stage/usr/share/vortex/"
cp "$root/README.md" "$root/LICENSE" "$root/SECURITY.md" "$stage/usr/share/doc/$package/"
cp "$root/packaging/deb/vortex.1" "$stage/usr/share/man/man1/vortex.1"
gzip -n -f "$stage/usr/share/man/man1/vortex.1"
cp "$root/assets/completions/vortex.bash" "$stage/usr/share/bash-completion/completions/vortex"
cp "$root/assets/completions/vortex.zsh" "$stage/usr/share/zsh/vendor-completions/_vortex"
cp "$root/assets/completions/vortex.fish" "$stage/usr/share/fish/vendor_completions.d/vortex.fish"

cat > "$stage/usr/bin/vortex" <<'WRAPPER'
#!/bin/sh
exec /usr/bin/python3 /usr/share/vortex/cli/vortex.py "$@"
WRAPPER
chmod 0755 "$stage/usr/bin/vortex"
cat > "$stage/DEBIAN/control" <<CONTROL
Package: $package
Version: $version
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.11)
Maintainer: mrtc-solutions
Description: Linux Vortex Terminal
 Local-first Linux cybersecurity and operations workbench with a real
 shell-free execution authority, typed plans, local audit, and factual tools.
 No listener or user data is created during package installation.
CONTROL

# Do not auto-start a daemon or create user state from maintainer scripts.
dpkg-deb --build --root-owner-group "$stage" "$out/${package}_${version}_all.deb" >/dev/null
sha256sum "$out/${package}_${version}_all.deb" > "$out/${package}_${version}_all.deb.sha256"
if [[ -n "${VORTEX_GPG_KEY:-}" ]]; then
  gpg --batch --local-user "$VORTEX_GPG_KEY" --detach-sign --armor "$out/${package}_${version}_all.deb"
fi
printf 'Built %s\n' "$out/${package}_${version}_all.deb"
