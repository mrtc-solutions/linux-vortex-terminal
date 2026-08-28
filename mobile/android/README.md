# VORTEX Android client

The Android application is a WebView of the same VORTEX workbench that runs on
Linux. It does not reimplement execution: the Python sidecar on the Kali/Linux
host remains the only process authority.

## Build from this workbench

```bash
./vortex mobile apk --sidecar-url http://<kali-ip>:8765/
```

Or click **DOWNLOAD APK** in the workbench. That button always re-syncs the
live frontend into the package before the download starts.

The APK is written under `$XDG_DATA_HOME/vortex/mobile/vortex.apk` (or
`VORTEX_DATA_DIR/mobile/vortex.apk`).

## Install

1. Copy `vortex.apk` to the phone.
2. Allow installation from unknown sources for the file manager used.
3. Open the app. It loads the sidecar URL baked in at sync time.
4. If the URL is unreachable, the connect page lets you enter the host URL.

The phone and the Kali host must share a network path (LAN/VPN). Bind the
sidecar with `./vortex serve --bind-host 0.0.0.0 --bind-port 8765` for LAN
access.

## License

MIT. See `LICENSE` in the repository and inside `assets/LICENSE` in the APK.
