"""Device-Monitor Protocol (DMP) wire codec — controller ↔ device channel.

Implements the protobuf-based message format for the device-monitor channel.
The controller is the DMP *server* (port 29817 behind TLS); the device is the
*client* that connects in, registers with a token, and relays monitor/inform
component data. Network Check (ping/traceroute) probes flow through this
channel.

Unlike RTTY (a custom binary protocol), DMP uses **Google Protocol Buffers**
over an ECSP packet frame. The ECSP frame is a 4-byte big-endian length prefix
(the protobuf byte length) followed by the serialized monitor message
protobuf bytes — no type byte (the message type is inside the protobuf header).

See ``doc/DEVICE_PROTOCOL.md`` §11 for the full protocol reference.

Protobuf schema::

    message MonitorMessageHeader {
        bytes  mac         = 1;
        bytes  token       = 2;
        string path        = 3;
        string version     = 4;
        MsgTypeEnum msgType = 5;
        int32  seq         = 6;
        int32  devType     = 7;
        int32  errorCode   = 8;
        bool   needReply   = 9;
        int64  epochMs     = 10;
        int32  contentType = 11;
    }
    message MonitorMessage {
        MonitorMessageHeader header = 1;
        bytes data = 2;
    }
    message Component { int32 type = 1; bytes data = 2; }
    message ComponentList { repeated Component components = 1; }
    message JsonComponent { repeated string type = 1; bytes data = 2; }

    enum MsgTypeEnum {
        MSG_UNSPECIFIED        = 0;
        MSG_EMPTY              = 1;
        MSG_COMPONENT_LIST     = 2;
        MSG_JSON_COMPONENT_LIST = 3;
    }

The protobuf wire format is hand-coded here (no protobuf library dependency)
because the schema is small and stable.
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field
from typing import Optional

# -- MsgTypeEnum values -------------------------------------------------------

MSG_UNSPECIFIED = 0
MSG_EMPTY = 1
MSG_COMPONENT_LIST = 2
MSG_JSON_COMPONENT_LIST = 3

# -- Protobuf wire format helpers --------------------------------------------
# Protobuf field tags: (field_number << 3) | wire_type
# wire_type: 0=varint, 1=fixed64, 2=length-delimited, 5=fixed32

def _tag_varint(field_number: int) -> int:
    return field_number << 3


def _tag_bytes(field_number: int) -> int:
    return (field_number << 3) | 2


def _tag_fixed64(field_number: int) -> int:
    return (field_number << 3) | 1


def _encode_varint(value: int) -> bytes:
    """Encode an unsigned varint (protobuf base-128 encoding)."""
    if value < 0:
        # Treat as unsigned 64-bit (two's complement).
        value &= (1 << 64) - 1
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value & 0x7F)
    return bytes(out)


def _decode_varint(buf: bytes, offset: int) -> tuple[int, int]:
    """Decode a varint from *buf* at *offset*; return (value, new_offset)."""
    result = 0
    shift = 0
    while True:
        b = buf[offset]
        offset += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, offset


def _encode_bytes_field(field_number: int, value: bytes) -> bytes:
    """Encode a length-delimited protobuf field (bytes/string/submessage)."""
    return _encode_varint(_tag_bytes(field_number)) + _encode_varint(len(value)) + value


def _encode_varint_field(field_number: int, value: int) -> bytes:
    """Encode a varint protobuf field (int32/int64/bool/enum)."""
    return _encode_varint(_tag_varint(field_number)) + _encode_varint(value)


def _encode_string_field(field_number: int, value: str) -> bytes:
    """Encode a string protobuf field."""
    return _encode_bytes_field(field_number, value.encode("utf-8"))


def _encode_fixed64_field(field_number: int, value: int) -> bytes:
    """Encode a fixed64 protobuf field."""
    return _encode_varint(_tag_fixed64(field_number)) + struct.pack("<Q", value)


@dataclass
class MonitorMessageHeader:
    """The monitor message header protobuf message."""
    mac: bytes = b""
    token: bytes = b""
    path: str = ""
    version: str = "1.0"
    msg_type: int = MSG_EMPTY
    seq: int = 0
    dev_type: int = 0
    error_code: int = 0
    need_reply: bool = False
    epoch_ms: int = 0
    content_type: int = 0

    def encode(self) -> bytes:
        """Serialize to protobuf wire bytes."""
        out = bytearray()
        if self.mac:
            out += _encode_bytes_field(1, self.mac)
        if self.token:
            out += _encode_bytes_field(2, self.token)
        if self.path:
            out += _encode_string_field(3, self.path)
        if self.version:
            out += _encode_string_field(4, self.version)
        if self.msg_type:
            out += _encode_varint_field(5, self.msg_type)
        if self.seq:
            out += _encode_varint_field(6, self.seq)
        if self.dev_type:
            out += _encode_varint_field(7, self.dev_type)
        if self.error_code:
            out += _encode_varint_field(8, self.error_code)
        if self.need_reply:
            out += _encode_varint_field(9, 1)
        if self.epoch_ms:
            out += _encode_fixed64_field(10, self.epoch_ms)
        if self.content_type:
            out += _encode_varint_field(11, self.content_type)
        return bytes(out)

    @classmethod
    def decode(cls, buf: bytes, offset: int = 0, end: int = -1) -> "MonitorMessageHeader":
        """Deserialize from protobuf wire bytes."""
        if end < 0:
            end = len(buf)
        hdr = cls()
        while offset < end:
            tag, offset = _decode_varint(buf, offset)
            field_number = tag >> 3
            wire_type = tag & 0x7
            if wire_type == 0:  # varint
                val, offset = _decode_varint(buf, offset)
                if field_number == 5:
                    hdr.msg_type = val
                elif field_number == 6:
                    hdr.seq = val
                elif field_number == 7:
                    hdr.dev_type = val
                elif field_number == 8:
                    hdr.error_code = val
                elif field_number == 9:
                    hdr.need_reply = bool(val)
                elif field_number == 11:
                    hdr.content_type = val
            elif wire_type == 2:  # length-delimited
                ln, offset = _decode_varint(buf, offset)
                data = buf[offset:offset + ln]
                offset += ln
                if field_number == 1:
                    hdr.mac = bytes(data)
                elif field_number == 2:
                    hdr.token = bytes(data)
                elif field_number == 3:
                    hdr.path = data.decode("utf-8")
                elif field_number == 4:
                    hdr.version = data.decode("utf-8")
            elif wire_type == 1:  # fixed64
                val = struct.unpack_from("<Q", buf, offset)[0]
                offset += 8
                if field_number == 10:
                    hdr.epoch_ms = val
            elif wire_type == 5:  # fixed32
                offset += 4
        return hdr


@dataclass
class MonitorMessage:
    """The monitor message protobuf message."""
    header: MonitorMessageHeader = field(default_factory=MonitorMessageHeader)
    data: bytes = b""

    def encode(self) -> bytes:
        """Serialize to protobuf wire bytes."""
        out = bytearray()
        hdr_bytes = self.header.encode()
        if hdr_bytes:
            out += _encode_bytes_field(1, hdr_bytes)
        if self.data:
            out += _encode_bytes_field(2, self.data)
        return bytes(out)

    @classmethod
    def decode(cls, buf: bytes) -> "MonitorMessage":
        """Deserialize from protobuf wire bytes."""
        msg = cls()
        offset = 0
        while offset < len(buf):
            tag, offset = _decode_varint(buf, offset)
            field_number = tag >> 3
            wire_type = tag & 0x7
            if wire_type == 2:  # length-delimited
                ln, offset = _decode_varint(buf, offset)
                data = buf[offset:offset + ln]
                offset += ln
                if field_number == 1:
                    msg.header = MonitorMessageHeader.decode(data)
                elif field_number == 2:
                    msg.data = bytes(data)
            else:
                break  # unknown field, stop
        return msg


# -- ECSP packet framing ------------------------------------------------------

def pack_ecsp_packet(protobuf_bytes: bytes) -> bytes:
    """Encode an ECSP packet: 4-byte BE length + payload.

    The controller sends a 4-byte big-endian length prefix followed by the
    protobuf-serialized monitor message bytes.
    """
    return struct.pack(">I", len(protobuf_bytes)) + protobuf_bytes


def read_ecsp_packet(sock) -> Optional[MonitorMessage]:
    """Read one ECSP packet from *sock* and decode the protobuf message.

    Returns ``None`` if the connection is closed before a complete packet
    arrives.
    """
    # Read the 4-byte BE length prefix.
    length_bytes = _recv_exact(sock, 4)
    if length_bytes is None:
        return None
    (length,) = struct.unpack(">I", length_bytes)
    if length == 0:
        return MonitorMessage()
    # Read the protobuf payload.
    payload = _recv_exact(sock, length)
    if payload is None:
        return None
    return MonitorMessage.decode(payload)


def _recv_exact(sock, n: int) -> Optional[bytes]:
    """Read exactly *n* bytes from *sock*; return ``None`` on EOF."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


# -- Convenience builders -----------------------------------------------------

def build_register_message(
    mac_bytes: bytes,
    token_bytes: bytes,
    path: str = "/",
    version: str = "1.0",
    msg_type: int = MSG_EMPTY,
) -> bytes:
    """Build a DMP register/handshake message (ECSP-framed protobuf).

    The device sends this as its first message after connecting to the
    controller's DMP server (port 29817). The controller validates that
    ``header.mac``, ``header.token``, ``header.path`` and ``header.version``
    are all present (non-empty).
    """
    hdr = MonitorMessageHeader(
        mac=mac_bytes,
        token=token_bytes,
        path=path,
        version=version,
        msg_type=msg_type,
        epoch_ms=int(time.time() * 1000),
    )
    msg = MonitorMessage(header=hdr, data=b"")
    return pack_ecsp_packet(msg.encode())


def build_heartbeat_message(mac_bytes: bytes, token_bytes: bytes, seq: int = 0) -> bytes:
    """Build a DMP heartbeat/keepalive message (MSG_EMPTY with current epoch)."""
    hdr = MonitorMessageHeader(
        mac=mac_bytes,
        token=token_bytes,
        path="/",
        version="1.0",
        msg_type=MSG_EMPTY,
        seq=seq,
        epoch_ms=int(time.time() * 1000),
    )
    msg = MonitorMessage(header=hdr, data=b"")
    return pack_ecsp_packet(msg.encode())