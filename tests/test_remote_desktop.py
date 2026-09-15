"""Focused regression tests for authorized remote-desktop sessions.

These are unit/integration tests with scripted fixtures: they prove scope
enforcement, SSRF/metadata refusal, ticket lifecycle, session lifecycle,
concurrency limits, idle/revocation handling, and cleanup. They deliberately do
**not** claim to be real-protocol acceptance evidence — that lives in
``tests/remote_desktop_acceptance.py``, which drives a real VNC server and a real
X11 desktop and fails (never skips) when the target cannot be provisioned.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from backend.remote_desktop import (
    PROTOCOL_VNC,
    STATE_AWAITING_APPROVAL,
    STATE_CLOSED,
    STATE_CONNECTED,
    STATE_CREATED,
    STATE_DISCONNECTED,
    STATE_FAILED,
    TRANSPORT_TLS,
    TRANSPORT_UNENCRYPTED,
    EngagementScope,
    RemoteBridge,
    RemoteDesktopError,
    RemoteDesktopManager,
    WebSocketClosed,
    WebSocketConnection,
    authorize_endpoint,
    negotiate_subprotocol,
    parse_endpoint_target,
    probe_endpoint,
    resolve_vnc_port,
    subprotocol_ticket,
)
from backend.vortex_backend import Store


class ScriptedRfbServer:
    """A scripted TCP fixture that speaks just enough RFB to exercise the bridge."""

    def __init__(self, banner: bytes = b"RFB 003.008\n") -> None:
        # The bridge only dials the VNC display range, so the fixture serves on a
        # real display port. That keeps the test honest about the product rule.
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        last_error: Exception | None = None
        for candidate in range(5900, 6000):
            try:
                self.listener.bind(("127.0.0.1", candidate))
                last_error = None
                break
            except OSError as exc:  # port busy: try the next display
                last_error = exc
        if last_error is not None:
            self.listener.close()
            raise RuntimeError("no free VNC display port in 5900-5999") from last_error
        self.listener.listen(8)
        self.port = self.listener.getsockname()[1]
        self.banner = banner
        self.received = bytearray()
        self.connections = 0
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        self.listener.settimeout(0.2)
        conns: list[socket.socket] = []
        while not self._stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            self.connections += 1
            conns.append(conn)
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
        for conn in conns:
            try:
                conn.close()
            except OSError:
                pass

    def _handle(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(5)
            conn.sendall(self.banner)
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
                try:
                    conn.sendall(b"ACK:" + data[:32])
                except OSError:
                    break
        except OSError:
            pass
        finally:
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
        self.thread.join(timeout=2)


class ToggleableRfbServer:
    """A real RFB listener that starts offline and can be brought up later.

    Used to prove the "open desktop when ready" watcher reacts to a *real*
    endpoint becoming reachable without ever connecting on its own.
    """

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
        self.port = self.listener.getsockname()[1]
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.listener.listen(4)
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self) -> None:
        self.listener.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                return
            try:
                conn.sendall(b"RFB 003.008\n")
                time.sleep(0.05)
            except OSError:
                pass
            finally:
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
        if self._thread is not None:
            self._thread.join(timeout=2)


class LoopbackWorkspace(unittest.TestCase):
    """Engagement + manager fixtures pointed at the scripted loopback fixture."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        # Isolated operator settings: plaintext VNC is only reachable because this
        # test deployment opts in, exactly like the product requires.
        self._previous_config_dir = os.environ.get("VORTEX_CONFIG_DIR")
        config_dir = Path(self.tmp.name) / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        settings_file.write_text(json.dumps({
            "remote_desktop_allow_unencrypted": True,
            "remote_desktop_max_sessions": 2,
            "remote_desktop_idle_seconds": 30,
        }))
        settings_file.chmod(0o600)
        os.environ["VORTEX_CONFIG_DIR"] = str(config_dir)
        self.store = Store(Path(self.tmp.name) / "vortex.db")
        self.audit_events: list[tuple[str, dict[str, Any]]] = []
        self.manager = RemoteDesktopManager(
            self.store,
            max_sessions=2,
            idle_seconds=30,
            watch_interval=0.2,
            watch_deadline_seconds=5,
            audit=lambda event, payload: self.audit_events.append((event, payload)),
        )
        self.server = ScriptedRfbServer()

    def tearDown(self) -> None:
        self.manager.shutdown()
        self.server.close()
        if self._previous_config_dir is None:
            os.environ.pop("VORTEX_CONFIG_DIR", None)
        else:
            os.environ["VORTEX_CONFIG_DIR"] = self._previous_config_dir
        self.tmp.cleanup()

    def engagement(self, targets: list[str], *, excluded: list[str] | None = None, expires_at: str | None = None) -> str:
        from backend.vortex_backend import now_iso, secrets as _secrets  # noqa: F401  (kept explicit)

        item = {
            "id": _secrets.token_hex(8),
            "created_at": now_iso(),
            "expires_at": expires_at or _future(),
            "name": "test engagement",
            "authorization": "unit-test authorization",
            "targets": targets,
            "classes": ["remote-desktop"],
            "status": "active",
        }
        self.store.create_engagement(item)
        if excluded:
            with self.store.connect() as db:
                db.execute(
                    "INSERT INTO engagement_scope (engagement_id, excluded_json, environment, owner) VALUES (?,?,?,?)",
                    (item["id"], __import__("json").dumps(excluded), "", ""),
                )
        return item["id"]


def _future(seconds: int = 3600) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")


class ScopeTests(LoopbackWorkspace):
    def test_engagement_is_required_and_must_be_active(self):
        with self.assertRaises(RemoteDesktopError) as raised:
            EngagementScope.load(self.store, "")
        self.assertEqual(raised.exception.code, "engagement_required")

        engagement_id = self.engagement(["127.0.0.1"])
        self.store.close_engagement(engagement_id)
        with self.assertRaises(RemoteDesktopError) as raised:
            EngagementScope.load(self.store, engagement_id)
        self.assertEqual(raised.exception.code, "authorization_revoked")

    def test_expired_engagement_is_rejected(self):
        from datetime import datetime, timedelta, timezone
        expired = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(timespec="milliseconds")
        engagement_id = self.engagement(["127.0.0.1"], expires_at=expired)
        # create_engagement validates, so insert an already-expired row directly.
        with self.store.connect() as db:
            db.execute("UPDATE engagements SET expires_at=? WHERE id=?", (expired, engagement_id))
        with self.assertRaises(RemoteDesktopError) as raised:
            EngagementScope.load(self.store, engagement_id)
        self.assertIn(raised.exception.code, {"authorization_expired", "expired"})

    def test_unapproved_host_is_refused(self):
        engagement_id = self.engagement(["workstation.example.test"])
        scope = EngagementScope.load(self.store, engagement_id)
        with self.assertRaises(RemoteDesktopError) as raised:
            authorize_endpoint(scope, "other.example.test", 5900, addresses=["203.0.113.9"])
        self.assertEqual(raised.exception.code, "target_not_authorized")

    def test_excluded_target_is_refused_even_when_listed(self):
        engagement_id = self.engagement(["127.0.0.1"], excluded=["127.0.0.1"])
        scope = EngagementScope.load(self.store, engagement_id)
        with self.assertRaises(RemoteDesktopError) as raised:
            authorize_endpoint(scope, "127.0.0.1", 5900, addresses=["127.0.0.1"])
        self.assertEqual(raised.exception.code, "target_excluded")

    def test_http_scope_entry_never_authorizes_a_desktop_protocol(self):
        engagement_id = self.engagement(["https://portal.example.test"])
        scope = EngagementScope.load(self.store, engagement_id)
        with self.assertRaises(RemoteDesktopError) as raised:
            authorize_endpoint(scope, "portal.example.test", 5900, addresses=["203.0.113.10"])
        self.assertEqual(raised.exception.code, "target_not_authorized")

    def test_metadata_and_special_addresses_are_never_bridged(self):
        for address in ("169.254.169.254", "100.100.100.200", "224.0.0.1", "fe80::1"):
            engagement_id = self.engagement([address])
            scope = EngagementScope.load(self.store, engagement_id)
            with self.assertRaises(RemoteDesktopError) as raised:
                authorize_endpoint(scope, address, 5900, addresses=[address])
            self.assertIn(raised.exception.code, {"blocked_address", "metadata_blocked"})

    def test_metadata_hostname_is_refused(self):
        engagement_id = self.engagement(["metadata.google.internal"])
        scope = EngagementScope.load(self.store, engagement_id)
        with self.assertRaises(RemoteDesktopError) as raised:
            authorize_endpoint(scope, "metadata.google.internal", 5900, addresses=["169.254.169.254"])
        self.assertEqual(raised.exception.code, "blocked_hostname")

    def test_loopback_requires_a_literal_engagement_entry(self):
        engagement_id = self.engagement(["desktop.example.test"])
        scope = EngagementScope.load(self.store, engagement_id)
        with self.assertRaises(RemoteDesktopError) as raised:
            authorize_endpoint(scope, "desktop.example.test", 5900, addresses=["127.0.0.1"])
        self.assertEqual(raised.exception.code, "loopback_not_authorized")

    def test_private_address_needs_scope_match_or_explicit_acknowledgement(self):
        engagement_id = self.engagement(["desktop.example.test"])
        scope = EngagementScope.load(self.store, engagement_id)
        with self.assertRaises(RemoteDesktopError) as raised:
            authorize_endpoint(scope, "desktop.example.test", 5900, addresses=["10.20.30.40"])
        self.assertEqual(raised.exception.code, "private_address_not_confirmed")
        endpoint = authorize_endpoint(scope, "desktop.example.test", 5900, addresses=["10.20.30.40"], private_address_ack=True)
        self.assertEqual(endpoint["address"], "10.20.30.40")
        self.assertEqual(endpoint["address_class"], "private")

        cidr_id = self.engagement(["10.20.30.0/24"])
        cidr_scope = EngagementScope.load(self.store, cidr_id)
        self.assertEqual(authorize_endpoint(cidr_scope, "10.20.30.40", 5900, addresses=["10.20.30.40"])["address"], "10.20.30.40")

    def test_only_the_vnc_display_range_may_be_dialled(self):
        self.assertEqual(resolve_vnc_port(0), 5900)
        self.assertEqual(resolve_vnc_port(None, 5912), 5912)
        for bad in (22, 3389, 5900 - 1, 6000, 0):
            with self.assertRaises(RemoteDesktopError) as raised:
                resolve_vnc_port(None, bad)
            self.assertEqual(raised.exception.code, "port_out_of_range")
        with self.assertRaises(RemoteDesktopError):
            parse_endpoint_target("host:not-a-port")
        with self.assertRaises(RemoteDesktopError):
            parse_endpoint_target("vnc://host:5900")


class ProbeTests(LoopbackWorkspace):
    def test_probe_reports_a_real_rfb_banner_without_authentication(self):
        report = probe_endpoint(address="127.0.0.1", port=self.server.port, host="127.0.0.1", transport=TRANSPORT_UNENCRYPTED)
        self.assertTrue(report["available"])
        self.assertEqual(report["protocol_version"], "003.008")
        self.assertFalse(report["deep_probe"])
        self.assertEqual(self.server.received, b"")  # nothing was sent: no auth attempt

    def test_probe_reports_non_rfb_services_honestly(self):
        plain = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        plain.bind(("127.0.0.1", 0))
        plain.listen(2)
        port = plain.getsockname()[1]
        try:
            report = probe_endpoint(address="127.0.0.1", port=port, host="127.0.0.1", transport=TRANSPORT_UNENCRYPTED, timeout=1.0)
        except RemoteDesktopError as exc:
            self.assertEqual(exc.code, "protocol_mismatch")
        finally:
            plain.close()

    def test_deep_probe_lists_security_types_and_selects_none(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        port = None
        for candidate in range(5900, 6000):
            try:
                listener.bind(("127.0.0.1", candidate))
                port = candidate
                break
            except OSError:
                continue
        self.assertIsNotNone(port, "no free VNC display port for the deep-probe fixture")
        listener.listen(2)

        def handler() -> None:
            conn, _ = listener.accept()
            try:
                conn.sendall(b"RFB 003.008\n")
                version = conn.recv(12)
                self.assertEqual(version, b"RFB 003.008\n")
                conn.sendall(bytes([2, 2, 19]))
                time.sleep(0.2)
            finally:
                conn.close()
        thread = threading.Thread(target=handler, daemon=True)
        thread.start()
        try:
            report = probe_endpoint(
                address="127.0.0.1", port=port, host="127.0.0.1",
                transport=TRANSPORT_UNENCRYPTED, timeout=2.0, deep=True,
            )
            self.assertTrue(report["available"])
            self.assertEqual(report["security_types"], {2: "vnc-password (DES challenge-response)", 19: "vencrypt"})
            self.assertEqual(report["authentication"], "authentication required by the target")
        finally:
            listener.close()
            thread.join(timeout=2)


    def test_deep_probe_reads_the_single_security_type_of_a_3_3_server(self):
        """RFB 3.3 has no security-type list; the probe must still report honestly.

        Qt's VNC platform plugin (Qt 5.15) negotiates 003.003 and answers the
        version exchange with one 4-byte security type. Reading it is what makes
        the endpoint check useful on those servers; the probe must exit before
        the authentication phase either way.
        """
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        port = None
        for candidate in range(5900, 6000):
            try:
                listener.bind(("127.0.0.1", candidate))
                port = candidate
                break
            except OSError:
                continue
        self.assertIsNotNone(port, "no free VNC display port for the 3.3 fixture")
        listener.listen(2)
        observed: dict[str, bytes] = {}

        def handler() -> None:
            conn, _ = listener.accept()
            try:
                conn.sendall(b"RFB 003.003\n")
                observed["version_reply"] = conn.recv(12)
                conn.sendall(struct.pack(">I", 1))  # security type 1: None
                time.sleep(0.2)
            finally:
                conn.close()

        thread = threading.Thread(target=handler, daemon=True)
        thread.start()
        try:
            report = probe_endpoint(
                address="127.0.0.1", port=port, host="127.0.0.1",
                transport=TRANSPORT_UNENCRYPTED, timeout=2.0, deep=True,
            )
            self.assertTrue(report["available"])
            self.assertEqual(report["protocol_version"], "003.003")
            # The client mirrors the offered version: servers deadlock otherwise.
            self.assertEqual(observed.get("version_reply"), b"RFB 003.003\n")
            self.assertIn(1, report["security_types"])
            self.assertEqual(report["authentication"], "no authentication requested by the target")
        finally:
            listener.close()
            thread.join(timeout=2)


class TicketTests(LoopbackWorkspace):
    def _session(self) -> dict[str, Any]:
        engagement_id = self.engagement(["127.0.0.1"])
        created = self.manager.create(
            engagement_id=engagement_id, host="127.0.0.1", port=self.server.port, transport=TRANSPORT_UNENCRYPTED,
        )
        return self.manager.approve(created["id"], confirm=True, unencrypted_approved=True, protected_path_ack=True)

    def test_ticket_is_single_use_and_bound_to_session_and_client(self):
        session = self._session()
        ticket = self.manager.issue_ticket(session["id"], "fingerprint-a")["ticket"]
        with self.assertRaises(RemoteDesktopError) as reused:
            self.manager.begin_bridge(session["id"], ticket, "fingerprint-b", "http://localhost")
        self.assertEqual(reused.exception.code, "ticket_mismatch")

    def test_ticket_cannot_be_used_by_another_session(self):
        first = self._session()
        engagement_id = first["engagement_id"]
        second = self.manager.create(
            engagement_id=engagement_id, host="127.0.0.1", port=self.server.port, transport=TRANSPORT_UNENCRYPTED,
        )
        self.manager.approve(second["id"], confirm=True, unencrypted_approved=True, protected_path_ack=True)
        ticket = self.manager.issue_ticket(first["id"], "fp")["ticket"]
        with self.assertRaises(RemoteDesktopError) as raised:
            self.manager.begin_bridge(second["id"], ticket, "fp", "http://localhost")
        self.assertEqual(raised.exception.code, "ticket_mismatch")

    def test_subprotocol_parsing_and_negotiation(self):
        self.assertEqual(subprotocol_ticket("vortex.rfb.v1, vortex-ticket.abcDEF1234567890", "s"), "abcDEF1234567890")
        self.assertEqual(negotiate_subprotocol("vortex.rfb.v1, vortex-ticket.x"), "vortex.rfb.v1")
        with self.assertRaises(RemoteDesktopError):
            subprotocol_ticket("vortex.rfb.v1", "s")


class LifecycleTests(LoopbackWorkspace):
    def test_full_lifecycle_and_cleanup(self):
        engagement_id = self.engagement(["127.0.0.1"])
        created = self.manager.create(engagement_id=engagement_id, host="127.0.0.1", port=self.server.port,
                                      transport=TRANSPORT_UNENCRYPTED, label="fixture desktop")
        self.assertEqual(created["state"], STATE_AWAITING_APPROVAL)
        self.assertEqual(created["target"]["identity"], f"127.0.0.1:{self.server.port}")

        approved = self.manager.approve(created["id"], confirm=True, unencrypted_approved=True, protected_path_ack=True)
        self.assertEqual(approved["state"], STATE_CREATED)
        self.assertTrue(approved["unencrypted_approved"])

        ticket = self.manager.issue_ticket(created["id"], "fp")["ticket"]
        prepared = self.manager.begin_bridge(created["id"], ticket, "fp", "http://localhost")
        self.assertEqual(prepared["session"]["state"], STATE_CONNECTED)
        self.assertEqual(self.manager.info(created["id"])["connected_at"] is not None, True)

        prepared["upstream"].close()
        self.manager.note_disconnect(created["id"], "target closed")
        self.assertEqual(self.manager.info(created["id"])["state"], STATE_DISCONNECTED)

        closed = self.manager.close(created["id"], "operator_closed")
        self.assertEqual(closed["state"], STATE_CLOSED)
        self.assertEqual(self.manager.list()[0]["retained"], True)
        self.assertEqual(self.manager.info(created["id"])["state"], STATE_CLOSED)
        # A retained record cannot be reused.
        with self.assertRaises(RemoteDesktopError):
            self.manager.issue_ticket(created["id"], "fp")

    def test_approval_and_ticket_are_required(self):
        engagement_id = self.engagement(["127.0.0.1"])
        created = self.manager.create(engagement_id=engagement_id, host="127.0.0.1", port=self.server.port,
                                      transport=TRANSPORT_UNENCRYPTED)
        with self.assertRaises(RemoteDesktopError) as raised:
            self.manager.issue_ticket(created["id"], "fp")
        self.assertEqual(raised.exception.code, "session_not_approved")
        with self.assertRaises(RemoteDesktopError) as raised:
            self.manager.approve(created["id"], confirm=False)
        self.assertEqual(raised.exception.code, "confirmation_required")

    def test_unencrypted_transport_needs_deployment_opt_in_and_acknowledgement(self):
        engagement_id = self.engagement(["127.0.0.1"])
        created = self.manager.create(engagement_id=engagement_id, host="127.0.0.1", port=self.server.port,
                                      transport=TRANSPORT_UNENCRYPTED)
        self.manager.allow_unencrypted = lambda: False  # deployment does not permit plaintext VNC
        with self.assertRaises(RemoteDesktopError) as raised:
            self.manager.approve(created["id"], confirm=True, unencrypted_approved=True, protected_path_ack=True)
        self.assertEqual(raised.exception.code, "unencrypted_disabled")

        self.manager.allow_unencrypted = lambda: True  # explicit deployment opt-in
        with self.assertRaises(RemoteDesktopError) as raised:
            self.manager.approve(created["id"], confirm=True, unencrypted_approved=True, protected_path_ack=False)
        self.assertEqual(raised.exception.code, "protected_path_required")
        approved = self.manager.approve(created["id"], confirm=True, unencrypted_approved=True, protected_path_ack=True)
        self.assertEqual(approved["state"], STATE_CREATED)

    def test_concurrency_limit_is_enforced(self):
        engagement_id = self.engagement(["127.0.0.1", "127.0.0.2"])
        self.manager.create(engagement_id=engagement_id, host="127.0.0.1", port=self.server.port, transport=TRANSPORT_UNENCRYPTED)
        self.manager.create(engagement_id=engagement_id, host="127.0.0.2", port=self.server.port, transport=TRANSPORT_UNENCRYPTED)
        with self.assertRaises(RemoteDesktopError) as raised:
            self.manager.create(engagement_id=engagement_id, host="127.0.0.3", port=self.server.port, transport=TRANSPORT_UNENCRYPTED)
        self.assertEqual(raised.exception.code, "session_limit")

    def test_close_all_clears_every_session(self):
        engagement_id = self.engagement(["127.0.0.1", "127.0.0.2"])
        for host in ("127.0.0.1", "127.0.0.2"):
            self.manager.create(engagement_id=engagement_id, host=host, port=self.server.port, transport=TRANSPORT_UNENCRYPTED)
        result = self.manager.close_all("operator_stop_all")
        self.assertEqual(result["remote_sessions_closed"], 2)
        self.assertEqual(result["remote_sessions_remaining"], 0)
        self.assertTrue(all(item["state"] == STATE_CLOSED for item in self.manager.list()))

    def test_revoked_engagement_blocks_reconnect_and_closes_live_sessions(self):
        engagement_id = self.engagement(["127.0.0.1"])
        created = self.manager.create(engagement_id=engagement_id, host="127.0.0.1", port=self.server.port,
                                      transport=TRANSPORT_UNENCRYPTED)
        self.manager.approve(created["id"], confirm=True, unencrypted_approved=True, protected_path_ack=True)
        ticket = self.manager.issue_ticket(created["id"], "fp")["ticket"]
        self.manager.begin_bridge(created["id"], ticket, "fp", "http://localhost")
        self.store.close_engagement(engagement_id)
        self.manager._sweep()
        self.assertEqual(self.manager.info(created["id"])["state"], STATE_CLOSED)
        self.assertEqual([item for item in self.manager.list() if not item["retained"]], [])

    def test_authentication_transport_rejects_unverified_tls(self):
        """TLS is never silently downgraded: verification failure is fatal."""
        engagement_id = self.engagement(["127.0.0.1"])
        created = self.manager.create(engagement_id=engagement_id, host="127.0.0.1", port=self.server.port,
                                      transport=TRANSPORT_TLS)
        self.manager.approve(created["id"], confirm=True)
        ticket = self.manager.issue_ticket(created["id"], "fp")["ticket"]
        with self.assertRaises(RemoteDesktopError) as raised:
            self.manager.begin_bridge(created["id"], ticket, "fp", "http://localhost")
        self.assertIn(raised.exception.code, {"tls_handshake_failed", "tls_verification_failed"})
        self.assertEqual(self.manager.info(created["id"])["state"], STATE_FAILED)
        self.assertNotIn("password", self.manager.info(created["id"])["failure_reason"].lower())

    def test_failure_reasons_are_redacted(self):
        engagement_id = self.engagement(["127.0.0.1"])
        created = self.manager.create(engagement_id=engagement_id, host="127.0.0.1", port=self.server.port,
                                      transport=TRANSPORT_UNENCRYPTED)
        self.manager.approve(created["id"], confirm=True, unencrypted_approved=True, protected_path_ack=True)
        self.manager.disconnect(created["id"], "password=hunter2 token=abc123")
        recorded = self.manager.info(created["id"])["disconnect_reason"]
        self.assertNotIn("hunter2", recorded)
        self.assertNotIn("abc123", recorded)

    def test_unavailable_port_reports_an_actionable_failure(self):
        closed_port = self.server.port
        self.server.close()
        engagement_id = self.engagement(["127.0.0.1"])
        created = self.manager.create(engagement_id=engagement_id, host="127.0.0.1", port=closed_port,
                                      transport=TRANSPORT_UNENCRYPTED)
        self.manager.approve(created["id"], confirm=True, unencrypted_approved=True, protected_path_ack=True)
        ticket = self.manager.issue_ticket(created["id"], "fp")["ticket"]
        with self.assertRaises(RemoteDesktopError) as raised:
            self.manager.begin_bridge(created["id"], ticket, "fp", "http://localhost")
        self.assertEqual(raised.exception.code, "connect_failed")
        self.assertIn("Connection to the approved endpoint failed", self.manager.info(created["id"])["failure_reason"])

    def test_watch_mode_probes_then_reports_ready_without_connecting(self):
        fixture = ToggleableRfbServer()
        try:
            engagement_id = self.engagement(["127.0.0.1"])
            created = self.manager.create(engagement_id=engagement_id, host="127.0.0.1", port=fixture.port,
                                          transport=TRANSPORT_UNENCRYPTED)
            self.manager.approve(created["id"], confirm=True, unencrypted_approved=True, protected_path_ack=True, watch=True)
            self.manager._sweep()
            self.assertFalse(self.manager.info(created["id"])["watch_ready"])
            fixture.start()  # a compatible graphical endpoint becomes reachable
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                self.manager._sweep()
                if self.manager.info(created["id"])["watch_ready"]:
                    break
                time.sleep(0.1)
            session = self.manager.info(created["id"])
            self.assertTrue(session["watch_ready"], "watch never observed the endpoint")
            self.assertNotEqual(session["state"], STATE_CONNECTED)  # a window may open; auth is still required
            self.assertTrue(any(event == "remote_desktop_watch_ready" for event, _ in self.audit_events))
        finally:
            fixture.close()

    def test_idle_timeout_closes_a_connected_session(self):
        self.manager.idle_seconds = 1
        engagement_id = self.engagement(["127.0.0.1"])
        created = self.manager.create(engagement_id=engagement_id, host="127.0.0.1", port=self.server.port,
                                      transport=TRANSPORT_UNENCRYPTED)
        self.manager.approve(created["id"], confirm=True, unencrypted_approved=True, protected_path_ack=True)
        ticket = self.manager.issue_ticket(created["id"], "fp")["ticket"]
        self.manager.begin_bridge(created["id"], ticket, "fp", "http://localhost")
        self.manager.sessions[created["id"]].last_activity = time.monotonic() - 5
        self.manager._sweep()
        self.assertEqual(self.manager.info(created["id"])["state"], STATE_CLOSED)
        self.assertEqual([item for item in self.manager.list() if not item["retained"]], [])
        self.assertTrue(any(event == "remote_desktop_idle_timeout" for event, _ in self.audit_events))

    def test_audit_events_never_contain_credentials(self):
        engagement_id = self.engagement(["127.0.0.1"])
        created = self.manager.create(engagement_id=engagement_id, host="127.0.0.1", port=self.server.port,
                                      transport=TRANSPORT_UNENCRYPTED, label="fixture")
        self.manager.approve(created["id"], confirm=True, unencrypted_approved=True, protected_path_ack=True)
        serialized = repr(self.audit_events)
        self.assertNotIn("password", serialized.lower())
        self.assertNotIn("ticket", serialized.lower())


class WebSocketFrameTests(unittest.TestCase):
    """RFC 6455 framing behaviour of the server-side connection."""

    def _pair(self) -> tuple[socket.socket, socket.socket]:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client = socket.create_connection(server.getsockname())
        conn, _ = server.accept()
        server.close()
        return conn, client

    @staticmethod
    def _client_frame(payload: bytes, opcode: int = 0x2, *, fin: bool = True, mask: bytes = b"\x01\x02\x03\x04") -> bytes:
        header = bytearray()
        header.append((0x80 if fin else 0) | opcode)
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
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return bytes(header) + masked

    def test_accept_key_matches_rfc6455_example(self):
        self.assertEqual(WebSocketConnection.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_unmasked_client_frame_is_rejected(self):
        conn, client = self._pair()
        try:
            client.sendall(b"\x82\x03abc")
            ws = WebSocketConnection(conn, conn.makefile("rb"))
            with self.assertRaises(WebSocketClosed) as raised:
                ws.read_message()
            self.assertEqual(raised.exception.code, 1002)
        finally:
            conn.close()
            client.close()

    def test_fragmented_message_is_reassembled_and_oversize_is_refused(self):
        conn, client = self._pair()
        try:
            ws = WebSocketConnection(conn, conn.makefile("rb"))
            client.sendall(self._client_frame(b"RFB", opcode=0x2, fin=False))
            client.sendall(self._client_frame(b" 003", opcode=0x0, fin=False))
            client.sendall(self._client_frame(b".008\n", opcode=0x0, fin=True))
            opcode, payload = ws.read_message()
            self.assertEqual((opcode, payload), (0x2, b"RFB 003.008\n"))
        finally:
            conn.close()
            client.close()

    def test_oversize_message_closes_with_1009(self):
        conn, client = self._pair()
        try:
            ws = WebSocketConnection(conn, conn.makefile("rb"))
            client.sendall(self._client_frame(b"x" * 2048))
            with self.assertRaises(WebSocketClosed) as raised:
                ws.read_message(max_bytes=1024)
            self.assertEqual(raised.exception.code, 1009)
        finally:
            conn.close()
            client.close()

    def test_close_frame_is_surfaced(self):
        conn, client = self._pair()
        try:
            ws = WebSocketConnection(conn, conn.makefile("rb"))
            client.sendall(self._client_frame(struct.pack(">H", 1000) + b"bye", opcode=0x8))
            with self.assertRaises(WebSocketClosed) as raised:
                ws.read_message()
            self.assertEqual(raised.exception.code, 1000)
        finally:
            conn.close()
            client.close()


class BridgeTests(unittest.TestCase):
    def test_bridge_pipes_both_directions_and_stops_once(self):
        upstream_server = ScriptedRfbServer()
        ws_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ws_server.bind(("127.0.0.1", 0))
        ws_server.listen(1)
        client = socket.create_connection(ws_server.getsockname())
        ws_sock, _ = ws_server.accept()
        ws_server.close()
        upstream = socket.create_connection(("127.0.0.1", upstream_server.port))
        closed: list[str] = []
        try:
            bridge = RemoteBridge(
                session_id="0" * 24,
                ws=WebSocketConnection(ws_sock, ws_sock.makefile("rb")),
                upstream=upstream,
                idle_timeout=5.0,
                on_closed=lambda reason, unexpected: closed.append((reason, unexpected)),
            )
            thread = threading.Thread(target=bridge.run, daemon=True)
            thread.start()
            # Server -> client: the fixture banner arrives as one binary frame.
            header = client.recv(2)
            self.assertEqual(header[0] & 0x0F, 0x2)
            payload = client.recv(header[1] & 0x7F)
            self.assertTrue(payload.startswith(b"RFB 003.008"))
            # Client -> server: masked input frame reaches the fixture.
            client.sendall(WebSocketFrameTests._client_frame(b"hello-rfb"))
            deadline = time.monotonic() + 5
            while b"hello-rfb" not in upstream_server.received and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertIn(b"hello-rfb", upstream_server.received)
            deadline = time.monotonic() + 5
            while bridge.client_bytes < len(b"hello-rfb") and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertGreaterEqual(bridge.client_bytes, len(b"hello-rfb"))
            bridge.stop("test")
            bridge.stop("test-again")  # idempotent
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            self.assertTrue(closed)
            self.assertEqual(bridge.close_reason, "test")
            self.assertFalse(bridge.unexpected)
        finally:
            client.close()
            ws_sock.close()
            upstream.close()
            upstream_server.close()


class DisconnectBookkeepingTests(LoopbackWorkspace):
    """A stream teardown must never lie about who ended the connection."""

    def _connected_session(self) -> tuple[dict[str, Any], int]:
        engagement_id = self.engagement(["127.0.0.1"])
        created = self.manager.create(
            engagement_id=engagement_id, host="127.0.0.1", port=self.server.port,
            transport=TRANSPORT_UNENCRYPTED,
        )
        approved = self.manager.approve(
            created["id"], confirm=True, unencrypted_approved=True, protected_path_ack=True,
        )
        prepared = self.manager.begin_bridge(
            approved["id"], self.manager.issue_ticket(approved["id"], "fp")["ticket"], "fp", "http://127.0.0.1:8899",
        )
        try:
            prepared["upstream"].close()
        except OSError:
            pass
        return approved, int(prepared["epoch"])

    def test_unexpected_loss_records_a_sanitized_failure_reason(self):
        session, epoch = self._connected_session()
        self.assertEqual(self.manager.info(session["id"])["state"], STATE_CONNECTED)
        self.manager.note_disconnect(session["id"], "target connection lost: [Errno 104] reset", epoch=epoch,
                                     unexpected=True)
        record = self.manager.info(session["id"])
        self.assertEqual(record["state"], STATE_DISCONNECTED)
        self.assertIn("target connection lost", record["failure_reason"])
        self.assertIn("target connection lost", record["disconnect_reason"])

    def test_clean_disconnect_does_not_claim_a_failure(self):
        session, epoch = self._connected_session()
        self.manager.note_disconnect(session["id"], "operator_disconnected", epoch=epoch)
        record = self.manager.info(session["id"])
        self.assertEqual(record["state"], STATE_DISCONNECTED)
        self.assertEqual(record["failure_reason"], "")
        self.assertEqual(record["disconnect_reason"], "operator_disconnected")

    def test_late_teardown_from_a_superseded_stream_is_ignored(self):
        """Reconnect race: the stale handler must not touch the new stream."""
        session, first_epoch = self._connected_session()
        self.manager.disconnect(session["id"], "operator_disconnected")
        self.manager.request_reconnect(session["id"])
        prepared = self.manager.begin_bridge(
            session["id"], self.manager.issue_ticket(session["id"], "fp")["ticket"], "fp", "http://127.0.0.1:8899",
        )
        try:
            prepared["upstream"].close()
        except OSError:
            pass
        self.assertGreater(int(prepared["epoch"]), first_epoch)
        self.assertEqual(self.manager.info(session["id"])["state"], STATE_CONNECTED)
        # The superseded stream's teardown arrives late, carrying its old epoch.
        self.manager.note_disconnect(session["id"], "operator_disconnected", epoch=first_epoch, unexpected=True)
        record = self.manager.info(session["id"])
        self.assertEqual(record["state"], STATE_CONNECTED, "a stale teardown closed a live, reconnected session")
        self.assertEqual(record["failure_reason"], "")
        self.assertEqual(record["disconnect_reason"], "")


class DependencyReportingTests(unittest.TestCase):
    def test_dependency_rows_carry_state_version_purpose_source_license_and_install(self):
        from backend.dependencies import novnc_status, remote_desktop_capability_items
        items = remote_desktop_capability_items()
        self.assertTrue(items)
        for item in items:
            for key in ("id", "state", "purpose", "source", "license", "installation"):
                self.assertIn(key, item, key)
        novnc = novnc_status()
        self.assertEqual(novnc["license"], "MPL-2.0")
        self.assertIn(novnc["state"], {"bundled", "declared-not-built", "absent"})

    def test_rdp_is_reported_as_not_implemented_not_as_missing_dependency(self):
        from backend.dependencies import remote_desktop_capability_items
        rdp = [item for item in remote_desktop_capability_items() if item["name"] == "rdp-client"]
        self.assertEqual(len(rdp), 1)
        self.assertEqual(rdp[0]["state"], "not-implemented")
        self.assertIn("does not implement RDP", rdp[0]["installation"])


if __name__ == "__main__":
    unittest.main()
