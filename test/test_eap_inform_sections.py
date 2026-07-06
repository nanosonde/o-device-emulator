"""Unit tests for the EAP-specific INFORM sections: port status (uplink +
downlink LAN ports), PoE / power draw (poeInform), and mesh / wireless-uplink
info. These verify the field shapes for the uplink port status, downlink port
status, PoE, and mesh sections (see doc/DEVICE_PROTOCOL.md §7.8)."""
from __future__ import annotations

from dataclasses import fields
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.devices import build_device
from device_emulator.devices.eap import EapDevice
from device_emulator.services.runner import Runner


def _runner_with_chain(**ap_kwargs) -> tuple[Runner, EapDevice]:
    """Build a gateway → switch → AP chain and return (runner, ap)."""
    runner = Runner(controller_host="x")
    runner.add_device(build_device(
        {"name": "gw", "type": "gateway", "model": "ER605",
         "mac": "AA-BB-CC-DD-EE-03", "ip": "1.1.1.3"}
    ))
    runner.add_device(build_device(
        {"name": "sw", "type": "switch", "model": "TL-SG3210",
         "mac": "AA-BB-CC-DD-EE-02", "ip": "1.1.1.2",
         "uplink": "gw", "uplink_port": 5}
    ))
    ap_cfg: dict = {
        "name": "ap", "type": "ap", "model": "EAP245",
        "mac": "AA-BB-CC-DD-EE-01", "ip": "1.1.1.1",
        "uplink": "sw", "uplink_port": 8,
    }
    ap_cfg.update(ap_kwargs)
    runner.add_device(build_device(ap_cfg))
    runner._resolve_topology()
    ap = runner.devices[-1]
    assert isinstance(ap, EapDevice)
    return runner, ap


# ---------------------------------------------------------------------------
# Port status: uplinkPortStatus / portStatus
# ---------------------------------------------------------------------------

def test_ap_reports_uplink_port_status():
    _, ap = _runner_with_chain()
    extra = ap.manage_inform_extra()
    # The AP's local uplink port is port 1 (auto-assigned as local_uplink_port
    # defaults to 1 for the AP facing the switch's port 8).
    assert "uplinkPortStatus" in extra
    uplink_ports = extra["uplinkPortStatus"]
    assert len(uplink_ports) == 1
    entry = uplink_ports[0]
    # Uplink port status fields:
    # port(String), portType(Integer), duplex(Integer), link(Integer),
    # speed(Integer) + optional PoE telemetry / state enums.
    assert entry["port"] == "1"
    assert entry["portType"] == 0  # LAN
    assert entry["duplex"] == 1    # full
    assert entry["link"] == 1      # up
    assert entry["speed"] == 1000


def test_ap_single_port_has_no_downlink_port_status():
    """A single-port AP (lan_ports=1) uses its only port as the uplink, so
    portStatus (downlink ports) is absent."""
    _, ap = _runner_with_chain(lan_ports=1)
    extra = ap.manage_inform_extra()
    # No downlink ports beyond the uplink → portStatus is omitted.
    assert "portStatus" not in extra


def test_ap_multi_port_reports_downlink_port_status():
    """A multi-port AP (lan_ports=2) reports its non-uplink port as a downlink
    in portStatus."""
    _, ap = _runner_with_chain(lan_ports=2)
    extra = ap.manage_inform_extra()
    assert "portStatus" in extra
    ports = extra["portStatus"]
    assert len(ports) == 1
    # Port 1 is the uplink; port 2 is the downlink.
    assert ports[0]["port"] == "2"
    assert ports[0]["portType"] == 0
    assert ports[0]["link"] == 1
    assert ports[0]["speed"] == 1000


def test_ap_without_topology_no_uplink_port_status():
    """Without a resolved uplink there is no uplinkPortStatus, but portStatus
    may still report standalone ports."""
    ap = build_device({"name": "ap", "type": "ap", "model": "EAP245",
                       "mac": "AA-BB-CC-DD-EE-09", "ip": "1.1.1.9", "lan_ports": 1})
    extra = ap.manage_inform_extra()
    assert "uplinkPortStatus" not in extra
    # Port 1 is the only port and there's no uplink to filter it out, so it
    # appears as a downlink.
    assert "portStatus" in extra
    assert extra["portStatus"][0]["port"] == "1"


# ---------------------------------------------------------------------------
# Multi-port AP downlink traffic: portTraffics
# ---------------------------------------------------------------------------

def test_ap_single_port_uplink_only_omits_port_traffics():
    """A single-port AP (lan_ports=1) has no downlink ports, so portTraffics
    is omitted entirely."""
    _, ap = _runner_with_chain(lan_ports=1)
    extra = ap.manage_inform_extra()
    assert "portTraffics" not in extra


def test_ap_multi_port_reports_exactly_one_downlink_port_traffics():
    _, ap = _runner_with_chain(lan_ports=2)
    extra = ap.manage_inform_extra()
    assert "portTraffics" in extra
    entries = extra["portTraffics"]
    assert len(entries) == 1
    entry = entries[0]
    # Port 1 is the uplink; port 2 is the downlink.
    assert entry["port"] == "2"
    assert {"port", "rxP", "txP", "rx", "tx", "rxDP", "txDP", "rxEP", "txEP"} == set(entry)
    assert isinstance(entry["rx"], int) and isinstance(entry["tx"], int)
    assert isinstance(entry["rxP"], int) and isinstance(entry["txP"], int)
    assert entry["rxDP"] == 0 and entry["txDP"] == 0
    assert entry["rxEP"] == 0 and entry["txEP"] == 0


def test_ap_port_traffics_are_deterministic():
    _, ap1 = _runner_with_chain(lan_ports=2)
    _, ap2 = _runner_with_chain(lan_ports=2)
    assert ap1.manage_inform_extra()["portTraffics"] == ap2.manage_inform_extra()["portTraffics"]


# ---------------------------------------------------------------------------
# PoE / power draw: poeInform
# ---------------------------------------------------------------------------

def test_ap_reports_poe_inform_when_poe_supported():
    _, ap = _runner_with_chain(supports_poe=True)
    extra = ap.manage_inform_extra()
    assert "poeInform" in extra
    poe = extra["poeInform"]
    # PoE status fields:
    # remain(Double), percent(Double), total(Double), poeStartUp(Boolean).
    assert "remain" in poe
    assert "percent" in poe
    assert "total" in poe
    assert "poeStartUp" in poe
    assert poe["poeStartUp"] is True
    assert poe["total"] == 25.0  # 802.3at PoE+ budget
    assert 0 <= poe["remain"] <= poe["total"]
    assert 0 <= poe["percent"] <= 100


def test_ap_reports_empty_poe_inform_when_not_poe():
    """A non-PoE AP (DC-powered) reports a zero/empty poeInform budget."""
    ap = build_device({"name": "ap", "type": "ap", "model": "EAP245",
                       "mac": "AA-BB-CC-DD-EE-09", "ip": "1.1.1.9",
                       "supports_poe": False})
    extra = ap.manage_inform_extra()
    assert "poeInform" in extra
    poe = extra["poeInform"]
    assert poe["total"] == 0.0
    assert poe["remain"] == 0.0
    assert poe["percent"] == 0.0
    assert poe["poeStartUp"] is False


def test_ap_poe_inform_is_deterministic():
    """The PoE draw is MAC-seeded so the same AP always reports the same
    remaining budget."""
    mac = "AA-BB-CC-DD-EE-01"
    _, ap1 = _runner_with_chain(mac=mac)
    _, ap2 = _runner_with_chain(mac=mac)
    assert ap1.manage_inform_extra()["poeInform"]["remain"] == \
        ap2.manage_inform_extra()["poeInform"]["remain"]


# ---------------------------------------------------------------------------
# Mesh / wireless-uplink: mesh
# ---------------------------------------------------------------------------

def test_ap_wired_reports_inactive_mesh():
    """A wired AP (wireless_uplink=False, the default) reports an inactive
    mesh state: status=0 with empty lists."""
    _, ap = _runner_with_chain(wireless_uplink=False)
    extra = ap.manage_inform_extra()
    assert "mesh" in extra
    mesh = extra["mesh"]
    # Mesh section fields:
    # status(Integer), meshRid(Integer), isolatedAPs(List), childAPs(List),
    # candidateParents(section), childApRec(List).
    assert mesh["status"] == 0
    assert mesh["isolatedAPs"] == []
    assert mesh["childAPs"] == []
    # Non-mesh AP does not report candidate parents or child records.
    assert "candidateParents" not in mesh
    assert "childApRec" not in mesh


def test_ap_wireless_uplink_reports_active_mesh():
    """A wireless-uplink AP (wireless_uplink=True) reports an active mesh
    state with a candidate parent AP."""
    _, ap = _runner_with_chain(wireless_uplink=True)
    extra = ap.manage_inform_extra()
    assert "mesh" in extra
    mesh = extra["mesh"]
    assert mesh["status"] == 1
    assert mesh["meshRid"] == 1
    assert "candidateParents" in mesh
    parents = mesh["candidateParents"]
    # Candidate parents section: status(Integer), parentList(List of parent entries).
    assert parents["status"] == 1
    assert len(parents["parentList"]) == 1
    parent = parents["parentList"][0]
    # Parent entry: mac, rssi, snr, ch, meshVer, radioId.
    assert "mac" in parent
    assert "rssi" in parent
    assert "snr" in parent
    assert "ch" in parent
    assert "meshVer" in parent
    assert "radioId" in parent


def test_mesh_section_present_without_topology():
    """The mesh section is always emitted (even without a wired uplink)."""
    ap = build_device({"name": "ap", "type": "ap", "model": "EAP245",
                       "mac": "AA-BB-CC-DD-EE-09", "ip": "1.1.1.9"})
    extra = ap.manage_inform_extra()
    assert "mesh" in extra
    assert extra["mesh"]["status"] == 0


# ---------------------------------------------------------------------------
# Integration: all sections present together
# ---------------------------------------------------------------------------

def test_ap_inform_extra_has_all_new_sections():
    """A wired, PoE-powered AP with a topology uplink reports all three new
    sections (uplinkPortStatus, poeInform, mesh) alongside the existing
    lanInfo and clients."""
    _, ap = _runner_with_chain()
    extra = ap.manage_inform_extra()
    assert "lanInfo" in extra
    assert "uplinkPortStatus" in extra
    assert "poeInform" in extra
    assert "mesh" in extra
    assert "clients" in extra
    assert "wSettings_2G" in extra


# ---------------------------------------------------------------------------
# WLAN / SSID: controller-pushed via ssid_2G / ssid_5G SET keys
# ---------------------------------------------------------------------------

def test_ap_default_ssid_before_any_wlan_push():
    """Before the controller pushes any WLAN/SSID config, the AP reports a
    synthetic default SSID so the INFORM is well-formed (the controller shows
    ``undefined`` until a WLAN matches, by design)."""
    runner, ap = _runner_with_chain()
    from device_emulator.devices.clients import synthesize_site_clients
    synthesize_site_clients(runner.devices)
    extra = ap.manage_inform_extra()
    clients = extra["clients"]
    assert clients and all(c["ssid"] == "Lab-WiFi" for c in clients)
    assert extra["ssidStats_2G"][0]["ssid"] == "Lab-WiFi"
    assert extra["ssidStats_5G"][0]["ssid"] == "Lab-WiFi"


def test_ap_reports_controller_pushed_ssid_after_set():
    """The WLAN/SSID is controller-pushed (not a device-side property): the
    controller sends ``ssid_2G`` / ``ssid_5G`` SET keys (the SSID config ->
    SSID entries with ``ssidName``); the AP captures the push in
    ``build_set_response`` and reports that ``ssidName`` in its INFORM
    ``clients[].ssid`` / ``ssidStats_*.ssid`` so it matches the configured WLAN
    for wireless classification. See doc/DEVICE_PROTOCOL.md §7.8."""
    runner, ap = _runner_with_chain()
    from device_emulator.devices.clients import synthesize_site_clients
    synthesize_site_clients(runner.devices)
    # Simulate the controller pushing the WLAN/SSID config.
    ap.build_set_response({
        "sequenceId": 1,
        "configVersion": 2,
        "ssid_2G": {"radioId": 0, "ssid": [{"id": 1, "ssidName": "MyWLAN"}]},
        "ssid_5G": {"radioId": 1, "ssid": [{"id": 1, "ssidName": "MyWLAN"}]},
    })
    extra = ap.manage_inform_extra()
    clients = extra["clients"]
    assert clients and all(c["ssid"] == "MyWLAN" for c in clients)
    assert extra["ssidStats_2G"][0]["ssid"] == "MyWLAN"
    assert extra["ssidStats_5G"][0]["ssid"] == "MyWLAN"


def test_ap_empty_ssid_push_removes_associations_instead_of_restoring_default():
    """An explicit empty SSID config means the WLAN was removed. It differs from
    the pre-push state and must not resurrect the synthetic default SSID."""
    runner, ap = _runner_with_chain()
    from device_emulator.devices.clients import synthesize_site_clients
    synthesize_site_clients(runner.devices)
    ap.build_set_response({
        "sequenceId": 1,
        "configVersion": 2,
        "ssid_2G": {"radioId": 0, "ssid": []},
    })
    extra = ap.manage_inform_extra()
    assert all(client["rid"] != 0 for client in extra["clients"])
    assert extra["ssidStats_2G"] == []


def test_ap_get_response_echoes_pushed_ssid_config():
    """``build_get_response`` echoes the captured ``ssid_2G`` / ``ssid_5G``
    config under its AP configure key so the controller's WLAN config
    tab shows the applied values."""
    ap = build_device({
        "name": "ap", "type": "ap", "model": "EAP245",
        "mac": "AA-BB-CC-DD-EE-09", "ip": "1.1.1.9",
    })
    ap.build_set_response({
        "sequenceId": 1,
        "configVersion": 2,
        "ssid_5G": {"radioId": 1, "ssid": [{"id": 1, "ssidName": "Site-5G"}]},
    })
    resp = ap.build_get_response({"sequenceId": 7})
    assert resp["errcode"] == 0
    assert resp["ssid_5G"] == {"radioId": 1, "ssid": [{"id": 1, "ssidName": "Site-5G"}]}
    # ssid_2G was not pushed, so it is absent.
    assert "ssid_2G" not in resp


def test_ap_applied_ssid_config_is_isolated_from_mutation():
    ap = build_device({
        "name": "ap", "type": "ap", "model": "EAP245",
        "mac": "AA-BB-CC-DD-EE-09", "ip": "1.1.1.9",
    })
    request = {
        "ssid_2G": {"radioId": 0, "ssid": [{"id": 1, "ssidName": "Stable"}]},
    }
    ap.build_set_response(request)
    request["ssid_2G"]["ssid"][0]["ssidName"] = "Mutated"
    response = ap.build_get_response({})
    assert response["ssid_2G"]["ssid"][0]["ssidName"] == "Stable"
    response["ssid_2G"]["ssid"][0]["ssidName"] = "Mutated again"
    assert ap.build_get_response({})["ssid_2G"]["ssid"][0]["ssidName"] == "Stable"


# ---------------------------------------------------------------------------
# Radio config: controller-pushed via wirelessBasic_*G SET keys
# ---------------------------------------------------------------------------

def test_ap_radio_defaults_before_any_push():
    """Before the controller pushes any radio config, the AP reports the
    synthetic ``_RADIOS`` defaults (channel/bw) so the INFORM is well-formed."""
    runner, ap = _runner_with_chain()
    extra = ap.manage_inform_extra()
    w2 = extra["wSettings_2G"]
    w5 = extra["wSettings_5G"]
    # _RADIOS defaults: 2.4G ch=6 bw=20, 5G ch=36 bw=80.
    assert w2["ch"] == "6"
    assert w2["bw"] == "20"
    assert w5["ch"] == "36"
    assert w5["bw"] == "80"


def test_ap_reports_controller_pushed_radio_config_after_set():
    """The radio config (channel / channel width / txPower) is controller-pushed
    via ``wirelessBasic_2G`` / ``wirelessBasic_5G`` SET keys (the wireless basic config);
    the AP captures the push in ``build_set_response`` and reports the applied
    values in ``wSettings_<band>G`` so the controller's Radio settings tab
    reflects operator config (same design as the SSID capture). See
    doc/DEVICE_PROTOCOL.md §7.8."""
    runner, ap = _runner_with_chain()
    from device_emulator.devices.clients import synthesize_site_clients
    synthesize_site_clients(runner.devices)
    ap.build_set_response({
        "sequenceId": 1,
        "configVersion": 2,
        "wirelessBasic_2G": {"radioId": 0, "channel": 11, "chanWidth": 40, "txPower": 20},
        "wirelessBasic_5G": {"radioId": 1, "channel": 149, "chanWidth": 160, "txPower": 30},
    })
    extra = ap.manage_inform_extra()
    assert extra["wSettings_2G"]["ch"] == "11"
    assert extra["wSettings_2G"]["bw"] == "40"
    assert extra["wSettings_2G"]["txPower"] == "20dBm"
    assert extra["wSettings_5G"]["ch"] == "149"
    assert extra["wSettings_5G"]["bw"] == "160"
    assert extra["wSettings_5G"]["txPower"] == "30dBm"
    client_5g = next(client for client in extra["clients"] if client["rid"] == 1)
    assert client_5g["bw"] == 160


def test_ap_disabled_radio_omits_radio_telemetry_and_clients():
    runner, ap = _runner_with_chain()
    from device_emulator.devices.clients import synthesize_site_clients
    synthesize_site_clients(runner.devices)
    ap.build_set_response({
        "sequenceId": 1,
        "configVersion": 2,
        "wirelessBasic_2G": {"radioId": 0, "radioEnable": False},
    })
    extra = ap.manage_inform_extra()
    assert "wSettings_2G" not in extra
    assert "radioTraffic_2G" not in extra
    assert "ssidStats_2G" not in extra
    assert all(client["rid"] != 0 for client in extra["clients"])


def test_ap_radio_set_key_table_is_not_a_dataclass_init_field():
    assert "_RADIO_SET_KEYS" not in {field.name for field in fields(EapDevice)}


def test_ap_get_response_echoes_pushed_wireless_basic_config():
    """``build_get_response`` echoes the captured ``wirelessBasic_2G`` /
    ``wirelessBasic_5G`` config so the controller's Radio config tab stays in
    sync with the applied values."""
    ap = build_device({
        "name": "ap", "type": "ap", "model": "EAP245",
        "mac": "AA-BB-CC-DD-EE-09", "ip": "1.1.1.9",
    })
    ap.build_set_response({
        "sequenceId": 1,
        "configVersion": 2,
        "wirelessBasic_5G": {"radioId": 1, "channel": 44, "chanWidth": 80},
    })
    resp = ap.build_get_response({"sequenceId": 7})
    assert resp["errcode"] == 0
    assert resp["wirelessBasic_5G"] == {"radioId": 1, "channel": 44, "chanWidth": 80}
    assert "wirelessBasic_2G" not in resp


def test_ap_radio_falls_back_to_defaults_when_push_missing_fields():
    """A ``wirelessBasic_*G`` push missing ``channel`` / ``chanWidth`` / ``txPower``
    falls back to the ``_RADIOS`` synthetic defaults for those fields (partial
    push tolerance)."""
    runner, ap = _runner_with_chain()
    ap.build_set_response({
        "sequenceId": 1,
        "configVersion": 2,
        "wirelessBasic_2G": {"radioId": 0, "channel": 11},  # no chanWidth/txPower
    })
    extra = ap.manage_inform_extra()
    w2 = extra["wSettings_2G"]
    assert w2["ch"] == "11"            # pushed
    assert w2["bw"] == "20"            # _RADIOS fallback (2.4G default)
    assert w2["txPower"].endswith("dBm")  # synthetic fallback (MAC-seeded)


# ---------------------------------------------------------------------------
# Configurable wireless client pool (wireless_client_count, 0-5, default 5)
# ---------------------------------------------------------------------------

def test_ap_default_client_count_creates_five_round_robin():
    """Default AP creates exactly 5 wireless clients: radio IDs [0,1,0,1,0]
    in creation order (3 on 2.4 GHz, 2 on 5 GHz)."""
    from device_emulator.devices.clients import synthesize_site_clients
    runner, ap = _runner_with_chain()
    synthesize_site_clients(runner.devices)
    assert [c.radio_id for c in ap.reported_clients] == [0, 1, 0, 1, 0]
    assert sum(1 for c in ap.reported_clients if c.radio_id == 0) == 3
    assert sum(1 for c in ap.reported_clients if c.radio_id == 1) == 2


def test_ap_client_count_zero_one_and_five():
    from device_emulator.devices.clients import synthesize_site_clients
    for count in (0, 1, 5):
        runner, ap = _runner_with_chain(wireless_client_count=count)
        synthesize_site_clients(runner.devices)
        assert len(ap.reported_clients) == count


def test_ap_client_count_rejects_invalid_values():
    for bad in (-1, 6, True, "5", 1.5):
        try:
            build_device({
                "name": "ap", "type": "ap", "model": "EAP245",
                "mac": "AA-BB-CC-DD-EE-09", "ip": "1.1.1.9",
                "wireless_client_count": bad,
            })
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for wireless_client_count={bad!r}")


def test_ap_client_identity_stable_across_runs():
    """Two runs with the same AP MAC/count produce identical client MAC/name/
    radio assignments."""
    from device_emulator.devices.clients import synthesize_site_clients
    r1, ap1 = _runner_with_chain()
    synthesize_site_clients(r1.devices)
    r2, ap2 = _runner_with_chain()
    synthesize_site_clients(r2.devices)
    assert [(c.mac, c.name, c.radio_id) for c in ap1.reported_clients] == \
        [(c.mac, c.name, c.radio_id) for c in ap2.reported_clients]


def test_two_aps_own_counts_and_gateway_aggregates_all_clients_uniquely():
    runner = Runner(controller_host="x")
    runner.add_device(build_device(
        {"name": "gw", "type": "gateway", "model": "ER605",
         "mac": "AA-BB-CC-DD-EE-03", "ip": "1.1.1.3"}
    ))
    runner.add_device(build_device(
        {"name": "sw", "type": "switch", "model": "TL-SG3210",
         "mac": "AA-BB-CC-DD-EE-02", "ip": "1.1.1.2",
         "uplink": "gw", "uplink_port": 5}
    ))
    runner.add_device(build_device(
        {"name": "ap1", "type": "ap", "model": "EAP245",
         "mac": "AA-BB-CC-DD-EE-01", "ip": "1.1.1.1",
         "uplink": "sw", "uplink_port": 8, "wireless_client_count": 2}
    ))
    runner.add_device(build_device(
        {"name": "ap2", "type": "ap", "model": "EAP245",
         "mac": "AA-BB-CC-DD-EE-04", "ip": "1.1.1.4",
         "uplink": "sw", "uplink_port": 7, "wireless_client_count": 3}
    ))
    runner._resolve_topology()
    from device_emulator.devices.clients import synthesize_site_clients
    synthesize_site_clients(runner.devices)
    gw, sw, ap1, ap2 = runner.devices
    assert len(ap1.reported_clients) == 2
    assert len(ap2.reported_clients) == 3
    gw_macs = [c.mac for c in gw.reported_clients]
    assert len(gw_macs) == len(set(gw_macs))
    assert len(gw_macs) == 2 + 3 + 1  # ap1 + ap2 + switch's one wired client


# ---------------------------------------------------------------------------
# Multi-SSID effective state per radio (Phase 2) and client/SSID assignment
# (Phase 3). The SSID entry operation add/update/delete semantics are not yet
# confirmed (see EapDevice._apply_ssid_config docstring); these tests cover
# the documented conservative fallback: each ssid_<band>G push is a full
# snapshot, filtering operation==2 (delete) / empty ssidName.
# ---------------------------------------------------------------------------

def test_ap_pre_push_reports_one_fallback_profile_per_enabled_radio():
    runner, ap = _runner_with_chain()
    from device_emulator.devices.clients import synthesize_site_clients
    synthesize_site_clients(runner.devices)
    extra = ap.manage_inform_extra()
    assert len(extra["ssidStats_2G"]) == 1
    assert extra["ssidStats_2G"][0]["ssid"] == "Lab-WiFi"
    assert len(extra["ssidStats_5G"]) == 1
    assert extra["ssidStats_5G"][0]["ssid"] == "Lab-WiFi"


def test_ap_initial_multi_ssid_payload_creates_all_profiles_in_order():
    runner, ap = _runner_with_chain()
    from device_emulator.devices.clients import synthesize_site_clients
    synthesize_site_clients(runner.devices)
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp"},
            {"id": 2, "ssidName": "Guest"},
        ]},
    })
    extra = ap.manage_inform_extra()
    names = [row["ssid"] for row in extra["ssidStats_2G"]]
    assert names == ["Corp", "Guest"]


def test_ap_ssid_add_update_delete_one_and_delete_last():
    runner, ap = _runner_with_chain()
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [{"id": 1, "ssidName": "Corp"}]},
    })
    assert [p["ssid"] for p in ap._ssid_stats(0)] == ["Corp"]

    # Add a second SSID.
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp"}, {"id": 2, "ssidName": "Guest"},
        ]},
    })
    assert [p["ssid"] for p in ap._ssid_stats(0)] == ["Corp", "Guest"]

    # Rename/update the first SSID.
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp-Renamed"}, {"id": 2, "ssidName": "Guest"},
        ]},
    })
    assert [p["ssid"] for p in ap._ssid_stats(0)] == ["Corp-Renamed", "Guest"]

    # Delete one (of two) via operation == 2.
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp-Renamed"},
            {"id": 2, "ssidName": "Guest", "operation": 2},
        ]},
    })
    assert [p["ssid"] for p in ap._ssid_stats(0)] == ["Corp-Renamed"]

    # Delete the last remaining SSID.
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp-Renamed", "operation": 2},
        ]},
    })
    assert ap._ssid_stats(0) == []


def test_ap_explicit_empty_ssid_config_produces_no_active_profiles():
    """An explicit empty ``ssid`` list differs from the pre-push state: it
    must not resurrect the fallback profile."""
    runner, ap = _runner_with_chain()
    ap.build_set_response({"ssid_2G": {"radioId": 0, "ssid": []}})
    assert ap._active_ssids_for_radio(0) == []
    assert ap._ssid_stats(0) == []


def test_ap_hidden_ssid_remains_active():
    runner, ap = _runner_with_chain()
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Hidden", "ssidBcast": False},
        ]},
    })
    profiles = ap._active_ssids_for_radio(0)
    assert len(profiles) == 1
    assert profiles[0]["ssidName"] == "Hidden"
    assert profiles[0]["ssidBcast"] is False
    assert [p["ssid"] for p in ap._ssid_stats(0)] == ["Hidden"]


def test_ap_same_ssid_name_on_different_bands_is_independent():
    runner, ap = _runner_with_chain()
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [{"id": 1, "ssidName": "Home"}]},
        "ssid_5G": {"radioId": 1, "ssid": [{"id": 1, "ssidName": "Home"}]},
    })
    b2 = ap._ssid_stats(0)[0]["bssid"]
    b5 = ap._ssid_stats(1)[0]["bssid"]
    assert b2 != b5


def test_ap_bssid_stable_and_unique_across_profiles_and_restarts():
    runner, ap = _runner_with_chain()
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp"}, {"id": 2, "ssidName": "Guest"},
        ]},
    })
    first = {p["ssid"]: p["bssid"] for p in ap._ssid_stats(0)}
    assert first["Corp"] != first["Guest"]
    assert ap.mac not in first.values()

    # A second AP instance with the same MAC and the same push reproduces the
    # same BSSIDs (stability across restarts).
    runner2, ap2 = _runner_with_chain()
    ap2.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp"}, {"id": 2, "ssidName": "Guest"},
        ]},
    })
    second = {p["ssid"]: p["bssid"] for p in ap2._ssid_stats(0)}
    assert first == second

    # BSSIDs never equal a synthesized client MAC.
    from device_emulator.devices.clients import synthesize_site_clients
    synthesize_site_clients(runner.devices)
    client_macs = {c.mac for c in ap.reported_clients}
    assert not (set(first.values()) & client_macs)


def test_ap_five_clients_across_two_ssids_round_robin_and_counts():
    runner, ap = _runner_with_chain(wireless_client_count=5)
    from device_emulator.devices.clients import synthesize_site_clients
    synthesize_site_clients(runner.devices)
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp"}, {"id": 2, "ssidName": "Guest"},
        ]},
    })
    extra = ap.manage_inform_extra()
    radio0_clients = [c for c in extra["clients"] if c["rid"] == 0]
    # 3 clients on radio 0 (indices 0,2,4), round-robin across 2 profiles.
    ssid_seq = [c["ssid"] for c in sorted(radio0_clients, key=lambda c: c["mac"])]
    assert ssid_seq == ["Corp", "Guest", "Corp"]
    stats_by_ssid = {row["ssid"]: row for row in extra["ssidStats_2G"]}
    assert stats_by_ssid["Corp"]["clntNum"] == 2
    assert stats_by_ssid["Guest"]["clntNum"] == 1
    assert stats_by_ssid["Corp"]["clntNum"] + stats_by_ssid["Guest"]["clntNum"] == len(radio0_clients)


def test_ap_more_ssids_than_clients_keeps_zero_client_rows():
    runner, ap = _runner_with_chain(wireless_client_count=0)
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp"}, {"id": 2, "ssidName": "Guest"},
        ]},
    })
    rows = ap._ssid_stats(0)
    assert [r["ssid"] for r in rows] == ["Corp", "Guest"]
    assert all(r["clntNum"] == 0 for r in rows)


def test_ap_same_ssid_name_different_ids_kept_distinct():
    runner, ap = _runner_with_chain()
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Dup"}, {"id": 2, "ssidName": "Dup"},
        ]},
    })
    rows = ap._ssid_stats(0)
    assert len(rows) == 2
    assert rows[0]["bssid"] != rows[1]["bssid"]
    assert rows[0]["id"] != rows[1]["id"]


def test_ap_vlan_and_guest_propagation():
    runner, ap = _runner_with_chain(wireless_client_count=2)
    from device_emulator.devices.clients import synthesize_site_clients
    synthesize_site_clients(runner.devices)
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp", "vlanId": 20, "portal": True},
        ]},
    })
    extra = ap.manage_inform_extra()
    radio0_clients = [c for c in extra["clients"] if c["rid"] == 0]
    assert radio0_clients and all(c["vlan"] == 20 for c in radio0_clients)
    assert all(c["guest"] == 1 for c in radio0_clients)


def test_ap_traffic_and_packet_sums_equal_assigned_client_totals():
    runner, ap = _runner_with_chain(wireless_client_count=5)
    from device_emulator.devices.clients import synthesize_site_clients
    synthesize_site_clients(runner.devices)
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp"}, {"id": 2, "ssidName": "Guest"},
        ]},
    })
    extra = ap.manage_inform_extra()
    radio0_clients = [c for c in extra["clients"] if c["rid"] == 0]
    total_down = sum(c["down"] for c in radio0_clients)
    total_up = sum(c["up"] for c in radio0_clients)
    stats_down = sum(row["down"] for row in extra["ssidStats_2G"])
    stats_up = sum(row["up"] for row in extra["ssidStats_2G"])
    assert stats_down == total_down
    assert stats_up == total_up


def test_ap_disabled_radio_and_deleted_last_ssid_suppress_clients_and_stats():
    runner, ap = _runner_with_chain(wireless_client_count=5)
    from device_emulator.devices.clients import synthesize_site_clients
    synthesize_site_clients(runner.devices)
    # Delete the last SSID on radio 1 (5G).
    ap.build_set_response({
        "ssid_5G": {"radioId": 1, "ssid": [{"id": 1, "ssidName": "Only", "operation": 2}]},
    })
    extra = ap.manage_inform_extra()
    assert all(c["rid"] != 1 for c in extra["clients"])
    assert extra["ssidStats_5G"] == []
    # Disable radio 0 entirely.
    ap.build_set_response({"wirelessBasic_2G": {"radioId": 0, "radioEnable": False}})
    extra = ap.manage_inform_extra()
    assert all(c["rid"] != 0 for c in extra["clients"])
    assert "ssidStats_2G" not in extra


def test_gateway_reports_all_five_ap_clients_regardless_of_ssid():
    runner, ap = _runner_with_chain(wireless_client_count=5)
    from device_emulator.devices.clients import synthesize_site_clients
    synthesize_site_clients(runner.devices)
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [{"id": 1, "ssidName": "Corp"}]},
        "ssid_5G": {"radioId": 1, "ssid": [{"id": 1, "ssidName": "Guest"}]},
    })
    gw = runner.devices[0]
    from device_emulator.protocol import constants
    assert gw.device_type == constants.DEVICE_TYPE_GATEWAY
    # 5 AP wireless clients + 1 switch wired client from _runner_with_chain.
    assert len(gw.reported_clients) == 6

# -- SSID CRUD operation semantics tests -------------------------------

def _ap_for_ssid():
    from device_emulator.devices.registry import build_device
    return build_device(
        {"name": "ap-ssid", "type": "ap", "mac": "AC-DE-48-00-00-10",
         "ip": "192.168.56.10", "wireless_client_count": 0}
    )


def test_ssid_snapshot_no_operation_treated_as_full_list():
    """A SET with no operation field (snapshot) replaces the radio's SSIDs."""
    ap = _ap_for_ssid()
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp"},
            {"id": 2, "ssidName": "Guest"},
        ]},
    })
    assert len(ap._active_ssids_by_radio[0]) == 2
    assert ap._active_ssids_by_radio[0][0]["ssidName"] == "Corp"


def test_ssid_operation_add():
    """operation==1 adds a new SSID to the existing list."""
    ap = _ap_for_ssid()
    # Start with a snapshot.
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [{"id": 1, "ssidName": "Corp"}]},
    })
    # Add a new SSID.
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 2, "ssidName": "Guest", "operation": 1},
        ]},
    })
    names = [p["ssidName"] for p in ap._active_ssids_by_radio[0]]
    assert "Corp" in names and "Guest" in names
    assert len(ap._active_ssids_by_radio[0]) == 2


def test_ssid_operation_delete():
    """operation==2 removes the matching SSID."""
    ap = _ap_for_ssid()
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp"},
            {"id": 2, "ssidName": "Guest"},
        ]},
    })
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "operation": 2},
        ]},
    })
    names = [p["ssidName"] for p in ap._active_ssids_by_radio[0]]
    assert "Corp" not in names
    assert "Guest" in names


def test_ssid_operation_update():
    """operation==3 updates the matching SSID's fields, preserving profile_key."""
    ap = _ap_for_ssid()
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [{"id": 1, "ssidName": "Corp"}]},
    })
    old_key = ap._active_ssids_by_radio[0][0]["profile_key"]
    # Update the SSID name.
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp-Updated", "operation": 3, "vlanId": 100},
        ]},
    })
    profiles = ap._active_ssids_by_radio[0]
    assert len(profiles) == 1
    assert profiles[0]["ssidName"] == "Corp-Updated"
    assert profiles[0]["vlanId"] == 100
    # profile_key preserved (stable identity for client assignments).
    assert profiles[0]["profile_key"] == old_key


def test_ssid_add_duplicate_does_not_double():
    """Adding an SSID that already exists (by name) doesn't create a duplicate."""
    ap = _ap_for_ssid()
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [{"id": 1, "ssidName": "Corp"}]},
    })
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp", "operation": 1},
        ]},
    })
    assert len(ap._active_ssids_by_radio[0]) == 1


def test_ssid_snapshot_with_delete_operation_filters_entry():
    """In a snapshot, an entry with operation==2 is filtered out."""
    ap = _ap_for_ssid()
    ap.build_set_response({
        "ssid_2G": {"radioId": 0, "ssid": [
            {"id": 1, "ssidName": "Corp"},
            {"id": 2, "ssidName": "Guest", "operation": 2},
        ]},
    })
    # All ops are 0 or 2, so this is treated as a snapshot — entry 2 filtered.
    names = [p["ssidName"] for p in ap._active_ssids_by_radio[0]]
    assert "Corp" in names and "Guest" not in names
