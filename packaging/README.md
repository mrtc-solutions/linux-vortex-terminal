# Linux packaging

`packaging/deb/build.sh` builds a real, unsigned CLI `.deb` (default version
0.2.21) that installs the Python sidecar, frontend, `vortex` launcher, and a
menu entry (`vortex serve`, operator-started, loopback by default).
It never starts a daemon, never creates user data, and never installs
agents. A signed 1.0 package remains a release-VM gate.

Operator-local install without root: `./vortex install --user` or
`scripts/install-user.sh`. See `docs/USER_GUIDE.md`.
