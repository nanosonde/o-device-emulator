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


def test_eap_reports_nonempty_components_v2():
    # An empty component manifest makes the controller flag the AP as
    # incompatible, so the emulated AP must report a non-empty set.
    device = build_device(
        {"name": "ap", "type": "ap", "model": "EAP245", "mac": "AA-BB-CC-DD-EE-01", "ip": "192.168.56.5"}
    )
    comps = device.manage_components_v2()
    assert isinstance(comps, dict) and comps
    assert comps.get("ssid")  # a representative component is present


def test_switch_and_gateway_report_components_and_v22_version():
    # Switches and gateways also report a non-empty component manifest and are
    # classified at ECSP protocol version 2.2 (APs use 2.3).
    switch = build_device(
        {"name": "sw", "type": "switch", "model": "TL-SG3210", "mac": "AA-BB-CC-DD-EE-02", "ip": "192.168.56.6"}
    )
    gateway = build_device(
        {"name": "gw", "type": "gateway", "model": "ER605", "mac": "AA-BB-CC-DD-EE-03", "ip": "192.168.56.7"}
    )
    assert switch.manage_components_v2() and gateway.manage_components_v2()
    assert switch.protocol_version == "2.2.0"
    assert gateway.protocol_version == "2.2.0"
    # Switch/gateway device info uses the short-name shape.
    assert "modelVer" in switch.manage_device_info()
    assert gateway.manage_device_info()["lanMac"] == "AA-BB-CC-DD-EE-03"
    # Negotiation body carries the type-specific capability descriptor.
    assert "devCap" in switch.build_manage_negotiation_body("cid")
    assert "portInfos" in gateway.build_manage_negotiation_body("cid")["devCap"]
