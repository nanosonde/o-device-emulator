"""Wire protocol layer: framing, message envelope, and discovery body builders
for the device/controller protocol.

See doc/DEVICE_PROTOCOL.md for the confirmed wire format.
"""
from . import constants
from .discovery import build_discovery_body
from .framing import decode_frame, encode_frame
from .messages import DeviceMessage, MessageHeader, ParsedMessage

__all__ = [
    "constants",
    "build_discovery_body",
    "decode_frame",
    "encode_frame",
    "DeviceMessage",
    "MessageHeader",
    "ParsedMessage",
]
