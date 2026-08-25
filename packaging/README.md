# Linux packaging

The first release target is a signed `.deb` for supported Linux. Packaging is
intentionally marked as Phase 7 until PTY/session, report, model, and migration
contracts are complete. `packaging/deb/build.sh` refuses to emit a misleading
artifact; it documents the pinned-builder gate instead. No desktop autostart,
systemd unit, listener, or user-data creation belongs in the package.
