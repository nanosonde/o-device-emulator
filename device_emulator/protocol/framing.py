"""Wire framing for the device/controller message protocol.

Both the UDP discovery channel (port 29810) and the TCP manager channels
(29811/29812/29814) frame a JSON payload behind a 4-byte big-endian length
prefix (CONFIRMED for UDP via live testing; the TCP channels use the same
framing, see doc/DEVICE_PROTOCOL.md §2).
"""
from __future__ import annotations

import struct

_LENGTH_STRUCT = struct.Struct(">I")


def encode_frame(payload: bytes) -> bytes:
    """Prepend a 4-byte big-endian length prefix to a payload."""
    return _LENGTH_STRUCT.pack(len(payload)) + payload


def decode_frame(data: bytes) -> bytes:
    """Strip and validate the 4-byte big-endian length prefix from `data`.

    Returns the payload bytes. Raises ValueError if the buffer is too short
    or the declared length doesn't match what's available.
    """
    if len(data) < _LENGTH_STRUCT.size:
        raise ValueError(f"frame too short: {len(data)} bytes")
    (declared_length,) = _LENGTH_STRUCT.unpack_from(data, 0)
    payload = data[_LENGTH_STRUCT.size :]
    if len(payload) < declared_length:
        raise ValueError(
            f"declared length {declared_length} exceeds available {len(payload)} bytes"
        )
    return payload[:declared_length]
