# Linux packaging

Supported distributions: Debian 12+, Ubuntu 22.04+, Linux Mint 21+,
Kali rolling — anything with Python 3.10 or newer (the package Depends on
`python3 (>= 3.10)` and nothing else at install time).

## The .deb

`packaging/deb/build.sh` (or `vortex desktop deb`) builds a real, unsigned
CLI `.deb` — the default version is `APP_VERSION` from
`backend/vortex_backend.py` — that installs the Python sidecar, live
frontend, `vortex` launcher, man page, shell completions, and a menu entry
(`vortex serve`, operator-started, loopback by default). It never starts a
daemon, never creates user data, and never installs agents. The package
ships **no maintainer scripts and no conffiles**, so installing a newer
version cleanly replaces every installed file: upgrade and repair are plain
reinstalls. A signed 1.0 package remains a release-VM gate.

Single-file install without a repository:

```bash
packaging/deb/build.sh
sudo apt install ./dist/deb/linux-vortex-terminal_<version>_all.deb
```

## Install by name: the APT repository

`packaging/deb/make-repo.sh` (or `vortex desktop repo`) builds a minimal,
deterministic APT repository from one or more `.deb` files: a `pool/`, one
per-architecture `Packages` index, and a hashed `Release` (with `InRelease`
/ `Release.gpg` plus an exported `vortex-archive-key.asc` when `--sign`
is used). Pass several `--deb` files to keep multiple versions; apt
resolves to the newest one.

```bash
# 1. Build the package, then the repository.
vortex desktop deb
vortex desktop repo            # refuses to overwrite; add --replace to rebuild
# shell equivalent:
# packaging/deb/make-repo.sh --output ./vortex-apt --deb <file>.deb [--deb ...] [--sign KEYID]

# 2. Publish ATOMICALLY: stage the new tree next to the served path, then
#    rename it over the old one. Never rsync/cp INTO the live directory —
#    apt clients must never see a half-written Release/Packages pair.
#    Example for a web root:
#      rsync -a ./vortex-apt/ webhost:/srv/apt/vortex-new/
#      ssh webhost 'mv /srv/apt/vortex /srv/apt/vortex-prev && mv /srv/apt/vortex-new /srv/apt/vortex'
#    (Local-directory installs just copy the tree; there is no live reader.)
#    The tree is published 0755/0644 and must stay world-readable: apt reads
#    a local repository as the unprivileged `_apt` user and a web server as
#    its own account. Debian 12+ and Ubuntu create private home directories
#    (0700/0750), so a copy under $HOME cannot be registered — copy it to a
#    system path such as /srv/vortex-apt instead. install-repo.sh checks
#    this before writing anything and names the blocking directory.

# 3. On the target machine, copy the repository somewhere world-readable and
#    register it from inside that copy (the repo ships its own installer plus
#    NEXT-STEPS.txt), as root:
sudo cp -r /media/usb/vortex-apt /srv/vortex-apt
cd /srv/vortex-apt
sudo ./install-repo.sh --repo-path . --trust-unsigned   # local testing only
# -- or, for a signed repo served over https (any checkout also carries the
#    script at packaging/deb/install-repo.sh):
# sudo ./install-repo.sh --repo-url https://<host>/vortex --key ./vortex-archive-key.asc

# 4. Install, upgrade, and repair by package name.
sudo apt install linux-vortex-terminal
sudo apt upgrade linux-vortex-terminal              # newer version replaces the old one
sudo apt install --reinstall linux-vortex-terminal  # repair a damaged install
```

`install-repo.sh` refreshes the Vortex source on its own before the full
`apt update`; if apt cannot read the new repository, the previous
registration (or its absence) is restored so a broken source never lingers
and fails every later `apt update` on the machine.

## Uninstall

```bash
sudo apt remove linux-vortex-terminal
# purge is identical (the package keeps no conffiles). User data lives
# outside dpkg in ~/.local/share/vortex — remove it for a clean slate:
rm -rf ~/.local/share/vortex
```

The `.deb` also ships this tooling under
`/usr/share/vortex/packaging/deb/`, so an installed machine can rebuild or
re-register a repository without a checkout.

Operator-local install without root: `./vortex install --user` or
`scripts/install-user.sh`. See `docs/USER_GUIDE.md`.
