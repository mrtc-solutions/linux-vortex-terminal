#!/usr/bin/env bash
set -euo pipefail
# Build a minimal, deterministic APT repository from one or more .deb files.
# Layout (per Debian convention):
#   <output>/pool/<component>/<file>.deb
#   <output>/dists/<codename>/<component>/binary-<arch>/Packages{,.gz,.xz?}
#   <output>/dists/<codename>/{Release,InRelease?,Release.gpg?}
# Indexes are generated with dpkg-deb field extraction only, so the only
# builder requirement beyond coreutils+gzip is dpkg-deb (no apt-ftparchive).
umask 022
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

out=""
codename="stable"
component="main"
origin="Vortex"
sign_key=""
declare -a debs=()

usage() {
  cat >&2 <<'EOF'
Usage: make-repo.sh --output DIR --deb FILE [--deb FILE...]
                    [--codename NAME] [--component NAME] [--origin NAME]
                    [--sign KEYID]
EOF
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) out="${2:-}"; shift 2 ;;
    --deb) debs+=("${2:-}"); shift 2 ;;
    --codename) codename="${2:-}"; shift 2 ;;
    --component) component="${2:-}"; shift 2 ;;
    --origin) origin="${2:-}"; shift 2 ;;
    --sign) sign_key="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown argument: $1" >&2; usage ;;
  esac
done

[[ -n "$out" ]] || { echo "--output is required" >&2; usage; }
[[ "${#debs[@]}" -gt 0 ]] || { echo "at least one --deb is required" >&2; usage; }
for field in codename component origin; do
  value="${!field}"
  if [[ ! "$value" =~ ^[A-Za-z0-9._+-]{1,64}$ ]]; then
    echo "invalid --$field: '$value' (bounded [A-Za-z0-9._+-] only)" >&2
    exit 2
  fi
done
if [[ -e "$out" ]]; then
  echo "refusing to overwrite existing path: $out (remove it first)" >&2
  exit 2
fi
if [[ -n "$sign_key" && ( "$sign_key" == -* || "$sign_key" == *$'\n'* || "${#sign_key}" -gt 128 ) ]]; then
  echo "invalid --sign key id (must not start with - or contain a newline)" >&2
  exit 2
fi

dpkg_deb="${VORTEX_DPKG_DEB:-}"
if [[ -z "$dpkg_deb" ]]; then
  dpkg_deb=$(command -v dpkg-deb || true)
fi
if [[ -z "$dpkg_deb" || "$dpkg_deb" != /* || ! -x "$dpkg_deb" ]]; then
  echo "dpkg-deb is required to build an APT repository" >&2
  exit 2
fi
for tool in sha256sum sha1sum md5sum stat gzip date; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "$tool is required to build an APT repository" >&2
    exit 2
  fi
done
have_xz=0
if command -v xz >/dev/null 2>&1; then have_xz=1; fi
if [[ -n "$sign_key" ]] && ! command -v gpg >/dev/null 2>&1; then
  echo "gpg is required for --sign (omit --sign for an unsigned local repository)" >&2
  exit 2
fi

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

pool="$stage/pool/$component"
mkdir -p "$pool"
declare -a seen=()
declare -a archs=()

# field <deb> <name>: print one control field, failing on wrapped values.
field() {
  local value
  value=$("$dpkg_deb" --field "$1" "$2" 2>/dev/null || true)
  if [[ "$value" == *$'\n'* && "$2" != "Description" ]]; then
    echo "control field $2 of $1 is not single-line" >&2
    exit 2
  fi
  printf '%s' "$value"
}

for deb in "${debs[@]}"; do
  if [[ ! -f "$deb" ]]; then
    echo "not a regular file: $deb" >&2
    exit 2
  fi
  pkg=$(field "$deb" Package)
  ver=$(field "$deb" Version)
  arch=$(field "$deb" Architecture)
  if [[ ! "$pkg" =~ ^[a-z0-9][a-z0-9+.-]{0,63}$ ]]; then
    echo "invalid Package name '$pkg' in $deb" >&2
    exit 2
  fi
  if [[ -z "$ver" || "$ver" == *[[:space:]]* ]]; then
    echo "invalid Version '$ver' in $deb" >&2
    exit 2
  fi
  if [[ ! "$arch" =~ ^[A-Za-z0-9_+-]{1,32}$ ]]; then
    echo "invalid Architecture '$arch' in $deb" >&2
    exit 2
  fi
  key="$pkg|$ver|$arch"
  for prior in ${seen[@]+"${seen[@]}"}; do
    if [[ "$prior" == "$key" ]]; then
      echo "duplicate package $pkg $ver ($arch)" >&2
      exit 2
    fi
  done
  seen+=("$key")
  base=$(basename "$deb")
  if [[ -e "$pool/$base" ]]; then
    echo "filename collision in pool: $base (rename one input)" >&2
    exit 2
  fi
  cp "$deb" "$pool/$base"
  chmod 0644 "$pool/$base"

  dir="$stage/dists/$codename/$component/binary-$arch"
  mkdir -p "$dir"
  {
    echo "Package: $pkg"
    echo "Version: $ver"
    echo "Architecture: $arch"
    for optional in Maintainer Depends Recommends Section Priority Homepage Installed-Size; do
      value=$(field "$deb" "$optional")
      [[ -n "$value" ]] && echo "$optional: $value"
    done
    echo "Filename: pool/$component/$base"
    echo "Size: $(stat -c%s "$pool/$base")"
    echo "SHA256: $(sha256sum "$pool/$base" | cut -d' ' -f1)"
    echo "SHA1: $(sha1sum "$pool/$base" | cut -d' ' -f1)"
    echo "MD5sum: $(md5sum "$pool/$base" | cut -d' ' -f1)"
    # dpkg-deb --field prints the raw Description paragraph; re-emit it as
    # the stanza tail so multi-line descriptions stay intact.
    desc=$(field "$deb" Description)
    if [[ -n "$desc" ]]; then
      echo "Description: ${desc%%$'\n'*}"
      rest="${desc#*$'\n'}"
      if [[ "$rest" != "$desc" ]]; then
        printf '%s\n' "$rest" | while IFS= read -r line; do
          [[ "$line" == " "* ]] && printf '%s\n' "$line" || printf ' %s\n' "$line"
        done
      fi
    fi
    echo ""
  } >> "$dir/Packages"
  known=0
  for have in ${archs[@]+"${archs[@]}"}; do
    [[ "$have" == "$arch" ]] && known=1
  done
  [[ "$known" == "0" ]] && archs+=("$arch")
done

mapfile -t sorted_archs < <(printf '%s\n' "${archs[@]}" | LC_ALL=C sort)
index_dir="$stage/dists/$codename"
for arch in "${sorted_archs[@]}"; do
  dir="$index_dir/$component/binary-$arch"
  # gzip -n keeps the compressed index byte-deterministic.
  gzip -n -9 -c "$dir/Packages" > "$dir/Packages.gz"
  if [[ "$have_xz" == "1" ]]; then
    xz -9 -c "$dir/Packages" > "$dir/Packages.xz"
  fi
done

{
  echo "Origin: $origin"
  echo "Label: $origin"
  echo "Suite: $codename"
  echo "Codename: $codename"
  echo "Date: $(date -u +"%a, %d %b %Y %H:%M:%S UTC")"
  echo "Architectures: ${sorted_archs[*]}"
  echo "Components: $component"
  echo "Description: $origin APT repository"
  for algo in MD5Sum SHA1 SHA256; do
    case "$algo" in
      MD5Sum) sum=md5sum ;; SHA1) sum=sha1sum ;; SHA256) sum=sha256sum ;;
    esac
    echo "$algo:"
    while IFS= read -r -d '' index; do
      rel="${index#"$index_dir"/}"
      printf ' %s %16d %s\n' "$($sum "$index" | cut -d' ' -f1)" "$(stat -c%s "$index")" "$rel"
    done < <(find "$index_dir/$component" -type f \( -name 'Packages' -o -name 'Packages.gz' -o -name 'Packages.xz' \) -print0 | LC_ALL=C sort -z)
  done
} > "$index_dir/Release"

if [[ -n "$sign_key" ]]; then
  gpg --batch --yes --local-user "$sign_key" --clearsign -o "$index_dir/InRelease" "$index_dir/Release"
  gpg --batch --yes --local-user "$sign_key" --detach-sign --armor -o "$index_dir/Release.gpg" "$index_dir/Release"
  gpg --batch --yes --export --armor "$sign_key" > "$stage/vortex-archive-key.asc"
  if ! grep -q 'BEGIN PGP PUBLIC KEY BLOCK' "$stage/vortex-archive-key.asc"; then
    echo "gpg did not export a public key for '$sign_key'" >&2
    exit 2
  fi
  signed="yes"
else
  signed="no (unsigned local repository)"
fi

mkdir -p "$(dirname "$out")"
mv "$stage" "$out"
trap - EXIT
printf 'Built APT repository at %s (%d package(s), archs: %s, signed: %s)\n' \
  "$out" "${#debs[@]}" "${sorted_archs[*]}" "$signed"
