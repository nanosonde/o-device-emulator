"""Unit tests for the wired-topology reporting (LLDP/port/FDB/lanInfo that
drive the controller's topology map)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.devices import build_device
from device_emulator.devices.topology import LinkNeighbor, TopologyNeighbors
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
    assert set(extra) == {"port", "lldp", "fdb"}
    # Both the uplink (gateway) and downlink (AP) are present as LLDP neighbours.
    neigh_macs = {n["chassisId"] for p in extra["lldp"]["lldps"] for n in p["neighbors"]}
    assert neigh_macs == {"AA-BB-CC-DD-EE-03", "AA-BB-CC-DD-EE-01"}
    fdb_macs = {m["mac"] for e in extra["fdb"]["fdbs"] for m in e["macs"]}
    assert fdb_macs == {"AA-BB-CC-DD-EE-03", "AA-BB-CC-DD-EE-01"}


def test_gateway_reports_portinfo_and_lldp_only():
    gw, _, _ = _runner_with_chain().devices
    extra = gw.manage_inform_extra()
    assert set(extra) == {"portInfo", "lldp"}


def test_ap_reports_lan_info():
    _, _, ap = _runner_with_chain().devices
    extra = ap.manage_inform_extra()
    assert extra["lanInfo"]["port"] == "1"


def test_device_without_topology_reports_nothing_extra():
    device = build_device({"name": "ap", "type": "ap", "model": "EAP245",
                           "mac": "AA-BB-CC-DD-EE-09", "ip": "1.1.1.9"})
    assert device.manage_inform_extra() == {}
