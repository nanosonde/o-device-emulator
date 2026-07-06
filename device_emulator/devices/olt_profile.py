"""Negotiation profile for an emulated OLT (PON optical line terminal).

The OLT is a V2-protocol wired device (it advertises ECSP version 2.2 like
switches and gateways), and its discovery `deviceInfo` reuses the AP-style
long-name field set (`model`/`modelVersion`/`firmwareVersion`/
`hardwareVersion`/`upTime`), while its negotiation `deviceInfo` (OLT adopt
device-info shape) adds OLT-specific identity fields (`hwId`/`oemId`/`lagCount`/
`ponPortCount`/`wirelessLinked`). See doc/DEVICE_PROTOCOL.md §4.4 and §7.9.

Unlike APs/switches/gateways (whose `DEVICE_NEGOTIATION` body uses a generic
envelope with `components_v2`/`devCap`/`deviceMisc`), the OLT's
`DEVICE_NEGOTIATION` body is parsed directly as the OLT adopt-response shape,
which expects `components` (a map of OLT component -> version), `deviceInfo`
(OLT adopt device-info) and `isFactoryDefault`. The `centralManagement`
component is required: the adopt handler flags the device incompatible
(value 4) if it is missing.
"""
from __future__ import annotations

# ECSP protocol version advertised in header.version for OLTs. OLT is a V2
# wired device like switches/gateways (ECSP first-version enum, V2 fit version).
PROTOCOL_VERSION = "2.2.0"

# Component manifest reported in the OLT negotiation `components` map
# (a map of component name -> version, the `components` field in the
# negotiation body). The controller's adopt handler errors if `components`
# is null, and flags the device incompatible (value 4) if `centralManagement`
# is missing — so this must be non-null and include `centralManagement`.
# Versions use the `"<ver>.<funcVer>"` string format.
COMPONENTS = {
    'accessSecurity': '1.0',
    'acl': '1.0',
    'arp': '1.0',
    'autoVoip': '1.0',
    'bandWidthControl': '1.0',
    'bootConfig': '1.0',
    'classOfService': '1.1',
    'dbaProfile': '1.0',
    'ddm': '1.0',
    'dhcpFilter': '1.0',
    'dhcpL2Relay': '1.2',
    'dhcpRelay': '1.2',
    'dhcpServer': '1.0',
    'diagnostics': '1.0',
    'dldp': '1.0',
    'ethPort': '1.0',
    'ethernetOam': '1.0',
    'firmwareUpgrade': '1.0',
    'igmpSnooping': '1.0',
    'interface': '1.0',
    'lag': '1.0',
    'lineProfile': '1.1',
    'lldp': '1.0',
    'lldpMed': '1.0',
    'logs': '1.0',
    'macSddress': '1.1',
    'mgmtProfile': '1.1',
    'mirroring': '1.0',
    'mldSnooping': '1.0',
    'multicastFiltering': '1.0',
    'multicastInfo': '1.0',
    'mvr': '1.0',
    'onuManagement': '1.1',
    'onuRegister': '1.1',
    'ponPort': '1.0',
    'portSecurity': '1.0',
    'resetAndBackup': '1.1',
    'routingTable': '1.0',
    'servicePort': '1.0',
    'serviceProfile': '1.0',
    'snmp': '1.0',
    'staticRouting': '1.0',
    'stp': '1.0',
    'systemInfo': '1.0',
    'systemMonitor': '1.0',
    'systemReboot': '1.0',
    'systemReset': '1.0',
    'timeRange': '1.0',
    'trafficMonitor': '1.0',
    'trafficProfile': '1.0',
    'userManagement': '1.2',
    'vlan': '1.0',
    'voiceVlan': '1.0',
    'centralManagement': '1.1',   # required: adopt flags incompatible without it
    'ponProfile': '1.0',
    'boardControl': '1.0',
}

# Back-compat alias: the WiredDevice base exposes manage_components_v2(); the
# OLT does NOT send components_v2 on the wire (it sends `components`), but the
# emulator's compatibility checks (and tests) read components_v2 to confirm a
# non-empty manifest. Mirror the same map here.
COMPONENTS_V2 = dict(COMPONENTS)

# Valid OLT model names the controller recognises as compatible. Any other
# model string is flagged `compatible = 10` (INCOMPATIBLE) and rejected at
# adoption with
# errorCode -39060 "Failed to adopt incompatible devices." The default model
# below (DS-P7001-08) is an 8-PON-port pizza-box OLT.
VALID_MODELS = (
    "DS-P7001-01",  # 1 PON port, pizza-box
    "DS-P7001-04",  # 4 PON ports, pizza-box
    "DS-P7001-08",  # 8 PON ports, pizza-box
    "DS-P7001-16",  # 16 PON ports, pizza-box
    "DS-MCUA",      # chassis OLT
    "DS-P8000-X2",  # chassis OLT
)
DEFAULT_MODEL = "DS-P7001-08"

# OLT capability descriptor. OLTs do not expose a switch-style `portCap`/
# `devCap` port matrix in the negotiation body; the OLT adopt device-info
# carries the OLT-specific identity fields (hwId/oemId/lagCount/ponPortCount/
# wirelessLinked) directly in `deviceInfo`, so `devCap` is minimal here. The
# controller's OLT adopt handler reads ponPortCount/lagCount from deviceInfo.
DEV_CAP = {
    'ponPortCount': 8,
    'lagCount': 0,
}

# `deviceMisc` reported in the negotiation body. The OLT device-misc shape
# carries only `category`, `modelType` and `supportCluster` (NOT
# portNum/ponPortCount — those live in `deviceInfo`). OLT is its own category
# (`"OLT"`, not `"L2 SWITCH"` like the switch profile). `supportCluster`
# must be true for the device to be compatible when the controller runs in
# cluster mode; the emulator defaults it to true to be accepted in either
# standalone or cluster deployments.
DEVICE_MISC = {'category': 'OLT', 'modelType': 'NORMAL', 'supportCluster': 1}

# Static identity fields merged into the negotiation `deviceInfo` (OLT adopt
# device-info shape). Dynamic fields (model/versions/ip/uptime) are filled in
# by OltDevice at runtime; the long-name keys here mirror the OLT adopt
# device-info shape: model/modelVersion/firmwareVersion/hardwareVersion/hwId/
# oemId/lagCount/ponPortCount/wirelessLinked. `oemId`/`hwId` are uppercase-hex
# device identity strings (the switch profile uses the same 32-char hex
# form); they are required by the controller's adopt handler.
DEVICE_INFO_TEMPLATE = {
    'hwId': '00000000000000000000000000000000',
    'oemId': '00000000000000000000000000000000',
    'lagCount': 0,
    'ponPortCount': 8,
    'wirelessLinked': False,
}