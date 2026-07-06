"""Emulated gateway / router."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .. import stats
from ..protocol import constants
from ..protocol.discovery import build_gateway_discovery_body
from . import gateway_profiles, topology
from .wired import WiredDevice


def _derive_port_macs(mac: str, count: int) -> list[dict[str, Any]]:
    """Derive per-WAN-port default MACs from the device MAC by incrementing
    the last octet (so they are stable and consistent with the device)."""
    base = mac.split("-")
    try:
        last = int(base[-1], 16)
    except ValueError:
        last = 0
    macs = []
    for port in range(1, count + 1):
        octet = (last + port) & 0xFF
        macs.append({"defMac": "-".join(base[:-1] + [f"{octet:02X}"]), "portId": port})
    return macs


@dataclass
class GatewayDevice(WiredDevice):
    port_num: int = 5
    wireless: int = 0
    certified_version: str = "1.0"
    # Gateways report modest default utilisation.
    cpu_util: int = 1
    mem_util: int = 32

    # ``profile`` is set dynamically in ``__post_init__`` based on the model
    # string — see ``gateway_profiles.get_profile``.  The class-level default
    # keeps mypy / dataclass happy before init runs.
    profile = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.device_type = constants.DEVICE_TYPE_GATEWAY
        # Select the model-specific profile (ER605, ER706W, ER7206, ER8411…).
        # Falls back to ER605 for unrecognised models.
        self.profile = gateway_profiles.get_profile(self.identity.model)
        self._apply_wired_profile()
        # The controller-pushed WAN config, captured from the last SET_REQUEST so
        # a later GET can echo the applied values (Ports -> WAN tab). See
        # build_set_response / build_get_response.
        self._applied_wan_ipv4: dict[str, Any] = {}
        self._applied_wan_ipv6: dict[str, Any] = {}
        self._applied_wan_mac: dict[str, Any] = {}
        # Controller-pushed feature configs (firewall/NAT/QoS/VPN/DDNS/IPTV
        # etc.) captured from SET_REQUEST so a later GET can echo them.
        self._applied_configs: dict[str, Any] = {}
        # Structured VPN tunnel state parsed from the last pushed vpn/sslVpn/
        # wireguard SET config — used to drive the INFORM VPN sections instead
        # of purely synthetic defaults.
        self._vpn_tunnels: dict[str, Any] = {}
        self._ssl_vpn_connections: dict[str, Any] = {}
        self._wireguard_peers: dict[str, Any] = {}
        # The last SET response (for lastCfgResult / cfgResults INFORM sections).
        self._last_set_response: dict[str, Any] = {}
        # Rolling history of recent SET responses (for the cfgResults INFORM
        # section). Capped at 10 entries.
        self._cfg_result_history: list[dict[str, Any]] = []

    def manage_inform_extra(self) -> dict[str, Any]:
        # Report the full per-port status (incl. the WAN port with IPv4 fields),
        # the LLDP neighbour table for every wired downlink, and a small routing
        # table. The shapes mirror the controller's expected INFORM format
        # (portInfo/portInfos with per-port status, lldp, routingTable/routingTables).
        extra: dict[str, Any] = {}
        extra.update(self._port_info_section())
        links = self.topology.all_links()
        if links:
            extra.update(topology.lldp_section(links))
        extra.update(self._routing_table_section())
        # LAN clients, DHCP leases, WAN/network traffic and the ARP table so the
        # Clients page, DHCP-lease list, Overview throughput and ARP populate.
        extra.update(self._client_section())
        extra.update(self._dhcp_section())
        extra.update(self._traffic_section())
        extra.update(self._arp_section())
        # VPN / firewall / NAT / QoS / DDNS runtime sections so the gateway
        # detail-page tabs (VPN, Firewall/NAT/Session, QoS/Bandwidth, DDNS,
        # Port Forwarding) populate.
        extra.update(self._vpn_section())
        extra.update(self._ssl_vpn_section())
        extra.update(self._wireguard_section())
        extra.update(self._ddns_section())
        extra.update(self._qos_section())
        extra.update(self._ct_table_section())
        extra.update(self._portforward_section())
        extra.update(self._network_traffic_section())
        extra.update(self._ips_threat_section())
        # Capability-gated sections (only on models that support them).
        if getattr(self.profile, "SUPPORT_SDWAN", False):
            extra.update(self._sdwan_section())
        if getattr(self.profile, "SUPPORT_DISCRETE_WAN", False) or \
           getattr(self.profile, "SUPPORT_WAN_LOAD_BALANCE", False):
            extra.update(self._virtual_wan_section())
        if getattr(self.profile, "SUPPORT_LTE", False):
            extra.update(self._lte_section())
        if getattr(self.profile, "SUPPORT_POE", False):
            extra.update(self._poe_section())
        # Additional telemetry sections (always emitted, may be empty lists).
        extra.update(self._client_traffic_section())
        extra.update(self._abnormal_dt_section())
        extra.update(self._event_inform_section())
        extra.update(self._acl_hit_section())
        extra.update(self._portal_duration_section())
        extra.update(self._applications_traffic_section())
        extra.update(self._monitor_section())
        # Config-push result sections (reflect the last SET response).
        extra.update(self._last_cfg_result_section())
        extra.update(self._cfg_results_section())
        # Wireless INFORM sections (only for WiFi-capable gateway models,
        # i.e. ``wireless > 0``). The shapes mirror the AP's wireless sections
        # but are carried in the gateway's INFORM body: per-radio
        # ``wSettings_<band>G`` / ``radioTraffic_<band>G`` / ``ssidStats_<band>G``
        # plus ``mesh`` / ``roaming``. A wired-only gateway (ER605, wireless=0)
        # does not emit these. See doc/DEVICE_PROTOCOL.md §7.8.
        if self.wireless > 0:
            extra.update(self._wireless_sections())
        # VoIP / telephony INFORM section (``callLogInform``). Emitted when the
        # controller has pushed a ``callLog`` SET config (enabling call logging).
        # The gateway reports synthetic call-log entries. See
        # doc/DEVICE_PROTOCOL.md §7.8.
        extra.update(self._voip_section())
        return extra

    def _client_section(self) -> dict[str, Any]:
        """The ``client`` section: every LAN client the
        gateway sees (the gateway is the default route, so it aggregates all
        site clients)."""
        up = self.uptime_seconds
        clients = []
        for client in self.reported_clients:
            rx, tx = client.traffic(up)
            clients.append({
                "mac": client.mac,
                "name": client.name,
                "ip": client.ip,
                "vid": client.vlan,
                "time": client.assoc_seconds,
                "rx": rx,
                "rxP": stats.synthetic_packets(rx),
                "tx": tx,
                "txP": stats.synthetic_packets(tx),
                "txT": client.up_bps,
                "firstSeen": client.first_seen_ms,
                "authed": 1,
                "port": self.port_num,
            })
        return {"client": {"clients": clients}}

    def _dhcp_section(self) -> dict[str, Any]:
        """The ``dhcpClient`` section (``DhcpClientInfo``): the gateway's DHCP
        server leases (Ports/Services -> DHCP Client List)."""
        entries = [
            {"name": c.name, "ip": c.ip, "mac": c.mac, "leaseTime": 7200}
            for c in self.dhcp_leases
        ]
        return {"dhcpClient": {"clients": entries}}

    def _traffic_section(self) -> dict[str, Any]:
        """The ``trafficStat`` section: per-port
        byte/packet counters + instantaneous rates so the Overview Upload /
        Download rate and per-port traffic are non-zero (WAN is port 1)."""
        up = self.uptime_seconds
        port_caps = self.profile.DEV_CAP.get("portInfos", [])
        linked = {ln.local_port for ln in self.topology.all_links()}
        traffic = []
        for cap in port_caps:
            port = cap["port"]
            if port != 1 and port not in linked:
                continue
            rx_rate = stats.synthetic_rate_bps(self.mac, f"gwrx{port}", 20, 400)
            tx_rate = stats.synthetic_rate_bps(self.mac, f"gwtx{port}", 5, 120)
            rx = stats.synthetic_bytes(self.mac, f"gwrxb{port}", up, rx_rate)
            tx = stats.synthetic_bytes(self.mac, f"gwtxb{port}", up, tx_rate)
            traffic.append({
                "port": port,
                "physicalType": 0,
                "rx": rx, "tx": tx,
                "rxP": stats.synthetic_packets(rx), "txP": stats.synthetic_packets(tx),
                "rxR": rx_rate, "txR": tx_rate,
                "rxErrPkt": 0, "txErrPkt": 0, "errPkt": 0, "lossPkt": 0,
            })
        return {"trafficStat": {"trafficStats": traffic}}

    def _arp_section(self) -> dict[str, Any]:
        """The ``arp`` section: one ARP entry per LAN client."""
        arps = [
            {"mac": c.mac, "ip": c.ip, "port": self.port_num, "vlan": c.vlan}
            for c in self.reported_clients
        ]
        return {"arp": {"arps": arps}}

    def _port_info_section(self) -> dict[str, Any]:
        """The ``portInfo`` INFORM section: every port the gateway exposes
        (from the profile's ``devCap.portInfos``), with the WAN port (port 1)
        reporting its IPv4 address/gateway/DNS so the Ports -> WAN tab
        populates. Downlink ports that have a wired neighbour report ``status``
        up; the rest report link-down."""
        port_caps = self.profile.DEV_CAP.get("portInfos", [])
        # The WAN IPv4 details the device would obtain via DHCP on port 1.
        wan_ipv4 = {
            "ip": self.ip,
            "netmask": "255.255.255.0",
            "gateway": "10.0.2.2",
            "priDns": "8.8.8.8",
            "sndDns": "8.8.4.4",
        }
        linked_ports = {link.local_port for link in self.topology.all_links()}
        port_infos = []
        for cap in port_caps:
            port = cap["port"]
            entry: dict[str, Any] = {
                "port": port,
                "physicalType": 0,
                "name": cap.get("name", f"P{port}"),
                "mode": cap.get("mode", 1),
                "mac": self.mac,
                "status": 1 if port in linked_ports else 0,
                "speed": 1000 if port in linked_ports else 0,
                "duplex": 1 if port in linked_ports else 0,
                # The controller's port-inform decoder unboxes internetState /
                # internetV6 to int on EVERY port without a null check, so they
                # must be present on all ports (0 = no internet, 1 = online).
                "internetState": 1 if port == 1 else 0,
                "internetV6": 0,
            }
            if port == 1:
                # WAN port: report the acquired IPv4 lease + internet state.
                # The ip/netmask are flat per-port fields; the gateway and
                # DNS servers go in the nested ``ip4`` block — the
                # controller's port-inform decoder reads gw/priDns/sndDns from
                # there for the Ports -> WAN tab. ``publicWanIp`` is the WAN's
                # public address (== the lease IP for the emulator — no CGNAT
                # simulation); ``gw2``/``priDns2``/``sndDns2`` are the secondary
                # gateway/DNS for multi-WAN / dual-stack setups.
                entry.update({
                    "internetState": 1,
                    "ip": wan_ipv4["ip"],
                    "netmask": wan_ipv4["netmask"],
                    "publicWanIp": 1,
                    "latency": stats.synthetic_int(self.mac, "wanlat", 4, 30),
                    "ip4": {
                        "gw": wan_ipv4["gateway"],
                        "gw2": "",
                        "priDns": wan_ipv4["priDns"],
                        "sndDns": wan_ipv4["sndDns"],
                        "priDns2": "",
                        "sndDns2": "",
                    },
                })
                # IPv6 on the WAN port (ip6 block: addr, gw, priDns,
                # sndDns, prefix). Only when the profile supports IPv6.
                if getattr(self.profile, "SUPPORTS_IPV6", True):
                    entry["internetV6"] = 1
                    entry["ip2"] = "2001:db8::1"
                    entry["netmask2"] = "ffff:ffff:ffff:ffff::"
                    entry["ip6"] = {
                        "addr": "2001:db8::1",
                        "gw": "2001:db8::ffff",
                        "priDns": "2001:4860:4860::8888",
                        "sndDns": "2001:4860:4860::8844",
                        "prefix": "64",
                    }
            port_infos.append(entry)
        return {"portInfo": {"portInfos": port_infos}}

    def _routing_table_section(self) -> dict[str, Any]:
        """The ``routingTable`` INFORM section so the Routing tab shows entries.
        Matches the controller's routing table format (routingTables list
        (id, destIp (a list of strings), nextHop, interfaceName, metric).

        The baseline routes (default route via WAN + the directly-connected LAN
        network) are always present. When the controller has pushed a
        ``staticRouting`` / ``policyRouting`` SET config, the operator-configured
        routes are appended (mirroring how the switch echoes ``staticRouting``).
        The pushed static routing entry uses ``destinations`` (list of strings),
        ``nextHopIp``, ``interface`` and ``metric``."""
        routes: list[dict[str, Any]] = [
            {
                "id": 1,
                "destIp": ["0.0.0.0/0"],
                "nextHop": "10.0.2.2",
                "interfaceName": "wan1",
                "metric": 1,
            },
            {
                "id": 2,
                "destIp": [f"{self.ip}/24"],
                "nextHop": "0.0.0.0",
                "interfaceName": "lan",
                "metric": 0,
            },
        ]
        # Append operator-configured static routes (echoed from the last
        # ``staticRouting`` SET_REQUEST). The pushed config has
        # ``staticRoutings`` (list of routing entries); each entry carries
        # ``destinations`` (a list of strings), ``nextHopIp``, ``interface``, ``metric``.
        static_cfg = self._applied_configs.get("staticRouting", {})
        for entry in static_cfg.get("staticRoutings") or []:
            if not isinstance(entry, dict):
                continue
            routes.append({
                "id": entry.get("id", len(routes) + 1),
                "destIp": entry.get("destinations") or ["0.0.0.0/0"],
                "nextHop": entry.get("nextHopIp", "0.0.0.0"),
                "interfaceName": self._interface_name(entry.get("interface")),
                "metric": entry.get("metric", 1),
            })
        # Policy routing rules are reported the same way (policy routing entry
        # has the same ``destinations``/``nextHopIp``/``interface``/``metric`` fields).
        policy_cfg = self._applied_configs.get("policyRouting", {})
        for entry in policy_cfg.get("policyRoutings") or policy_cfg.get("rules") or []:
            if not isinstance(entry, dict):
                continue
            routes.append({
                "id": entry.get("id", len(routes) + 1),
                "destIp": entry.get("destinations") or ["0.0.0.0/0"],
                "nextHop": entry.get("nextHopIp", "0.0.0.0"),
                "interfaceName": self._interface_name(entry.get("interface")),
                "metric": entry.get("metric", 1),
            })
        return {"routingTable": {"routingTables": routes}}

    @staticmethod
    def _interface_name(interface_id: Any) -> str:
        """Map a pushed interface id (Integer) to a routing-table interface
        name. Port 1 is the WAN (``wan1``); other ports are LAN interfaces."""
        try:
            port = int(interface_id)
        except (TypeError, ValueError):
            return "lan"
        return "wan1" if port == 1 else f"lan{port}"

    # -- SET keys whose applied config we capture for GET echo ----------
    # Every config key the controller
    # may push to a gateway. We capture the dict-valued ones for GET echo
    # and config-driven INFORM sections. (See /memories/repo/gateway-services-dtos.md
    # §gateway-vpn-config-dtos.md for the confirmed list.)
    _CAPTURED_SET_KEYS = (
        # WAN / connectivity
        "wanIpv4", "wanIpv6", "wanMac", "wanIpv4Usb", "wanBasicSetting",
        "wanLoadBalance", "connect", "onlineDetection", "virtualWan",
        "network", "lanDns", "iptv", "dsl", "lte", "speedTest",
        "speedTestSchedule",
        # Security / firewall / NAT
        "firewallConfig", "attackDefense", "natAlg", "sessionLimit",
        "bandwidthCtrl", "qos", "natPf", "oneToOneNat", "disableNat", "acl",
        "wirelessAcl", "customAcl", "urlFiltering", "wirelessUrlFiltering",
        "ips", "ipsWhiteList", "ipsBlackList", "signatureList",
        "blockCountry", "countryGroup", "macFilter", "ipMacBinding",
        # VPN
        "vpn", "vpnUser", "vpnUsers", "sslVpn", "wireguard",
        "ipsecFailover", "radiusProfile",
        # Routing
        "staticRouting", "policyRouting",
        # Services / management
        "snmp", "led", "ssh", "lldp", "upnp", "mdns", "hwOffload", "jumbo",
        "echoServer", "common", "system", "timeSetting", "dstConfig",
        "delayEffect", "serviceType", "ipGroup", "ipv6Group", "ipPortGroup",
        "ipv6PortGroup", "domainGroup", "domainNoPortGroup", "macGroup",
        "timeRange", "ddns", "mail", "ldap", "dnsProxy", "dnsCache",
        "dpiProtocols", "dpiTraffic",
        # Client / portal
        "client", "clientOpt", "clientIpBinding", "clientTrafficRequire",
        "portalFreePolicyConfig", "portforward",
        # Infrastructure / device management
        "sdwan", "port", "speedDuplex", "mirror", "poe",
        "abnormalDetect",
        # Wireless (gateway models with integrated WiFi — captured even if
        # not config-driven so GET echoes them; wireless INFORM sections are
        # emitted by ``_wireless_sections`` when ``wireless > 0``).
        "bandSteering", "mesh", "roaming", "ppskV3",
        # VoIP / telephony (gateway models with integrated VoIP — captured
        # so GET echoes them; VoIP INFORM sections are emitted by
        # ``_voip_section``).
        "voipDeviceOsgSetting", "callForwarding", "callBlocking", "callLog",
        "voiceMail", "voiceMailDownload", "voiceMailSettings",
        "voipViaIpv6", "numberAdvancedSetting",
    )

    # Keys that are handled specially (terminalSetting/monitorServer/
    # packageCapture/transferChannel) by the base/runner and must NOT be
    # captured/acked as feature configs here.
    _SPECIAL_HANDLED_KEYS = frozenset({
        "terminalSetting", "monitorServer", "packageCapture",
        "transferChannel", "controllerInfo", "controllerSetting",
        "userAccount",  # handled separately (managed account)
        "sequenceId", "configVersion",  # protocol-control fields
    })

    def build_set_response(self, req_body: dict[str, Any]) -> dict[str, Any]:
        """Acknowledge a SET and remember the controller-pushed WAN config so a
        later GET can echo the *applied* values (the Ports -> WAN tab reads the
        applied config, not the INFORM-reported port status). Also adds
        per-feature ack sub-objects (``{key:
        {errcode: 0}}``) for each feature config the controller pushed so the
        controller knows each feature was applied successfully. Every key in
        the SET body (except protocol-control / specially-handled keys) is
        acked — this covers every config key rather than a subset."""
        resp = super().build_set_response(req_body)
        wan = req_body.get("wanIpv4")
        if isinstance(wan, dict):
            self._applied_wan_ipv4 = deepcopy(wan)
        wan_ipv6 = req_body.get("wanIpv6")
        if isinstance(wan_ipv6, dict):
            self._applied_wan_ipv6 = deepcopy(wan_ipv6)
        wan_mac = req_body.get("wanMac")
        if isinstance(wan_mac, dict):
            self._applied_wan_mac = deepcopy(wan_mac)
        # Capture every recognised feature config so GET can echo it.
        for key in self._CAPTURED_SET_KEYS:
            val = req_body.get(key)
            if isinstance(val, dict):
                self._applied_configs[key] = deepcopy(val)
        # Parse VPN configs into structured tunnel state for config-driven
        # INFORM sections (see _vpn_section / _ssl_vpn_section /
        # _wireguard_section).
        self._parse_vpn_config()
        # Add per-feature SET ack sub-objects.
        # Each ack is {"errcode": 0} — the base response shape. Ack every
        # feature key present in the request body so the controller records
        # each pushed feature as applied. Keys handled by the base/runner
        # (terminalSetting/monitorServer/packageCapture/transferChannel) are
        # skipped here — they are acked by their own handlers.
        for key in req_body:
            if key in self._SPECIAL_HANDLED_KEYS:
                continue
            if key in self._CAPTURED_SET_KEYS:
                resp[key] = {"errcode": 0}
        # WAN config keys are acked explicitly (they live outside the
        # _CAPTURED_SET_KEYS feature-config set but are still ack
        # ack keys).
        if "wanIpv4" in req_body:
            resp["wanIpv4"] = {"errcode": 0}
        if "wanMac" in req_body:
            resp["wanMac"] = {"errcode": 0}
        if "wanIpv6" in req_body:
            resp["wanIpv6"] = {"errcode": 0}
        if "wanIpv4Usb" in req_body:
            resp["wanIpv4Usb"] = {"errcode": 0}
        # Store the last SET response for lastCfgResult / cfgResults INFORM.
        self._last_set_response = deepcopy(resp)
        # Accumulate the response into the cfgResults history (see
        # _cfg_results_section) — capped to avoid unbounded growth.
        self._cfg_result_history.append(deepcopy(resp))
        if len(self._cfg_result_history) > 10:
            del self._cfg_result_history[:-10]
        return resp

    def _parse_vpn_config(self) -> None:
        """Parse the captured vpn/sslVpn/wireguard SET configs into structured
        tunnel-state dicts.  The pushed config field names are CONFIRMED from
        the confirmed VPN config field names
        (v6.2.14.11, see /memories/repo/gateway-vpn-config-dtos.md):

        - ``vpn`` uses ``server_IPSecs``/``server_OpenVPNs``/``server_PPTPs``/
          ``server_L2TPs``/``autoIPSecs``/``manualIPSecs``/``client_Wireguards``
          (underscore-prefixed server/client keys), NOT ``ipsecTunnels`` etc.
        - ``sslVpn`` uses ``users`` (not ``sslVpnUsers``) + ``locks`` + a
          ``sslVpnServer`` sub-object holding the enable flag.
        - ``wireguard`` uses ``interfaces``/``peers`` (already correct).

        We extract the tunnel lists so the INFORM VPN sections can report real
        tunnel counts and identity instead of purely synthetic defaults. The
        legacy fallback keys are kept for robustness against older builds."""
        vpn_cfg = self._applied_configs.get("vpn", {})
        if vpn_cfg:
            # VPN config tunnel lists (confirmed keys + legacy fallbacks).
            ipsec = (vpn_cfg.get("server_IPSecs") or vpn_cfg.get("autoIPSecs")
                     or vpn_cfg.get("manualIPSecs") or vpn_cfg.get("ipsecTunnels")
                     or vpn_cfg.get("ipSecs") or [])
            openvpn = (vpn_cfg.get("server_OpenVPNs") or vpn_cfg.get("openvpnTunnels")
                       or vpn_cfg.get("openvpn") or [])
            pptp = (vpn_cfg.get("server_PPTPs") or vpn_cfg.get("pptpTunnels")
                    or vpn_cfg.get("pptpClients") or [])
            l2tp = (vpn_cfg.get("server_L2TPs") or vpn_cfg.get("l2tpTunnels")
                    or vpn_cfg.get("l2tpClients") or [])
            # client-to-site WireGuard tunnels live inside the vpn config
            # (vpn config client_Wireguards) and drive the vpn.wireguard
            # INFORM sub-field (see _vpn_section).
            c2s_wg = vpn_cfg.get("client_Wireguards") or vpn_cfg.get("server_Wireguards") or []
            self._vpn_tunnels = {
                "ipsec": ipsec,
                "openvpn": openvpn,
                "pptp": pptp,
                "l2tp": l2tp,
                "c2s_wireguard": c2s_wg,
            }
        ssl_cfg = self._applied_configs.get("sslVpn", {})
        if ssl_cfg:
            # SSL-VPN config: ``users`` (confirmed) drives connections; ``locks``
            # drives the INFORM locks; enable flag is in ``sslVpnServer``.
            server_cfg = ssl_cfg.get("sslVpnServer") or {}
            if isinstance(server_cfg, dict):
                ssl_enable = int(server_cfg.get("enable", 1))
            else:
                ssl_enable = int(ssl_cfg.get("enable", 1))
            self._ssl_vpn_connections = {
                "users": ssl_cfg.get("users") or ssl_cfg.get("sslVpnUsers") or [],
                "locks": ssl_cfg.get("locks") or [],
                "enable": ssl_enable,
            }
        wg_cfg = self._applied_configs.get("wireguard", {})
        if wg_cfg:
            self._wireguard_peers = {
                "interfaces": wg_cfg.get("interfaces") or wg_cfg.get("wireguards") or [],
                "peers": wg_cfg.get("peers") or wg_cfg.get("tunnels") or [],
            }

    def build_get_response(self, req_body: dict[str, Any]) -> dict[str, Any]:
        """Respond to a GET with the applied WAN IPv4/IPv6 config so the Ports
        -> WAN tab populates. Matches the GET response format (sequenceId, errcode,
        and a ``wanIpv4`` map from the parent response). The WAN MAC
        comes from the controller-pushed ``wanMac`` setting; the IP/gateway/DNS
        default to the device's own lease (reported in INFORM) until the
        controller pushes a static WAN. Also echoes ALL captured feature
        configs under their GET response keys, plus dedicated GET
        response bodies (``arptable``/``dnsCache``/``dpiProtocols``)."""
        resp = super().build_get_response(req_body)
        wan_mac = None
        mac_settings = (getattr(self, "_applied_wan_mac", {}) or {}).get("settings") or []
        if mac_settings:
            wan_mac = mac_settings[0].get("mac")
        wan_settings = (getattr(self, "_applied_wan_ipv4", {}) or {}).get("settings") or []
        pushed = wan_settings[0] if wan_settings else {}
        wan_ipv4: dict[str, Any] = {
            "portId": pushed.get("portId", 1),
            "proto": pushed.get("proto", "dhcp"),
            "mtu": pushed.get("mtu", 1500),
            "vlanId": pushed.get("vlanId", 0),
            "qosTag": pushed.get("qosTag", -1),
            "unicast": pushed.get("unicast", "off"),
            # The acquired lease reported in the INFORM portInfo (port 1).
            "ip": self.ip,
            "netmask": "255.255.255.0",
            "gateway": "10.0.2.2",
            "priDns": "8.8.8.8",
            "sndDns": "8.8.4.4",
            "mac": wan_mac or _derive_port_macs(self.mac, 1)[0]["defMac"],
            "status": 1,
        }
        resp["wanIpv4"] = wan_ipv4
        # Echo the applied WAN IPv6 config if the controller pushed one.
        if self._applied_wan_ipv6:
            resp["wanIpv6"] = deepcopy(self._applied_wan_ipv6)
        # Dedicated GET response bodies (keys that have their
        # own response shape rather than a 1:1 config echo).
        resp["arptable"] = {"arps": [
            {"mac": c.mac, "ip": c.ip, "port": self.port_num, "vlan": c.vlan}
            for c in self.reported_clients
        ]}
        # dnsCache: synthetic DNS cache entries (domain -> resolved IP) for a
        # few well-known hosts. Reported only on GET (not in INFORM).
        resp["dnsCache"] = {"caches": [
            {"domain": "example.com", "ip": "93.184.216.34", "ttl": 300},
            {"domain": "example.org", "ip": "50.57.234.100", "ttl": 3600},
        ]}
        # dpiProtocols: synthetic DPI protocol list. If a dpiProtocols config
        # was pushed, reflect it; otherwise report a minimal default set.
        dpi_cfg = self._applied_configs.get("dpiProtocols", {})
        protocols = dpi_cfg.get("protocols") if isinstance(dpi_cfg, dict) else None
        if not protocols:
            protocols = [
                {"id": 1, "name": "HTTP", "enable": 1},
                {"id": 2, "name": "HTTPS", "enable": 1},
                {"id": 3, "name": "DNS", "enable": 1},
            ]
        resp["dpiProtocols"] = {"protocols": protocols}
        # Echo ALL applied feature configs under their GET response keys.
        # The key mapping covers the confirmed GET-response JSON key
        # names.  Most SET keys map 1:1 to GET keys; a few are renamed.
        _GET_KEY_MAP = {
            # Confirmed GET response keys (with rename).
            "vpn": "vpn",
            "sslVpn": "sslVpn",
            "ddns": "ddnsStats",
            "sessionLimit": "sessionLimit",
            "wireguard": "wireguard",
            "acl": "aclHit",
            "urlFiltering": "urlFiltering",
            "lte": "lte",
            # These echo under the same key name (the controller accepts them
            # as additional properties on the base class).
            "firewallConfig": "firewallConfig",
            "natAlg": "natAlg",
            "bandwidthCtrl": "bandwidthCtrl",
            "iptv": "iptv",
            "attackDefense": "attackDefense",
            "portforward": "portforward",
            "natPf": "natPf",
            "oneToOneNat": "oneToOneNat",
            "qos": "qos",
            "onlineDetection": "onlineDetection",
            "ipsecFailover": "ipsecFailover",
            "snmp": "snmp",
            "led": "led",
            "lldp": "lldp",
            "upnp": "upnp",
            "hwOffload": "hwOffload",
            "staticRouting": "staticRouting",
            "policyRouting": "policyRouting",
            "network": "network",
            "serviceType": "serviceType",
            "ipGroup": "ipGroup",
            "ips": "ips",
            "jumbo": "jumbo",
            "vpnUser": "vpnUser",
            "vpnUsers": "vpnUsers",
            # Additional SET keys that map 1:1 to GET echo keys.
            "macFilter": "macFilter",
            "ipMacBinding": "ipMacBinding",
            "clientIpBinding": "clientIpBinding",
            "clientOpt": "clientOpt",
            "clientTrafficRequire": "clientTrafficRequire",
            "ldap": "ldap",
            "timeRange": "timeRange",
            "mirror": "mirror",
            "ssh": "ssh",
            "mdns": "mdns",
            "virtualWan": "virtualWan",
            "wanLoadBalance": "wanLoadBalance",
            "dsl": "dsl",
            "sdwan": "sdwan",
            "poe": "poe",
            "disableNat": "disableNat",
            "customAcl": "customAcl",
            "wirelessAcl": "wirelessAcl",
            "wirelessUrlFiltering": "wirelessUrlFiltering",
            "ipsWhiteList": "ipsWhiteList",
            "ipsBlackList": "ipsBlackList",
            "signatureList": "signatureList",
            "blockCountry": "blockCountry",
            "countryGroup": "countryGroup",
            "ipv6Group": "ipv6Group",
            "ipPortGroup": "ipPortGroup",
            "ipv6PortGroup": "ipv6PortGroup",
            "domainGroup": "domainGroup",
            "macGroup": "macGroup",
            "radiusProfile": "radiusProfile",
            "common": "common",
            "system": "system",
            "echoServer": "echoServer",
            "dstConfig": "dstConfig",
            "delayEffect": "delayEffect",
            "lanDns": "lanDns",
            "wanBasicSetting": "wanBasicSetting",
            "abnormalDetect": "abnormalDetect",
            "mail": "mail",
            "dnsProxy": "dnsProxy",
            "dpiTraffic": "dpiTraffic",
            "client": "client",
            "portalFreePolicyConfig": "portalFreePolicyConfig",
            "port": "port",
            "speedDuplex": "speedDuplex",
            "bandSteering": "bandSteering",
            "mesh": "mesh",
            "roaming": "roaming",
            "ppskV3": "ppskV3",
            # VoIP / telephony SET → GET echo keys.
            "voipDeviceOsgSetting": "voipDeviceOsgSetting",
            "callForwarding": "callForwarding",
            "callBlocking": "callBlocking",
            "callLog": "callLog",
            "voiceMail": "voiceMail",
            "voiceMailDownload": "voiceMailDownload",
            "voiceMailSettings": "voiceMailSettings",
            "voipViaIpv6": "voipViaIpv6",
            "numberAdvancedSetting": "numberAdvancedSetting",
        }
        for set_key, get_key in _GET_KEY_MAP.items():
            if set_key in self._applied_configs:
                resp[get_key] = deepcopy(self._applied_configs[set_key])
        return resp

    def build_discovery_body(self) -> dict[str, Any]:
        assert self.controller_id is not None
        return build_gateway_discovery_body(
            ip=self.ip,
            model=self.identity.model,
            model_version=self.identity.model_version,
            firmware_version=self.identity.firmware_version,
            certified_version=self.certified_version,
            hardware_version=self.identity.hardware_version,
            controller_id=self.controller_id,
            up_time_seconds=self.uptime_seconds,
            port_num=self.port_num,
            wireless=self.wireless,
            country_code=self.country_code,
        )

    def _vpn_section(self) -> dict[str, Any]:
        """The ``vpn`` section: IPsec, OpenVPN, and PPTP/
        L2TP tunnels. Field types match the controller's expected format:
        ``id`` is Integer (vpnId), ``spi`` is Long, ``direct``/``protocol``/
        ``espAuth``/``ahAuth``/``espEncry`` are String, ``infa`` is Integer
        (interfaceId), ``up``/``down`` are Long bytes, ``upP``/``downP`` are
        Long packets, ``uptime`` is String for PPTP/L2TP / Long for OpenVPN.

        When the controller has pushed a ``vpn`` SET config, the tunnel counts
        and identity come from the pushed config; traffic stats remain
        synthetic. When no config has been pushed, falls back to synthetic
        defaults (2 IPsec, 1 OpenVPN, 1 PPTP)."""
        up = self.uptime_seconds
        # Config-driven IPsec tunnels (from pushed vpn config), or synthetic.
        pushed_ipsec = self._vpn_tunnels.get("ipsec", [])
        if pushed_ipsec:
            ipsec = []
            for t in pushed_ipsec:
                if not isinstance(t, dict):
                    continue
                i = len(ipsec)
                ipsec.append({
                    "id": t.get("id", i + 1),
                    "direct": str(t.get("direct", "1")),
                    "protocol": str(t.get("protocol", "1")),
                    "spi": stats.synthetic_int(self.mac, f"ipsecspi{i}", 1000, 9999),
                    "localTun": t.get("localTun", "10.0.2.2"),
                    "peerTun": t.get("peerTun", f"198.51.{100 + i}.1"),
                    "localSa": t.get("localSa", "10.0.2.2/32"),
                    "remoteSa": t.get("remoteSa", f"198.51.{100 + i}.1/32"),
                    "espEncry": str(t.get("espEncry", "3")),
                    "espAuth": str(t.get("espAuth", "2")),
                    "ahAuth": str(t.get("ahAuth", "2")),
                })
        else:
            ipsec = [{
                "id": i + 1,
                "direct": "1",
                "protocol": "1",
                "spi": stats.synthetic_int(self.mac, f"ipsecspi{i}", 1000, 9999),
                "localTun": "10.0.2.2",
                "peerTun": f"198.51.{100 + i}.1",
                "localSa": "10.0.2.2/32",
                "remoteSa": f"198.51.{100 + i}.1/32",
                "espEncry": "3",
                "espAuth": "2",
                "ahAuth": "2",
            } for i in range(2)]
        # Config-driven OpenVPN tunnels, or synthetic.
        pushed_openvpn = self._vpn_tunnels.get("openvpn", [])
        if pushed_openvpn:
            openvpn = []
            for t in pushed_openvpn:
                if not isinstance(t, dict):
                    continue
                i = len(openvpn)
                openvpn.append({
                    "id": t.get("id", i + 1),
                    "userId": t.get("userId", i + 1),
                    "userName": t.get("userName", f"ovpn-user{i + 1}"),
                    "localIp": t.get("localIp", "10.0.2.2"),
                    "remoteIp": t.get("remoteIp", f"203.0.{113 + i}.1"),
                    "infa": t.get("infa", 1),
                    "dns": t.get("dns", "8.8.8.8"),
                    "up": stats.synthetic_bytes(self.mac, f"ovpnu{i}", up, 50000),
                    "down": stats.synthetic_bytes(self.mac, f"ovpnd{i}", up, 50000),
                    "upP": stats.synthetic_int(self.mac, f"ovpnup{i}", 1, 100),
                    "downP": stats.synthetic_int(self.mac, f"ovpndp{i}", 1, 100),
                    "uptime": int(up),
                })
        else:
            openvpn = [{
                "id": i + 1,
                "userId": i + 1,
                "userName": f"ovpn-user{i + 1}",
                "localIp": "10.0.2.2",
                "remoteIp": f"203.0.{113 + i}.1",
                "infa": 1,
                "dns": "8.8.8.8",
                "up": stats.synthetic_bytes(self.mac, f"ovpnu{i}", up, 50000),
                "down": stats.synthetic_bytes(self.mac, f"ovpnd{i}", up, 50000),
                "upP": stats.synthetic_int(self.mac, f"ovpnup{i}", 1, 100),
                "downP": stats.synthetic_int(self.mac, f"ovpndp{i}", 1, 100),
                "uptime": int(up),
            } for i in range(1)]
        # Config-driven PPTP/L2TP tunnels, or synthetic.
        pushed_pptp = self._vpn_tunnels.get("pptp", [])
        pushed_l2tp = self._vpn_tunnels.get("l2tp", [])
        pushed_tuns = pushed_pptp + pushed_l2tp
        if pushed_tuns:
            tuns = []
            for t in pushed_tuns:
                if not isinstance(t, dict):
                    continue
                i = len(tuns)
                tuns.append({
                    "id": t.get("id", i + 1),
                    "user": t.get("user", f"vpn-user{i + 1}"),
                    "userId": t.get("userId", i + 1),
                    "authType": t.get("authType", 0),
                    "mode": str(t.get("mode", "0")),
                    "localIp": t.get("localIp", "10.0.2.2"),
                    "remoteIp": t.get("remoteIp", f"192.0.{2 + i}.1"),
                    "infa": t.get("infa", 1),
                    "dns": t.get("dns", "8.8.8.8"),
                    "up": stats.synthetic_bytes(self.mac, f"pptpu{i}", up, 30000),
                    "down": stats.synthetic_bytes(self.mac, f"pptpd{i}", up, 30000),
                    "upP": stats.synthetic_int(self.mac, f"pptpup{i}", 1, 100),
                    "downP": stats.synthetic_int(self.mac, f"pptpdp{i}", 1, 100),
                    "uptime": str(int(up)),
                    "loginTime": int(up),
                })
        else:
            tuns = [{
                "id": i + 1,
                "user": f"pptp-user{i + 1}",
                "userId": i + 1,
                "authType": 0,
                "mode": "0",
                "localIp": "10.0.2.2",
                "remoteIp": f"192.0.{2 + i}.1",
                "infa": 1,
                "dns": "8.8.8.8",
                "up": stats.synthetic_bytes(self.mac, f"pptpu{i}", up, 30000),
                "down": stats.synthetic_bytes(self.mac, f"pptpd{i}", up, 30000),
                "upP": stats.synthetic_int(self.mac, f"pptpup{i}", 1, 100),
                "downP": stats.synthetic_int(self.mac, f"pptpdp{i}", 1, 100),
                "uptime": str(int(up)),
                "loginTime": int(up),
            } for i in range(1)]
        # Client-to-site WireGuard tunnels live inside the vpn config
        # (vpn config client_Wireguards) and are reported here as the
        # ``wireguard`` sub-field, distinct
        # from the top-level ``wireguard`` INFORM section.
        c2s_wg = self._vpn_tunnels.get("c2s_wireguard", [])
        if c2s_wg:
            wireguard = []
            for w in c2s_wg:
                if not isinstance(w, dict):
                    continue
                wid = w.get("id", len(wireguard) + 1)
                wireguard.append({
                    "id": wid,
                    "type": w.get("type", 0),
                    "activeClients": w.get("activeClients", 0),
                    "totalClients": w.get("totalClients", 0),
                    "serverAddress": w.get("serverAddress", f"10.9.{wid}.1"),
                    "status": w.get("status", 1),
                    "tunnels": [],
                })
        else:
            wireguard = []
        return {"vpn": {"ipSecs": ipsec, "openvpn": openvpn, "tuns": tuns,
                        "wireguard": wireguard}}

    def _ssl_vpn_section(self) -> dict[str, Any]:
        """The ``sslVpn`` section: active SSL-VPN connections
        and license locks. When the controller has pushed an ``sslVpn`` SET
        config, the connection count and user names come from the pushed
        config; traffic stats remain synthetic."""
        up = self.uptime_seconds
        pushed_users = self._ssl_vpn_connections.get("users", [])
        if pushed_users:
            connections = []
            for u in pushed_users:
                if not isinstance(u, dict):
                    continue
                i = len(connections)
                connections.append({
                    "id": u.get("id", i + 1),
                    "user": u.get("name", u.get("user", f"sslvpn-user{i + 1}")),
                    "vIp": u.get("vIp", f"10.8.{i + 1}.2"),
                    "lIp": "10.0.2.2",
                    "up": stats.synthetic_bytes(self.mac, f"sslvpnu{i}", up, 40000),
                    "down": stats.synthetic_bytes(self.mac, f"sslvpnd{i}", up, 40000),
                    "authType": u.get("authType", 0),
                    "time": int(up),
                })
        else:
            connections = [{
                "id": i + 1,
                "user": f"sslvpn-user{i + 1}",
                "vIp": f"10.8.{i + 1}.2",
                "lIp": "10.0.2.2",
                "up": stats.synthetic_bytes(self.mac, f"sslvpnu{i}", up, 40000),
                "down": stats.synthetic_bytes(self.mac, f"sslvpnd{i}", up, 40000),
                "authType": 0,
                "time": int(up),
            } for i in range(2)]
        locks = [{
            "user": c["user"],
            "ip": c["vIp"],
            "type": 0,
            "rTime": int(up),
            "tTime": int(up) + 3600,
        } for c in connections]
        return {"sslVpn": {"connections": connections, "locks": locks}}

    def _wireguard_section(self) -> dict[str, Any]:
        """The ``wireguard`` section: interface +
        peer/tunnel stats. When the controller has pushed a ``wireguard`` SET
        config, the interface and peer counts come from the pushed config;
        traffic stats remain synthetic."""
        up = self.uptime_seconds
        pushed_ifaces = self._wireguard_peers.get("interfaces", [])
        pushed_peers = self._wireguard_peers.get("peers", [])
        if pushed_ifaces:
            interfaces = []
            for iface in pushed_ifaces:
                if not isinstance(iface, dict):
                    continue
                iface_id = iface.get("id", len(interfaces) + 1)
                iface_peers = [p for p in pushed_peers
                               if isinstance(p, dict) and p.get("interfaceId", iface_id) == iface_id]
                interfaces.append({
                    "id": iface_id,
                    "activePeers": len(iface_peers),
                    "totalPeers": len(iface_peers),
                })
        else:
            interfaces = [{
                "id": 1,
                "activePeers": 2,
                "totalPeers": 5,
            }]
        if pushed_peers:
            tunnels = []
            for p in pushed_peers:
                if not isinstance(p, dict):
                    continue
                i = len(tunnels)
                tunnels.append({
                    "id": p.get("id", i + 1),
                    "ip": p.get("ip", f"10.9.{i + 1}.1"),
                    "port": p.get("port", 51820 + i),
                    "up": stats.synthetic_bytes(self.mac, f"wgu{i}", up, 60000),
                    "upp": stats.synthetic_int(self.mac, f"wgup{i}", 1, 200),
                    "down": stats.synthetic_bytes(self.mac, f"wgd{i}", up, 60000),
                    "downp": stats.synthetic_int(self.mac, f"wgdp{i}", 1, 200),
                    "hshake": int(up),
                    "status": 1,
                })
        else:
            tunnels = [{
                "id": i + 1,
                "ip": f"10.9.{i + 1}.1",
                "port": 51820 + i,
                "up": stats.synthetic_bytes(self.mac, f"wgu{i}", up, 60000),
                "upp": stats.synthetic_int(self.mac, f"wgup{i}", 1, 200),
                "down": stats.synthetic_bytes(self.mac, f"wgd{i}", up, 60000),
                "downp": stats.synthetic_int(self.mac, f"wgdp{i}", 1, 200),
                "hshake": int(up),
                "status": 1,
            } for i in range(2)]
        return {"wireguard": {"connections": tunnels, "interfaces": interfaces}}

    def _ddns_section(self) -> dict[str, Any]:
        """The ``ddns`` section: configured DDNS entries.
        Field types: ``id`` (entryId) is Integer, ``domain`` is
        a list of strings, ``interface`` (interfacePortId) is Integer, ``status``
        is Integer, ``lastUpdated`` is Long.

        When the controller has pushed a ``ddns`` SET config, the entries are
        derived from the pushed DDNS config rules. The
        config entry's ``domain`` is a single String; the INFORM domain
        is a list of strings, so it is wrapped. When no config has been pushed,
        falls back to a single synthetic entry."""
        ddns_cfg = self._applied_configs.get("ddns", {})
        rules = ddns_cfg.get("rules") or []
        if rules:
            ddnss = []
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                domain = rule.get("domain") or ""
                ddnss.append({
                    "id": rule.get("id", len(ddnss) + 1),
                    "domain": [domain] if domain else [],
                    "interface": rule.get("interface", 1),
                    "ip": self.ip,
                    "status": rule.get("status", 1),
                    "statusMsg": "",
                    "lastUpdated": int(self.uptime_seconds),
                })
        else:
            ddnss = [{
                "id": 1,
                "domain": ["gw1.exampleddns.com"],
                "interface": 1,
                "ip": self.ip,
                "status": 1,
                "statusMsg": "",
                "lastUpdated": int(self.uptime_seconds),
            }]
        return {"ddns": {"ddnss": ddnss}}

    def _qos_section(self) -> dict[str, Any]:
        """The ``qos`` section: per-port QoS class stats.
        Each entry has ``port`` (Integer), ``throughputs``
        (list of class entries where each has ``class`` (Integer), ``inbound``
        (Long), ``outbound`` (Long)), and ``voip`` (VoipDataEntry with
        ``inbound``/``outbound`` Longs).

        When the controller has pushed a ``qos`` SET config, the per-class
        throughputs are derived from the pushed QoS config classRules
        (list of class-rule entries, each carrying a ``class`` Integer). Otherwise
        three default classes are reported. Traffic counters stay synthetic."""
        qos_cfg = self._applied_configs.get("qos", {})
        class_rules = qos_cfg.get("classRules") or []
        classes = [r.get("class", i) for i, r in enumerate(class_rules)
                   if isinstance(r, dict)] or [0, 1, 2]
        port_caps = self.profile.DEV_CAP.get("portInfos", [])
        linked = {ln.local_port for ln in self.topology.all_links()}
        data = []
        for cap in port_caps:
            port = cap["port"]
            if port != 1 and port not in linked:
                continue
            throughputs = [{
                "class": cls,
                "inbound": stats.synthetic_int(self.mac, f"qosi{port}c{cls}", 1000, 99999),
                "outbound": stats.synthetic_int(self.mac, f"qoso{port}c{cls}", 1000, 99999),
            } for cls in classes]
            data.append({
                "port": port,
                "throughputs": throughputs,
                "voip": {
                    "inbound": stats.synthetic_int(self.mac, f"voipi{port}", 0, 9999),
                    "outbound": stats.synthetic_int(self.mac, f"voipo{port}", 0, 9999),
                },
            })
        return {"qos": {"data": data}}

    def _ct_table_section(self) -> dict[str, Any]:
        """The ``ctTable`` section: connection-tracking
        session counts."""
        ct_max = 20000
        return {"ctTable": {
            "ctMax": ct_max,
            "ctNum": stats.synthetic_int(self.mac, "ctnum", 100, ct_max),
        }}

    def _portforward_section(self) -> dict[str, Any]:
        """The ``portforward`` section: UPnP +
        user port-forwarding entries. Field types:
        ``id`` (entryId) is Integer, ``proto`` (protocol) is Integer,
        ``infa`` (interfaceWanPortId) is a list of integers, ``export`` (externalPort)
        is String, ``inip`` (internalIp) is String, ``inport`` (internalPort)
        is String, ``bts`` (bytes) is Long, ``pkts`` (packets) is Long, ``dura``
        (leaseDuration) is Long.

        When the controller has pushed a ``portforward`` SET config, the user
        forwards are derived from the pushed port-forward config settings
        (list of forwarding entries with ``ipaddr``/``externalPort``/
        ``internalPort``/``protocol``/``interface``). UPnP entries stay synthetic."""
        pf_cfg = self._applied_configs.get("portforward", {})
        settings = pf_cfg.get("settings") or []
        if settings:
            users = []
            for entry in settings:
                if not isinstance(entry, dict):
                    continue
                i = len(users)
                users.append({
                    "id": entry.get("id", i + 1),
                    "name": entry.get("name", f"fwd{i + 1}"),
                    "proto": entry.get("protocol", 0),
                    "inip": entry.get("ipaddr", "10.0.2.2"),
                    "inport": str(entry.get("internalPort", 8080 + i)),
                    "infa": entry.get("interface") or [1],
                    "export": str(entry.get("externalPort", 8080 + i)),
                    "bts": stats.synthetic_int(self.mac, f"pfbtns{i}", 0, 9999),
                    "pkts": stats.synthetic_int(self.mac, f"pfpkts{i}", 0, 99999),
                    "dura": int(self.uptime_seconds),
                })
        else:
            users = [{
                "id": i + 1,
                "name": f"fwd{i + 1}",
                "proto": i % 2,
                "inip": "10.0.2.2",
                "inport": str(8080 + i),
                "infa": [1],
                "export": str(8080 + i),
                "bts": stats.synthetic_int(self.mac, f"pfbtns{i}", 0, 9999),
                "pkts": stats.synthetic_int(self.mac, f"pfpkts{i}", 0, 99999),
                "dura": int(self.uptime_seconds),
            } for i in range(2)]
        upnps = [{
            "id": i + 1,
            "name": f"upnp{i + 1}",
            "proto": i % 2,
            "inip": "10.0.2.2",
            "inport": str(9000 + i),
            "infa": [1],
            "export": str(9000 + i),
            "bts": stats.synthetic_int(self.mac, f"upnpbts{i}", 0, 9999),
            "pkts": stats.synthetic_int(self.mac, f"upnppkts{i}", 0, 99999),
            "dura": int(self.uptime_seconds),
        } for i in range(1)]
        return {"portforward": {"users": users, "upnps": upnps}}

    def _network_traffic_section(self) -> dict[str, Any]:
        """The ``networkTraffic`` section: per-VLAN
        network traffic counters."""
        up = self.uptime_seconds
        network_traffics = [{
            "ip": "10.0.2.0",
            "ip6": "",
            "rx": stats.synthetic_bytes(self.mac, "ntrx", up, 80000),
            "tx": stats.synthetic_bytes(self.mac, "nttx", up, 80000),
            "vlan": 1,
            "dhcpsUtil": stats.synthetic_int(self.mac, "dhcpu", 0, 100),
            "dhcps6Util": 0,
            "dhcpsOffer": stats.synthetic_int(self.mac, "dhcpo", 10, 200),
            "dhcps6Offer": 0,
        }]
        return {"networkTraffic": {"networkTraffics": network_traffics}}

    def _ips_threat_section(self) -> dict[str, Any]:
        """The ``ipsThreat`` section (``IpsThreatInfo``): IPS threat log.
        When the controller has pushed an ``ips`` SET config with IPS enabled,
        a few synthetic threat events are reported (seeded by the configured
        ``categoryIds``). When IPS is disabled (or no config pushed), the
        section is omitted entirely — a real device does not report threats
        when IPS is off, and emitting an empty ``data`` list would leave the
        IPS tab in a misleading "no threats" state indistinguishable from
        IPS-disabled."""
        ips_cfg = self._applied_configs.get("ips", {})
        if not ips_cfg:
            # No IPS config pushed yet — report a couple of default synthetic
            # threats so the IPS tab is non-empty during initial adoption.
            ips_enabled = True
            category_ids = [1]
        else:
            enable = ips_cfg.get("enable")
            ips_enabled = bool(enable) if enable is not None else True
            category_ids = ips_cfg.get("categoryIds") or [1]
        if not ips_enabled:
            return {}
        now = int(self.uptime_seconds)
        data = [{
            "time": now - i * 60,
            "severity": 2,
            "threatDescription": "Synthetic threat event",
            "categoryId": category_ids[i % len(category_ids)],
            "classDescription": "Test",
            "dataUsage": stats.synthetic_int(self.mac, f"ipsd{i}", 0, 9999),
            "srcIp": f"192.168.{i}.1",
            "dstIp": self.ip,
            "srcCountry": "",
            "dstCountry": "",
            "protocol": "TCP",
            "sid": 2000000 + i,
            "classification": "misc-activity",
        } for i in range(2)]
        return {"ipsThreat": {"data": data}}

    # -- New INFORM sections (v6.2.14.11) --

    def _sdwan_section(self) -> dict[str, Any]:
        """The ``sdwan`` section: SD-WAN tunnel stats.
        Has a single field ``tuns`` (list of tunnel entries);
        each entry has only ``remoteTun`` (String). Only emitted
        on models that support SD-WAN."""
        tuns = [{
            "remoteTun": f"203.0.{113 + i}.1",
        } for i in range(2)]
        return {"sdwan": {"tuns": tuns}}

    def _virtual_wan_section(self) -> dict[str, Any]:
        """The ``virtualWanInfo`` section (``VirtualWanInfo``): virtual WAN
        entries for multi-WAN / load-balance models. ``VirtualWanInfo`` has
        ``virtualWans`` (list of virtual WAN entries); each entry has
        ``virtualWanEntryId`` (Integer), ``ip`` (String), ``ip2`` (String),
        ``status`` (Integer), ``internetState`` (Integer), ``onlineDetection``
        (Integer), ``mac`` (String), and nested ``ipv4`` (VirtualWanIpv4Entry
        with ``gw``/``gw2``/``priDns``/``sndDns``/``priDns2``/``sndDns2``).
        Only emitted on models that support discrete WAN or load balancing."""
        port_macs = _derive_port_macs(self.mac, max(0, self.port_num - 1))
        virtual_wans = []
        for i in range(min(2, len(port_macs))):
            virtual_wans.append({
                "virtualWanEntryId": i + 1,
                "ip": f"10.0.{i + 2}.2" if i == 0 else self.ip,
                "ip2": "",
                "status": 1,
                "internetState": 1,
                "onlineDetection": 1,
                "mac": port_macs[i]["defMac"],
                "ipv4": {
                    "gw": "10.0.2.2",
                    "gw2": "",
                    "priDns": "8.8.8.8",
                    "sndDns": "8.8.4.4",
                    "priDns2": "",
                    "sndDns2": "",
                },
            })
        return {"virtualWanInfo": {"virtualWans": virtual_wans}}

    def _lte_section(self) -> dict[str, Any]:
        """The ``lte`` section: LTE APN configuration.
        Has ``selectedApns`` (list of APN configs) and
        ``selectedApns1`` (list of APN configs for SIM2). Each APN config has
        ``port`` (Integer), ``apns`` (list of APN profile entries),
        ``cleanDefaultProfiles`` (Integer), ``supportSMS`` (Integer).
        Only emitted on models that support LTE."""
        apn_configs = [{
            "port": 1,
            "apns": [{
                "apn": "internet",
                "user": "",
                "password": "",
                "authType": 0,
            }],
            "cleanDefaultProfiles": 0,
            "supportSMS": 1,
        }]
        return {"lte": {"selectedApns": apn_configs, "selectedApns1": []}}

    def _client_traffic_section(self) -> dict[str, Any]:
        """The ``clientTraffic`` section: per-client
        traffic counters. Has ``traffic``
        (list of entries); each entry has ``mac`` (String),
        ``tx`` (Long), ``rx`` (Long), ``txP`` (Long), ``rxP`` (Long)."""
        up = self.uptime_seconds
        traffic = []
        for client in self.reported_clients:
            rx, tx = client.traffic(up)
            traffic.append({
                "mac": client.mac,
                "tx": tx,
                "rx": rx,
                "txP": stats.synthetic_packets(tx),
                "rxP": stats.synthetic_packets(rx),
            })
        return {"clientTraffic": {"traffic": traffic}}

    def _abnormal_dt_section(self) -> dict[str, Any]:
        """The ``abnormalDt`` section:
        abnormal-detection events. Has
        ``access`` (list of access entries) and ``dev``
        (list of device entries).
        Emits empty lists by default (no abnormal events in a healthy lab)."""
        return {"abnormalDt": {"access": [], "dev": []}}

    def _event_inform_section(self) -> dict[str, Any]:
        """The ``eventInform`` section (``List[EventInform]``): device events.
        Each ``EventInform`` has ``eid`` (String), ``timestamp`` (Long),
        ``data`` (Map). Emits an empty list by default."""
        return {"eventInform": []}

    def _acl_hit_section(self) -> dict[str, Any]:
        """The ``aclHit`` section: ACL hit
        counters. Each entry has ``id`` (Integer) and
        ``hitCount`` (Integer). Derives from the pushed ACL config if present,
        otherwise emits an empty list."""
        acl_config = self._applied_configs.get("acl", {})
        rules = acl_config.get("rules") or acl_config.get("acls") or []
        acl_hit = []
        for rule in rules:
            if isinstance(rule, dict):
                rule_id = rule.get("id", 0)
                if isinstance(rule_id, int):
                    acl_hit.append({
                        "id": rule_id,
                        "hitCount": stats.synthetic_int(
                            self.mac, f"aclhit{rule_id}", 0, 9999),
                    })
        return {"aclHit": acl_hit}

    def _portal_duration_section(self) -> dict[str, Any]:
        """The ``portalDuration`` section: portal
        authentication duration stats. Has
        ``portalDurations`` (list of entries); each entry has
        ``client`` (String), ``start`` (Long), ``dura`` (Long).
        Emits an empty list (no portal configured by default)."""
        return {"portalDuration": {"portalDurations": []}}

    def _applications_traffic_section(self) -> dict[str, Any]:
        """The ``applicationsTraffic`` section:
        application-level traffic categorisation.
        has ``traffic`` (List) and ``block`` (List). Emits empty lists
        (application traffic requires DPI which is a controller-side feature)."""
        return {"applicationsTraffic": {"traffic": [], "block": []}}

    def _poe_section(self) -> dict[str, Any]:
        """The ``poe`` section: PoE budget and per-port
        draw. Has ``limit`` (Double), ``remain`` (Double),
        ``percent`` (Double), ``fan`` (Integer), ``ports``
        (list of per-port entries). Each per-port entry has ``port``
        (Integer), ``state`` (Integer), ``p`` (Double), ``u`` (Double),
        ``i`` (Double). Only emitted on models with PoE-out ports."""
        port_caps = self.profile.DEV_CAP.get("portInfos", [])
        poe_ports = []
        for cap in port_caps:
            if cap.get("supportPoe"):
                port = cap["port"]
                poe_ports.append({
                    "port": port,
                    "state": 1,
                    "p": 15.0,
                    "u": 48.0,
                    "i": 0.31,
                })
        return {"poe": {
            "limit": 30.0,
            "remain": 30.0 - len(poe_ports) * 15.0,
            "percent": 100.0 - len(poe_ports) * 50.0,
            "fan": 1,
            "ports": poe_ports,
        }}

    def _monitor_section(self) -> dict[str, Any]:
        """The ``monitor`` section (``MonitorLink``): link-monitoring status.
        ``MonitorLink`` has a single field ``link`` (Integer). Emits 1
        (link up) by default."""
        return {"monitor": {"link": 1}}

    def _last_cfg_result_section(self) -> dict[str, Any]:
        """The ``lastCfgResult`` section: the result
        of the last config push. Echoes the per-feature ack sub-objects from
        the last SET response (if any)."""
        if self._last_set_response:
            return {"lastCfgResult": deepcopy(self._last_set_response)}
        return {}

    def _cfg_results_section(self) -> dict[str, Any]:
        """The ``cfgResults`` section: a rolling
        history of recent SET responses. Has
        ``setResults`` (list of response entries). The history is
        accumulated in ``build_set_response`` (capped at 10 entries) so the
        controller can display the recent config-push results."""
        return {"cfgResults": {"setResults": deepcopy(self._cfg_result_history)}}

    # -- wireless sections (WiFi-capable gateway models only) ------------

    # Per-radio hardware defaults for WiFi-capable gateways (e.g. ER706W).
    # Same structure as the AP's ``_RADIOS`` but simplified for gateway use.
    _GW_RADIOS = {
        0: {"suffix": "2G", "band": "2.4G", "ch": 6, "bw": 20, "rdMode": "11ng"},
        1: {"suffix": "5G", "band": "5G", "ch": 36, "bw": 80, "rdMode": "11ac"},
    }

    def _wireless_sections(self) -> dict[str, Any]:
        """Wireless INFORM sections for WiFi-capable gateways (``wireless > 0``).

        Emits per-radio ``wSettings_<band>G`` (radio settings: channel,
        channel-width, txPower, radio mode), ``radioTraffic_<band>G`` (per-radio
        tx/rx bytes + client count), and ``ssidStats_<band>G`` (per-SSID stats),
        plus ``mesh`` and ``roaming`` sections. The shapes mirror the AP's
        wireless INFORM sections but are carried in the gateway's
        gateway INFORM body. Values are synthetic-but-deterministic.
        See doc/DEVICE_PROTOCOL.md §7.8."""
        extra: dict[str, Any] = {}
        up = self.uptime_seconds
        for radio_id, radio in self._GW_RADIOS.items():
            suffix = radio["suffix"]
            # wSettings: radio settings (channel, channel-width, txPower, rdMode).
            extra[f"wSettings_{suffix}"] = {
                "rid": radio_id,
                "ch": radio["ch"],
                "bw": radio["bw"],
                "txPower": 20,
                "rdMode": radio["rdMode"],
                "radioEnable": True,
            }
            # radioTraffic: per-radio aggregate traffic + connected client count.
            rx_rate = stats.synthetic_rate_bps(self.mac, f"gwrx{radio_id}", 1, 100)
            tx_rate = stats.synthetic_rate_bps(self.mac, f"gwtx{radio_id}", 1, 100)
            extra[f"radioTraffic_{suffix}"] = {
                "rid": radio_id,
                "rx": stats.synthetic_bytes(self.mac, f"gwrxb{radio_id}", up, rx_rate),
                "tx": stats.synthetic_bytes(self.mac, f"gwtxb{radio_id}", up, tx_rate),
                "rxRate": rx_rate,
                "txRate": tx_rate,
                "clientNum": stats.synthetic_int(self.mac, f"gwcn{radio_id}", 0, 5),
            }
            # ssidStats: per-SSID stats (one synthetic SSID per radio).
            ssid_rx = stats.synthetic_bytes(self.mac, f"gwssidrx{radio_id}", up, rx_rate // 2)
            ssid_tx = stats.synthetic_bytes(self.mac, f"gwssidtx{radio_id}", up, tx_rate // 2)
            extra[f"ssidStats_{suffix}"] = [{
                "ssid": f"Gateway-WiFi-{suffix}",
                "bssid": stats.synthetic_bssid(self.mac, radio_id, f"gw:{radio_id}"),
                "rx": ssid_rx,
                "tx": ssid_tx,
                "rxRate": rx_rate // 2,
                "txRate": tx_rate // 2,
                "clientNum": stats.synthetic_int(self.mac, f"gwssidcn{radio_id}", 0, 3),
            }]
        # mesh: inactive for a wired gateway with integrated WiFi (not a mesh node).
        extra["mesh"] = {
            "status": 0,
            "meshRid": 0,
            "isolatedAPs": [],
            "childAPs": [],
            "candidateParents": [],
        }
        # roaming: gateway is the roaming controller; report a minimal inactive state.
        extra["roaming"] = {
            "enable": False,
            "mode": 0,
        }
        return extra

    def _voip_section(self) -> dict[str, Any]:
        """The VoIP / telephony INFORM section (``callLogInform``).

        The gateway's INFORM body carries a ``callLogInform`` field
        (``CallLogInform`` from ``inform/ap/voip/``) when the controller has
        pushed a ``callLog`` SET config enabling call logging. The emulator
        reports synthetic call-log entries derived from the pushed config
        (number of ports from ``voipDeviceOsgSetting``). When no VoIP config
        has been pushed, the section is omitted (the gateway has no VoIP
        hardware). See doc/DEVICE_PROTOCOL.md §7.8.

        ``CallLogInform`` wraps a list of ``CallLogEvent`` entries, each with:
        ``port`` (Integer), ``callType`` (Integer: 1=incoming, 2=outgoing,
        3=missed), ``phoneNumber`` (String), ``duration`` (Long, seconds),
        ``timestamp`` (Long, epoch millis).
        """
        voip_cfg = self._applied_configs.get("voipDeviceOsgSetting", {})
        if not isinstance(voip_cfg, dict) or not voip_cfg:
            return {}
        port_settings = voip_cfg.get("portSettings") or []
        if not isinstance(port_settings, list) or not port_settings:
            return {}
        up = self.uptime_seconds
        logs = []
        for port_entry in port_settings:
            if not isinstance(port_entry, dict):
                continue
            port = port_entry.get("port", 1)
            # Generate 0-2 synthetic call log entries per port.
            call_count = stats.synthetic_int(self.mac, f"voipcalls{port}", 0, 2)
            for i in range(call_count):
                call_type = stats.synthetic_int(self.mac, f"voipct{port}:{i}", 1, 3)
                logs.append({
                    "port": port,
                    "callType": call_type,
                    "phoneNumber": f"555{stats.synthetic_int(self.mac, f'voipnum{port}:{i}', 1000, 9999)}",
                    "duration": stats.synthetic_int(self.mac, f"voipdur{port}:{i}", 10, 3600),
                    "timestamp": int((up - stats.synthetic_int(self.mac, f"voipts{port}:{i}", 0, max(1, up))) * 1000),
                })
        return {"callLogInform": {"logs": logs}}

    def _extra_device_info(self) -> dict[str, Any]:
        # Gateways report a "<model> v<hw>" hwVer plus MAC/port identity fields
        # and the model-specific identity fields from the profile's
        # DEVICE_INFO_TEMPLATE (encryptedHwId/hwId/oemId/modelId/speeds/mask).
        # These are merged on top of the common short-name deviceInfo set during
        # negotiation device info AND in the INFORM deviceInfo
        # (INFORM device info). The INFORM-only fields (sm/cerVer/ipv6List/
        # fac/temp/fan/rps/txRate/rxRate) are added separately by
        # ``manage_inform_body`` so they don't leak into the negotiation body
        # (where they can stall the controller's negotiation parser).
        return {
            "hwVer": f"{self.identity.model} v{self.identity.hardware_version}",
            "lanMac": self.mac,
            "wanDefaultMacs": _derive_port_macs(self.mac, max(0, self.port_num - 1)),
            # Negotiation identity fields (from the profile template). The
            # template already carries these, but we re-assert them here so
            # they survive the ``manage_device_info`` base update and remain
            # present in the negotiated deviceInfo.
            "encryptedHwId": self.profile.DEVICE_INFO_TEMPLATE.get("encryptedHwId", ""),
            "hwId": self.profile.DEVICE_INFO_TEMPLATE.get("hwId", ""),
            "oemId": self.profile.DEVICE_INFO_TEMPLATE.get("oemId", ""),
            "encryptedOemId": self.profile.DEVICE_INFO_TEMPLATE.get("encryptedOemId", ""),
            "modelId": self.profile.DEVICE_INFO_TEMPLATE.get("modelId", 0),
            "speeds": self.profile.DEVICE_INFO_TEMPLATE.get("speeds", [1, 2, 3]),
            "mask": self.profile.DEVICE_INFO_TEMPLATE.get("mask", "255.255.255.0"),
        }

    def _inform_device_info_extra(self) -> dict[str, Any]:
        """INFORM-only device info fields (Overview tab) not present
        in the negotiation device info. These are merged into the
        INFORM deviceInfo by ``manage_inform_body`` but NOT into the negotiation
        deviceInfo, because the controller's negotiation parser does not expect
        them and adding them can stall the adoption handshake."""
        up = self.uptime_seconds
        wan_rx = stats.synthetic_rate_bps(self.mac, "gwrx1", 20, 400)
        wan_tx = stats.synthetic_rate_bps(self.mac, "gwtx1", 5, 120)
        info: dict[str, Any] = {
            "sm": self.mac.replace("-", "").lower(),
            "cerVer": self.certified_version,
            "ipv6List": [],
            "fac": self.profile.DEVICE_INFO_TEMPLATE.get("fac", False),
            # device info temp is Integer (not Double/float).
            "temp": stats.synthetic_int(self.mac, "gwtemp", 30, 55),
            "fan": [],
            "rps": [],
            # device info txRate/rxRate are Integer (not Long).
            # Send the instantaneous WAN rate (bps) as an int, not accumulated
            # bytes (which would overflow int range at large uptimes).
            "txRate": int(wan_tx),
            "rxRate": int(wan_rx),
        }
        # Populate ipv6List when the model supports IPv6 and the INFORM
        # portInfo reports a WAN IPv6 address.
        if getattr(self.profile, "SUPPORTS_IPV6", False):
            try:
                suffix = int(self.mac.replace("-", "")[-2:], 16) % 256
            except ValueError:
                suffix = 1
            info["ipv6List"] = [f"2001:db8::1{suffix}"]
        return info

    def manage_inform_body(self) -> dict[str, Any]:
        """Build the full periodic INFORM body. Overrides the base to add the
        INFORM-only device info fields (sm/cerVer/ipv6List/fac/temp/
        fan/rps/txRate/rxRate) to the deviceInfo — these are NOT in the
        negotiation device info and must not leak into the
        negotiation body."""
        from ..protocol import adoption

        device_info = self.manage_device_info()
        device_info.update(self._inform_device_info_extra())
        body = adoption.build_inform_body(device_info)
        body.update(self.manage_inform_extra())
        return body
