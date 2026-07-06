"""Unit tests for the gateway runtime-service INFORM sections (VPN, SSL-VPN,
WireGuard, DDNS, QoS, connection-tracking, port-forwarding, IPS, network
traffic) and the extended SET/GET response flow."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.devices.registry import build_device


def _make_gateway():
    return build_device(
        {
            "name": "gw-01",
            "type": "gateway",
            "model": "ER605",
            "mac": "AA-BB-CC-DD-EE-03",
            "ip": "192.168.56.70",
        }
    )


def test_gateway_inform_has_vpn_sections():
    gw = _make_gateway()
    extra = gw.manage_inform_extra()
    for key in ("vpn", "sslVpn", "wireguard"):
        assert key in extra, f"missing {key} section"


def test_gateway_vpn_section_shape():
    gw = _make_gateway()
    vpn = gw.manage_inform_extra()["vpn"]
    assert "ipSecs" in vpn and "openvpn" in vpn and "tuns" in vpn
    assert isinstance(vpn["ipSecs"], list) and vpn["ipSecs"]
    # IPsec required fields
    ipsec = vpn["ipSecs"][0]
    for f in ("id", "direct", "protocol", "spi", "localTun", "peerTun"):
        assert f in ipsec


def test_gateway_ssl_vpn_section_shape():
    gw = _make_gateway()
    ssl = gw.manage_inform_extra()["sslVpn"]
    assert "connections" in ssl and "locks" in ssl
    conn = ssl["connections"][0]
    for f in ("id", "user", "vIp", "lIp", "up", "down", "authType", "time"):
        assert f in conn


def test_gateway_wireguard_section_shape():
    gw = _make_gateway()
    wg = gw.manage_inform_extra()["wireguard"]
    assert "connections" in wg and "interfaces" in wg
    iface = wg["interfaces"][0]
    for f in ("id", "activePeers", "totalPeers"):
        assert f in iface
    tun = wg["connections"][0]
    for f in ("id", "ip", "port", "up", "upp", "down", "downp", "hshake", "status"):
        assert f in tun


def test_gateway_ddns_section_shape():
    gw = _make_gateway()
    ddns = gw.manage_inform_extra()["ddns"]
    assert "ddnss" in ddns
    entry = ddns["ddnss"][0]
    for f in ("id", "domain", "interface", "ip", "status", "statusMsg", "lastUpdated"):
        assert f in entry
    # domain is a list of strings
    assert isinstance(entry["domain"], list)
    # interface is an Integer (port id)
    assert isinstance(entry["interface"], int)


def test_gateway_qos_section_shape():
    gw = _make_gateway()
    qos = gw.manage_inform_extra()["qos"]
    assert "data" in qos
    entry = qos["data"][0]
    for f in ("port", "throughputs", "voip"):
        assert f in entry
    # throughputs is a list of class data entries {class, inbound, outbound}
    tp = entry["throughputs"][0]
    for f in ("class", "inbound", "outbound"):
        assert f in tp
    # voip is a voip data entry {inbound, outbound}
    for f in ("inbound", "outbound"):
        assert f in entry["voip"]


def test_gateway_ct_table_section_shape():
    gw = _make_gateway()
    ct = gw.manage_inform_extra()["ctTable"]
    assert "ctMax" in ct and "ctNum" in ct
    assert isinstance(ct["ctMax"], int) and isinstance(ct["ctNum"], int)


def test_gateway_portforward_section_shape():
    gw = _make_gateway()
    pf = gw.manage_inform_extra()["portforward"]
    assert "users" in pf and "upnps" in pf
    user = pf["users"][0]
    for f in ("id", "name", "proto", "inip", "inport", "infa", "export", "bts", "pkts", "dura"):
        assert f in user
    # infa is a list of integers
    assert isinstance(user["infa"], list)


def test_gateway_network_traffic_section_shape():
    gw = _make_gateway()
    nt = gw.manage_inform_extra()["networkTraffic"]
    assert "networkTraffics" in nt
    entry = nt["networkTraffics"][0]
    for f in ("ip", "ip6", "rx", "tx", "vlan", "dhcpsUtil", "dhcps6Util", "dhcpsOffer", "dhcps6Offer"):
        assert f in entry


def test_gateway_ips_threat_section_shape():
    gw = _make_gateway()
    ips = gw.manage_inform_extra()["ipsThreat"]
    assert "data" in ips
    entry = ips["data"][0]
    for f in ("time", "severity", "threatDescription", "categoryId", "srcIp", "dstIp", "protocol", "sid"):
        assert f in entry


def test_gateway_set_response_captures_feature_configs():
    gw = _make_gateway()
    req = {
        "sequenceId": 1,
        "configVersion": 5,
        "firewallConfig": {"enable": 1},
        "vpn": {"enable": 1},
        "vpnUser": {"users": []},
        "ddns": {"enable": 1},
        "qos": {"enable": 1},
        "sessionLimit": {"enable": 1},
    }
    resp = gw.build_set_response(req)
    assert resp["errcode"] == 0
    assert resp["configVersion"] == 5
    assert "firewallConfig" in gw._applied_configs
    assert "vpn" in gw._applied_configs
    assert "vpnUser" in gw._applied_configs
    assert "ddns" in gw._applied_configs
    assert "qos" in gw._applied_configs
    assert "sessionLimit" in gw._applied_configs


def test_gateway_applied_config_is_isolated_from_request_and_response_mutation():
    gw = _make_gateway()
    request = {"vpn": {"enable": 1, "tunnels": [{"id": 7}]}}
    gw.build_set_response(request)
    request["vpn"]["tunnels"][0]["id"] = 99
    assert gw._applied_configs["vpn"]["tunnels"][0]["id"] == 7

    response = gw.build_get_response({})
    response["vpn"]["tunnels"][0]["id"] = 42
    assert gw._applied_configs["vpn"]["tunnels"][0]["id"] == 7


def test_gateway_get_response_echoes_applied_configs():
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1,
        "configVersion": 5,
        "vpn": {"enable": 1, "tunnels": []},
        "ddns": {"enable": 1},
        "sessionLimit": {"enable": 1, "max": 20000},
    })
    resp = gw.build_get_response({"sequenceId": 10})
    assert resp["errcode"] == 0
    assert "wanIpv4" in resp
    assert resp["vpn"] == {"enable": 1, "tunnels": []}
    assert resp["ddnsStats"] == {"enable": 1}
    assert resp["sessionLimit"] == {"enable": 1, "max": 20000}


def test_gateway_full_inform_body_contains_all_new_sections():
    gw = _make_gateway()
    body = gw.manage_inform_body()
    for key in (
        "deviceInfo", "portInfo", "trafficStat", "client", "dhcpClient", "arp",
        "routingTable", "vpn", "sslVpn", "wireguard", "ddns", "qos",
        "ctTable", "portforward", "networkTraffic", "ipsThreat",
    ):
        assert key in body, f"INFORM body missing {key}"


# -- New section shape tests (confirmed field shapes, v6.2.14.11) --

def test_gateway_sdwan_section_shape():
    # ER605 does not support SD-WAN — no sdwan section.
    gw = _make_gateway()
    extra = gw.manage_inform_extra()
    assert "sdwan" not in extra  # ER605 has no SD-WAN support


def test_gateway_sdwan_on_supporting_model():
    from device_emulator.devices.gateway_profiles import get_profile
    gw = build_device({
        "name": "gw-sdwan", "type": "gateway", "model": "ER7206",
        "mac": "AA-BB-CC-DD-EE-13", "ip": "192.168.56.72",
    })
    extra = gw.manage_inform_extra()
    assert "sdwan" in extra
    assert "tuns" in extra["sdwan"]
    assert isinstance(extra["sdwan"]["tuns"], list)
    assert "remoteTun" in extra["sdwan"]["tuns"][0]


def test_gateway_virtual_wan_section_on_supporting_model():
    gw = build_device({
        "name": "gw-vwan", "type": "gateway", "model": "ER7206",
        "mac": "AA-BB-CC-DD-EE-14", "ip": "192.168.56.72",
    })
    extra = gw.manage_inform_extra()
    assert "virtualWanInfo" in extra
    vws = extra["virtualWanInfo"]["virtualWans"]
    assert isinstance(vws, list) and vws
    for f in ("virtualWanEntryId", "ip", "ip2", "status", "internetState",
              "onlineDetection", "mac", "ipv4"):
        assert f in vws[0]
    for f in ("gw", "gw2", "priDns", "sndDns", "priDns2", "sndDns2"):
        assert f in vws[0]["ipv4"]


def test_gateway_lte_section_on_supporting_model():
    gw = build_device({
        "name": "gw-lte", "type": "gateway", "model": "ER706W",
        "mac": "AA-BB-CC-DD-EE-15", "ip": "192.168.56.71",
    })
    extra = gw.manage_inform_extra()
    assert "lte" in extra
    assert "selectedApns" in extra["lte"]
    assert isinstance(extra["lte"]["selectedApns"], list)


def test_gateway_lte_section_absent_on_er605():
    gw = _make_gateway()
    extra = gw.manage_inform_extra()
    assert "lte" not in extra


def test_gateway_client_traffic_section_shape():
    gw = _make_gateway()
    ct = gw.manage_inform_extra()["clientTraffic"]
    assert "traffic" in ct
    if ct["traffic"]:
        entry = ct["traffic"][0]
        for f in ("mac", "tx", "rx", "txP", "rxP"):
            assert f in entry


def test_gateway_abnormal_dt_section_shape():
    gw = _make_gateway()
    adt = gw.manage_inform_extra()["abnormalDt"]
    assert "access" in adt and "dev" in adt
    assert isinstance(adt["access"], list)
    assert isinstance(adt["dev"], list)


def test_gateway_event_inform_section_shape():
    gw = _make_gateway()
    ei = gw.manage_inform_extra()["eventInform"]
    assert isinstance(ei, list)


def test_gateway_acl_hit_section_shape():
    gw = _make_gateway()
    ah = gw.manage_inform_extra()["aclHit"]
    assert isinstance(ah, list)


def test_gateway_portal_duration_section_shape():
    gw = _make_gateway()
    pd = gw.manage_inform_extra()["portalDuration"]
    assert "portalDurations" in pd
    assert isinstance(pd["portalDurations"], list)


def test_gateway_applications_traffic_section_shape():
    gw = _make_gateway()
    at = gw.manage_inform_extra()["applicationsTraffic"]
    assert "traffic" in at and "block" in at


def test_gateway_monitor_section_shape():
    gw = _make_gateway()
    mon = gw.manage_inform_extra()["monitor"]
    assert "link" in mon


def test_gateway_cfg_results_section_shape():
    gw = _make_gateway()
    cr = gw.manage_inform_extra()["cfgResults"]
    assert "setResults" in cr


def test_gateway_last_cfg_result_after_set():
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "firewallConfig": {"enable": 1},
    })
    extra = gw.manage_inform_extra()
    assert "lastCfgResult" in extra
    assert extra["lastCfgResult"]["errcode"] == 0


def test_gateway_ipv6_on_wan_port():
    gw = _make_gateway()
    port_infos = gw.manage_inform_extra()["portInfo"]["portInfos"]
    wan = [p for p in port_infos if p["port"] == 1][0]
    assert wan["internetV6"] == 1
    assert "ip2" in wan
    assert "ip6" in wan
    for f in ("addr", "gw", "priDns", "sndDns", "prefix"):
        assert f in wan["ip6"]


def test_gateway_set_response_has_per_feature_acks():
    gw = _make_gateway()
    resp = gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "firewallConfig": {"enable": 1},
        "vpn": {"enable": 1},
        "qos": {"enable": 1},
        "wireguard": {"enable": 1},
    })
    assert resp["errcode"] == 0
    assert resp["firewallConfig"] == {"errcode": 0}
    assert resp["vpn"] == {"errcode": 0}
    assert resp["qos"] == {"errcode": 0}
    assert resp["wireguard"] == {"errcode": 0}


def test_gateway_get_response_echoes_all_captured_configs():
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "vpn": {"enable": 1, "tunnels": []},
        "sslVpn": {"enable": 1},
        "ddns": {"enable": 1},
        "sessionLimit": {"enable": 1, "max": 20000},
        "firewallConfig": {"enable": 1},
        "qos": {"enable": 1},
        "wireguard": {"enable": 1},
        "acl": {"rules": []},
    })
    resp = gw.build_get_response({"sequenceId": 10})
    assert resp["errcode"] == 0
    assert "wanIpv4" in resp
    assert resp["vpn"] == {"enable": 1, "tunnels": []}
    assert resp["sslVpn"] == {"enable": 1}
    assert resp["ddnsStats"] == {"enable": 1}
    assert resp["sessionLimit"] == {"enable": 1, "max": 20000}
    assert resp["firewallConfig"] == {"enable": 1}
    assert resp["qos"] == {"enable": 1}
    assert resp["wireguard"] == {"enable": 1}
    assert resp["aclHit"] == {"rules": []}


def test_gateway_config_driven_vpn_tunnel_count():
    gw = _make_gateway()
    # Push a vpn config with 3 IPsec tunnels.
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "vpn": {"ipsecTunnels": [
            {"id": 1, "peerTun": "203.0.113.1"},
            {"id": 2, "peerTun": "203.0.113.2"},
            {"id": 3, "peerTun": "203.0.113.3"},
        ]},
    })
    vpn = gw.manage_inform_extra()["vpn"]
    assert len(vpn["ipSecs"]) == 3
    assert vpn["ipSecs"][0]["peerTun"] == "203.0.113.1"
    assert vpn["ipSecs"][2]["peerTun"] == "203.0.113.3"


def test_gateway_config_driven_wireguard_peer_count():
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "wireguard": {
            "interfaces": [{"id": 1}],
            "peers": [
                {"id": 1, "ip": "10.9.1.1"},
                {"id": 2, "ip": "10.9.2.1"},
                {"id": 3, "ip": "10.9.3.1"},
                {"id": 4, "ip": "10.9.4.1"},
                {"id": 5, "ip": "10.9.5.1"},
            ],
        },
    })
    wg = gw.manage_inform_extra()["wireguard"]
    assert len(wg["connections"]) == 5
    assert wg["interfaces"][0]["activePeers"] == 5
    assert wg["interfaces"][0]["totalPeers"] == 5


def test_gateway_config_driven_ssl_vpn_user_count():
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "sslVpn": {"users": [
            {"id": 1, "name": "alice"},
            {"id": 2, "name": "bob"},
            {"id": 3, "name": "charlie"},
        ]},
    })
    ssl = gw.manage_inform_extra()["sslVpn"]
    assert len(ssl["connections"]) == 3
    assert ssl["connections"][0]["user"] == "alice"


# ---------------------------------------------------------------------------
# Phase 1: config-driven INFORM sections
# ---------------------------------------------------------------------------

def test_gateway_routing_table_reflects_pushed_static_routing():
    """routingTable INFORM section echoes pushed staticRouting config."""
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "staticRouting": {"staticRoutings": [
            {"id": 10, "destinations": ["10.50.0.0/16"], "nextHopIp": "10.0.2.1",
             "interface": 2, "metric": 5},
            {"id": 11, "destinations": ["172.16.0.0/12"], "nextHopIp": "10.0.2.1",
             "interface": 3, "metric": 5},
        ]},
    })
    routes = gw.manage_inform_extra()["routingTable"]["routingTables"]
    # 2 baseline + 2 pushed
    assert len(routes) == 4
    pushed = [r for r in routes if r["id"] in (10, 11)]
    assert len(pushed) == 2
    assert pushed[0]["destIp"] == ["10.50.0.0/16"]
    assert pushed[0]["nextHop"] == "10.0.2.1"
    assert pushed[0]["interfaceName"] == "lan2"
    assert pushed[0]["metric"] == 5


def test_gateway_ddns_reflects_pushed_ddns_config():
    """ddns INFORM section derives entries from pushed ddns config rules."""
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "ddns": {"rules": [
            {"id": 1, "domain": "site.example.com", "interface": 1, "status": 1},
            {"id": 2, "domain": "vpn.example.com", "interface": 2, "status": 0},
        ]},
    })
    ddnss = gw.manage_inform_extra()["ddns"]["ddnss"]
    assert len(ddnss) == 2
    # domain is wrapped in a list (the DDNS domain field is a list of strings)
    assert ddnss[0]["domain"] == ["site.example.com"]
    assert ddnss[0]["interface"] == 1
    assert ddnss[1]["status"] == 0


def test_gateway_qos_reflects_pushed_qos_classes():
    """qos INFORM section derives per-port throughputs from pushed classRules."""
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "qos": {"classRules": [
            {"id": 1, "class": 0},
            {"id": 2, "class": 3},
        ]},
    })
    data = gw.manage_inform_extra()["qos"]["data"]
    # ER605 WAN port 1 always reports; classes come from pushed config
    classes = [t["class"] for t in data[0]["throughputs"]]
    assert classes == [0, 3]


def test_gateway_portforward_reflects_pushed_config():
    """portforward INFORM section derives user forwards from pushed config."""
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "portforward": {"settings": [
            {"id": 1, "name": "web", "protocol": 6, "ipaddr": "10.0.2.10",
             "externalPort": "80", "internalPort": "8080", "interface": [1]},
        ]},
    })
    pf = gw.manage_inform_extra()["portforward"]
    assert len(pf["users"]) == 1
    assert pf["users"][0]["name"] == "web"
    assert pf["users"][0]["inip"] == "10.0.2.10"
    assert pf["users"][0]["export"] == "80"
    assert pf["users"][0]["inport"] == "8080"
    assert pf["users"][0]["infa"] == [1]
    # UPnP entries remain synthetic
    assert "upnps" in pf


def test_gateway_ips_threat_omitted_when_ips_disabled():
    """ipsThreat section is omitted entirely when pushed IPS config is disabled."""
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "ips": {"enable": False, "categoryIds": [1, 2]},
    })
    extra = gw.manage_inform_extra()
    assert "ipsThreat" not in extra


def test_gateway_ips_threat_reflects_pushed_category_ids():
    """ipsThreat section uses pushed categoryIds when IPS enabled."""
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "ips": {"enable": True, "categoryIds": [7, 9]},
    })
    threats = gw.manage_inform_extra()["ipsThreat"]["data"]
    assert {t["categoryId"] for t in threats} <= {7, 9}


# ---------------------------------------------------------------------------
# Phase 2: full SET ack coverage
# ---------------------------------------------------------------------------

def test_gateway_set_acks_all_pushed_feature_keys():
    """Every feature key present in a SET body is acked with {errcode: 0}."""
    gw = _make_gateway()
    req = {
        "sequenceId": 1, "configVersion": 5,
        "firewallConfig": {"enable": 1},
        "macFilter": {"enable": 1},
        "urlFiltering": {"enable": 1},
        "snmp": {"enable": 1},
        "iptv": {"enable": 1},
        "attackDefense": {"enable": 1},
        "oneToOneNat": {"enable": 1},
        "client": {"enable": 1},
    }
    resp = gw.build_set_response(req)
    for key in ("firewallConfig", "macFilter", "urlFiltering", "snmp",
                "iptv", "attackDefense", "oneToOneNat", "client"):
        assert resp[key] == {"errcode": 0}, f"{key} not acked"


def test_gateway_set_empty_body_keeps_base_ack():
    """An empty SET body (no feature keys) still returns the base ack — an
    empty {} body makes the controller forget the device."""
    gw = _make_gateway()
    resp = gw.build_set_response({"sequenceId": 1, "configVersion": 5})
    assert resp["errcode"] == 0
    assert resp["sequenceId"] == 1
    assert resp["configVersion"] == 5


# ---------------------------------------------------------------------------
# Phase 3: full GET response coverage
# ---------------------------------------------------------------------------

def test_gateway_get_echoes_dedicated_response_bodies():
    """GET response includes arptable, dnsCache, dpiProtocols, wanIpv6."""
    gw = _make_gateway()
    gw.build_set_response({"sequenceId": 1, "configVersion": 5,
                           "wanIpv6": {"enable": 1, "proto": "dhcp6"}})
    resp = gw.build_get_response({"sequenceId": 2})
    assert "arptable" in resp
    assert "arps" in resp["arptable"]
    assert "dnsCache" in resp
    assert "caches" in resp["dnsCache"]
    assert "dpiProtocols" in resp
    assert "protocols" in resp["dpiProtocols"]
    # WAN IPv6 config echoed when pushed
    assert resp["wanIpv6"]["proto"] == "dhcp6"


def test_gateway_get_echoes_full_config_key_map():
    """GET echoes all captured configs under the full GET key map."""
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "virtualWan": {"enable": 1},
        "macFilter": {"enable": 1},
        "ipMacBinding": {"enable": 1},
        "staticRouting": {"staticRoutings": []},
        "wanLoadBalance": {"enable": 1},
        "ssh": {"enable": 1},
    })
    resp = gw.build_get_response({"sequenceId": 2})
    assert resp["virtualWan"] == {"enable": 1}
    assert resp["macFilter"] == {"enable": 1}
    assert resp["ipMacBinding"] == {"enable": 1}
    assert resp["staticRouting"] == {"staticRoutings": []}
    assert resp["wanLoadBalance"] == {"enable": 1}
    assert resp["ssh"] == {"enable": 1}


# ---------------------------------------------------------------------------
# Phase 4: deviceInfo + negotiation completeness
# ---------------------------------------------------------------------------

def test_gateway_inform_device_info_has_full_fields():
    """INFORM deviceInfo carries the inform device info fields (sm, cerVer,
    ipv6List, fac, temp, txRate, rxRate) — these are INFORM-only and must NOT
    be in the negotiation deviceInfo."""
    gw = _make_gateway()
    inform_info = gw.manage_inform_body()["deviceInfo"]
    for f in ("sm", "cerVer", "ipv6List", "fac", "temp", "txRate", "rxRate"):
        assert f in inform_info, f"missing INFORM deviceInfo field {f}"
    # The negotiation deviceInfo must NOT carry the INFORM-only fields
    negot_info = gw.manage_device_info()
    for f in ("sm", "cerVer", "ipv6List", "temp", "txRate", "rxRate"):
        assert f not in negot_info, f"{f} leaked into negotiation deviceInfo"


def test_gateway_negotiation_device_info_has_identity_fields():
    """Negotiation deviceInfo carries encryptedHwId/hwId/oemId/speeds/mask/modelId."""
    gw = _make_gateway()
    info = gw.manage_device_info()
    for f in ("encryptedHwId", "hwId", "oemId", "speeds", "mask", "modelId"):
        assert f in info, f"missing negotiation identity field {f}"


def test_gateway_wan_port_has_full_ip4_entry():
    """WAN port (port 1) reports publicWanIp + ip4 gw2/priDns2/sndDns2."""
    gw = _make_gateway()
    ports = gw.manage_inform_extra()["portInfo"]["portInfos"]
    wan = [p for p in ports if p["port"] == 1][0]
    assert "publicWanIp" in wan
    assert "gw2" in wan["ip4"]
    assert "priDns2" in wan["ip4"]
    assert "sndDns2" in wan["ip4"]


# ---------------------------------------------------------------------------
# Phase 5: cfgResults history + vpn.wireguard sub-field
# ---------------------------------------------------------------------------

def test_gateway_cfg_results_accumulates_history():
    """cfgResults INFORM section accumulates recent SET responses."""
    gw = _make_gateway()
    gw.build_set_response({"sequenceId": 1, "configVersion": 5,
                           "firewallConfig": {"enable": 1}})
    gw.build_set_response({"sequenceId": 2, "configVersion": 6,
                           "snmp": {"enable": 1}})
    cfg = gw.manage_inform_extra()["cfgResults"]["setResults"]
    assert len(cfg) == 2
    assert cfg[0]["sequenceId"] == 1
    assert cfg[1]["sequenceId"] == 2


def test_gateway_cfg_results_history_capped():
    """cfgResults history is capped at 10 entries."""
    gw = _make_gateway()
    for i in range(12):
        gw.build_set_response({"sequenceId": i, "configVersion": i})
    cfg = gw.manage_inform_extra()["cfgResults"]["setResults"]
    assert len(cfg) == 10


def test_gateway_vpn_section_has_wireguard_subfield_from_client_wireguards():
    """vpn.wireguard sub-field populated from pushed client_Wireguards."""
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "vpn": {"client_Wireguards": [
            {"id": 1, "type": 1, "activeClients": 2, "totalClients": 5,
             "serverAddress": "10.9.1.1", "status": 1},
        ]},
    })
    vpn = gw.manage_inform_extra()["vpn"]
    assert "wireguard" in vpn
    assert len(vpn["wireguard"]) == 1
    assert vpn["wireguard"][0]["serverAddress"] == "10.9.1.1"
    assert vpn["wireguard"][0]["totalClients"] == 5

# -- Gateway wireless INFORM sections (WiFi-capable models) ------------

def _make_wireless_gateway():
    return build_device(
        {
            "name": "gw-wifi",
            "type": "gateway",
            "model": "ER706W",
            "mac": "AA-BB-CC-DD-EE-0W",
            "ip": "192.168.56.71",
            "wireless": 1,
        }
    )


def test_wired_gateway_has_no_wireless_sections():
    """A wired-only gateway (ER605, wireless=0) does not emit wireless sections."""
    gw = _make_gateway()
    extra = gw.manage_inform_extra()
    assert "wSettings_2G" not in extra
    assert "radioTraffic_5G" not in extra
    assert "mesh" not in extra


def test_wireless_gateway_emits_wireless_sections():
    """A WiFi-capable gateway (wireless>0) emits wSettings/radioTraffic/ssidStats."""
    gw = _make_wireless_gateway()
    extra = gw.manage_inform_extra()
    assert "wSettings_2G" in extra
    assert "wSettings_5G" in extra
    assert "radioTraffic_2G" in extra
    assert "radioTraffic_5G" in extra
    assert "ssidStats_2G" in extra
    assert "ssidStats_5G" in extra
    assert "mesh" in extra
    assert "roaming" in extra


def test_wireless_gateway_wsettings_shape():
    gw = _make_wireless_gateway()
    ws = gw.manage_inform_extra()["wSettings_5G"]
    assert "rid" in ws and "ch" in ws and "bw" in ws
    assert "txPower" in ws and "rdMode" in ws


def test_wireless_gateway_radio_traffic_shape():
    gw = _make_wireless_gateway()
    rt = gw.manage_inform_extra()["radioTraffic_5G"]
    for f in ("rid", "rx", "tx", "rxRate", "txRate", "clientNum"):
        assert f in rt


def test_wireless_gateway_ssid_stats_shape():
    gw = _make_wireless_gateway()
    ss = gw.manage_inform_extra()["ssidStats_5G"]
    assert isinstance(ss, list) and len(ss) >= 1
    entry = ss[0]
    for f in ("ssid", "bssid", "rx", "tx", "clientNum"):
        assert f in entry


def test_wireless_gateway_mesh_inactive():
    gw = _make_wireless_gateway()
    mesh = gw.manage_inform_extra()["mesh"]
    assert mesh["status"] == 0


# -- Gateway VoIP sections ---------------------------------------------

def test_wired_gateway_has_no_voip_section():
    """A gateway with no pushed VoIP config does not emit callLogInform."""
    gw = _make_gateway()
    extra = gw.manage_inform_extra()
    assert "callLogInform" not in extra


def test_gateway_voip_section_after_config_push():
    """When voipDeviceOsgSetting is pushed, callLogInform is emitted."""
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 1,
        "voipDeviceOsgSetting": {
            "portSettings": [
                {"port": 1, "numberForOutgoingCalls": "5551000"},
                {"port": 2, "numberForOutgoingCalls": "5552000"},
            ],
        },
    })
    extra = gw.manage_inform_extra()
    assert "callLogInform" in extra
    logs = extra["callLogInform"]["logs"]
    assert isinstance(logs, list)
    if logs:
        log = logs[0]
        for f in ("port", "callType", "phoneNumber", "duration", "timestamp"):
            assert f in log


def test_gateway_voip_set_keys_captured_for_get_echo():
    """VoIP SET keys are captured and echoed on GET."""
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 1,
        "callForwarding": {"ruleList": [{"id": 1}]},
    })
    resp = gw.build_get_response({"sequenceId": 1})
    assert "callForwarding" in resp
    assert resp["callForwarding"]["ruleList"][0]["id"] == 1
