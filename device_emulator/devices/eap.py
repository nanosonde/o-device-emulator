"""Emulated access point."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..protocol import constants
from ..protocol.discovery import build_ap_discovery_body
from .base import Device


@dataclass
class EapDevice(Device):
    wireless_linked: bool = False
    cpu_util: int = 5
    mem_util: int = 30

    def __post_init__(self) -> None:
        self.device_type = constants.DEVICE_TYPE_AP

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
