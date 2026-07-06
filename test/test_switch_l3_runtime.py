"""Unit tests for the switch LAG / SFP-DDM / per-port STP runtime INFORM
sections and the extended SET/GET response flow."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.devices.registry import build_device


def _make_switch():
    sw = build_device(
        {
            "name": "sw-01",
            "type": "switch",
            "model": "TL-SG3210",
            "mac": "AA-BB-CC-DD-EE-02",
            "ip": "192.168.56.60",
            "uplink": "gw-01",
            "uplink_port": 1,
        }
    )
    # Give the switch a couple of downlinks so LAG groups can form.
    from device_emulator.devices.topology import LinkNeighbor, TopologyNeighbors

    sw.topology = TopologyNeighbors(
        uplink=LinkNeighbor(
            mac="AA-BB-CC-DD-EE-03", model="ER605", device_type="gateway",
            local_port=1, remote_port=2,
        ),
        downlinks=[
            LinkNeighbor(
                mac="AA-BB-CC-DD-EE-01", model="EAP245", device_type="ap",
                local_port=2, remote_port=1,
            ),
            LinkNeighbor(
                mac="AA-BB-CC-DD-EE-04", model="EAP245", device_type="ap",
                local_port=3, remote_port=1,
            ),
        ],
    )
    return sw


def test_switch_inform_has_lag_ddm_stp_sections():
    sw = _make_switch()
    extra = sw.manage_inform_extra()
    for key in ("lag", "ddm", "stpInform"):
        assert key in extra, f"missing {key} section"


def test_switch_lag_section_shape():
    sw = _make_switch()
    lag = sw.manage_inform_extra()["lag"]
    assert "lags" in lag and "rates" in lag
    # With 2 downlinks, at least 1 LAG group should form.
    assert len(lag["lags"]) >= 1
    entry = lag["lags"][0]
    assert "lag" in entry and "stMembers" in entry
    assert isinstance(entry["stMembers"], list) and len(entry["stMembers"]) == 2
    assert "duplex" in entry


def test_switch_lag_rates_shape():
    sw = _make_switch()
    rates = sw.manage_inform_extra()["lag"]["rates"]
    if rates:
        r = rates[0]
        assert "lag" in r


def test_switch_ddm_section_shape():
    sw = _make_switch()
    ddm = sw.manage_inform_extra()["ddm"]
    assert "ports" in ddm
    # TL-SG3210 has 2 SFP ports.
    assert len(ddm["ports"]) == 2
    entry = ddm["ports"][0]
    # Verify all DDM measurement categories are nested objects.
    for prefix in ("tem", "vol", "bc", "tx", "rx"):
        assert prefix in entry, f"missing {prefix} field"
        assert isinstance(entry[prefix], dict), f"{prefix} should be a nested object"
        assert f"{prefix}0" in entry[prefix], f"missing {prefix}0 raw value"
        for suffix in ("Ha", "Hw", "La", "Lw", "St"):
            assert f"{prefix}{suffix}" in entry[prefix], f"missing {prefix}{suffix}"
    assert "standardPort" in entry and "port" in entry
    assert "txFault" in entry and "rxLos" in entry


def test_switch_stp_inform_section_shape():
    sw = _make_switch()
    stp = sw.manage_inform_extra()["stpInform"]
    assert "ports" in stp
    # All linked ports should report STP state.
    assert len(stp["ports"]) >= 2
    entry = stp["ports"][0]
    for f in ("port", "standardPort", "stpState", "stpVlan"):
        assert f in entry


def test_switch_set_response_captures_lag_stp():
    sw = _make_switch()
    req = {
        "sequenceId": 1,
        "configVersion": 3,
        "lag": {"enable": 1, "groups": []},
        "stp": {"enable": 1, "mode": 0},
        "portStp": {"ports": []},
    }
    resp = sw.build_set_response(req)
    assert resp["errcode"] == 0
    assert sw._applied_lag == {"enable": 1, "groups": []}
    assert sw._applied_stp == {"enable": 1, "mode": 0}
    assert sw._applied_port_stp == {"ports": []}


def test_switch_get_response_echoes_lag_stp():
    sw = _make_switch()
    sw.build_set_response({
        "sequenceId": 1,
        "configVersion": 3,
        "lag": {"enable": 1},
        "stp": {"enable": 1, "mode": 0},
    })
    resp = sw.build_get_response({"sequenceId": 10})
    assert resp["errcode"] == 0
    assert resp["lag"] == {"enable": 1}
    assert resp["stp"] == {"enable": 1, "mode": 0}


def test_switch_applied_config_is_isolated_from_mutation():
    sw = _make_switch()
    request = {"lag": {"groups": [{"id": 1, "members": [1, 2]}]}}
    sw.build_set_response(request)
    request["lag"]["groups"][0]["id"] = 99
    response = sw.build_get_response({})
    assert response["lag"]["groups"][0]["id"] == 1
    response["lag"]["groups"][0]["id"] = 42
    assert sw.build_get_response({})["lag"]["groups"][0]["id"] == 1


def test_switch_full_inform_body_contains_new_sections():
    sw = _make_switch()
    body = sw.manage_inform_body()
    for key in ("deviceInfo", "port", "poe", "client", "routingTable",
                "loopback", "lag", "ddm", "stpInform"):
        assert key in body, f"INFORM body missing {key}"


def test_switch_profile_advertises_ddm_stp_components():
    sw = _make_switch()
    comps = sw.manage_components_v2()
    assert "lag" in comps
    assert "stp" in comps
    assert "ddm" in comps
    assert "ddmInform" in comps
    assert "stpInform" in comps