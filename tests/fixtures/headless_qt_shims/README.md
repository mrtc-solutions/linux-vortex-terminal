# Headless Qt shims (acceptance scaffolding only)

Qt's `libQt5Gui`/`libQt6Gui` declare `libGL.so.1` as a shared-library dependency and Qt's
VNC platform plugin additionally links `libdbus-1.so.3`, even though the RFB path paints
exclusively with the raster engine and never opens a session bus. Minimal containers such
as the Vortex acceptance runner may ship neither library, in which case Qt cannot load at
all and a *real* VNC target cannot be started.

`gl_shim.c` and `dbus_standin.c` are compiled on demand by
`tests/remote_desktop_acceptance.py` **only when the real libraries are missing**, so the
acceptance suite can still exercise a genuine RFB server:

* `gl_shim.c` exports the four GL entry points `libQt5Gui` references and aborts loudly if
  any of them is ever called — a GL code path can never be silently faked.
* `dbus_standin.c` reports the honest state of such a container: no session bus, so
  D-Bus lookups fail exactly as they do for a real `libdbus-1` on a machine without a bus.

Neither file is part of the application, neither is shipped, and CI installs the real
libraries (Mesa + D-Bus) with the other acceptance dependencies.
