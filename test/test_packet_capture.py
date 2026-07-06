"""Unit tests for the Packet Capture feature:

* ``protocol/pcap`` libpcap global header + record framing.
* Generated frames parse as valid Ethernet/IPv4 with the expected L4
  protocols (ARP/ICMP/TCP/UDP) and correct checksums.
* ``build_synthetic_packets`` is deterministic for a given MAC + captureInfo
  and scales packet count with ``duration``/``totalSize``.
* The ``packageCapture`` SET-key lifecycle: ``Device.handle_package_capture``
  stores the config.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.devices.registry import build_device
from device_emulator.protocol import pcap as pcap_mod


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


# -- libpcap global header ---------------------------------------------------

def test_pcap_global_header_is_valid():
    hdr = pcap_mod.pcap_global_header()
    assert len(hdr) == 24
    magic, major, minor, thiszone, sigfigs, snaplen, network = struct.unpack(
        "<IHHiIII", hdr
    )
    assert magic == pcap_mod.PCAP_MAGIC
    assert major == 2
    assert minor == 4
    assert thiszone == 0
    assert sigfigs == 0
    assert snaplen == pcap_mod.PCAP_SNAPLEN
    assert network == pcap_mod.LINKTYPE_ETHERNET


def test_write_pcap_round_trip_header_and_records():
    device = _make_ap()
    packets = pcap_mod.build_synthetic_packets(device, {"duration": 5, "totalSize": 64})
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "out.pcap")
        n = pcap_mod.write_pcap(path, packets)
        # Global header (24) + 16-byte record header per packet + frame bytes.
        expected = 24 + sum(16 + len(p.data) for p in packets)
        assert n == expected
        with open(path, "rb") as f:
            data = f.read()
        assert data[:24] == pcap_mod.pcap_global_header()
        # First record header ts_sec/ts_usec match the first packet.
        ts_sec, ts_usec, incl_len, orig_len = struct.unpack_from("<IIII", data, 24)
        assert ts_sec == packets[0].ts_sec
        assert ts_usec == packets[0].ts_usec
        assert incl_len == len(packets[0].data)
        assert orig_len == len(packets[0].data)


def test_to_pcap_bytes_matches_write_pcap():
    device = _make_ap()
    packets = pcap_mod.build_synthetic_packets(device, {})
    buf = pcap_mod.to_pcap_bytes(packets)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "x.pcap")
        pcap_mod.write_pcap(path, packets)
        with open(path, "rb") as f:
            file_bytes = f.read()
    assert buf == file_bytes


# -- frame parsing helpers ---------------------------------------------------

def _parse_ethernet(frame: bytes) -> tuple[bytes, bytes, int, bytes]:
    """Return (dst_mac, src_mac, ethertype, payload) for an Ethernet II frame."""
    dst = frame[:6]
    src = frame[6:12]
    ethertype = struct.unpack_from("!H", frame, 12)[0]
    return dst, src, ethertype, frame[14:]


def _ip_checksum_ok(header: bytes) -> bool:
    """Validate the IPv4 header checksum (header must be 20 bytes, no opts)."""
    assert len(header) >= 20
    stored = struct.unpack_from("!H", header, 10)[0]
    # Zero the checksum field and recompute.
    zeroed = header[:10] + b"\x00\x00" + header[12:]
    cs = pcap_mod._checksum(zeroed)
    return cs == stored


def _parse_ipv4(payload: bytes) -> tuple[int, int, str, str, bytes]:
    """Return (proto, total_length, src_ip, dst_ip, l4_payload) for an IPv4
    packet (no options)."""
    ihl = (payload[0] & 0x0F) * 4
    total_length = struct.unpack_from("!H", payload, 2)[0]
    proto = payload[9]
    src = ".".join(str(b) for b in payload[12:16])
    dst = ".".join(str(b) for b in payload[16:20])
    return proto, total_length, src, dst, payload[ihl:total_length]


# -- per-protocol frame validity --------------------------------------------

def test_arp_frame_is_valid():
    p = pcap_mod.build_arp(
        ts_sec=0, ts_usec=0,
        src_mac=b"\xaa\xbb\xcc\xdd\xee\x01", src_ip="192.168.1.10",
        dst_mac=b"\xff\xff\xff\xff\xff\xff", dst_ip="192.168.1.1",
        operation=1,
    )
    dst, src, ethertype, payload = _parse_ethernet(p.data)
    assert ethertype == pcap_mod.ETHERTYPE_ARP
    assert dst == b"\xff\xff\xff\xff\xff\xff"
    # ARP htype=1, ptype=0x0800, hlen=6, plen=4, op=1.
    htype, ptype, hlen, plen, op = struct.unpack_from("!HHBBH", payload, 0)
    assert htype == 1
    assert ptype == pcap_mod.ETHERTYPE_IPV4
    assert hlen == 6
    assert plen == 4
    assert op == 1
    # Ethernet II minimum payload is 46 bytes (frame padded by the builder).
    assert len(payload) >= 46


def test_icmp_echo_frame_has_valid_ip_and_icmp_checksums():
    p = pcap_mod.build_icmp_echo(
        ts_sec=0, ts_usec=0,
        src_mac=b"\xaa\xbb\xcc\xdd\xee\x01", src_ip="192.168.1.10",
        dst_mac=b"\x00\x11\x22\x33\x44\x55", dst_ip="192.168.1.1",
        icmp_type=8, identifier=0x1234, sequence=1, payload=b"hello",
    )
    _, _, ethertype, payload = _parse_ethernet(p.data)
    assert ethertype == pcap_mod.ETHERTYPE_IPV4
    proto, total_length, src, dst, l4 = _parse_ipv4(payload)
    assert proto == pcap_mod.IPPROTO_ICMP
    assert src == "192.168.1.10"
    assert dst == "192.168.1.1"
    assert total_length == 20 + len(l4)
    assert _ip_checksum_ok(payload[:20])
    # ICMP type=8, code=0, checksum valid, id, seq.
    icmp_type, code, cs, ident, seq = struct.unpack_from("!BBHHH", l4, 0)
    assert icmp_type == 8
    assert code == 0
    # Recompute the ICMP checksum (zero the checksum field at bytes 2-3) and compare.
    zeroed = l4[:2] + b"\x00\x00" + l4[4:]
    assert pcap_mod._checksum(zeroed) == cs
    assert ident == 0x1234
    assert seq == 1


def test_tcp_segment_has_valid_checksums():
    p = pcap_mod.build_tcp(
        ts_sec=0, ts_usec=0,
        src_mac=b"\xaa\xbb\xcc\xdd\xee\x01", src_ip="192.168.1.10", src_port=12345,
        dst_mac=b"\x00\x11\x22\x33\x44\x55", dst_ip="192.168.1.1", dst_port=443,
        seq=1000, ack=0, flags=0x02,  # SYN
        payload=b"",
    )
    _, _, ethertype, payload = _parse_ethernet(p.data)
    assert ethertype == pcap_mod.ETHERTYPE_IPV4
    proto, total_length, src, dst, l4 = _parse_ipv4(payload)
    assert proto == pcap_mod.IPPROTO_TCP
    assert src == "192.168.1.10"
    assert dst == "192.168.1.1"
    assert _ip_checksum_ok(payload[:20])
    # TCP header: sport(2) dport(2) seq(4) ack(4) data_offset(1) flags(1)
    # window(2) checksum(2) urgent(2). The builder packs data_offset=0x50
    # (5 dwords = 20-byte header) and flags as separate bytes.
    sport, dport, seq, ack, data_offset, flags, window, cs, urg = struct.unpack_from(
        "!HHIIBBHHH", l4, 0
    )
    assert sport == 12345
    assert dport == 443
    assert seq == 1000
    assert data_offset == 0x50  # 5 dwords = 20-byte header, no options
    assert flags == 0x02  # SYN
    # Recompute the TCP checksum (with pseudo-header) and compare.
    zeroed = l4[:16] + b"\x00\x00" + l4[18:]
    pseudo = pcap_mod._tcp_pseudo_header(src, dst, len(l4))
    assert pcap_mod._checksum(zeroed, start=pseudo) == cs


def test_udp_segment_has_valid_checksums():
    payload_data = b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01"
    p = pcap_mod.build_udp(
        ts_sec=0, ts_usec=0,
        src_mac=b"\xaa\xbb\xcc\xdd\xee\x01", src_ip="192.168.1.10", src_port=51235,
        dst_mac=b"\x00\x11\x22\x33\x44\x55", dst_ip="192.168.1.1", dst_port=53,
        payload=payload_data,
    )
    _, _, ethertype, payload = _parse_ethernet(p.data)
    assert ethertype == pcap_mod.ETHERTYPE_IPV4
    proto, total_length, src, dst, l4 = _parse_ipv4(payload)
    assert proto == pcap_mod.IPPROTO_UDP
    assert _ip_checksum_ok(payload[:20])
    sport, dport, length, cs = struct.unpack_from("!HHHH", l4, 0)
    assert sport == 51235
    assert dport == 53
    assert length == 8 + len(payload_data)
    # UDP checksum must be valid (the builder transmits 0xFFFF, never 0x0000).
    assert cs != 0
    zeroed = l4[:6] + b"\x00\x00" + l4[8:]
    pseudo = pcap_mod._udp_pseudo_header(src, dst, len(l4))
    assert pcap_mod._checksum(zeroed, start=pseudo) == cs


# -- synthetic capture generator --------------------------------------------

def test_build_synthetic_packets_contains_all_protocols():
    device = _make_ap()
    packets = pcap_mod.build_synthetic_packets(device, {})
    protos = set()
    for p in packets:
        _, _, ethertype, payload = _parse_ethernet(p.data)
        if ethertype == pcap_mod.ETHERTYPE_ARP:
            protos.add("ARP")
        elif ethertype == pcap_mod.ETHERTYPE_IPV4:
            proto, _, _, _, _ = _parse_ipv4(payload)
            protos.add({1: "ICMP", 6: "TCP", 17: "UDP"}[proto])
    assert {"ARP", "ICMP", "TCP", "UDP"} <= protos


def test_build_synthetic_packets_is_deterministic():
    device = _make_ap()
    a = pcap_mod.build_synthetic_packets(device, {"duration": 5, "totalSize": 64})
    b = pcap_mod.build_synthetic_packets(device, {"duration": 5, "totalSize": 64})
    assert len(a) == len(b)
    for pa, pb in zip(a, b):
        assert pa.data == pb.data


def test_build_synthetic_packets_scales_with_duration_and_size():
    device = _make_ap()
    small = pcap_mod.build_synthetic_packets(device, {"duration": 5, "totalSize": 64})
    large = pcap_mod.build_synthetic_packets(
        device, {"duration": 60, "totalSize": 1_048_576}
    )
    assert len(large) > len(small)


def test_build_synthetic_packets_all_ip_headers_have_valid_checksum():
    device = _make_ap()
    packets = pcap_mod.build_synthetic_packets(device, {})
    for p in packets:
        _, _, ethertype, payload = _parse_ethernet(p.data)
        if ethertype == pcap_mod.ETHERTYPE_IPV4:
            assert _ip_checksum_ok(payload[:20]), "invalid IPv4 header checksum"


def test_build_synthetic_packets_timestamps_are_monotonic():
    device = _make_ap()
    packets = pcap_mod.build_synthetic_packets(device, {}, base_ts=1_700_000_000.0)
    us = [(p.ts_sec, p.ts_usec) for p in packets]
    assert us == sorted(us)


# -- packageCapture SET-key lifecycle ----------------------------------------

def test_handle_package_capture_stores_start_config():
    device = _make_ap()
    cfg = {
        "operation": "start",
        "nid": "abc",
        "captureInfo": {"duration": 10, "totalSize": 1024, "interface": "eth0"},
    }
    device.handle_package_capture(cfg)
    assert device.package_capture_config == cfg
    # Stored as a copy.
    cfg["operation"] = "stop"
    assert device.package_capture_config["operation"] == "start"


def test_handle_package_capture_stores_stop_config():
    device = _make_ap()
    cfg = {"operation": "stop", "nid": "abc"}
    device.handle_package_capture(cfg)
    assert device.package_capture_config["operation"] == "stop"


def test_packet_capture_service_builds_valid_pcap_without_network():
    """The PacketCaptureService builds a synthetic pcap buffer (without
    opening a socket) that starts with a valid libpcap global header and
    contains at least one record."""
    from device_emulator.services.packet_capture import PacketCaptureService

    device = _make_ap()
    svc = PacketCaptureService(
        device,
        controller_host="127.0.0.1",
        capture_info={"duration": 5, "totalSize": 64},
        nid="test",
    )
    data = svc._build_pcap()
    assert data[:24] == pcap_mod.pcap_global_header()
    # At least one record (16-byte header) follows the global header.
    assert len(data) > 24 + 16
    incl_len = struct.unpack_from("<I", data, 24 + 8)[0]
    assert incl_len > 0
    assert not svc.is_running()


def test_packet_capture_service_file_transfer_frame_is_valid_ecsp():
    """The per-partition transfer frame is a valid ECSP message (4-byte BE
    length prefix + JSON {header, body}) with type FILE_TRANSFER_REQUEST_V2
    and a file transfer body carrying the base64 partition."""
    from device_emulator.services.packet_capture import PacketCaptureService
    from device_emulator.protocol import constants
    from device_emulator.protocol.framing import decode_frame

    device = _make_ap()
    svc = PacketCaptureService(
        device,
        controller_host="127.0.0.1",
        capture_info={"duration": 5, "totalSize": 64},
        nid="sess-1",
    )
    frame = svc._frame_transfer_message(0, "Zm9vYmFy")  # base64 of "foobar"
    # 4-byte BE length prefix.
    declared = int.from_bytes(frame[:4], "big")
    payload = decode_frame(frame)
    assert declared == len(payload)
    msg = json.loads(payload)
    assert msg["header"]["type"] == constants.MESSAGE_TYPE_FILE_TRANSFER_RESPONSE_V2
    assert msg["header"]["mac"] == device.mac
    assert msg["header"]["seq"] == 0
    ft = msg["body"]["fileTransfer"]
    assert ft["errCode"] == 0
    assert ft["fileName"].endswith("_sess-1.pcap")
    assert ft["partition"] == 0
    assert ft["data"] == "Zm9vYmFy"
    assert ft["fileType"] == "pcap"


def test_packet_capture_service_announces_file_then_serves_partitions():
    """The device announces the capture with a FILE_TRANSFER notify (subject 6,
    type 1) carrying name/size/md5, then serves the controller's byte-range
    partition requests as FILE_TRANSFER_RESPONSE_V2."""
    import base64
    import hashlib
    from device_emulator.services.packet_capture import (
        PacketCaptureService, NOTIFY_SUBJECT_FILE_TRANSFER, CAPTURE_FILE_NOTIFY_TYPE,
    )

    device = _make_ap()
    svc = PacketCaptureService(
        device,
        controller_host="127.0.0.1",
        capture_info={"duration": 5, "totalSize": 64},
        nid="loop-test",
    )
    notifies: list = []
    sent: list = []

    class FakeManage:
        _sock = True  # truthy: "connected"

        def send_notify(self, subject, content):
            notifies.append((subject, content))
            return True

        def send_file_transfer_frame(self, body):
            sent.append(body)
            return True

    device.manage_service = FakeManage()
    pcap_bytes = svc._build_pcap()
    svc._last_pcap = pcap_bytes

    assert svc.announce_file() is True
    subject, content = notifies[0]
    assert subject == NOTIFY_SUBJECT_FILE_TRANSFER
    assert content["type"] == CAPTURE_FILE_NOTIFY_TYPE
    assert content["cmdId"] == "loop-test"
    assert content["errCode"] == 0
    info = content["fileInfos"][0]
    assert info["fileSize"] == len(pcap_bytes)
    assert info["md5"] == hashlib.md5(pcap_bytes).hexdigest()

    # The controller then requests the whole file as one partition.
    assert svc.handle_transfer_request(
        {"fileTransfer": {"fileName": info["fileName"], "partition": 0,
                          "startIndex": 0, "endIndex": len(pcap_bytes) - 1}}
    ) is True
    ft = sent[0]["fileTransfer"]
    assert ft["partition"] == 0
    assert ft["errCode"] == 0
    assert base64.b64decode(ft["data"]) == pcap_bytes


def test_packet_capture_service_serves_partial_byte_range():
    """A partition request for a sub-range returns exactly those bytes."""
    import base64
    from device_emulator.services.packet_capture import PacketCaptureService

    device = _make_ap()
    svc = PacketCaptureService(device, controller_host="127.0.0.1", capture_info={}, nid="r")
    sent: list = []

    class FakeManage:
        _sock = True

        def send_file_transfer_frame(self, body):
            sent.append(body)
            return True

    device.manage_service = FakeManage()
    data = svc._build_pcap()
    svc._last_pcap = data

    assert svc.handle_transfer_request(
        {"fileTransfer": {"partition": 1, "startIndex": 10, "endIndex": 19}}
    ) is True
    ft = sent[0]["fileTransfer"]
    assert ft["partition"] == 1
    assert base64.b64decode(ft["data"]) == data[10:20]


def test_packet_capture_service_transfer_fails_when_not_connected():
    """Without a live management channel the device can neither announce the
    capture nor serve partition requests."""
    from device_emulator.services.packet_capture import PacketCaptureService

    device = _make_ap()
    svc = PacketCaptureService(
        device, controller_host="127.0.0.1", capture_info={}, nid="x",
    )
    # No manage_service on the device → not connected.
    assert svc.announce_file() is False
    assert svc.handle_transfer_request({}) is False

    # manage_service present but _sock None → not connected.
    class FakeManage:
        _sock = None
    device.manage_service = FakeManage()
    assert svc.announce_file() is False
    assert svc.handle_transfer_request({}) is False