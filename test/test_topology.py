"""Unit tests for the wired-topology reporting (LLDP/port/FDB/lanInfo that
drive the controller's topology map)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.devices import build_device
from device_emulator.services.runner import Runner


def _runner_with_chain() -> Runner:
    runner = Runner(controller_host="x")
    runner.add_device(build_device(
        {"name": "gw", "type": "gateway", "model": "ER605", "mac": "AA-BB-CC-DD-EE-03", "ip": "1.1.1.3"}
    ))
    runner.add_device(build_device(
        {"name": "sw", "type": "switch", "model": "TL-SG3210", "mac": "AA-BB-CC-DD-EE-02",
         "ip": "1.1.1.2", "uplink": "gw", "uplink_port": 5}
    ))
    runner.add_device(build_device(
        {"name": "ap", "type": "ap", "model": "EAP245", "mac": "AA-BB-CC-DD-EE-01",
         "ip": "1.1.1.1", "uplink": "sw", "uplink_port": 8}
    ))
    runner._resolve_topology()
    return runner


def test_resolve_topology_builds_bidirectional_links():
    gw, sw, ap = _runner_with_chain().devices
    # AP uplinks to the switch on the switch's port 8; switch uplinks to gateway
    # on the gateway's port 5.
    assert ap.topology.uplink and ap.topology.uplink.mac == sw.mac
    assert ap.topology.uplink.remote_port == 8
    assert sw.topology.uplink and sw.topology.uplink.mac == gw.mac
    assert sw.topology.uplink.remote_port == 5
    # Parents see their children as downlinks.
    assert [d.mac for d in sw.topology.downlinks] == [ap.mac]
    assert [d.mac for d in gw.topology.downlinks] == [sw.mac]
    assert not gw.topology.uplink  # gateway is the root


def test_olt_uplink_is_resolved_and_reported_over_lldp():
    runner = Runner(controller_host="x")
    runner.add_device(build_device(
        {"name": "sw", "type": "switch", "model": "TL-SG3210",
         "mac": "AA-BB-CC-DD-EE-02", "ip": "1.1.1.2"}
    ))
    runner.add_device(build_device(
        {"name": "olt", "type": "olt", "model": "DS-P7001-08",
         "mac": "AA-BB-CC-DD-EE-04", "ip": "1.1.1.4", "uplink": "sw",
         "uplink_port": 9}
    ))

    runner._resolve_topology()
    sw, olt = runner.devices

    assert olt.topology.uplink and olt.topology.uplink.mac == sw.mac
    assert olt.topology.uplink.local_port == 1
    assert olt.topology.uplink.remote_port == 9
    assert [(link.mac, link.local_port, link.remote_port) for link in sw.topology.downlinks] == [
        (olt.mac, 9, 1)
    ]
    lldp_neighbors = olt.manage_inform_body()["lldp"]["lldps"]
    assert lldp_neighbors[0]["portId"] == 1
    assert lldp_neighbors[0]["neighbors"][0]["chassisId"] == sw.mac


def test_unknown_uplink_is_ignored():
    runner = Runner(controller_host="x")
    runner.add_device(build_device(
        {"name": "ap", "type": "ap", "model": "EAP245", "mac": "AA-BB-CC-DD-EE-01",
         "ip": "1.1.1.1", "uplink": "does-not-exist"}
    ))
    runner._resolve_topology()  # must not raise
    assert runner.devices[0].topology.uplink is None


def test_switch_reports_port_lldp_and_fdb():
    _, sw, _ = _runner_with_chain().devices
    extra = sw.manage_inform_extra()
    # Structural topology sections plus the (empty, until clients are
    # synthesised) client list, the PoE budget, and the Layer-3 routing table
    # and loopback status (the TL-SG3210 v3 supports static routing).
    assert set(extra) == {"port", "lldp", "fdb", "client", "poe",
                          "routingTable", "loopback", "lag", "ddm",
                          "stpInform"}
    # Both the uplink (gateway) and downlink (AP) are present as LLDP neighbours.
    neigh_macs = {n["chassisId"] for p in extra["lldp"]["lldps"] for n in p["neighbors"]}
    assert neigh_macs == {"AA-BB-CC-DD-EE-03", "AA-BB-CC-DD-EE-01"}
    # The LLDP Neighbor Table view keys its rows on standardPort per port.
    assert all("standardPort" in p for p in extra["lldp"]["lldps"])
    fdb_macs = {m["mac"] for e in extra["fdb"]["fdbs"] for m in e["macs"]}
    assert fdb_macs == {"AA-BB-CC-DD-EE-03", "AA-BB-CC-DD-EE-01"}
    # Linked ports carry byte/packet counters for the Ports TX/RX SUM columns.
    assert all({"tx", "rx", "txP", "rxP"} <= set(p) for p in extra["port"]["ports"])


def test_gateway_reports_portinfo_and_lldp_only():
    gw, _, _ = _runner_with_chain().devices
    extra = gw.manage_inform_extra()
    # The gateway's INFORM extra carries the per-port status (portInfo), the
    # LLDP neighbour table (lldp), a small routing table (routingTable), and the
    # LAN client / DHCP-lease / traffic / ARP telemetry, plus the VPN/firewall/
    # NAT/QoS/DDNS/IPS runtime sections and the additional telemetry sections
    # (clientTraffic, abnormalDt, eventInform, aclHit, portalDuration,
    # applicationsTraffic, monitor, lastCfgResult, cfgResults).
    expected = {"portInfo", "lldp", "routingTable",
                "client", "dhcpClient", "trafficStat", "arp",
                "vpn", "sslVpn", "wireguard", "ddns", "qos",
                "ctTable", "portforward", "networkTraffic",
                "ipsThreat", "clientTraffic", "abnormalDt",
                "eventInform", "aclHit", "portalDuration",
                "applicationsTraffic", "monitor", "cfgResults"}
    # lastCfgResult is only present if a SET has been pushed.
    if "lastCfgResult" in extra:
        expected.add("lastCfgResult")
    assert set(extra) == expected, f"unexpected keys: {set(extra) - expected}"
    # portInfo uses the controller's gateway port status shape under "portInfos".
    port_infos = extra["portInfo"]["portInfos"]
    assert {p["port"] for p in port_infos} == {1, 2, 3, 4, 5}
    # The WAN port (port 1) reports its IPv4 lease so the Ports -> WAN tab
    # populates (MAC/IP flat; Gateway/DNS nested in "ip4" per the gateway port IPv4 entry).
    wan = next(p for p in port_infos if p["port"] == 1)
    assert wan["internetState"] == 1
    assert wan["ip"]
    assert wan["ip4"]["gw"]
    assert wan["ip4"]["priDns"]
    # The downlink to the switch (gateway port 5) reports link-up.
    assert next(p for p in port_infos if p["port"] == 5)["status"] == 1
    # routingTable matches the gateway inform routing -> routingTables -> routing table entry.
    rt = extra["routingTable"]["routingTables"]
    assert rt and {"id", "destIp", "nextHop", "interfaceName", "metric"} <= set(rt[0])


def test_ap_reports_lan_info():
    _, _, ap = _runner_with_chain().devices
    extra = ap.manage_inform_extra()
    assert extra["lanInfo"]["port"] == "1"


def test_device_without_topology_reports_nothing_extra():
    device = build_device({"name": "ap", "type": "ap", "model": "EAP245",
                           "mac": "AA-BB-CC-DD-EE-09", "ip": "1.1.1.9"})
    extra = device.manage_inform_extra()
    # Without a resolved uplink there is no lanInfo, and without synthesised
    # clients the client list is empty - but the AP always reports its per-radio
    # settings so the Statistics/radio view is populated.
    assert "lanInfo" not in extra
    assert extra["clients"] == []
    assert "wSettings_2G" in extra and "wSettings_5G" in extra


def test_synthesized_clients_are_reported():
    from device_emulator.devices.clients import synthesize_site_clients

    gw, sw, ap = _runner_with_chain().devices
    synthesize_site_clients([gw, sw, ap])
    # AP reports five wireless clients (default wireless_client_count); switch
    # one wired; gateway aggregates all.
    assert len(ap.manage_inform_extra()["clients"]) == 5
    assert len(sw.manage_inform_extra()["client"]["clients"]) == 1
    assert len(gw.manage_inform_extra()["client"]["clients"]) == 6
    assert len(gw.manage_inform_extra()["dhcpClient"]["clients"]) == 6


def test_switch_reports_l3_routing_table():
    """The TL-SG3210 v3 is a Layer-3 switch: its INFORM carries a routingTable
    section (the switch inform routing -> routingTables -> routing table entry with destIp/
    nextHop/distance) so the Tools -> Routing Table view populates."""
    _, sw, _ = _runner_with_chain().devices
    extra = sw.manage_inform_extra()
    rt = extra["routingTable"]["routingTables"]
    assert rt
    # Each entry matches the switch routing table shape.
    assert {"destIp", "nextHop", "distance"} <= set(rt[0])
    # The directly-connected management network is present as an on-link route.
    assert any(r["distance"] == 0 and r["nextHop"] == "0.0.0.0" for r in rt)
    # A default route via the upstream gateway is present (the switch uplinks
    # to the gateway, which is the site's default router).
    assert any(r["destIp"] == "0.0.0.0/0" for r in rt)


def test_switch_static_routing_set_and_get_roundtrip():
    """The switch acks a staticRouting SET_REQUEST and echoes the applied
    config back on GET (the switch static routing config -> staticRoutings list of
    routing entries with id/destIp/nextHop/distance). The pushed routes
    also surface in the INFORM routing table."""
    _, sw, _ = _runner_with_chain().devices
    pushed = {
        "staticRoutings": [
            {"id": 1, "operation": 1, "destIp": ["192.168.50.0/24"],
             "nextHop": "10.0.2.254", "distance": 1},
        ],
    }
    set_resp = sw.build_set_response({"sequenceId": 7, "configVersion": "3",
                                     "staticRouting": pushed})
    assert set_resp["errcode"] == 0
    assert set_resp["sequenceId"] == 7
    # GET echoes the applied static routing config.
    get_resp = sw.build_get_response({"sequenceId": 8})
    assert get_resp["staticRouting"] == pushed
    # The pushed static route appears in the INFORM routing table.
    rt = sw.manage_inform_extra()["routingTable"]["routingTables"]
    assert any(r["destIp"] == "192.168.50.0/24" and r["nextHop"] == "10.0.2.254"
               for r in rt)


def test_switch_loopback_interface_set_and_inform():
    """The switch acks a loopbackInterface SET and reports the loopback status
    in its INFORM (the switch loopback status -> enable) so the L3 interface view
    reflects the configured state."""
    _, sw, _ = _runner_with_chain().devices
    sw.build_set_response({"sequenceId": 1, "configVersion": "1",
                          "loopbackInterface": {"enable": 1}})
    extra = sw.manage_inform_extra()
    assert extra["loopback"]["enable"] == 1
