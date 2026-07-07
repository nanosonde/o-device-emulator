"""Emulated managed switch."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..protocol import constants
from ..protocol.discovery import build_switch_discovery_body
from .base import Device, format_uptime
from . import switch_profile


@dataclass
class SwitchDevice(Device):
    port_num: int = 8
    stack_id: str = ""
    cpu_util: int = 0
    mem_util: int = 45

    def __post_init__(self) -> None:
        self.device_type = constants.DEVICE_TYPE_SWITCH
        # Switches are classified at ECSP protocol version 2.2 (see
        # doc/DEVICE_PROTOCOL.md §7.5).
        self.protocol_version = "2.2.0"

    def build_discovery_body(self) -> dict[str, Any]:
        assert self.controller_id is not None
        return build_switch_discovery_body(
            ip=self.ip,
            model=self.identity.model,
            model_version=self.identity.model_version,
            firmware_version=self.identity.firmware_version,
            hardware_version=self.identity.hardware_version,
            controller_id=self.controller_id,
            up_time_seconds=self.uptime_seconds,
            port_num=self.port_num,
            stack_id=self.stack_id,
        )

    def manage_device_info(self) -> dict[str, Any]:
        info = dict(switch_profile.DEVICE_INFO_TEMPLATE)
        info.update(
            {
                "model": self.identity.model,
                "modelVer": self.identity.model_version,
                "fwVer": self.identity.firmware_version,
                "hwVer": self.identity.hardware_version,
                "ip": self.ip,
                "time": format_uptime(self.uptime_seconds),
                "cu": self.cpu_util,
                "mu": self.mem_util,
            }
        )
        return info

    def manage_components_v2(self) -> dict[str, str]:
        return dict(switch_profile.COMPONENTS_V2)

    def build_manage_negotiation_body(self, controller_id: str) -> dict[str, Any]:
        return {
            "key": "",
            "configVersion": "0",
            "deviceInfo": self.manage_device_info(),
            "controllerSetting": {
                "controllerId": controller_id,
                "destOmadacId": controller_id,
            },
            "components": "",
            "components_v2": self.manage_components_v2(),
            "devCap": dict(switch_profile.DEV_CAP),
            "deviceMisc": dict(switch_profile.DEVICE_MISC),
        }
