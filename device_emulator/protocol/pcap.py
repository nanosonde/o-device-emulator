"""Libpcap file generator for the emulated Packet Capture feature.

The controller's Tools → Packet Capture feature (§11.6) pushes a
``packageCapture`` SET key to start a capture; the device is expected to
produce a capture file and transfer it back on port 29815
(``TRANSFER_V2_TCP_PORT``). The exact 29815 transfer framing is only
partially characterized (PROVISIONAL), so this module focuses on
producing a **fully valid libpcap (`.pcap`) file** that opens cleanly in
tcpdump/Wireshark and shows realistic, parseable frames — the user's
explicit requirement: "valid packet data".

The generated capture is **synthetic and deterministic** (MAC-seeded via
``device_emulator.stats``): it contains no real traffic, just a small set of
representative frames (ARP, ICMP, TCP handshake + data, UDP DNS) so the
result is obviously dummy yet structurally correct.

The libpcap format (v2.4) is::

    Global header  (24 bytes)
        magic_number   0xa1b2c3d4   (native byte order)
        version_major  2
        version_minor  4
        thiszone       0
        sigfigs        0
        snaplen        65535
        network        1            (LINKTYPE_ETHERNET)
    Per-packet record header (16 bytes)
        ts_sec         uint32
        ts_usec        uint32
        incl_len       uint32
        orig_len       uint32
    Packet data (incl_len bytes)
"""
from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .. import stats

# -- libpcap constants --------------------------------------------------------

PCAP_MAGIC = 0xA1B2C3D4
PCAP_VERSION_MAJOR = 2
PCAP_VERSION_MINOR = 4
PCAP_SNAPLEN = 65535
LINKTYPE_ETHERNET = 1

# Ethertypes
ETHERTYPE_IPV4 = 0x0800
ETHERTYPE_ARP = 0x0806

# IP protocol numbers
IPPROTO_ICMP = 1
IPPROTO_TCP = 6
IPPROTO_UDP = 17

# Common ports
PORT_DNS = 53
PORT_HTTPS = 443


@dataclass
class PcapPacket:
    """A single libpcap record (timestamp + raw frame bytes)."""
    ts_sec: int
    ts_usec: int
    data: bytes


# -- low-level frame builders -------------------------------------------------

def _mac_bytes(mac: str) -> bytes:
    """Convert a hyphen/colon-separated MAC string to 6 raw bytes."""
    cleaned = mac.replace(":", "-")
    parts = cleaned.split("-")
    if len(parts) != 6:
        raise ValueError(f"bad MAC: {mac!r}")
    return bytes(int(p, 16) for p in parts)


def _ones_complement_sum(data: bytes, start: int = 0) -> int:
    """Compute the 16-bit one's complement sum used by IP/TCP/UDP/ICMP
    checksums. ``start`` is folded in (used for the UDP/TCP pseudo-header)."""
    total = start
    if len(data) % 2:
        data = data + b"\x00"  # pad to even length
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
    # Fold carries
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return total


def _checksum(data: bytes, start: int = 0) -> int:
    """Return the 16-bit one's complement checksum (~sum)."""
    return (~_ones_complement_sum(data, start)) & 0xFFFF


def _ethernet(dst_mac: bytes, src_mac: bytes, ethertype: int, payload: bytes) -> bytes:
    """Build an Ethernet II frame (dst + src + ethertype + payload)."""
    return dst_mac + src_mac + struct.pack("!H", ethertype) + payload


def _ipv4_header(
    src_ip: str,
    dst_ip: str,
    proto: int,
    payload_len: int,
    identification: int = 0,
    ttl: int = 64,
) -> bytes:
    """Build an IPv4 header (20 bytes, no options) with a correct checksum.
    The ``payload_len`` is the L4 payload byte length (the header's total-length
    field is computed from it)."""
    total_length = 20 + payload_len
    # Version/IHL=0x45, DSCP/ECN=0, identification, flags=0, fragment offset=0
    header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0x00,
        total_length,
        identification & 0xFFFF,
        0x4000,  # Don't Fragment, fragment offset 0
        ttl,
        proto,
        0,  # checksum placeholder
        _ip_bytes(src_ip),
        _ip_bytes(dst_ip),
    )
    cs = _checksum(header)
    # Patch the checksum into bytes 10-11.
    return header[:10] + struct.pack("!H", cs) + header[12:]


def _ip_bytes(ip: str) -> bytes:
    parts = ip.split(".")
    if len(parts) != 4:
        raise ValueError(f"bad IPv4: {ip!r}")
    return bytes(int(p) & 0xFF for p in parts)


def _tcp_pseudo_header(src_ip: str, dst_ip: str, tcp_len: int) -> int:
    """Fold the IPv4 pseudo-header (used in the TCP/UDP checksum) into a
    one's-complement running sum."""
    pseudo = (
        _ip_bytes(src_ip)
        + _ip_bytes(dst_ip)
        + struct.pack("!BBH", 0, 6, tcp_len)
    )
    return _ones_complement_sum(pseudo)


def _udp_pseudo_header(src_ip: str, dst_ip: str, udp_len: int) -> int:
    pseudo = (
        _ip_bytes(src_ip)
        + _ip_bytes(dst_ip)
        + struct.pack("!BBH", 0, 17, udp_len)
    )
    return _ones_complement_sum(pseudo)


# -- packet builders (one per protocol) --------------------------------------

def build_arp(
    *,
    ts_sec: int,
    ts_usec: int,
    src_mac: bytes,
    src_ip: str,
    dst_mac: bytes,
    dst_ip: str,
    operation: int = 1,  # 1=request, 2=reply
) -> PcapPacket:
    """Build an ARP (Ethernet/IPv4) frame.

    For a request, ``dst_mac`` is normally the broadcast address; for a reply
    it is the requester's MAC. The ARP ``hw_target``/``proto_target`` follow
    the same convention.
    """
    # ARP header: htype=1 (Ethernet), ptype=0x0800 (IPv4), hlen=6, plen=4,
    # op, sha, spa, tha, tpa.
    arp = struct.pack("!HHBBH", 1, ETHERTYPE_IPV4, 6, 4, operation)
    arp += src_mac + _ip_bytes(src_ip)
    arp += dst_mac + _ip_bytes(dst_ip)
    # Pad to minimum Ethernet frame size (60 bytes excluding the FCS, which
    # libpcap captures without). Ethernet header is 14 bytes, so payload must
    # be >= 46 bytes.
    if len(arp) < 46:
        arp = arp + b"\x00" * (46 - len(arp))
    frame = _ethernet(dst_mac, src_mac, ETHERTYPE_ARP, arp)
    return PcapPacket(ts_sec, ts_usec, frame)


def build_icmp_echo(
    *,
    ts_sec: int,
    ts_usec: int,
    src_mac: bytes,
    src_ip: str,
    dst_mac: bytes,
    dst_ip: str,
    icmp_type: int = 8,  # 8=echo request, 0=echo reply
    identifier: int = 1,
    sequence: int = 1,
    payload: bytes = b"emulator-ping-check",
) -> PcapPacket:
    """Build an ICMP echo request/reply inside an Ethernet/IPv4 frame."""
    # ICMP: type, code=0, checksum placeholder, id, seq, payload.
    icmp = struct.pack("!BBHHH", icmp_type, 0, 0, identifier & 0xFFFF, sequence & 0xFFFF) + payload
    cs = _checksum(icmp)
    icmp = icmp[:2] + struct.pack("!H", cs) + icmp[4:]
    ip = _ipv4_header(src_ip, dst_ip, IPPROTO_ICMP, len(icmp), identification=identifier)
    frame = _ethernet(dst_mac, src_mac, ETHERTYPE_IPV4, ip + icmp)
    return PcapPacket(ts_sec, ts_usec, frame)


def build_tcp(
    *,
    ts_sec: int,
    ts_usec: int,
    src_mac: bytes,
    src_ip: str,
    src_port: int,
    dst_mac: bytes,
    dst_ip: str,
    dst_port: int,
    seq: int,
    ack: int,
    flags: int,  # e.g. 0x02 SYN, 0x12 SYN+ACK, 0x10 ACK, 0x18 PSH+ACK
    window: int = 65535,
    payload: bytes = b"",
    identification: int = 0,
) -> PcapPacket:
    """Build a TCP segment inside an Ethernet/IPv4 frame with a correct
    checksum (including the IPv4 pseudo-header)."""
    data_offset = 5 << 4  # 20-byte header, no options
    tcp = struct.pack(
        "!HHIIBBHHH",
        src_port & 0xFFFF,
        dst_port & 0xFFFF,
        seq & 0xFFFFFFFF,
        ack & 0xFFFFFFFF,
        data_offset,
        flags & 0xFF,
        window & 0xFFFF,
        0,  # checksum placeholder
        0,  # urgent pointer
    ) + payload
    cs = _checksum(tcp, start=_tcp_pseudo_header(src_ip, dst_ip, len(tcp)))
    tcp = tcp[:16] + struct.pack("!H", cs) + tcp[18:]
    ip = _ipv4_header(src_ip, dst_ip, IPPROTO_TCP, len(tcp), identification=identification)
    frame = _ethernet(dst_mac, src_mac, ETHERTYPE_IPV4, ip + tcp)
    return PcapPacket(ts_sec, ts_usec, frame)


def build_udp(
    *,
    ts_sec: int,
    ts_usec: int,
    src_mac: bytes,
    src_ip: str,
    src_port: int,
    dst_mac: bytes,
    dst_ip: str,
    dst_port: int,
    payload: bytes,
    identification: int = 0,
) -> PcapPacket:
    """Build a UDP datagram inside an Ethernet/IPv4 frame with a correct
    checksum (including the IPv4 pseudo-header)."""
    udp = struct.pack("!HHHH", src_port & 0xFFFF, dst_port & 0xFFFF, 8 + len(payload), 0) + payload
    cs = _checksum(udp, start=_udp_pseudo_header(src_ip, dst_ip, len(udp)))
    if cs == 0:
        cs = 0xFFFF  # UDP uses 0x0000 to mean "no checksum"; transmit 0xFFFF
    udp = udp[:6] + struct.pack("!H", cs) + udp[8:]
    ip = _ipv4_header(src_ip, dst_ip, IPPROTO_UDP, len(udp), identification=identification)
    frame = _ethernet(dst_mac, src_mac, ETHERTYPE_IPV4, ip + udp)
    return PcapPacket(ts_sec, ts_usec, frame)


# -- synthetic capture generator ---------------------------------------------

def _client_mac(device_mac: str, salt: str) -> bytes:
    """A deterministic, locally-administered client MAC (so capture frames
    look like real client↔device traffic without colliding with the device's
    own OUI)."""
    raw = stats.synthetic_client_mac(salt, 0)
    return _mac_bytes(raw)


def _packet_count(capture_info: dict[str, Any], device_mac: str) -> int:
    """Scale the synthetic packet count with the requested capture
    ``duration``/``totalSize``. Defaults to a small, representative set."""
    duration = int(capture_info.get("duration") or 0)
    total_size = int(capture_info.get("totalSize") or 0)
    # Base set: ARP req/reply + ICMP req/reply + 3-way TCP handshake +
    # 1 TCP data segment + DNS query/response = 9 packets.
    base = 9
    # Add one extra TCP data segment per ~32KB of requested totalSize, capped.
    extra_size = min(40, total_size // 32_768)
    # Add one extra ICMP echo pair per ~5s of requested duration, capped.
    extra_dur = min(20, duration // 5) * 2
    return base + extra_size + extra_dur


def build_synthetic_packets(
    device: Any,
    capture_info: Optional[dict[str, Any]] = None,
    *,
    base_ts: Optional[float] = None,
) -> list[PcapPacket]:
    """Build a deterministic, MAC-seeded synthetic capture for ``device``.

    The capture contains realistic, fully-valid frames:

    * an ARP request + reply (who-has / is-at),
    * an ICMP echo request + reply,
    * a TCP 3-way handshake (SYN / SYN-ACK / ACK) on port 443,
    * one or more TCP PSH-ACK data segments carrying a small HTTP-ish body,
    * a UDP DNS query + response on port 53.

    The packet count scales modestly with the ``duration``/``totalSize``
    fields of ``capture_info`` (see ``_packet_count``). All timestamps start
    at ``base_ts`` (default: now) and increment by ~1ms per packet.
    """
    capture_info = capture_info or {}
    dev_mac_str = device.mac
    dev_mac = _mac_bytes(dev_mac_str)
    # The device's LAN IP (best-effort; fall back to a placeholder).
    dev_ip = getattr(device, "ip", None) or "192.168.1.1"
    # A deterministic peer (client) on the LAN.
    cli_mac = _client_mac(dev_mac_str, "pcap-peer")
    cli_ip = "192.168.1." + str(stats.synthetic_int(dev_mac_str, "cliip", 100, 250))
    # Upstream/gateway used for the ARP/ICMP exchange.
    gw_ip = "192.168.1." + str(stats.synthetic_int(dev_mac_str, "gwip", 1, 9))
    gw_mac = _mac_bytes(stats.synthetic_client_mac("pcap-gw", 0))
    bcast = b"\xff\xff\xff\xff\xff\xff"

    if base_ts is None:
        base_ts = time.time()
    ts_sec = int(base_ts)
    ts_usec = int((base_ts - ts_sec) * 1_000_000)

    def _tick() -> tuple[int, int]:
        nonlocal ts_usec, ts_sec
        ts_usec += 1000  # +1ms per packet
        if ts_usec >= 1_000_000:
            ts_usec -= 1_000_000
            ts_sec += 1
        return ts_sec, ts_usec

    packets: list[PcapPacket] = []

    # 1. ARP: client asks who-has the device; device replies.
    s, u = _tick()
    packets.append(build_arp(
        ts_sec=s, ts_usec=u, src_mac=cli_mac, src_ip=cli_ip, dst_mac=bcast, dst_ip=dev_ip, operation=1,
    ))
    s, u = _tick()
    packets.append(build_arp(
        ts_sec=s, ts_usec=u, src_mac=dev_mac, src_ip=dev_ip, dst_mac=cli_mac, dst_ip=cli_ip, operation=2,
    ))

    # 2. ICMP echo: device pings the gateway; gateway replies.
    ping_payload = b"emulator-network-check"
    s, u = _tick()
    packets.append(build_icmp_echo(
        ts_sec=s, ts_usec=u, src_mac=dev_mac, src_ip=dev_ip, dst_mac=gw_mac, dst_ip=gw_ip,
        icmp_type=8, identifier=0x1234, sequence=1, payload=ping_payload,
    ))
    s, u = _tick()
    packets.append(build_icmp_echo(
        ts_sec=s, ts_usec=u, src_mac=gw_mac, src_ip=gw_ip, dst_mac=dev_mac, dst_ip=dev_ip,
        icmp_type=0, identifier=0x1234, sequence=1, payload=ping_payload,
    ))

    # 3. TCP 3-way handshake on :443 (client → device).
    s, u = _tick()
    packets.append(build_tcp(
        ts_sec=s, ts_usec=u, src_mac=cli_mac, src_ip=cli_ip, src_port=51234, dst_mac=dev_mac, dst_ip=dev_ip,
        dst_port=PORT_HTTPS, seq=1000, ack=0, flags=0x02, identification=0x1001,
    ))  # SYN
    s, u = _tick()
    packets.append(build_tcp(
        ts_sec=s, ts_usec=u, src_mac=dev_mac, src_ip=dev_ip, src_port=PORT_HTTPS, dst_mac=cli_mac, dst_ip=cli_ip,
        dst_port=51234, seq=0, ack=1001, flags=0x12, window=65535, identification=0x2001,
    ))  # SYN-ACK
    s, u = _tick()
    packets.append(build_tcp(
        ts_sec=s, ts_usec=u, src_mac=cli_mac, src_ip=cli_ip, src_port=51234, dst_mac=dev_mac, dst_ip=dev_ip,
        dst_port=PORT_HTTPS, seq=1001, ack=1, flags=0x10, identification=0x1002,
    ))  # ACK

    # 4. TCP data segment(s): client posts a small HTTP-ish request.
    count = _packet_count(capture_info, dev_mac_str)
    extra_data = count - 9
    for i in range(max(0, extra_data)):
        body = b"GET / HTTP/1.1\r\nHost: " + dev_ip.encode() + b"\r\nX-Synthetic: 1\r\n\r\n"
        s, u = _tick()
        packets.append(build_tcp(
            ts_sec=s, ts_usec=u, src_mac=cli_mac, src_ip=cli_ip, src_port=51234, dst_mac=dev_mac, dst_ip=dev_ip,
            dst_port=PORT_HTTPS, seq=1001 + i * len(body), ack=1, flags=0x18,
            window=65535, payload=body, identification=0x1003 + i,
        ))  # PSH-ACK
    # Always include at least one data segment so the capture has TCP payload.
    if extra_data <= 0:
        body = b"GET / HTTP/1.1\r\nHost: " + dev_ip.encode() + b"\r\n\r\n"
        s, u = _tick()
        packets.append(build_tcp(
            ts_sec=s, ts_usec=u, src_mac=cli_mac, src_ip=cli_ip, src_port=51234, dst_mac=dev_mac, dst_ip=dev_ip,
            dst_port=PORT_HTTPS, seq=1001, ack=1, flags=0x18, window=65535,
            payload=body, identification=0x1003,
        ))

    # 5. UDP DNS query + response (client → device, device → client).
    # A minimal DNS query for "example.com" A record.
    dns_query = _dns_query("example.com")
    s, u = _tick()
    packets.append(build_udp(
        ts_sec=s, ts_usec=u, src_mac=cli_mac, src_ip=cli_ip, src_port=51235, dst_mac=dev_mac, dst_ip=dev_ip,
        dst_port=PORT_DNS, payload=dns_query, identification=0x3001,
    ))
    dns_resp = _dns_response("example.com", dev_ip)
    s, u = _tick()
    packets.append(build_udp(
        ts_sec=s, ts_usec=u, src_mac=dev_mac, src_ip=dev_ip, src_port=PORT_DNS, dst_mac=cli_mac, dst_ip=cli_ip,
        dst_port=51235, payload=dns_resp, identification=0x3002,
    ))

    return packets


def _dns_query(name: str) -> bytes:
    """A minimal DNS query message (ID=0x1234, RD=1, QDCOUNT=1) for ``name``
    A record."""
    header = struct.pack("!HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0)  # flags: RD=1
    qname = b"".join(
        bytes([len(label)]) + label.encode() for label in name.split(".")
    ) + b"\x00"
    question = qname + struct.pack("!HH", 1, 1)  # QTYPE=A, QCLASS=IN
    return header + question


def _dns_response(name: str, answer_ip: str) -> bytes:
    """A minimal DNS response (QR=1, AA=1, ANCOUNT=1) with one A record."""
    header = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 1, 0, 0)  # flags: QR+RD+RA+AA
    qname = b"".join(
        bytes([len(label)]) + label.encode() for label in name.split(".")
    ) + b"\x00"
    question = qname + struct.pack("!HH", 1, 1)
    # Answer: name pointer to offset 12 (0xC00C), type A, class IN, TTL 300,
    # rdlength 4, rdata = answer_ip.
    answer = struct.pack("!HHHIH", 0xC00C, 1, 1, 300, 4) + _ip_bytes(answer_ip)
    return header + question + answer


# -- pcap file writer --------------------------------------------------------

def pcap_global_header() -> bytes:
    """The 24-byte libpcap global header (native byte order, v2.4,
    LINKTYPE_ETHERNET)."""
    return struct.pack(
        "<IHHiIII",
        PCAP_MAGIC,
        PCAP_VERSION_MAJOR,
        PCAP_VERSION_MINOR,
        0,  # thiszone
        0,  # sigfigs
        PCAP_SNAPLEN,
        LINKTYPE_ETHERNET,
    )


def pcap_record(packet: PcapPacket) -> bytes:
    """A 16-byte per-packet record header + the frame bytes."""
    header = struct.pack(
        "<IIII",
        packet.ts_sec & 0xFFFFFFFF,
        packet.ts_usec & 0xFFFFFFFF,
        len(packet.data),
        len(packet.data),
    )
    return header + packet.data


def write_pcap(path: str, packets: Iterable[PcapPacket]) -> int:
    """Write ``packets`` to ``path`` as a libpcap file and return the byte
    count written. The file is opened in binary mode; the parent directory
    must exist."""
    total = 0
    with open(path, "wb") as f:
        f.write(pcap_global_header())
        total += 24
        for packet in packets:
            record = pcap_record(packet)
            f.write(record)
            total += len(record)
    return total


def to_pcap_bytes(packets: Iterable[PcapPacket]) -> bytes:
    """Serialize a synthetic capture to a single ``bytes`` buffer (in-memory,
    no temp file). Useful for tests and for streaming over a socket."""
    out = bytearray(pcap_global_header())
    for packet in packets:
        out += pcap_record(packet)
    return bytes(out)


def temp_pcap_path(device_mac: str, suffix: str = "") -> str:
    """A deterministic temp path for a device's capture file."""
    safe_mac = device_mac.replace(":", "-").replace("/", "_")
    name = f"emulator-capture-{safe_mac}{suffix}.pcap"
    return os.path.join(_temp_dir(), name)


def _temp_dir() -> str:
    import tempfile

    d = os.path.join(tempfile.gettempdir(), "o-device-emulator-pcap")
    os.makedirs(d, exist_ok=True)
    return d