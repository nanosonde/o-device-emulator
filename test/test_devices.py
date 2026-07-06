"""Unit tests for device classes and the config-driven device registry."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from device_emulator.devices.eap import EapDevice
from device_emulator.devices.gateway import GatewayDevice
from device_emulator.devices.registry import build_device
from device_emulator.devices.switch import SwitchDevice


def test_build_device_ap():
    device = build_device(
        {
            "name": "lab-eap-01",
            "type": "ap",
            "model": "EAP245",
            "mac": "02:15:6d:00:00:20",
            "ip": "192.168.56.53",
        }
    )
    assert isinstance(device, EapDevice)
    assert device.device_type == "ap"
    assert device.mac == "02-15-6D-00-00-20"


def test_build_device_switch():
    device = build_device(
        {"name": "sw-01", "type": "switch", "mac": "02:15:6d:00:00:10", "ip": "192.168.56.60"}
    )
    assert isinstance(device, SwitchDevice)
    assert device.device_type == "switch"


def test_build_device_gateway():
    device = build_device(
        {"name": "gw-01", "type": "gateway", "mac": "02:15:6d:00:00:30", "ip": "192.168.56.70"}
    )
    assert isinstance(device, GatewayDevice)
    assert device.device_type == "gateway"


def test_build_device_requires_non_loopback_ip():
    with pytest.raises(ValueError):
        build_device({"name": "bad", "type": "ap", "mac": "02:15:6d:00:00:99", "ip": "auto"})


def test_build_device_requires_mac():
    with pytest.raises(ValueError):
        build_device({"name": "bad", "type": "ap", "ip": "192.168.56.99"})


def test_discovery_message_requires_controller_id():
    device = build_device(
        {"name": "lab-eap-01", "type": "ap", "mac": "02:15:6d:00:00:20", "ip": "192.168.56.53"}
    )
    with pytest.raises(ValueError):
        device.build_discovery_message()

    device.controller_id = "6e4b42bfc99261c0e09bec9f8688d9c7"
    message = device.build_discovery_message()
    assert message.header.mac == device.mac
