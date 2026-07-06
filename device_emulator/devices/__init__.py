"""Emulated network device classes."""
from .base import Device, DeviceIdentity
from .eap import EapDevice
from .gateway import GatewayDevice
from .registry import build_device
from .switch import SwitchDevice

__all__ = [
    "Device",
    "DeviceIdentity",
    "EapDevice",
    "SwitchDevice",
    "GatewayDevice",
    "build_device",
]
