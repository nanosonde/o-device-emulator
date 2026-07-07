"""Body builders for the management-channel (adoption) handshake.

These construct the JSON `body` objects the device sends over the TLS
management channel once adoption has been initiated (see
doc/DEVICE_PROTOCOL.md §8). Field sets were validated live against a real
controller for an access point; switch/gateway variants share the same
envelope but their per-type deviceInfo details are not separately confirmed.
"""
from __future__ import annotations

import uuid
from typing import Any


def new_verify_nonce() -> str:
    """Return a fresh device verify nonce (`randomKeyForSystemVerify`).

    Must be a full 36-character hyphenated UUID: newer controllers (ECSP
    1.7.x, e.g. controller v6.2) reject a `randomKeyForSystemVerify` shorter
    than 36 characters. A 36-char UUID is also accepted by older controllers,
    so this is backward-compatible.
    """
    return str(uuid.uuid4())


def build_pre_connect_body(rebuild: int = 0) -> dict[str, Any]:
    """First device->controller message on the management channel.

    Requests the verify nonce (and the username the controller expects).
    """
    return {"needUsername": True, "rebuild": rebuild}


def build_device_verify_body(auth: str, random_key_for_system_verify: str) -> dict[str, Any]:
    """Device->controller verify message.

    `auth` proves the device knows the credential; `random_key_for_system_verify`
    is the device's own nonce the controller must answer to prove itself.
    """
    return {"auth": auth, "randomKeyForSystemVerify": random_key_for_system_verify}


def build_negotiation_body(
    device_info: dict[str, Any],
    controller_id: str,
    *,
    config_version: str = "0",
    country_code: int = 0,
    components_v2: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Device->controller negotiation message that carries the device's
    capabilities and the controller id it is now managed by.

    `components_v2` is the device's component manifest ({name: version}). The
    controller flags a device with an empty manifest as incompatible, so a
    realistic non-empty map should be supplied for the device to be reported
    as compatible.
    """
    return {
        "key": "",
        "configVersion": config_version,
        "deviceInfo": device_info,
        "controllerSetting": {"controllerId": controller_id},
        "components": "",
        "components_v2": components_v2 or {},
        "channelInfo": {},
        "radioCap": [],
        "devCap": {},
        "deviceMisc": {"customizeRegion": country_code},
    }


def build_inform_body(device_info: dict[str, Any], *, config_version: str = "0") -> dict[str, Any]:
    """Periodic device->controller heartbeat body sent once CONNECTED."""
    return {"deviceInfo": device_info, "configVersion": config_version}
