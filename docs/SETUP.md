# New PC setup — install Vortex Terminal from GitHub

This is the operator path for a **fresh Linux PC**. The GitHub tree and the
`.deb` ship the application. They do **not** ship multi-gigabyte local LLM
weights. After install, open **Dependencies** (present + missing) and import
or download models yourself.

## Minimum hardware (not a maximum)

| Item | Minimum | Notes |
|---|---|---|
| RAM | **2 GB** | Floor. More RAM automatically uses a higher GGUF/council profile. |
| CPU | **2 GHz Intel i5 class** (or equivalent) | Floor. Extra cores raise thread/context caps. |
| OS | Debian 12+, Ubuntu 22.04+, Mint 21+, Kali rolling | Python 3.10+ |
| Disk | ~200 MB for the app; **~4 GB extra** if you keep both curated GGUF files | Weights stay outside Git |

## 1. Get the source

```bash
git clone https://github.com/mrtc-solutions/linux-vortex-terminal.git
cd linux-vortex-terminal
```

## 2. Install the app (`sudo apt install` still works)

The package name is `linux-vortex-terminal`. GitHub is not an apt mirror, so
you either install the built `.deb` by path, or register a repository you
publish.

### Option A — local `.deb` (any checkout)

```bash
# Optional desktop UI (skip if you only want the CLI sidecar)
npm ci
npm run build

packaging/deb/build.sh
sudo apt install ./dist/deb/linux-vortex-terminal_*_all.deb
```

`sudo apt install ./path/to.deb` works while the project lives on GitHub.
You do **not** need a public PPA for that path.

### Option B — install by package name

Build and register a repository (see [`packaging/README.md`](../packaging/README.md)):

```bash
./vortex desktop deb
./vortex desktop repo --output /srv/vortex-apt
cd /srv/vortex-apt
sudo ./install-repo.sh --repo-path . --trust-unsigned   # local testing only
sudo apt install linux-vortex-terminal
```

### Option C — user-local, no root

```bash
./vortex install --user
export PATH="$HOME/.local/bin:$PATH"
```

The `.deb` never starts a daemon, never writes `~/.local/share/vortex`, and
never downloads models.

## 3. What is in the install vs what you add

| Ships with GitHub / `.deb` | You add after install (Dependencies / Models) |
|---|---|
| Python sidecar, CLI, React UI, icons | Curated GGUF files (`Llama-3.2-3B…`, `Qwen2.5-3B…`) |
| Built-in `vortex-local` advisor | Optional `llama-cpp-python` / `llama-cli` / llamafile |
| Setup manifest (`packaging/setup-manifest.json`) | Optional Ollama + loopback models |
| Apt plans for distro tools (`nmap`, `podman`, …) | Those packages, via Guardian-reviewed apt |

Manifest: [`packaging/setup-manifest.json`](../packaging/setup-manifest.json).  
GGUF placement: [`models/README.md`](../models/README.md).

## 4. First launch on the new PC

```bash
vortex serve --bind-host 127.0.0.1 --bind-port 8765
# or, from a checkout with Node:
npm start
```

1. The **Host dependencies** popup lists **present** and **missing** items.
2. Tap **Refresh** if a probe failed. Tap **Rescan host** after an apt install.
3. For Debian packages: **Create reviewed install plan** (Guardian + OS sudo).
4. For local LLMs: download the GGUF yourself (see `models/README.md`) **or**
   **Open Models → import** a file already on disk. Vortex Terminal never
   silent-downloads weights.
5. Every popup has **Minimise**, **Maximise**, and **Exit**.

## 5. Confirm

```bash
vortex doctor --json
vortex deps --json
vortex model status --json
python3 scripts/final_gates.py
```

Missing tools stay `absent`. The deterministic core and Guardian still work
without a local model.
