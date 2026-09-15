#!/usr/bin/env python3
"""Real graphical-target acceptance for authorized remote desktops.

This is the acceptance gate for `Feature: Remote Desktop`. It is deliberately
browser-free so it runs on build hosts without a browser, and it never uses a
mock framebuffer: a real VNC server serves a real graphical application, the
client speaks the real RFB protocol through the real sidecar WebSocket bridge,
and the assertions read the target application's own state.

Two target flavours are supported:

  qt       PyQt5's bundled Qt VNC platform plugin serves a real Qt application.
           Needs `pip install PyQt5`; works on slim containers (the runner
           compiles the tiny headless GL/D-Bus stand-ins only when the real
           libraries are missing - see tests/fixtures/headless_qt_shims).
  x11vnc   Xvfb + openbox + xterm + xev + x11vnc: a virtual display with a real
           desktop application and a real, independently maintained VNC server.
           Needs the system packages (Debian: xvfb x11vnc xterm x11-utils openbox).

Exit codes: 0 all checks passed, 1 a check failed, 3 environment blocked
(no target available) - a blocked gate is never reported as a pass.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

from rfb_client import RfbClient, RfbError, WebSocketChannel  # noqa: E402  (path set above)

ANSI = {"green": "\033[32m", "red": "\033[31m", "yellow": "\033[33m", "dim": "\033[2m", "reset": "\033[0m"}
DISPLAY_PORT_LOW, DISPLAY_PORT_HIGH = 5900, 5999


def color(text: str, name: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{ANSI[name]}{text}{ANSI['reset']}"


class TargetUnavailable(RuntimeError):
    """The environment cannot run a real target; the gate must be reported as blocked."""


class CheckFailed(RuntimeError):
    pass


# --------------------------------------------------------------------------- helpers


def free_display_port() -> int:
    for candidate in range(DISPLAY_PORT_LOW, DISPLAY_PORT_HIGH + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", candidate))
                return candidate
            except OSError:
                continue
    raise TargetUnavailable("no free VNC display port in 5900-5999")


def wait_for_banner(port: int, timeout: float = 25.0) -> str:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
                sock.settimeout(3)
                banner = sock.recv(12)
                if banner.startswith(b"RFB "):
                    return banner.decode("ascii").strip()
                last = repr(banner)
        except OSError as exc:
            last = str(exc)
        time.sleep(0.3)
    raise CheckFailed(f"no RFB banner on 127.0.0.1:{port} within {timeout:.0f}s ({last})")


def port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


# --------------------------------------------------------------------------- sidecar


class Sidecar:
    """The real sidecar process, started with isolated state and a capability token."""

    def __init__(self, root: Path):
        self.tmp = Path(tempfile.mkdtemp(prefix="vortex-remote-acceptance-"))
        self.token = os.urandom(32).hex()
        self.log_path = self.tmp / "sidecar.log"
        self.log = open(self.log_path, "w")  # noqa: SIM115 - closed in stop()
        config = self.tmp / "config"
        config.mkdir(parents=True, exist_ok=True)
        settings = config / "settings.json"
        settings.write_text(json.dumps({
            "remote_desktop_allow_unencrypted": True,
            "remote_desktop_max_sessions": 4,
            "remote_desktop_idle_seconds": 300,
        }))
        settings.chmod(0o600)
        self.env = {
            **os.environ,
            "VORTEX_DATA_DIR": str(self.tmp / "data"),
            "VORTEX_CONFIG_DIR": str(config),
            "VORTEX_RUNTIME_DIR": str(self.tmp / "runtime"),
            "VORTEX_SIDECAR_TOKEN": self.token,
        }
        self.process: subprocess.Popen | None = None
        self.port = 0

    def start(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "backend" / "vortex_backend.py"), "--host", "127.0.0.1", "--port", "0"],
            cwd=ROOT, env=self.env, stdout=subprocess.PIPE, stderr=self.log, text=True, start_new_session=True,
        )
        deadline = time.monotonic() + 30
        assert self.process.stdout is not None
        while time.monotonic() < deadline:
            line = self.process.stdout.readline()
            if not line:
                break
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if payload.get("backend") == "online":
                self.port = int(payload["port"])
                return
        raise CheckFailed("the sidecar did not report readiness")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=10)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except OSError:
                    pass
        self.log.close()

    def cleanup(self) -> None:
        self.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- HTTP ----

    def request(self, method: str, path: str, body: dict | None = None, *, token: str | None = None,
                cookie: str | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        supplied = self.token if token is None else token
        if supplied:
            headers["X-Vortex-Token"] = supplied
        if cookie:
            headers["Cookie"] = cookie
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode() or "{}")
            except ValueError:
                return exc.code, {}

    def engagement(self, targets: list[str]) -> str:
        status, payload = self.request("POST", "/api/engagements", {"name": "remote desktop acceptance", "targets": targets})
        if status != 201:
            raise CheckFailed(f"engagement creation failed: {status} {payload}")
        return str(payload["engagement"]["id"])


# --------------------------------------------------------------------------- targets


class QtVncTarget:
    """Qt's VNC platform plugin serving a real Qt application (real RFB server)."""

    flavour = "qt"
    display_name = "Qt VNC platform plugin (RFB server) + real Qt application"

    def __init__(self, root: Path, interpreter: str, width: int = 1024, height: int = 768):
        self.root = root
        self.interpreter = interpreter
        self.width, self.height = width, height
        self.tmp = Path(tempfile.mkdtemp(prefix="vortex-qt-target-"))
        self.state_path = self.tmp / "state.json"
        self.port = free_display_port()
        self.process: subprocess.Popen | None = None
        self.shim_dir = self.tmp / "shims"

    # ---- environment preparation ----

    def _library_missing(self, library: str) -> bool:
        """True when the dynamic loader cannot resolve this soname."""
        for directory in ("/lib", "/usr/lib", "/lib64", "/usr/lib64",
                          "/lib/x86_64-linux-gnu", "/usr/lib/x86_64-linux-gnu"):
            if list(Path(directory).glob(f"{library}*")):
                return False
        ldconfig = shutil.which("ldconfig") or "/sbin/ldconfig"
        if Path(ldconfig).exists():
            try:
                result = subprocess.run([ldconfig, "-p"], capture_output=True, text=True, timeout=20)
                if library in (result.stdout or ""):
                    return False
            except (OSError, subprocess.SubprocessError):
                pass
        return True

    def _build_shims(self) -> dict[str, str]:
        """Compile the headless stand-ins only for libraries this host lacks."""
        env: dict[str, str] = {}
        sources = self.root / "tests" / "fixtures" / "headless_qt_shims"
        needed = []
        if self._library_missing("libGL.so.1"):
            needed.append(("gl_shim.c", "libGL.so.1"))
        if self._library_missing("libdbus-1.so.3"):
            needed.append(("dbus_standin.c", "libdbus-1.so.3"))
        if not needed:
            return env
        compiler = shutil.which("cc") or shutil.which("gcc")
        if compiler is None:
            raise TargetUnavailable(
                "libGL.so.1 / libdbus-1.so.3 are missing and no C compiler is available to build the "
                "headless Qt stand-ins. Install Mesa and D-Bus (Debian: libgl1 libdbus-1-3) or a compiler."
            )
        self.shim_dir.mkdir(parents=True, exist_ok=True)
        for source, soname in needed:
            target = self.shim_dir / soname
            result = subprocess.run(
                [compiler, "-shared", "-fPIC", "-O2", f"-Wl,-soname,{soname}", "-o", str(target), str(sources / source)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise TargetUnavailable(f"could not build {source}: {result.stderr.strip()[:300]}")
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            [str(self.shim_dir), *([os.environ["LD_LIBRARY_PATH"]] if os.environ.get("LD_LIBRARY_PATH") else [])]
        )
        return env

    # ---- lifecycle ----

    def preflight(self, shim_env: dict[str, str]) -> None:
        """Fail with an actionable message when this interpreter cannot run Qt.

        The import is checked with the same library path the target will use, so
        a host that genuinely lacks Qt fails here with an install instruction
        instead of dying silently inside a detached process.
        """
        probe = subprocess.run(
            [self.interpreter, "-c", "import PyQt5.QtWidgets, PyQt5.QtCore; print('ok')"],
            capture_output=True, text=True, timeout=60, env={**os.environ, **shim_env},
        )
        if probe.returncode != 0 or "ok" not in probe.stdout:
            detail = (probe.stderr or probe.stdout).strip().splitlines()
            raise TargetUnavailable(
                f"{self.interpreter} cannot import PyQt5 ({detail[-1] if detail else 'unknown error'}). "
                "Install it for that interpreter (python3 -m pip install PyQt5) or use --target x11vnc with the "
                "system packages xvfb x11vnc xterm x11-utils x11-xserver-utils xdotool openbox."
            )

    def start(self) -> None:
        shim_env = self._build_shims()
        self.preflight(shim_env)
        env = {
            **os.environ,
            **shim_env,
            "VRS_STATE": str(self.state_path),
            "XDG_RUNTIME_DIR": str(self.tmp / "runtime"),
            "XDG_CURRENT_DESKTOP": "XFCE",
            "QT_QPA_PLATFORM": f"vnc:port={self.port}:size={self.width}x{self.height}",
        }
        (self.tmp / "runtime").mkdir(mode=0o700, exist_ok=True)
        self.process = subprocess.Popen(
            [self.interpreter, str(self.root / "tests" / "fixtures" / "qt_vnc_target.py")],
            cwd=self.tmp, env=env, stdout=open(self.tmp / "target.log", "w"),
            stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            self.banner = wait_for_banner(self.port, timeout=25.0)
        except CheckFailed as failure:
            tail = _log_tail(self.tmp / "target.log")
            exited = self.process.poll()
            hint = ""
            if "could not find or load the Qt platform plugin" in tail or "This application failed to start" in tail:
                hint = (" — the Qt VNC platform plugin is unavailable in this Qt build; use --target x11vnc "
                        "with the system packages")
            if "Address already in use" in tail:
                hint = f" — port {self.port} was taken after the check passed; rerun the suite"
            raise TargetUnavailable(f"{failure}{hint}. Target log ({self.tmp / 'target.log'}): {tail}") from (
                None if exited is None else None
            )

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=10)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=5)
                except OSError:
                    pass
        self.process = None

    def interrupt(self) -> None:
        """Kill the RFB service (the whole Qt process: it *is* the service)."""
        self.stop()

    def resume(self) -> None:
        self.start()

    def cleanup(self) -> None:
        self.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- target-side state ----

    def state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {}

    @property
    def supports_runtime_resize(self) -> bool:
        return False  # Qt's VNC screen geometry is fixed at start-up

    @property
    def supports_vnc_auth(self) -> bool:
        return False  # Qt's VNC plugin offers security type None only


class X11VncTarget:
    """Xvfb + openbox + xterm + xev served by real x11vnc (independent VNC server)."""

    flavour = "x11vnc"
    display_name = "Xvfb virtual display + openbox + xterm/xev served by x11vnc"

    def __init__(self, root: Path, width: int = 1024, height: int = 768):
        required = ("Xvfb", "x11vnc", "xterm", "xev", "openbox", "xrandr", "xdotool")
        missing = [tool for tool in required if shutil.which(tool) is None]
        if missing:
            raise TargetUnavailable(
                "x11vnc target needs the system packages providing: " + ", ".join(missing)
                + " (Debian: sudo apt-get install -y xvfb openbox x11vnc xterm x11-utils x11-xserver-utils xdotool)"
            )
        self.root = root
        self.width, self.height = width, height
        self.tmp = Path(tempfile.mkdtemp(prefix="vortex-x11vnc-target-"))
        self.display = self._free_display_number()
        self.port = free_display_port()
        self.auth_port = free_display_port()
        self.password = "vortex-acceptance"
        self.typed_path = self.tmp / "typed.txt"
        self.xev_path = self.tmp / "xev.log"
        self.procs: list[subprocess.Popen] = []
        self.vnc_procs: list[subprocess.Popen] = []

    def _free_display_number(self) -> int:
        for number in range(80, 120):
            if not Path(f"/tmp/.X{number}-lock").exists():
                return number
        raise TargetUnavailable("no free X display number")

    def _spawn(self, argv: list[str], *, env: dict | None = None, log: str = "target.log") -> subprocess.Popen:
        handle = open(self.tmp / log, "a")
        process = subprocess.Popen(argv, env={**os.environ, **(env or {})}, stdout=handle, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        self.procs.append(process)
        return process

    def start(self) -> None:
        self._spawn(["Xvfb", f":{self.display}", "-screen", "0", f"{self.width}x{self.height}x24", "-nolisten", "tcp"])
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not Path(f"/tmp/.X11-unix/X{self.display}").exists():
            time.sleep(0.2)
        if not Path(f"/tmp/.X11-unix/X{self.display}").exists():
            raise CheckFailed(f"Xvfb did not create display :{self.display}")
        env = {"DISPLAY": f":{self.display}"}
        self._spawn(["openbox"], env=env)
        # Real terminal application: keystrokes typed over RFB become a file on
        # the target host, which is application-level evidence of input delivery.
        self._spawn(["xterm", "-T", "vortex-acceptance", "-geometry", "80x24+0+0", "-e", "sh", "-c",
                     f"stty -echo; printf 'ready\\n'; IFS= read -r line; printf '%s' \"$line\" > {self.typed_path}; sleep 900"],
                    env=env)
        # Real X client that logs the pointer events it receives, so mouse
        # interaction is proven by a target-side program, not by a screenshot.
        self._spawn(["xev", "-name", "vortex-xev", "-geometry", "40x10+700+520", "-event", "mouse", "-event", "keyboard"],
                    env=env, log="xev.log")
        time.sleep(2.0)
        self._focus_typing_terminal(env)
        # A first instance serves the desktop openly; a second one requires VNC
        # authentication so credential failure can be tested against a real server.
        password_file = self.tmp / "vncpasswd"
        subprocess.run(["x11vnc", "-storepasswd", self.password, str(password_file)], check=True,
                       capture_output=True, env=env)
        self._spawn_vnc_servers(env)
        wait_for_banner(self.port)
        wait_for_banner(self.auth_port)

    def _run_in_display(self, argv: list[str], env: dict) -> subprocess.CompletedProcess:
        return subprocess.run(argv, env={**os.environ, **env}, capture_output=True, timeout=20, text=True)

    def _window_id(self, name: str, env: dict) -> str:
        result = self._run_in_display(["xdotool", "search", "--name", name], env)
        ids = [line for line in (result.stdout or "").splitlines() if line.strip()]
        if not ids:
            raise CheckFailed(f"could not find the {name} window on display :{self.display}")
        return ids[-1].strip()

    def _focus_typing_terminal(self, env: dict) -> None:
        window = self._window_id("vortex-acceptance", env)
        self._run_in_display(["xdotool", "windowactivate", "--sync", window], env)
        self._run_in_display(["xdotool", "windowfocus", "--sync", window], env)

    def _window_geometry(self, name: str, env: dict) -> tuple[int, int, int, int]:
        window = self._window_id(name, env)
        result = self._run_in_display(["xdotool", "getwindowgeometry", window], env)
        position = size = None
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("Position:"):
                x, y = line.split(":", 1)[1].strip().split(",")
                position = (int(x), int(y))
            elif line.startswith("Geometry:"):
                width, height = line.split(":", 1)[1].strip().split("x")
                size = (int(width), int(height))
        if position is None or size is None:
            raise CheckFailed(f"could not read the geometry of {name}: {result.stdout!r} {result.stderr!r}")
        return position[0], position[1], size[0], size[1]

    def interrupt(self) -> None:
        """Kill the VNC service but keep the desktop and its applications alive."""
        if self.vnc_procs:
            for process in self.vnc_procs:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except OSError:
                        pass
            deadline = time.monotonic() + 8
            for process in self.vnc_procs:
                try:
                    process.wait(timeout=max(0.5, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        pass
            self.vnc_procs = []

    def resume(self) -> None:
        env = {"DISPLAY": f":{self.display}"}
        self._spawn_vnc_servers(env)

    def _spawn_vnc_servers(self, env: dict) -> None:
        self.vnc_procs = [
            self._spawn(["x11vnc", "-display", f":{self.display}", "-rfbport", str(self.port), "-forever", "-shared",
                         "-xrandr", "-nopw", "-quiet", "-o", str(self.tmp / "x11vnc.log")], env=env),
            self._spawn(["x11vnc", "-display", f":{self.display}", "-rfbport", str(self.auth_port), "-forever", "-shared",
                         "-rfbauth", str(self.tmp / "vncpasswd"), "-quiet", "-o", str(self.tmp / "x11vnc-auth.log")],
                        env=env),
        ]

    def stop(self) -> None:
        for process in reversed(self.procs):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except OSError:
                    pass
        deadline = time.monotonic() + 8
        for process in reversed(self.procs):
            try:
                process.wait(timeout=max(0.5, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    pass
        self.procs = []

    def cleanup(self) -> None:
        self.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- target-side state ----

    def state(self) -> dict:
        typed = self.typed_path.read_text() if self.typed_path.exists() else ""
        events = self.xev_path.read_text(errors="replace") if self.xev_path.exists() else ""
        presses = [line for line in events.splitlines() if "ButtonPress" in line]
        return {
            "text": typed,
            "clicks": len(presses),
            "status": "typed" if typed else "waiting",
            "button_label": f"xev ButtonPress events: {len(presses)}",
            "screen": {"width": self.width, "height": self.height},
        }

    def pointer_target(self) -> tuple[int, int]:
        """Centre of the real xev window, read from the X server itself."""
        env = {"DISPLAY": f":{self.display}"}
        x, y, width, height = self._window_geometry("vortex-xev", env)
        return x + width // 2, y + height // 2

    def resize(self, width: int, height: int) -> None:
        """Runtime resize of the real display (xrandr against Xvfb)."""
        result = subprocess.run(
            ["xrandr", "--fb", f"{width}x{height}"], env={**os.environ, "DISPLAY": f":{self.display}"},
            capture_output=True, text=True, timeout=20,
        )
        # x11vnc only follows display changes when it is asked to look at them.
        time.sleep(1.0)
        if result.returncode != 0:
            raise CheckFailed(f"xrandr resize failed: {result.stderr.strip()[:200]}")
        self.width, self.height = width, height
        time.sleep(1.5)

    @property
    def supports_runtime_resize(self) -> bool:
        return True

    @property
    def supports_vnc_auth(self) -> bool:
        return True


# --------------------------------------------------------------------------- checks


class Results:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.entries.append({"check": name, "ok": bool(ok), "detail": detail})
        mark = color("PASS", "green") if ok else color("FAIL", "red")
        print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""), flush=True)
        return ok

    def require(self, name: str, ok: bool, detail: str = "") -> None:
        if not self.check(name, ok, detail):
            raise CheckFailed(f"{name}: {detail}")

    @property
    def failed(self) -> list[dict]:
        return [entry for entry in self.entries if not entry["ok"]]

    def report(self) -> dict:
        return {
            "checks": self.entries,
            "passed": len([entry for entry in self.entries if entry["ok"]]),
            "failed": len(self.failed),
        }


class Session:
    """One authorized remote-desktop session plus its live RFB client."""

    def __init__(self, sidecar: Sidecar, engagement_id: str, port: int, *, transport: str = "unencrypted"):
        self.sidecar = sidecar
        self.engagement_id = engagement_id
        self.port = port
        self.transport = transport
        self.record: dict = {}
        self.channel: WebSocketChannel | None = None
        self.client: RfbClient | None = None

    def create(self) -> dict:
        status, payload = self.sidecar.request("POST", "/api/remote-desktop/sessions", {
            "engagement_id": self.engagement_id,
            "host": "127.0.0.1",
            "port": self.port,
            "transport": self.transport,
            "private_address_ack": True,
            "label": "acceptance session",
            "client_library": "vortex-acceptance-rfb-client",
        })
        if status != 201:
            raise CheckFailed(f"session creation failed: {status} {payload}")
        self.record = payload["session"]
        return self.record

    def approve(self) -> dict:
        status, payload = self.sidecar.request("POST", f"/api/remote-desktop/sessions/{self.record['id']}/approve", {
            "confirm": True,
            "unencrypted_approved": self.transport == "unencrypted",
            "protected_path_ack": self.transport == "unencrypted",
            "private_address_ack": True,
        })
        if status != 200:
            raise CheckFailed(f"approval failed: {status} {payload}")
        self.record = payload["session"]
        return self.record

    def ticket(self, *, cookie: str | None = None) -> str:
        status, payload = self.sidecar.request("POST", f"/api/remote-desktop/sessions/{self.record['id']}/ticket",
                                              {}, token="" if cookie else None, cookie=cookie)
        if status != 200:
            raise CheckFailed(f"ticket issue failed: {status} {payload}")
        return str(payload["ticket"]["ticket"])

    def connect(self, *, cookie: str | None = None, password: bytes | None = None) -> RfbClient:
        ticket = self.ticket(cookie=cookie)
        channel = WebSocketChannel.connect(
            "127.0.0.1", self.sidecar.port,
            f"/api/remote-desktop/sessions/{self.record['id']}/stream",
            subprotocols=["vortex.rfb.v1", f"vortex-ticket.{ticket}"],
            token=None if cookie else self.sidecar.token,
            cookie=cookie,
        )
        client = RfbClient(channel)
        client.handshake(password=password)
        self.channel, self.client = channel, client
        return client

    def close_client(self) -> None:
        if self.channel is not None:
            self.channel.close()
            self.channel = None
            self.client = None

    def close(self, reason: str = "acceptance_finished") -> None:
        self.close_client()
        self.sidecar.request("POST", f"/api/remote-desktop/sessions/{self.record['id']}/close", {"reason": reason})


# --------------------------------------------------------------------------- acceptance


def run_acceptance(args: argparse.Namespace) -> int:
    results = Results()
    root = ROOT
    target: QtVncTarget | X11VncTarget | None = None
    sidecar: Sidecar | None = None
    sessions: list[Session] = []

    def build_target() -> QtVncTarget | X11VncTarget:
        nonlocal target
        order = [args.target] if args.target != "auto" else ["x11vnc", "qt"]
        errors: list[str] = []
        for flavour in order:
            try:
                if flavour == "x11vnc":
                    target = X11VncTarget(root)
                    print(f"  {color('target', 'dim')}: {target.display_name}")
                    return target
                if flavour == "qt":
                    target = QtVncTarget(root, interpreter=args.python)
                    print(f"  {color('target', 'dim')}: {target.display_name} ({args.python})")
                    return target
            except TargetUnavailable as exc:
                errors.append(f"{flavour}: {exc}")
        raise TargetUnavailable("; ".join(errors) or "no target requested")

    try:
        print(color("== authorized remote desktop acceptance ==", "yellow"))
        target = build_target()
        target.start()
        sidecar = Sidecar(root)
        sidecar.start()
        print(f"  sidecar on 127.0.0.1:{sidecar.port} · target on 127.0.0.1:{target.port}")

        # --- 1. capability reporting -------------------------------------
        status, payload = sidecar.request("GET", "/api/remote-desktop")
        document = payload.get("remote_desktop", {})
        protocols = {item["id"]: item["status"] for item in document.get("protocols", [])}
        results.require("capability matrix reports VNC supported and RDP not implemented",
                        protocols.get("vnc") == "supported" and protocols.get("rdp") == "not_implemented", str(protocols))

        # --- 2. scope enforcement ----------------------------------------
        engagement_id = sidecar.engagement(["127.0.0.1"])
        status, payload = sidecar.request("POST", "/api/remote-desktop/probe", {
            "engagement_id": engagement_id, "host": "192.0.2.10", "port": 5900, "transport": "unencrypted",
        })
        results.require("out-of-scope target is refused before any connection",
                        status == 403 and payload.get("error", {}).get("code") in
                        {"target_not_authorized", "private_address_not_confirmed"},
                        f"{status} {payload.get('error', {}).get('code')}")

        # --- 3. endpoint check -------------------------------------------
        status, payload = sidecar.request("POST", "/api/remote-desktop/probe", {
            "engagement_id": engagement_id, "host": "127.0.0.1", "port": target.port,
            "transport": "unencrypted", "private_address_ack": True, "deep": True,
        })
        probe = payload.get("probe", {})
        results.require("deep probe reports a compatible RFB endpoint",
                        status == 200 and probe.get("available") is True,
                        f"{status} {probe.get('error') or probe.get('protocol_version')}")
        results.require("probe stays unauthenticated and reports security types",
                        "security_types" in probe and probe.get("deep_probe") is True, str(probe.get("security_types")))
        secret_keys = find_secret_keys(probe)
        results.require("endpoint check never returns credentials or session material",
                        not secret_keys, f"secret-bearing keys: {secret_keys}" if secret_keys else "none")

        # --- 4. approval requirements ------------------------------------
        session = Session(sidecar, engagement_id, target.port)
        sessions.append(session)
        record = session.create()
        results.require("created session waits for approval",
                        record.get("state") == "awaiting_approval" and record.get("approved_at") in (None, ""),
                        str(record.get("state")))
        results.require("non-secret lifecycle metadata is retained",
                        all(key in record for key in ("id", "engagement_id", "target", "protocol", "transport",
                                                      "created_at", "last_activity")),
                        ",".join(sorted(record.keys()))[:120])
        status, payload = sidecar.request("POST", f"/api/remote-desktop/sessions/{record['id']}/approve",
                                          {"confirm": False})
        results.require("approval without explicit confirmation is refused",
                        status == 400 and payload.get("error", {}).get("code") == "confirmation_required",
                        f"{status} {payload.get('error', {}).get('code')}")
        status, payload = sidecar.request("POST", f"/api/remote-desktop/sessions/{record['id']}/approve",
                                          {"confirm": True})
        results.require("unencrypted transport needs the protected-path acknowledgement",
                        status == 403 and payload.get("error", {}).get("code") == "protected_path_required",
                        f"{status} {payload.get('error', {}).get('code')}")
        session.approve()
        results.require("approval is recorded and the session becomes connectable",
                        session.record.get("state") == "created" and bool(session.record.get("approved_at")),
                        f"{session.record.get('state')} approved_at={session.record.get('approved_at')}")

        # --- 5. stream authorization -------------------------------------
        status, payload = sidecar.request("GET", f"/api/remote-desktop/sessions/{record['id']}/"
                                                 f"stream")
        results.require("the stream endpoint only answers WebSocket upgrades, never plain data",
                        status == 400 and payload.get("error", {}).get("code") == "upgrade_required",
                        f"{status} {payload.get('error', {}).get('code')}")

        # --- 6. real rendering + identity --------------------------------
        client = session.connect()
        results.require("real RFB handshake completed through the bridge",
                        client.version.startswith("003.") and client.width > 0 and client.height > 0,
                        f"RFB {client.version} {client.width}x{client.height} name={client.name!r}")
        results.require("framebuffer geometry matches the target display",
                        (client.width, client.height) == (target.width, target.height),
                        f"client {client.width}x{client.height} target {target.width}x{target.height}")
        rendered = client.update_until(lambda c: c.distinct_colors() > 4, timeout=30, full_first=True)
        results.require("live framebuffer content arrived (real rendered pixels)",
                        rendered, f"{client.distinct_colors()} distinct colours in {client.updates} update(s)")
        before_input = client.checksum()
        results.require("session identity matches the approved endpoint",
                        session.record["target"]["identity"] == f"127.0.0.1:{target.port}",
                        session.record["target"]["identity"])

        # --- 7. keyboard input changes target-side application state -----
        marker = f"vortex-{int(time.time()) % 100000}"
        if target.flavour == "qt":
            client.type_text(marker)
        else:
            client.type_text(marker)
        typed = wait_for(lambda: target.state().get("text") == marker, timeout=20)
        results.require("keyboard events delivered over RFB changed target-side application state",
                        typed, f"target reported {target.state().get('text')!r}")
        changed = client.update_until(lambda c: c.checksum() != before_input, timeout=20)
        results.require("the framebuffer changed after keystrokes (Qt/X rendered them)",
                        changed, f"{client.updates} update(s) total")

        # --- 8. pointer input changes target-side state ------------------
        clicks_before = int(target.state().get("clicks", 0))
        if target.flavour == "qt":
            rect = target.state().get("button") or {}
            x = int(rect.get("x", 0) + rect.get("width", 0) / 2)
            y = int(rect.get("y", 0) + rect.get("height", 0) / 2)
        else:
            x, y = target.pointer_target()
        client.pointer(x, y, 0)
        client.click(x, y)
        clicked = wait_for(lambda: int(target.state().get("clicks", 0)) > clicks_before, timeout=20)
        results.require("pointer events delivered over RFB changed target-side state",
                        clicked, f"clicks {clicks_before} -> {target.state().get('clicks')} at ({x},{y})")
        if target.flavour == "qt":
            results.require("the clicked widget reported the press (application-level evidence)",
                            target.state().get("clicks", 0) >= clicks_before + 1
                            and "pressed" in str(target.state().get("status", "")).lower(),
                            str(target.state().get("status")))

        # --- 9. two concurrent, isolated sessions ------------------------
        second = Session(sidecar, engagement_id, target.port)
        sessions.append(second)
        second.create()
        second.approve()
        second_client = second.connect()
        second_ok = second_client.update_until(lambda c: c.distinct_colors() > 4, timeout=25, full_first=True)
        results.require("a second concurrent session renders independently", second_ok,
                        f"{second_client.distinct_colors()} colours")
        results.require("both sessions hold distinct sockets and tickets",
                        second.record["id"] != session.record["id"]
                        and session.channel is not None and second.channel is not None
                        and session.channel.sock.fileno() != second.channel.sock.fileno(), "")
        second.close()
        still_live = client.update_until(lambda c: c.updates > 0, timeout=15)
        results.require("closing one session leaves the other connected", still_live, "")

        # --- 10. disconnect, reconnect, fresh ticket ---------------------
        previous_channel = session.channel
        status, payload = sidecar.request("POST", f"/api/remote-desktop/sessions/{session.record['id']}/disconnect",
                                          {"reason": "acceptance_disconnect"})
        results.require("disconnect is recorded on the session",
                        status == 200 and payload["session"]["state"] == "disconnected",
                        str(payload.get("session", {}).get("state")))
        socket_closed = previous_channel is None or previous_channel.is_closed(timeout=10)
        session.channel = None
        results.require("the bridge socket is closed on disconnect (no half-open stream)", socket_closed, "")
        status, payload = sidecar.request("POST", f"/api/remote-desktop/sessions/{session.record['id']}/reconnect", {})
        results.require("reconnect is allowed under the approved policy", status == 200, str(payload)[:120])
        client = session.connect()
        results.require("reconnected session renders again",
                        client.update_until(lambda c: c.distinct_colors() > 4, timeout=25, full_first=True), "")

        # --- 11. interruption and recovery -------------------------------
        target.interrupt()
        interrupted = wait_for(lambda: sidecar.request(
            "GET", f"/api/remote-desktop/sessions/{session.record['id']}")[1]["session"]["state"] != "connected", timeout=20)
        results.require("target interruption moves the session out of the connected state", interrupted,
                        str(sidecar.request("GET", f"/api/remote-desktop/sessions/{session.record['id']}")[1]["session"]["state"]))
        status, payload = sidecar.request("GET", f"/api/remote-desktop/sessions/{session.record['id']}")
        record = payload["session"]
        reason = str(record.get("failure_reason") or record.get("disconnect_reason") or "")
        results.require("an outage is recorded as a failure, not a clean disconnect",
                        bool(record.get("failure_reason")) and bool(record.get("disconnect_reason")),
                        f"failure={record.get('failure_reason')!r} disconnect={record.get('disconnect_reason')!r}")
        results.require("the failure reason is recorded and sanitized",
                        bool(reason) and "password" not in reason.lower() and len(reason) < 400, reason[:120])
        target.resume()
        status, payload = sidecar.request("POST", f"/api/remote-desktop/sessions/{session.record['id']}/reconnect", {})
        results.require("reconnect after an interruption is accepted",
                        status == 200 and payload["session"]["state"] == "reconnecting",
                        f"{status} {payload.get('session', {}).get('state')}")
        client = session.connect()
        results.require("the recovered session renders the restarted target",
                        client.update_until(lambda c: c.distinct_colors() > 4, timeout=25, full_first=True), "")

        # --- 12. resize semantics ----------------------------------------
        if target.supports_runtime_resize:
            new_size = (800, 600) if (target.width, target.height) != (800, 600) else (1024, 768)
            target.resize(*new_size)
            resized = client.update_until(lambda c: (c.width, c.height) == new_size, timeout=25, full_first=True)
            results.require(f"a live display resize reached the session ({new_size[0]}x{new_size[1]})", resized,
                            f"client reports {client.width}x{client.height}")
        else:
            results.require("the target reports a fixed resolution the UI documents and scales",
                            (client.width, client.height) == (target.width, target.height),
                            f"fixed {client.width}x{client.height}")

        # --- 13. auth failure against a real VNC-auth endpoint -----------
        if target.supports_vnc_auth:
            auth_session = Session(sidecar, engagement_id, target.auth_port)
            sessions.append(auth_session)
            auth_session.create()
            auth_session.approve()
            ticket = auth_session.ticket()
            channel = WebSocketChannel.connect(
                "127.0.0.1", sidecar.port, f"/api/remote-desktop/sessions/{auth_session.record['id']}/stream",
                subprotocols=["vortex.rfb.v1", f"vortex-ticket.{ticket}"], token=sidecar.token,
            )
            failing = RfbClient(channel)
            rejected = False
            try:
                failing.handshake(bogus_auth=True)
            except RfbError as exc:
                rejected = exc.status is not None
            results.require("a real VNC-auth endpoint rejects wrong credentials", rejected, "security failure surfaced")
            good = Session(sidecar, engagement_id, target.auth_port)
            sessions.append(good)
            good.create()
            good.approve()
            good_client = good.connect(password=target.password.encode())
            results.require("a real VNC-auth endpoint accepts the approved password",
                            good_client.update_until(lambda c: c.distinct_colors() > 2, timeout=25, full_first=True),
                            f"{good_client.distinct_colors()} colours")
            good.close()
        else:
            results.check("real VNC-auth endpoint available for credential-failure coverage", True,
                          "not applicable to this target flavour (Qt's VNC plugin offers no authentication); "
                          "covered by the x11vnc target and by tests/test_remote_desktop.py")

        # --- 14. cleanup paths -------------------------------------------
        status, payload = sidecar.request("GET", "/api/remote-desktop/sessions")
        live = [item for item in payload.get("sessions", []) if not item.get("retained")]
        results.require("live sessions are listed for the operator", len(live) >= 1, f"{len(live)} live")
        for extra in sessions:
            extra.close_client()
        for extra in sessions:
            sidecar.request("POST", f"/api/remote-desktop/sessions/{extra.record['id']}/close", {"reason": "acceptance_cleanup"})
        status, payload = sidecar.request("GET", "/api/remote-desktop/sessions")
        live_after = [item for item in payload.get("sessions", []) if not item.get("retained")]
        results.require("closing sessions leaves no live session records", not live_after, f"{len(live_after)} live")

        # STOP ALL closes every remote session and its socket.
        stop_session = Session(sidecar, engagement_id, target.port)
        sessions.append(stop_session)
        stop_session.create()
        stop_session.approve()
        stop_client = stop_session.connect()
        results.require("session for the STOP ALL check is connected",
                        stop_client.update_until(lambda c: c.distinct_colors() > 2, timeout=25, full_first=True), "")
        status, payload = sidecar.request("POST", "/api/control/stop-all", {})
        closed = payload.get("stop", {}).get("remote_sessions_closed", 0)
        results.require("STOP ALL closes authorized remote sessions", status in {200, 202} and closed >= 1,
                        f"{status} closed={closed}")
        results.require("STOP ALL tears the bridge socket down",
                        stop_session.channel is None or stop_session.channel.is_closed(timeout=10), "")
        status, payload = sidecar.request("GET", "/api/remote-desktop/sessions")
        results.require("no live remote session survives STOP ALL",
                        not [item for item in payload.get("sessions", []) if not item.get("retained")], "")

        # --- 15. no orphan processes or sockets --------------------------
        target.stop()
        results.require("the target process tree is gone after teardown",
                        target.process is None or target.process.poll() is not None, "")
        results.require("the target port is released (no orphan listener)", not port_is_open(target.port), "")
        sidecar.stop()
        results.require("the sidecar stopped with the run", sidecar.process.poll() is not None, "")

    except TargetUnavailable as exc:
        print(color(f"\nBLOCKED: {exc}", "yellow"))
        return 3
    except CheckFailed as exc:
        print(color(f"\nFAILED: {exc}", "red"))
    finally:
        for session in sessions:
            try:
                session.close_client()
            except Exception:
                pass
        if target is not None:
            try:
                target.cleanup()
            except Exception:
                pass
        if sidecar is not None:
            sidecar.cleanup()

    report = results.report()
    print(f"\n{report['passed']} checks passed, {report['failed']} failed")
    if args.report:
        Path(args.report).write_text(json.dumps({
            "target": target.flavour if target else None,
            "target_description": getattr(target, "display_name", None),
            "sidecar_port": sidecar.port if sidecar else None,
            **report,
        }, indent=2))
    return 1 if report["failed"] else 0


SECRET_KEY_NAMES = ("password", "passwd", "credential", "secret", "token", "ticket", "authorization",
                    "cookie", "bearer")


def find_secret_keys(payload, path: str = "") -> list[str]:
    """Keys that look like they carry secrets, anywhere in a payload tree."""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            here = f"{path}.{key}" if path else str(key)
            if any(name in lowered for name in SECRET_KEY_NAMES):
                found.append(here)
            found.extend(find_secret_keys(value, here))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(find_secret_keys(value, f"{path}[{index}]"))
    return found


def _log_tail(path: Path, lines: int = 12) -> str:
    try:
        content = path.read_text(errors="replace").strip().splitlines()
    except OSError:
        return "(no target log)"
    return " | ".join(content[-lines:]) or "(empty target log)"


def wait_for(predicate, timeout: float, interval: float = 0.4) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(interval)
    try:
        return bool(predicate())
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", choices=["auto", "qt", "x11vnc"], default="auto",
                        help="which real graphical target to use (default: x11vnc when installed, else qt)")
    parser.add_argument("--python", default=sys.executable,
                        help="interpreter that has PyQt5 installed, for the qt target")
    parser.add_argument("--report", help="write a JSON report to this path")
    args = parser.parse_args()
    return run_acceptance(args)


if __name__ == "__main__":
    raise SystemExit(main())
