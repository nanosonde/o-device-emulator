"""Emulated gateway / router."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..protocol import constants
from ..protocol.discovery import build_gateway_discovery_body
from .base import Device


@dataclass
class GatewayDevice(Device):
    port_num: int = 5
    wireless: int = 0
    certified_version: str = "1.0"

    def __post_init__(self) -> None:
        self.device_type = constants.DEVICE_TYPE_GATEWAY

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
