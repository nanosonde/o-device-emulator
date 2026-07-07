"""Shared base for wired managed devices (switches and gateways).

Switches and gateways negotiate the same way and differ from access points:

- they advertise ECSP protocol version 2.2 (APs use 2.3);
- their management-channel ``deviceInfo`` uses the short-name field set
  (``model``/``modelVer``/``fwVer``/``hwVer``/``time``/``cu``/``mu``) plus a few
  type-specific identity fields, rather than the access point's long-name set;
- their negotiation body carries a type-specific capability descriptor
  (``devCap``) and ``deviceMisc`` instead of the access point's empty
  ``channelInfo``/``radioCap`` placeholders.

This base captures that shared shape. A concrete wired device supplies a
``profile`` module (see ``switch_profile`` / ``gateway_profile``) with
``PROTOCOL_VERSION``, ``COMPONENTS_V2``, ``DEV_CAP``, ``DEVICE_MISC`` and
``DEVICE_INFO_TEMPLATE``, and may add extra ``deviceInfo`` fields by overriding
``_extra_device_info()``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import Device, format_uptime


@dataclass
class WiredDevice(Device):
    # CPU / memory utilisation reported in deviceInfo (cu / mu).
    cpu_util: int = 0
    mem_util: int = 45

    # Class attributes (NOT dataclass fields - deliberately un-annotated) set
    # by concrete subclasses. ``profile`` is a module exposing PROTOCOL_VERSION,
    # COMPONENTS_V2, DEV_CAP, DEVICE_MISC and DEVICE_INFO_TEMPLATE.
    profile = None
    include_dest_omadac_id = False

    def _apply_wired_profile(self) -> None:
        """Set the advertised protocol version from the profile. Call from a
        subclass ``__post_init__`` after setting ``device_type``."""
        self.protocol_version = self.profile.PROTOCOL_VERSION

    def _extra_device_info(self) -> dict[str, Any]:
        """Type-specific ``deviceInfo`` fields merged on top of the common
        short-name set (empty by default; gateways add MAC/port fields)."""
        return {}

    def manage_device_info(self) -> dict[str, Any]:
        info = dict(self.profile.DEVICE_INFO_TEMPLATE)
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
        info.update(self._extra_device_info())
        return info

    def manage_components_v2(self) -> dict[str, str]:
        return dict(self.profile.COMPONENTS_V2)

    def build_manage_negotiation_body(self, controller_id: str) -> dict[str, Any]:
        controller_setting: dict[str, Any] = {"controllerId": controller_id}
        if self.include_dest_omadac_id:
            controller_setting["destOmadacId"] = controller_id
        return {
            "key": "",
            "configVersion": "0",
            "deviceInfo": self.manage_device_info(),
            "controllerSetting": controller_setting,
            "components": "",
            "components_v2": self.manage_components_v2(),
            "devCap": dict(self.profile.DEV_CAP),
            "deviceMisc": dict(self.profile.DEVICE_MISC),
        }
