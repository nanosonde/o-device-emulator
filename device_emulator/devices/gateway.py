"""Emulated gateway / router."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..protocol import constants
from ..protocol.discovery import build_gateway_discovery_body
from . import gateway_profile
from .wired import WiredDevice


def _derive_port_macs(mac: str, count: int) -> list[dict[str, Any]]:
    """Derive per-WAN-port default MACs from the device MAC by incrementing
    the last octet (so they are stable and consistent with the device)."""
    base = mac.split("-")
    try:
        last = int(base[-1], 16)
    except ValueError:
        last = 0
    macs = []
    for port in range(1, count + 1):
        octet = (last + port) & 0xFF
        macs.append({"defMac": "-".join(base[:-1] + [f"{octet:02X}"]), "portId": port})
    return macs


@dataclass
class GatewayDevice(WiredDevice):
    port_num: int = 5
    wireless: int = 0
    certified_version: str = "1.0"
    # Gateways report modest default utilisation.
    cpu_util: int = 1
    mem_util: int = 32

    profile = gateway_profile

    def __post_init__(self) -> None:
        self.device_type = constants.DEVICE_TYPE_GATEWAY
        self._apply_wired_profile()

    def build_discovery_body(self) -> dict[str, Any]:
        assert self.controller_id is not None
        return build_gateway_discovery_body(
            ip=self.ip,
            model=self.identity.model,
            model_version=self.identity.model_version,
            firmware_version=self.identity.firmware_version,
            certified_version=self.certified_version,
            hardware_version=self.identity.hardware_version,
            controller_id=self.controller_id,
            up_time_seconds=self.uptime_seconds,
            port_num=self.port_num,
            wireless=self.wireless,
            country_code=self.country_code,
        )

    def _extra_device_info(self) -> dict[str, Any]:
        # Gateways report a "<model> v<hw>" hwVer plus MAC/port identity fields.
        return {
            "hwVer": f"{self.identity.model} v{self.identity.hardware_version}",
            "lanMac": self.mac,
            "wanDefaultMacs": _derive_port_macs(self.mac, max(0, self.port_num - 1)),
        }
