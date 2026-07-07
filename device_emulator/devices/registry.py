"""Build Device instances from YAML-sourced config dicts."""
from __future__ import annotations

from typing import Any

from ..protocol import constants
from .base import Device, DeviceIdentity
from .eap import EapDevice
from .gateway import GatewayDevice
from .switch import SwitchDevice

_TYPE_MAP = {
    constants.DEVICE_TYPE_AP: EapDevice,
    "eap": EapDevice,
    "access_point": EapDevice,
    constants.DEVICE_TYPE_SWITCH: SwitchDevice,
    constants.DEVICE_TYPE_GATEWAY: GatewayDevice,
    "router": GatewayDevice,
}

_DEFAULT_MODEL_BY_TYPE = {
    EapDevice: "EAP245",
    SwitchDevice: "TL-SG3210",
    GatewayDevice: "ER605",
}


def build_device(cfg: dict[str, Any]) -> Device:
    """Construct a Device subclass instance from a single `devices:` entry."""
    try:
        name = cfg["name"]
        mac = cfg["mac"]
    except KeyError as exc:
        raise ValueError(f"device config missing required field: {exc}") from exc

    device_type_key = cfg.get("type", constants.DEVICE_TYPE_AP)
    try:
        device_cls = _TYPE_MAP[device_type_key]
    except KeyError as exc:
        raise ValueError(f"unsupported device type: {device_type_key!r}") from exc

    identity = DeviceIdentity(
        name=name,
        mac=mac,
        model=cfg.get("model", _DEFAULT_MODEL_BY_TYPE[device_cls]),
        model_version=cfg.get("model_version", "1.0"),
        firmware_version=cfg.get("firmware", "1.0.0 Build 20240101 Rel.12345"),
        hardware_version=cfg.get("hardware_version", "1.0"),
    )
    ip = cfg.get("ip")
    if not ip or ip == "auto":
        raise ValueError(
            f"device {name!r}: an explicit non-loopback 'ip' is required "
            "(auto-detection is not yet implemented)"
        )

    kwargs: dict[str, Any] = {
        "identity": identity,
        "ip": ip,
        "country_code": cfg.get("country_code", 0),
        "uplink": cfg.get("uplink"),
        "uplink_port": cfg.get("uplink_port"),
        "local_uplink_port": cfg.get("local_uplink_port"),
    }
    if device_cls is SwitchDevice:
        kwargs["port_num"] = cfg.get("port_num", 8)
    elif device_cls is GatewayDevice:
        kwargs["port_num"] = cfg.get("port_num", 5)
        kwargs["wireless"] = cfg.get("wireless", 0)

    return device_cls(**kwargs)
