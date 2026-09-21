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
# Single source of truth: backend/vortex_backend.py APP_VERSION. VORTEX_VERSION
# (set by backend.debbuild) wins when present; the literal is a last-resort
# fallback if the source tree is damaged. The regex below still bounds it.
if [[ -z "${VORTEX_VERSION:-}" ]]; then
  version=$(sed -n 's/^APP_VERSION = "\(.*\)"$/\1/p' "$root/backend/vortex_backend.py" | head -n 1)
  version="${version:-0.3.0}"
else
  version="$VORTEX_VERSION"
fi
package="linux-vortex-terminal"
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
cd "$root"

# Debian versions use letters, digits, and ``.+:~-`` after their mandatory
# leading digit.  In particular, an underscore is *not* legal; accepting one
# here used to defer a clear operator-input error to dpkg-deb after staging the
# entire payload.
if [[ ! "$version" =~ ^[0-9][0-9A-Za-z.+:~-]{0,63}$ ]]; then
  echo "VORTEX_VERSION is not a valid bounded Debian version" >&2
  exit 2
fi
# The control file is written through an expanding heredoc, so a crafted
# VORTEX_HOMEPAGE could inject control fields. Bound it to one plain URL.
# (The pattern lives in a variable because an unquoted & is a syntax error
# inside [[ =~ ]].)
homepage_re='^https?://[A-Za-z0-9./_~:?#@!$&'"'"'()*+,;=%-]{1,200}$'
if [[ -n "${VORTEX_HOMEPAGE:-}" && ! "$VORTEX_HOMEPAGE" =~ $homepage_re ]]; then
  echo "VORTEX_HOMEPAGE is not a valid bounded URL" >&2
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
  "$stage/usr/share/applications" "$stage/usr/share/icons/hicolor/scalable/apps" \
  "$stage/usr/share/icons/hicolor/16x16/apps" "$stage/usr/share/icons/hicolor/24x24/apps" \
  "$stage/usr/share/icons/hicolor/32x32/apps" "$stage/usr/share/icons/hicolor/48x48/apps" \
  "$stage/usr/share/icons/hicolor/64x64/apps" "$stage/usr/share/icons/hicolor/128x128/apps" \
  "$stage/usr/share/icons/hicolor/256x256/apps" "$stage/usr/share/pixmaps"

# The production React shell is a self-contained, CSP-hashed document.
# Never silently release the legacy UI because the frontend build was omitted.
if [[ ! -f "$root/dist/index.html" ]]; then
  echo "React build missing: run npm ci && npm run build before packaging." >&2
  exit 2
fi
# The remote-desktop window needs the noVNC RFB client, which is inlined into
# this document by the build. Ship an actionable failure instead of a package
# whose desktop window would open blank.
if ! grep -q 'vortex.rfb.v1' "$root/dist/index.html"; then
  echo "React build is missing the bundled noVNC client (no RFB subprotocol marker)." >&2
  echo "Run: npm ci && npm run build  (dependency: @novnc/novnc, MPL-2.0)" >&2
  exit 2
fi
install -D -m 0644 "$root/dist/index.html" "$stage/usr/share/vortex/dist/index.html"

# This package carries a bundled MPL-2.0 component, so its license text and the
# build-time notice must ship with it. Refuse to emit a package that would omit
# them rather than silently distributing noVNC without its license.
novnc_license="$root/node_modules/@novnc/novnc/LICENSE.txt"
if [[ ! -f "$novnc_license" ]]; then
  echo "noVNC license text not found at $novnc_license" >&2
  echo "Run: npm ci  (it installs @novnc/novnc, MPL-2.0, whose license must ship)" >&2
  exit 2
fi
install -D -m 0644 "$novnc_license" "$stage/usr/share/doc/$package/noVNC-LICENSE.txt"
# noVNC's own notice refers to the MPL 2.0 text; ship the full text too so the
# package is self-contained for license review.
for candidate in /usr/share/common-licenses/MPL-2.0; do
  if [[ -f "$candidate" ]]; then
    install -D -m 0644 "$candidate" "$stage/usr/share/doc/$package/MPL-2.0.txt"
    break
  fi
done

# Ship only reviewed source file types and explicit frontend/assets. A blanket
# `cp -a` would silently include an operator's untracked .env, editor backup,
# bytecode cache, or other checkout residue in a downloadable package.
while IFS= read -r -d '' source; do
  install -D -m 0644 "$source" "$stage/usr/share/vortex/$source"
done < <(find backend cli -type f -name '*.py' -print0)
for source in index.html app.js workspace.js terminal.js windows.js models.js aiops.js agent.js hud.js styles.css; do
  install -D -m 0644 "$root/frontend/$source" "$stage/usr/share/vortex/frontend/$source"
done
for source in README.md hooded-researcher.svg; do
  install -D -m 0644 "$root/assets/$source" "$stage/usr/share/vortex/assets/$source"
done
if [[ -d "$root/assets/icons" ]]; then
  while IFS= read -r -d '' icon; do
    install -D -m 0644 "$icon" "$stage/usr/share/vortex/assets/icons/$(basename "$icon")"
  done < <(find "$root/assets/icons" -type f \( -name 'vortex.svg' -o -name 'vortex.png' -o -name 'vortex-*.png' \) -print0)
fi
for source in vortex.bash vortex.zsh vortex.fish; do
  install -D -m 0644 "$root/assets/completions/$source" "$stage/usr/share/vortex/assets/completions/$source"
done
for source in README.md LICENSE LICENSES.md NOTICE SECURITY.md; do
  install -D -m 0644 "$root/$source" "$stage/usr/share/vortex/$source"
done
if [[ -f "$root/docs/SETUP.md" ]]; then
  install -D -m 0644 "$root/docs/SETUP.md" "$stage/usr/share/vortex/docs/SETUP.md"
fi
if [[ -f "$root/models/README.md" ]]; then
  install -D -m 0644 "$root/models/README.md" "$stage/usr/share/vortex/models/README.md"
fi
if [[ -f "$root/packaging/setup-manifest.json" ]]; then
  install -D -m 0644 "$root/packaging/setup-manifest.json" "$stage/usr/share/vortex/packaging/setup-manifest.json"
fi
for source in build.sh make-repo.sh install-repo.sh vortex.1 vortex.desktop; do
  mode=0644
  [[ "$source" == *.sh ]] && mode=0755
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
icon_svg="$root/assets/icons/vortex.svg"
if [[ ! -f "$icon_svg" ]]; then
  icon_svg="$root/assets/hooded-researcher.svg"
fi
cp "$icon_svg" "$stage/usr/share/icons/hicolor/scalable/apps/vortex.svg"
# Raster sizes so menus that ignore SVG still show a real Vortex icon.
for size in 16 24 32 48 64 128 256; do
  png="$root/assets/icons/vortex-${size}.png"
  if [[ -f "$png" ]]; then
    cp "$png" "$stage/usr/share/icons/hicolor/${size}x${size}/apps/vortex.png"
  fi
done
if [[ -f "$root/assets/icons/vortex.png" ]]; then
  cp "$root/assets/icons/vortex.png" "$stage/usr/share/pixmaps/vortex.png"
fi

cat > "$stage/usr/bin/vortex" <<'WRAPPER'
#!/bin/sh
# -X utf8 pins the interpreter to UTF-8 mode so C-locale machines (or
# PYTHONCOERCECLOCALE=0 environments) cannot crash non-ASCII output.
exec /usr/bin/python3 -X utf8 /usr/share/vortex/cli/vortex.py "$@"
WRAPPER
chmod 0755 "$stage/usr/bin/vortex"
# Floor is 3.10 (Ubuntu 22.04 ships 3.10): shipped code is grammar-gated and
# API-swept for 3.10 in tests/test_apt_repo.py, so no 3.11-only construct can
# slip back in. Re-verify before ever raising this bound.
installed_kb=$(du -sk --exclude=DEBIAN "$stage" | cut -f1)
if [[ ! "$installed_kb" =~ ^[0-9]{1,12}$ ]]; then
  echo "could not measure the installed payload size" >&2
  exit 2
fi
cat > "$stage/DEBIAN/control" <<CONTROL
Package: $package
Version: $version
Section: utils
Priority: optional
Architecture: all
Installed-Size: $installed_kb
Depends: python3 (>= 3.10)
Recommends: zstd
Maintainer: mrtc-solutions
Homepage: ${VORTEX_HOMEPAGE:-https://github.com/mrtc-solutions/linux-vortex-terminal}
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
