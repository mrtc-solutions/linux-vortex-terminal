# Linux packaging

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

# 2. Publish: copy the repo directory to the target machine, or serve it
#    over https from any static web server.

# 3. On the target machine, register the repository (as root). Signed by
#    default; --trust-unsigned is for a local repo you built yourself.
sudo ./install-repo.sh --repo-url https://<host>/vortex --key vortex-archive-key.asc
# local-directory shortcut (testing only):
# sudo ./install-repo.sh --repo-path /path/to/copied/repo --trust-unsigned

# 4. Install, upgrade, and repair by package name.
sudo apt install linux-vortex-terminal
sudo apt upgrade linux-vortex-terminal              # newer version replaces the old one
sudo apt install --reinstall linux-vortex-terminal  # repair a damaged install
```

The `.deb` also ships this tooling under
`/usr/share/vortex/packaging/deb/`, so an installed machine can rebuild or
re-register a repository without a checkout.

Operator-local install without root: `./vortex install --user` or
`scripts/install-user.sh`. See `docs/USER_GUIDE.md`.
