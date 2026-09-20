#!/usr/bin/env bash
set -euo pipefail
# Register a Vortex APT repository (built by make-repo.sh) on a target
# machine, then refresh APT so `sudo apt install linux-vortex-terminal`
# resolves the package by name. Upgrades and repairs are plain apt
# operations afterwards: the package ships no maintainer scripts and no
# conffiles, so a newer version cleanly replaces every installed file.
#
# Trust model: a signed repository is required by default (the .asc key that
# make-repo.sh --sign exports). --trust-unsigned exists only for local
# testing and prints a loud warning; never use it for a network repository.
umask 022
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

repo_url=""
repo_path=""
codename="stable"
component="main"
key_file=""
key_url=""
root="/"
no_update=0
trust_unsigned=0

usage() {
  cat >&2 <<'EOF'
Usage: install-repo.sh (--repo-url URL | --repo-path DIR)
                       [--codename NAME] [--component NAME]
                       [--key FILE | --key-url URL] [--trust-unsigned]
                       [--root DIR] [--no-update]
EOF
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url) repo_url="${2:-}"; shift 2 ;;
    --repo-path) repo_path="${2:-}"; shift 2 ;;
    --codename) codename="${2:-}"; shift 2 ;;
    --component) component="${2:-}"; shift 2 ;;
    --key) key_file="${2:-}"; shift 2 ;;
    --key-url) key_url="${2:-}"; shift 2 ;;
    --root) root="${2:-}"; shift 2 ;;
    --no-update) no_update=1; shift ;;
    --trust-unsigned) trust_unsigned=1; shift ;;
    -h|--help) usage ;;
    *) echo "unknown argument: $1" >&2; usage ;;
  esac
done

if [[ -n "$repo_url" && -n "$repo_path" ]] || [[ -z "$repo_url" && -z "$repo_path" ]]; then
  echo "exactly one of --repo-url or --repo-path is required" >&2
  usage
fi
if [[ -n "$key_file" && -n "$key_url" ]]; then
  echo "only one of --key or --key-url may be given" >&2
  usage
fi
if [[ "$trust_unsigned" == "0" && -z "$key_file" && -z "$key_url" ]]; then
  echo "a repository signing key is required (--key or --key-url), or pass --trust-unsigned for local testing only" >&2
  exit 2
fi
for field in codename component; do
  value="${!field}"
  if [[ ! "$value" =~ ^[A-Za-z0-9._+-]{1,64}$ ]]; then
    echo "invalid --$field: '$value' (bounded [A-Za-z0-9._+-] only)" >&2
    exit 2
  fi
done
if [[ "$root" != /* ]]; then
  echo "--root must be an absolute path" >&2
  exit 2
fi

# Validate the repository BEFORE writing anything under /etc/apt.
check_repo_tree() {
  if [[ ! -f "$repo_path/dists/$codename/Release" ]]; then
    echo "not a Vortex repository for suite '$codename': $repo_path (missing dists/$codename/Release; build it with make-repo.sh)" >&2
    exit 2
  fi
  if [[ ! -d "$repo_path/dists/$codename/$component" ]]; then
    echo "repository has no component '$component' for suite '$codename': $repo_path" >&2
    exit 2
  fi
  if ! grep -qxF "Codename: $codename" "$repo_path/dists/$codename/Release"; then
    echo "repository Release names a different suite (expected 'Codename: $codename'): $repo_path" >&2
    exit 2
  fi
}

if [[ -n "$repo_path" ]]; then
  if [[ ! -d "$repo_path" ]]; then
    echo "repository directory not found: $repo_path" >&2
    exit 2
  fi
  repo_path=$(cd "$repo_path" && pwd)
  check_repo_tree
  url="file://$repo_path"
else
  url="$repo_url"
  if [[ "$url" == file://* ]]; then
    repo_path="${url#file://}"
    check_repo_tree
  elif [[ ! "$url" =~ ^https?://[^[:space:]]+$ ]]; then
    echo "invalid --repo-url (http(s):// or file://, no whitespace)" >&2
    exit 2
  elif [[ "$url" == http://* ]]; then
    echo "WARNING: plain http repository URL; prefer https for network repositories." >&2
  fi
fi
if [[ "$url" == *[[:space:]]* ]]; then
  echo "repository URL must not contain whitespace" >&2
  exit 2
fi

keyring_name="vortex-archive-keyring.asc"
keyring_path="/usr/share/keyrings/$keyring_name"
if [[ "$trust_unsigned" == "0" ]]; then
  tmp_key=""
  if [[ -n "$key_url" ]]; then
    if [[ ! "$key_url" =~ ^https?://[^[:space:]]+$ ]]; then
      echo "invalid --key-url (http(s)://, no whitespace)" >&2
      exit 2
    fi
    if ! command -v curl >/dev/null 2>&1; then
      echo "curl is required to download the repository key (or download it manually and pass --key)" >&2
      exit 2
    fi
    tmp_key=$(mktemp)
    trap 'rm -f "$tmp_key"' EXIT
    if ! curl -fsSL --max-filesize 1048576 --max-time 60 "$key_url" -o "$tmp_key"; then
      echo "failed to download the repository key from $key_url" >&2
      exit 2
    fi
    key_file="$tmp_key"
  fi
  if [[ ! -f "$key_file" ]]; then
    echo "repository key not found: $key_file" >&2
    exit 2
  fi
  key_bytes=$(stat -c%s "$key_file")
  if [[ "$key_bytes" -le 0 || "$key_bytes" -gt 1048576 ]]; then
    echo "repository key has an invalid size ($key_bytes bytes)" >&2
    exit 2
  fi
  if ! grep -q 'BEGIN PGP PUBLIC KEY BLOCK' "$key_file" || ! grep -q 'END PGP PUBLIC KEY BLOCK' "$key_file"; then
    echo "repository key is not a complete ASCII-armored PGP public key (need BEGIN and END markers): $key_file" >&2
    exit 2
  fi
fi

if [[ "$root" == "/" && "$(id -u)" -ne 0 ]]; then
  echo "writing /etc/apt requires root; re-run with sudo." >&2
  exit 2
fi
# Validate before mutating: if we intend to refresh the index, apt-get must
# exist before the first file is written (the later check stays as a guard).
if [[ "$root" == "/" && "$no_update" == "0" ]] && ! command -v apt-get >/dev/null 2>&1; then
  echo "apt-get not found; cannot refresh the package index (use --no-update to register only)" >&2
  exit 2
fi

mkdir -p "$root/etc/apt/sources.list.d" "$root/usr/share/keyrings"
sources="$root/etc/apt/sources.list.d/vortex.sources"
if [[ "$trust_unsigned" == "1" ]]; then
  cat > "$sources" <<SOURCES
Types: deb
URIs: $url
Suites: $codename
Components: $component
Trusted: yes
SOURCES
  chmod 0644 "$sources"
  echo "WARNING: repository registered WITHOUT signature verification (--trust-unsigned)." >&2
  echo "WARNING: use only for a local repository you built yourself." >&2
else
  cp "$key_file" "$root$keyring_path"
  chmod 0644 "$root$keyring_path"
  cat > "$sources" <<SOURCES
Types: deb
URIs: $url
Suites: $codename
Components: $component
Signed-By: $keyring_path
SOURCES
  chmod 0644 "$sources"
fi

if [[ -n "${tmp_key:-}" ]]; then
  rm -f "$tmp_key"
  trap - EXIT
fi

if [[ "$root" != "/" ]]; then
  echo "Staged APT source at $sources (root=$root); apt-get update skipped." >&2
elif [[ "$no_update" == "1" ]]; then
  echo "Registered $sources; apt-get update skipped (--no-update)." >&2
else
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "apt-get not found; cannot refresh the package index" >&2
    exit 2
  fi
  if command -v timeout >/dev/null 2>&1; then
    timeout 300 apt-get update
  else
    apt-get update
  fi
fi
printf 'Next: sudo apt install linux-vortex-terminal\n'
