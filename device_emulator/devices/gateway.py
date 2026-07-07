"""Emulated gateway / router."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..protocol import constants
from ..protocol.discovery import build_gateway_discovery_body
from .base import Device, format_uptime
from . import gateway_profile


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
class GatewayDevice(Device):
    port_num: int = 5
    wireless: int = 0
    certified_version: str = "1.0"
    cpu_util: int = 1
    mem_util: int = 32

    def __post_init__(self) -> None:
        self.device_type = constants.DEVICE_TYPE_GATEWAY
        # Gateways are classified at ECSP protocol version 2.2 (see
        # doc/DEVICE_PROTOCOL.md §7.5).
        self.protocol_version = "2.2.0"

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

    def manage_device_info(self) -> dict[str, Any]:
        info = dict(gateway_profile.DEVICE_INFO_TEMPLATE)
        info.update(
            {
                "model": self.identity.model,
                "modelVer": self.identity.model_version,
                "fwVer": self.identity.firmware_version,
                "hwVer": f"{self.identity.model} v{self.identity.hardware_version}",
                "ip": self.ip,
                "lanMac": self.mac,
                "wanDefaultMacs": _derive_port_macs(self.mac, max(0, self.port_num - 1)),
                "time": format_uptime(self.uptime_seconds),
                "cu": self.cpu_util,
                "mu": self.mem_util,
            }
        )
        return info

    def manage_components_v2(self) -> dict[str, str]:
        return dict(gateway_profile.COMPONENTS_V2)

    def build_manage_negotiation_body(self, controller_id: str) -> dict[str, Any]:
        return {
            "key": "",
            "configVersion": "0",
            "deviceInfo": self.manage_device_info(),
            "controllerSetting": {"controllerId": controller_id},
            "components": "",
            "components_v2": self.manage_components_v2(),
            "devCap": dict(gateway_profile.DEV_CAP),
            "deviceMisc": dict(gateway_profile.DEVICE_MISC),
        }
