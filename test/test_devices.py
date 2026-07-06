"""Unit tests for device classes and the config-driven device registry."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from device_emulator.devices.eap import EapDevice
from device_emulator.devices.gateway import GatewayDevice
from device_emulator.devices.olt import OltDevice
from device_emulator.devices.registry import build_device
from device_emulator.devices.switch import SwitchDevice


def test_build_device_ap():
    device = build_device(
        {
            "name": "lab-eap-01",
            "type": "ap",
            "model": "EAP245",
            "mac": "02:15:6d:00:00:20",
            "ip": "192.168.56.53",
        }
    )
    assert isinstance(device, EapDevice)
    assert device.device_type == "ap"
    assert device.mac == "02-15-6D-00-00-20"


def test_build_device_switch():
    device = build_device(
        {"name": "sw-01", "type": "switch", "mac": "02:15:6d:00:00:10", "ip": "192.168.56.60"}
    )
    assert isinstance(device, SwitchDevice)
    assert device.device_type == "switch"


def test_build_device_gateway():
    device = build_device(
        {"name": "gw-01", "type": "gateway", "mac": "02:15:6d:00:00:30", "ip": "192.168.56.70"}
    )
    assert isinstance(device, GatewayDevice)
    assert device.device_type == "gateway"


def test_build_device_auto_detects_ip():
    # ``ip: auto`` (or missing) auto-detects the host's primary non-loopback IP.
    device = build_device(
        {"name": "auto-ip", "type": "ap", "mac": "02:15:6d:00:00:99", "ip": "auto"}
    )
    assert isinstance(device, EapDevice)
    # The auto-detected IP should be a valid non-empty string.
    assert device.ip and "." in device.ip
    # A missing ip also auto-detects.
    device2 = build_device(
        {"name": "no-ip", "type": "ap", "mac": "02:15:6d:00:00:98"}
    )
    assert device2.ip and "." in device2.ip


def test_build_device_requires_mac():
    with pytest.raises(ValueError):
        build_device({"name": "bad", "type": "ap", "ip": "192.168.56.99"})


def test_discovery_message_requires_controller_id():
    device = build_device(
        {"name": "lab-eap-01", "type": "ap", "mac": "02:15:6d:00:00:20", "ip": "192.168.56.53"}
    )
    with pytest.raises(ValueError):
        device.build_discovery_message()

    device.controller_id = "6e4b42bfc99261c0e09bec9f8688d9c7"
    message = device.build_discovery_message()
    assert message.header.mac == device.mac


def test_eap_reports_nonempty_components_v2():
    # An empty component manifest makes the controller flag the AP as
    # incompatible, so the emulated AP must report a non-empty set.
    device = build_device(
        {"name": "ap", "type": "ap", "model": "EAP245", "mac": "AA-BB-CC-DD-EE-01", "ip": "192.168.56.5"}
    )
    comps = device.manage_components_v2()
    assert isinstance(comps, dict) and comps
    assert comps.get("ssid")  # a representative component is present


def test_eap_negotiation_reports_dual_band_radio_capabilities():
    device = build_device(
        {"name": "ap", "type": "ap", "model": "EAP245", "mac": "AA-BB-CC-DD-EE-01", "ip": "192.168.56.5"}
    )
    body = device.build_manage_negotiation_body("cid")

    assert [item["radioId"] for item in body["channelInfo"]] == [0, 1]
    assert [item["radioId"] for item in body["radioCap"]] == [0, 1]
    assert all(item["supportSsidNum"] == 8 for item in body["radioCap"])
    for item in body["channelInfo"]:
        assert item["channelList"]
        assert all(
            set(channel) == {"fr", "vl", "mPow", "cFlag", "dFlag", "lm"}
            for channel in item["channelList"]
        )


def test_switch_and_gateway_report_components_and_v22_version():
    # Switches and gateways also report a non-empty component manifest and are
    # classified at ECSP protocol version 2.2 (APs use 2.3).
    switch = build_device(
        {"name": "sw", "type": "switch", "model": "TL-SG3210", "mac": "AA-BB-CC-DD-EE-02", "ip": "192.168.56.6"}
    )
    gateway = build_device(
        {"name": "gw", "type": "gateway", "model": "ER605", "mac": "AA-BB-CC-DD-EE-03", "ip": "192.168.56.7"}
    )
    assert switch.manage_components_v2() and gateway.manage_components_v2()
    assert switch.protocol_version == "2.2.0"
    assert gateway.protocol_version == "2.2.0"
    # Switch/gateway device info uses the short-name shape.
    assert "modelVer" in switch.manage_device_info()
    assert gateway.manage_device_info()["lanMac"] == "AA-BB-CC-DD-EE-03"
    # Negotiation body carries the type-specific capability descriptor.
    assert "devCap" in switch.build_manage_negotiation_body("cid")
    assert "portInfos" in gateway.build_manage_negotiation_body("cid")["devCap"]


def test_build_device_olt():
    device = build_device(
        {"name": "olt-01", "type": "olt", "mac": "02:15:6d:00:00:40", "ip": "192.168.56.80"}
    )
    assert isinstance(device, OltDevice)
    assert device.device_type == "olt"


def test_olt_reports_nonempty_components_v2_and_v22_version():
    # OLT is a V2 wired device: it advertises ECSP 2.2 and a non-empty
    # component manifest (an empty manifest makes the controller flag the
    # device as incompatible).
    device = build_device(
        {"name": "olt", "type": "olt", "model": "DS-P7001-08", "mac": "AA-BB-CC-DD-EE-04", "ip": "192.168.56.8"}
    )
    comps = device.manage_components_v2()
    assert isinstance(comps, dict) and comps
    assert comps.get("ponPort")
    assert comps.get("onuManagement")
    assert comps.get("centralManagement")
    assert device.protocol_version == "2.2.0"


def test_olt_discovery_body_uses_controller_id_convention():
    # The OLT discovery body uses the long-name deviceInfo keys (like an AP)
    # BUT the switch/gateway controller/id convention (NOT the AP-style
    # controllerSetting/controllerId): the OLT discovery controller setting maps
    # its controllerId field with JSON key "id" and the body wrapper maps
    # controllerSetting with JSON key "controller".
    device = build_device(
        {"name": "olt", "type": "olt", "mac": "AA-BB-CC-DD-EE-04", "ip": "192.168.56.8"}
    )
    device.controller_id = "cid"
    body = device.build_discovery_body()
    assert "controller" in body
    assert "controllerSetting" not in body
    assert body["controller"]["id"] == "cid"
    info = body["deviceInfo"]
    # Long-name version fields (AP-style), not the switch/gateway short names.
    assert "modelVersion" in info and "firmwareVersion" in info and "hardwareVersion" in info
    # upTime is a JSON integer (Long), not a string.
    assert isinstance(info["upTime"], int)
    # deviceMisc is the base device misc shape (modelType/category/supportCluster), not
    # the OLT PON fields (ponPortCount/lagCount live in the adopt deviceInfo).
    assert body["deviceMisc"]["category"] == "OLT"


def test_olt_negotiation_uses_adopt_resp_body_shape():
    # The OLT's DEVICE_NEGOTIATION body is parsed by the controller directly
    # as the OLT adopt response body (NOT the generic components_v2/devCap/deviceMisc
    # envelope used by APs/switches/gateways): it carries `components`
    # (a string-to-string map, must be non-null + include `centralManagement`),
    # `deviceInfo` (the OLT adopt device info) and `isFactoryDefault`.
    device = build_device(
        {"name": "olt", "type": "olt", "mac": "AA-BB-CC-DD-EE-04", "ip": "192.168.56.8"}
    )
    info = device.manage_device_info()
    assert "modelVersion" in info and "firmwareVersion" in info
    assert info["ponPortCount"] == 8
    assert info["lagCount"] == 0
    assert info["wirelessLinked"] is False
    neg = device.build_manage_negotiation_body("cid")
    assert isinstance(neg["components"], dict) and neg["components"]
    assert "centralManagement" in neg["components"]
    assert neg["isFactoryDefault"] is True
    assert neg["deviceInfo"] == info


def test_olt_inform_reports_traffic_stat_per_pon_port():
    # The OLT INFORM body uses the OLT inform shape: the deviceInfo is the
    # OLT inform device info (with onuCount/portOnuCount, which the controller
    # unboxes without null checks), plus per-PON-port trafficStat.
    device = build_device(
        {"name": "olt", "type": "olt", "mac": "AA-BB-CC-DD-EE-04", "ip": "192.168.56.8",
         "pon_port_count": 4}
    )
    body = device.manage_inform_body()
    # deviceInfo is the inform shape (the OLT inform device info), not the adopt shape.
    info = body["deviceInfo"]
    assert "onuCount" in info and isinstance(info["onuCount"], int)
    assert "portOnuCount" in info and len(info["portOnuCount"]) == 4
    assert "cpuUti" in info and "memUti" in info and "upTime" in info
    # trafficStat carries per-PON-port port stats with multicast/broadcast.
    assert "trafficStat" in body
    ports = body["trafficStat"]["portStats"]
    assert len(ports) == 4
    p0 = ports[0]
    assert p0["port"] == 1 and p0["linkStatus"] == 1
    for key in ("rx", "tx", "rxP", "txP", "rxMP", "txMP", "rxBP", "txBP"):
        assert key in p0


def test_olt_set_response_captures_controller_info_and_high_ability():
    # The OLT SET key set defines exactly two SET keys -- controllerInfo and
    # highAbility -- plus the upgrade push (the upgrade config).
    # build_set_response should ack and capture each pushed dict so a later
    # GET can echo it.
    device = build_device(
        {"name": "olt", "type": "olt", "mac": "AA-BB-CC-DD-EE-04", "ip": "192.168.56.8"}
    )
    req = {
        "sequenceId": 1,
        "configVersion": 2,
        "controllerInfo": {"ip": "10.0.0.1", "discoverPort": 29810, "managePort": 29814},
        "highAbility": {"mod": 0, "ips": []},
        "upgrade": {"reboot": 0, "interval": 0},
    }
    resp = device.build_set_response(req)
    assert resp["errcode"] == 0
    assert resp["sequenceId"] == 1
    assert resp["configVersion"] == 2
    assert device._applied_configs["controllerInfo"] == req["controllerInfo"]
    assert device._applied_configs["highAbility"] == req["highAbility"]
    assert device._applied_configs["upgrade"] == req["upgrade"]


def test_olt_applied_config_is_isolated_from_request_mutation():
    device = build_device(
        {"name": "olt", "type": "olt", "mac": "AA-BB-CC-DD-EE-04", "ip": "192.168.56.8"}
    )
    request = {"highAbility": {"ips": [{"ip": "10.0.0.1"}]}}
    device.build_set_response(request)
    request["highAbility"]["ips"][0]["ip"] = "10.0.0.99"
    assert device._applied_configs["highAbility"]["ips"][0]["ip"] == "10.0.0.1"


def test_olt_uri_get_uses_device_response_body_shape():
    # OLT detail queries use a request body with {uri, params} and require the
    # device response body wrapper, not a flat config response. A covered
    # URI returns a synthetic payload; an uncovered URI returns data:null.
    device = build_device(
        {"name": "olt", "type": "olt", "mac": "AA-BB-CC-DD-EE-04", "ip": "192.168.56.8"}
    )
    resp = device.build_get_response({"uri": "pon/pon-port/informations/list", "params": {}})
    assert resp["deviceType"] == "olt"
    assert resp["errcode"] == 0
    assert resp["message"] == ""
    assert isinstance(resp["data"], list)
    # uncovered URI still returns data:null
    resp2 = device.build_get_response({"uri": "unknown/uri", "params": {}})
    assert resp2["data"] is None


def test_olt_uri_set_uses_device_response_body_without_capturing_params():
    device = build_device(
        {"name": "olt", "type": "olt", "mac": "AA-BB-CC-DD-EE-04", "ip": "192.168.56.8"}
    )
    resp = device.build_set_response({
        "uri": "system-tools/reboot/now",
        "params": {"saveCurrentConfig": True},
    })
    assert resp["deviceType"] == "olt"
    assert resp["errcode"] == 0
    # reboot returns a status payload, not null
    assert resp["data"] == {"status": "SUCCESS"}
    assert device._applied_configs == {}


def test_olt_get_response_empty_when_nothing_pushed():
    # A non-URI request retains the generic base ack for forward compatibility.
    device = build_device(
        {"name": "olt", "type": "olt", "mac": "AA-BB-CC-DD-EE-04", "ip": "192.168.56.8"}
    )
    resp = device.build_get_response({"sequenceId": 1})
    assert resp["errcode"] == 0
    assert "controllerInfo" not in resp
    assert "highAbility" not in resp


# -- OLT detail-ops URI-RPC dispatch ---------------------------------


def _olt():
    return build_device(
        {"name": "olt", "type": "olt", "model": "DS-P7001-08",
         "mac": "AA-BB-CC-DD-EE-04", "ip": "192.168.56.8", "pon_port_count": 8}
    )


def _get(device, uri, params=None):
    return device.build_get_response({"uri": uri, "params": params or {}})


def _set(device, uri, params=None):
    return device.build_set_response({"uri": uri, "params": params or {}})


def test_olt_pon_port_informations():
    device = _olt()
    data = _get(device, "pon/pon-port/informations/list")["data"]
    assert isinstance(data, list)
    assert len(data) == 8  # pon_port_count
    port = data[0]
    assert port["portId"] == 1
    assert port["status"] == "ENABLE"
    assert "opticalPower" in port
    assert "onuNum" in port


def test_olt_onu_information_list():
    device = _olt()
    data = _get(device, "pon/onu/management/information/list")["data"]
    assert isinstance(data, list)
    assert len(data) > 0
    onu = data[0]
    assert "onuId" in onu
    assert "serialNumber" in onu
    assert "macAddress" in onu
    assert onu["onlineStatus"] in ("ONLINE", "OFFLINE")
    assert onu["adminStatus"] == "ACTIVATE"


def test_olt_dba_profiles():
    device = _olt()
    data = _get(device, "profile/dba/profiles/list")["data"]
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "dbaId" in data[0]
    assert "type" in data[0]


def test_olt_line_profiles_and_children():
    device = _olt()
    profiles = _get(device, "profile/line/profiles/list")["data"]
    assert len(profiles) >= 1
    assert "lineProfileId" in profiles[0]
    assert "mappingMode" in profiles[0]

    tconts = _get(device, "profile/line/t-conts/list")["data"]
    assert len(tconts) >= 1
    assert "tcontId" in tconts[0]

    gems = _get(device, "profile/line/gem-ports/list")["data"]
    assert len(gems) >= 1
    assert "gemPortId" in gems[0]


def test_olt_service_profiles():
    device = _olt()
    data = _get(device, "profile/service/profiles/list")["data"]
    assert len(data) >= 1
    assert "serviceId" in data[0]
    assert "ethNum" in data[0]


def test_olt_traffic_profiles():
    device = _olt()
    data = _get(device, "profile/traffic/profiles/list")["data"]
    assert len(data) >= 1
    assert "trafficId" in data[0]
    assert "cirValue" in data[0]


def test_olt_service_ports():
    device = _olt()
    data = _get(device, "pon/service-ports/list")["data"]
    assert isinstance(data, list)
    if data:
        assert "gemPortId" in data[0]
        assert "ponPortId" in data[0]
        assert "tagAction" in data[0]


def test_olt_vlan_configs():
    device = _olt()
    data = _get(device, "vlan/8021q/vlan-configs/list")["data"]
    assert len(data) >= 1
    assert "vlanId" in data[0]
    assert "vlanName" in data[0]


def test_olt_stp_summary():
    device = _olt()
    data = _get(device, "stp/summary/summarys/get")["data"]
    assert isinstance(data, dict)
    assert data["spanningTree"] == "ENABLE"
    assert "spanningTreeMode" in data


def test_olt_lldp_global():
    device = _olt()
    data = _get(device, "lldp/global/configs/get")["data"]
    assert isinstance(data, dict)
    assert "txInterval" in data


def test_olt_routing_table_ipv4():
    device = _olt()
    data = _get(device, "routing-table/ipv4-tables/list")["data"]
    assert len(data) >= 1
    assert "destIp" in data[0]
    assert "nextHop" in data[0]


def test_olt_arp_table():
    device = _olt()
    data = _get(device, "arp/arp-tables/list")["data"]
    assert len(data) >= 1
    assert "ipAddress" in data[0]
    assert "macAddress" in data[0]


def test_olt_igmp_global():
    device = _olt()
    data = _get(device, "igmp/global-config/get")["data"]
    assert data["status"] == "ENABLE"
    assert "version" in data


def test_olt_mvr_config():
    device = _olt()
    data = _get(device, "mvr/config/configs/get")["data"]
    assert "status" in data
    assert "multicastVlanId" in data


def test_olt_acl_configs():
    device = _olt()
    data = _get(device, "acl/configs/list")["data"]
    assert len(data) >= 1
    assert "aclId" in data[0]
    assert "aclType" in data[0]


def test_olt_system_info():
    device = _olt()
    data = _get(device, "system-info/configs/get")["data"]
    assert data["mac"] == "AA-BB-CC-DD-EE-04"
    assert "firmwareVersion" in data
    assert "hardwareVersion" in data


def test_olt_system_monitor_cpu_memory():
    device = _olt()
    cpu = _get(device, "system-monitor/cpu/list")["data"]
    assert len(cpu) == 1
    assert "cpuUti" in cpu[0]
    mem = _get(device, "system-monitor/memory/list")["data"]
    assert len(mem) == 1
    assert "memUti" in mem[0]


def test_olt_board_control():
    device = _olt()
    data = _get(device, "system/board/control-board/load")["data"]
    assert "boardDetail" in data
    assert data["boardDetail"]["runningStatus"] == "RUNNING"
    assert "boardControl" in data


def test_olt_ddm_status():
    device = _olt()
    data = _get(device, "ddm/status/info/get")["data"]
    assert "ports" in data
    assert len(data["ports"]) == 8
    port = data["ports"][0]
    assert "temperature" in port
    assert "txPower" in port
    assert "rxPower" in port
    assert port["temperatureFlag"] == "NORMAL"


def test_olt_users():
    device = _olt()
    data = _get(device, "user-management/users/list")["data"]
    assert len(data) >= 1
    assert data[0]["userName"] == "admin"
    assert data[0]["accessLevelType"] == "ADMIN"


def test_olt_eth_port_unit1():
    device = _olt()
    data = _get(device, "eth-port/port/unit1/list")["data"]
    assert len(data) >= 1
    assert "port" in data[0]
    assert "speed" in data[0]
    assert data[0]["linkStatus"] == "UP"


def test_olt_diagnostics_ping_config():
    device = _olt()
    data = _get(device, "diagnostics/ping/configs/get")["data"]
    assert "target" in data
    assert "count" in data


def test_olt_set_mutation_returns_null_data():
    device = _olt()
    # A config-mutation SET (e.g. VLAN add) returns data:null, errcode:0.
    resp = _set(device, "vlan/8021q/vlan-configs/add", {"vlanId": 300})
    assert resp["errcode"] == 0
    assert resp["data"] is None


def test_olt_set_reboot_returns_status():
    device = _olt()
    resp = _set(device, "system-tools/reboot/now", {"saveCurrentConfig": True})
    assert resp["data"] == {"status": "SUCCESS"}


def test_olt_set_config_backup_returns_status():
    device = _olt()
    resp = _set(device, "system-tools/config/backup", {})
    assert resp["data"] == {"status": "SUCCESS"}


def test_olt_unknown_uri_get_returns_null_data():
    device = _olt()
    resp = _get(device, "some/future/uri/get", {})
    assert resp["errcode"] == 0
    assert resp["data"] is None


def test_olt_detail_ops_deterministic():
    # Same MAC + params → same output (deterministic synthetic data).
    d1 = _olt()
    d2 = _olt()
    r1 = _get(d1, "pon/pon-port/informations/list")["data"]
    r2 = _get(d2, "pon/pon-port/informations/list")["data"]
    assert r1 == r2


def test_olt_detail_ops_pon_count_varies():
    # Different pon_port_count → different number of PON port entries.
    d4 = build_device(
        {"name": "olt", "type": "olt", "mac": "AA-BB-CC-DD-EE-04",
         "ip": "192.168.56.8", "pon_port_count": 4}
    )
    data = _get(d4, "pon/pon-port/informations/list")["data"]
    assert len(data) == 4


# -- OLT firmware upgrade tests ---------------------------------------


def test_olt_firmware_upgrade_set_records_state():
    """A system-tools/firmware/upgrade SET records the upgrade state."""
    device = build_device(
        {"name": "olt", "type": "olt", "mac": "AA-BB-CC-DD-EE-04", "ip": "192.168.56.8"}
    )
    resp = device.build_set_response({
        "uri": "system-tools/firmware/upgrade",
        "params": {"version": "2.0.0", "reboot": True},
    })
    assert resp["errcode"] == 0
    assert resp["data"]["status"] == "success"
    assert resp["data"]["newVersion"] == "2.0.0"
    # The image-table GET should now reflect the new version.
    img = device.build_get_response({
        "uri": "system-tools/image-table/list", "params": {}
    })["data"]
    assert any(e.get("version") == "2.0.0" for e in img)


def test_olt_upgrade_config_push_records_state():
    """An OLT config upgrade push records the upgrade state."""
    from device_emulator.devices import olt_detail_ops
    device = build_device(
        {"name": "olt", "type": "olt", "mac": "AA-BB-CC-DD-EE-04", "ip": "192.168.56.8"}
    )
    device.build_set_response({
        "sequenceId": 1, "configVersion": 1,
        "upgrade": {"reboot": 1, "interval": 0, "newVersion": "2.1.0"},
    })
    state = olt_detail_ops._UPGRADE_STATE.get(device.mac)
    assert state is not None
    assert state["status"] == "success"
    assert state["newVersion"] == "2.1.0"


def test_olt_firmware_upgrade_status_get():
    """system-tools/firmware/upgrade/status GET returns the upgrade state."""
    # Use a distinct MAC so no prior test's upgrade state leaks.
    device = build_device(
        {"name": "olt", "type": "olt", "mac": "AA-BB-CC-DD-EE-09", "ip": "192.168.56.8"}
    )
    # Before any upgrade, status is idle.
    resp = device.build_get_response({
        "uri": "system-tools/firmware/upgrade/status", "params": {}
    })
    assert resp["data"]["status"] == "idle"
