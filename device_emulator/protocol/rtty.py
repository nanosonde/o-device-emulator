"""RTTY (remote TTY) binary wire protocol — controller ↔ device channel.

Implements the binary frame format and message types for the RTTY channel.
The controller is the RTTY *server* (port 29816 behind TLS); the device is
the *client* that connects in, registers, and relays shell I/O.

See ``doc/DEVICE_PROTOCOL.md`` §10 for the full protocol reference.

Frame variants (the type byte determines which header applies):

* **V1** — ``type(1) + length(2, big-endian) + payload`` (3-byte header).
  Used by REGISTER, LOGIN, LOGOUT, TERMDATA, WINSIZE, CMD, HEARTBEAT, ACK.

* **V2** — ``type(1) + length(4, big-endian) + payload`` (5-byte header).
  Used by TCPDATA, HTTPSDATA, SSHDATA, TELNETDATA, TUNNEL_ADD, TUNNEL_DELETE,
  STANDALONE_AUTH.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

# -- Message types (RTTY message-type enum) -----------------------------------

REGISTER = 0
LOGIN = 1
LOGOUT = 2
TERMDATA = 3
WINSIZE = 4
CMD = 5
HEARTBEAT = 6
ACK = 9
DEVICE_DISCONNECT_EXCEPTION = 10
DEVICE_DISCONNECT_NORMALLY = 11
TCPDATA = 20
HTTPSDATA = 22
SSHDATA = 31
TELNETDATA = 32
TUNNEL_ADD = 40
TUNNEL_DELETE = 41
STANDALONE_AUTH = 42

# V1 message types (3-byte header: type + uint16 length)
_V1_TYPES = frozenset({
    REGISTER, LOGIN, LOGOUT, TERMDATA, WINSIZE, CMD, HEARTBEAT, ACK,
    DEVICE_DISCONNECT_EXCEPTION, DEVICE_DISCONNECT_NORMALLY,
})

# V2 message types (5-byte header: type + uint32 length)
_V2_TYPES = frozenset({
    TCPDATA, HTTPSDATA, SSHDATA, TELNETDATA,
    TUNNEL_ADD, TUNNEL_DELETE, STANDALONE_AUTH,
})

# Minimum supported REGISTER version (RTTY protocol minimum).
MIN_PROTOCOL_VERSION = 3
# Session ID is always 32 bytes (browser-generated UUID hex, hyphens stripped).
SESSION_ID_LENGTH = 32

# REGISTER error codes
REGISTER_OK = 0
REGISTER_ERR = 1
REGISTER_MSG_OK = "OK"
REGISTER_MSG_INVALID_TOKEN = "Invalid token"
REGISTER_MSG_UNSUPPORTED_PROTOCOL = "unsupported protocol"
REGISTER_MSG_ID_CONFLICT = "ID conflicting"

# LOGIN error codes (device → controller reply)
LOGIN_OK = 0
LOGIN_DEVICE_BUSY = 1


def _is_v1(msg_type: int) -> bool:
    return msg_type in _V1_TYPES


@dataclass
class RttyFrame:
    """A parsed RTTY frame."""
    type: int
    payload: bytes

    def is_v1(self) -> bool:
        return _is_v1(self.type)


# -- Frame packing -----------------------------------------------------------

def pack_frame(msg_type: int, payload: bytes) -> bytes:
    """Pack a single RTTY frame (V1 or V2 header + payload) into bytes."""
    if _is_v1(msg_type):
        if len(payload) > 0xFFFF:
            raise ValueError(f"V1 payload too large ({len(payload)} > 65535)")
        return struct.pack(">BH", msg_type, len(payload)) + payload
    # V2
    return struct.pack(">BI", msg_type, len(payload)) + payload


def pack_register_request(version: int, devid: str, description: str, token: str) -> bytes:
    """REGISTER (device → controller): ``version(1)`` + null-terminated fields.

    Payload: ``version(1) + devid\\0 + description\\0 + token\\0``.
    The controller's register handler reads the
    version byte, then splits the remaining bytes on ``\\0`` and requires
    exactly 4 segments — ``devid``, ``description``, ``token`` and a trailing
    empty segment produced by the final ``\\0``. Emitting an extra ``\\0``
    yields 5 segments and the controller drops the connection.
    """
    payload = struct.pack(">B", version)
    payload += devid.encode("utf-8") + b"\x00"
    payload += description.encode("utf-8") + b"\x00"
    payload += token.encode("utf-8") + b"\x00"
    return pack_frame(REGISTER, payload)


def pack_register_response(err: int, msg: str) -> bytes:
    """REGISTER (controller → device): ``err(1) + msg(UTF-8)``."""
    payload = struct.pack(">B", err) + msg.encode("utf-8")
    return pack_frame(REGISTER, payload)


def pack_login(sid: str) -> bytes:
    """LOGIN (controller → device): ``sid(32 bytes, ASCII)``."""
    return pack_frame(LOGIN, _sid_bytes(sid))


def pack_login_response(sid: str, code: int) -> bytes:
    """LOGIN (device → controller): ``sid(32) + code(1)``."""
    payload = _sid_bytes(sid) + struct.pack(">B", code)
    return pack_frame(LOGIN, payload)


def pack_logout(sid: str) -> bytes:
    """LOGOUT (controller → device): ``sid(32)``."""
    return pack_frame(LOGOUT, _sid_bytes(sid))


def pack_termdata(sid: str, data: str) -> bytes:
    """TERMDATA (bidirectional): ``sid(32) + data(UTF-8, remaining)``."""
    payload = _sid_bytes(sid) + data.encode("utf-8")
    return pack_frame(TERMDATA, payload)


def pack_termdata_raw(sid: str, data: bytes) -> bytes:
    """TERMDATA with raw bytes (no UTF-8 encoding)."""
    payload = _sid_bytes(sid) + data
    return pack_frame(TERMDATA, payload)


def pack_heartbeat(uptime: int = 0) -> bytes:
    """HEARTBEAT (device → controller): ``uptime(int32)``.

    The controller's heartbeat handler reads a
    4-byte int (``payload.getInt()``) for the device uptime; an empty payload
    triggers a ``BufferUnderflowException`` on the controller and tears down
    the RTTY channel.
    """
    return pack_frame(HEARTBEAT, struct.pack(">I", uptime & 0xFFFFFFFF))


def pack_ack(sid: str, ack: int) -> bytes:
    """ACK (controller → device): ``sid(32) + ack(uint16)``."""
    payload = _sid_bytes(sid) + struct.pack(">H", ack)
    return pack_frame(ACK, payload)


def pack_winsize(sid: str, cols: int, rows: int) -> bytes:
    """WINSIZE (controller → device): ``sid(32) + cols(?) + rows(?)``.

    The controller's winsize pack method returns null, so
    the exact packing is unverified. We use ``sid(32) + cols(uint16) +
    rows(uint16)`` as the most plausible layout from the field declarations.
    """
    payload = _sid_bytes(sid) + struct.pack(">HH", cols, rows)
    return pack_frame(WINSIZE, payload)


def pack_tunnel_add(tunnel_id: int, local_address: int, local_port: int) -> bytes:
    """TUNNEL_ADD (controller → device, V2): ``tunnelId(1) + localAddress(uint32) + localPort(uint16)``."""
    payload = struct.pack(">BIH", tunnel_id, local_address, local_port)
    return pack_frame(TUNNEL_ADD, payload)


def pack_tunnel_delete(tunnel_id: int) -> bytes:
    """TUNNEL_DELETE (controller → device, V2): ``tunnelId(1)``."""
    return pack_frame(TUNNEL_DELETE, struct.pack(">B", tunnel_id))


def pack_ssh_data(tunnel_id: int, data: str) -> bytes:
    """SSHDATA (bidirectional, V2): ``tunnelId(1) + data(UTF-8)``."""
    payload = struct.pack(">B", tunnel_id) + data.encode("utf-8")
    return pack_frame(SSHDATA, payload)


def pack_telnet_data(tunnel_id: int, data: str) -> bytes:
    """TELNETDATA (bidirectional, V2): ``tunnelId(1) + data(UTF-8)``."""
    payload = struct.pack(">B", tunnel_id) + data.encode("utf-8")
    return pack_frame(TELNETDATA, payload)


def pack_tcp_data(tunnel_id: int, request_id: bytes, data: bytes) -> bytes:
    """TCPDATA (bidirectional, V2): ``tunnelId(1) + requestId(16) + data``."""
    if len(request_id) != 16:
        raise ValueError("requestId must be 16 bytes")
    payload = struct.pack(">B", tunnel_id) + request_id + data
    return pack_frame(TCPDATA, payload)


def pack_https_data(tunnel_id: int, request_id: bytes, data: bytes) -> bytes:
    """HTTPSDATA (bidirectional, V2): ``tunnelId(1) + requestId(16) + data``."""
    if len(request_id) != 16:
        raise ValueError("requestId must be 16 bytes")
    payload = struct.pack(">B", tunnel_id) + request_id + data
    return pack_frame(HTTPSDATA, payload)


def pack_standalone_auth(tunnel_id: int, username_and_password: str) -> bytes:
    """STANDALONE_AUTH (controller → device, V2): ``tunnelId(1) + usernameAndPassword(UTF-8)``."""
    payload = struct.pack(">B", tunnel_id) + username_and_password.encode("utf-8")
    return pack_frame(STANDALONE_AUTH, payload)


# -- Frame parsing ------------------------------------------------------------

def _sid_bytes(sid: str) -> bytes:
    """Encode a session id (32-char hex string) to 32 raw bytes (ASCII)."""
    sid_b = sid.encode("ascii")
    if len(sid_b) != SESSION_ID_LENGTH:
        raise ValueError(f"sid must be {SESSION_ID_LENGTH} bytes, got {len(sid_b)}")
    return sid_b


def _read_exact(sock, n: int) -> Optional[bytes]:
    """Read exactly n bytes from a socket; None on EOF."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def read_frame(sock) -> Optional[RttyFrame]:
    """Read one RTTY frame from a (blocking) socket.

    Peeks the type byte first, then reads the appropriate length field (V1 =
    2 bytes, V2 = 4 bytes). Returns ``None`` on EOF.
    """
    # Read the type byte (1 byte)
    type_byte = _read_exact(sock, 1)
    if type_byte is None:
        return None
    msg_type = type_byte[0]

    if _is_v1(msg_type):
        length_bytes = _read_exact(sock, 2)
        if length_bytes is None:
            return None
        (length,) = struct.unpack(">H", length_bytes)
    else:
        length_bytes = _read_exact(sock, 4)
        if length_bytes is None:
            return None
        (length,) = struct.unpack(">I", length_bytes)

    payload = _read_exact(sock, length) if length > 0 else b""
    if payload is None:
        return None
    return RttyFrame(type=msg_type, payload=payload)


# -- Payload parsing helpers --------------------------------------------------

def parse_register_response(payload: bytes) -> tuple[int, str]:
    """Parse a REGISTER reply (controller → device): ``err(1) + msg(UTF-8)``."""
    if len(payload) < 1:
        return REGISTER_ERR, ""
    err = payload[0]
    msg = payload[1:].decode("utf-8", errors="replace")
    return err, msg


def parse_login(payload: bytes) -> str:
    """Parse a LOGIN (controller → device): ``sid(32 bytes)``."""
    if len(payload) < SESSION_ID_LENGTH:
        raise ValueError(f"LOGIN payload too short: {len(payload)}")
    return payload[:SESSION_ID_LENGTH].decode("ascii")


def parse_login_response(payload: bytes) -> tuple[str, int]:
    """Parse a LOGIN reply (device → controller): ``sid(32) + code(1)``."""
    if len(payload) < SESSION_ID_LENGTH + 1:
        raise ValueError(f"LOGIN response too short: {len(payload)}")
    sid = payload[:SESSION_ID_LENGTH].decode("ascii")
    code = payload[SESSION_ID_LENGTH]
    return sid, code


def parse_logout(payload: bytes) -> str:
    """Parse a LOGOUT (controller → device): ``sid(32)``."""
    if len(payload) < SESSION_ID_LENGTH:
        raise ValueError(f"LOGOUT payload too short: {len(payload)}")
    return payload[:SESSION_ID_LENGTH].decode("ascii")


def parse_termdata(payload: bytes) -> tuple[str, bytes]:
    """Parse a TERMDATA frame: ``sid(32) + data(remaining bytes)``.

    Returns ``(sid, data_bytes)``. The data is returned as raw bytes — the
    caller is responsible for decoding (it may be UTF-8 terminal output or
    arbitrary bytes if SPAKE2 encryption is active).
    """
    if len(payload) < SESSION_ID_LENGTH:
        raise ValueError(f"TERMDATA payload too short: {len(payload)}")
    sid = payload[:SESSION_ID_LENGTH].decode("ascii")
    data = payload[SESSION_ID_LENGTH:]
    return sid, data


def parse_ack(payload: bytes) -> tuple[str, int]:
    """Parse an ACK (controller → device): ``sid(32) + ack(uint16)``."""
    if len(payload) < SESSION_ID_LENGTH + 2:
        raise ValueError(f"ACK payload too short: {len(payload)}")
    sid = payload[:SESSION_ID_LENGTH].decode("ascii")
    (ack,) = struct.unpack(">H", payload[SESSION_ID_LENGTH:SESSION_ID_LENGTH + 2])
    return sid, ack


def parse_tunnel_add(payload: bytes) -> tuple[int, int, int]:
    """Parse a TUNNEL_ADD (V2): ``tunnelId(1) + localAddress(uint32) + localPort(uint16)``."""
    if len(payload) < 7:
        raise ValueError(f"TUNNEL_ADD payload too short: {len(payload)}")
    tunnel_id, local_addr, local_port = struct.unpack(">BIH", payload[:7])
    return tunnel_id, local_addr, local_port


def parse_tunnel_delete(payload: bytes) -> int:
    """Parse a TUNNEL_DELETE (V2): ``tunnelId(1)``."""
    if len(payload) < 1:
        raise ValueError("TUNNEL_DELETE payload empty")
    return payload[0]


def parse_ssh_data(payload: bytes) -> tuple[int, str]:
    """Parse SSHDATA (V2): ``tunnelId(1) + data(UTF-8)``."""
    if len(payload) < 1:
        raise ValueError("SSHDATA payload empty")
    return payload[0], payload[1:].decode("utf-8", errors="replace")


def parse_telnet_data(payload: bytes) -> tuple[int, str]:
    """Parse TELNETDATA (V2): ``tunnelId(1) + data(UTF-8)``."""
    if len(payload) < 1:
        raise ValueError("TELNETDATA payload empty")
    return payload[0], payload[1:].decode("utf-8", errors="replace")


def parse_tcp_data(payload: bytes) -> tuple[int, bytes, bytes]:
    """Parse TCPDATA (V2): ``tunnelId(1) + requestId(16) + data``."""
    if len(payload) < 17:
        raise ValueError(f"TCPDATA payload too short: {len(payload)}")
    tunnel_id = payload[0]
    request_id = payload[1:17]
    data = payload[17:]
    return tunnel_id, request_id, data


def parse_https_data(payload: bytes) -> tuple[int, bytes, bytes]:
    """Parse HTTPSDATA (V2): ``tunnelId(1) + requestId(16) + data``."""
    if len(payload) < 17:
        raise ValueError(f"HTTPSDATA payload too short: {len(payload)}")
    tunnel_id = payload[0]
    request_id = payload[1:17]
    data = payload[17:]
    return tunnel_id, request_id, data


def parse_standalone_auth(payload: bytes) -> tuple[int, str]:
    """Parse STANDALONE_AUTH (V2): ``tunnelId(1) + usernameAndPassword(UTF-8)``."""
    if len(payload) < 1:
        raise ValueError("STANDALONE_AUTH payload empty")
    return payload[0], payload[1:].decode("utf-8", errors="replace")