"""Emulated managed switch."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..protocol import constants
from ..protocol.discovery import build_switch_discovery_body
from . import switch_profile
from .wired import WiredDevice


@dataclass
class SwitchDevice(WiredDevice):
    port_num: int = 8
    stack_id: str = ""

    profile = switch_profile
    # Switches echo the controller id back as destOmadacId in the negotiation.
    include_dest_omadac_id = True

    def __post_init__(self) -> None:
        self.device_type = constants.DEVICE_TYPE_SWITCH
        self._apply_wired_profile()

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
