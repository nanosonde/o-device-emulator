"""Synthetic connected-client model and site-wide client synthesis.

The controller builds its client store from what each device reports in its
periodic INFORM (access points report associated wireless stations, switches
report per-port learned clients, the gateway reports DHCP leases / LAN clients).
The emulator has no real clients, so this module fabricates a small, stable,
internally-consistent roster and hands each device the slice it should report:

- wireless clients are attached to an access point (and appear on the gateway's
  DHCP-lease / LAN-client tables too, since the gateway is the DHCP server);
- wired clients are attached to a free switch downlink port (and likewise show
  up as gateway DHCP leases).

Everything is derived deterministically from the host device MAC so the same
clients reappear across restarts. Field names on the wire follow the
controller's INFORM payloads (see doc/DEVICE_PROTOCOL.md).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .. import stats

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .base import Device


_VENDORS = ["Apple, Inc.", "Samsung Electronics", "Intel Corporate",
            "Google, Inc.", "Raspberry Pi", "Dell Inc."]
_HOST_PREFIXES = ["android", "laptop", "desktop-pc", "iphone", "tablet", "iot"]


@dataclass
class NetworkClient:
    """One synthetic end-host client, consistent across every device/page that
    reports it."""

    mac: str
    ip: str
    name: str
    vendor: str
    wireless: bool
    host_mac: str            # infrastructure device the client is attached to
    host_port: int = 0       # switch/AP LAN port (0 = wireless)
    ssid: str = ""
    radio_id: int = 0        # 0 = 2.4 GHz, 1 = 5 GHz
    vlan: int = 1
    rssi: int = -55
    snr: int = 35
    rate_mbps: int = 300
    down_bps: int = 0
    up_bps: int = 0
    first_seen_ms: int = 0
    assoc_seconds: int = 0

    def traffic(self, uptime_seconds: int) -> tuple[int, int]:
        """(rx_bytes, tx_bytes) for this client, accumulated over the client's
        association time (capped by device uptime) at roughly a tenth of its
        peak rate, so totals stay plausible and only grow."""
        secs = min(self.assoc_seconds, max(0, uptime_seconds))
        rx = stats.synthetic_bytes(self.mac, "cl-rx", secs, self.down_bps // 10)
        tx = stats.synthetic_bytes(self.mac, "cl-tx", secs, self.up_bps // 10)
        return rx, tx


def _make_client(host: "Device", index: int, *, wireless: bool, host_port: int,
                 ssid: str, radio_id: int, ip_last: int) -> NetworkClient:
    mac = stats.synthetic_client_mac(host.mac, index)
    seed = mac
    vendor = _VENDORS[stats.synthetic_int(seed, "vendor", 0, len(_VENDORS))]
    name = f"{_HOST_PREFIXES[stats.synthetic_int(seed, 'name', 0, len(_HOST_PREFIXES))]}-{mac[-5:].replace('-', '')}"
    down = stats.synthetic_rate_bps(seed, "down", 5, 60)
    up = stats.synthetic_rate_bps(seed, "up", 1, 20)
    assoc = stats.synthetic_int(seed, "assoc", 300, 86_400)
    return NetworkClient(
        mac=mac,
        ip=f"192.168.0.{ip_last}",
        name=name,
        vendor=vendor,
        wireless=wireless,
        host_mac=host.mac,
        host_port=host_port,
        ssid=ssid,
        radio_id=radio_id,
        vlan=1,
        rssi=-40 - stats.synthetic_int(seed, "rssi", 0, 45),
        snr=20 + stats.synthetic_int(seed, "snr", 0, 40),
        rate_mbps=(144 if radio_id == 0 else 866) if wireless else 1000,
        down_bps=down,
        up_bps=up,
        first_seen_ms=int(time.time() * 1000) - assoc * 1000,
        assoc_seconds=assoc,
    )


def synthesize_site_clients(devices: list["Device"]) -> None:
    """Populate ``device.reported_clients`` (and, for the gateway,
    ``device.dhcp_leases``) with a stable, internally-consistent client roster.

    Called by the runner after topology is resolved. Access points get wireless
    clients, switches get a wired client on a free downlink port, and the
    gateway aggregates them all as DHCP leases / LAN clients."""
    from ..protocol import constants

    all_clients: list[NetworkClient] = []
    ip_last = 100

    for device in devices:
        device.reported_clients = []

    for device in devices:
        if device.device_type == constants.DEVICE_TYPE_AP:
            # Wireless clients are associated with an SSID that is controller-
            # pushed (ssid_*G SET keys) and captured by the AP, not a property
            # of the synthetic client roster. Use "" here; the AP's INFORM
            # _client_stats/_ssid_stats overrides this via
            # EapDevice._radio_client_assignments (see eap.py).
            radio_ids = getattr(device, "SUPPORTED_RADIO_IDS", (0, 1))
            count = getattr(device, "wireless_client_count", 5)
            for index in range(count):
                radio_id = radio_ids[index % len(radio_ids)]
                client = _make_client(
                    device, index, wireless=True, host_port=0,
                    ssid="", radio_id=radio_id, ip_last=ip_last,
                )
                ip_last += 1
                device.reported_clients.append(client)
                all_clients.append(client)
        elif device.device_type == constants.DEVICE_TYPE_SWITCH:
            # One wired client on a downlink port that is not an infrastructure
            # uplink (fall back to a high port number).
            used = {ln.local_port for ln in device.topology.all_links()}
            port = next((p for p in range(1, getattr(device, "port_num", 8) + 1) if p not in used), 1)
            client = _make_client(
                device, 90, wireless=False, host_port=port,
                ssid="", radio_id=0, ip_last=ip_last,
            )
            ip_last += 1
            device.reported_clients.append(client)
            all_clients.append(client)

    # The gateway is the DHCP server / default route: it sees every client.
    for device in devices:
        if device.device_type == constants.DEVICE_TYPE_GATEWAY:
            device.reported_clients = list(all_clients)
            device.dhcp_leases = list(all_clients)
