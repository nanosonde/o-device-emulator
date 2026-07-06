"""Negotiation profile for an emulated ER8411 gateway (high-end dual-WAN).

The ER8411 is a high-end gateway with 9 ports (2 WAN/LAN + 5 LAN + 2
SFP), supporting SD-WAN, multi-WAN load balancing, and the highest VPN
tunnel capacities in the lineup.
"""
from __future__ import annotations

PROTOCOL_VERSION = "2.2.0"

SUPPORT_LTE = False
SUPPORT_SDWAN = True
SUPPORT_DISCRETE_WAN = True
SUPPORT_WAN_LOAD_BALANCE = True
SUPPORT_POE = False
SUPPORTS_IPV6 = True

COMPONENTS_V2 = {
    'abnormalDetect': '1.1', 'abnormalDt': '1.0', 'acl': '1.2',
    'aclDisable': '1.0', 'arpInform': '0.0', 'arpTable': '1.0',
    'attackDefense': '1.1', 'bandwidthCtrl': '1.0', 'client': '0.0',
    'clientInform': '0.0', 'clientIpBinding': '1.0', 'clientOpt': '0.0',
    'clientTrafficRequire': '0.0', 'configVersion': '0.0', 'connect': '1.0',
    'controllerInfo': '0.0', 'ctTable': '1.0', 'ddns': '1.1',
    'ddnsStats': '1.0', 'devInform': '0.0', 'dsl': '1.0', 'dst': '0.0',
    'echoServer': '1.0', 'facebookV2': '1.1', 'firewallConfig': '1.0',
    'hwOffload': '1.0', 'igmp': '1.1', 'informInterval': '1.1',
    'ipGroup': '1.0', 'ipMacBinding': '1.0', 'ipPortGroup': '1.0',
    'ipsecFailover': '1.1', 'iptv': '1.1', 'iptv_hw': '1.0',
    'ipv6Group': '1.0', 'led': '1.0', 'lldp': '1.0', 'logInform': '0.0',
    'mdns': '1.1', 'mirror': '1.0', 'natAlg': '1.0', 'natPf': '1.0',
    'network': '1.0', 'networkTraffic': '0.0', 'oneToOneNat': '1.0',
    'onlineDetection': '1.1', 'policyRouting': '1.1', 'port': '1.0',
    'portInfo': '0.0', 'portalAct': '0.0', 'portalDuration': '1.0',
    'portalFreePolicy': '1.0', 'portforward': '1.0', 'privacyPolicy': '1.0',
    'qos': '1.0', 'rebootSchedule': '1.0', 'routingTable': '1.0',
    'sdwan': '1.0', 'serviceType': '1.0', 'sessionLimit': '1.0',
    'sideParams': '1.0', 'snmp': '1.0', 'snmpAdvance': '1.0',
    'speedDuplex': '1.0', 'speedTest': '1.0', 'ssh': '1.0',
    'staticRouting': '1.0', 'system': '0.0', 'time': '0.0',
    'timeRange': '0.0', 'trafficStat': '0.0', 'upnp': '1.0',
    'urlFiltering': '1.1', 'userAcnt': '0.0', 'virtualWan': '1.0',
    'vpn': '1.3', 'vpnUsers': '1.1', 'wanBasicSetting': '1.0',
    'wanIpv4': '1.2', 'wanIpv6': '1.0', 'wanLoadBalance': '1.0',
    'wanMac': '1.0',
}

DEV_CAP = {
    'defaultIgmpWan': 1,
    'extraPortInfos': [],
    'ipsecNum': 200,
    'mandatoryPorts': [],
    'maxSslVpnUserConcurrentNum': 1000,
    'maxVpnUserConcurrentNum': 1000,
    'portInfos': [
        {'defaultSpeedDuplex': '0:0', 'maxBandwidth': 10000, 'mode': 0,
         'name': 'WAN1/SFP1', 'port': 1,
         'speedDuplexList': ['0:0', '1:1', '1:2', '2:1', '2:2', '3:2'],
         'supportInternetVlan': 1, 'supportIptv': 1, 'supportMirror': 1,
         'supportPoe': 0, 'type': 0},
        {'defaultSpeedDuplex': '0:0', 'maxBandwidth': 1000, 'mode': 1,
         'name': 'WAN2/LAN1', 'port': 2,
         'speedDuplexList': ['0:0', '1:1', '1:2', '2:1', '2:2', '3:2'],
         'supportInternetVlan': 1, 'supportIptv': 1, 'supportMirror': 1,
         'supportPoe': 0, 'type': 1},
        {'defaultSpeedDuplex': '0:0', 'maxBandwidth': 1000, 'mode': 1,
         'name': 'WAN3/LAN2', 'port': 3,
         'speedDuplexList': ['0:0', '1:1', '1:2', '2:1', '2:2', '3:2'],
         'supportInternetVlan': 1, 'supportIptv': 1, 'supportMirror': 1,
         'supportPoe': 0, 'type': 1},
        {'defaultSpeedDuplex': '0:0', 'maxBandwidth': 1000, 'mode': 1,
         'name': 'LAN3', 'port': 4,
         'speedDuplexList': ['0:0', '1:1', '1:2', '2:1', '2:2', '3:2'],
         'supportInternetVlan': 1, 'supportIptv': 1, 'supportMirror': 1,
         'supportPoe': 0, 'type': 2},
        {'defaultSpeedDuplex': '0:0', 'maxBandwidth': 1000, 'mode': 1,
         'name': 'LAN4', 'port': 5,
         'speedDuplexList': ['0:0', '1:1', '1:2', '2:1', '2:2', '3:2'],
         'supportInternetVlan': 1, 'supportIptv': 1, 'supportMirror': 1,
         'supportPoe': 0, 'type': 2},
        {'defaultSpeedDuplex': '0:0', 'maxBandwidth': 1000, 'mode': 1,
         'name': 'LAN5', 'port': 6,
         'speedDuplexList': ['0:0', '1:1', '1:2', '2:1', '2:2', '3:2'],
         'supportInternetVlan': 1, 'supportIptv': 1, 'supportMirror': 1,
         'supportPoe': 0, 'type': 2},
        {'defaultSpeedDuplex': '0:0', 'maxBandwidth': 1000, 'mode': 1,
         'name': 'LAN6', 'port': 7,
         'speedDuplexList': ['0:0', '1:1', '1:2', '2:1', '2:2', '3:2'],
         'supportInternetVlan': 1, 'supportIptv': 1, 'supportMirror': 1,
         'supportPoe': 0, 'type': 2},
        {'defaultSpeedDuplex': '0:0', 'maxBandwidth': 1000, 'mode': 1,
         'name': 'LAN7', 'port': 8,
         'speedDuplexList': ['0:0', '1:1', '1:2', '2:1', '2:2', '3:2'],
         'supportInternetVlan': 1, 'supportIptv': 1, 'supportMirror': 1,
         'supportPoe': 0, 'type': 2},
        {'defaultSpeedDuplex': '0:0', 'maxBandwidth': 10000, 'mode': 1,
         'name': 'SFP2', 'port': 9,
         'speedDuplexList': ['0:0', '3:2'],
         'supportInternetVlan': 1, 'supportIptv': 0, 'supportMirror': 1,
         'supportPoe': 0, 'type': 1},
    ],
    'specification': {
        'aclNum': 512, 'bandwidthCtrlNum': 256, 'clientIpBindingNum': 2048,
        'ddnsNum': 24, 'ipGroupNum': 1024, 'ipv6GroupNum': 1024,
        'ldapClassRulesNum': 16, 'natPfNum': 128, 'networkNum': 256,
        'policyRoutingNum': 128, 'qosClassRulesNum': 64,
        'serviceTypeNum': 256, 'sessionLimitNum': 128,
        'sslVpnConnectionsNum': 5000, 'sslVpnLocksNum': 10000,
        'sslVpnResourceGroupsNum': 256, 'sslVpnResourcesNum': 128,
        'sslVpnUserGroupsNum': 512, 'sslVpnUsersNum': 2048,
        'staticRoutingNum': 128, 'urlFilteringNum': 128,
        'vpnIPSecNum': 200, 'vpnL2TPClientNum': 200, 'vpnOpenVPNNum': 200,
        'vpnPPTPClientNum': 200, 'vpnUsersNum': 2000,
        'wireguardAllPeerNum': 500, 'wireguardNum': 200,
        'wireguardPeerNum': 200,
    },
    'supportAclDisable': 1, 'supportAllWan': True,
    'supportDiscreteWan': 1, 'supportIPsecFailover': 1,
    'supportRoutingVpnClient': 1, 'supportSdWan': 1,
    'supportVpnUsb': 0, 'supportVpnVerify': 1, 'supportWanLoadBalance': 1,
}

DEVICE_MISC = {'extraPortNum': {'extraPort': 0, 'usbLteWan': 0}, 'portNum': 9}

DEVICE_INFO_TEMPLATE = {
    'cu': 4,
    'encryptedHwId': 'C3D4E5F6A7B8C9D0E1F2A3B4C5D6E7F8',
    'encryptedOemId': 'D3C4B5A69788796A5B4C3D2E1F001122',
    'extraWanDefaultMacs': [],
    'fac': False,
    'fwVer': '1.0.0 Build 20240101 Rel.22222',
    'hwId': 'C3D4E5F6A7B8C9D0E1F2A3B4C5D6E7F8',
    'hwVer': 'ER8411 v1.0',
    'ip': '192.168.1.1',
    'lanMac': '00-FF-00-12-7A-D4',
    'mask': '255.255.255.0',
    'model': 'ER8411',
    'modelId': 0,
    'modelVer': '1.0',
    'mu': 128,
    'oemId': 'D3C4B5A69788796A5B4C3D2E1F001122',
    'speeds': [1, 2, 3],
    'time': '0 days 00:03:55',
    'wanDefaultMacs': [
        {'defMac': '00-FF-00-12-7A-D5', 'portId': 1},
        {'defMac': '00-FF-00-12-7A-D6', 'portId': 2},
        {'defMac': '00-FF-00-12-7A-D7', 'portId': 3},
        {'defMac': '00-FF-00-12-7A-D8', 'portId': 4},
    ],
}