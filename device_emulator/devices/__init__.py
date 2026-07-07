"""Emulated network device classes."""
from .base import Device, DeviceIdentity
from .eap import EapDevice
from .gateway import GatewayDevice
from .registry import build_device
from .switch import SwitchDevice
from .wired import WiredDevice

__all__ = [
    "Device",
    "DeviceIdentity",
    "WiredDevice",
    "EapDevice",
    "SwitchDevice",
    "GatewayDevice",
    "build_device",
]
