#!/usr/bin/env bash
set -euo pipefail
# mktemp keeps staging private; packaged directories/files need conventional
# 0755/0644 modes so dpkg accepts and installed users can execute/read them.
umask 022
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

# Build a real, local CLI .deb. It never installs data, starts a service, or
# emits a placeholder artifact. Run this on a Linux builder with dpkg-deb.
root=$(cd "$(dirname "$0")/../.." && pwd)
out="${1:-$root/dist/deb}"
version="${VORTEX_VERSION:-0.2.21}"
package="linux-vortex-terminal"
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
cd "$root"

if [[ ! "$version" =~ ^[0-9][0-9A-Za-z.+:~_-]{0,63}$ ]]; then
  echo "VORTEX_VERSION is not a valid bounded Debian version" >&2
  exit 2
fi
dpkg_deb="${VORTEX_DPKG_DEB:-}"
if [[ -z "$dpkg_deb" ]]; then
  dpkg_deb=$(command -v dpkg-deb || true)
fi
if [[ -z "$dpkg_deb" || "$dpkg_deb" != /* || ! -x "$dpkg_deb" ]]; then
  echo "dpkg-deb is required to build a Debian package" >&2
  exit 2
fi
mkdir -p "$out" "$stage/DEBIAN" "$stage/usr/share/vortex" "$stage/usr/share/man/man1" \
  "$stage/usr/share/bash-completion/completions" "$stage/usr/share/zsh/vendor-completions" \
  "$stage/usr/share/fish/vendor_completions.d" "$stage/usr/bin" "$stage/usr/share/doc/$package" \
  "$stage/usr/share/applications" "$stage/usr/share/icons/hicolor/scalable/apps"

# Ship only reviewed source file types and explicit frontend/assets. A blanket
# `cp -a` would silently include an operator's untracked .env, editor backup,
# bytecode cache, or other checkout residue in a downloadable package.
while IFS= read -r -d '' source; do
  install -D -m 0644 "$source" "$stage/usr/share/vortex/$source"
done < <(find backend cli -type f -name '*.py' -print0)
for source in index.html app.js workspace.js terminal.js windows.js models.js hud.js styles.css; do
  install -D -m 0644 "$root/frontend/$source" "$stage/usr/share/vortex/frontend/$source"
done
for source in README.md hooded-researcher.svg; do
  install -D -m 0644 "$root/assets/$source" "$stage/usr/share/vortex/assets/$source"
done
for source in vortex.bash vortex.zsh vortex.fish; do
  install -D -m 0644 "$root/assets/completions/$source" "$stage/usr/share/vortex/assets/completions/$source"
done
for source in README.md LICENSE NOTICE SECURITY.md; do
  install -D -m 0644 "$root/$source" "$stage/usr/share/vortex/$source"
done
for source in build.sh vortex.1 vortex.desktop; do
  mode=0644
  [[ "$source" == "build.sh" ]] && mode=0755
  install -D -m "$mode" "$root/packaging/deb/$source" "$stage/usr/share/vortex/packaging/deb/$source"
done
# Defense in depth if the source allowlist is expanded in the future.
find "$stage/usr/share/vortex" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$stage/usr/share/vortex" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
cp "$root/README.md" "$root/LICENSE" "$root/NOTICE" "$root/SECURITY.md" "$stage/usr/share/doc/$package/"
cp "$root/packaging/deb/vortex.1" "$stage/usr/share/man/man1/vortex.1"
gzip -n -f "$stage/usr/share/man/man1/vortex.1"
cp "$root/assets/completions/vortex.bash" "$stage/usr/share/bash-completion/completions/vortex"
cp "$root/assets/completions/vortex.zsh" "$stage/usr/share/zsh/vendor-completions/_vortex"
cp "$root/assets/completions/vortex.fish" "$stage/usr/share/fish/vendor_completions.d/vortex.fish"
# Desktop integration: menu entry + icon. Operator-started only (vortex serve
# binds loopback); no maintainer scripts, no autostart, no user data.
cp "$root/packaging/deb/vortex.desktop" "$stage/usr/share/applications/vortex.desktop"
cp "$root/assets/hooded-researcher.svg" "$stage/usr/share/icons/hicolor/scalable/apps/vortex.svg"

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
Recommends: zstd
Maintainer: mrtc-solutions
Description: Linux Vortex Terminal
 Local-first Linux cybersecurity and operations workbench with a real
 shell-free execution authority, typed plans, local audit, and factual tools.
 No listener or user data is created during package installation.
CONTROL

# Do not auto-start a daemon or create user state from maintainer scripts.
"$dpkg_deb" --build --root-owner-group "$stage" "$out/${package}_${version}_all.deb" >/dev/null
sha256sum "$out/${package}_${version}_all.deb" > "$out/${package}_${version}_all.deb.sha256"
if [[ -n "${VORTEX_GPG_KEY:-}" ]]; then
  gpg --batch --local-user "$VORTEX_GPG_KEY" --detach-sign --armor "$out/${package}_${version}_all.deb"
fi
printf 'Built %s\n' "$out/${package}_${version}_all.deb"
