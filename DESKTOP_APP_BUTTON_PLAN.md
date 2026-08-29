# Desktop Application Button — Implementation Plan

Status: **implemented and audited** (commit `386d866`, 2026-08-29) · Shipped version: 0.2.21 · Branch: `arena/01a04d85-linux-vortex-terminal`

Audit result: every plan item shipped with no deviation; the change is purely
additive (no existing route, window, terminal, or policy behavior touched —
verified by full-suite run 176/176 + 4 JS suites + lint, and a 15-route live
battery of pre-existing endpoints returning identical statuses). Both download
flows re-verified from a wiped artifact state: honest 404 before build, byte-
identical downloads after, valid v1-signed APK (AXML/DEX verified) and valid
unsigned .deb (dpkg-deb, zero maintainer scripts).

## Goal

Add a **DOWNLOAD DESKTOP APP** control that packages the *live* workbench as a
real Linux `.deb` and downloads it — the desktop twin of the (now working)
DOWNLOAD APK flow. Same guarantees: always rebuilt from the running tree so it
cannot lag behind, honest artifact, no daemons, no silent installs.

## Ground rules (same as the APK fix)

1. **Read before writing.** The flow below was traced through the real code:
   `packaging/deb/build.sh`, `backend/vortex_backend.py` (routes + token gate),
   `backend/mobile/apkbuild.py` (pattern to mirror), `frontend/app.js`
   (`downloadApk` + layered trigger), `frontend/index.html` (settings grid),
   `cli/vortex.py` (`mobile apk` subcommand).
2. **Do not tamper with functionality.** No changes to execution policy,
   Guardian, PTY, engagements, or window management. The button is additive.
3. **No fake artifacts.** If `dpkg-deb` is missing, the button reports an
   actionable error — it never serves a placeholder file (repo policy:
   `packaging/README.md`, README "Signed .deb remains a release-VM gate").

## What exists today (evidence)

| Piece | Status |
|---|---|
| `.deb` builder | `packaging/deb/build.sh` — real, reviewed; stages `backend/ cli/ frontend/ assets/`, man page, shell completions, `/usr/bin/vortex` wrapper; `dpkg-deb --build`; **no maintainer scripts, no daemon** |
| Builder inputs | Takes an output-dir argument and `VORTEX_VERSION` env — already parameterized for reuse |
| Freshness | `build.sh` copies from the repo tree the running sidecar serves → a rebuild is always current (same guarantee the APK has) |
| Electron shell | `desktop/main.js` spawns the sidecar; **deliberately NOT shipped in the .deb** ("Electron remains optional" — build.sh comment) |
| Ignore rules | `.gitignore` already excludes `*.deb` and `dist/` — binaries stay out of git |
| Tools | `dpkg-deb 1.21.23` present in this environment ✓ |
| Auth model | All POST routes pass through the `X-Vortex-Token` sidecar-capability gate (`do_POST` line 3777) — new routes inherit it automatically; no new privilege surface |
| UI space | Settings grid has the "Android APK" card (`id="download-apk-settings"`, index.html ~line 150) — a sibling card drops in cleanly; the topbar was just decongested and stays untouched |

## Design

### Backend — mirror `mobile.apkbuild`, reuse `build.sh`

New module `backend/debbuild.py` (pattern: `backend/mobile/apkbuild.py`):

- `build_deb(output_dir=None) -> dict`:
  - output root = `data_root()/desktop/` (mode 0700, **outside the repo**), never `dist/` inside the repo;
  - runs the existing `packaging/deb/build.sh <out>` via `subprocess` with
    `VORTEX_VERSION = APP_VERSION` — **single source of truth**, no duplicated
    packaging logic; a pre-flight `shutil.which("dpkg-deb")` check yields the
    honest error message;
  - computes `sha256`, `size_bytes`, `mtime`, and a `frontend_digest` (same
    digest over the staged `frontend/` files as `sync_payload` uses) so the UI
    can prove the package matches the live workbench;
  - returns `ok/built/path/filename/version/sha256/size_bytes/license`.
- `deb_status() -> dict` — mirrors `apk_status()`.
- **Always rebuild on POST** (no stale artifact can ever be downloaded).

### Routes — mirror `/api/mobile/apk*` exactly

In `backend/vortex_backend.py`:

| Route | Behavior |
|---|---|
| `GET /api/desktop/deb` | status (`deb_status()`), like line 3617 |
| `POST /api/desktop/deb` | `build_deb()` → 201, like line 4009 |
| `GET /api/desktop/deb/download` | stream the `.deb`, `Content-Type: application/vnd.debian.binary-package`, `Content-Disposition: attachment; filename="linux-vortex-terminal_<ver>_all.deb"`, like line 3623 |

### Frontend — reuse the fixed, layered download trigger

In `frontend/app.js`:

- generalize `triggerApkDownload()` → `triggerDownload(url, filename)` (tab
  first, anchor fallback — the exact fix from 0.2.20; APK call sites updated,
  behavior identical);
- `downloadDeb()` mirrors `downloadApk()`: POST build → trigger → toast with a
  manual **DOWNLOAD .deb** link (10 s) for sandboxed contexts;
- bind `download-deb` and `download-deb-settings`.

In `frontend/index.html` (Settings, after the Android APK card):

```html
<section class="panel setting-card">
  <div class="setting-icon amber-bg">⌁</div>
  <div><h2>Desktop app</h2>
  <p>Download a Linux .deb of this workbench (vortex CLI + sidecar + this
  frontend), rebuilt from the live tree. Unsigned — review before install.
  The Electron shell is not bundled; run it from a checkout.</p></div>
  <button class="secondary-button" id="download-deb-settings">DOWNLOAD .DEB</button>
</section>
```

**Placement decision (recommendation): Settings card only.** The topbar was
just decongested (7 controls) and a second download button would re-crowd it.
The card is where "get this app elsewhere" actions already live. If topbar
parity with DOWNLOAD APK is wanted, `DOWNLOAD .DEB` can be added safely — the
topbar now wraps — but it is not needed for the flow to work.

### Desktop integration (small, in-policy addition to `build.sh`)

Ship a menu entry so the package is a real desktop application:

- `packaging/deb/vortex.desktop` → `Exec=vortex serve` (operator-started,
  never auto-run), `Icon=vortex`, `Terminal=true`;
- install `assets/hooded-researcher.svg` → `/usr/share/icons/hicolor/scalable/apps/vortex.svg`
  and the `.desktop` → `/usr/share/applications/` in `build.sh`;
- no `postinst`/`prerm` scripts, no user data, no autostart — unchanged policy.

### CLI parity

`cli/vortex.py`: add `desktop` command group with `deb` action
(mirrors `mobile apk`, line 248/371): `./vortex desktop deb [--output DIR]`.

## Explicit non-goals

- **No Electron bundling / AppImage** — repo policy keeps Electron optional;
  a signed bundled package is the 1.0 release-VM gate. The button's copy says
  so honestly instead of shipping something misleading.
- **No signing** in-app (GPG stays a release-VM step; message states "unsigned").
- **No apt repository, no auto-install** — the button downloads; the operator
  reviews and installs with `dpkg -i` / `apt install ./file.deb`.
- **No topbar changes, no window-management changes, no policy changes.**

## Verification gate (must all pass before commit)

1. `npm test` — 171+ Python tests and all 4 JS suites pass, plus new:
   - `tests/test_desktop_deb.py`: builds into a temp dir; `dpkg-deb -I` shows
     correct control fields/version; `dpkg-deb -x` extract contains the live
     `frontend/app.js`; marker-file edit changes the sha256 on rebuild
     (freshness proof, mirroring `test_rebuild_picks_up_frontend_changes`);
     missing-`dpkg-deb` path returns the honest error;
   - `tests/test_frontend.js`: button ids exist, `triggerDownload` used,
     settings card present, topbar untouched;
   - `tests/test_frontend_runtime.js`: `downloadDeb()` exercises the mocked
     route, tab trigger, and manual toast link.
2. `npm run lint` clean.
3. **Live end-to-end** against the sidecar preview:
   `POST /api/desktop/deb` → 201 with digest; `GET /api/desktop/deb/download`
   → correct MIME + disposition; extract the downloaded file and assert the
   0.2.21 frontend is inside; `dpkg-deb --info` clean.
4. Click-test in the live preview (tab download + manual toast link).
5. Version bump 0.2.19→0.2.20 precedent followed: `package.json`,
   `apkbuild.py`/`axml.py`, `APP_VERSION`, CLI `--version`, sidebar/terminal
   strings, CHANGELOG entry.
6. Commit **source only** — the `.deb` stays under `~/.local/share/vortex/desktop/`
   (gitignored by policy and pattern).

## Rollout

One commit on `arena/01a04d85-linux-vortex-terminal`: backend module + routes,
frontend button + trigger refactor, `build.sh` desktop-entry addition, CLI
subcommand, tests, CHANGELOG, version bump. Live preview left running for the
operator to click-test both download buttons.
