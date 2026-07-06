"""Discovery (header.type == MESSAGE_TYPE_DISCOVERY) body builders.

Body shapes differ per device type in non-obvious ways (see
doc/DEVICE_PROTOCOL.md §4) - most notably access points use the JSON key
"controllerSetting" while switches and gateways use "controller" for the
same concept. These builders encode those confirmed (AP) and best-effort
(switch/gateway) shapes precisely so callers don't have to track the
per-type quirks themselves.
"""
from __future__ import annotations

from typing import Any

from . import constants


def _format_uptime(seconds: int) -> str:
    """Format an uptime as "<N> days HH:MM:SS" (the form the controller
    expects in the discovery ``deviceInfo.time`` / ``upTime`` field). A raw
    ``str(seconds)`` is rejected by the controller's discovery handler
    because it splits by space and expects at least 2 parts."""
    days, rem = divmod(max(0, seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{days} days {hours:02d}:{minutes:02d}:{secs:02d}"


def build_ap_discovery_body(
    *,
    ip: str,
    model: str,
    model_version: str,
    firmware_version: str,
    hardware_version: str,
    name: str,
    controller_id: str,
    up_time_seconds: int = 0,
    cpu_util: int = 5,
    mem_util: int = 30,
    wireless_linked: bool = False,
    p2p: bool = False,
    country_code: int = 0,
) -> dict[str, Any]:
    """Build the confirmed-working AP discovery body.

    Field set validated live against a real controller (see
    doc/DEVICE_PROTOCOL.md §4): controllerSetting.controllerId and
    deviceMisc.customizeRegion are required, or the controller rejects and
    drops the packet.
    """
    return {
        "deviceInfo": {
            "ip": ip,
            "model": model,
            "modelVersion": model_version,
            "firmwareVersion": firmware_version,
            "hardwareVersion": hardware_version,
            "name": name,
            "upTime": _format_uptime(up_time_seconds),
            "cpuUti": cpu_util,
            "memUti": mem_util,
            "wirelessLinked": wireless_linked,
            "p2p": p2p,
        },
        "deviceMisc": {
            "customizeRegion": country_code,
        },
        "controllerSetting": {
            "controllerId": controller_id,
        },
    }


def build_switch_discovery_body(
    *,
    ip: str,
    model: str,
    model_version: str,
    firmware_version: str,
    hardware_version: str,
    controller_id: str,
    up_time_seconds: int = 0,
    port_num: int = 8,
    stack_id: str = "",
) -> dict[str, Any]:
    """Build a switch discovery body.

    CONFIRMED LIVE: for switches (and gateways) the nested id field's JSON
    key is "id", inside a top-level "controller" object - NOT the
    "controllerSetting" / "controllerId" pair that the access-point body
    uses. Using the access-point key names here makes the controller reject
    the packet. See doc/DEVICE_PROTOCOL.md §4.
    """
    return {
        "deviceInfo": {
            "ip": ip,
            "model": model,
            "modelVer": model_version,
            "fwVer": firmware_version,
            "hwVer": hardware_version,
            "time": _format_uptime(up_time_seconds),
        },
        "deviceMisc": {
            "portNum": port_num,
        },
        "controller": {
            "id": controller_id,
        },
        "stackId": stack_id,
    }


def build_gateway_discovery_body(
    *,
    ip: str,
    model: str,
    model_version: str,
    firmware_version: str,
    certified_version: str,
    hardware_version: str,
    controller_id: str,
    up_time_seconds: int = 0,
    port_num: int = 5,
    wireless: int = 0,
    country_code: int = 0,
) -> dict[str, Any]:
    """Build a gateway discovery body.

    CONFIRMED LIVE (via this package's own DiscoveryService, not just a
    hand-crafted probe): accepted on the first attempt, logged by the
    controller as a discovered device. Uses the same "controller"/"id"
    nested key as the switch body. See doc/DEVICE_PROTOCOL.md §4.3.
    """
    return {
        "deviceInfo": {
            "ip": ip,
            "model": model,
            "modelVer": model_version,
            "fwVer": firmware_version,
            "cerVer": certified_version,
            "hwVer": hardware_version,
            "time": _format_uptime(up_time_seconds),
            "wireless": wireless,
        },
        "deviceMisc": {
            "portNum": port_num,
            "customizeRegion": country_code,
        },
        "controller": {
            "id": controller_id,
        },
    }


def build_olt_discovery_body(
    *,
    ip: str,
    model: str,
    model_version: str,
    firmware_version: str,
    hardware_version: str,
    name: str,
    controller_id: str,
    up_time_seconds: int = 0,
    pon_port_count: int = 8,
    lag_count: int = 0,
    oem_id: str = "",
    hw_id: str = "",
    country_code: int = 0,
) -> dict[str, Any]:
    """Build an OLT (PON optical line terminal) discovery body.

    CONFIRMED against a live controller v6.2 (ECSP 1.8.6). The wire format
    follows the controller's OLT discovery message structure. The
    OLT uses the long-name `deviceInfo` keys (like an AP) BUT the
    **switch/gateway `controller`/`id` controller-id convention** (NOT the
    AP-style `controllerSetting`/`controllerId`): the controller-id field
    uses JSON key `"id"`, and the body wrapper uses JSON key `"controller"`
    for the controller-setting object.

    Key shape details:
    - `deviceInfo.upTime` is a JSON **integer**, not the string some
      other types use.
    - `deviceMisc` carries `modelType`, `category`, and an optional
      `supportCluster` — of these only `modelType`/`category` are sent
      (`supportCluster` is optional). It is NOT
      `ponPortCount`/`lagCount`/`customizeRegion`
      (those PON fields are carried in the *adopt* response, not discovery).
    - `ponPortCount`/`lagCount`/`oem_id`/`hw_id`/`country_code` are accepted by
      this builder for API symmetry but are NOT placed in the discovery body;
      they are reported later in the negotiation/adopt `deviceInfo`.
    - The controller sets the device `compatible` flag from the model name:
      only the controller's known OLT models are accepted as compatible. See
      `device_emulator/devices/olt_profile.py` for the valid model list.
    See doc/DEVICE_PROTOCOL.md §4.4.
    """
    return {
        "deviceInfo": {
            "ip": ip,
            "model": model,
            "modelVersion": model_version,
            "firmwareVersion": firmware_version,
            "hardwareVersion": hardware_version,
            "name": name,
            "upTime": int(up_time_seconds),
        },
        "deviceMisc": {
            "modelType": "NORMAL",
            "category": "OLT",
        },
        "controller": {
            "id": controller_id,
        },
    }


_BUILDERS = {
    constants.DEVICE_TYPE_AP: build_ap_discovery_body,
    constants.DEVICE_TYPE_SWITCH: build_switch_discovery_body,
    constants.DEVICE_TYPE_GATEWAY: build_gateway_discovery_body,
    constants.DEVICE_TYPE_OLT: build_olt_discovery_body,
}


def build_discovery_body(device_type: str, **kwargs: Any) -> dict[str, Any]:
    try:
        builder = _BUILDERS[device_type]
    except KeyError as exc:
        raise ValueError(f"unsupported device type for discovery: {device_type!r}") from exc
    return builder(**kwargs)
