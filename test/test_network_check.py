"""Unit tests for the Network Check (device-monitor) feature:

* ``services/network_probe.handle_probe`` synthetic ping/traceroute shapes.
* ``protocol/device_monitor`` ECSP framing + protobuf encode/decode round-trip
  for a probe request/response.
* The ``monitorServer`` SET-key lifecycle: ``Device.build_set_response`` acks
  the SET body and ``Device.handle_monitor_server`` stores the config.
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.devices.registry import build_device
from device_emulator.protocol import device_monitor as dmp
from device_emulator.services import network_probe


def _make_ap():
    return build_device(
        {
            "name": "ap-01",
            "type": "ap",
            "model": "EAP245",
            "mac": "AA-BB-CC-DD-EE-01",
            "ip": "192.168.56.53",
        }
    )


# -- network_probe.handle_probe ----------------------------------------------

def test_ping_response_shape():
    device = _make_ap()
    data = json.dumps({"target": "8.8.8.8"}).encode()
    out = network_probe.handle_probe(device, "/ping", data)
    result = json.loads(out)
    assert result["status"] == "success"
    assert result["target"] == "8.8.8.8"
    assert result["ip"] == "8.8.8.8"
    assert result["packetsSent"] == 4
    assert result["packetsReceived"] == 4
    assert result["packetsLost"] == 0
    assert result["lossRate"] == 0
    assert len(result["rtts"]) == 4
    assert result["minRtt"] <= result["avgRtt"] <= result["maxRtt"]


def test_ping_response_defaults_target_when_no_payload():
    device = _make_ap()
    out = network_probe.handle_probe(device, "/ping", b"")
    result = json.loads(out)
    # The default target is 8.8.8.8 when no JSON payload is sent.
    assert result["target"] == "8.8.8.8"
    assert result["status"] == "success"


def test_traceroute_response_shape():
    device = _make_ap()
    data = json.dumps({"target": "1.1.1.1"}).encode()
    out = network_probe.handle_probe(device, "/traceroute", data)
    result = json.loads(out)
    assert result["status"] == "success"
    assert result["target"] == "1.1.1.1"
    assert result["hopCount"] == len(result["hops"])
    # The last hop is the target.
    assert result["hops"][-1]["ip"] == "1.1.1.1"
    for hop in result["hops"]:
        assert len(hop["rtts"]) == 3
        assert hop["status"] == "success"


def test_unknown_probe_returns_empty():
    device = _make_ap()
    assert network_probe.handle_probe(device, "/unknown", b"") == b""


def test_ping_rtt_is_deterministic_for_same_mac():
    device = _make_ap()
    out1 = json.loads(network_probe.handle_probe(device, "/ping", b""))
    out2 = json.loads(network_probe.handle_probe(device, "/ping", b""))
    assert out1["rtts"] == out2["rtts"]


# -- protocol/device_monitor codec -------------------------------------------

def test_monitor_message_round_trip():
    """A monitor message with header fields + data bytes encodes and decodes
    back to the same values."""
    mac = bytes.fromhex("AABBCCDDEE01")
    token = b"test-token"
    hdr = dmp.MonitorMessageHeader(
        mac=mac,
        token=token,
        path="/ping",
        version="1.0",
        msg_type=dmp.MSG_EMPTY,
        seq=42,
        epoch_ms=1_700_000_000_000,
    )
    msg = dmp.MonitorMessage(header=hdr, data=b'{"target":"8.8.8.8"}')
    encoded = msg.encode()
    decoded = dmp.MonitorMessage.decode(encoded)
    assert decoded.header.mac == mac
    assert decoded.header.token == token
    assert decoded.header.path == "/ping"
    assert decoded.header.version == "1.0"
    assert decoded.header.msg_type == dmp.MSG_EMPTY
    assert decoded.header.seq == 42
    assert decoded.header.epoch_ms == 1_700_000_000_000
    assert decoded.data == b'{"target":"8.8.8.8"}'


def test_ecsp_packet_framing_round_trip():
    """pack_ecsp_packet prepends a 4-byte BE length; read_ecsp_packet reads it
    back from a connected socket pair."""
    hdr = dmp.MonitorMessageHeader(
        mac=bytes.fromhex("AABBCCDDEE01"),
        token=b"tok",
        path="/",
        version="1.0",
        msg_type=dmp.MSG_EMPTY,
        seq=1,
    )
    msg = dmp.MonitorMessage(header=hdr, data=b"")
    pkt = dmp.pack_ecsp_packet(msg.encode())
    # 4-byte BE length prefix + payload.
    assert int.from_bytes(pkt[:4], "big") == len(pkt) - 4

    a, b = socket.socketpair()
    try:
        a.sendall(pkt)
        decoded = dmp.read_ecsp_packet(b)
        assert decoded is not None
        assert decoded.header.mac == bytes.fromhex("AABBCCDDEE01")
        assert decoded.header.path == "/"
        assert decoded.header.seq == 1
    finally:
        a.close()
        b.close()


def test_build_register_message_has_required_fields():
    pkt = dmp.build_register_message(
        mac_bytes=bytes.fromhex("AABBCCDDEE01"),
        token_bytes=b"my-token",
        path="/",
        version="1.0",
    )
    msg = dmp.MonitorMessage.decode(pkt[4:])
    assert msg.header.mac == bytes.fromhex("AABBCCDDEE01")
    assert msg.header.token == b"my-token"
    assert msg.header.path == "/"
    assert msg.header.version == "1.0"
    assert msg.header.msg_type == dmp.MSG_EMPTY


# -- monitorServer SET-key lifecycle -----------------------------------------

def test_device_set_response_acks_monitor_server():
    device = _make_ap()
    resp = device.build_set_response({
        "sequenceId": 7,
        "configVersion": 3,
        "monitorServer": {"token": "abc", "port": 29817, "path": "/"},
    })
    assert resp["errcode"] == 0
    assert resp["sequenceId"] == 7
    assert resp["configVersion"] == 3


def test_device_set_response_acks_package_capture():
    """A packageCapture SET push must be acked with a ``packageCapture``
    sub-object carrying ``errCode: 0`` — without it the controller logs
    ``fail to send start package capture request ... packageCaptureConfigResp=null``
    and the UI shows "No device response"."""
    device = _make_ap()
    resp = device.build_set_response({
        "sequenceId": 9,
        "packageCapture": {
            "operation": "start",
            "nid": "abc",
            "captureInfo": {"duration": 5, "totalSize": 1024},
        },
    })
    assert resp["errcode"] == 0
    assert resp["sequenceId"] == 9
    assert resp["packageCapture"] == {"errCode": 0}


def test_device_set_response_no_package_capture_ack_when_absent():
    device = _make_ap()
    resp = device.build_set_response({"sequenceId": 1})
    assert "packageCapture" not in resp


def test_handle_monitor_server_stores_config():
    device = _make_ap()
    cfg = {"token": "abc123", "port": 29817, "protocol": "tls", "path": "/"}
    device.handle_monitor_server(cfg)
    assert device.monitor_server_config == cfg
    # Stored as a copy, not a reference.
    cfg["token"] = "changed"
    assert device.monitor_server_config["token"] == "abc123"


def test_handle_monitor_server_disabled_when_no_token():
    device = _make_ap()
    device.handle_monitor_server({"port": 29817})
    # An empty token is treated as "disabled" — the config is still stored.
    assert device.monitor_server_config == {"port": 29817}


def test_device_monitor_service_constructs_and_parses_config():
    """The DeviceMonitorService parses the monitorServer config fields
    (token/port/protocol/path) without starting a thread (no network)."""
    from device_emulator.services.device_monitor import DeviceMonitorService

    device = _make_ap()
    svc = DeviceMonitorService(
        device,
        controller_host="127.0.0.1",
        token="abc123",
        monitor_port=29817,
        use_tls=True,
        path="/",
    )
    assert svc.token == "abc123"
    assert svc.monitor_port == 29817
    assert svc.use_tls is True
    assert svc.path == "/"
    assert not svc.is_running()


def test_manage_service_has_monitor_server_callback_param():
    """ManageService exposes on_monitor_server / on_package_capture ctor
    params so the runner can wire the SET-key lifecycle."""
    from device_emulator.services.manage import ManageService

    device = _make_ap()
    device.controller_id = "cid"
    captured: dict = {}

    def on_ms(dev, cfg):
        captured["dev"] = dev
        captured["cfg"] = cfg

    svc = ManageService(
        device,
        controller_host="127.0.0.1",
        controller_id="cid",
        on_monitor_server=on_ms,
    )
    assert svc.on_monitor_server is on_ms
    # The callback is invoked with the device + config.
    svc.on_monitor_server(device, {"token": "x"})
    assert captured["dev"] is device
    assert captured["cfg"] == {"token": "x"}