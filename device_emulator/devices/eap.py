"""Emulated access point."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .. import stats
from ..protocol import constants
from ..protocol.discovery import build_ap_discovery_body
from . import eap_profile, topology
from .base import Device, format_uptime

# Per-radio hardware defaults: (INFORM key suffix, channel, channel width MHz,
# radio mode). The suffix (2.4G/5G band assignment) is a hardware fact and is
# always used. channel/bw/txPower are controller-pushed via the
# ``wirelessBasic_<band>G`` SET key; the values here
# are the synthetic pre-push fallback (same role as _DEFAULT_SSID for the
# SSID). rdMode is reported as a string ("11ng"/"11ac"); the controller pushes
# an Integer ``wirelessMode`` whose ->string mapping is not yet confirmed, so
# rdMode stays as this fallback until that mapping is confirmed.
_RADIOS = {
    0: {
        "suffix": "2G", "band": "2.4G", "ch": 6, "bw": 20, "rdMode": "11ng",
        "channels": ((2412, 1), (2437, 6), (2462, 11)),
    },
    1: {
        "suffix": "5G", "band": "5G", "ch": 36, "bw": 80, "rdMode": "11ac",
        "channels": ((5180, 36), (5200, 40), (5220, 44), (5240, 48)),
    },
}

# Synthetic SSID reported before the controller pushes any WLAN/SSID config
# (the controller shows ``undefined`` until a configured WLAN matches, by
# design — see doc/DEVICE_PROTOCOL.md §7.8). Not per-instance state.
_DEFAULT_SSID = "Lab-WiFi"


@dataclass
class EapDevice(Device):
    # Discovery-time wireless-mesh link status. Must stay False for a wired AP:
    # a True value makes the controller treat it as a mesh AP that needs an
    # uplink AP and refuse adoption ("No available uplink APs"). The radios are
    # reported as operational post-adoption via manage_device_info instead.
    wireless_linked: bool = False
    cpu_util: int = 5
    mem_util: int = 30
    # Number of Ethernet LAN ports the AP has (EAP245 = 1). The single port
    # serves as the wired uplink on a wired AP; multi-port APs may have
    # additional downlink ports. Drives the ``portStatus`` / ``uplinkPortStatus``
# INFORM sections (downlink / uplink port status).
    lan_ports: int = 1
    # Whether this AP is PoE-powered (a PoE *consumer*). When true the AP
    # reports a ``poeInform`` section (PoE status) with its received power
    # budget. The ``powerControl`` component is always advertised in
    # ``components_v2`` so the controller expects this section.
    supports_poe: bool = True
    # Whether the AP uses a wireless mesh uplink (rather than wired). When true
    # the ``mesh`` section (mesh info) reports an active mesh link to a
    # parent AP; when false it reports an inactive/non-mesh state.
    wireless_uplink: bool = False
    # Number of synthetic wireless clients to simulate on this AP (0-5,
    # validated in registry.build_device). This is an emulator simulation
    # input, not a controller-owned setting: the SSID each client reports
    # still comes only from the controller's SET push (see
    # _radio_client_assignments / _active_ssids_for_radio).
    wireless_client_count: int = 5

    # Radio ids this AP hardware supports (keys of ``_RADIOS``), exposed so
    # client synthesis (clients.py) does not duplicate radio knowledge.
    SUPPORTED_RADIO_IDS: ClassVar[tuple[int, ...]] = tuple(_RADIOS)

    # -- WLAN / radio config (controller-pushed) -------------------------
    # The SSID and radio settings an AP reports are NOT device-side properties:
    # the controller pushes them via SET keys (see
    # /memories/repo/ap-wlan-ssid-set-dtos.md). The AP captures the pushes in
    # build_set_response and reports
    # the applied values back in INFORM. Synthetic pre-push fallbacks
    # (``_DEFAULT_SSID``, ``_RADIOS``) keep the INFORM well-formed before any
    # config is pushed; the controller shows ``undefined`` until a configured
    # WLAN/radio matches, by design (see doc/DEVICE_PROTOCOL.md §7.8).
    #
    # Captured per radio id (0=2.4G, 1=5G, 2=5G2, 3=6G):
    #   ssid_*G        -> SSID config -> _applied_ssid_configs (raw) /
    #                     _active_ssids_by_radio (normalized effective profiles)
    #   wirelessBasic_*G -> wireless basic config -> _applied_wireless_basic
    #   wirelessAdv_*G   -> wireless adv config   -> _applied_wireless_adv
    _applied_ssid_configs: dict[int, dict[str, Any]] = field(init=False, default_factory=dict)
    _active_ssids_by_radio: dict[int, list[dict[str, Any]]] = field(init=False, default_factory=dict)
    _applied_wireless_basic: dict[int, dict[str, Any]] = field(init=False, default_factory=dict)
    _applied_wireless_adv: dict[int, dict[str, Any]] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.device_type = constants.DEVICE_TYPE_AP
        self.protocol_version = eap_profile.PROTOCOL_VERSION

    def manage_dev_cap(self) -> dict[str, Any]:
        # Advertise terminal (RTTY) support so the controller's Tools →
        # Terminal device picker includes this AP. The controller checks
        # `apImage.bm()` (mapped from `devCap.supportTerminal` /
        # `deviceMisc.supportTerminal`) and the frontend additionally
        # checks `devCap.terminalSupport`. See doc/DEVICE_PROTOCOL.md §10.6.
        return {"supportTerminal": True, "terminalSupport": True}

    def build_manage_negotiation_body(self, controller_id: str) -> dict[str, Any]:
        body = super().build_manage_negotiation_body(controller_id)
        body["channelInfo"] = [
            {
                "radioId": radio_id,
                "band": radio["band"],
                "channelList": [
                    {
                        "fr": frequency,
                        "vl": channel,
                        "mPow": 23,
                        "cFlag": 0,
                        "dFlag": 0,
                        "lm": 0,
                    }
                    for frequency, channel in radio["channels"]
                ],
            }
            for radio_id, radio in _RADIOS.items()
        ]
        body["radioCap"] = [
            {"radioId": radio_id, "supportSsidNum": 8}
            for radio_id in _RADIOS
        ]
        return body

    def _radio_clients(self, radio_id: int) -> list[Any]:
        return [client for client, _profile in self._radio_client_assignments(radio_id)]

    def _agg_rates(self) -> tuple[int, int]:
        """(rxRate, txRate) in bytes/sec, aggregated over wireless clients."""
        clients = [c for c in self.reported_clients
                   if not c.wireless or c in self._radio_clients(c.radio_id)]
        down = sum(getattr(c, "down_bps", 0) for c in clients)
        up = sum(getattr(c, "up_bps", 0) for c in clients)
        return down // 8, up // 8

    def _fallback_ssid_profile(self, radio_id: int) -> dict[str, Any]:
        """The single virtual SSID profile reported before the controller has
        ever pushed a ``ssid_<band>G`` SET for this radio. Never stored as
        controller-applied state; see ``_active_ssids_for_radio``."""
        return {
            "ssidName": _DEFAULT_SSID,
            "id": None,
            "index": None,
            "vlanId": 1,
            "portal": False,
            "ssidIsolation": False,
            "ssidBcast": True,
            "profile_key": f"fallback-{radio_id}",
        }

    def _active_ssids_for_radio(self, radio_id: int) -> list[dict[str, Any]]:
        """Effective SSID profiles the AP should report for ``radio_id``, in
        controller order. Three states:
        - No SET ever received for this radio -> one fallback profile.
        - SET received with active profiles -> those profiles, in order.
        - SET received but no active profiles remain (e.g. all SSIDs deleted)
          -> an empty list; the fallback is never resurrected."""
        if radio_id not in self._applied_ssid_configs:
            return [self._fallback_ssid_profile(radio_id)]
        return self._active_ssids_by_radio.get(radio_id, [])

    def _radio_client_assignments(self, radio_id: int) -> list[tuple[Any, dict[str, Any]]]:
        """The single source of truth assigning wireless clients to SSID
        profiles for a radio: filters disabled radios and radios with no
        active SSIDs, then round-robins clients (stably ordered by MAC) across
        the active profiles in controller order. Used by ``_client_stats``,
        ``_ssid_stats``, ``_radio_clients`` and aggregate rate calculation so
        client counts and traffic totals cannot diverge."""
        if not self._radio_enabled(radio_id):
            return []
        profiles = self._active_ssids_for_radio(radio_id)
        if not profiles:
            return []
        clients = sorted(
            (c for c in self.reported_clients if c.wireless and c.radio_id == radio_id),
            key=lambda c: c.mac,
        )
        return [(client, profiles[i % len(profiles)]) for i, client in enumerate(clients)]

    def _radio_enabled(self, radio_id: int) -> bool:
        """Whether the controller-pushed radio config leaves this radio on."""
        return self._applied_wireless_basic.get(radio_id, {}).get("radioEnable") is not False

    # Per-radio SET-key groups the AP captures (radio_id -> SET key suffix).
    # ``ssid`` -> SSID config, ``wirelessBasic`` -> wireless basic config,
    # ``wirelessAdv`` -> wireless adv config (all per-radio, ``<band>G`` suffix).
    _RADIO_SET_KEYS: ClassVar[tuple[tuple[int, str, str], ...]] = (
        (0, "ssid_2G", "ssid"), (0, "wirelessBasic_2G", "wirelessBasic"),
        (0, "wirelessAdv_2G", "wirelessAdv"),
        (1, "ssid_5G", "ssid"), (1, "wirelessBasic_5G", "wirelessBasic"),
        (1, "wirelessAdv_5G", "wirelessAdv"),
        (2, "ssid_5G2", "ssid"), (2, "wirelessBasic_5G2", "wirelessBasic"),
        (2, "wirelessAdv_5G2", "wirelessAdv"),
        (3, "ssid_6G", "ssid"), (3, "wirelessBasic_6G", "wirelessBasic"),
        (3, "wirelessAdv_6G", "wirelessAdv"),
    )

    def build_set_response(self, req_body: dict[str, Any]) -> dict[str, Any]:
        """Acknowledge an AP SET_REQUEST and capture the controller-pushed WLAN /
        radio config so the AP reports the applied values in its next INFORM.

        Captures three per-radio SET-key groups (see
        /memories/repo/ap-wlan-ssid-set-dtos.md):
        - ``ssid_<band>G`` (SSID config = ``{radioId, ssid: [entry, ...]}``;
          each entry carries ``ssidName``) -> normalized into effective
          active profiles by ``_apply_ssid_config``, driving ``clients[].ssid``
          / ``ssidStats_*`` (see §7.8).
        - ``wirelessBasic_<band>G`` (wireless basic config: ``channel`` /
          ``chanWidth`` / ``txPower``) -> drives ``wSettings_<band>G``
          ``ch`` / ``bw`` / ``txPower``.
        - ``wirelessAdv_<band>G`` (wireless adv config) -> captured for GET
          round-trip (no current INFORM field consumes it)."""
        resp = super().build_set_response(req_body)
        for radio_id, set_key, group in self._RADIO_SET_KEYS:
            cfg = req_body.get(set_key)
            if not isinstance(cfg, dict):
                continue
            if group == "ssid":
                self._applied_ssid_configs[radio_id] = deepcopy(cfg)
                self._apply_ssid_config(radio_id, cfg)
            elif group == "wirelessBasic":
                self._applied_wireless_basic[radio_id] = deepcopy(cfg)
            elif group == "wirelessAdv":
                self._applied_wireless_adv[radio_id] = deepcopy(cfg)
        return resp

    def build_get_response(self, req_body: dict[str, Any]) -> dict[str, Any]:
        """Respond to an AP GET_REQUEST by echoing the applied WLAN / radio config
        under the AP config keys so the controller's WLAN / Radio config
        tabs show the configured values."""
        resp = super().build_get_response(req_body)
        for radio_id, set_key, group in self._RADIO_SET_KEYS:
            cfg = (
                self._applied_ssid_configs if group == "ssid"
                else self._applied_wireless_basic if group == "wirelessBasic"
                else self._applied_wireless_adv
            ).get(radio_id)
            if cfg is not None:
                resp[set_key] = deepcopy(cfg)
        return resp

    # SSID entry ``operation`` CRUD semantics. The controller's
    # operation enum uses: 1 = add, 2 = delete, 3 = update/modify.
    # A missing/0 operation on a full-config-sync SET is treated as a
    # snapshot entry (the entry is authoritative, neither add nor delete).
    # See doc/DEVICE_PROTOCOL.md §7.8 and /memories/repo/ap-wlan-ssid-set-dtos.md.
    _SSID_OP_ADD = 1
    _SSID_OP_DELETE = 2
    _SSID_OP_UPDATE = 3

    def _apply_ssid_config(self, radio_id: int, ssid_config: dict[str, Any]) -> None:
        """Normalize a pushed SSID config (``{radioId, ssid: [entry, ...]}``)
        into the effective active SSID profile list for ``radio_id``, stored in
        ``_active_ssids_by_radio``.

        Processes each entry's ``operation`` field with proper CRUD semantics:
        - ``operation == 1`` (add): add a new SSID profile (by id/index/name).
        - ``operation == 2`` (delete): remove the matching SSID profile.
        - ``operation == 3`` (update): update the matching SSID profile's
          fields (ssidName/vlanId/portal/ssidIsolation/ssidBcast), preserving
          the old profile_key so client assignments stay stable.
        - ``operation`` missing/0 (snapshot): treat the SET as a full
          authoritative snapshot — the entry list replaces the radio's
          profiles (this is the full-config-sync behaviour confirmed live
          against the controller 6.2.14.11).

        A hidden SSID (``ssidBcast=false``) is still active. An entry with an
        empty/missing ``ssidName`` is skipped (it cannot be a valid SSID).
        See doc/DEVICE_PROTOCOL.md §7.8."""
        ssid_list = ssid_config.get("ssid")
        if not isinstance(ssid_list, list):
            return

        # Determine whether this SET is a CRUD delta (any entry has a non-zero
        # operation) or a full snapshot (all operations are missing/0).
        has_crud_ops = any(
            isinstance(e, dict) and e.get("operation") in (
                self._SSID_OP_ADD, self._SSID_OP_DELETE, self._SSID_OP_UPDATE
            )
            for e in ssid_list
        )

        if has_crud_ops:
            self._apply_ssid_crud(radio_id, ssid_list)
        else:
            self._apply_ssid_snapshot(radio_id, ssid_list)

    def _apply_ssid_snapshot(self, radio_id: int, ssid_list: list) -> None:
        """Full snapshot: replace the radio's active SSID profiles with the
        entries in ``ssid_list``. An entry is active unless ``operation == 2``
        (delete) or ``ssidName`` is empty/missing."""
        profiles: list[dict[str, Any]] = []
        for entry in ssid_list:
            if not isinstance(entry, dict) or entry.get("operation") == self._SSID_OP_DELETE:
                continue
            name = entry.get("ssidName")
            if not isinstance(name, str) or not name:
                continue
            profiles.append(self._ssid_profile_from_entry(radio_id, entry))
        self._active_ssids_by_radio[radio_id] = profiles

    def _apply_ssid_crud(self, radio_id: int, ssid_list: list) -> None:
        """CRUD delta: process each entry's ``operation`` against the existing
        profile list. ``operation == 1`` adds, ``2`` deletes, ``3`` updates."""
        profiles = list(self._active_ssids_by_radio.get(radio_id, []))
        for entry in ssid_list:
            if not isinstance(entry, dict):
                continue
            op = entry.get("operation")
            name = entry.get("ssidName")
            old_name = entry.get("oldSsidName")
            entry_id = entry.get("id")
            entry_index = entry.get("index")

            # Match profiles by id, then index, then ssidName/oldSsidName.
            def _match(p: dict) -> bool:
                if isinstance(entry_id, int) and p.get("id") == entry_id:
                    return True
                if isinstance(entry_index, int) and p.get("index") == entry_index:
                    return True
                p_name = p.get("ssidName")
                if isinstance(old_name, str) and p_name == old_name:
                    return True
                if isinstance(name, str) and p_name == name:
                    return True
                return False

            if op == self._SSID_OP_DELETE:
                profiles = [p for p in profiles if not _match(p)]
            elif op == self._SSID_OP_ADD:
                if isinstance(name, str) and name:
                    # Don't add a duplicate (same id/index/name).
                    if not any(_match(p) for p in profiles):
                        profiles.append(self._ssid_profile_from_entry(radio_id, entry))
            elif op == self._SSID_OP_UPDATE:
                # Update the matching profile's fields, preserving its
                # profile_key so client assignments stay stable.
                updated = False
                for p in profiles:
                    if _match(p):
                        new_profile = self._ssid_profile_from_entry(radio_id, entry)
                        # Preserve the original profile_key (stable identity).
                        new_profile["profile_key"] = p.get("profile_key", new_profile["profile_key"])
                        profiles[profiles.index(p)] = new_profile
                        updated = True
                        break
                if not updated and isinstance(name, str) and name:
                    # Update for a non-existent profile — treat as add.
                    profiles.append(self._ssid_profile_from_entry(radio_id, entry))
            else:
                # Unknown/missing operation in a CRUD SET — treat as add if
                # the entry has a valid ssidName and isn't a duplicate.
                if isinstance(name, str) and name and not any(_match(p) for p in profiles):
                    profiles.append(self._ssid_profile_from_entry(radio_id, entry))
        self._active_ssids_by_radio[radio_id] = profiles

    @staticmethod
    def _ssid_profile_from_entry(radio_id: int, entry: dict[str, Any]) -> dict[str, Any]:
        """Build a profile dict from an SSID config entry."""
        name = entry.get("ssidName")
        entry_id = entry.get("id")
        entry_index = entry.get("index")
        if isinstance(entry_id, int):
            profile_key = f"id{entry_id}"
        elif isinstance(entry_index, int):
            profile_key = f"idx{entry_index}"
        else:
            profile_key = f"name-{name}"
        return {
            "ssidName": name,
            "id": entry_id if isinstance(entry_id, int) else None,
            "index": entry_index if isinstance(entry_index, int) else None,
            "vlanId": entry.get("vlanId") if isinstance(entry.get("vlanId"), int) else None,
            "portal": entry.get("portal") if isinstance(entry.get("portal"), bool) else None,
            "ssidIsolation": entry.get("ssidIsolation") if isinstance(entry.get("ssidIsolation"), bool) else None,
            "ssidBcast": entry.get("ssidBcast") if isinstance(entry.get("ssidBcast"), bool) else True,
            "profile_key": f"{radio_id}:{profile_key}",
        }

    def manage_inform_extra(self) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        # Wired uplink port -> topology placement.
        if self.topology.uplink is not None:
            extra.update(topology.ap_lan_info_section(self.topology.uplink))
        # AP LAN-port status (``uplinkPortStatus`` / ``portStatus``) so the
        # controller's AP → Ports / topology view shows link state, speed and
        # duplex for the uplink and any downlink LAN ports.
        extra.update(self._ap_port_status_sections())
        # AP downlink LAN-port traffic counters (``portTraffics``) for
        # multi-port APs (drives the AP → Ports traffic columns).
        extra.update(self._port_traffics_section())
        # AP PoE / power-draw (``poeInform``) so the AP → PoE view shows the
        # received power budget for a PoE-powered AP.
        extra.update(self._poe_inform_section())
        # Mesh / wireless-uplink info (``mesh``) so the controller knows this
        # AP is not part of a mesh (wired) or reports its mesh uplink state.
        extra.update(self._mesh_section())
        # Associated wireless clients (drives the Clients page + client tables).
        extra["clients"] = self._client_stats()
        # Per-radio settings, traffic and SSID stats (drives the AP Statistics /
        # radio Overview so channel/utilisation are no longer "undefined").
        for radio_id, radio in _RADIOS.items():
            if not self._radio_enabled(radio_id):
                continue
            extra[f"wSettings_{radio['suffix']}"] = self._wireless_info(radio_id, radio)
            extra[f"radioTraffic_{radio['suffix']}"] = self._radio_traffic(radio_id)
            extra[f"ssidStats_{radio['suffix']}"] = self._ssid_stats(radio_id)
        return extra

    def _ap_port_status_sections(self) -> dict[str, Any]:
        """The ``uplinkPortStatus`` and ``portStatus`` INFORM sections
        (uplink / downlink port status).

        The uplink port is the AP's wired Ethernet port facing the upstream
        switch/gateway. Multi-port APs (``lan_ports > 1``) may have additional
        downlink LAN ports for downstream-wired devices. Both sections share the
        same field set: ``port``, ``portType``, ``duplex``, ``link``, ``speed``,
        plus optional PoE telemetry (``txPw``/``rxPw``/``temp``/``volt``/``curr``)
        and state enums (``poeState``/``voipState``). All optional fields are
        omitted when null.

        ``port`` is a 1-based string port number. ``portType``: 0 = LAN,
        1 = WAN (APs use LAN). ``link``: 1 = up, 0 = down. ``duplex``: 1 = full,
        0 = half. ``speed``: negotiated link speed in Mbps.
        """
        extra: dict[str, Any] = {}
        uplink = self.topology.uplink
        if uplink is not None:
            extra["uplinkPortStatus"] = [{
                "port": str(uplink.local_port),
                "portType": 0,
                "duplex": 1,
                "link": 1,
                "speed": 1000,
            }]
        # Downlink ports: any LAN ports beyond the uplink port. For a
        # single-port AP (``lan_ports == 1``) the only port is the uplink, so
        # there are no downlinks and ``portStatus`` is an empty list.
        downlink_ports = self._downlink_ports()
        if downlink_ports:
            extra["portStatus"] = [{
                "port": str(p),
                "portType": 0,
                "duplex": 1,
                "link": 1,
                "speed": 1000,
            } for p in downlink_ports]
        return extra

    def _downlink_ports(self) -> list[int]:
        """LAN ports beyond the wired uplink port (empty for a single-port AP,
        whose only port is the uplink)."""
        uplink = self.topology.uplink
        ports = list(range(1, self.lan_ports + 1))
        if uplink is not None:
            ports = [p for p in ports if p != uplink.local_port]
        return ports

    def _port_traffics_section(self) -> dict[str, Any]:
        """The ``portTraffics`` INFORM section (downlink port traffic):
        per-downlink-LAN-port traffic counters for multi-port APs. Confirmed
        fields: ``port``
        (String), ``rxP``/``txP`` (packets), ``rx``/``tx`` (bytes),
        ``rxDP``/``txDP`` (drop packets), ``rxEP``/``txEP`` (error packets).
        Only downlink ports report traffic (the uplink port's traffic is not
        modeled here); a single-port AP (whose only port is the uplink) omits
        this key entirely."""
        downlink_ports = self._downlink_ports()
        if not downlink_ports:
            return {}
        up = self.uptime_seconds
        entries = []
        for port in downlink_ports:
            rate = stats.synthetic_rate_bps(self.mac, f"pt-rt{port}", 1, 50)
            rx = stats.synthetic_bytes(self.mac, f"pt-rx{port}", up, rate)
            tx = stats.synthetic_bytes(self.mac, f"pt-tx{port}", up, rate)
            entries.append({
                "port": str(port),
                "rxP": stats.synthetic_packets(rx),
                "txP": stats.synthetic_packets(tx),
                "rx": rx,
                "tx": tx,
                "rxDP": 0,
                "txDP": 0,
                "rxEP": 0,
                "txEP": 0,
            })
        return {"portTraffics": entries}

    def _poe_inform_section(self) -> dict[str, Any]:
        """The ``poeInform`` INFORM section (PoE status).

        The AP is a PoE *consumer* (powered by the switch's PoE budget). The
        section reports the AP's received power budget: ``total`` (budget in W),
        ``remain`` (remaining in W), ``percent`` (remaining %), and
        ``poeStartUp`` (whether PoE startup is complete). For a non-PoE AP
        (``supports_poe == False``, e.g. powered by a DC adapter) the section
        reports a zero/empty budget.
        """
        if not self.supports_poe:
            return {"poeInform": {
                "remain": 0.0, "percent": 0.0, "total": 0.0, "poeStartUp": False,
            }}
        # EAP245(US) v3.0 is an 802.3at (PoE+) device with a ~25W budget.
        total = 25.0
        draw = stats.synthetic_int(self.mac, "poedraw", 50, 180) / 10.0
        remain = round(max(0.0, total - draw), 1)
        percent = round(remain / total * 100, 1) if total else 0.0
        return {"poeInform": {
            "remain": remain,
            "percent": percent,
            "total": total,
            "poeStartUp": True,
        }}

    def _mesh_section(self) -> dict[str, Any]:
        """The ``mesh`` INFORM section (mesh info).

        For a wired AP (``wireless_uplink == False``, the default) this reports
        an inactive/non-mesh state: ``status`` = 0 (disabled), empty
        ``isolatedAPs`` / ``childAPs`` lists, and no ``candidateParents`` or
        ``childApRec``. This tells the controller the AP is not part of a mesh.

        For a wireless-uplink AP (``wireless_uplink == True``) the section
        reports an active mesh state with a synthetic parent AP candidate.
        """
        if not self.wireless_uplink:
            return {"mesh": {
                "status": 0,
                "isolatedAPs": [],
                "childAPs": [],
            }}
        # Wireless-uplink (mesh) AP: report an active mesh with a synthetic
        # parent candidate so the controller can place it in the mesh tree.
        parent_mac = stats.synthetic_client_mac(self.mac, 0)
        return {"mesh": {
            "status": 1,
            "meshRid": 1,
            "isolatedAPs": [],
            "childAPs": [],
            "candidateParents": {
                "status": 1,
                "parentList": [{
                    "mac": parent_mac,
                    "rssi": -45,
                    "snr": 35,
                    "ch": 36,
                    "meshVer": 2,
                    "radioId": 1,
                }],
            },
        }}

    def _client_stats(self) -> list[dict[str, Any]]:
        """``clients`` INFORM section. Each wireless client is assigned an
        active SSID profile by ``_radio_client_assignments`` (round-robin
        across the profiles active on that radio); wired-uplink clients (only
        relevant for a wireless-uplink mesh AP) pass through unchanged."""
        up = self.uptime_seconds
        assignments: dict[str, dict[str, Any]] = {}
        for radio_id in _RADIOS:
            for client, profile in self._radio_client_assignments(radio_id):
                assignments[client.mac] = profile
        out = []
        for client in self.reported_clients:
            if not client.wireless or not self._radio_enabled(client.radio_id):
                continue
            profile = assignments.get(client.mac)
            if profile is None:
                continue
            rx, tx = client.traffic(up)
            radio = _RADIOS.get(client.radio_id, _RADIOS[0])
            wireless_basic = self._applied_wireless_basic.get(client.radio_id, {})
            bandwidth = wireless_basic.get("chanWidth")
            if bandwidth is None:
                bandwidth = radio["bw"]
            vlan = profile.get("vlanId")
            if not isinstance(vlan, int):
                vlan = 1
            guest = 1 if profile.get("portal") is True or profile.get("ssidIsolation") is True else 0
            out.append({
                "mac": client.mac,
                "rid": client.radio_id,
                "ap": self.mac,
                "ssid": profile["ssidName"],
                "snr": client.snr,
                "rssi": client.rssi,
                "ccq": 90,
                "rate": f"{client.rate_mbps}M",
                "down": rx,
                "up": tx,
                "time": format_uptime(client.assoc_seconds),
                "ip": client.ip,
                "name": client.name,
                "type": "",
                "txR": client.up_bps,
                "rxR": client.down_bps,
                "txP": stats.synthetic_packets(tx),
                "rxP": stats.synthetic_packets(rx),
                "aTime": client.assoc_seconds,
                "bw": bandwidth,
                "vlan": vlan,
                "guest": guest,
            })
        return out

    def _wireless_info(self, radio_id: int, radio: dict[str, Any]) -> dict[str, Any]:
        n = len(self._radio_clients(radio_id))
        # channel / chanWidth / txPower are controller-pushed via
        # ``wirelessBasic_<band>G`` (wireless basic config: ``channel`` /
        # ``chanWidth`` / ``txPower`` Integers). Use the captured values when
        # pushed, falling back to the ``_RADIOS`` synthetic defaults pre-push.
        wbc = self._applied_wireless_basic.get(radio_id, {})
        ch = wbc.get("channel")
        bw = wbc.get("chanWidth")
        tx_power = wbc.get("txPower")
        ch = str(ch if ch is not None else radio["ch"])
        bw = str(bw if bw is not None else radio["bw"])
        # rdMode is a string ("11ng"/"11ac"); the push carries an Integer
        # ``wirelessMode`` whose ->string mapping is not yet confirmed, so
        # rdMode stays as the ``_RADIOS`` fallback until that mapping is
        # confirmed.
        tx_rate = stats.synthetic_int(self.mac, f"txr{radio_id}", 200, 600)
        if tx_power is None:
            tx_power = stats.synthetic_int(self.mac, f"txp{radio_id}", 17, 23)
        # ch / bw / rdMode / txR / txPower are strings on the wire. The
        # controller's WLAN decoder parses txR as the integer before a '.' and
        # txPower by stripping its 3-char unit suffix, so both need that shape.
        return {
            "region": self.country_code,
            "ch": ch,
            "bw": bw,
            "rdMode": radio["rdMode"],
            "txR": f"{tx_rate}.0",
            "txPower": f"{tx_power}dBm",
            "txUti": stats.synthetic_int(self.mac, f"txu{radio_id}", 2, 30),
            "rxUti": stats.synthetic_int(self.mac, f"rxu{radio_id}", 2, 20),
            "interUti": stats.synthetic_int(self.mac, f"iu{radio_id}", 0, 10),
            "busyUti": stats.synthetic_int(self.mac, f"bu{radio_id}", 5, 40),
            "aiRoamingOffset": 0,
            "staNum": n,
        }

    def _radio_traffic(self, radio_id: int) -> dict[str, Any]:
        up = self.uptime_seconds
        rate = stats.synthetic_rate_bps(self.mac, f"rt{radio_id}", 10, 150)
        rx = stats.synthetic_bytes(self.mac, f"rrx{radio_id}", up, rate)
        tx = stats.synthetic_bytes(self.mac, f"rtx{radio_id}", up, rate)
        return {
            "rx": rx, "tx": tx,
            "rxP": stats.synthetic_packets(rx), "txP": stats.synthetic_packets(tx),
        }

    def _ssid_stats(self, radio_id: int) -> list[dict[str, Any]]:
        """``ssidStats_<band>G`` INFORM section: one row per active SSID
        profile on this radio (including profiles with zero associated
        clients), so the controller's per-SSID client/traffic breakdown
        reflects every configured WLAN, not just ones with traffic."""
        profiles = self._active_ssids_for_radio(radio_id)
        if not profiles:
            return []
        assignments = self._radio_client_assignments(radio_id)
        up = self.uptime_seconds
        out = []
        for profile in profiles:
            clients = [client for client, p in assignments if p is profile]
            down = sum(c.traffic(up)[0] for c in clients)
            upb = sum(c.traffic(up)[1] for c in clients)
            profile_id = profile.get("id")
            if not isinstance(profile_id, int):
                profile_id = stats.synthetic_int(profile["profile_key"], "ssid-stats-id", 1, 9999)
            out.append({
                "id": profile_id,
                "ssid": profile["ssidName"],
                "clntNum": len(clients),
                "down": down,
                "up": upb,
                "downPkts": stats.synthetic_packets(down),
                "upPkts": stats.synthetic_packets(upb),
                "bssid": stats.synthetic_bssid(self.mac, radio_id, profile["profile_key"]),
                "rxS": down, "txS": upb,
            })
        return out

    def manage_device_info(self) -> dict[str, Any]:
        # Access points use the long-name deviceInfo field set. ip / txRate /
        # rxRate are required for the Devices grid to show the AP's IP and its
        # up/down rate (the controller renders "--" / 0 without them).
        rx_rate, tx_rate = self._agg_rates()
        return {
            "name": self.name,
            "model": self.identity.model,
            "modelVersion": self.identity.model_version,
            "firmwareVersion": self.identity.firmware_version,
            "hardwareVersion": self.identity.hardware_version,
            "upTime": format_uptime(self.uptime_seconds),
            "ip": self.ip,
            "cpuUti": self.cpu_util,
            "memUti": self.mem_util,
            "txRate": tx_rate,
            "rxRate": rx_rate,
            # Radios are operational once adopted (independent of the
            # discovery-time mesh-link flag, which must stay False for a wired AP).
            "wirelessLinked": True,
            "p2p": False,
        }

    def manage_components_v2(self) -> dict[str, str]:
        return dict(eap_profile.COMPONENTS_V2)

    def build_discovery_body(self) -> dict[str, Any]:
        assert self.controller_id is not None
        return build_ap_discovery_body(
            ip=self.ip,
            model=self.identity.model,
            model_version=self.identity.model_version,
            firmware_version=self.identity.firmware_version,
            hardware_version=self.identity.hardware_version,
            name=self.name,
            controller_id=self.controller_id,
            up_time_seconds=self.uptime_seconds,
            cpu_util=self.cpu_util,
            mem_util=self.mem_util,
            wireless_linked=self.wireless_linked,
            p2p=False,
            country_code=self.country_code,
        )
