"""DeviceMessage envelope: {"header": {...}, "body": {...}}.

See doc/DEVICE_PROTOCOL.md §2-3 for the confirmed field semantics.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from . import constants


@dataclass
class MessageHeader:
    mac: str
    type: int
    device: str
    version: str = constants.PROTOCOL_VERSION
    verCap: int = constants.PROTOCOL_VER_CAP
    timestamp: Optional[int] = None
    seq: Optional[int] = None
    error: int = 0
    compress: Optional[str] = None
    dest: Optional[str] = None
    ip: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        ts = self.timestamp if self.timestamp is not None else int(time.time() * 1000)
        out: dict[str, Any] = {
            "mac": self.mac,
            "type": self.type,
            "device": self.device,
            "version": self.version,
            "verCap": self.verCap,
            "timestamp": ts,
            "error": self.error,
        }
        if self.seq is not None:
            out["seq"] = self.seq
        if self.compress is not None:
            out["compress"] = self.compress
        if self.dest is not None:
            out["dest"] = self.dest
        if self.ip is not None:
            out["ip"] = self.ip
        return out


@dataclass
class DeviceMessage:
    header: MessageHeader
    body: dict[str, Any] = field(default_factory=dict)

    def to_json_bytes(self) -> bytes:
        envelope = {"header": self.header.to_dict(), "body": self.body}
        return json.dumps(envelope, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def parse(raw: bytes) -> "ParsedMessage":
        envelope = json.loads(raw.decode("utf-8"))
        return ParsedMessage(
            header=envelope.get("header", {}) or {},
            body=envelope.get("body", {}) or {},
        )


@dataclass
class ParsedMessage:
    """A loosely-typed parsed envelope (controller responses aren't fully
    characterized yet, so keep this permissive rather than validating
    strictly against MessageHeader)."""

    header: dict[str, Any]
    body: dict[str, Any]

    @property
    def type(self) -> Optional[int]:
        return self.header.get("type")

    @property
    def mac(self) -> Optional[str]:
        return self.header.get("mac")
