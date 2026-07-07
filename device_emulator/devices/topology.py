"""Wired topology reporting.

The controller draws its topology map (gateway -> switch -> access point) from
data the devices report in their periodic INFORM: a switch/gateway reports its
per-port link status, LLDP neighbour table and (switch) MAC forwarding table;
an access point reports its wired uplink port. The controller correlates the
LLDP/FDB adjacency into a successor tree.

This module models the per-device neighbour set (an optional uplink plus any
downlinks) and builds those INFORM sections from it. The runner populates each
device's ``TopologyNeighbors`` from the ``uplink`` relationships declared in the
YAML config (see services/runner.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LinkNeighbor:
    """One end of a wired link, as seen from a device."""

    mac: str
    model: str
    device_type: str  # "ap" / "switch" / "gateway"
    local_port: int   # port on THIS device facing the neighbour
    remote_port: int  # port on the NEIGHBOUR facing this device


@dataclass
class TopologyNeighbors:
    """A device's wired neighbours: its uplink (upstream) and downlinks."""

    uplink: Optional[LinkNeighbor] = None
    downlinks: list[LinkNeighbor] = field(default_factory=list)

    def all_links(self) -> list[LinkNeighbor]:
        return ([self.uplink] if self.uplink else []) + list(self.downlinks)


def _lldp_neighbor(link: LinkNeighbor) -> dict[str, Any]:
    return {
        "chassisIdSubtype": 4,  # MAC address
        "chassisId": link.mac,
        "portIdSubtype": 3,
        "portId": str(link.remote_port),
        "name": link.model,
        "description": link.model,
        "capabilities": "",
        "ttl": 120,
    }


def lldp_section(links: list[LinkNeighbor]) -> dict[str, Any]:
    """The ``lldp`` INFORM section (switch and gateway) - one neighbour per
    port. The controller matches each neighbour's chassisId (a MAC) to a device
    node to build an edge."""
    return {
        "lldp": {
            "lldps": [
                {
                    "portId": link.local_port,
                    "standardOswPort": str(link.local_port),
                    "neighbors": [_lldp_neighbor(link)],
                }
                for link in links
            ]
        }
    }


def switch_port_section(links: list[LinkNeighbor]) -> dict[str, Any]:
    """The switch ``port`` INFORM section - the connecting ports reported up."""
    return {
        "port": {
            "ports": [
                {
                    "port": link.local_port,
                    "standardPort": str(link.local_port),
                    "status": 1,
                    "speed": 1000,
                    "duplex": 1,
                    "stpState": 1,
                    "mode": 0,
                }
                for link in links
            ]
        }
    }


def switch_fdb_section(links: list[LinkNeighbor]) -> dict[str, Any]:
    """The switch ``fdb`` INFORM section - each neighbour's MAC seen on its
    port. Wired access points are placed under the switch from this table."""
    return {
        "fdb": {
            "fdbs": [
                {
                    "port": link.local_port,
                    "standardPort": str(link.local_port),
                    "macs": [{"mac": link.mac}],
                    "totCnt": 1,
                }
                for link in links
            ]
        }
    }


def gateway_port_section(links: list[LinkNeighbor], device_mac: str) -> dict[str, Any]:
    """The gateway ``portInfo`` INFORM section - the connecting ports up."""
    return {
        "portInfo": {
            "portStatusList": [
                {
                    "port": link.local_port,
                    "physicalType": 2,
                    "name": f"P{link.local_port}",
                    "mode": 1,
                    "mac": device_mac,
                    "status": 1,
                    "speed": 1000,
                }
                for link in links
            ]
        }
    }


def ap_lan_info_section(uplink: LinkNeighbor) -> dict[str, Any]:
    """The access point ``lanInfo`` INFORM section - its wired uplink port.
    The controller pairs this with the switch's LLDP/FDB to place the AP."""
    return {"lanInfo": {"rate": "1000", "duplex": 1, "port": str(uplink.local_port)}}
