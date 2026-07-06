"""Build Device instances from YAML-sourced config dicts."""
from __future__ import annotations

import socket
from typing import Any

from ..protocol import constants
from .base import Device, DeviceIdentity
from .eap import EapDevice
from .gateway import GatewayDevice
from .olt import OltDevice
from . import olt_profile
from .switch import SwitchDevice

_TYPE_MAP = {
    constants.DEVICE_TYPE_AP: EapDevice,
    "eap": EapDevice,
    "access_point": EapDevice,
    constants.DEVICE_TYPE_SWITCH: SwitchDevice,
    constants.DEVICE_TYPE_GATEWAY: GatewayDevice,
    "router": GatewayDevice,
    constants.DEVICE_TYPE_OLT: OltDevice,
}

_DEFAULT_MODEL_BY_TYPE = {
    EapDevice: "EAP245",
    SwitchDevice: "TL-SG3210",
    GatewayDevice: "ER605",
    OltDevice: olt_profile.DEFAULT_MODEL,
}


def _detect_local_ip() -> str:
    """Auto-detect the host's primary non-loopback IPv4 address.

    Opens a UDP socket to a public DNS address (no packets are actually sent
    on a UDP socket) and reads the bound local address. Falls back to
    ``127.0.0.1`` if no suitable interface is found.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Connect to a non-local address to determine the primary
            # interface IP. No packets are sent on a UDP socket.
            sock.connect(("8.8.8.8", 53))
            ip = sock.getsockname()[0]
        finally:
            sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return "127.0.0.1"


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
        ip = _detect_local_ip()

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
        # Default port_num from the model's profile DEV_CAP if not specified.
        from . import gateway_profiles
        _gw_profile = gateway_profiles.get_profile(identity.model)
        _default_port_num = _gw_profile.DEVICE_MISC.get("portNum", 5)
        kwargs["port_num"] = cfg.get("port_num", _default_port_num)
        kwargs["wireless"] = cfg.get("wireless", 0)
    elif device_cls is EapDevice:
        kwargs["lan_ports"] = cfg.get("lan_ports", 1)
        kwargs["supports_poe"] = cfg.get("supports_poe", True)
        kwargs["wireless_uplink"] = cfg.get("wireless_uplink", False)
        client_count = cfg.get("wireless_client_count", 5)
        if isinstance(client_count, bool) or not isinstance(client_count, int) or not 0 <= client_count <= 5:
            raise ValueError(
                f"device {name!r}: 'wireless_client_count' must be an int 0-5, "
                f"got {client_count!r}"
            )
        kwargs["wireless_client_count"] = client_count
    elif device_cls is OltDevice:
        kwargs["pon_port_count"] = cfg.get("pon_port_count", 8)
        kwargs["lag_count"] = cfg.get("lag_count", 0)
        kwargs["oem_id"] = cfg.get("oem_id", "EBBE93F5D7E4DE41DD95F8C510575D7D")
        kwargs["hw_id"] = cfg.get("hw_id", "93198DDF77EAF24F93AFD110A07C48AB")

    return device_cls(**kwargs)
