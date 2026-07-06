"""Unit tests for the protocol layer (framing, message envelope, discovery
body builders). These don't require a live controller - see
test/sim_cli.py / doc/DEVICE_PROTOCOL.md for live verification.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.protocol import constants
from device_emulator.protocol.discovery import (
    build_ap_discovery_body,
    build_gateway_discovery_body,
    build_switch_discovery_body,
)
from device_emulator.protocol.framing import decode_frame, encode_frame
from device_emulator.protocol.messages import DeviceMessage, MessageHeader


def test_frame_round_trip():
    payload = b'{"header":{},"body":{}}'
    framed = encode_frame(payload)
    assert framed[:4] == len(payload).to_bytes(4, "big")
    assert decode_frame(framed) == payload


def test_frame_round_trip_various_lengths():
    for length in (0, 1, 40, 1000):
        payload = b"x" * length
        assert decode_frame(encode_frame(payload)) == payload


def test_message_envelope_shape():
    header = MessageHeader(mac="AA-BB-CC-DD-EE-FF", type=constants.MESSAGE_TYPE_DISCOVERY, device="ap")
    message = DeviceMessage(header=header, body={"deviceInfo": {"ip": "1.2.3.4"}})
    raw = message.to_json_bytes()
    envelope = json.loads(raw)
    assert set(envelope.keys()) == {"header", "body"}
    assert envelope["header"]["mac"] == "AA-BB-CC-DD-EE-FF"
    assert envelope["header"]["type"] == constants.MESSAGE_TYPE_DISCOVERY
    assert envelope["header"]["device"] == "ap"
    assert envelope["header"]["version"]  # required, must be non-empty
    assert envelope["body"]["deviceInfo"]["ip"] == "1.2.3.4"


def test_ap_discovery_body_confirmed_shape():
    """Field set mirrors the exact payload verified against a live
    controller (see doc/DEVICE_PROTOCOL.md §4)."""
    body = build_ap_discovery_body(
        ip="192.168.56.53",
        model="EAP245",
        model_version="3.0",
        firmware_version="5.1.0 Build 20230101 Rel.12345",
        hardware_version="3.0",
        name="fake-eap-01",
        controller_id="6e4b42bfc99261c0e09bec9f8688d9c7",
    )
    assert body["deviceInfo"]["p2p"] is False
    assert body["deviceMisc"]["customizeRegion"] == 0
    assert body["controllerSetting"]["controllerId"] == "6e4b42bfc99261c0e09bec9f8688d9c7"


def test_switch_discovery_body_uses_controller_key_not_controllerSetting():
    """Regression test for the confirmed AP-vs-switch/gateway JSON key
    inconsistency ("controllerSetting" vs "controller", and "controllerId"
    vs "id" for the nested id field)."""
    body = build_switch_discovery_body(
        ip="192.168.56.60",
        model="TL-SG3210",
        model_version="1.0",
        firmware_version="1.0.0 Build 20230101 Rel.12345",
        hardware_version="1.0",
        controller_id="abc123",
    )
    assert "controller" in body
    assert "controllerSetting" not in body
    assert body["controller"]["id"] == "abc123"
    assert body["deviceInfo"]["modelVer"] == "1.0"
    assert body["deviceInfo"]["fwVer"].startswith("1.0.0")


def test_gateway_discovery_body_uses_controller_key():
    body = build_gateway_discovery_body(
        ip="192.168.56.70",
        model="ER605",
        model_version="1.0",
        firmware_version="1.0.0 Build 20230101 Rel.12345",
        certified_version="1.0",
        hardware_version="1.0",
        controller_id="abc123",
    )
    assert "controller" in body
    assert "controllerSetting" not in body
    assert body["controller"]["id"] == "abc123"
    assert body["deviceInfo"]["cerVer"] == "1.0"
