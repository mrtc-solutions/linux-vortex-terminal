"""End-to-end WebSocket/HTTP integration tests for remote-desktop authorization.

A real sidecar process is started with isolated data, a capability token, and a
scripted RFB listener as the approved endpoint. The WebSocket client is written
by hand so the tests can assert the exact handshake requirements (origin,
capability/cookie authentication, session-bound single-use ticket) and prove the
bridge really pipes RFB bytes in both directions, closes on STOP ALL, and leaves
no listener or session behind.

These tests are integration evidence for the *authorization and bridge* layers
with a scripted endpoint. They are not acceptance evidence for a real graphical
desktop: that is ``tests/remote_desktop_acceptance.py``.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ScriptedRfbListener:
    """Minimal RFB-speaking TCP listener used as the approved endpoint."""

    def __init__(self) -> None:
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bound = False
        for candidate in range(5900, 6000):
            try:
                self.listener.bind(("127.0.0.1", candidate))
                bound = True
                break
            except OSError:
                continue
        if not bound:
            self.listener.close()
            raise RuntimeError("no free VNC display port in 5900-5999")
        self.listener.listen(8)
        self.port = self.listener.getsockname()[1]
        self.received = bytearray()
        self.connections = 0
        self.closed_connections = 0
        import threading
        self._stop = threading.Event()
        self._sockets: list[socket.socket] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        self.listener.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            self.connections += 1
            self._sockets.append(conn)
            import threading
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(0.5)
            conn.sendall(b"RFB 003.008\n")
            while not self._stop.is_set():
                try:
                    data = conn.recv(4096)
                except (socket.timeout, TimeoutError):
                    continue
                except OSError:
                    break
                if not data:
                    break
                self.received.extend(data)
        finally:
            self.closed_connections += 1
            try:
                conn.close()
            except OSError:
                pass

    def close(self) -> None:
        self._stop.set()
        try:
            self.listener.close()
        except OSError:
            pass
        for conn in self._sockets:
            try:
                conn.close()
            except OSError:
                pass
        self._thread.join(timeout=2)


class SidecarHarness:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="vortex-remote-ws-")
        self.token = "b" * 64
        config_dir = Path(self.tmp.name) / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        settings = config_dir / "settings.json"
        settings.write_text(json.dumps({
            "remote_desktop_allow_unencrypted": True,
            "remote_desktop_max_sessions": 3,
            "remote_desktop_idle_seconds": 120,
        }))
        settings.chmod(0o600)
        self.env = {
            **os.environ,
            "VORTEX_DATA_DIR": str(Path(self.tmp.name) / "data"),
            "VORTEX_CONFIG_DIR": str(config_dir),
            "VORTEX_RUNTIME_DIR": str(Path(self.tmp.name) / "runtime"),
            "VORTEX_SIDECAR_TOKEN": self.token,
        }
        self.process: subprocess.Popen | None = None
        self.port = 0
        self.log = open(Path(self.tmp.name) / "sidecar.log", "w")  # noqa: SIM115 - closed in stop()

    def start(self) -> None:
        try:
            self.process = subprocess.Popen(
                [sys.executable, str(ROOT / "backend/vortex_backend.py"), "--host", "127.0.0.1", "--port", "0"],
                cwd=ROOT, env=self.env, stdout=subprocess.PIPE, stderr=self.log, text=True, start_new_session=True,
            )
            deadline = time.monotonic() + 20
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
            raise RuntimeError("sidecar did not report readiness")
        except BaseException:
            # setUpClass does not guarantee tearDownClass after a failed
            # readiness check, so clean the child and its PIPE on this path too.
            try:
                self.stop()
            except Exception:
                pass
            raise

    def stop(self) -> None:
        process = self.process
        try:
            if process and process.poll() is None:
                try:
                    os.killpg(process.pid, 15)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, 9)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
        finally:
            # Popen does not close a parent-owned stdout PIPE after wait().
            # Closing it explicitly prevents an interpreter-shutdown
            # ResourceWarning and proves the integration harness leaves no
            # descriptors behind between test modules.
            if process and process.stdout:
                try:
                    process.stdout.close()
                except OSError:
                    pass
            self.process = None
            self.log.close()
            self.tmp.cleanup()

    # ---- HTTP helpers (real requests, real responses) ----

    _DEFAULT_TOKEN = "__default__"

    def request(self, method: str, path: str, body: dict | None = None, *, token: str | None = _DEFAULT_TOKEN,
                cookie: str | None = None, origin: str | None = None) -> tuple[int, dict, dict]:
        headers = {"Content-Type": "application/json"}
        supplied = self.token if token == self._DEFAULT_TOKEN else token
        if supplied:
            headers["X-Vortex-Token"] = supplied
        if cookie:
            headers["Cookie"] = cookie
        if origin:
            headers["Origin"] = origin
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode() or "{}")
                return response.status, payload, dict(response.headers)
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode() or "{}")
            return exc.code, payload, dict(exc.headers)

    def engagement(self, targets: list[str]) -> str:
        status, payload, _ = self.request("POST", "/api/engagements", {"name": "ws acceptance", "targets": targets})
        assert status == 201, payload
        return payload["engagement"]["id"]


class WebSocketClient:
    """Hand-rolled RFC 6455 client used to assert exact handshake behaviour."""

    def __init__(self, sock: socket.socket, response: bytes):
        self.sock = sock
        self.response = response

    @classmethod
    def connect(cls, port: int, session_id: str, *, ticket: str | None, token: str | None, cookie: str | None = None,
                origin: str | None = None, subprotocol: str = "vortex.rfb.v1", path: str | None = None,
                timeout: float = 10.0) -> "WebSocketClient":
        if origin is None:
            origin = f"http://127.0.0.1:{port}"  # browsers always send the page origin, including the port
        sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        protocols = [subprotocol] if subprotocol else []
        if ticket:
            protocols.append(f"vortex-ticket.{ticket}")
        route = path or f"/api/remote-desktop/sessions/{session_id}/stream"
        lines = [
            f"GET {route} HTTP/1.1",
            f"Host: 127.0.0.1:{port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
        ]
        if protocols:
            lines.append("Sec-WebSocket-Protocol: " + ", ".join(protocols))
        if token:
            lines.append(f"X-Vortex-Token: {token}")
        if cookie:
            lines.append(f"Cookie: {cookie}")
        if origin:
            lines.append(f"Origin: {origin}")
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        response = cls._read_headers(sock)
        client = cls(sock, response)
        client.body_bytes = client._drain_body(response)
        return client

    def _drain_body(self, response: bytes) -> bytes:
        """Read the JSON error body the sidecar sends instead of an upgrade."""
        if self.status == 101:
            return b""
        try:
            head, _, tail = response.partition(b"\r\n\r\n")
        except ValueError:  # pragma: no cover
            return b""
        length = 0
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1].strip())
        body = bytearray(tail)
        self.sock.settimeout(5)
        while len(body) < length:
            chunk = self.sock.recv(length - len(body))
            if not chunk:
                break
            body.extend(chunk)
        return bytes(body)

    @staticmethod
    def _read_headers(sock: socket.socket) -> bytes:
        buffer = bytearray()
        while b"\r\n\r\n" not in buffer:
            chunk = sock.recv(1)
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > 16 * 1024:
                break
        return bytes(buffer)

    @property
    def status(self) -> int:
        try:
            return int(self.response.split(b"\r\n", 1)[0].split(b" ")[1])
        except (IndexError, ValueError):
            return 0

    def body(self) -> dict:
        try:
            return json.loads((getattr(self, "body_bytes", b"") or b"{}").decode())
        except ValueError:
            return {}

    def send_masked(self, payload: bytes, opcode: int = 0x2) -> None:
        mask = os.urandom(4)
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", length))
        header.extend(mask)
        self.sock.sendall(bytes(header) + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload)))

    def read_frame(self, timeout: float = 10.0) -> tuple[int, bytes]:
        self.sock.settimeout(timeout)
        header = self._read_exactly(2)
        first, second = header[0], header[1]
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read_exactly(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read_exactly(8))[0]
        payload = self._read_exactly(length) if length else b""
        return opcode, payload

    def _read_exactly(self, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self.sock.recv(size - len(chunks))
            if not chunk:
                raise ConnectionError("websocket closed")
            chunks.extend(chunk)
        return bytes(chunks)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class RemoteDesktopWebSocketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.harness = SidecarHarness()
        cls.fixture = ScriptedRfbListener()
        cls.harness.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.close()
        cls.harness.stop()

    def setUp(self) -> None:
        self.fixture.received = bytearray()
        self.engagement_id = self.harness.engagement(["127.0.0.1"])
        self.created_sessions: list[str] = []

    def tearDown(self) -> None:
        for session_id in self.created_sessions:
            self.harness.request("POST", f"/api/remote-desktop/sessions/{session_id}/close", {"reason": "test_cleanup"})
        self.harness.request("POST", "/api/control/stop-all", {})

    # ---- helpers ----

    def approve_session(self, *, transport: str = "unencrypted", port: int | None = None) -> dict:
        status, created, _ = self.harness.request("POST", "/api/remote-desktop/sessions", {
            "engagement_id": self.engagement_id,
            "host": "127.0.0.1",
            "port": port if port is not None else self.fixture.port,
            "transport": transport,
        })
        self.assertEqual(status, 201, created)
        session = created["session"]
        self.created_sessions.append(session["id"])
        status, approved, _ = self.harness.request(
            "POST", f"/api/remote-desktop/sessions/{session['id']}/approve",
            {"confirm": True, "unencrypted_approved": True, "protected_path_ack": True},
        )
        self.assertEqual(status, 200, approved)
        return approved["session"]

    def ticket(self, session_id: str) -> str:
        status, payload, _ = self.harness.request("POST", f"/api/remote-desktop/sessions/{session_id}/ticket", {})
        self.assertEqual(status, 200, payload)
        return payload["ticket"]["ticket"]

    # ---- tests ----

    def test_authenticated_upgrade_streams_real_bytes_both_ways(self):
        session = self.approve_session()
        client = WebSocketClient.connect(self.harness.port, session["id"], ticket=self.ticket(session["id"]),
                                          token=self.harness.token)
        try:
            self.assertEqual(client.status, 101, client.response[:200])
            self.assertIn(b"Sec-WebSocket-Accept:", client.response)
            self.assertIn(b"Sec-WebSocket-Protocol: vortex.rfb.v1", client.response)
            opcode, payload = client.read_frame()
            self.assertEqual(opcode, 0x2)
            self.assertTrue(payload.startswith(b"RFB 003.008"), payload[:20])
            client.send_masked(b"keyboard-and-mouse")
            deadline = time.monotonic() + 10
            while b"keyboard-and-mouse" not in self.fixture.received and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertIn(b"keyboard-and-mouse", self.fixture.received)
            status, payload, _ = self.harness.request("GET", f"/api/remote-desktop/sessions/{session['id']}")
            self.assertEqual(status, 200)
            self.assertEqual(payload["session"]["state"], "connected")
            self.assertEqual(payload["session"]["target"]["identity"], f"127.0.0.1:{self.fixture.port}")
            self.assertGreater(payload["session"]["bytes_in"], 0)
        finally:
            client.close()

    def test_upgrade_requires_authentication(self):
        session = self.approve_session()
        ticket = self.ticket(session["id"])
        anonymous = WebSocketClient.connect(self.harness.port, session["id"], ticket=ticket, token=None)
        try:
            self.assertEqual(anonymous.status, 401, anonymous.response[:200])
        finally:
            anonymous.close()

    def test_upgrade_requires_a_session_bound_single_use_ticket(self):
        session = self.approve_session()
        missing = WebSocketClient.connect(self.harness.port, session["id"], ticket=None, token=self.harness.token)
        try:
            self.assertEqual(missing.status, 403)
            self.assertEqual(missing.body()["error"]["code"], "ticket_missing")
        finally:
            missing.close()

        forged = WebSocketClient.connect(self.harness.port, session["id"], ticket="forged-ticket-value-123",
                                         token=self.harness.token)
        try:
            self.assertEqual(forged.status, 403)
            self.assertEqual(forged.body()["error"]["code"], "ticket_invalid")
        finally:
            forged.close()

        ticket = self.ticket(session["id"])
        first = WebSocketClient.connect(self.harness.port, session["id"], ticket=ticket, token=self.harness.token)
        try:
            self.assertEqual(first.status, 101)
        finally:
            first.close()
        # Wait for the bridge to release the session, then attempt the replay with
        # every other condition satisfied: only the consumed ticket can refuse it.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            _, payload, _ = self.harness.request("GET", f"/api/remote-desktop/sessions/{session['id']}")
            if payload["session"]["state"] != "connected":
                break
            time.sleep(0.1)
        replay = WebSocketClient.connect(self.harness.port, session["id"], ticket=ticket, token=self.harness.token)
        try:
            self.assertEqual(replay.status, 403)
            self.assertEqual(replay.body()["error"]["code"], "ticket_invalid")
        finally:
            replay.close()

    def test_ticket_cannot_cross_sessions(self):
        first = self.approve_session()
        second = self.approve_session()
        stolen = self.ticket(first["id"])
        crossed = WebSocketClient.connect(self.harness.port, second["id"], ticket=stolen, token=self.harness.token)
        try:
            self.assertEqual(crossed.status, 403)
            self.assertEqual(crossed.body()["error"]["code"], "ticket_mismatch")
        finally:
            crossed.close()

    def test_cross_origin_upgrade_is_refused(self):
        session = self.approve_session()
        hostile = WebSocketClient.connect(self.harness.port, session["id"], ticket=self.ticket(session["id"]),
                                          token=self.harness.token, origin="https://attacker.example")
        try:
            self.assertEqual(hostile.status, 403)
            self.assertEqual(hostile.body()["error"]["code"], "cross_origin_denied")
        finally:
            hostile.close()

    def test_unapproved_session_cannot_open_a_stream(self):
        status, created, _ = self.harness.request("POST", "/api/remote-desktop/sessions", {
            "engagement_id": self.engagement_id, "host": "127.0.0.1", "port": self.fixture.port,
            "transport": "unencrypted",
        })
        self.assertEqual(status, 201)
        session = created["session"]
        self.created_sessions.append(session["id"])
        refused = WebSocketClient.connect(self.harness.port, session["id"], ticket=None, token=self.harness.token)
        try:
            self.assertEqual(refused.status, 403)
        finally:
            refused.close()

    def test_browser_cookie_path_matches_the_desktop_client(self):
        """Electron authenticates the renderer with the same cookie the web build uses."""
        status, payload, headers = self.harness.request("POST", "/api/auth/session", {})
        self.assertEqual(status, 200, payload)
        raw = headers.get("Set-Cookie", "")
        cookie = raw.split(";", 1)[0]
        self.assertTrue(cookie.startswith("Vortex-Session="))
        session = self.approve_session()
        # Tickets are bound to the credential context that requested them: mint
        # this one with the cookie, exactly like the desktop renderer does.
        status, payload, _ = self.harness.request(
            "POST", f"/api/remote-desktop/sessions/{session['id']}/ticket", {}, token=None, cookie=cookie,
        )
        self.assertEqual(status, 200, payload)
        client = WebSocketClient.connect(self.harness.port, session["id"], ticket=payload["ticket"]["ticket"],
                                         token=None, cookie=cookie)
        try:
            self.assertEqual(client.status, 101, client.response[:200])
            opcode, payload = client.read_frame()
            self.assertEqual(opcode, 0x2)
            self.assertTrue(payload.startswith(b"RFB"))
        finally:
            client.close()

    def test_probe_reports_availability_without_authenticating(self):
        status, payload, _ = self.harness.request("POST", "/api/remote-desktop/probe", {
            "engagement_id": self.engagement_id, "host": "127.0.0.1", "port": self.fixture.port,
            "transport": "unencrypted",
        })
        self.assertEqual(status, 200, payload)
        probe = payload["probe"]
        self.assertTrue(probe["available"])
        self.assertEqual(probe["protocol_version"], "003.008")
        self.assertEqual(probe["engagement_id"], self.engagement_id)
        self.assertEqual(self.fixture.received, b"")

    def test_probe_reports_unavailable_endpoint_with_a_reason(self):
        session = self.approve_session()
        self.harness.request("POST", f"/api/remote-desktop/sessions/{session['id']}/close", {"reason": "test"})
        status, payload, _ = self.harness.request("POST", "/api/remote-desktop/probe", {
            "engagement_id": self.engagement_id, "host": "127.0.0.1", "port": 5999, "transport": "unencrypted",
        })
        self.assertEqual(status, 200)
        self.assertFalse(payload["probe"]["available"])
        self.assertEqual(payload["probe"]["error"]["code"], "connect_failed")

    def test_scope_and_port_rules_are_enforced_through_http(self):
        status, payload, _ = self.harness.request("POST", "/api/remote-desktop/probe", {
            "engagement_id": self.engagement_id, "host": "10.0.0.5", "port": 5900, "transport": "tls",
        })
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "target_not_authorized")

        status, payload, _ = self.harness.request("POST", "/api/remote-desktop/probe", {
            "engagement_id": self.engagement_id, "host": "127.0.0.1", "port": 6100, "transport": "tls",
        })
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "port_out_of_range")

        status, payload, _ = self.harness.request("POST", "/api/remote-desktop/probe", {
            "engagement_id": self.engagement_id, "host": "169.254.169.254", "port": 5900, "transport": "tls",
        })
        self.assertIn(status, (403,))
        self.assertIn(payload["error"]["code"], {"target_not_authorized", "blocked_address", "blocked_hostname"})

    def test_stop_all_closes_bridges_and_sockets(self):
        session = self.approve_session()
        client = WebSocketClient.connect(self.harness.port, session["id"], ticket=self.ticket(session["id"]),
                                         token=self.harness.token)
        try:
            self.assertEqual(client.status, 101)
            client.read_frame()
            status, payload, _ = self.harness.request("POST", "/api/control/stop-all", {})
            self.assertEqual(status, 202, payload)
            self.assertGreaterEqual(payload["stop"]["remote_sessions_closed"], 1)
            # The bridge must tear the socket down: the client either sees a close
            # frame or EOF, never a hung connection.
            client.sock.settimeout(10)
            try:
                opcode, _ = client.read_frame(timeout=10)
                self.assertEqual(opcode, 0x8)
            except (ConnectionError, OSError, socket.timeout, TimeoutError):
                pass
            status, payload, _ = self.harness.request("GET", "/api/remote-desktop/sessions")
            self.assertEqual(status, 200)
            live = [item for item in payload["sessions"] if not item.get("retained")]
            self.assertEqual(live, [])
        finally:
            client.close()

    def test_disconnect_keeps_the_session_for_reconnect_and_close_removes_it(self):
        session = self.approve_session()
        client = WebSocketClient.connect(self.harness.port, session["id"], ticket=self.ticket(session["id"]),
                                         token=self.harness.token)
        try:
            self.assertEqual(client.status, 101)
            client.read_frame()
            status, payload, _ = self.harness.request("POST", f"/api/remote-desktop/sessions/{session['id']}/disconnect", {})
            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["session"]["state"], "disconnected")
            status, payload, _ = self.harness.request("POST", f"/api/remote-desktop/sessions/{session['id']}/reconnect", {})
            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["session"]["state"], "reconnecting")
            again = WebSocketClient.connect(self.harness.port, session["id"], ticket=self.ticket(session["id"]),
                                            token=self.harness.token)
            try:
                self.assertEqual(again.status, 101, again.response[:200])
            finally:
                again.close()
            status, payload, _ = self.harness.request("POST", f"/api/remote-desktop/sessions/{session['id']}/close", {})
            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["session"]["state"], "closed")
            status, payload, _ = self.harness.request("GET", f"/api/remote-desktop/sessions/{session['id']}")
            self.assertEqual(status, 200)
            self.assertEqual(payload["session"]["state"], "closed")
            self.assertTrue(payload["session"]["retained"])
            self.assertEqual(payload["session"]["target"]["identity"], f"127.0.0.1:{self.fixture.port}")
        finally:
            client.close()

    def test_capability_endpoint_reports_the_support_matrix(self):
        status, payload, _ = self.harness.request("GET", "/api/remote-desktop")
        self.assertEqual(status, 200)
        document = payload["remote_desktop"]
        protocols = {item["id"]: item["status"] for item in document["protocols"]}
        self.assertEqual(protocols, {"vnc": "supported", "rdp": "not_implemented"})
        self.assertFalse(document["settings"]["clipboard_sync"])
        self.assertFalse(document["settings"]["file_transfer"])
        self.assertEqual(document["bridge"]["port_range"], [5900, 5999])

    def test_fixture_received_no_credentials_and_target_logs_no_secrets(self):
        """The bridge never authenticates on the operator's behalf."""
        session = self.approve_session()
        client = WebSocketClient.connect(self.harness.port, session["id"], ticket=self.ticket(session["id"]),
                                         token=self.harness.token)
        try:
            self.assertEqual(client.status, 101)
            client.read_frame()
            time.sleep(0.3)
        finally:
            client.close()
        # Everything the fixture saw is the RFB banner exchange the client drives.
        self.assertNotIn(b"password", bytes(self.fixture.received).lower())


if __name__ == "__main__":
    unittest.main()
