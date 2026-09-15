"""Minimal real RFB (VNC) client that speaks through the Vortex WebSocket bridge.

This is *test tooling*: an independent implementation of the client side of the
protocol so acceptance runs do not depend on the browser. It performs the real
RFB handshake against a real VNC server through the real bridge, decodes Raw
framebuffer updates, and can inject real keyboard and pointer events.

No framebuffer is ever fabricated: every pixel the assertions look at came off
the wire from the remote desktop server.
"""
from __future__ import annotations

import base64
import os
import socket
import struct
import time

# ---------------------------------------------------------------- WebSocket


class WebSocketFrameError(RuntimeError):
    pass


class WebSocketChannel:
    """RFC 6455 client side of the sidecar bridge (binary frames only)."""

    def __init__(self, sock: socket.socket, handshake: bytes):
        self.sock = sock
        self.handshake = handshake
        self._buffer = bytearray()
        self._closed = False
        self.close_code: int | None = None
        self.close_reason = ""

    # ---- handshake ----

    @classmethod
    def connect(
        cls,
        host: str,
        port: int,
        path: str,
        *,
        subprotocols: list[str] | None = None,
        token: str | None = None,
        cookie: str | None = None,
        origin: str | None = None,
        timeout: float = 15.0,
    ) -> "WebSocketChannel":
        sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        if origin is None:
            origin = f"http://{host}:{port}"
        lines = [
            f"GET {path} HTTP/1.1",
            f"Host: {host}:{port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
            f"Origin: {origin}",
        ]
        if subprotocols:
            lines.append("Sec-WebSocket-Protocol: " + ", ".join(subprotocols))
        if token:
            lines.append(f"X-Vortex-Token: {token}")
        if cookie:
            lines.append(f"Cookie: {cookie}")
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        handshake = cls._read_headers(sock)
        status = cls._status(handshake)
        if status != 101:
            body = cls._read_body(sock, handshake)
            sock.close()
            raise WebSocketFrameError(f"bridge refused the upgrade: {status} {body[:400]!r}")
        if b"Sec-WebSocket-Accept:" not in handshake:
            sock.close()
            raise WebSocketFrameError("bridge did not answer Sec-WebSocket-Accept")
        return cls(sock, handshake)

    @staticmethod
    def _status(handshake: bytes) -> int:
        try:
            return int(handshake.split(b"\r\n", 1)[0].split(b" ")[1])
        except (IndexError, ValueError):
            return 0

    @staticmethod
    def _read_headers(sock: socket.socket) -> bytes:
        buffer = bytearray()
        while b"\r\n\r\n" not in buffer:
            chunk = sock.recv(1)
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > 32 * 1024:
                break
        return bytes(buffer)

    @staticmethod
    def _read_body(sock: socket.socket, handshake: bytes) -> bytes:
        head, _, tail = handshake.partition(b"\r\n\r\n")
        length = 0
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1].strip())
        body = bytearray(tail)
        sock.settimeout(5)
        while len(body) < length:
            chunk = sock.recv(length - len(body))
            if not chunk:
                break
            body.extend(chunk)
        return bytes(body)

    # ---- framing ----

    def _read_exactly(self, size: int, timeout: float) -> bytes:
        self.sock.settimeout(timeout)
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self.sock.recv(size - len(chunks))
            if not chunk:
                raise ConnectionError("bridge closed the connection")
            chunks.extend(chunk)
        return bytes(chunks)

    def _next_frame(self, timeout: float) -> tuple[int, bytes]:
        header = self._read_exactly(2, timeout)
        opcode = header[0] & 0x0F
        masked = bool(header[1] & 0x80)
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read_exactly(2, timeout))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read_exactly(8, timeout))[0]
        mask = self._read_exactly(4, timeout) if masked else b""
        payload = self._read_exactly(length, timeout) if length else b""
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def read(self, size: int, timeout: float = 15.0) -> bytes:
        """Read exactly ``size`` RFB bytes, transparently answering pings."""
        deadline = time.monotonic() + timeout
        while len(self._buffer) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"bridge did not deliver {size} bytes in time")
            opcode, payload = self._next_frame(remaining)
            if opcode == 0x2:
                self._buffer.extend(payload)
            elif opcode == 0x9:
                self.send(payload, opcode=0xA)
            elif opcode == 0xA:
                continue
            elif opcode == 0x8:
                self._closed = True
                if len(payload) >= 2:
                    self.close_code = struct.unpack(">H", payload[:2])[0]
                    self.close_reason = payload[2:].decode("utf-8", "replace")
                raise ConnectionError(f"bridge sent close: {self.close_code} {self.close_reason}")
            else:  # pragma: no cover - text frames are refused by the bridge
                raise WebSocketFrameError(f"unexpected frame opcode {opcode}")
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data

    def send(self, payload: bytes, opcode: int = 0x2) -> None:
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

    def close(self, code: int = 1000, reason: str = "test finished") -> None:
        try:
            self.send(struct.pack(">H", code) + reason.encode()[:120], opcode=0x8)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def is_closed(self, timeout: float = 10.0) -> bool:
        """True when the bridge ends the stream (close frame or EOF)."""
        if self._closed:
            return True
        try:
            self.sock.settimeout(timeout)
            chunk = self.sock.recv(4096)
            if not chunk:
                self._closed = True
                return True
            self._buffer.extend(chunk)
            return False
        except (socket.timeout, TimeoutError):
            return False
        except OSError:
            self._closed = True
            return True


# ---------------------------------------------------------------- RFB client


class RfbError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


SECURITY_NONE = 1
SECURITY_VNC_AUTH = 2
ENCODING_RAW = 0
ENCODING_DESKTOP_SIZE = -223


class RfbClient:
    """Client side of RFB 3.3-3.8, enough to prove rendering and real input."""

    def __init__(self, channel: WebSocketChannel):
        self.channel = channel
        self.version = ""
        self.security_type = 0
        self.width = 0
        self.height = 0
        self.name = ""
        self.framebuffer = bytearray()
        self.bytes_received = 0
        self.updates = 0

    # ---- helpers ----

    def _read(self, size: int, timeout: float = 15.0) -> bytes:
        data = self.channel.read(size, timeout)
        self.bytes_received += len(data)
        return data

    def _read_u8(self, timeout: float = 15.0) -> int:
        return self._read(1, timeout)[0]

    def _read_u16(self, timeout: float = 15.0) -> int:
        return struct.unpack(">H", self._read(2, timeout))[0]

    def _read_u32(self, timeout: float = 15.0) -> int:
        return struct.unpack(">I", self._read(4, timeout))[0]

    # ---- handshake ----

    def handshake(self, *, password: bytes | None = None, bogus_auth: bool = False, allow_vnc_auth: bool = True) -> None:
        banner = self._read(12)
        if not banner.startswith(b"RFB "):
            raise RfbError(f"not an RFB server banner: {banner!r}")
        version = banner[4:11].decode("ascii", "replace").strip()
        # Real clients answer with the lower of the two versions. Qt's VNC
        # platform plugin only implements 3.3, so honour what the server offers.
        offered = version if version in {"003.003", "003.007", "003.008"} else "003.008"
        self.version = offered
        self.channel.send(b"RFB " + offered.encode() + b"\n")

        if offered == "003.003":
            self.security_type = self._read_u32()
        else:
            count = self._read_u8()
            if count == 0:
                reason_len = self._read_u32()
                raise RfbError("server refused the connection: " + self._read(reason_len).decode("utf-8", "replace"))
            types = list(self._read(count))
            if SECURITY_NONE in types:
                self.security_type = SECURITY_NONE
            elif SECURITY_VNC_AUTH in types and allow_vnc_auth:
                self.security_type = SECURITY_VNC_AUTH
            else:
                raise RfbError(f"no supported security type offered: {types}")
            self.channel.send(bytes([self.security_type]))

        if self.security_type == SECURITY_VNC_AUTH:
            challenge = self._read(16)
            if bogus_auth:
                response = os.urandom(16)  # deliberately wrong: proves the server checks credentials
            else:
                if password is None:
                    raise RfbError("server requires VNC authentication but no password was supplied")
                response = vnc_auth_response(challenge, password)
            self.channel.send(response)
        elif self.security_type != SECURITY_NONE:
            raise RfbError(f"unsupported security type {self.security_type}")

        if offered != "003.003" or self.security_type == SECURITY_VNC_AUTH:
            status = self._read_u32()
            if status != 0:
                reason = ""
                try:
                    length = self._read_u32(timeout=3)
                    reason = self._read(length, timeout=3).decode("utf-8", "replace")
                except (TimeoutError, ConnectionError):
                    pass
                raise RfbError(f"security handshake failed (status {status}) {reason}".strip(), status=status)

        self.channel.send(b"\x01")  # ClientInit: shared
        self.width = self._read_u16()
        self.height = self._read_u16()
        self._read(16)  # server pixel format (we override it below)
        name_length = self._read_u32()
        self.name = self._read(name_length).decode("utf-8", "replace") if name_length else ""
        self.framebuffer = bytearray(self.width * self.height * 4)
        self.set_pixel_format()
        self.set_encodings([ENCODING_RAW, ENCODING_DESKTOP_SIZE])

    def set_pixel_format(self) -> None:
        # 32bpp, depth 24, little-endian, true colour, max 255, shifts 16/8/0 —
        # every mainstream VNC server supports this exact format.
        body = struct.pack(
            ">BBBBHHHBBBxxx",
            32, 24, 0, 1, 255, 255, 255, 16, 8, 0,
        )
        self.channel.send(b"\x00\x00\x00\x00" + body)

    def set_encodings(self, encodings: list[int]) -> None:
        body = struct.pack(">H", len(encodings)) + b"".join(struct.pack(">i", item) for item in encodings)
        # SetEncodings: type(1) + padding(1) + count(2) + encodings(4 each)
        self.channel.send(b"\x02\x00" + body)

    def request_full_update(self) -> None:
        """Full (non-incremental) refresh.

        Several real servers - Qt's VNC platform plugin among them - only paint
        dirty regions for incremental requests, so a client that never asks for a
        full update on a static screen receives nothing at all.
        """
        self.request_update(incremental=False)

    def request_update(self, *, incremental: bool = True, x: int = 0, y: int = 0, width: int | None = None, height: int | None = None) -> None:
        body = struct.pack(
            ">BHHHH",
            1 if incremental else 0, x, y,
            width if width is not None else self.width,
            height if height is not None else self.height,
        )
        self.channel.send(b"\x03" + body)

    # ---- input ----

    def key(self, keysym: int, down: bool) -> None:
        self.channel.send(struct.pack(">BBxxI", 4, 1 if down else 0, keysym))

    def tap(self, keysym: int, hold: float = 0.05) -> None:
        self.key(keysym, True)
        time.sleep(hold)
        self.key(keysym, False)

    def type_text(self, text: str, hold: float = 0.03) -> None:
        for char in text:
            self.tap(ord(char), hold)

    def pointer(self, x: int, y: int, mask: int = 0) -> None:
        self.channel.send(struct.pack(">BBHH", 5, mask, x, y))

    def click(self, x: int, y: int) -> None:
        self.pointer(x, y, 0)
        time.sleep(0.05)
        self.pointer(x, y, 1)
        time.sleep(0.08)
        self.pointer(x, y, 0)

    def ctrl_alt_del(self) -> None:
        for keysym in (0xFFE3, 0xFFE9, 0xFFFF):
            self.key(keysym, True)
        for keysym in (0xFFFF, 0xFFE9, 0xFFE3):
            self.key(keysym, False)

    # ---- messages ----

    def read_message(self, timeout: float = 15.0) -> tuple[str, dict]:
        message_type = self._read_u8(timeout)
        if message_type == 0:  # FramebufferUpdate
            self._read(1)  # padding
            rect_count = self._read_u16()
            rects: list[dict] = []
            for _ in range(rect_count):
                x = self._read_u16()
                y = self._read_u16()
                width = self._read_u16()
                height = self._read_u16()
                encoding = struct.unpack(">i", self._read(4))[0]
                rects.append({"x": x, "y": y, "width": width, "height": height, "encoding": encoding})
                if encoding == ENCODING_DESKTOP_SIZE:
                    self.width, self.height = width, height
                    self.framebuffer = bytearray(width * height * 4)
                    continue
                if encoding == ENCODING_RAW:
                    payload = self._read(width * height * 4)
                    if (width, height) != (self.width, self.height) and not self.framebuffer:
                        self.width, self.height = width, height
                        self.framebuffer = bytearray(width * height * 4)
                    for row in range(height):
                        target_y = y + row
                        if target_y >= self.height or x + width > self.width:
                            continue
                        start = target_y * self.width * 4 + x * 4
                        self.framebuffer[start:start + width * 4] = payload[row * width * 4:(row + 1) * width * 4]
                    continue
                raise RfbError(f"server used unsupported encoding {encoding}")
            self.updates += 1
            return "update", {"rects": rects, "width": self.width, "height": self.height}
        if message_type == 2:  # Bell
            return "bell", {}
        if message_type == 3:  # ServerCutText
            self._read(3)
            length = self._read_u32()
            return "clipboard", {"text": self._read(length).decode("latin-1")}
        raise RfbError(f"unsupported server message type {message_type}")

    def update_until(self, predicate, *, timeout: float = 20.0, poll: bool = True, full_first: bool = False) -> bool:
        """Request updates until ``predicate(self)`` holds or the deadline passes."""
        deadline = time.monotonic() + timeout
        first = True
        while time.monotonic() < deadline:
            if poll:
                self.request_update(incremental=not (first and full_first))
            first = False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                self.read_message(timeout=min(remaining, 5.0))
            except TimeoutError:
                continue
            if predicate(self):
                return True
        return False

    # ---- framebuffer inspection (real pixels from the wire) ----

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        offset = (y * self.width + x) * 4
        blue, green, red, _ = self.framebuffer[offset:offset + 4]
        return red, green, blue

    def distinct_colors(self) -> int:
        return len({bytes(self.framebuffer[index:index + 4]) for index in range(0, len(self.framebuffer), 4)})

    def checksum(self) -> bytes:
        import hashlib
        return hashlib.sha256(bytes(self.framebuffer)).digest()

    def color_histogram(self, limit: int = 8) -> list[tuple[tuple[int, int, int], int]]:
        counts: dict[tuple[int, int, int], int] = {}
        for index in range(0, len(self.framebuffer), 4):
            blue, green, red, _ = self.framebuffer[index:index + 4]
            counts[(red, green, blue)] = counts.get((red, green, blue), 0) + 1
        return sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]


def vnc_auth_response(challenge: bytes, password: bytes) -> bytes:
    """DES-encrypt the VNC challenge with the bit-reversed password key."""
    key = bytearray(8)
    for index in range(min(8, len(password))):
        key[index] = reverse_bits(password[index])
    return des_encrypt(challenge, bytes(key))


def reverse_bits(value: int) -> int:
    result = 0
    for bit in range(8):
        result = (result << 1) | ((value >> bit) & 1)
    return result


# Minimal DES (ECB, single block) — only used for real VNC authentication.
_PC1 = [56, 48, 40, 32, 24, 16, 8, 0, 57, 49, 41, 33, 25, 17, 9, 1, 58, 50, 42, 34, 26, 18,
        10, 2, 59, 51, 43, 35, 62, 54, 46, 38, 30, 22, 14, 6, 61, 53, 45, 37, 29, 21, 13, 5,
        60, 52, 44, 36, 28, 20, 12, 4, 27, 19, 11, 3]
_PC2 = [13, 16, 10, 23, 0, 4, 2, 27, 14, 5, 20, 9, 22, 18, 11, 3, 25, 7, 15, 6, 26, 19, 12,
        1, 40, 51, 30, 36, 46, 54, 29, 39, 50, 44, 32, 47, 43, 48, 38, 55, 33, 52, 45, 41,
        49, 35, 28, 31]
_IP = [57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3, 61, 53, 45, 37, 29, 21,
       13, 5, 63, 55, 47, 39, 31, 23, 15, 7, 56, 48, 40, 32, 24, 16, 8, 0, 58, 50, 42, 34,
       26, 18, 10, 2, 60, 52, 44, 36, 28, 20, 12, 4, 62, 54, 46, 38, 30, 22, 14, 6]
# Final permutation, 0-based. The published table lists the 8 columns for each
# of the 8 rows of the *swapped* halves; flattening the implicit half swap gives
# 64 entries. A 56-entry table silently shortens the ciphertext by one byte.
_FP = [39, 7, 47, 15, 55, 23, 63, 31, 38, 6, 46, 14, 54, 22, 62, 30, 37, 5, 45, 13, 53, 21,
       61, 29, 36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27, 34, 2, 42, 10,
       50, 18, 58, 26, 33, 1, 41, 9, 49, 17, 57, 25, 32, 0, 40, 8, 48, 16, 56, 24]
_E = [31, 0, 1, 2, 3, 4, 3, 4, 5, 6, 7, 8, 7, 8, 9, 10, 11, 12, 11, 12, 13, 14, 15, 16, 15,
      16, 17, 18, 19, 20, 19, 20, 21, 22, 23, 24, 23, 24, 25, 26, 27, 28, 27, 28, 29, 30,
      31, 0]
_P = [15, 6, 19, 20, 28, 11, 27, 16, 0, 14, 22, 25, 4, 17, 30, 9, 1, 7, 23, 13, 31, 26, 2, 8,
      18, 12, 29, 5, 21, 10, 3, 24]
_SHIFTS = [1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1]
_SBOX = [
    [14, 4, 13, 1, 2, 15, 11, 8, 3, 10, 6, 12, 5, 9, 0, 7, 0, 15, 7, 4, 14, 2, 13, 1, 10, 6, 12, 11, 9, 5, 3, 8,
     4, 1, 14, 8, 13, 6, 2, 11, 15, 12, 9, 7, 3, 10, 5, 0, 15, 12, 8, 2, 4, 9, 1, 7, 5, 11, 3, 14, 10, 0, 6, 13],
    [15, 1, 8, 14, 6, 11, 3, 4, 9, 7, 2, 13, 12, 0, 5, 10, 3, 13, 4, 7, 15, 2, 8, 14, 12, 0, 1, 10, 6, 9, 11, 5,
     0, 14, 7, 11, 10, 4, 13, 1, 5, 8, 12, 6, 9, 3, 2, 15, 13, 8, 10, 1, 3, 15, 4, 2, 11, 6, 7, 12, 0, 5, 14, 9],
    [10, 0, 9, 14, 6, 3, 15, 5, 1, 13, 12, 7, 11, 4, 2, 8, 13, 7, 0, 9, 3, 4, 6, 10, 2, 8, 5, 14, 12, 11, 15, 1,
     13, 6, 4, 9, 8, 15, 3, 0, 11, 1, 2, 12, 5, 10, 14, 7, 1, 10, 13, 0, 6, 9, 8, 7, 4, 15, 14, 3, 11, 5, 2, 12],
    [7, 13, 14, 3, 0, 6, 9, 10, 1, 2, 8, 5, 11, 12, 4, 15, 13, 8, 11, 5, 6, 15, 0, 3, 4, 7, 2, 12, 1, 10, 14, 9,
     10, 6, 9, 0, 12, 11, 7, 13, 15, 1, 3, 14, 5, 2, 8, 4, 3, 15, 0, 6, 10, 1, 13, 8, 9, 4, 5, 11, 12, 7, 2, 14],
    [2, 12, 4, 1, 7, 10, 11, 6, 8, 5, 3, 15, 13, 0, 14, 9, 14, 11, 2, 12, 4, 7, 13, 1, 5, 0, 15, 10, 3, 9, 8, 6,
     4, 2, 1, 11, 10, 13, 7, 8, 15, 9, 12, 5, 6, 3, 0, 14, 11, 8, 12, 7, 1, 14, 2, 13, 6, 15, 0, 9, 10, 4, 5, 3],
    [12, 1, 10, 15, 9, 2, 6, 8, 0, 13, 3, 4, 14, 7, 5, 11, 10, 15, 4, 2, 7, 12, 9, 5, 6, 1, 13, 14, 0, 11, 3, 8,
     9, 14, 15, 5, 2, 8, 12, 3, 7, 0, 4, 10, 1, 13, 11, 6, 4, 3, 2, 12, 9, 5, 15, 10, 11, 14, 1, 7, 6, 0, 8, 13],
    [4, 11, 2, 14, 15, 0, 8, 13, 3, 12, 9, 7, 5, 10, 6, 1, 13, 0, 11, 7, 4, 9, 1, 10, 14, 3, 5, 12, 2, 15, 8, 6,
     1, 4, 11, 13, 12, 3, 7, 14, 10, 15, 6, 8, 0, 5, 9, 2, 6, 11, 13, 8, 1, 4, 10, 7, 9, 5, 0, 15, 14, 2, 3, 12],
    [13, 2, 8, 4, 6, 15, 11, 1, 10, 9, 3, 14, 5, 0, 12, 7, 1, 15, 13, 8, 10, 3, 7, 4, 12, 5, 6, 11, 0, 14, 9, 2,
     7, 11, 4, 1, 9, 12, 14, 2, 0, 6, 10, 13, 15, 3, 5, 8, 2, 1, 14, 7, 4, 10, 8, 13, 15, 12, 9, 0, 3, 5, 6, 11],
]


def _bits(data: bytes) -> list[int]:
    return [(byte >> (7 - bit)) & 1 for byte in data for bit in range(8)]


def _bytes_from_bits(bits: list[int]) -> bytes:
    out = bytearray()
    for index in range(0, len(bits), 8):
        value = 0
        for bit in bits[index:index + 8]:
            value = (value << 1) | bit
        out.append(value)
    return bytes(out)


def _permute(bits: list[int], table: list[int]) -> list[int]:
    return [bits[index] for index in table]


def _subkeys(key: bytes) -> list[list[int]]:
    bits = _permute(_bits(key), _PC1)
    left, right = bits[:28], bits[28:]
    keys = []
    for shift in _SHIFTS:
        left = left[shift:] + left[:shift]
        right = right[shift:] + right[:shift]
        keys.append(_permute(left + right, _PC2))
    return keys


def des_encrypt(block: bytes, key: bytes) -> bytes:
    """ECB-encrypt ``block`` (any multiple of 8 bytes) with a raw 8-byte key."""
    if len(block) % 8:
        raise ValueError("DES block size must be a multiple of 8 bytes")
    return b"".join(_des_block(block[offset:offset + 8], key) for offset in range(0, len(block), 8))


def _des_block(block: bytes, key: bytes) -> bytes:
    bits = _permute(_bits(block), _IP)
    left, right = bits[:32], bits[32:]
    for subkey in _subkeys(key):
        expanded = _permute(right, _E)
        mixed = [a ^ b for a, b in zip(expanded, subkey)]
        output: list[int] = []
        for index in range(8):
            chunk = mixed[index * 6:(index + 1) * 6]
            row = (chunk[0] << 1) | chunk[5]
            column = (chunk[1] << 3) | (chunk[2] << 2) | (chunk[3] << 1) | chunk[4]
            value = _SBOX[index][row * 16 + column]
            output.extend([(value >> shift) & 1 for shift in (3, 2, 1, 0)])
        left, right = right, [a ^ b for a, b in zip(left, _permute(output, _P))]
    return _bytes_from_bits(_permute(right + left, _FP))
