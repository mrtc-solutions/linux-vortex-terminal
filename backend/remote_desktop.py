"""Authorized remote-desktop sessions and a scope-checked WebSocket bridge.

This module owns the *remote* half of the product: the sidecar dials an approved
engagement target, and the renderer receives the real RFB byte stream over an
authenticated, ticket-bound WebSocket. Nothing here fabricates a desktop:

* the browser never contacts the target — the sidecar does, after re-validating
  engagement scope, resolving the endpoint and checking every resolved address;
* the renderer only ever sees bytes a real remote-desktop server produced;
* a remote *shell* (the local PTY in ``SessionManager``) is a different feature
  entirely and is never reported as graphical access.

Security properties enforced here (each has a focused regression test):

1. Only VNC/RFB is implemented. RDP is reported as not implemented rather than
   half-wired, and no other protocol is dialled on the operator's behalf.
2. The bridge dials exactly one validated ``host:port`` and never follows
   redirects, proxies arbitrary URLs, or accepts a renderer-supplied socket.
3. Destination ports are restricted to the VNC display range (5900-5999) so the
   sidecar cannot be turned into a general-purpose TCP proxy.
4. Cloud metadata, link-local, multicast, unspecified and broadcast addresses
   are refused outright; loopback requires a literal engagement match; other
   private/CGNAT/ULA space requires an explicit engagement match or an explicit
   operator acknowledgement for an engagement-approved hostname.
5. TLS is the default transport and certificates are always verified against the
   system trust store. Unencrypted VNC needs both a deployment setting and a
   per-session operator acknowledgement, and is reported loudly everywhere.
6. WebSocket access requires a short-lived, single-use, session-bound ticket
   minted by an authenticated HTTP request, plus an accepted ``Origin``.
7. No credential, screen content, or keystroke is stored, logged, or audited.
   Sessions keep non-secret metadata only.

The module is deliberately standard-library only so the sidecar keeps its
"boots on a fresh Linux install" property.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import struct
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

# --------------------------------------------------------------------------
# Backend helpers (the sidecar owns canonical targets and redaction)
# --------------------------------------------------------------------------

try:  # pragma: no cover - imported as a package
    from .security.scope import excluded as scope_excluded
except ImportError:  # pragma: no cover - direct execution/import
    try:
        from security.scope import excluded as scope_excluded  # type: ignore
    except ImportError:  # pragma: no cover - minimal test harness
        def scope_excluded(target: str, engagement: dict[str, Any] | None) -> bool:  # type: ignore
            return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _default_redact(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(text))
    text = re.sub(r"(?i)\b(password|passwd|secret|token|credential)\s*[=:]\s*\S+", r"\1=[REDACTED]", text)
    return text


try:  # pragma: no cover - sidecar context
    from .vortex_backend import redact as _backend_redact  # type: ignore
except ImportError:  # pragma: no cover
    try:
        from vortex_backend import redact as _backend_redact  # type: ignore
    except ImportError:
        _backend_redact = _default_redact  # type: ignore


def redact(text: Any) -> str:
    """Sanitize an operator-facing reason: no credentials, no control bytes."""
    try:
        return _backend_redact(str(text))
    except Exception:  # pragma: no cover - never let redaction break a session
        return _default_redact(text)


def normalize_target(raw: str) -> str:
    """Canonicalize an engagement target exactly like the sidecar does."""
    try:
        from vortex_backend import normalize_target as _normalize  # type: ignore
    except ImportError:
        try:
            from .vortex_backend import normalize_target as _normalize  # type: ignore
        except ImportError:  # pragma: no cover - minimal test harness
            return str(raw).strip().lower()
    return _normalize(raw)


# --------------------------------------------------------------------------
# Protocol support matrix (honest, not aspirational)
# --------------------------------------------------------------------------

PROTOCOL_VNC = "vnc"
PROTOCOL_RDP = "rdp"

VNC_PORT_LOW = 5900
VNC_PORT_HIGH = 5999
VNC_WS_SUBPROTOCOL = "vortex.rfb.v1"
VNC_WS_PROTOCOL_VERSION = "1.0"
TICKET_PREFIX = "vortex-ticket."
TICKET_TTL_SECONDS = 45
TICKET_MAX_PER_SESSION = 4

TRANSPORT_TLS = "tls"
TRANSPORT_UNENCRYPTED = "unencrypted"

STATE_CREATED = "created"
STATE_AWAITING_APPROVAL = "awaiting_approval"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_RECONNECTING = "reconnecting"
STATE_DISCONNECTED = "disconnected"
STATE_FAILED = "failed"
STATE_CLOSED = "closed"

SESSION_STATES = (
    STATE_CREATED,
    STATE_AWAITING_APPROVAL,
    STATE_CONNECTING,
    STATE_CONNECTED,
    STATE_RECONNECTING,
    STATE_DISCONNECTED,
    STATE_FAILED,
    STATE_CLOSED,
)

PROTOCOL_MATRIX: tuple[dict[str, Any], ...] = (
    {
        "id": PROTOCOL_VNC,
        "name": "VNC (RFB 3.3-3.8)",
        "status": "supported",
        "client": "noVNC (bundled at build time)",
        "transport": ["tls", "unencrypted (opt-in, loudly reported)"],
        "input": "keyboard + mouse forwarded over the same authenticated stream",
        "resize": "client-side scale viewport; server-side resize only when the target offers it",
        "verify": "TCP dial + RFB banner probe; authentication is performed end to end by the client",
        "notes": "Tested against a real X11 desktop served by x11vnc in the release acceptance gate.",
    },
    {
        "id": PROTOCOL_RDP,
        "name": "RDP",
        "status": "not_implemented",
        "client": "none",
        "transport": [],
        "input": "none",
        "resize": "n/a",
        "verify": "n/a",
        "notes": (
            "Vortex Terminal does not implement RDP. No RDP client, gateway, or credential "
            "handling is wired in, and the operator interface reports it as unavailable. "
            "Installing FreeRDP host tools does not enable RDP inside Vortex."
        ),
    },
)

# Addresses that must never be bridged, even when an engagement lists them: they
# are not remote-desktop endpoints and are classic SSRF pivots.
ALWAYS_BLOCKED_ADDRESSES = frozenset({
    "169.254.169.254",   # AWS/GCP/Azure/OpenStack instance metadata
    "169.254.170.2",     # AWS ECS task metadata
    "169.254.169.123",   # AWS NTP/metadata alias
    "100.100.100.200",   # Alibaba Cloud metadata
    "192.0.0.192",       # Oracle Cloud metadata
    "fd00:ec2::254",     # AWS IMDSv6
})

ALWAYS_BLOCKED_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),   # link-local IPv4
    ipaddress.ip_network("fe80::/10"),        # link-local IPv6
    ipaddress.ip_network("ff00::/8"),         # multicast IPv6
    ipaddress.ip_network("224.0.0.0/4"),      # multicast IPv4
    ipaddress.ip_network("0.0.0.0/8"),        # "this network"
    ipaddress.ip_network("240.0.0.0/4"),      # reserved
    ipaddress.ip_network("::/128"),           # unspecified
    ipaddress.ip_network("::1/128"),          # loopback IPv6 is handled as loopback first
)

# Requires an explicit engagement match (literal address, CIDR, or an
# acknowledged private resolution of an approved hostname).
PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT / carrier internal
    ipaddress.ip_network("fc00::/7"),         # unique local IPv6
)

LOOPBACK_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)

BLOCKED_HOSTNAMES = frozenset({
    "metadata",
    "metadata.google.internal",
    "instance-data",
    "instance-data.ec2.internal",
    "kubernetes.default",
    "kubernetes.default.svc",
    "control-plane",
})

RFB_BANNER_RE = re.compile(rb"^RFB (\d{3})\.(\d{3})\n$")

# RFB security types (RFC 6143 + registered extensions).
SECURITY_TYPES: dict[int, str] = {
    0: "invalid",
    1: "none (server accepts unauthenticated clients)",
    2: "vnc-password (DES challenge-response)",
    5: "ra2",
    6: "ra2ne",
    16: "tight",
    17: "ultra",
    18: "tls",
    19: "vencrypt",
    20: "sasl",
    21: "md5-hash",
    22: "xvp",
    30: "apple-remote-desktop",
    35: "tls-plain",
}

# WebSocket tuning. Frames are bounded so a hostile client cannot exhaust memory,
# and server->client frames stay under the 64 KiB single-frame length field.
WS_MAX_MESSAGE_BYTES = 1024 * 1024
WS_SEND_CHUNK = 60 * 1024
WS_IDLE_POLL = 0.25

MAX_PROBE_BYTES = 64
MAX_LABEL_LENGTH = 120


class RemoteDesktopError(ValueError):
    """Operator-facing failure with a stable machine code."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _utc_timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


# --------------------------------------------------------------------------
# Endpoint parsing and engagement scope
# --------------------------------------------------------------------------


def parse_endpoint_target(raw: str) -> tuple[str, int | None]:
    """Parse a host / host:port / [v6]:port endpoint as typed by the operator.

    The engagement scope is the authority for *which* hosts may be contacted;
    this helper only rejects malformed input and never invents a port.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise RemoteDesktopError("invalid_endpoint", "Target host is required.")
    value = raw.strip()
    if len(value) > 253 or any(char in value for char in "\x00\r\n\t ;|&`$()<>\\\"'"):
        raise RemoteDesktopError("invalid_endpoint", "Target host contains unsupported characters.")
    if re.search(r"(?i)^(https?|vnc|rdp|rfb|tcp)://", value):
        raise RemoteDesktopError(
            "invalid_endpoint",
            "Enter the target as a host, or host:port. Scheme URLs are not accepted here; "
            "the engagement scope lists the canonical host.",
        )
    host = value
    port: int | None = None
    if value.startswith("["):
        close = value.find("]")
        if close < 0:
            raise RemoteDesktopError("invalid_endpoint", "Invalid IPv6 literal: missing closing bracket.")
        host = value[1:close]
        remainder = value[close + 1:]
        if remainder:
            if not remainder.startswith(":") or not remainder[1:].isdigit():
                raise RemoteDesktopError("invalid_endpoint", "Invalid port after the IPv6 literal.")
            port = int(remainder[1:])
    elif value.count(":") == 1:
        host, raw_port = value.rsplit(":", 1)
        if not raw_port.isdigit():
            raise RemoteDesktopError("invalid_endpoint", "Port must be numeric.")
        port = int(raw_port)
    elif value.count(":") > 1:
        host = value  # bare IPv6 literal
    host = host.strip().rstrip(".").lower()
    if not host or len(host) > 253:
        raise RemoteDesktopError("invalid_endpoint", "Target host is empty or too long.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        if any(not label for label in labels) or any(len(label) > 63 for label in labels):
            raise RemoteDesktopError("invalid_endpoint", "Target host is not a valid hostname or IP address.")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host, re.IGNORECASE):
            raise RemoteDesktopError("invalid_endpoint", "Target host is not a valid hostname or IP address.")
    if port is not None and not (1 <= port <= 65535):
        raise RemoteDesktopError("invalid_endpoint", "Port must be between 1 and 65535.")
    return host, port


def resolve_vnc_port(display: Any, explicit: Any = None) -> int:
    """Resolve the VNC port from a display number, restricted to 5900-5999.

    Only the standard display range may be bridged. Reaching a non-standard port
    would turn the sidecar into a general proxying primitive, so it is refused
    with instructions to tunnel the display into range instead.
    """
    port: int | None = None
    if explicit is not None and explicit != "":
        if isinstance(explicit, bool) or not isinstance(explicit, int):
            raise RemoteDesktopError("invalid_port", "Explicit port must be an integer.")
        port = int(explicit)
    elif display is not None and display != "":
        if isinstance(display, bool) or not isinstance(display, int):
            raise RemoteDesktopError("invalid_display", "VNC display must be an integer.")
        if not (0 <= int(display) <= 99):
            raise RemoteDesktopError("invalid_display", "VNC display must be between 0 and 99.")
        port = VNC_PORT_LOW + int(display)
    if port is None:
        port = VNC_PORT_LOW
    if not (VNC_PORT_LOW <= port <= VNC_PORT_HIGH):
        raise RemoteDesktopError(
            "port_out_of_range",
            f"Only VNC display ports {VNC_PORT_LOW}-{VNC_PORT_HIGH} can be bridged. "
            "Tunnel or forward the target display into that range (for example an SSH or VPN tunnel) "
            "instead of exposing an arbitrary port to the sidecar.",
        )
    return port


def _host_matches_target(entry: str, host: str) -> bool:
    """True when a canonical engagement entry authorizes this host name."""
    entry_norm = normalize_target(entry)
    if "/" in entry_norm and not entry_norm.lower().startswith(("http://", "https://")):
        return False  # CIDR entries are matched by address, not by name
    if entry_norm.lower().startswith(("http://", "https://")):
        return False  # an HTTP scope entry never authorizes a desktop protocol
    return entry_norm == host or host.endswith("." + entry_norm)


def _address_in_target(entry: str, address: str) -> bool:
    entry_norm = normalize_target(entry)
    if entry_norm.lower().startswith(("http://", "https://")):
        return False
    if "/" in entry_norm:
        try:
            network = ipaddress.ip_network(entry_norm, strict=False)
        except ValueError:
            return False
        try:
            return ipaddress.ip_address(address) in network
        except ValueError:
            return False
    try:
        return str(ipaddress.ip_address(entry_norm)) == str(ipaddress.ip_address(address))
    except ValueError:
        return False


class EngagementScope:
    """Validated view of the engagement that authorizes a remote session."""

    def __init__(self, engagement: dict[str, Any]):
        self.engagement = engagement
        self.id = str(engagement.get("id") or "")
        self.targets = [str(item) for item in (engagement.get("targets") or [])]

    @classmethod
    def load(cls, store: Any, engagement_id: Any) -> "EngagementScope":
        if not isinstance(engagement_id, str) or not engagement_id.strip():
            raise RemoteDesktopError(
                "engagement_required",
                "An authorized engagement is required. Remote sessions never open outside an approved scope.",
                403,
            )
        record = store.get_engagement(engagement_id.strip())
        if not record:
            raise RemoteDesktopError("engagement_not_found", "Engagement not found.", 404)
        if str(record.get("status") or "") != "active":
            raise RemoteDesktopError(
                "authorization_revoked",
                "This engagement is closed. Authorization for its targets was revoked.",
                403,
            )
        expires = _utc_timestamp(record.get("expires_at"))
        if expires is None or expires <= time.time():
            raise RemoteDesktopError(
                "authorization_expired",
                "This engagement authorization expired. Re-authorize the target before connecting.",
                403,
            )
        scope = cls(record)
        scope.excluded_targets = scope._excluded_targets(store)
        return scope

    def _excluded_targets(self, store: Any) -> list[str]:
        try:
            with store.connect() as db:
                row = db.execute(
                    "SELECT excluded_json FROM engagement_scope WHERE engagement_id=?",
                    (self.id,),
                ).fetchone()
            if row:
                values = row["excluded_json"] if "excluded_json" in row.keys() else row[0]
                return [str(item) for item in json.loads(values)]
        except Exception:
            pass
        return []

    def is_excluded(self, host: str) -> bool:
        engagement = dict(self.engagement)
        engagement["excluded_targets"] = list(self.excluded_targets)
        try:
            if scope_excluded(host, engagement):
                return True
        except Exception:
            return False
        return False

    def authorizes_host(self, host: str) -> str | None:
        for entry in self.targets:
            try:
                if _host_matches_target(entry, host):
                    return normalize_target(entry)
            except Exception:
                continue
        return None

    def authorizes_address(self, address: str) -> str | None:
        for entry in self.targets:
            try:
                if _address_in_target(entry, address):
                    return normalize_target(entry)
            except Exception:
                continue
        return None

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "engagement_id": self.id,
            "name": str(self.engagement.get("name") or ""),
            "targets": self.targets[:100],
            "expires_at": self.engagement.get("expires_at"),
        }


def _address_class(address: str) -> str:
    """Classify a resolved address for the scope decision."""
    try:
        value = ipaddress.ip_address(address)
    except ValueError:
        return "invalid"
    if str(value) in ALWAYS_BLOCKED_ADDRESSES:
        return "metadata"
    if any(value in network for network in LOOPBACK_NETWORKS):
        return "loopback"
    if any(value in network for network in ALWAYS_BLOCKED_NETWORKS):
        return "special"
    if any(value in network for network in PRIVATE_NETWORKS):
        return "private"
    return "global"


def resolve_endpoint(host: str, port: int, *, timeout: float = 5.0) -> list[str]:
    """Resolve once, for validation and for the actual dial target."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise RemoteDesktopError("dns_failure", redact(f"Could not resolve the approved target: {exc}")) from exc
    addresses: list[str] = []
    for info in infos:
        address = str(info[4][0])
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise RemoteDesktopError("dns_failure", "The approved target did not resolve to any address.")
    return addresses


def authorize_endpoint(
    scope: EngagementScope,
    host: str,
    port: int,
    *,
    addresses: list[str] | None = None,
    private_address_ack: bool = False,
) -> dict[str, Any]:
    """Decide whether the sidecar may dial this exact endpoint.

    Returns the validated endpoint (host, port, chosen address, matched scope
    entry) or raises :class:`RemoteDesktopError` with an actionable reason.
    """
    lowered = host.lower().rstrip(".")
    if lowered in BLOCKED_HOSTNAMES:
        raise RemoteDesktopError(
            "blocked_hostname",
            "That host name is a platform metadata/control-plane name. Vortex never bridges it.",
            403,
        )
    if scope.is_excluded(lowered):
        raise RemoteDesktopError(
            "target_excluded",
            f"{lowered} is listed as an excluded target in this engagement.",
            403,
        )
    resolved = addresses if addresses is not None else resolve_endpoint(lowered, port)
    # A scope entry authorizes either the host name itself or (for IP/CIDR
    # entries) the address it resolves to. Everything else needs a new
    # authorization: an engagement never silently widens.
    authorizes_host = scope.authorizes_host(lowered)
    if not authorizes_host:
        authorizes_host = next((scope.authorizes_address(item) for item in resolved if scope.authorizes_address(item)), None)
    if not authorizes_host:
        raise RemoteDesktopError(
            "target_not_authorized",
            f"{lowered} is not in the engagement scope. Add the exact host (or its CIDR) to the "
            "engagement authorization before requesting a remote desktop.",
            403,
        )
    for address in resolved:
        kind = _address_class(address)
        if kind in {"metadata", "special", "invalid"}:
            raise RemoteDesktopError(
                "blocked_address",
                f"{lowered} resolves to {address}, a metadata/link-local/multicast address. "
                "Vortex never bridges these endpoints.",
                403,
            )
        if kind == "loopback":
            if not scope.authorizes_address(address):
                raise RemoteDesktopError(
                    "loopback_not_authorized",
                    f"{lowered} resolves to the loopback address {address}. Add that literal address to the "
                    "engagement scope if this local desktop is genuinely in scope.",
                    403,
                )
            continue
        if kind == "private":
            if scope.authorizes_address(address):
                continue
            if private_address_ack:
                continue
            raise RemoteDesktopError(
                "private_address_not_confirmed",
                f"{lowered} resolves to the private address {address}. Confirm the private-address "
                "routing for this approved target, or add the address/CIDR to the engagement scope.",
                403,
            )
    address = next((item for item in resolved if _address_class(item) == "global"), resolved[0])
    return {
        "host": lowered,
        "port": port,
        "address": address,
        "addresses": resolved,
        "matched_target": authorizes_host,
        "address_class": _address_class(address),
        "dns_name": _is_dns_name(lowered),
    }


def _is_dns_name(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        return True


# --------------------------------------------------------------------------
# RFB probing
# --------------------------------------------------------------------------


def _open_socket(
    address: str,
    port: int,
    *,
    timeout: float,
    transport: str,
    server_hostname: str,
    ca_file: str | None = None,
) -> tuple[socket.socket, dict[str, Any]]:
    """Dial one validated address and return a ready (optionally TLS) socket."""
    sock = socket.socket(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((address, port))
    except OSError as exc:
        sock.close()
        raise RemoteDesktopError("connect_failed", redact(f"Connection to the approved endpoint failed: {exc}")) from exc
    details: dict[str, Any] = {"transport": transport, "tls_verified": False}
    if transport == TRANSPORT_TLS:
        # Certificate verification is mandatory: no unverified fallback exists.
        try:
            context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH, cafile=ca_file or None)
            if ca_file:
                context.load_verify_locations(cafile=ca_file)
            wrapped = context.wrap_socket(sock, server_hostname=server_hostname)
        except ssl.SSLCertVerificationError as exc:
            sock.close()
            raise RemoteDesktopError(
                "tls_verification_failed",
                redact(
                    "TLS certificate verification failed; Vortex does not ignore certificate errors. "
                    f"Reason: {exc.verify_message if hasattr(exc, 'verify_message') else exc}"
                ),
            ) from exc
        except ssl.SSLError as exc:
            sock.close()
            raise RemoteDesktopError("tls_handshake_failed", redact(f"TLS handshake failed: {exc}")) from exc
        except OSError as exc:
            sock.close()
            raise RemoteDesktopError("tls_handshake_failed", redact(f"TLS handshake failed: {exc}")) from exc
        certificate = wrapped.getpeercert() or {}
        details.update({
            "tls_verified": True,
            "tls_version": wrapped.version(),
            "tls_cipher": (wrapped.cipher() or ("",))[0],
            "tls_peer_subject": _flatten_name(certificate.get("subject")),
            "tls_peer_notAfter": certificate.get("notAfter"),
        })
        sock = wrapped
    return sock, details


def _flatten_name(parts: Any) -> str:
    try:
        return ", ".join("=".join(str(item) for item in group) for group in (parts or []))
    except (TypeError, ValueError):
        return ""


def probe_endpoint(
    *,
    address: str,
    port: int,
    host: str,
    transport: str = TRANSPORT_TLS,
    timeout: float = 6.0,
    deep: bool = False,
    ca_file: str | None = None,
) -> dict[str, Any]:
    """Check whether a compatible graphical endpoint answers on this endpoint.

    This is a *reachability and protocol* check. It never authenticates, never
    submits a password, and never claims that a graphical session is available
    just because a socket opened.
    """
    sock: socket.socket | None = None
    started = time.monotonic()
    try:
        sock, details = _open_socket(
            address, port, timeout=timeout, transport=transport, server_hostname=host, ca_file=ca_file,
        )
        banner = _read_exactly(sock, 12, deadline=time.monotonic() + timeout)
        if not RFB_BANNER_RE.match(banner):
            raise RemoteDesktopError(
                "protocol_mismatch",
                "The endpoint answered, but it does not speak the RFB/VNC protocol "
                f"(first bytes: {banner[:12]!r}). A reachable port is not a graphical session.",
            )
        version = banner.decode("ascii").strip().split(" ", 1)[1]
        report: dict[str, Any] = {
            "available": True,
            "protocol": PROTOCOL_VNC,
            "protocol_version": version,
            "endpoint": {"host": host, "port": port, "address": address},
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            **details,
        }
        if deep:
            security = _probe_security_types(sock, version, deadline=time.monotonic() + timeout)
            report.update(security)
            report["deep_probe"] = True
            report["deep_probe_note"] = (
                "A handshake was started to list offered security types; it appears in the target's log. "
                "No credentials were sent and no security type was selected."
            )
        else:
            report["deep_probe"] = False
            report["authentication"] = "not determined (banner-only probe; use a deep probe to list security types)"
        return report
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _read_exactly(sock: socket.socket, size: int, *, deadline: float) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sock.settimeout(max(0.05, min(remaining, 5.0)))
        try:
            chunk = sock.recv(size - len(chunks))
        except (socket.timeout, TimeoutError):
            break
        except OSError as exc:
            raise RemoteDesktopError("connect_failed", redact(f"Reading from the endpoint failed: {exc}")) from exc
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def _probe_security_types(sock: socket.socket, version: str, *, deadline: float) -> dict[str, Any]:
    """Read the offered RFB security types without selecting or submitting one."""
    try:
        major, minor = (int(part) for part in version.split("."))
    except ValueError:
        return {"security_types": "unknown"}
    if (major, minor) < (3, 7):
        # 3.3 has no security-type list: the server answers the version exchange
        # with a single 4-byte type. Reply with the server's own version and read
        # that number - no security type is selected and no credential is sent.
        try:
            sock.sendall(f"RFB {version}\n".encode("ascii"))
        except OSError:
            return {"security_types": "unavailable"}
        raw = _read_exactly(sock, 4, deadline=deadline)
        if len(raw) != 4:
            return {"security_types": "incomplete"}
        code = struct.unpack(">I", raw)[0]
        name = SECURITY_TYPES.get(code, f"unknown({code})")
        return {
            "security_types": {code: name},
            "authentication": "no authentication requested by the target" if code == 1 else name,
        }
    # Ask the server for its list; never select a type and never send credentials.
    try:
        sock.sendall(f"RFB {version}\n".encode("ascii"))
    except OSError:
        return {"security_types": "unavailable"}
    count_raw = _read_exactly(sock, 1, deadline=deadline)
    if len(count_raw) != 1:
        return {"security_types": "incomplete"}
    count = count_raw[0]
    if count == 0:
        reason_raw = _read_exactly(sock, 4, deadline=deadline)
        length = struct.unpack(">I", reason_raw)[0] if len(reason_raw) == 4 else 0
        reason = _read_exactly(sock, min(length, 256), deadline=deadline).decode("utf-8", "replace")
        return {"security_types": {}, "authentication": "server-refused", "server_reason": redact(reason)}
    listed = _read_exactly(sock, min(count, 32), deadline=deadline)
    types = {int(code): SECURITY_TYPES.get(int(code), f"unknown({int(code)})") for code in listed}
    result: dict[str, Any] = {"security_types": types}
    if 1 in types:
        result["authentication"] = "none offered by the server - do not treat this as authorized access"
        result["warning"] = "The target offers an unauthenticated RFB security type."
    else:
        result["authentication"] = "authentication required by the target"
    return result


# --------------------------------------------------------------------------
# Short-lived, session-bound connection tickets
# --------------------------------------------------------------------------


class TicketStore:
    """Single-use WebSocket tickets bound to a session and a capability."""

    def __init__(self, ttl: int = TICKET_TTL_SECONDS, max_per_session: int = TICKET_MAX_PER_SESSION):
        self.ttl = ttl
        self.max_per_session = max_per_session
        self._tickets: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def issue(self, session_id: str, fingerprint: str) -> str:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            issued = [key for key, item in self._tickets.items() if item["session_id"] == session_id]
            if len(issued) >= self.max_per_session:
                oldest = min(issued, key=lambda key: self._tickets[key]["expires"])
                self._tickets.pop(oldest, None)
            ticket = secrets.token_urlsafe(32)
            self._tickets[ticket] = {
                "session_id": session_id,
                "fingerprint": fingerprint,
                "expires": now + self.ttl,
                "used": False,
            }
            return ticket

    def consume(self, ticket: str, session_id: str, fingerprint: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            item = self._tickets.get(ticket)
            if item is None:
                raise RemoteDesktopError("ticket_invalid", "The connection ticket is unknown, expired, or already used.", 403)
            if item["used"]:
                self._tickets.pop(ticket, None)
                raise RemoteDesktopError("ticket_reused", "The connection ticket was already used.", 403)
            if item["expires"] <= now:
                self._tickets.pop(ticket, None)
                raise RemoteDesktopError("ticket_expired", "The connection ticket expired. Request a new one.", 403)
            if item["session_id"] != session_id or item["fingerprint"] != fingerprint:
                self._tickets.pop(ticket, None)
                raise RemoteDesktopError("ticket_mismatch", "The connection ticket does not belong to this session and client.", 403)
            item["used"] = True
            self._tickets.pop(ticket, None)

    def revoke_session(self, session_id: str) -> int:
        with self._lock:
            keys = [key for key, item in self._tickets.items() if item["session_id"] == session_id]
            for key in keys:
                self._tickets.pop(key, None)
            return len(keys)

    def _prune(self, now: float) -> None:
        for key in [key for key, item in self._tickets.items() if item["expires"] <= now or item["used"]]:
            self._tickets.pop(key, None)


# --------------------------------------------------------------------------
# RFC 6455 WebSocket plumbing (server side, binary payloads only)
# --------------------------------------------------------------------------


class WebSocketClosed(Exception):
    def __init__(self, code: int = 1000, reason: str = ""):
        super().__init__(reason or f"websocket closed ({code})")
        self.code = code
        self.reason = reason


class WebSocketConnection:
    """Minimal, strict RFC 6455 server connection used by the RFB bridge."""

    def __init__(self, sock: socket.socket, rfile: Any):
        self.sock = sock
        self.rfile = rfile
        self.closed = False
        self.last_activity = time.monotonic()
        self._send_lock = threading.Lock()

    # ---- handshake ----

    @staticmethod
    def accept_key(client_key: str) -> str:
        digest = hashlib.sha1((client_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        return base64.b64encode(digest).decode("ascii")

    # ---- framing ----

    def read_message(self, max_bytes: int = WS_MAX_MESSAGE_BYTES) -> tuple[int, bytes]:
        """Read one complete message. Returns (opcode, payload)."""
        fragments = bytearray()
        opcode: int | None = None
        while True:
            fin, frame_opcode, payload = self._read_frame(max_bytes)
            self.last_activity = time.monotonic()
            if frame_opcode >= 0x8:
                if not fin or len(payload) > 125:
                    raise WebSocketClosed(1002, "invalid control frame")
                if frame_opcode == 0x8:
                    code = 1000
                    reason = ""
                    if len(payload) >= 2:
                        code = struct.unpack(">H", payload[:2])[0]
                        reason = payload[2:].decode("utf-8", "replace")
                    raise WebSocketClosed(code, reason)
                if frame_opcode == 0x9:
                    self.send_frame(payload, opcode=0xA)
                continue  # pong: activity noted above
            if frame_opcode == 0x0:
                if opcode is None:
                    raise WebSocketClosed(1002, "continuation without a start frame")
            else:
                if opcode is not None:
                    raise WebSocketClosed(1002, "new data frame before the previous message finished")
                opcode = frame_opcode
            fragments.extend(payload)
            if len(fragments) > max_bytes:
                raise WebSocketClosed(1009, "message too large")
            if fin:
                return opcode if opcode is not None else 0x2, bytes(fragments)

    def _read_frame(self, max_bytes: int) -> tuple[bool, int, bytes]:
        header = self._read_exactly(2)
        if not header:
            raise WebSocketClosed(1006, "client connection lost")
        first, second = header[0], header[1]
        fin = bool(first & 0x80)
        if first & 0x70:
            raise WebSocketClosed(1002, "reserved bits set")
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if not masked:
            # A server MUST reject unmasked client frames.
            raise WebSocketClosed(1002, "client frames must be masked")
        if length == 126:
            length = struct.unpack(">H", self._read_exactly(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read_exactly(8))[0]
            if length > (1 << 32):
                raise WebSocketClosed(1009, "frame too large")
        if length > max_bytes:
            raise WebSocketClosed(1009, "frame too large")
        mask = self._read_exactly(4)
        payload = self._read_exactly(length) if length else b""
        if len(payload) != length:
            raise WebSocketClosed(1006, "truncated frame")
        return fin, opcode, bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))

    def _read_exactly(self, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            try:
                chunk = self.rfile.read(size - len(chunks))
            except (OSError, ValueError):
                raise WebSocketClosed(1006, "connection lost")
            if not chunk:
                raise WebSocketClosed(1006, "client connection lost")
            chunks.extend(chunk)
        return bytes(chunks)

    def send_frame(self, payload: bytes, opcode: int = 0x2, fin: bool = True) -> None:
        if self.closed:
            return
        header = bytearray()
        header.append((0x80 if fin else 0) | (opcode & 0x0F))
        length = len(payload)
        if length < 126:
            header.append(length)
        elif length < (1 << 16):
            header.append(126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(127)
            header.extend(struct.pack(">Q", length))
        with self._send_lock:
            try:
                self.sock.sendall(bytes(header) + payload)
            except OSError as exc:
                self.closed = True
                raise WebSocketClosed(1006, f"send failed: {exc}") from exc

    def send_bytes(self, payload: bytes) -> None:
        if not payload:
            return
        for offset in range(0, len(payload), WS_SEND_CHUNK):
            self.send_frame(payload[offset:offset + WS_SEND_CHUNK], opcode=0x2)

    def ping(self, payload: bytes = b"") -> None:
        self.send_frame(payload[:125], opcode=0x9)

    def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.send_frame(struct.pack(">H", code) + reason.encode("utf-8")[:120], opcode=0x8)
        except WebSocketClosed:
            pass
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


# --------------------------------------------------------------------------
# The bridge
# --------------------------------------------------------------------------


class RemoteBridge:
    """Pipes one WebSocket to one validated remote-desktop socket.

    Each instance owns exactly one upstream socket, one WebSocket, and one reader
    thread. Credentials, tickets, and sockets are never shared between sessions,
    and ``stop()`` is idempotent so window close, STOP ALL, and handler teardown
    can all call it safely.
    """

    def __init__(
        self,
        *,
        session_id: str,
        ws: WebSocketConnection,
        upstream: socket.socket,
        on_activity: Callable[[], None] | None = None,
        on_closed: Callable[[str, bool], None] | None = None,
        idle_timeout: float = 900.0,
        log: Callable[[str], None] | None = None,
    ):
        self.session_id = session_id
        self.ws = ws
        self.upstream = upstream
        self.on_activity = on_activity
        self.on_closed = on_closed
        self.idle_timeout = idle_timeout
        self.log = log or (lambda _message: None)
        self.upstream_bytes = 0
        self.client_bytes = 0
        self.started_at = time.monotonic()
        self.last_activity = time.monotonic()
        self.stop_event = threading.Event()
        self.reader: threading.Thread | None = None
        self.close_reason = ""
        # True when the stream ended without an operator action: the target or
        # the network went away. The manager records that as a failure reason so
        # the operator never mistakes an outage for a clean disconnect.
        self.unexpected = False
        # True once an operator action (disconnect, close, STOP ALL, shutdown)
        # started the teardown. Later socket errors are then consequences of
        # that action and must not be reported as connection failures.
        self._deliberate_stop = False
        self._stopped = threading.Event()

    # ---- lifecycle ----

    def run(self) -> None:
        """Serve the session until either side closes. Owns the handler thread."""
        self.reader = threading.Thread(target=self._upstream_to_client, name=f"vortex-rfb-{self.session_id[:8]}", daemon=True)
        self.reader.start()
        try:
            while not self.stop_event.is_set():
                try:
                    opcode, payload = self.ws.read_message()
                except WebSocketClosed as closed:
                    self._finish(_client_close_reason(closed.code, closed.reason),
                                 unexpected=closed.code == 1006)
                    return
                self.last_activity = time.monotonic()
                if self.on_activity:
                    self.on_activity()
                if opcode == 0x1:
                    # Text frames are not part of RFB; refuse rather than guess.
                    self.ws.close(1003, "binary frames only")
                    self._finish("client sent a text frame", unexpected=True)
                    return
                try:
                    self.upstream.sendall(payload)
                except OSError as exc:
                    self._finish(f"target connection lost: {exc}", unexpected=True)
                    return
                self.client_bytes += len(payload)
                if self._idle_expired():
                    self._finish("idle timeout")
                    return
        finally:
            self._shutdown_sockets()
            if self.reader is not None and self.reader is not threading.current_thread():
                self.reader.join(timeout=2.0)
            if self.on_closed:
                try:
                    self.on_closed(self.close_reason or "closed", self.unexpected)
                except Exception:  # pragma: no cover - teardown must not raise
                    pass

    def _upstream_to_client(self) -> None:
        last_ping = time.monotonic()
        while not self.stop_event.is_set():
            if (time.monotonic() - last_ping) > 20:
                last_ping = time.monotonic()
                try:
                    self.ws.ping()
                except WebSocketClosed:
                    self._finish("client connection lost")
                    return
            if self._idle_expired():
                self.ws.close(1001, "idle timeout")
                self.stop_event.set()
                self._shutdown_sockets()
                return
            self.upstream.settimeout(WS_IDLE_POLL)
            try:
                chunk = self.upstream.recv(WS_SEND_CHUNK)
            except (socket.timeout, TimeoutError):
                continue
            except OSError as exc:
                self._finish(f"target connection lost: {redact(str(exc))}", unexpected=True)
                return
            if not chunk:
                # The target ended the stream. Record that before tearing the
                # client socket down, so the operator sees the real cause rather
                # than the client-side symptom of our own shutdown.
                self._finish("the remote desktop closed the connection", unexpected=True)
                return
            try:
                self.ws.send_bytes(chunk)
            except WebSocketClosed as exc:
                self._finish(str(exc), unexpected=True)
                return
            self.upstream_bytes += len(chunk)
            self.last_activity = time.monotonic()

    def _idle_expired(self) -> bool:
        return self.idle_timeout > 0 and (time.monotonic() - self.last_activity) > self.idle_timeout

    def _finish(self, reason: str, *, unexpected: bool = False) -> None:
        if self.stop_event.is_set():
            # Teardown already started: keep the first (root-cause) reason. A
            # later error only adds information when the stream died on its own;
            # after a deliberate stop it is just our own socket teardown.
            if not self._deliberate_stop:
                self.unexpected = self.unexpected or unexpected
            return
        self.close_reason = reason
        self.unexpected = self.unexpected or unexpected
        self.stop_event.set()
        self._shutdown_sockets()

    def _shutdown_sockets(self) -> None:
        if self._stopped.is_set():
            return
        self._stopped.set()
        self.stop_event.set()
        try:
            self.upstream.close()
        except OSError:
            pass
        try:
            self.ws.close(1000, "session closed")
        except Exception:  # pragma: no cover
            pass

    def stop(self, reason: str = "operator_disconnected") -> None:
        """Idempotent teardown used by disconnect, STOP ALL, and shutdown.

        The first finished path keeps the root cause: a deliberate stop records
        the operator's reason, while a stream that already died keeps the
        network-side reason instead of having it overwritten by the handler's
        teardown bookkeeping.
        """
        if self.stop_event.is_set():
            self._shutdown_sockets()
            return
        self._deliberate_stop = True
        self.unexpected = False
        self.close_reason = reason
        self.stop_event.set()
        self._shutdown_sockets()

    def stats(self) -> dict[str, Any]:
        return {
            "upstream_bytes": self.upstream_bytes,
            "client_bytes": self.client_bytes,
            "seconds": round(time.monotonic() - self.started_at, 3),
        }


def _client_close_reason(code: int, reason: str) -> str:
    """Operator-facing wording for a close frame from the desktop window."""
    if reason:
        return reason
    if code in {1000, 1001}:
        return "the desktop window was closed"
    if code == 1006:
        return "the desktop window's connection was lost"
    return f"client closed ({code})"


# --------------------------------------------------------------------------
# Session manager
# --------------------------------------------------------------------------


class RemoteSession:
    """Non-secret metadata plus live runtime handles for one desktop session."""

    def __init__(self, session_id: str, *, engagement: dict[str, Any], endpoint: dict[str, Any], protocol: str,
                 transport: str, label: str, owner: str):
        self.id = session_id
        self.engagement = engagement
        self.endpoint = endpoint
        self.protocol = protocol
        self.transport = transport
        self.label = label
        self.owner = owner
        self.state = STATE_AWAITING_APPROVAL
        self.created_at = _now_iso()
        self.approved_at: str | None = None
        self.connected_at: str | None = None
        self.disconnected_at: str | None = None
        self.closed_at: str | None = None
        self.last_activity = time.monotonic()
        self.last_activity_at = self.created_at
        # Connection generation. Every accepted stream bumps it, so a teardown
        # that arrives late - after a reconnect has already taken over - cannot
        # mark the new, healthy connection as disconnected.
        self.epoch = 0
        self.failure_reason = ""
        self.disconnect_reason = ""
        self.reconnect_attempts = 0
        self.unencrypted_approved = False
        self.protected_path_ack = False
        self.private_address_ack = False
        self.watch_ready = False
        self.watch_requested = False
        self.watch_deadline = 0.0
        self.client_library = ""
        self.bridge: RemoteBridge | None = None
        self.upstream: socket.socket | None = None
        self.tickets = 0
        self.deep_probe: dict[str, Any] | None = None

    def public(self) -> dict[str, Any]:
        """Everything the UI may see: no sockets, tickets, or credentials."""
        bridge = self.bridge.stats() if self.bridge is not None else {"upstream_bytes": 0, "client_bytes": 0, "seconds": 0}
        return {
            "id": self.id,
            "engagement_id": self.engagement.get("id"),
            "engagement_name": self.engagement.get("name"),
            "target": {
                "host": self.endpoint.get("host"),
                "port": self.endpoint.get("port"),
                "address": self.endpoint.get("address"),
                "identity": self.endpoint.get("identity"),
                "matched_target": self.endpoint.get("matched_target"),
                "address_class": self.endpoint.get("address_class"),
                "display": (int(self.endpoint.get("port", VNC_PORT_LOW)) - VNC_PORT_LOW)
                if isinstance(self.endpoint.get("port"), int) and VNC_PORT_LOW <= int(self.endpoint["port"]) <= VNC_PORT_HIGH else None,
            },
            "label": self.label,
            "protocol": self.protocol,
            "protocol_status": "supported" if self.protocol == PROTOCOL_VNC else "not_implemented",
            "transport": self.transport,
            "transport_secure": self.transport == TRANSPORT_TLS,
            "unencrypted_approved": self.unencrypted_approved,
            "protected_path_ack": self.protected_path_ack,
            "private_address_ack": self.private_address_ack,
            "state": self.state,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "connected_at": self.connected_at,
            "disconnected_at": self.disconnected_at,
            "closed_at": self.closed_at,
            "last_activity": self.last_activity_at,
            "failure_reason": self.failure_reason,
            "disconnect_reason": self.disconnect_reason,
            "reconnect_attempts": self.reconnect_attempts,
            "watch_requested": self.watch_requested,
            "watch_ready": self.watch_ready,
            "client_library": self.client_library,
            "bytes_in": bridge["upstream_bytes"],
            "bytes_out": bridge["client_bytes"],
            "uptime_seconds": bridge["seconds"] if self.state == STATE_CONNECTED else 0,
        }


class RemoteDesktopManager:
    """Owns authorized remote-desktop sessions, tickets, bridges, and cleanup."""

    def __init__(
        self,
        store: Any,
        *,
        max_sessions: int | None = None,
        idle_seconds: int | None = None,
        connect_timeout: float = 8.0,
        probe_timeout: float = 6.0,
        watch_interval: float = 15.0,
        watch_deadline_seconds: int = 1800,
        audit: Callable[[str, dict[str, Any]], Any] | None = None,
        log: Callable[[str], None] | None = None,
        ca_file: str | None = None,
    ):
        self.store = store
        # Precedence: explicit argument, environment override, operator setting,
        # compiled default. Concurrency and idle limits are always bounded.
        if max_sessions is not None:
            self.max_sessions = max(1, min(int(max_sessions), 16))
        elif os.environ.get("VORTEX_REMOTE_MAX_SESSIONS"):
            self.max_sessions = self._env_int("VORTEX_REMOTE_MAX_SESSIONS", 4, 1, 16)
        else:
            self.max_sessions = self._setting_int("remote_desktop_max_sessions", 4, 1, 16)
        if idle_seconds is not None:
            self.idle_seconds = max(30, min(int(idle_seconds), 86400))
        elif os.environ.get("VORTEX_REMOTE_IDLE_SECONDS"):
            self.idle_seconds = self._env_int("VORTEX_REMOTE_IDLE_SECONDS", 900, 30, 86400)
        else:
            self.idle_seconds = self._setting_int("remote_desktop_idle_seconds", 900, 30, 86400)
        self.connect_timeout = connect_timeout
        self.probe_timeout = probe_timeout
        self.watch_interval = watch_interval
        self.watch_deadline_seconds = watch_deadline_seconds
        self.audit = audit
        self.log = log or (lambda _message: None)
        self.ca_file = ca_file or os.environ.get("VORTEX_REMOTE_CA_FILE") or None
        self.tickets = TicketStore()
        self.sessions: dict[str, RemoteSession] = {}
        self.history: list[dict[str, Any]] = []
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._reaper = threading.Thread(target=self._maintain, name="vortex-remote-reaper", daemon=True)
        self._reaper.start()

    @staticmethod
    def _env_int(name: str, default: int, low: int, high: int) -> int:
        raw = os.environ.get(name, str(default))
        try:
            if isinstance(raw, bool) or not str(raw).lstrip("-").isdigit():
                return default
            return max(low, min(int(raw), high))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _setting_int(key: str, default: int, low: int, high: int) -> int:
        try:
            try:
                from .config import load_settings
            except ImportError:
                from config import load_settings  # type: ignore
            value = load_settings().get(key, default)
            if isinstance(value, bool) or not isinstance(value, int):
                return default
            return max(low, min(int(value), high))
        except Exception:
            return default

    # ---- introspection ----

    def allow_unencrypted(self) -> bool:
        try:
            try:
                from .config import load_settings
            except ImportError:
                from config import load_settings  # type: ignore
            return bool(load_settings().get("remote_desktop_allow_unencrypted", False))
        except Exception:
            return False

    def capabilities(self) -> dict[str, Any]:
        client = _load_backend_module()
        return {
            "protocols": [dict(item) for item in PROTOCOL_MATRIX],
            "bridge": {
                "implementation": "python-stdlib-websocket-bridge",
                "websocket": "RFC 6455 (binary frames, masked client frames enforced, bounded payloads)",
                "subprotocol": VNC_WS_SUBPROTOCOL,
                "dial_policy": "single validated host:port, no redirects, no arbitrary proxying",
                "port_range": [VNC_PORT_LOW, VNC_PORT_HIGH],
                "tls": "verified against the system trust store; certificate errors are never ignored",
            },
            "limits": {
                "max_sessions": self.max_sessions,
                "idle_timeout_seconds": self.idle_seconds,
                "ticket_ttl_seconds": self.tickets.ttl,
                "ticket_max_per_session": self.tickets.max_per_session,
                "watch_deadline_seconds": self.watch_deadline_seconds,
            },
            "settings": {
                "remote_desktop_allow_unencrypted": self.allow_unencrypted(),
                "remote_desktop_open_when_ready_default": False,
                "clipboard_sync": False,
                "file_transfer": False,
                "audio_redirection": False,
                "shared_folders": False,
                "session_recording": False,
            },
            "dependencies": self.dependency_items(),
            "sessions": self.list(),
            "client_library": {
                "bundled": "noVNC (MPL-2.0), reported per session by the connecting client",
                "server_side": "no external package: the WebSocket-to-RFB bridge is part of the sidecar",
            },
            "python": client,
        }

    @staticmethod
    def dependency_items() -> list[dict[str, Any]]:
        """Real dependency state for the operator interface (never guessed)."""
        items: list[dict[str, Any]] = []
        # The bridge is stdlib-only; the honest "installed" evidence is the
        # interpreter and the TLS trust store it will use.
        try:
            import sys
            items.append({
                "id": "remote-desktop:bridge",
                "kind": "capability",
                "name": "websocket-rfb-bridge",
                "title": "WebSocket to RFB bridge (sidecar)",
                "state": "installed",
                "installed": True,
                "required": True,
                "version": f"python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                "purpose": "Dials the approved endpoint and pipes RFB bytes to the authenticated window.",
                "source": "Vortex Terminal (in-tree, MIT)",
                "license": "MIT",
                "installation": "No installation required; part of the sidecar.",
            })
        except Exception:  # pragma: no cover
            pass
        tls_state = "installed"
        tls_detail = "system trust store"
        try:
            context = ssl.create_default_context()
            paths = ssl.get_default_verify_paths()
            if not context.get_ca_certs() and not paths.cafile and not os.path.isdir(paths.capath or ""):
                tls_state, tls_detail = "unavailable", "no system CA store found"
        except Exception as exc:  # pragma: no cover
            tls_state, tls_detail = "unavailable", redact(str(exc))
        items.append({
            "id": "remote-desktop:tls",
            "kind": "capability",
            "name": "verified-tls-transport",
            "title": "Verified TLS transport",
            "state": tls_state,
            "installed": tls_state == "installed",
            "required": False,
            "version": ssl.OPENSSL_VERSION if tls_state == "installed" else None,
            "purpose": "Encrypted remote-desktop transports with mandatory certificate verification.",
            "source": "Python standard library (OpenSSL)",
            "license": "PSF-2.0 / Apache-2.0 (OpenSSL)",
            "installation": f"Provided by the host Python installation ({tls_detail}).",
        })
        try:
            try:
                from . import dependencies as deps_module
            except ImportError:
                import dependencies as deps_module  # type: ignore
            novnc = getattr(deps_module, "novnc_status", None)
            if callable(novnc):
                items.append(novnc())
        except Exception:  # pragma: no cover
            pass
        items.append({
            "id": "remote-desktop:rdp",
            "kind": "capability",
            "name": "rdp-client",
            "title": "RDP client",
            "state": "not-implemented",
            "installed": False,
            "required": False,
            "version": None,
            "purpose": "RDP desktops inside the Vortex window manager.",
            "source": "Not integrated",
            "license": "n/a",
            "installation": (
                "Vortex Terminal does not implement RDP. Installing FreeRDP host tools does not change "
                "this: there is no reviewer-approved RDP gateway integration in the product."
            ),
        })
        return items

    # ---- engagement-bound operations ----

    def shell_evidence(self, host: str) -> dict[str, Any]:
        """Whether an authenticated remote *shell* was observed for this host.

        Shell access is not desktop access. This only decides which guidance the
        operator sees; it never grants anything and never claims a graphical
        session exists.
        """
        needle = host.lower()
        try:
            history = self.store.list_history(200) or []
        except Exception:
            return {"observed": False, "detail": "operation history unavailable"}
        for operation in history:
            try:
                targets = [str(item).lower() for item in (operation.get("scope") or {}).get("targets", [])]
            except AttributeError:
                targets = []
            for spec in operation.get("commands") or []:
                adapter = str(spec.get("adapter_id") or "")
                if adapter != "linux.ssh.connection":
                    continue
                blob = " ".join([*(targets or []), str(spec.get("display") or ""), " ".join(spec.get("argv") or [])]).lower()
                if needle and needle in blob:
                    return {
                        "observed": True,
                        "detail": f"an SSH connection operation was recorded for {host}",
                        "operation_id": operation.get("id"),
                    }
        return {"observed": False, "detail": "no SSH connection operation recorded for this host"}

    def guidance(self, host: str, probe_report: dict[str, Any]) -> str:
        if probe_report.get("available"):
            return (
                "A compatible RFB/VNC service answered. Authentication happens in the remote desktop window "
                "and is performed end to end by the client."
            )
        if self.shell_evidence(host).get("observed"):
            return "Remote shell access is available, but no compatible graphical session has been verified."
        return (
            "No compatible graphical session has been verified on this endpoint. Configure a VNC display "
            "(port 5900-5999) or approve a tunnel into that range; Vortex will not present a placeholder desktop."
        )

    def probe(self, *, engagement_id: str, host: str, protocol: str, display: Any = None, port: Any = None,
              transport: str = TRANSPORT_TLS, deep: bool = False, private_address_ack: bool = False) -> dict[str, Any]:
        if protocol != PROTOCOL_VNC:
            raise RemoteDesktopError(
                "protocol_not_implemented",
                f"{protocol.upper()} is not implemented in Vortex Terminal. Only VNC is available today.",
                501,
            )
        transport = self._validated_transport(transport, unencrypted_approved=False)
        scope = EngagementScope.load(self.store, engagement_id)
        parsed_host, parsed_port = parse_endpoint_target(host)
        target_port = resolve_vnc_port(display, parsed_port if parsed_port is not None else port)
        endpoint = authorize_endpoint(scope, parsed_host, target_port, private_address_ack=private_address_ack)
        self._audit("remote_desktop_probe", {
            "engagement_id": scope.id,
            "host": endpoint["host"],
            "port": endpoint["port"],
            "transport": transport,
            "deep": bool(deep),
            "matched_target": endpoint["matched_target"],
        })
        try:
            report = probe_endpoint(
                address=endpoint["address"], port=endpoint["port"], host=endpoint["host"],
                transport=transport, timeout=self.probe_timeout, deep=deep, ca_file=self.ca_file,
            )
        except RemoteDesktopError as exc:
            evidence = self.shell_evidence(endpoint["host"])
            return {
                "available": False,
                "protocol": protocol,
                "endpoint": {"host": endpoint["host"], "port": endpoint["port"], "address": endpoint["address"]},
                "error": {"code": exc.code, "message": exc.message},
                "deep_probe": bool(deep),
                "engagement_id": scope.id,
                "scope": scope.describe(),
                "shell_evidence": evidence,
                "guidance": self.guidance(endpoint["host"], {}),
            }
        report["engagement_id"] = scope.id
        report["scope"] = scope.describe()
        report["shell_evidence"] = self.shell_evidence(endpoint["host"])
        report["guidance"] = self.guidance(endpoint["host"], report)
        return report

    def create(
        self,
        *,
        engagement_id: str,
        host: str,
        protocol: str = PROTOCOL_VNC,
        display: Any = None,
        port: Any = None,
        transport: str = TRANSPORT_TLS,
        label: str = "",
        owner: str = "",
        client_library: str = "",
    ) -> dict[str, Any]:
        if protocol != PROTOCOL_VNC:
            raise RemoteDesktopError(
                "protocol_not_implemented",
                f"{protocol.upper()} is not implemented in Vortex Terminal. Only VNC is available today.",
                501,
            )
        transport = self._validated_transport(transport, unencrypted_approved=False)
        scope = EngagementScope.load(self.store, engagement_id)
        parsed_host, parsed_port = parse_endpoint_target(host)
        target_port = resolve_vnc_port(display, parsed_port if parsed_port is not None else port)
        with self.lock:
            active = [item for item in self.sessions.values() if item.state != STATE_CLOSED]
            if len(active) >= self.max_sessions:
                raise RemoteDesktopError(
                    "session_limit",
                    f"The configured remote-desktop limit ({self.max_sessions}) is reached. "
                    "Close a session or raise the limit consciously.",
                    429,
                )
        endpoint = authorize_endpoint(scope, parsed_host, target_port)
        session = RemoteSession(
            secrets.token_hex(12),
            engagement=scope.describe(),
            endpoint={**endpoint, "identity": f"{endpoint['host']}:{endpoint['port']}"},
            protocol=protocol,
            transport=transport,
            label=redact(label or f"{endpoint['host']}:{endpoint['port']}")[:MAX_LABEL_LENGTH],
            owner=owner,
        )
        session.client_library = redact(client_library)[:64]
        with self.lock:
            self.sessions[session.id] = session
        self._audit("remote_desktop_session_created", {
            "session_id": session.id,
            "engagement_id": scope.id,
            "host": endpoint["host"],
            "port": endpoint["port"],
            "address": endpoint["address"],
            "transport": transport,
            "matched_target": endpoint["matched_target"],
        })
        return session.public()

    def approve(
        self,
        session_id: str,
        *,
        confirm: bool,
        unencrypted_approved: bool = False,
        protected_path_ack: bool = False,
        private_address_ack: bool = False,
        watch: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            raise RemoteDesktopError("confirmation_required", "Explicit operator approval is required before connecting.", 400)
        session = self._require(session_id)
        if session.state in {STATE_CLOSED, STATE_FAILED}:
            raise RemoteDesktopError("session_closed", "This session is closed. Create a new approved session.", 409)
        if session.transport == TRANSPORT_UNENCRYPTED:
            if not self.allow_unencrypted():
                raise RemoteDesktopError(
                    "unencrypted_disabled",
                    "This deployment does not permit unencrypted remote-desktop transports. "
                    "Enable it consciously in Settings, or connect through a TLS-capable endpoint.",
                    403,
                )
            if not (unencrypted_approved and protected_path_ack):
                raise RemoteDesktopError(
                    "protected_path_required",
                    "Unencrypted VNC needs an acknowledged protected connection path (for example an approved "
                    "VPN or SSH tunnel) plus explicit approval for this session.",
                    403,
                )
        scope = EngagementScope.load(self.store, session.engagement.get("id") or session.engagement.get("engagement_id"))
        # Re-resolve and re-authorize: DNS answers and scope can change between
        # creation and connection.
        endpoint = authorize_endpoint(
            scope, session.endpoint["host"], int(session.endpoint["port"]), private_address_ack=private_address_ack,
        )
        with self.lock:
            session.endpoint.update(endpoint)
            session.unencrypted_approved = bool(unencrypted_approved)
            session.protected_path_ack = bool(protected_path_ack)
            session.private_address_ack = bool(private_address_ack)
            session.approved_at = _now_iso()
            session.state = STATE_CREATED
            session.watch_requested = bool(watch)
            session.watch_deadline = time.monotonic() + self.watch_deadline_seconds if watch else 0.0
            session.watch_ready = False
        self._audit("remote_desktop_session_approved", {
            "session_id": session.id,
            "engagement_id": scope.id,
            "host": session.endpoint["host"],
            "port": session.endpoint["port"],
            "transport": session.transport,
            "unencrypted_approved": bool(unencrypted_approved),
            "protected_path_ack": bool(protected_path_ack),
            "watch_requested": bool(watch),
        })
        return session.public()

    def issue_ticket(self, session_id: str, fingerprint: str) -> dict[str, Any]:
        session = self._require(session_id)
        if session.state in {STATE_AWAITING_APPROVAL, STATE_CLOSED, STATE_FAILED}:
            raise RemoteDesktopError(
                "session_not_approved",
                "Approve this session before requesting a connection ticket.",
                409,
            )
        ticket = self.tickets.issue(session.id, fingerprint)
        session.tickets += 1
        return {
            "ticket": ticket,
            "subprotocol": f"{VNC_WS_SUBPROTOCOL},{TICKET_PREFIX}{ticket}",
            "expires_in": self.tickets.ttl,
        }

    def begin_bridge(self, session_id: str, ticket: str, fingerprint: str, origin: str) -> dict[str, Any]:
        """Validate everything again, then dial. Returns connection parameters."""
        session = self._require(session_id)
        if session.state == STATE_CONNECTED:
            raise RemoteDesktopError("session_busy", "This session already has a live connection.", 409)
        if session.state in {STATE_AWAITING_APPROVAL, STATE_CLOSED}:
            raise RemoteDesktopError("session_not_approved", "This session is not approved for connection.", 409)
        self.tickets.consume(ticket, session_id, fingerprint)
        scope = EngagementScope.load(self.store, session.engagement.get("id") or session.engagement.get("engagement_id"))
        endpoint = authorize_endpoint(
            scope, session.endpoint["host"], int(session.endpoint["port"]),
            private_address_ack=session.private_address_ack,
        )
        with self.lock:
            session.endpoint.update(endpoint)
            session.state = STATE_CONNECTING
            session.epoch += 1
            session.bridge = None
            session.upstream = None
        epoch = session.epoch
        upstream: socket.socket | None = None
        try:
            upstream, details = _open_socket(
                endpoint["address"],
                int(endpoint["port"]),
                timeout=self.connect_timeout,
                transport=session.transport,
                server_hostname=endpoint["host"],
                ca_file=self.ca_file,
            )
        except RemoteDesktopError as exc:
            with self.lock:
                session.state = STATE_FAILED
                session.failure_reason = f"{exc.code}: {exc.message}"
            self._audit("remote_desktop_connect_failed", {
                "session_id": session.id, "code": exc.code, "reason": exc.message, "origin": origin,
            })
            raise
        with self.lock:
            session.upstream = upstream
            session.connected_at = _now_iso()
            session.disconnected_at = None
            session.failure_reason = ""
            session.disconnect_reason = ""
            session.state = STATE_CONNECTED
            session.last_activity = time.monotonic()
        self._audit("remote_desktop_connected", {
            "session_id": session.id,
            "engagement_id": scope.id,
            "host": endpoint["host"],
            "port": endpoint["port"],
            "address": endpoint["address"],
            "transport": session.transport,
            "tls_verified": bool(details.get("tls_verified")),
        })
        return {
            "session": session.public(),
            "upstream": upstream,
            "details": details,
            "idle_timeout": self.idle_seconds,
            "epoch": epoch,
        }

    def bind_bridge(self, session_id: str, bridge: RemoteBridge) -> None:
        with self.lock:
            session = self.sessions.get(session_id)
            if session is not None:
                session.bridge = bridge

    def mark_activity(self, session_id: str, kind: str = "traffic") -> dict[str, Any]:
        session = self._require(session_id)
        with self.lock:
            session.last_activity = time.monotonic()
            session.last_activity_at = _now_iso()
        if kind in {"input_begin", "input_end"}:
            # Only the fact that keyboard focus moved is recorded: never keys.
            self._audit(f"remote_desktop_{kind}", {"session_id": session.id, "host": session.endpoint.get("host")})
        return {"session": session.public()}

    def note_disconnect(self, session_id: str, reason: str, *, unexpected: bool = False,
                        epoch: int | None = None) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return
        clean = redact(reason)[:400]
        with self.lock:
            if session.state not in {STATE_CONNECTED, STATE_CONNECTING, STATE_RECONNECTING}:
                return  # already disconnected/closed: never double-count or double-audit
            if epoch is not None and epoch != session.epoch:
                # Teardown for a superseded stream: the connection it belonged to
                # is already gone, so it must not touch the live generation.
                return
            session.bridge = None
            session.upstream = None
            session.disconnected_at = _now_iso()
            session.disconnect_reason = clean
            if unexpected:
                # An outage is not a clean disconnect; say so in the record.
                session.failure_reason = clean
            session.state = STATE_DISCONNECTED
        self._audit("remote_desktop_disconnected",
                    {"session_id": session.id, "reason": clean, "unexpected": bool(unexpected)})

    def disconnect(self, session_id: str, reason: str = "operator_disconnected") -> dict[str, Any]:
        session = self._require(session_id)
        bridge = session.bridge
        if bridge is not None:
            bridge.stop(reason)
        with self.lock:
            session.bridge = None
            session.upstream = None
            session.disconnected_at = _now_iso()
            session.disconnect_reason = redact(reason)[:400]
            if session.state in {STATE_CONNECTED, STATE_CONNECTING}:
                session.state = STATE_DISCONNECTED
        self.tickets.revoke_session(session.id)
        self._audit("remote_desktop_disconnected", {"session_id": session.id, "reason": redact(reason)[:200]})
        return session.public()

    def request_reconnect(self, session_id: str) -> dict[str, Any]:
        session = self._require(session_id)
        if session.state == STATE_CLOSED:
            raise RemoteDesktopError("session_closed", "This session is closed. Create a new approved session.", 409)
        if session.state == STATE_AWAITING_APPROVAL:
            raise RemoteDesktopError("session_not_approved", "Approve this session before reconnecting.", 409)
        if session.state == STATE_CONNECTED:
            raise RemoteDesktopError("session_busy", "This session is already connected.", 409)
        scope = EngagementScope.load(self.store, session.engagement.get("id") or session.engagement.get("engagement_id"))  # revalidate authorization
        endpoint = authorize_endpoint(
            scope, session.endpoint["host"], int(session.endpoint["port"]),
            private_address_ack=session.private_address_ack,
        )
        with self.lock:
            session.endpoint.update(endpoint)
            session.reconnect_attempts += 1
            session.state = STATE_RECONNECTING
            session.failure_reason = ""
        self._audit("remote_desktop_reconnect_requested", {
            "session_id": session.id, "attempt": session.reconnect_attempts, "host": endpoint["host"],
        })
        return session.public()

    def close(self, session_id: str, reason: str = "operator_closed") -> dict[str, Any]:
        session = self._require(session_id)
        if session.bridge is not None:
            session.bridge.stop(reason)
        upstream = session.upstream
        if upstream is not None:
            try:
                upstream.close()
            except OSError:
                pass
        self.tickets.revoke_session(session.id)
        cleaned = redact(reason)[:400]
        with self.lock:
            session.bridge = None
            session.upstream = None
            session.state = STATE_CLOSED
            session.closed_at = _now_iso()
            session.disconnect_reason = session.disconnect_reason or cleaned
            # The retained record keeps non-secret identity; authorization is
            # gone because the session no longer exists in the live registry.
            self.sessions.pop(session.id, None)
            self.history.insert(0, session.public())
            del self.history[20:]
        self._audit("remote_desktop_closed", {"session_id": session.id, "reason": cleaned})
        return session.public()

    def close_all(self, reason: str = "operator_stop_all") -> dict[str, Any]:
        with self.lock:
            ids = list(self.sessions.keys())
        closed = 0
        for session_id in ids:
            try:
                self.close(session_id, reason)
                closed += 1
            except RemoteDesktopError:
                continue
        self._audit("remote_desktop_stop_all", {"sessions_closed": closed, "reason": reason})
        return {"remote_sessions_closed": closed, "remote_sessions_remaining": len(self.sessions)}

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            sessions = [item.public() for item in self.sessions.values()]
            history = [dict(item) for item in self.history[:8]]
        sessions.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        for item in sessions:
            item["retained"] = False
        for item in history:
            item["retained"] = True
        return sessions + history

    def info(self, session_id: str) -> dict[str, Any] | None:
        session = self.sessions.get(session_id)
        if session is not None:
            return session.public()
        for item in self.history:
            if item.get("id") == session_id:
                return dict(item, retained=True)
        return None

    def shutdown(self) -> None:
        self._stop.set()
        try:
            self.close_all("sidecar_shutdown")
        finally:
            if self._reaper is not threading.current_thread():
                self._reaper.join(timeout=2.0)

    # ---- internals ----

    def _validated_transport(self, transport: Any, *, unencrypted_approved: bool) -> str:
        value = str(transport or TRANSPORT_TLS).strip().lower()
        if value not in {TRANSPORT_TLS, TRANSPORT_UNENCRYPTED}:
            raise RemoteDesktopError("invalid_transport", "Transport must be 'tls' or 'unencrypted'.", 400)
        return value

    def _require(self, session_id: Any) -> RemoteSession:
        if not isinstance(session_id, str) or not re.fullmatch(r"[0-9a-f]{24}", session_id or ""):
            raise RemoteDesktopError("session_not_found", "Unknown remote-desktop session.", 404)
        with self.lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise RemoteDesktopError("session_not_found", "Unknown or already closed remote-desktop session.", 404)
        return session

    def _audit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.audit is None:
            return
        try:
            self.audit(event_type, payload)
        except Exception as exc:  # pragma: no cover - auditing must never break a session
            self.log(f"audit failure ({event_type}): {redact(exc)}")

    def _maintain(self) -> None:
        """Idle reaping, authorization revocation, and watched-endpoint polling."""
        while not self._stop.wait(2.0):
            try:
                self._sweep()
            except Exception as exc:  # pragma: no cover - the loop must survive
                self.log(f"maintenance error: {redact(exc)}")

    def _sweep(self) -> None:
        now = time.monotonic()
        with self.lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            if session.state == STATE_CLOSED:
                continue
            if session.state == STATE_CONNECTED:
                activity = session.last_activity
                if session.bridge is not None:
                    # Passive viewing is still activity: the bridge tracks traffic.
                    activity = max(activity, session.bridge.last_activity)
                if (now - activity) > self.idle_seconds:
                    self._audit("remote_desktop_idle_timeout", {"session_id": session.id, "idle_seconds": self.idle_seconds})
                    try:
                        self.close(session.id, "idle_timeout")
                    except RemoteDesktopError:
                        pass
                    continue
                try:
                    EngagementScope.load(self.store, session.engagement.get("id") or session.engagement.get("engagement_id"))
                except RemoteDesktopError as exc:
                    # Expired/closed engagement: revoke the live connection now.
                    session.failure_reason = f"{exc.code}: {exc.message}"
                    self._audit("remote_desktop_authorization_revoked", {"session_id": session.id, "code": exc.code})
                    try:
                        self.close(session.id, f"authorization_revoked:{exc.code}")
                    except RemoteDesktopError:
                        pass
                continue
            if session.watch_requested and not session.watch_ready:
                if now > session.watch_deadline:
                    session.watch_requested = False
                    session.failure_reason = "watch_deadline: no compatible graphical session became available in time"
                    self._audit("remote_desktop_watch_expired", {"session_id": session.id})
                    continue
                if now - session.last_activity < self.watch_interval:
                    continue
                session.last_activity = now
                try:
                    report = probe_endpoint(
                        address=session.endpoint["address"],
                        port=int(session.endpoint["port"]),
                        host=session.endpoint["host"],
                        transport=session.transport,
                        timeout=min(self.probe_timeout, 5.0),
                        ca_file=self.ca_file,
                    )
                except RemoteDesktopError:
                    continue
                if report.get("available"):
                    session.watch_ready = True
                    session.watch_requested = False
                    self._audit("remote_desktop_watch_ready", {
                        "session_id": session.id,
                        "host": session.endpoint["host"],
                        "protocol_version": report.get("protocol_version"),
                    })
                continue
            if session.state in {STATE_CREATED, STATE_DISCONNECTED} and not session.watch_requested:
                # Unattended sessions do not linger forever.
                if (now - session.last_activity) > max(self.idle_seconds, 300):
                    try:
                        self.close(session.id, "stale_unused_session")
                    except RemoteDesktopError:
                        pass


def _load_backend_module() -> dict[str, Any]:
    try:
        import sys
        return {"version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", "implementation": sys.implementation.name}
    except Exception:  # pragma: no cover
        return {}


# --------------------------------------------------------------------------
# HTTP helpers used by the sidecar routes
# --------------------------------------------------------------------------


def subprotocol_ticket(header_value: str, session_id: str) -> str:
    """Extract the ticket from ``Sec-WebSocket-Protocol``.

    Tickets travel in the handshake header (never the URL) so they cannot leak
    through access logs, referrers, or browser history.
    """
    offered = [item.strip() for item in (header_value or "").split(",") if item.strip()]
    for item in offered:
        if item.startswith(TICKET_PREFIX):
            ticket = item[len(TICKET_PREFIX):]
            if re.fullmatch(r"[A-Za-z0-9_-]{16,128}", ticket):
                return ticket
    raise RemoteDesktopError("ticket_missing", "The WebSocket handshake did not carry a connection ticket.", 403)


def negotiate_subprotocol(header_value: str) -> str | None:
    offered = [item.strip() for item in (header_value or "").split(",") if item.strip()]
    if VNC_WS_SUBPROTOCOL in offered:
        return VNC_WS_SUBPROTOCOL
    return None
