"""Base class for emulated network devices.

Each device knows how to build its own discovery announcement (the one
protocol phase confirmed against a live controller - see
doc/DEVICE_PROTOCOL.md). Adoption/inform (TCP channels) are not yet
confirmed; devices expose extension points for that but the daemon's
supported behavior today is discovery only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..protocol import constants
from ..protocol.discovery import build_discovery_body
from ..protocol.messages import DeviceMessage, MessageHeader


def _normalize_mac(mac: str) -> str:
    """Normalize a MAC address to the hyphenated uppercase form seen on the
    wire in live testing (e.g. "AA-BB-CC-DD-EE-FF")."""
    cleaned = mac.replace(":", "-").replace(".", "-").upper()
    return cleaned


def format_uptime(seconds: int) -> str:
    """Format an uptime as "<N> days HH:MM:SS" (the form switches and gateways
    report in their management-channel device info)."""
    days, rem = divmod(max(0, seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{days} days {hours:02d}:{minutes:02d}:{secs:02d}"


@dataclass
class DeviceIdentity:
    name: str
    mac: str
    model: str
    model_version: str = "1.0"
    firmware_version: str = "1.0.0 Build 20240101 Rel.12345"
    hardware_version: str = "1.0"


@dataclass
class Device:
    """Base class for an emulated network device.

    Subclasses (EapDevice, SwitchDevice, GatewayDevice) set `device_type` and
    implement `build_discovery_body()`.
    """

    identity: DeviceIdentity
    ip: str
    device_type: str = field(init=False, default="")
    # ECSP protocol version advertised in header.version. The controller
    # classifies this per device type; subclasses override it (access points
    # use 2.3.0, switches/gateways use 2.2.0).
    protocol_version: str = field(init=False, default=constants.PROTOCOL_VERSION)
    controller_id: Optional[str] = None
    uptime_start: float = field(default_factory=time.time)
    country_code: int = 0

    @property
    def mac(self) -> str:
        return _normalize_mac(self.identity.mac)

    @property
    def name(self) -> str:
        return self.identity.name

    @property
    def uptime_seconds(self) -> int:
        return max(0, int(time.time() - self.uptime_start))

    def build_discovery_body(self) -> dict[str, Any]:
        raise NotImplementedError

    def manage_device_info(self) -> dict[str, Any]:
        """The ``deviceInfo`` object sent over the management channel during
        and after adoption (negotiation + INFORM heartbeats).

        The shape is device-type-specific (access points use a long-name field
        set; switches/gateways use short names), so concrete device classes
        implement it.
        """
        raise NotImplementedError

    def manage_components_v2(self) -> dict[str, str]:
        """The component manifest ({name: version}) reported during
        negotiation. The controller treats an empty manifest as incompatible
        (and shows a warning), so subclasses that support adoption return a
        realistic, non-empty set. Empty by default.
        """
        return {}

    def build_manage_negotiation_body(self, controller_id: str) -> dict[str, Any]:
        """The DEVICE_NEGOTIATION body sent over the management channel.

        This default is the access-point ("wireless") shape: the device info,
        the component manifest, and empty capability placeholders
        (``channelInfo``/``radioCap``/``devCap``). Wired devices (switches and
        gateways) override this with their own capability descriptor - see
        ``WiredDevice``.
        """
        from ..protocol import adoption

        return adoption.build_negotiation_body(
            self.manage_device_info(),
            controller_id,
            country_code=self.country_code,
            components_v2=self.manage_components_v2(),
        )

    def build_discovery_message(self) -> DeviceMessage:
        if not self.controller_id:
            raise ValueError(
                f"device {self.name!r} has no controller_id set; "
                "fetch it from the controller (GET /api/info) before announcing"
            )
        header = MessageHeader(
            mac=self.mac,
            type=constants.MESSAGE_TYPE_DISCOVERY,
            device=self.device_type,
            version=self.protocol_version,
        )
        body = self.build_discovery_body()
        return DeviceMessage(header=header, body=body)

    def to_state_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mac": self.mac,
            "model": self.identity.model,
            "device_type": self.device_type,
            "ip": self.ip,
            "uptime_start": self.uptime_start,
        }
