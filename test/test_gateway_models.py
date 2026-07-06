"""Unit tests for multi-model gateway profile selection and capability-gated
INFORM sections."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.devices.gateway_profiles import get_profile
from device_emulator.devices.registry import build_device


def _make_gateway(model="ER605", mac="AA-BB-CC-DD-EE-03"):
    return build_device({
        "name": f"gw-{model.lower()}",
        "type": "gateway",
        "model": model,
        "mac": mac,
        "ip": "192.168.56.70",
    })


# -- Profile selection --------------------------------------------------------

def test_get_profile_er605():
    p = get_profile("ER605")
    assert p.PROTOCOL_VERSION == "2.2.0"
    assert p.DEVICE_INFO_TEMPLATE["model"] == "ER605"
    assert not p.SUPPORT_LTE
    assert not p.SUPPORT_SDWAN


def test_get_profile_er706w():
    p = get_profile("ER706W")
    assert p.DEVICE_INFO_TEMPLATE["model"] == "ER706W"
    assert p.SUPPORT_LTE
    assert p.SUPPORT_DISCRETE_WAN
    assert p.SUPPORT_WAN_LOAD_BALANCE


def test_get_profile_er7206():
    p = get_profile("ER7206")
    assert p.DEVICE_INFO_TEMPLATE["model"] == "ER7206"
    assert p.SUPPORT_SDWAN
    assert p.SUPPORT_DISCRETE_WAN
    assert p.SUPPORT_WAN_LOAD_BALANCE


def test_get_profile_er8411():
    p = get_profile("ER8411")
    assert p.DEVICE_INFO_TEMPLATE["model"] == "ER8411"
    assert p.SUPPORT_SDWAN
    assert p.SUPPORT_DISCRETE_WAN


def test_get_profile_unknown_falls_back_to_er605():
    p = get_profile("UNKNOWN-MODEL")
    assert p.DEVICE_INFO_TEMPLATE["model"] == "ER605"


def test_get_profile_case_insensitive():
    p = get_profile("er706w")
    assert p.DEVICE_INFO_TEMPLATE["model"] == "ER706W"


# -- Device construction with model-selected profile --------------------------

def test_er605_device_uses_er605_profile():
    gw = _make_gateway("ER605")
    assert gw.profile.DEVICE_INFO_TEMPLATE["model"] == "ER605"
    assert gw.port_num == 5


def test_er706w_device_uses_er706w_profile():
    gw = _make_gateway("ER706W", mac="AA-BB-CC-DD-EE-15")
    assert gw.profile.DEVICE_INFO_TEMPLATE["model"] == "ER706W"
    assert gw.port_num == 5


def test_er7206_device_uses_er7206_profile():
    gw = _make_gateway("ER7206", mac="AA-BB-CC-DD-EE-16")
    assert gw.profile.DEVICE_INFO_TEMPLATE["model"] == "ER7206"
    assert gw.port_num == 9  # ER7206 has 9 ports


def test_er8411_device_uses_er8411_profile():
    gw = _make_gateway("ER8411", mac="AA-BB-CC-DD-EE-17")
    assert gw.profile.DEVICE_INFO_TEMPLATE["model"] == "ER8411"
    assert gw.port_num == 9  # ER8411 has 9 ports


# -- Capability-gated INFORM sections -----------------------------------------

def test_er605_no_sdwan_section():
    gw = _make_gateway("ER605")
    extra = gw.manage_inform_extra()
    assert "sdwan" not in extra
    assert "virtualWanInfo" not in extra
    assert "lte" not in extra


def test_er706w_has_lte_section():
    gw = _make_gateway("ER706W", mac="AA-BB-CC-DD-EE-15")
    extra = gw.manage_inform_extra()
    assert "lte" in extra
    assert "virtualWanInfo" in extra  # ER706W supports discrete WAN
    assert "sdwan" not in extra  # ER706W does NOT support SD-WAN


def test_er7206_has_sdwan_and_virtual_wan():
    gw = _make_gateway("ER7206", mac="AA-BB-CC-DD-EE-16")
    extra = gw.manage_inform_extra()
    assert "sdwan" in extra
    assert "virtualWanInfo" in extra
    assert "lte" not in extra  # ER7206 does NOT support LTE


def test_er8411_has_sdwan_and_virtual_wan():
    gw = _make_gateway("ER8411", mac="AA-BB-CC-DD-EE-17")
    extra = gw.manage_inform_extra()
    assert "sdwan" in extra
    assert "virtualWanInfo" in extra


# -- VPN capacity specs differ by model ---------------------------------------

def test_er605_vpn_capacities():
    p = get_profile("ER605")
    spec = p.DEV_CAP["specification"]
    assert spec["vpnIPSecNum"] == 20
    assert spec["sslVpnConnectionsNum"] == 500
    assert spec["wireguardNum"] == 20


def test_er706w_vpn_capacities():
    p = get_profile("ER706W")
    spec = p.DEV_CAP["specification"]
    assert spec["vpnIPSecNum"] == 50
    assert spec["sslVpnConnectionsNum"] == 1000
    assert spec["wireguardNum"] == 50


def test_er7206_vpn_capacities():
    p = get_profile("ER7206")
    spec = p.DEV_CAP["specification"]
    assert spec["vpnIPSecNum"] == 100
    assert spec["sslVpnConnectionsNum"] == 2000
    assert spec["wireguardNum"] == 100


def test_er8411_vpn_capacities():
    p = get_profile("ER8411")
    spec = p.DEV_CAP["specification"]
    assert spec["vpnIPSecNum"] == 200
    assert spec["sslVpnConnectionsNum"] == 5000
    assert spec["wireguardNum"] == 200


# -- Port counts differ by model ---------------------------------------------

def test_er605_port_count():
    p = get_profile("ER605")
    assert len(p.DEV_CAP["portInfos"]) == 5


def test_er7206_port_count():
    p = get_profile("ER7206")
    assert len(p.DEV_CAP["portInfos"]) == 9


def test_er8411_port_count():
    p = get_profile("ER8411")
    assert len(p.DEV_CAP["portInfos"]) == 9


# -- Components_V2 includes model-specific components ------------------------

def test_er706w_has_lte_component():
    p = get_profile("ER706W")
    assert "lte" in p.COMPONENTS_V2


def test_er7206_has_sdwan_component():
    p = get_profile("ER7206")
    assert "sdwan" in p.COMPONENTS_V2
    assert "virtualWan" in p.COMPONENTS_V2


def test_er605_no_lte_component():
    p = get_profile("ER605")
    assert "lte" not in p.COMPONENTS_V2


# -- All models report IPv6 on WAN port ---------------------------------------

def test_all_models_support_ipv6():
    for model in ("ER605", "ER706W", "ER7206", "ER8411"):
        p = get_profile(model)
        assert p.SUPPORTS_IPV6, f"{model} should support IPv6"


def test_all_models_report_ipv6_in_portinfo():
    for model, mac in [
        ("ER605", "AA-BB-CC-DD-EE-03"),
        ("ER706W", "AA-BB-CC-DD-EE-15"),
        ("ER7206", "AA-BB-CC-DD-EE-16"),
        ("ER8411", "AA-BB-CC-DD-EE-17"),
    ]:
        gw = _make_gateway(model, mac=mac)
        port_infos = gw.manage_inform_extra()["portInfo"]["portInfos"]
        wan = [p for p in port_infos if p["port"] == 1][0]
        assert wan["internetV6"] == 1, f"{model} WAN port should have internetV6=1"
        assert "ip2" in wan, f"{model} WAN port should have IPv6 ip2"
        assert "ip6" in wan, f"{model} WAN port should have ip6 nested entry"

# -- Phase 6: confirmed VPN config field names -------------------------------

def test_gateway_vpn_config_driven_ipsec_uses_confirmed_field_names():
    """VPN config parsing uses the confirmed VPN config field names
    (server_IPSecs / server_OpenVPNs / server_PPTPs), not the legacy guesses."""
    gw = _make_gateway()
    gw.build_set_response({
        "sequenceId": 1, "configVersion": 5,
        "vpn": {
            "server_IPSecs": [
                {"id": 1, "remote_peer": "198.51.100.1"},
                {"id": 2, "remote_peer": "198.51.100.2"},
                {"id": 3, "remote_peer": "198.51.100.3"},
            ],
            "server_OpenVPNs": [{"id": 1}],
            "server_PPTPs": [{"id": 1}, {"id": 2}],
        },
    })
    vpn = gw.manage_inform_extra()["vpn"]
    assert len(vpn["ipSecs"]) == 3
    assert len(vpn["openvpn"]) == 1
    assert len(vpn["tuns"]) == 2  # PPTP + L2TP combined
    # peerTun reflects the confirmed remote_peer field
    assert vpn["ipSecs"][0]["peerTun"] == "198.51.100.1"


def test_gateway_negotiation_device_info_identity_fields():
    """All gateway models report encryptedHwId/hwId/oemId/modelId/speeds/mask
    in the negotiated deviceInfo (from the profile template)."""
    for model in ("ER605", "ER706W", "ER7206", "ER8411"):
        gw = _make_gateway(model=model, mac=f"AA-BB-CC-DD-EE-{model[-2:]}")
        info = gw.manage_device_info()
        for f in ("encryptedHwId", "hwId", "oemId", "modelId", "speeds", "mask"):
            assert f in info, f"{model} missing negotiation identity field {f}"
