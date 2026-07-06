"""Wire protocol layer: framing, message envelope, discovery body builders,
and the management-channel (adoption) helpers for the device/controller
protocol.

See doc/DEVICE_PROTOCOL.md for the confirmed wire format.
"""
from . import adoption, constants
from .auth import calculate_device_auth, md5_upper, sha256_upper
from .discovery import build_discovery_body
from .framing import decode_frame, encode_frame
from .messages import DeviceMessage, MessageHeader, ParsedMessage

__all__ = [
    "adoption",
    "constants",
    "build_discovery_body",
    "calculate_device_auth",
    "md5_upper",
    "sha256_upper",
    "decode_frame",
    "encode_frame",
    "DeviceMessage",
    "MessageHeader",
    "ParsedMessage",
]
