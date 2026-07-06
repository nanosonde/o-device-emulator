"""Emulated managed switch."""
from __future__ import annotations

import ipaddress
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .. import stats
from ..protocol import constants
from ..protocol.discovery import build_switch_discovery_body
from . import switch_profile, topology
from .wired import WiredDevice


def _ip_network_cidr(ip: str, prefix: int) -> str:
    """The ``ip/prefix`` CIDR for the network containing ``ip`` (used for the
    switch's directly-connected route). Falls back to ``ip/prefix`` if the IP
    is not parseable."""
    try:
        net = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
        return str(net)
    except ValueError:
        return f"{ip}/{prefix}"


def _subnet_first_host(ip: str, prefix: int) -> str:
    """The first usable host address in the subnet containing ``ip`` (used as a
    stable default next-hop for the upstream gateway). Falls back to the
    gateway's common ``.1`` form."""
    try:
        net = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
        hosts = list(net.hosts())
        return str(hosts[0]) if hosts else str(net.network_address + 1)
    except ValueError:
        parts = ip.rsplit(".", 1)
        return f"{parts[0]}.1" if len(parts) == 2 else "10.0.2.1"


@dataclass
class SwitchDevice(WiredDevice):
    port_num: int = 8
    stack_id: str = ""
    # Whether this switch model delivers PoE (drives the poe INFORM section).
    supports_poe: bool = False

    profile = switch_profile
    # Switches echo the controller id back as destOmadacId in the negotiation.
    include_dest_omadac_id = True

    def __post_init__(self) -> None:
        self.device_type = constants.DEVICE_TYPE_SWITCH
        self._apply_wired_profile()
        # L3 / static-routing state captured from the controller's SET_REQUEST
        # config pushes so a later GET can echo the applied values and the
        # Routing tab reflects operator-configured routes. The TL-SG3210 v3
        # supports Layer 3 / static routing (see the model spec), and the
        # switch profile advertises the `staticRouting`/`routingTable`/
        # `loopback`/`vlanIf`/`network`/`ipGroup` components for it.
        self._applied_static_routing: dict[str, Any] = {}
        self._applied_loopback_interface: dict[str, Any] = {}
        self._applied_vlan_if: dict[str, Any] = {}
        # LAG / STP config captured from SET pushes so GET can echo them.
        self._applied_lag: dict[str, Any] = {}
        self._applied_stp: dict[str, Any] = {}
        self._applied_port_stp: dict[str, Any] = {}
        # Report a small non-zero CPU utilisation: the controller's health
        # scorer treats a 0% CPU sample as "no data" and leaves the switch's
        # health score at -1 (No Data).
        if not self.cpu_util:
            self.cpu_util = stats.synthetic_percent(self.mac, "swcpu", 2, 12)

    def manage_inform_extra(self) -> dict[str, Any]:
        # Report port link status + per-port traffic, the LLDP neighbour table,
        # the MAC forwarding table, learned wired clients, PoE and the Layer-3
        # routing table, so the controller can place this switch in the topology
        # map and populate its Ports / Clients / PoE / Tools (Routing Table,
        # LLDP Neighbor Table) views.
        links = self.topology.all_links()
        extra: dict[str, Any] = {}
        if links:
            extra.update(self._port_section(links))
            extra.update(topology.switch_lldp_section(links))
            extra.update(topology.switch_fdb_section(links))
        extra.update(self._client_section())
        extra.update(self._poe_section())
        extra.update(self._routing_table_section())
        extra.update(self._loopback_section())
        # LAG / SFP-DDM / per-port STP runtime so the switch detail Pages
        # (LAG groups, SFP DDM) and Tools (STP status) populate.
        extra.update(self._lag_section())
        extra.update(self._ddm_section())
        extra.update(self._stp_inform_section())
        return extra

    def _port_section(self, links: list[topology.LinkNeighbor]) -> dict[str, Any]:
        """The switch ``port`` section (link status + per-port byte/packet
        counters) so the Ports tab shows TX SUM / RX SUM instead of ``--``."""
        section = topology.switch_port_section(links)
        up = self.uptime_seconds
        for entry in section["port"]["ports"]:
            port = entry["port"]
            salt = f"port{port}"
            rx = stats.synthetic_bytes(self.mac, salt + "rx", up,
                                       stats.synthetic_rate_bps(self.mac, salt + "rr", 5, 200))
            tx = stats.synthetic_bytes(self.mac, salt + "tx", up,
                                       stats.synthetic_rate_bps(self.mac, salt + "tr", 5, 200))
            entry.update({
                "rx": rx,
                "tx": tx,
                "rxP": stats.synthetic_packets(rx),
                "txP": stats.synthetic_packets(tx),
            })
        return section

    def _client_section(self) -> dict[str, Any]:
        """The ``client`` section (switch client list) listing the switch's
        learned wired clients so they appear in the Clients page and the
        device's client tables."""
        clients = []
        up = self.uptime_seconds
        for client in self.reported_clients:
            rx, tx = client.traffic(up)
            clients.append({
                "type": 0,
                "mac": client.mac,
                "name": client.name,
                "vendor": client.vendor,
                "ip": client.ip,
                "vid": client.vlan,
                "port": client.host_port,
                "standardPort": f"1/0/{client.host_port}",
                "time": client.assoc_seconds,
                "rx": rx,
                "tx": tx,
                "rxP": stats.synthetic_packets(rx),
                "txP": stats.synthetic_packets(tx),
                "rxT": client.down_bps,
                "txT": client.up_bps,
            })
        return {"client": {"clients": clients}}

    def _poe_section(self) -> dict[str, Any]:
        """The ``poe`` section (PoE status). Non-PoE models report a zero
        budget; PoE models would report per-port draw here."""
        if not self.supports_poe:
            return {"poe": {"total": 0.0, "remain": 0.0, "percent": 0, "ports": []}}
        ports = []
        linked = {ln.local_port for ln in self.topology.all_links()}
        for port in sorted(linked):
            watts = stats.synthetic_int(self.mac, f"poe{port}", 20, 150) / 10.0
            ports.append({
                "standardPort": f"1/0/{port}",
                "id": port,
                "state": 1,
                "p": watts,
                "pdClass": 3,
            })
        total = round(sum(p["p"] for p in ports), 1)
        return {"poe": {"total": total, "remain": round(max(0.0, 150.0 - total), 1),
                        "percent": int(total / 150.0 * 100), "ports": ports}}

    def _routing_table_section(self) -> dict[str, Any]:
        """The ``routingTable`` INFORM section (routing tables list) so the
        Tools -> Routing Table view populates. The TL-SG3210 v3 is a Layer-3
        switch and reports its active routing table here; each entry carries
        ``destIp`` (a CIDR string), ``nextHop``, ``distance`` and optionally
        ``nextHops`` (a list of ECMP next-hops). The route set is the device's
        own interface network plus any operator-configured static routes
        (captured from the controller's ``staticRouting`` SET push)."""
        routes: list[dict[str, Any]] = []
        # The directly-connected network for the switch's management VLAN.
        net = self._l3_network_cidr()
        if net:
            routes.append({
                "destIp": net,
                "nextHop": "0.0.0.0",
                "distance": 0,
            })
        # A default route via the upstream gateway if this switch has one
        # (the gateway is the site's default router).
        uplink = self.topology.uplink
        if uplink and uplink.device_type == "gateway":
            routes.append({
                "destIp": "0.0.0.0/0",
                "nextHop": self._uplink_gateway_ip(),
                "distance": 1,
            })
        # Operator-configured static routes (echoed from the last
        # `staticRouting` SET_REQUEST). The controller's static routing entry
        # uses `id`/`destIp` (list of CIDR)/`nextHop`/`distance`; the inform
        # routing table flattens a single destination to a string.
        for entry in self._static_route_entries():
            dests = entry.get("destIp") or []
            dest = dests[0] if isinstance(dests, list) and dests else dests
            routes.append({
                "destIp": dest,
                "nextHop": entry.get("nextHop", "0.0.0.0"),
                "distance": entry.get("distance", 1),
            })
        return {"routingTable": {"routingTables": routes}}

    def _lag_section(self) -> dict[str, Any]:
        """The ``lag`` section (LAG groups): LAG groups with member ports.
        The TL-SG3210 supports up to 8 LAG groups of 8 members each
        (``devCap.lagNum``/``lagMember``). Each LAG entry carries ``lag``
        (group id) + ``stMembers`` (set of member port strings). The controller
        also expects a ``duplex`` field (not in the section but read without
        null check in the controller's inform decoder)."""
        links = self.topology.all_links()
        if len(links) < 2:
            return {"lag": {"lags": [], "rates": []}}
        # Group linked ports into LAG groups of 2.
        lags = []
        ports = sorted(ln.local_port for ln in links)
        for i in range(0, len(ports) - 1, 2):
            gid = i // 2 + 1
            members = [f"1/0/{ports[i]}", f"1/0/{ports[i + 1]}"]
            lags.append({"lag": gid, "stMembers": members, "duplex": 1, "status": 1})
        rates = [{
            "lag": lg["lag"],
        } for lg in lags]
        return {"lag": {"lags": lags, "rates": rates}}

    def _ddm_section(self) -> dict[str, Any]:
        """The ``ddm`` section (SFP DDM): SFP digital-diagnostic
        monitoring. The TL-SG3210 has 2 SFP ports (``devCap.sfpBeginNum=9``,
        ``sfpNum=2``). Each SFP port reports nested measurement objects for
        temperature (``tem``), voltage (``vol``), bias current (``bc``),
        tx-power (``tx``), and rx-power (``rx``), each with a raw value
        (``*0``), high/low alarm/warn thresholds (``*Ha``/``*Hw``/``*La``/
        ``*Lw``), and status (``*St``). Plus flat ``port``, ``standardPort``,
        ``rxLos``, ``txFault``, ``base``, ``ddmData``, ``qsfp``, ``rd``."""
        sfp_begin = self.profile.DEV_CAP.get("sfpBeginNum", 9)
        sfp_num = self.profile.DEV_CAP.get("sfpNum", 0)
        if sfp_num <= 0:
            return {"ddm": {"ports": []}}
        ports = []
        for i in range(sfp_num):
            port = sfp_begin + i
            ports.append({
                "port": port,
                "standardPort": f"1/0/{port}",
                "ddmData": 1,
                "qsfp": 0,
                "rd": 0,
                "rxLos": 0,
                "txFault": 0,
                "base": 0,
                "tem": {
                    "tem0": float(stats.synthetic_int(self.mac, f"tem0{port}", 25, 45)),
                    "temHa": 80.0, "temHw": 70.0, "temLa": 0.0, "temLw": 10.0,
                    "temSt": 1,
                },
                "vol": {
                    "vol0": float(stats.synthetic_int(self.mac, f"vol0{port}", 3200, 3600)),
                    "volHa": 3700.0, "volHw": 3650.0, "volLa": 3000.0, "volLw": 3100.0,
                    "volSt": 1,
                },
                "bc": {
                    "bc0": float(stats.synthetic_int(self.mac, f"bc0{port}", 5, 40)),
                    "bcHa": 80.0, "bcHw": 70.0, "bcLa": 0.0, "bcLw": 3.0,
                    "bcSt": 1,
                },
                "tx": {
                    "tx0": float(stats.synthetic_int(self.mac, f"tx0{port}", 1, 5)),
                    "txHa": 10.0, "txHw": 8.0, "txLa": -10.0, "txLw": -8.0,
                    "txSt": 1,
                },
                "rx": {
                    "rx0": float(stats.synthetic_int(self.mac, f"rx0{port}", 1, 5)),
                    "rxHa": 10.0, "rxHw": 8.0, "rxLa": -10.0, "rxLw": -8.0,
                    "rxSt": 1,
                },
            })
        return {"ddm": {"ports": ports}}

    def _stp_inform_section(self) -> dict[str, Any]:
        """The ``stpInform`` section (STP info -> ``ports`` list of per-port
        STP state): per-port runtime STP state. Each port entry
        carries ``port``, ``standardPort``, ``stpState`` and ``stpVlan``.
        ``stpState``: 0=disabled, 1=forwarding, 2=learning, 3=listening,
        4=blocking, 5=discarding."""
        links = self.topology.all_links()
        ports = [{
            "port": link.local_port,
            "standardPort": f"1/0/{link.local_port}",
            "stpState": 1,  # forwarding
            "stpVlan": 1,
        } for link in links]
        return {"stpInform": {"ports": ports}}

    def _loopback_section(self) -> dict[str, Any]:
        """The ``loopback`` INFORM section (loopback status) reporting
        whether the Layer-3 loopback interface is enabled. The switch's
        `loopback` component (loopback config) carries `enable`/`type`;
        the inform mirrors the configured state so the controller's L3
        interface view reflects it."""
        enabled = bool(self._applied_loopback_interface.get("enable", 0))
        return {"loopback": {"enable": 1 if enabled else 0, "type": 0}}

    def _static_route_entries(self) -> list[dict[str, Any]]:
        """The operator-configured static routes, as static routing entry
        dicts (``id``/``operation``/``destIp``/``nextHop``/``distance``).
        Populated from the last ``staticRouting`` SET push; empty until the
        controller pushes one."""
        cfg = self._applied_static_routing or {}
        routes = cfg.get("staticRoutings") or []
        return [r for r in routes if isinstance(r, dict)]

    def _l3_network_cidr(self) -> str:
        """The directly-connected network CIDR for the switch's management IP
        (the on-link route a Layer-3 switch installs for its interface)."""
        return _ip_network_cidr(self.ip, 24)

    def _uplink_gateway_ip(self) -> str:
        """The next-hop IP for the upstream gateway. The gateway sits on the
        same management subnet; use the subnet's first usable address as a
        stable default (the emulator does not know the gateway's real IP from
        the switch's viewpoint, but the routing table only needs a plausible
        next-hop to render)."""
        return _subnet_first_host(self.ip, 24)

    def build_set_response(self, req_body: dict[str, Any]) -> dict[str, Any]:
        """Acknowledge a SET and remember the controller-pushed Layer-3 config
        (``staticRouting`` / ``loopbackInterface`` / ``vlanIf``) so a later GET
        can echo the applied values and the INFORM routing table reflects the
        operator-configured routes. Matches the switch config body keys
        (STATIC_ROUTING -> ``staticRouting``,
        LOOPBACK_INTERFACE -> ``loopbackInterface``)."""
        resp = super().build_set_response(req_body)
        sr = req_body.get("staticRouting")
        if isinstance(sr, dict):
            self._applied_static_routing = deepcopy(sr)
        lb = req_body.get("loopbackInterface")
        if isinstance(lb, dict):
            self._applied_loopback_interface = deepcopy(lb)
        vif = req_body.get("vlanIf")
        if isinstance(vif, dict):
            self._applied_vlan_if = deepcopy(vif)
        lag = req_body.get("lag")
        if isinstance(lag, dict):
            self._applied_lag = deepcopy(lag)
        stp = req_body.get("stp")
        if isinstance(stp, dict):
            self._applied_stp = deepcopy(stp)
        port_stp = req_body.get("portStp")
        if isinstance(port_stp, dict):
            self._applied_port_stp = deepcopy(port_stp)
        return resp

    def build_get_response(self, req_body: dict[str, Any]) -> dict[str, Any]:
        """Respond to a GET with the applied Layer-3 config so the controller's
        Routing / Interface config tabs populate. The switch GET response body
        only declares ``cliConfig``/``stack`` top-level fields, but the
        controller's config-tab GET requests use feature-specific keys and
        merge the response body verbatim, so echoing the applied config under
        its config body key (e.g. ``staticRouting``) makes the tab show
        the configured values."""
        resp = super().build_get_response(req_body)
        if self._applied_static_routing:
            resp["staticRouting"] = deepcopy(self._applied_static_routing)
        if self._applied_loopback_interface:
            resp["loopbackInterface"] = deepcopy(self._applied_loopback_interface)
        if self._applied_vlan_if:
            resp["vlanIf"] = deepcopy(self._applied_vlan_if)
        if self._applied_lag:
            resp["lag"] = deepcopy(self._applied_lag)
        if self._applied_stp:
            resp["stp"] = deepcopy(self._applied_stp)
        if self._applied_port_stp:
            resp["portStp"] = deepcopy(self._applied_port_stp)
        return resp

    def build_discovery_body(self) -> dict[str, Any]:
        assert self.controller_id is not None
        return build_switch_discovery_body(
            ip=self.ip,
            model=self.identity.model,
            model_version=self.identity.model_version,
            firmware_version=self.identity.firmware_version,
            hardware_version=self.identity.hardware_version,
            controller_id=self.controller_id,
            up_time_seconds=self.uptime_seconds,
            port_num=self.port_num,
            stack_id=self.stack_id,
        )
