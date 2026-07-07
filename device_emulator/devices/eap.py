"""Emulated access point."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..protocol import constants
from ..protocol.discovery import build_ap_discovery_body
from .base import Device
from .eap_components import EAP_COMPONENTS_V2


@dataclass
class EapDevice(Device):
    wireless_linked: bool = False
    cpu_util: int = 5
    mem_util: int = 30

    def __post_init__(self) -> None:
        self.device_type = constants.DEVICE_TYPE_AP

    def manage_device_info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model": self.identity.model,
            "modelVersion": self.identity.model_version,
            "firmwareVersion": self.identity.firmware_version,
            "hardwareVersion": self.identity.hardware_version,
            "upTime": str(self.uptime_seconds),
            "cpuUti": self.cpu_util,
            "memUti": self.mem_util,
            "wirelessLinked": self.wireless_linked,
            "p2p": False,
        }

    def manage_components_v2(self) -> dict[str, str]:
        return dict(EAP_COMPONENTS_V2)

    def build_discovery_body(self) -> dict[str, Any]:
        assert self.controller_id is not None
        return build_ap_discovery_body(
            ip=self.ip,
            model=self.identity.model,
            model_version=self.identity.model_version,
            firmware_version=self.identity.firmware_version,
            hardware_version=self.identity.hardware_version,
            name=self.name,
            controller_id=self.controller_id,
            up_time_seconds=self.uptime_seconds,
            cpu_util=self.cpu_util,
            mem_util=self.mem_util,
            wireless_linked=self.wireless_linked,
            p2p=False,
            country_code=self.country_code,
        )
