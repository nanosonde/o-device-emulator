"""Emulated OLT (PON optical line terminal).

An OLT is the headend of a GPON/EPON passive optical network. On the wire it
is device type ``"olt"`` (see doc/DEVICE_PROTOCOL.md §4.4) and uses the V2
ECSP message branch. Unlike switches/gateways (which use the short-name
``deviceInfo`` field set), the OLT reuses the AP-style long-name field set
(``modelVersion``/``firmwareVersion``/``hardwareVersion``/``upTime``) plus
PON-specific identity fields (``hwId``/``oemId``/``lagCount``/``ponPortCount``/
``wirelessLinked``), matching the OLT adopt device-info shape.

The INFORM body mirrors the OLT inform shape: a ``deviceInfo`` block
carrying ONU counts plus CPU/mem utilisation, a ``trafficStat`` block with
per-PON-port counters, and the ``trafficTimeStamp``/``oltNeedReply`` flags.
See doc/DEVICE_PROTOCOL.md §4.4 / §7.9 for the full protocol reference.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .. import stats
from ..protocol import constants
from ..protocol.discovery import build_olt_discovery_body
from . import olt_detail_ops, olt_profile, topology
from .wired import WiredDevice


@dataclass
class OltDevice(WiredDevice):
    # Number of PON ports on the OLT (each serves a tree of ONUs).
    pon_port_count: int = 8
    # Number of link aggregation groups the OLT supports.
    lag_count: int = 0
    # OLT device identity (part of the negotiation device-info).
    oem_id: str = "EBBE93F5D7E4DE41DD95F8C510575D7D"
    hw_id: str = "93198DDF77EAF24F93AFD110A07C48AB"
    # Whether a wireless uplink is in use (OLTs are wired; stay False).
    wireless_linked: bool = False

    profile = olt_profile

    # The OLT config-push surface is minimal: exactly two SET keys --
    # ``controllerInfo`` (the controller's own address pushed to the device)
    # and ``highAbility`` (host-ability / cluster mode) -- plus the
    # ``upgrade`` push. There is no dedicated GET-key enum; the OLT GET
    # response uses the generic response shape. The PON/ONU/QoS/L3/IGMP/
    # security/firmware/user subsystems the controller's OLT detail page
    # exposes are URI-based ECSP RPCs (request body with ``uri`` and
    # ``params``); the emulator dispatches these via
    # :mod:`device_emulator.devices.olt_detail_ops`, which returns synthetic
    # payloads matching the controller's OLT management responses. See
    # doc/DEVICE_PROTOCOL.md §7.9.3 and /memories/repo/olt-device-analysis.md.
    _applied_configs: dict[str, Any] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.device_type = constants.DEVICE_TYPE_OLT
        self._apply_wired_profile()
        self._applied_configs = {}
        # Report a small non-zero CPU utilisation, like switches, so the
        # controller's health scorer has a data point (a 0% sample reads as
        # "no data").
        if not self.cpu_util:
            self.cpu_util = stats.synthetic_percent(self.mac, "oltcpu", 2, 15)

    # -- negotiation / management-channel bodies -------------------------
    # The OLT reuses the AP-style long-name deviceInfo (not the
    # switch/gateway short-name set), so override the WiredDevice defaults
    # that build short-name fields.
    def manage_device_info(self) -> dict[str, Any]:
        """The negotiation `deviceInfo` block (OLT adopt device-info shape):
        long-name version fields + OLT-specific identity fields
        (hwId/oemId/lagCount/ponPortCount/wirelessLinked). Note this differs
        from the discovery device-info (which also has ip/name/upTime/
        isFactoryDefault) — the adopt device-info carries only the
        identity/firmware fields the controller's adopt handler reads."""
        return {
            "model": self.identity.model,
            "modelVersion": self.identity.model_version,
            "firmwareVersion": self.identity.firmware_version,
            "hardwareVersion": self.identity.hardware_version,
            "hwId": self.hw_id,
            "oemId": self.oem_id,
            "lagCount": self.lag_count,
            "ponPortCount": self.pon_port_count,
            "wirelessLinked": self.wireless_linked,
        }

    def build_manage_negotiation_body(self, controller_id: str) -> dict[str, Any]:
        """The DEVICE_NEGOTIATION body. Unlike APs/switches/gateways (whose
        negotiation body uses a generic envelope with `components_v2`/`devCap`/
        `deviceMisc`), the OLT's negotiation body is parsed by the controller
        directly as the OLT adopt-response shape, which expects `components`
        (a map of OLT component -> "ver.funcVer"), `deviceInfo` (OLT adopt
        device-info) and `isFactoryDefault`. The `components` map must be
        non-null (the controller errors on null) and must include
        `centralManagement` (else the adopt handler flags the device
        incompatible). The controller id is NOT carried in this body for OLT
        — it is taken from the ECSP session/header. See
        doc/DEVICE_PROTOCOL.md §7.9."""
        return {
            "components": dict(olt_profile.COMPONENTS),
            "deviceInfo": self.manage_device_info(),
            "isFactoryDefault": True,
        }

    # -- INFORM body -----------------------------------------------------
    def manage_inform_body(self) -> dict[str, Any]:
        """The OLT periodic INFORM body. Unlike APs/switches/gateways, the OLT's
        inform ``deviceInfo`` is the OLT inform device-info shape
        (ip/name/cpuUti/memUti/upTime/onuCount/portOnuCount), NOT the adopt
        device-info returned by ``manage_device_info()``. The controller
        unboxes ``onuCount`` and the traffic ``time`` field without null
        checks, so both must be present (else errors in the monitor/inform
        handlers). The body also carries the per-PON-port ``trafficStat``
        (a list of per-port counters), ``trafficTimeStamp``, ``needReply``
        and an optional ``lldp`` section. See doc/DEVICE_PROTOCOL.md §7.9.2."""
        up = self.uptime_seconds
        agg_rx, agg_tx = self._aggregate_traffic()
        body: dict[str, Any] = {
            "deviceInfo": {
                "name": self.name,
                "upTime": up,
                "ip": self.ip,
                "memUti": self.mem_util,
                "cpuUti": self.cpu_util,
                "down": str(agg_rx),
                "up": str(agg_tx),
                "onuCount": self._onu_count(),
                "portOnuCount": self._port_onu_count(),
            },
            "needReply": False,
        }
        body.update(self._traffic_stat_section())
        links = self.topology.all_links()
        if links:
            body.update(topology.lldp_section(links))
        return body

    def manage_inform_extra(self) -> dict[str, Any]:
        # Unused for OLT: manage_inform_body() builds the full body. Kept as a
        # no-op for back-compat with the base Device contract.
        return {}

    def _onu_count(self) -> int:
        """Total registered ONUs across all PON ports (synthetic, deterministic
        per device)."""
        return stats.synthetic_int(self.mac, "onuct", 1, self.pon_port_count * 4)

    def _port_onu_count(self) -> dict[str, int]:
        """Per-PON-port registered ONU count (a map keyed by port number as a
        string)."""
        return {str(p): stats.synthetic_int(self.mac, f"onu{p}", 0, 4)
                for p in range(1, self.pon_port_count + 1)}

    def _aggregate_traffic(self) -> tuple[int, int]:
        """(rx_bytes, tx_bytes) aggregated across all PON ports for the inform
        ``deviceInfo.down``/``up`` fields."""
        up = self.uptime_seconds
        rx = sum(stats.synthetic_bytes(self.mac, f"pon{p}rx", up,
                  stats.synthetic_rate_bps(self.mac, f"pon{p}rr", 5, 1000))
                 for p in range(1, self.pon_port_count + 1))
        tx = sum(stats.synthetic_bytes(self.mac, f"pon{p}tx", up,
                  stats.synthetic_rate_bps(self.mac, f"pon{p}tr", 5, 1000))
                 for p in range(1, self.pon_port_count + 1))
        return rx, tx

    def _traffic_stat_section(self) -> dict[str, Any]:
        """The ``trafficStat`` block (a list of per-PON-port stats). Reports
        per-PON-port byte/packet counters (incl. multicast/broadcast) and an
        aggregate up/down, so the controller's OLT detail page has non-empty
        port statistics."""
        up = self.uptime_seconds
        ports = []
        for port in range(1, self.pon_port_count + 1):
            salt = f"pon{port}"
            rx = stats.synthetic_bytes(self.mac, salt + "rx", up,
                                       stats.synthetic_rate_bps(self.mac, salt + "rr", 5, 1000))
            tx = stats.synthetic_bytes(self.mac, salt + "tx", up,
                                       stats.synthetic_rate_bps(self.mac, salt + "tr", 5, 1000))
            ports.append({
                "port": port,
                "linkStatus": 1,
                "rx": rx,
                "tx": tx,
                "rxP": stats.synthetic_packets(rx),
                "txP": stats.synthetic_packets(tx),
                "rxMP": stats.synthetic_packets(rx // 4),  # multicast packets
                "txMP": stats.synthetic_packets(tx // 4),
                "rxBP": stats.synthetic_packets(rx // 8),  # broadcast packets
                "txBP": stats.synthetic_packets(tx // 8),
                "status": 1,
            })
        agg_rx = sum(p["rx"] for p in ports)
        agg_tx = sum(p["tx"] for p in ports)
        return {
            "trafficStat": {
                "up": agg_tx,
                "down": agg_rx,
                "portStats": ports,
            },
            "trafficTimeStamp": int(up),
            "oltNeedReply": False,
        }

    # -- config push / query round-trip ---------------------------------
    # The OLT SET-key surface has exactly two keys (``controllerInfo`` /
    # ``highAbility``). ``upgrade`` is part of the config body rather than an
    # enum key, but can arrive in the same initial/config SET body.
    _CAPTURED_SET_KEYS: ClassVar[tuple[str, ...]] = (
        "controllerInfo", "highAbility", "upgrade",
    )

    @staticmethod
    def _device_response(data: Any = None) -> dict[str, Any]:
        """Build the OLT detail-operation response shape.

        The OLT controller subsystem sends URI-based requests (with ``uri``
        and ``params``) over ordinary ECSP SET/GET requests. Those are
        distinct from initial config pushes and require this wrapper even
        when the requested detail operation is not implemented by the
        emulator.
        """
        return {
            "deviceType": constants.DEVICE_TYPE_OLT,
            "errcode": 0,
            "message": "",
            "data": data,
        }

    def build_set_response(self, req_body: dict[str, Any]) -> dict[str, Any]:
        """Handle either an OLT URI operation or an initial/config SET push."""
        uri = req_body.get("uri")
        if isinstance(uri, str):
            params = req_body.get("params") or {}
            data = olt_detail_ops.handle_set(
                uri, self.mac, self.pon_port_count, params)
            return self._device_response(data)
        resp = super().build_set_response(req_body)
        for key in self._CAPTURED_SET_KEYS:
            value = req_body.get(key)
            if isinstance(value, dict):
                self._applied_configs[key] = deepcopy(value)
                if key == "upgrade":
                    # Upgrade config = {reboot, interval}. When the
                    # controller pushes an upgrade config with reboot set,
                    # record the firmware-upgrade state so the image-table
                    # GET and firmware-upgrade-status reflect it.
                    olt_detail_ops._UPGRADE_STATE[self.mac] = {
                        "status": "success" if value.get("reboot") else "downloading",
                        "progress": 100 if value.get("reboot") else 50,
                        "newVersion": value.get("newVersion", "1.1.0"),
                        "message": ("Firmware upgraded, rebooting"
                                    if value.get("reboot")
                                    else "Firmware download initiated"),
                    }
        return resp

    def build_get_response(self, req_body: dict[str, Any]) -> dict[str, Any]:
        """Respond to an OLT URI GET with the detail-operation response shape.

        OLT has no dedicated GET-key config-query surface. A non-URI request
        is retained as the generic base ack for forward compatibility, but
        never invents a flat OLT config body. URI GETs dispatch to the
        synthetic detail-ops handlers (:mod:`device_emulator.devices.olt_detail_ops`)
        which return realistic per-URI payloads matching the controller's OLT
        management responses (PON ports, ONU management, profiles, VLAN, LAG,
        STP, LLDP, routing, ARP, IGMP/MLD/MVR multicast, ACL, QoS, system info,
        DDM, SNMP, users, diagnostics, etc.). Uncovered URIs return
        ``data: null`` with ``errcode: 0``.
        """
        uri = req_body.get("uri")
        if isinstance(uri, str):
            params = req_body.get("params") or {}
            data = olt_detail_ops.handle_get(
                uri, self.mac, self.pon_port_count, params)
            return self._device_response(data)
        return super().build_get_response(req_body)

    # -- discovery -------------------------------------------------------
    def build_discovery_body(self) -> dict[str, Any]:
        assert self.controller_id is not None
        return build_olt_discovery_body(
            ip=self.ip,
            model=self.identity.model,
            model_version=self.identity.model_version,
            firmware_version=self.identity.firmware_version,
            hardware_version=self.identity.hardware_version,
            name=self.name,
            controller_id=self.controller_id,
            up_time_seconds=self.uptime_seconds,
            pon_port_count=self.pon_port_count,
            lag_count=self.lag_count,
            oem_id=self.oem_id,
            hw_id=self.hw_id,
            country_code=self.country_code,
        )