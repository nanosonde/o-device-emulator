"""Synthetic responses for OLT detail-page URI-RPC operations.

The controller's OLT management subsystem sends detail-page operations as
ordinary ECSP SET/GET requests with a body of ``{uri, params}`` and expects a
response of ``{deviceType, errcode, message, data}``. The ``uri`` string
selects the operation and ``data`` carries the operation-specific response
payload. There is no dedicated config-query enum for OLTs; the URI itself is
the operation selector.

The full URI surface (230+ operations across 30+ subsystems) and the response
field names are documented in ``doc/DEVICE_PROTOCOL.md`` §7.9.3. This module
provides a dispatch table mapping URI strings to synthetic data generators.
Each generator returns a JSON-serialisable object matching the expected field
shapes with deterministic, per-device synthetic values (derived from the
device MAC via :mod:`device_emulator.stats`).

The controller's OLT detail page reads these via GET requests (``list``/``get``
URIs). Config-modifying operations (``add``/``edit``/``delete``) arrive as SET
requests and are acked with ``errcode: 0`` and ``data: null`` (the controller
does not expect a data payload for mutations). A handful of SET operations
that return status (e.g. ``reboot/ack``, ``config/backup``) return a small
status object.

Coverage philosophy: every GET (read) URI returns a realistic synthetic
payload so the controller's OLT detail page has non-empty data for every tab.
SET (mutation) URIs are universally acked. URIs not yet covered fall through
to a default that returns ``data: null`` with ``errcode: 0`` (so the controller
never sees an error, just an empty detail section — matching the previous
behaviour but now with the vast majority of tabs populated).
"""
from __future__ import annotations

from typing import Any, Callable

from .. import stats

# Type alias for a handler: (mac, pon_port_count, params) -> data payload
UriHandler = Callable[[str, int, dict[str, Any]], Any]

# Per-device firmware-upgrade state (mac → status dict). Populated when the
# OLT receives an ``upgrade`` config push ({reboot,
# interval}) or a ``system-tools/firmware/upgrade`` SET. Read by the
# ``system-tools/image-table/list`` and firmware-upgrade-status handlers.
# Status values: "idle", "downloading", "applying", "rebooting", "success".
_UPGRADE_STATE: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seq(mac: str, salt: str, index: int) -> str:
    """A deterministic serial-number-like string for synthetic entities."""
    seed = stats._seed_from_mac(f"{mac}:{salt}:{index}")
    return f"ONU{seed:08X}"


def _mac_for_index(mac: str, salt: str, index: int) -> str:
    """A deterministic MAC address for a synthetic entity (e.g. an ONU)."""
    seed = stats._seed_from_mac(f"{mac}:{salt}:mac:{index}")
    return "02:%02X:%02X:%02X:%02X:%02X" % (
        (seed >> 24) & 0xFF,
        (seed >> 16) & 0xFF,
        (seed >> 8) & 0xFF,
        (seed >> 0) & 0xFF,
        (stats._seed_from_mac(f"{mac}:{salt}:mac2:{index}") >> 24) & 0xFF,
    )


def _int_list(mac: str, salt: str, count: int, low: int, high: int) -> list[int]:
    return [stats.synthetic_int(mac, f"{salt}:{i}", low, high) for i in range(count)]


# ---------------------------------------------------------------------------
# PON ports
# ---------------------------------------------------------------------------

def _pon_port_informations(mac: str, pon: int, params: dict) -> list[dict]:
    """``pon/pon-port/informations/list`` → list of PON port information entries."""
    ports = []
    for p in range(1, pon + 1):
        onu = stats.synthetic_int(mac, f"pononu{p}", 0, 4)
        ports.append({
            "portId": p,
            "onuNum": onu,
            "status": "ENABLE",
            "maxBandwidth": 2488,
            "actualBandwidth": stats.synthetic_int(mac, f"ponbw{p}", 100, 2000),
            "remainBandwidth": stats.synthetic_int(mac, f"ponrem{p}", 200, 2000),
            "opticalVcc": 3.2 + (stats._seed_from_mac(f"{mac}:vcc{p}") % 10) / 10.0,
            "opticalBias": 15.0 + (stats._seed_from_mac(f"{mac}:bias{p}") % 20) / 10.0,
            "opticalPower": 1.5 + (stats._seed_from_mac(f"{mac}:opwr{p}") % 15) / 10.0,
        })
    return ports


def _pon_port_configs(mac: str, pon: int, params: dict) -> list[dict]:
    """``pon/pon-port/configs/list`` → PON port config entries."""
    return [
        {
            "portId": p,
            "status": "ENABLE",
            "adminStatus": "ENABLE",
            "description": f"PON port {p}",
            "broadcastEnable": True,
            "multicastMode": "IGMP_SNOOPING",
        }
        for p in range(1, pon + 1)
    ]


def _pon_auto_service_ports(mac: str, pon: int, params: dict) -> list[dict]:
    """``pon/auto-service-ports/list`` → auto service-port entries."""
    return [
        {
            "gemPortId": 100 + p,
            "ponPortId": p,
            "ponPortStr": f" pon{p}",
            "onuId": 1,
            "userVlan": 1,
            "svlan": 100,
            "tagAction": "TRANSLATION",
            "etherType": "NONE",
        }
        for p in range(1, pon + 1)
    ]


def _pon_service_ports(mac: str, pon: int, params: dict) -> list[dict]:
    """``pon/service-ports/list`` → service port entries (one per ONU)."""
    ports = []
    idx = 0
    for p in range(1, pon + 1):
        onu_count = stats.synthetic_int(mac, f"pononu{p}", 0, 4)
        for o in range(1, onu_count + 1):
            idx += 1
            ports.append({
                "index": idx,
                "activeStatus": "ACTIVE",
                "description": f"Service port ONU{p}/{o}",
                "onuId": o,
                "adminStatus": "ENABLE",
                "gemPortId": 128 + idx,
                "ponPortId": p,
                "ponPortStr": f" pon{p}",
                "userVlan": 1,
                "userVlanPriority": 0,
                "innerVlan": 1,
                "innerVlanPriority": 0,
                "svlan": 100,
                "tagAction": "TRANSLATION",
                "etherType": "NONE",
                "inboundTrafficProfileId": 1,
                "outboundTrafficProfileId": 1,
                "statisticPerformance": False,
            })
    return ports


def _pon_onu_autofinds(mac: str, pon: int, params: dict) -> list[dict]:
    """``pon/onu-register/autofinds/list`` → discovered-but-unregistered ONUs."""
    # A few autofind entries on the first couple PON ports
    entries = []
    for p in range(1, min(pon + 1, 3)):
        for o in range(1, 3):
            entries.append({
                "ponPortId": p,
                "ponPortStr": f" pon{p}",
                "onuId": o,
                "serialNumber": _seq(mac, "af", p * 10 + o),
                "macAddress": _mac_for_index(mac, "af", p * 10 + o),
                "equipmentId": "EPON",
                "hardwareVersion": "1.0",
                "softwareVersion": "1.0.0",
                "password": "",
                "registerTime": 0,
            })
    return entries


# ---------------------------------------------------------------------------
# ONU management (information)
# ---------------------------------------------------------------------------

def _onu_information_list(mac: str, pon: int, params: dict) -> list[dict]:
    """ONU information list — the controller's ONU table (key tab).

    Reuses the ONU information field shape. The controller
    fetches this via a paginated query; we return a flat list of all ONUs
    across all PON ports.
    """
    onus = []
    idx = 0
    for p in range(1, pon + 1):
        onu_count = stats.synthetic_int(mac, f"pononu{p}", 0, 4)
        for o in range(1, onu_count + 1):
            idx += 1
            online = stats.synthetic_int(mac, f"onuon{p}:{o}", 0, 10) > 1
            onus.append({
                "key": f"pon{p}/onu{o}",
                "ponPortId": p,
                "ponPortStr": f" pon{p}",
                "onuId": o,
                "onuDescription": f"ONU-{p}-{o}",
                "serialNumber": _seq(mac, "onu", idx),
                "macAddress": _mac_for_index(mac, "onu", idx),
                "equipmentId": "GPON",
                "hardwareVersion": "1.0",
                "softwareVersion": "1.0.0",
                "adminStatus": "ACTIVATE",
                "onlineStatus": "ONLINE" if online else "OFFLINE",
                "configStatus": "SUCCESS",
                "matchStatus": "MATCH",
                "activeStatus": "ACTIVE" if online else "INACTIVE",
                "lineProfile": "line-profile-1",
                "serviceProfile": "service-profile-1",
                "mgmtProfile": "",
                "servicePortProfile": "",
                "receivedOpticalPower": -20.0 + (stats._seed_from_mac(f"{mac}:rxpwr{idx}") % 30) / 10.0,
                "transmittedOpticalPower": -8.0 + (stats._seed_from_mac(f"{mac}:txpwr{idx}") % 20) / 10.0,
            })
    return onus


def _onu_detail(mac: str, pon: int, params: dict) -> dict:
    """ONU detail (nested ONU detail config). Triggered when the
    controller opens a specific ONU's detail page."""
    pon_id = params.get("ponPortId", 1)
    onu_id = params.get("onuId", 1)
    idx = pon_id * 10 + onu_id
    return {
        "onuBasicInformation": {
            "onuDescription": f"ONU-{pon_id}-{onu_id}",
            "serialNumber": _seq(mac, "onu", idx),
            "macAddress": _mac_for_index(mac, "onu", idx),
            "vendorId": "ONU",
            "equipmentId": "GPON",
            "adminStatus": "ACTIVATE",
            "onlineStatus": "ONLINE",
            "configStatus": "SUCCESS",
            "matchStatus": "MATCH",
            "activeStatus": "ACTIVE",
            "onuDistance": stats.synthetic_int(mac, f"dist{idx}", 100, 5000),
            "onlineTime": stats.synthetic_int(mac, f"ontime{idx}", 3600, 864000),
            "hardwareVersion": "1.0",
            "lineProfile": "line-profile-1",
            "serviceProfile": "service-profile-1",
            "mgmtProfile": "",
        },
        "onuCapabilityInformation": {
            "omccVersion": "0x80",
            "totalEthNumber": 4,
            "totalVoipNumber": 0,
            "totalGemPortNumber": 8,
            "totalTcontNumber": 4,
        },
        "onuOpticalLinkInformation": {
            "receivedOpticalPower": -19.5,
            "transmittedOpticalPower": -2.5,
            "biasCurrent": 15.2,
            "workingVoltage": 3.25,
            "workingTemperature": 45.0,
        },
        "onuSoftwareInformation": {
            "software0Version": "1.0.0",
            "software0Active": True,
            "software0Commited": True,
            "software0Valid": True,
            "software1Version": "1.0.0",
            "software1Active": False,
            "software1Commited": False,
            "software1Valid": True,
        },
    }


# ---------------------------------------------------------------------------
# Profiles (PON)
# ---------------------------------------------------------------------------

def _dba_profiles(mac: str, pon: int, params: dict) -> list[dict]:
    """``profile/dba/profiles/list`` → DBA profile list."""
    return [
        {
            "dbaId": i,
            "name": f"DBA-Profile-{i}",
            "isSystemProfile": i == 1,
            "isInUse": i == 1,
            "type": "ASSURE_MAX",
            "fix": 512 if i == 1 else 0,
            "assure": 1024 if i == 1 else 2048,
            "max": 2488,
            "tcontNum": stats.synthetic_int(mac, f"dbaTc{i}", 1, 32),
        }
        for i in range(1, 4)
    ]


def _line_profiles(mac: str, pon: int, params: dict) -> list[dict]:
    """``profile/line/profiles/list`` → line profile list."""
    return [
        {
            "lineProfileId": i,
            "name": f"Line-Profile-{i}",
            "isSystemProfile": i == 1,
            "isInUse": i == 1,
            "upstreamFEC": "ENABLE",
            "mappingMode": "VLAN",
            "omccEncrypt": "ENABLE",
            "tcontNum": 4,
            "gemPortNum": 8,
        }
        for i in range(1, 3)
    ]


def _line_tconts(mac: str, pon: int, params: dict) -> list[dict]:
    """``profile/line/t-conts/list`` → T-CONT list."""
    return [
        {
            "tcontId": i,
            "lineProfileId": 1,
            "dbaId": 1,
            "gemPortIds": [j for j in range(1, 3)],
            "isInUse": True,
        }
        for i in range(1, 5)
    ]


def _line_gem_ports(mac: str, pon: int, params: dict) -> list[dict]:
    """``profile/line/gem-ports/list`` → GEM port list."""
    return [
        {
            "gemPortId": i,
            "lineProfileId": 1,
            "isInUse": True,
            "tcontId": ((i - 1) // 2) + 1,
            "encrypt": "ENABLE",
            "gemMappingIds": [i],
        }
        for i in range(1, 9)
    ]


def _line_gem_mappings(mac: str, pon: int, params: dict) -> list[dict]:
    """``profile/line/gem-mappings/list`` → gem mapping entries."""
    return [
        {"gemPortId": i, "mappingId": i, "vlanId": 1, "priority": 0}
        for i in range(1, 9)
    ]


def _service_profiles(mac: str, pon: int, params: dict) -> list[dict]:
    """``profile/service/profiles/list`` → service profile list."""
    return [
        {
            "serviceId": i,
            "isSystemProfile": i == 1,
            "isInUse": i == 1,
            "name": f"Service-Profile-{i}",
            "ethNum": 4,
            "maxAdaptiveEthNum": 4,
            "potsNum": 0,
            "maxAdaptivePotsNum": 0,
            "nativeVlan": 1,
            "onuBindNum": stats.synthetic_int(mac, f"svcBind{i}", 0, 16),
        }
        for i in range(1, 3)
    ]


def _service_eth_ports(mac: str, pon: int, params: dict) -> list[dict]:
    """``profile/service/eth-ports/list`` → ONU ETH port list."""
    return [
        {"port": p, "serviceProfileId": 1, "nativeVlan": 1, "vlanMode": "TRANSPARENT"}
        for p in range(1, 5)
    ]


def _service_pots_ports(mac: str, pon: int, params: dict) -> list[dict]:
    """``profile/service/pots-ports/list`` → ONU POTS port list (empty)."""
    return []


def _traffic_profiles(mac: str, pon: int, params: dict) -> list[dict]:
    """``profile/traffic/profiles/list`` → traffic profile list."""
    return [
        {
            "trafficId": i,
            "name": f"Traffic-Profile-{i}",
            "isInUse": i <= 2,
            "cirValue": 1024 * i,
            "cbsValue": 2048 * i,
            "pirValue": 4096 * i,
            "pbsValue": 8192 * i,
            "priority": 0,
            "priorityValue": 0,
            "innerPriority": "NONE",
            "innerPriorityValue": 0,
            "priorityPolicy": "STRICT",
            "rateLimitStatus": "ENABLE",
        }
        for i in range(1, 4)
    ]


# ---------------------------------------------------------------------------
# L2: Ethernet ports
# ---------------------------------------------------------------------------

def _eth_port_unit1(mac: str, pon: int, params: dict) -> list[dict]:
    """``eth-port/port/unit1/list`` → uplink ETH port list."""
    # Pizza-box OLTs typically have 2-4 uplink Ethernet ports
    eth_count = 2
    return [
        {
            "port": p,
            "mediaType": "1000BASE-T",
            "description": f"Uplink {p}",
            "status": "ENABLE",
            "speed": "1000M",
            "duplex": "FULL",
            "flowControl": "DISABLE",
            "lag": 0,
            "speedLink": "1000M",
            "duplexLink": "FULL",
            "linkStatus": "UP",
            "type": "RJ45",
            "speedMax": "1000M",
        }
        for p in range(1, eth_count + 1)
    ]


def _eth_port_mode(mac: str, pon: int, params: dict) -> list[dict]:
    """``eth-port/port/mode/list`` → port mode entries."""
    return [
        {"port": p, "mode": "AUTO"} for p in range(1, 3)
    ]


def _eth_port_isolation(mac: str, pon: int, params: dict) -> list[dict]:
    """``eth-port/port-isolation/list`` → port-isolation entries."""
    return [
        {"port": p, "isolation": "DISABLE"} for p in range(1, 3)
    ]


# ---------------------------------------------------------------------------
# L2: VLAN
# ---------------------------------------------------------------------------

def _vlan_configs(mac: str, pon: int, params: dict) -> list[dict]:
    """``vlan/8021q/vlan-configs/list`` → VLAN config list."""
    return [
        {
            "vlanId": v,
            "vlanName": f"VLAN{v}",
            "unTaggedPorts": [] if v != 1 else [1],
            "taggedPorts": [2] if v == 100 else [],
        }
        for v in (1, 100, 200)
    ]


def _vlan_unit1_configs(mac: str, pon: int, params: dict) -> list[dict]:
    """``vlan/8021q/unit1/configs/list`` → per-port VLAN config."""
    return [
        {"port": p, "portVlan": 1, "vlanMode": "ACCESS" if p == 1 else "TRUNK", "acceptFrame": "ALL"}
        for p in range(1, 3)
    ]


def _vlan_lags_configs(mac: str, pon: int, params: dict) -> list[dict]:
    """``vlan/8021q/lags/configs/list`` → per-LAG VLAN config (empty)."""
    return []


def _vlan_gvrp_lags(mac: str, pon: int, params: dict) -> list[dict]:
    return []


# ---------------------------------------------------------------------------
# L2: LAG
# ---------------------------------------------------------------------------

def _lag_table(mac: str, pon: int, params: dict) -> list[dict]:
    """``lag/lag-table/list`` → LAG config list (empty for pizza-box)."""
    return []


def _lag_global(mac: str, pon: int, params: dict) -> dict:
    """``lag/lacp-config/list`` → global LAG config."""
    return {"hashAlgorithm": 0}


def _lag_lacp(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _lag_static(mac: str, pon: int, params: dict) -> list[dict]:
    return []


# ---------------------------------------------------------------------------
# L2: STP
# ---------------------------------------------------------------------------

def _stp_summary(mac: str, pon: int, params: dict) -> dict:
    """``stp/summary/summarys/get`` → STP summary."""
    return {
        "spanningTree": "ENABLE",
        "spanningTreeMode": "MSTP",
        "localBridge": "00:00:00:00:00:00",
        "rootBridge": "00:00:00:00:00:00",
        "externalPathCost": 0,
        "regionalRootBridge": "00:00:00:00:00:00",
        "internalPathCost": 0,
        "designatedBridge": "00:00:00:00:00:00",
        "rootPort": 0,
        "latestTcTime": 0,
        "tcCount": 0,
    }


def _stp_mstp_summary(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _stp_global_config(mac: str, pon: int, params: dict) -> dict:
    """``stp/config/globals/get`` → STP global config."""
    return {
        "spanningTree": "ENABLE",
        "spanningTreeMode": "MSTP",
        "helloTime": 2,
        "forwardDelay": 15,
        "maxAge": 20,
        "maxHop": 20,
    }


def _stp_parameters(mac: str, pon: int, params: dict) -> dict:
    """``stp/config/parameters/get`` → STP parameters."""
    return {
        "helloTime": 2,
        "forwardDelay": 15,
        "maxAge": 20,
        "maxHop": 20,
    }


def _stp_port_unit1(mac: str, pon: int, params: dict) -> list[dict]:
    """``stp/port/unit1/configs/list`` → per-port STP config."""
    return [
        {"port": p, "stpStatus": "ENABLE", "pathCost": 200000, "priority": 128, "edgePort": "DISABLE"}
        for p in range(1, 3)
    ]


def _stp_port_lags(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _stp_mstp_instances(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _stp_mstp_region(mac: str, pon: int, params: dict) -> dict:
    return {"regionName": "", "revision": 0, "vlanMap": {}}


# ---------------------------------------------------------------------------
# L2: LLDP
# ---------------------------------------------------------------------------

def _lldp_global(mac: str, pon: int, params: dict) -> dict:
    """``lldp/global/configs/get`` → LLDP global config."""
    return {"txInterval": 30, "txHold": 120, "reinitDelay": 2, "txDelay": 2}


def _lldp_port(mac: str, pon: int, params: dict) -> list[dict]:
    """``lldp/port/config/list`` → per-port LLDP config."""
    return [
        {"port": p, "txStatus": "ENABLE", "rxStatus": "ENABLE"} for p in range(1, 3)
    ]


def _lldp_neighbor(mac: str, pon: int, params: dict) -> list[dict]:
    """``lldp/neighbor/info/get`` → LLDP neighbor info (empty or uplink)."""
    return []


def _lldp_local_info(mac: str, pon: int, params: dict) -> dict:
    return {"chassisId": mac, "systemName": f"OLT-{mac[-5:]}", "portCount": 2}


def _lldp_statistic(mac: str, pon: int, params: dict) -> list[dict]:
    return [
        {"port": p, "txFrames": stats.synthetic_int(mac, f"lldpTx{p}", 0, 10000),
         "rxFrames": stats.synthetic_int(mac, f"lldpRx{p}", 0, 10000),
         "discardedFrames": 0}
        for p in range(1, 3)
    ]


# ---------------------------------------------------------------------------
# L2: MAC address
# ---------------------------------------------------------------------------

def _mac_address_list(mac: str, pon: int, params: dict) -> list[dict]:
    """``mac-address/list`` → MAC address list."""
    return [
        {"mac": _mac_for_index(mac, "mac", i), "vlanId": 1, "port": 1, "type": "DYNAMIC"}
        for i in range(1, 4)
    ]


# ---------------------------------------------------------------------------
# L3: routing / ARP / interface / DHCP
# ---------------------------------------------------------------------------

def _routing_table_ipv4(mac: str, pon: int, params: dict) -> list[dict]:
    """``routing-table/ipv4-tables/list`` → IPv4 routing table."""
    return [
        {"destIp": "0.0.0.0/0", "nextHop": "192.168.1.1", "interface": "vlan1",
         "distance": 1, "protocol": "STATIC"},
        {"destIp": "192.168.1.0/24", "nextHop": "0.0.0.0", "interface": "vlan1",
         "distance": 0, "protocol": "DIRECT"},
    ]


def _routing_table_ipv6(mac: str, pon: int, params: dict) -> list[dict]:
    """``routing-table/ipv6-tables/list`` → IPv6 routing table."""
    return []


def _static_routing_ipv4(mac: str, pon: int, params: dict) -> list[dict]:
    return [
        {"destIp": "0.0.0.0", "mask": "0.0.0.0", "nextHop": "192.168.1.1",
         "interface": "vlan1", "distance": 1}
    ]


def _static_routing_ipv6(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _interface_configs(mac: str, pon: int, params: dict) -> list[dict]:
    """``interface/interface-configs/...`` → interface config list."""
    return [
        {"interfaceName": "vlan1", "ipAddress": "192.168.1.2", "mask": "255.255.255.0",
         "interfaceType": "VLAN", "status": "UP"},
    ]


def _interface_routing(mac: str, pon: int, params: dict) -> dict:
    """``interface/routing-configs/get`` → routing interface config."""
    return {"interfaceName": "vlan1", "ipAddress": "192.168.1.2", "mask": "255.255.255.0"}


def _arp_table(mac: str, pon: int, params: dict) -> list[dict]:
    """``arp/arp-tables/list`` → ARP table list."""
    return [
        {"interfaceName": "vlan1", "ipAddress": "192.168.1.1",
         "macAddress": "00:00:00:00:00:01", "type": "DYNAMIC"},
        {"interfaceName": "vlan1", "ipAddress": "192.168.1.100",
         "macAddress": _mac_for_index(mac, "arp", 1), "type": "DYNAMIC"},
    ]


def _gratuitous_arp(mac: str, pon: int, params: dict) -> dict:
    """``arp/gratuitous-arp/configs/list`` → GARP config."""
    return {"status": "DISABLE"}


def _proxy_arp(mac: str, pon: int, params: dict) -> dict:
    return {"status": "DISABLE"}


def _static_arp(mac: str, pon: int, params: dict) -> list[dict]:
    return []


# ---------------------------------------------------------------------------
# Multicast: IGMP / MLD / MVR
# ---------------------------------------------------------------------------

def _igmp_global(mac: str, pon: int, params: dict) -> dict:
    """``igmp/global-config/get`` → IGMP global config."""
    return {
        "status": "ENABLE",
        "version": "V2",
        "unknownMulticastGroup": "DISCARD",
        "headerValidation": "DISABLE",
    }


def _igmp_vlan_configs(mac: str, pon: int, params: dict) -> list[dict]:
    return [{"vlanId": 200, "status": "ENABLE", "querier": "ENABLE"}]


def _igmp_port_configs(mac: str, pon: int, params: dict) -> list[dict]:
    return [
        {"port": p, "status": "ENABLE", "fastLeave": "ENABLE"}
        for p in range(1, 3)
    ]


def _igmp_static_group(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _mld_global(mac: str, pon: int, params: dict) -> dict:
    return {"status": "DISABLE", "version": "V1"}


def _mld_vlan_configs(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _mld_port_configs(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _mld_static_group(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _mvr_config(mac: str, pon: int, params: dict) -> dict:
    """``mvr/config/configs/get`` → MVR config."""
    return {
        "status": "DISABLE",
        "mvrMode": "NORMAL",
        "multicastVlanId": 0,
        "queryResponseTime": 10,
        "maxMulticastGroups": 256,
        "currentMulticastGroups": 0,
    }


def _mvr_group_configs(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _mvr_port_configs(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _multicast_info_stats(mac: str, pon: int, params: dict) -> list[dict]:
    """``multicast/info/statistics/list`` → multicast statistics."""
    return []


# ---------------------------------------------------------------------------
# Security: ACL / port-security / access-security
# ---------------------------------------------------------------------------

def _acl_configs(mac: str, pon: int, params: dict) -> list[dict]:
    """``acl/configs/list`` → ACL config list."""
    return [
        {"aclId": 1, "aclType": "MAC", "aclName": "default-mac-acl", "ruleCount": 0},
        {"aclId": 2, "aclType": "IP", "aclName": "default-ip-acl", "ruleCount": 0},
    ]


def _acl_rules_ip(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _acl_rules_ipv6(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _acl_rules_mac(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _acl_rules_combined(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _acl_binding_port(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _acl_binding_vlan(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _port_security(mac: str, pon: int, params: dict) -> list[dict]:
    """``port-security/port/configs/list`` → port security config."""
    return [
        {"port": p, "status": "DISABLE", "maxMac": 1} for p in range(1, 3)
    ]


def _access_security_ssh(mac: str, pon: int, params: dict) -> dict:
    """``access-security/ssh/configs/get`` → SSH config."""
    return {"status": "ENABLE", "port": 22}


# ---------------------------------------------------------------------------
# QoS
# ---------------------------------------------------------------------------

def _qos_dscp(mac: str, pon: int, params: dict) -> dict:
    """``qos/cos/dscp/configs/list`` → DSCP priority config."""
    return {"dscp": 0, "cos": 0}


def _qos_port_unit1(mac: str, pon: int, params: dict) -> list[dict]:
    """``qos/cos/port/unit1/configs/list`` → per-port CoS config."""
    return [
        {"port": p, "trust": "DSCP", "defaultCos": 0} for p in range(1, 3)
    ]


def _qos_port_lags(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _qos_scheduler(mac: str, pon: int, params: dict) -> dict:
    """``qos/cos/scheduler/configs/list`` → scheduler config."""
    return {"mode": "SP", "weight": "1,2,4,8"}


def _auto_voip_global(mac: str, pon: int, params: dict) -> dict:
    """``auto-voip/global/configs/get``."""
    return {"status": "DISABLE"}


def _auto_voip_port(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _voice_vlan_global(mac: str, pon: int, params: dict) -> dict:
    return {"status": "DISABLE", "vlanId": 0}


def _voice_vlan_port(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _voice_vlan_oui(mac: str, pon: int, params: dict) -> list[dict]:
    return []


# ---------------------------------------------------------------------------
# System: info / monitor / board / DDM / boot-config / time
# ---------------------------------------------------------------------------

def _system_info(mac: str, pon: int, params: dict) -> dict:
    """``system-info/configs/get`` → system info."""
    return {
        "systemDescription": "PON OLT",
        "deviceName": f"OLT-{mac[-5:]}",
        "deviceLocation": "",
        "contactInformation": "",
        "mac": mac,
        "serialNumber": _seq(mac, "sn", 1),
        "hardwareVersion": "1.0",
        "firmwareVersion": "1.0.0",
        "bootLoaderVersion": "1.0.0",
        "systemTime": "2026-01-01 00:00:00",
        "runningTime": "0d 0h 0m 0s",
        "jumboFrameStatus": "DISABLE",
        "sntpStatus": "ENABLE",
        "igmpSnoopingStatus": "ENABLE",
        "snmpStatus": "DISABLE",
        "spanningTreeStatus": "ENABLE",
        "dhcpRelayStatus": "DISABLE",
        "httpServerStatus": "ENABLE",
        "telnetStatus": "DISABLE",
        "sshStatus": "ENABLE",
    }


def _system_led(mac: str, pon: int, params: dict) -> dict:
    """``system-info/led/configs/get``."""
    return {"ledStatus": "ENABLE"}


def _system_time(mac: str, pon: int, params: dict) -> dict:
    return {"timeSource": "SNTP", "timeZone": "UTC", "sntpServer": "pool.ntp.org"}


def _system_ui_config(mac: str, pon: int, params: dict) -> dict:
    return {"uiConfig": "default"}


def _system_port_bandwidth(mac: str, pon: int, params: dict) -> dict:
    return {"bandwidthUtilization": stats.synthetic_int(mac, "bwutil", 1, 80)}


def _system_cpu(mac: str, pon: int, params: dict) -> list[dict]:
    """``system-monitor/cpu/list`` → CPU utilisation history."""
    return [{"cpuUti": stats.synthetic_percent(mac, "cpu", 2, 15)}]


def _system_memory(mac: str, pon: int, params: dict) -> list[dict]:
    """``system-monitor/memory/list`` → memory utilisation history."""
    return [{"memUti": stats.synthetic_percent(mac, "mem", 10, 40)}]


def _board_control(mac: str, pon: int, params: dict) -> dict:
    """``system/board/control-board/load`` → board info."""
    return {
        "boardDetail": {
            "slot": 1,
            "runningStatus": "RUNNING",
            "activeStatus": "ACTIVE",
            "hardwareVersion": "1.0",
            "softwareVersion": "1.0.0",
            "cpu": stats.synthetic_percent(mac, "boardcpu", 2, 15),
            "macAddress": mac,
            "seNumber": _seq(mac, "board", 1),
            "backupLoaded": True,
        },
        "boardControl": {"autoLoad": "ENABLE", "forwardingMode": "NORMAL"},
        "linkBackupConfig": {"autoRecover": "ENABLE"},
    }


def _board_service(mac: str, pon: int, params: dict) -> dict:
    return {
        "boardDetail": {
            "slot": 2,
            "runningStatus": "RUNNING",
            "activeStatus": "ACTIVE",
            "hardwareVersion": "1.0",
            "softwareVersion": "1.0.0",
            "cpu": stats.synthetic_percent(mac, "svccpu", 2, 15),
            "macAddress": mac,
            "seNumber": _seq(mac, "svcboard", 1),
            "backupLoaded": False,
        },
        "boardControl": {"autoLoad": "ENABLE", "forwardingMode": "NORMAL"},
        "linkBackupConfig": {"autoRecover": "DISABLE"},
    }


def _board_status(mac: str, pon: int, params: dict) -> dict:
    return {"slot1": "RUNNING", "slot2": "RUNNING"}


def _ddm_port_config(mac: str, pon: int, params: dict) -> list[dict]:
    """``ddm/port/list/get`` → DDM port config list."""
    return [
        {"port": p, "ddmStatus": "ENABLE", "shutdown": "DISABLE", "lag": 0}
        for p in range(1, pon + 1)
    ]


def _ddm_status(mac: str, pon: int, params: dict) -> dict:
    """``ddm/status/info/get`` → DDM status (aggregate)."""
    ports = []
    for p in range(1, pon + 1):
        ports.append({
            "port": p,
            "temperature": 40.0 + (stats._seed_from_mac(f"{mac}:temp{p}") % 20) / 10.0,
            "temperatureFlag": "NORMAL",
            "voltage": 3.2 + (stats._seed_from_mac(f"{mac}:volt{p}") % 10) / 100.0,
            "voltageFlag": "NORMAL",
            "biasCurrent": 15.0 + (stats._seed_from_mac(f"{mac}:bias{p}") % 20) / 10.0,
            "biasCurrentFlag": "NORMAL",
            "txPower": -3.0 + (stats._seed_from_mac(f"{mac}:ddmtx{p}") % 20) / 10.0,
            "txPowerFlag": "NORMAL",
            "rxPower": -20.0 + (stats._seed_from_mac(f"{mac}:ddmrx{p}") % 30) / 10.0,
            "rxPowerFlag": "NORMAL",
            "transmitFault": False,
            "lossOfSignal": False,
            "dataReady": True,
        })
    return {"ports": ports}


def _ddm_threshold_rx_power(mac: str, pon: int, params: dict) -> list[dict]:
    return [
        {"port": p, "highAlarm": -3.0, "lowAlarm": -30.0,
         "highWarn": -8.0, "lowWarn": -25.0}
        for p in range(1, pon + 1)
    ]


def _ddm_threshold_tx_power(mac: str, pon: int, params: dict) -> list[dict]:
    return [
        {"port": p, "highAlarm": 5.0, "lowAlarm": -10.0,
         "highWarn": 2.0, "lowWarn": -7.0}
        for p in range(1, pon + 1)
    ]


def _ddm_threshold_voltage(mac: str, pon: int, params: dict) -> list[dict]:
    return [
        {"port": p, "highAlarm": 3.5, "lowAlarm": 3.0,
         "highWarn": 3.4, "lowWarn": 3.1}
        for p in range(1, pon + 1)
    ]


def _boot_config(mac: str, pon: int, params: dict) -> dict:
    """``system-tools/boot-config/list`` → boot config."""
    return {"bootMode": "NORMAL", "bootImage": "image1"}


def _image_table(mac: str, pon: int, params: dict) -> list[dict]:
    """``system-tools/image-table/list`` → firmware image table.

    Reports two firmware image slots (image1 active/committed, image2
    inactive). If a firmware upgrade is in progress (tracked in the
    per-device upgrade state dict), image2 shows ``active: false`` with the
    new version and ``valid: true`` (downloaded, not yet committed).
    """
    upgrade_state = _UPGRADE_STATE.get(mac, {})
    new_version = upgrade_state.get("newVersion")
    upgrading = upgrade_state.get("status") == "downloading"
    return [
        {"image": "image1", "version": "1.0.0", "active": True,
         "committed": True, "valid": True},
        {"image": "image2",
         "version": new_version or "1.0.0",
         "active": False,
         "committed": False,
         "valid": bool(new_version) or True,
         "downloading": upgrading,
        },
    ]


def _firmware_upgrade_status(mac: str, pon: int, params: dict) -> dict:
    """Return firmware upgrade status for ``system-tools/firmware/upgrade``.

    The controller pushes an ``upgrade`` config (``{reboot, interval}``).
    When the reboot field is set, the OLT applies the downloaded image and
    reboots. This handler returns a synthetic upgrade-status so the
    controller's firmware page shows progress/success.
    """
    state = _UPGRADE_STATE.get(mac, {})
    return {
        "status": state.get("status", "idle"),
        "progress": state.get("progress", 0),
        "newVersion": state.get("newVersion", ""),
        "message": state.get("message", ""),
    }


# ---------------------------------------------------------------------------
# Traffic monitor
# ---------------------------------------------------------------------------

def _traffic_monitor_unit1(mac: str, pon: int, params: dict) -> list[dict]:
    """``traffic-monitor/unit1/list`` → per-port traffic stats."""
    return [
        {"port": p,
         "rx": stats.synthetic_int(mac, f"tmrx{p}", 0, 10000000),
         "tx": stats.synthetic_int(mac, f"tmtx{p}", 0, 10000000)}
        for p in range(1, 3)
    ]


def _traffic_monitor_lags(mac: str, pon: int, params: dict) -> list[dict]:
    return []


# ---------------------------------------------------------------------------
# SNMP
# ---------------------------------------------------------------------------

def _snmp_global(mac: str, pon: int, params: dict) -> dict:
    """``snmp/global/configs/get`` → SNMP global config."""
    return {"status": "DISABLE", "engineId": ""}


def _snmp_communities(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _snmp_v3_users(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _snmp_v3_groups(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _snmp_views(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _snmp_notifications(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _snmp_traps(mac: str, pon: int, params: dict) -> dict:
    return {"status": "DISABLE"}


def _snmp_rmon_alarms(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _snmp_rmon_events(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _snmp_rmon_histories(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _snmp_rmon_statistics(mac: str, pon: int, params: dict) -> list[dict]:
    return []


# ---------------------------------------------------------------------------
# Maintenance: logs / OAM / DLDP / mirror / CFM
# ---------------------------------------------------------------------------

def _log_info(mac: str, pon: int, params: dict) -> list[dict]:
    """``maintenance/log/info/list`` → log entries."""
    return [
        {"time": "2026-01-01 00:00:00", "level": "INFO", "module": "SYSTEM",
         "description": "System started"}
    ]


def _log_local(mac: str, pon: int, params: dict) -> dict:
    """``maintenance/log/local/list`` → local log config."""
    return {"status": "ENABLE", "logLevel": "INFO"}


def _log_remote(mac: str, pon: int, params: dict) -> dict:
    """``maintenance/log/remote/list`` → remote log config."""
    return {"status": "DISABLE", "serverIp": "", "port": 514}


def _log_backup(mac: str, pon: int, params: dict) -> dict:
    return {"backupStatus": "IDLE"}


def _oam_basic(mac: str, pon: int, params: dict) -> dict:
    """``oam/basic-configs/list`` → OAM basic config."""
    return {"status": "ENABLE"}


def _oam_discovery(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _oam_link_monitor(mac: str, pon: int, params: dict) -> dict:
    return {"status": "DISABLE"}


def _oam_statistic(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _dldp_global(mac: str, pon: int, params: dict) -> dict:
    """``maintenance/dldp/globals/get`` → DLDP global config."""
    return {"status": "DISABLE"}


def _dldp_ports(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _mirror_sessions(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _cfm_ma_groups(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _cfm_local_mep(mac: str, pon: int, params: dict) -> list[dict]:
    return []


def _cfm_remote_mep(mac: str, pon: int, params: dict) -> list[dict]:
    return []


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

def _users(mac: str, pon: int, params: dict) -> list[dict]:
    """``user-management/users/list`` → user list."""
    return [
        {"userId": 1, "adoptedAccountFlag": True, "userName": "admin",
         "accessLevelType": "ADMIN", "password": ""},
    ]


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def _diag_ping_config(mac: str, pon: int, params: dict) -> dict:
    """``diagnostics/ping/configs/get``."""
    return {"target": "", "count": 4, "interval": 1, "timeout": 1}


def _diag_ping_results(mac: str, pon: int, params: dict) -> list[dict]:
    """``diagnostics/ping/results/get`` → ping results (empty until run)."""
    return []


def _diag_tracert_config(mac: str, pon: int, params: dict) -> dict:
    return {"target": "", "maxHops": 30, "timeout": 1}


def _diag_tracert_results(mac: str, pon: int, params: dict) -> list[dict]:
    return []


# ---------------------------------------------------------------------------
# System tools (SET operations returning status)
# ---------------------------------------------------------------------------

def _reboot_status(mac: str, pon: int, params: dict) -> dict:
    """``system-tools/reboot/ack`` → reboot acknowledgement."""
    return {"status": "SUCCESS"}


def _config_backup(mac: str, pon: int, params: dict) -> dict:
    """``system-tools/config/backup`` → backup status."""
    return {"status": "SUCCESS"}


def _firmware_upgrade_set(mac: str, pon: int, params: dict) -> dict:
    """``system-tools/firmware/upgrade`` SET → start a synthetic firmware
    upgrade.

    The controller pushes firmware via an ``upgrade`` config ({reboot,
    interval}), or via this URI SET. The emulator records the upgrade state
    so the image-table GET reflects the new image. The ``reboot`` flag in
    params (or the upgrade config's reboot field) triggers the apply step;
    otherwise the image is just downloaded.
    """
    reboot = bool(params.get("reboot", False))
    new_version = params.get("version") or params.get("newVersion") or "1.1.0"
    status = "rebooting" if reboot else "downloading"
    _UPGRADE_STATE[mac] = {
        "status": "success" if reboot else "downloading",
        "progress": 100 if reboot else 50,
        "newVersion": new_version,
        "message": "Firmware upgrade initiated" if not reboot
                   else "Firmware upgraded, rebooting",
    }
    return _firmware_upgrade_status(mac, pon, params)


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

# GET handlers: return synthetic data payloads. Keyed by exact URI string.
# URIs ending in /list, /get, /info/get are read operations.
_GET_HANDLERS: dict[str, UriHandler] = {
    # PON ports
    "pon/pon-port/informations/list": _pon_port_informations,
    "pon/pon-port/configs/list": _pon_port_configs,
    "pon/auto-service-ports/list": _pon_auto_service_ports,
    "pon/service-ports/list": _pon_service_ports,
    "pon/onu-register/autofinds/list": _pon_onu_autofinds,

    # ONU management (information)
    "pon/onu/management/information/list": _onu_information_list,
    "pon/onu/management/information/get": _onu_detail,

    # Profiles — DBA
    "profile/dba/profiles/list": _dba_profiles,
    # Profiles — line
    "profile/line/profiles/list": _line_profiles,
    "profile/line/t-conts/list": _line_tconts,
    "profile/line/gem-ports/list": _line_gem_ports,
    "profile/line/gem-mappings/list": _line_gem_mappings,
    # Profiles — service
    "profile/service/profiles/list": _service_profiles,
    "profile/service/eth-ports/list": _service_eth_ports,
    "profile/service/pots-ports/list": _service_pots_ports,
    # Profiles — traffic
    "profile/traffic/profiles/list": _traffic_profiles,

    # L2 — Ethernet ports
    "eth-port/port/unit1/list": _eth_port_unit1,
    "eth-port/port/mode/list": _eth_port_mode,
    "eth-port/port-isolation/list": _eth_port_isolation,
    "eth-port/port/lags/list": _lag_table,  # no LAG ports

    # L2 — VLAN
    "vlan/8021q/vlan-configs/list": _vlan_configs,
    "vlan/8021q/unit1/configs/list": _vlan_unit1_configs,
    "vlan/8021q/lags/configs/list": _vlan_lags_configs,
    "vlan/gvrp/lags/configs/list": _vlan_gvrp_lags,

    # L2 — LAG
    "lag/lag-table/list": _lag_table,
    "lag/lacp-config/list": _lag_global,
    "lag/lacp-config/get": _lag_global,
    "lag/static-lag/list": _lag_static,

    # L2 — STP
    "stp/summary/summarys/get": _stp_summary,
    "stp/summary/mstp-instances/get": _stp_mstp_summary,
    "stp/config/globals/get": _stp_global_config,
    "stp/config/parameters/get": _stp_parameters,
    "stp/port/unit1/configs/list": _stp_port_unit1,
    "stp/port/lags/configs/list": _stp_port_lags,
    "stp/mstp/instances/list": _stp_mstp_instances,
    "stp/mstp/region-configs/get": _stp_mstp_region,
    "stp/mstp/lags/configs/list": _stp_port_lags,
    "stp/mstp/unit1/configs/list": _stp_port_unit1,
    "stp/security/unit1/configs/list": _stp_port_unit1,
    "stp/security/lags/configs/list": _stp_port_lags,

    # L2 — LLDP
    "lldp/global/configs/get": _lldp_global,
    "lldp/port/config/list": _lldp_port,
    "lldp/neighbor/info/get": _lldp_neighbor,
    "lldp/local/info/get": _lldp_local_info,
    "lldp/statistic/info/get": _lldp_statistic,
    "lldp/parameter/configs/get": _lldp_global,

    # L2 — MAC address
    "mac-address/list": _mac_address_list,

    # L3 — routing
    "routing-table/ipv4-tables/list": _routing_table_ipv4,
    "routing-table/ipv6-tables/list": _routing_table_ipv6,
    "static-routing/ipv4-configs/list": _static_routing_ipv4,
    "static-routing/ipv6-configs/list": _static_routing_ipv6,

    # L3 — interface
    "interface/routing-configs/get": _interface_routing,

    # L3 — ARP
    "arp/arp-tables/list": _arp_table,
    "arp/gratuitous-arp/configs/list": _gratuitous_arp,
    "arp/proxy-arp/configs/list": _proxy_arp,
    "arp/static-arp-configs/list": _static_arp,

    # Multicast — IGMP
    "igmp/global-config/get": _igmp_global,
    "igmp/global/vlan-configs/list": _igmp_vlan_configs,
    "igmp/port/unit1/configs/list": _igmp_port_configs,
    "igmp/port/lags/configs/list": _igmp_port_configs,
    "igmp/static-group/configs/list": _igmp_static_group,

    # Multicast — MLD
    "mld/global-config/get": _mld_global,
    "mld/global/vlan-configs/list": _mld_vlan_configs,
    "mld/port/unit1/configs/list": _mld_port_configs,
    "mld/port/lags/configs/list": _mld_port_configs,
    "mld/static-group/configs/list": _mld_static_group,

    # Multicast — MVR
    "mvr/config/configs/get": _mvr_config,
    "mvr/group/configs/list": _mvr_group_configs,
    "mvr/port/unit1/configs/list": _mvr_port_configs,
    "mvr/static-group/members/list": _mvr_group_configs,

    # Multicast — info
    "multicast/info/statistics/list": _multicast_info_stats,

    # Security — ACL
    "acl/configs/list": _acl_configs,
    "acl/configs/ip/rule/list": _acl_rules_ip,
    "acl/configs/ipv6/rule/list": _acl_rules_ipv6,
    "acl/configs/mac/rule/list": _acl_rules_mac,
    "acl/configs/combined/rule/list": _acl_rules_combined,
    "acl/binding/port/configs/list": _acl_binding_port,
    "acl/binding/vlan/configs/list": _acl_binding_vlan,

    # Security — port security / access security
    "port-security/port/configs/list": _port_security,
    "access-security/ssh/configs/get": _access_security_ssh,

    # QoS
    "qos/cos/dscp/configs/list": _qos_dscp,
    "qos/cos/port/unit1/configs/list": _qos_port_unit1,
    "qos/cos/port/lags/configs/list": _qos_port_lags,
    "qos/cos/scheduler/configs/list": _qos_scheduler,
    "auto-voip/global/configs/get": _auto_voip_global,
    "auto-voip/port/configs/list": _auto_voip_port,
    "qos/voice-vlan/global/configs/get": _voice_vlan_global,
    "qos/voice-vlan/port/configs/list": _voice_vlan_port,
    "qos/voice-vlan/oui/list": _voice_vlan_oui,

    # System — info / monitor / board / DDM / boot / time
    "system-info/configs/get": _system_info,
    "system-info/led/configs/get": _system_led,
    "system-info/system-time/get": _system_time,
    "system-info/ui/configs": _system_ui_config,
    "system-info/port/band-utils/get": _system_port_bandwidth,
    "system-monitor/cpu/list": _system_cpu,
    "system-monitor/memory/list": _system_memory,
    "system/board/control-board/load": _board_control,
    "system/board/service-board/load": _board_service,
    "system/board/status/get": _board_status,
    "ddm/port/list/get": _ddm_port_config,
    "ddm/status/info/get": _ddm_status,
    "ddm/threshold/rx-power/list/get": _ddm_threshold_rx_power,
    "ddm/threshold/tx-power/list/get": _ddm_threshold_tx_power,
    "ddm/threshold/voltage/list/get": _ddm_threshold_voltage,
    "system-tools/boot-config/list": _boot_config,
    "system-tools/image-table/list": _image_table,
    "system-tools/firmware/upgrade/status": _firmware_upgrade_status,

    # Traffic monitor
    "traffic-monitor/unit1/list": _traffic_monitor_unit1,
    "traffic-monitor/lags/list": _traffic_monitor_lags,

    # SNMP
    "snmp/global/configs/get": _snmp_global,
    "snmp/v1-v2c/communities/list": _snmp_communities,
    "snmp/v3/users/list": _snmp_v3_users,
    "snmp/v3/groups/list": _snmp_v3_groups,
    "snmp/global/view-configs/list": _snmp_views,
    "snmp/notification/configs/list": _snmp_notifications,
    "snmp/notification/traps/get": _snmp_traps,
    "snmp/rmon/alarms/list": _snmp_rmon_alarms,
    "snmp/rmon/events/list": _snmp_rmon_events,
    "snmp/rmon/histories/list": _snmp_rmon_histories,
    "snmp/rmon/statistics/list": _snmp_rmon_statistics,

    # Maintenance — logs
    "maintenance/log/info/list": _log_info,
    "maintenance/log/local/list": _log_local,
    "maintenance/log/remote/list": _log_remote,
    "maintenance/log/back-up/get": _log_backup,

    # Maintenance — OAM / DLDP / mirror / CFM
    "oam/basic-configs/list": _oam_basic,
    "oam/discovery-info-configs/list": _oam_discovery,
    "oam/link-monitor-configs/list": _oam_link_monitor,
    "oam/statistic/pdu-configs/list": _oam_statistic,
    "maintenance/dldp/globals/get": _dldp_global,
    "maintenance/dldp/ports/list": _dldp_ports,
    "maintenance/mirror/sessions/list": _mirror_sessions,
    "maintenance/cfm/ma-group/list": _cfm_ma_groups,
    "maintenance/cfm/local-mep/list": _cfm_local_mep,
    "maintenance/cfm/remote-mep/list": _cfm_remote_mep,

    # User management
    "user-management/users/list": _users,

    # Diagnostics
    "diagnostics/ping/configs/get": _diag_ping_config,
    "diagnostics/ping/results/get": _diag_ping_results,
    "diagnostics/tracert/configs/get": _diag_tracert_config,
    "diagnostics/tracert/results/get": _diag_tracert_results,
}

# SET handlers: operations that modify config and return a status payload
# (most SET operations just return data:null with errcode:0). Keyed by URI.
_SET_HANDLERS: dict[str, UriHandler] = {
    "system-tools/reboot/now": _reboot_status,
    "system-tools/reboot/ack": _reboot_status,
    "system-tools/config/backup": _config_backup,
    "system-tools/config/save": _config_backup,
    "system-tools/config/restore": _config_backup,
    "system-tools/firmware/upgrade": _firmware_upgrade_set,
}


def handle_get(uri: str, mac: str, pon_port_count: int,
               params: dict[str, Any]) -> Any:
    """Return synthetic ``data`` for an OLT URI-RPC GET request.

    If the URI is not in the dispatch table, returns ``None`` (so the
    response carries ``data: null`` — the controller shows an
    empty section but no error).
    """
    handler = _GET_HANDLERS.get(uri)
    if handler is None:
        return None
    return handler(mac, pon_port_count, params)


def handle_set(uri: str, mac: str, pon_port_count: int,
               params: dict[str, Any]) -> Any:
    """Return synthetic ``data`` for an OLT URI-RPC SET (mutation) request.

    Most SET operations return ``None`` (data:null, errcode:0). A few
    status-returning operations (reboot, backup) return a small status object.
    """
    handler = _SET_HANDLERS.get(uri)
    if handler is None:
        return None
    return handler(mac, pon_port_count, params)


# URIs that are known SET (mutation) operations — used for logging/debugging.
SET_URIS: frozenset[str] = frozenset(
    uri for uri in (
        # PON
        "pon/pon-port/configs/edit",
        "pon/auto-service-ports/edit",
        "pon/service-ports/add", "pon/service-ports/edit", "pon/service-ports/delete",
        # Profiles
        "profile/dba/profiles/add", "profile/dba/profiles/edit", "profile/dba/profiles/delete",
        "profile/line/profiles/add", "profile/line/profiles/edit", "profile/line/profiles/delete",
        "profile/line/t-conts/add", "profile/line/t-conts/edit", "profile/line/t-conts/delete",
        "profile/line/gem-ports/add", "profile/line/gem-ports/edit", "profile/line/gem-ports/delete",
        "profile/line/gem-mappings/add", "profile/line/gem-mappings/edit",
        "profile/service/profiles/add", "profile/service/profiles/edit", "profile/service/profiles/delete",
        "profile/service/eth-ports/edit", "profile/service/pots-ports/edit",
        "profile/traffic/profiles/add", "profile/traffic/profiles/edit", "profile/traffic/profiles/delete",
        # L2
        "eth-port/port/unit1/edit", "eth-port/port/lags/edit", "eth-port/port-isolation/edit",
        "vlan/8021q/vlan-configs/add", "vlan/8021q/vlan-configs/edit", "vlan/8021q/vlan-configs/delete",
        "vlan/8021q/unit1/configs/edit", "vlan/8021q/lags/configs/edit",
        "lag/lag-table/delete", "lag/lacp-config/edit", "lag/static-lag/edit",
        "stp/config/globals/edit", "stp/config/parameters/edit",
        "stp/port/unit1/configs/edit", "stp/port/lags/configs/edit",
        "stp/mstp/instances/add", "stp/mstp/instances/edit", "stp/mstp/instances/delete",
        "stp/mstp/region-configs/edit", "stp/mstp/lags/configs/edit", "stp/mstp/unit1/configs/edit",
        "stp/security/unit1/configs/edit", "stp/security/lags/configs/edit",
        "lldp/global/configs/edit", "lldp/port/config/edit", "lldp/parameter/configs/edit",
        "lldp/statistic/info/delete",
        "mac-address/delete", "mac-address/filter/add", "mac-address/static/add",
        "mac-address/dynamic/bind/edit",
        # L3
        "interface/interface-configs/add", "interface/routing-configs/edit",
        "static-routing/ipv4-configs/add", "static-routing/ipv6-configs/add",
        "arp/static-arp-configs/add", "arp/static-arp-configs/delete",
        "arp/gratuitous-arp/configs/edit", "arp/proxy-arp/configs/edit",
        # Multicast
        "igmp/global-config/edit", "igmp/global/vlan-configs/edit",
        "igmp/port/unit1/configs/edit", "igmp/port/lags/configs/edit",
        "igmp/static-group/configs/add",
        "mld/global-config/edit", "mld/global/vlan-configs/edit",
        "mld/port/unit1/configs/edit", "mld/port/lags/configs/edit",
        "mld/static-group/configs/add", "mld/static-group/configs/delete",
        "mvr/config/configs/edit", "mvr/group/configs/add", "mvr/group/configs/delete",
        "mvr/port/unit1/configs/edit", "mvr/static-group/members/edit",
        # Security
        "acl/configs/add", "acl/configs/delete", "acl/configs/rule/delete",
        "acl/configs/rule/ip/add", "acl/configs/rule/ip/edit",
        "acl/configs/rule/ipv6/add", "acl/configs/rule/ipv6/edit",
        "acl/configs/rule/mac/add", "acl/configs/rule/mac/edit",
        "acl/configs/rule/combined/add", "acl/configs/rule/combined/edit",
        "acl/configs/rule/resequence",
        "acl/binding/port/configs/add", "acl/binding/port/configs/delete",
        "acl/binding/vlan/configs/add", "acl/binding/vlan/configs/delete",
        "port-security/port/configs/edit",
        "access-security/ssh/key/edit", "access-security/ssh/key/delete",
        "access-security/https/key/edit",
        # QoS
        "qos/cos/dscp/configs/edit", "qos/cos/port/unit1/configs/edit",
        "qos/cos/port/lags/configs/edit", "qos/cos/scheduler/configs/edit",
        "auto-voip/global/configs/edit", "auto-voip/port/configs/edit",
        # System
        "system-info/configs/edit", "system-info/led/configs/edit",
        "system-tools/boot-config/edit", "system-tools/factory-reset",
        "system/board/control-board/load",
        "ddm/port/list/edit", "ddm/threshold/voltage/list/edit",
        # SNMP
        "snmp/global/configs/edit",
        "snmp/v1-v2c/communities/add", "snmp/v1-v2c/communities/edit", "snmp/v1-v2c/communities/delete",
        "snmp/v3/users/add", "snmp/v3/users/edit", "snmp/v3/users/delete",
        "snmp/v3/groups/add", "snmp/v3/groups/edit", "snmp/v3/groups/delete",
        "snmp/global/view-configs/add", "snmp/global/view-configs/edit", "snmp/global/view-configs/delete",
        "snmp/notification/configs/add", "snmp/notification/configs/edit",
        "snmp/notification/traps/edit",
        "snmp/rmon/alarms/edit", "snmp/rmon/events/edit", "snmp/rmon/histories/edit",
        "snmp/rmon/statistics/add", "snmp/rmon/statistics/edit", "snmp/rmon/statistics/delete",
        # Maintenance
        "maintenance/log/local/edit", "maintenance/log/remote/edit",
        "maintenance/dldp/globals/edit", "maintenance/dldp/ports/edit",
        "maintenance/cfm/ma-group/add", "maintenance/cfm/ma-group/edit", "maintenance/cfm/ma-group/delete",
        "maintenance/cfm/local-mep/add", "maintenance/cfm/local-mep/edit",
        "maintenance/cfm/remote-mep/add", "maintenance/cfm/remote-mep/edit",
        "maintenance/mirror/sessions/edit",
        # Users
        "user-management/users/add", "user-management/users/edit", "user-management/users/delete",
        # Diagnostics
        "bandwidth/storm/port/recover",
        "traffic-monitor/unit1/clear", "traffic-monitor/lags/clear",
        "oam/basic-configs/edit", "oam/link-monitor-configs/edit",
        "oam/statistic/pdu-configs/clear",
        # Device setting
        "device-setting/migrate",
        # Time range
        "time-range/holiday-configs/add",
    )
)


def covered_get_uris() -> frozenset[str]:
    """Return the set of GET URIs the dispatch table covers."""
    return frozenset(_GET_HANDLERS)


def covered_set_uris() -> frozenset[str]:
    """Return the set of SET URIs with dedicated status handlers."""
    return frozenset(_SET_HANDLERS)