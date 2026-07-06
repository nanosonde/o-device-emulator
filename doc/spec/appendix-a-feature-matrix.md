# Appendix A — Feature Matrix

> This appendix provides cross-class and cross-model comparison tables and
> quick references. See [`README.md`](README.md) for the document index.

## A.1 Device type comparison matrix

| Dimension | EAP (AP) | Switch | Gateway | OLT |
|---|---|---|---|---|
| Role | Wi-Fi access | Wired fabric | Internet edge / router | PON headend |
| `header.device` | `ap` | `switch` | `gateway` | `olt` |
| `header.version` | `2.3.0` | `2.2.0` | `2.2.0` | `2.2.0` |
| Discovery controller-ID path | `controllerSetting.controllerId` | `controller.id` | `controller.id` | `controller.id` |
| `deviceInfo` naming | long | short | short + `cerVer`/`wireless` | long (AP-style) |
| `upTime` format | string `"<N> days HH:MM:SS"` | string | string | integer (seconds) |
| Base class | `Device` | `WiredDevice` | `WiredDevice` | `WiredDevice` |
| WiFi | native (2 radios) | none | optional (`wireless>0`) | none |
| PoE role | consumer | provider | provider (gated) | none |
| Mesh | `mesh` section | none | `mesh` (WiFi models) | none |
| Remote Terminal (RTTY) | ✅ | ✅ | ✅ | ✅ |
| Network Check (DMP) | ✅ | ✅ | ✅ | ✅ |
| Packet Capture | ✅ | ✅ | ✅ | ✅ |
| Clients reported | wireless stations | wired per-port | all site (DHCP server) | ONUs (in ONU table) |
| Config-push SET keys | per-radio SSID/radio | routing/lag/stp/etc. | ~80+ (largest) | only 2 + upgrade |
| Detail operations | n/a | GET echo | GET echo + extras | 230+ URI-RPC |
| Top INFORM sections | `clients`, `wSettings_*`, `ssidStats_*` | `port`, `lldp`, `fdb`, `routingTable` | `portInfo`, `vpn`, `trafficStat`, `client` | `deviceInfo` (ONU counts), `trafficStat` |
| Component manifest size | ~75 | ~69 | ~82–86 | ~57 |

## A.2 Gateway model comparison

### A.2.1 Capability flags

| Capability | ER605 | ER706W | ER7206 | ER8411 |
|---|---|---|---|---|
| Ports | 5 | 5 | 9 | 9 |
| 10G SFP ports | 0 | 0 | 1 | 2 |
| LTE | ❌ | ✅ | ❌ | ❌ |
| SD-WAN | ❌ | ❌ | ✅ | ✅ |
| Multi-WAN (discrete) | ❌ | ✅ | ✅ | ✅ |
| WAN load balance | ❌ | ✅ | ✅ | ✅ |
| VPN-over-USB | ❌ | ✅ | ❌ | ❌ |
| Integrated Wi-Fi | ❌ | ✅ (Wi-Fi 5) | ❌ | ❌ |
| PoE provider | ❌ | ❌ | ❌ | ❌ |
| IPv6 on WAN | ✅ | ✅ | ✅ | ✅ |

### A.2.2 VPN and SSL-VPN capacities

| Capacity | ER605 | ER706W | ER7206 | ER8411 |
|---|---:|---:|---:|---:|
| IPsec tunnels | 20 | 50 | 100 | 200 |
| OpenVPN | 10 | 50 | 100 | 200 |
| PPTP | 10 | 50 | 100 | 200 |
| L2TP | 10 | 50 | 100 | 200 |
| VPN users | 240 | 500 | 1000 | 2000 |
| SSL-VPN connections | 500 | 1000 | 2000 | 5000 |
| SSL-VPN users | 512 | 512 | 1024 | 2048 |
| SSL-VPN locks | 1000 | 2000 | 4000 | 10000 |
| Max SSL-VPN concurrent | 100 | 200 | 500 | 1000 |
| Max VPN concurrent | 100 | 200 | 500 | 1000 |
| WireGuard tunnels | 20 | 50 | 100 | 200 |
| WireGuard peers | 20 | 50 | 100 | 200 |
| WireGuard all peers | 100 | 200 | 500 | 500 |

### A.2.3 Rule and routing capacities

| Count | ER605 | ER706W | ER7206 | ER8411 |
|---|---:|---:|---:|---:|
| ACL rules | 64 | 128 | 256 | 512 |
| Static routes | 64 | 64 | 64 | 128 |
| Policy routes | 64 | 64 | 64 | 128 |
| Port forward | 32 | 64 | 64 | 128 |
| QoS rules | 32 | 32 | 32 | 64 |
| IP groups | 512 | 512 | 512 | 1024 |
| IPv6 groups | 512 | 512 | 512 | 1024 |
| Bandwidth control | 64 | 128 | 128 | 256 |
| Session limit | 64 | 64 | 64 | 128 |
| DDNS | 24 | 24 | 24 | 24 |
| Networks | 128 | 128 | 128 | 256 |
| Client IP bindings | 1024 | 1024 | 1024 | 2048 |
| URL filtering | 64 | 64 | 64 | 128 |

### A.2.4 Component additions vs ER605

| Component | ER605 | ER706W | ER7206 | ER8411 |
|---|---|---|---|---|
| `dsl` | — | ✅ | ✅ | ✅ |
| `lte` | — | ✅ | — | — |
| `sdwan` | — | — | ✅ | ✅ |
| `virtualWan` | — | — | ✅ | ✅ |

## A.3 INFORM sections by device type

Rows = INFORM section; columns = device class. ✓ = reported; — = not applicable.

| INFORM section | EAP | Switch | Gateway | OLT |
|---|:---:|:---:|:---:|:---:|
| `deviceInfo` | ✓ | ✓ | ✓ | ✓ |
| `clients` | ✓ | — | — | — |
| `client` | — | ✓ | ✓ | — |
| `dhcpClient` | — | — | ✓ | — |
| `lanInfo` | ✓ | — | — | — |
| `uplinkPortStatus` | ✓ | — | — | — |
| `portStatus` | ✓ | — | — | — |
| `portTraffics` | ✓ | — | — | — |
| `port` | — | ✓ | — | — |
| `portInfo` | — | — | ✓ | — |
| `lldp` | — | ✓ | ✓ | ✓ |
| `fdb` | — | ✓ | — | — |
| `poe` | — | ✓ | ✓ (gated) | — |
| `poeInform` | ✓ | — | — | — |
| `mesh` | ✓ | — | ✓ (WiFi) | — |
| `routingTable` | — | ✓ | ✓ | — |
| `loopback` | — | ✓ | — | — |
| `lag` | — | ✓ | — | — |
| `ddm` | — | ✓ | — | — |
| `stpInform` | — | ✓ | — | — |
| `wSettings_2G` / `wSettings_5G` | ✓ | — | ✓ (WiFi) | — |
| `radioTraffic_2G` / `radioTraffic_5G` | ✓ | — | ✓ (WiFi) | — |
| `ssidStats_2G` / `ssidStats_5G` | ✓ | — | ✓ (WiFi) | — |
| `roaming` | ✓ | — | ✓ (WiFi) | — |
| `trafficStat` | — | — | ✓ | ✓ |
| `arp` | — | — | ✓ | — |
| `vpn` | — | — | ✓ | — |
| `sslVpn` | — | — | ✓ | — |
| `wireguard` | — | — | ✓ | — |
| `ddns` | — | — | ✓ | — |
| `qos` | — | — | ✓ | — |
| `ctTable` | — | — | ✓ | — |
| `portforward` | — | — | ✓ | — |
| `networkTraffic` | — | — | ✓ | — |
| `ipsThreat` | — | — | ✓ | — |
| `sdwan` | — | — | ✓ (gated) | — |
| `virtualWanInfo` | — | — | ✓ (gated) | — |
| `lte` | — | — | ✓ (gated) | — |
| `trafficTimeStamp` | — | — | — | ✓ |

> WiFi-gated sections apply only when the gateway advertises `wireless > 0`
> (e.g. ER706W). Capability-gated sections apply only on models that advertise
> the corresponding `support*` flag (see [A.2.1](#a21-capability-flags)).

## A.4 Component manifests

The component manifest (`components_v2` in DEVICE_NEGOTIATION) MUST be
non-empty. Below are the notable components per class. The full version-tagged
lists are long; only the distinguishing components are shown. Cross-cutting
components (`terminalSetting`, `transferChannel`, `packageCapture`,
`controllerInfo`, `configVersion`, `devInform`, `upgrade`, `time`,
`userAcnt`, `system`, `logInform`, `ping`, `traceroute`, `led`, `snmp`,
`ssh`, `lldp`) appear in all/most classes and are omitted for brevity.

### A.4.1 EAP (AP) — ~75 components

AP-specific: `ssid` (2.3), `ssidInform` (2.0), `ssidRateLimit` (2.1),
`wlanBasic` (2.0), `wlanAdv` (1.0), `wlanInform` (2.0), `mesh` (1.1),
`meshInform` (2.0), `bandSteer` (1.1), `bSteerInform` (1.0), `portal` (2.0),
`portalAct` (2.0), `rogueAp` (3.0), `rogueApInform` (2.0), `roaming` (1.1),
`roamingInform` (2.0), `roamRecInform` (1.0), `radioAccessInform` (1.0),
`rfScan` (1.0), `clientInform` (2.0), `clientConnectionInform` (1.0),
`clientAct` (1.1), `powerControl` (1.0), `lanPort` (1.0), `lanInform` (2.0),
`lldpInform` (1.0), `facebookV2` (1.0), `urlFiltering` (1.0), `macfilter` (2.0),
`scheduler` (2.0), `acl` (2.1), `qos` (1.0), `ipGroup` (1.0),
`ipv6Group` (1.0), `rssiFilter` (1.0), `reportInterval` (1.0),
`informInterval` (1.2).

### A.4.2 Switch — ~69 components

Switch-specific: `staticRouting` (1.1), `routingTable` (1.1), `loopback` (1.1),
`loopbackInform` (1.1), `vlanIf` (1.1), `network` (1.1), `lag` (1.1),
`ddm` (1.0), `ddmInform` (1.0), `stp` (1.0), `stpInform` (1.0), `port` (1.0),
`portInform` (1.0), `portCommon` (1.0), `portIsolation` (1.0), `fdbInform` (1.0),
`igmpSnoop` (1.0), `mldSnoop` (1.0), `multicastInform` (1.0), `dot1x` (1.0),
`dot1xInform` (1.0), `acl` (1.2), `qosRate` (1.0), `dhcpServer` (1.0),
`dhcpRelay` (1.0), `dhcpL2Relay` (1.0), `dhcpGuard` (1.0), `dhcpv6Guard` (1.0),
`dhcpInform` (1.0), `mirroring` (1.0), `voiceVlan` (1.0), `ouiBasedVlan` (1.1),
`managementVlan` (1.0), `macGroup` (1.0), `jumbo` (1.0), `eee` (1.0),
`flowControl` (1.0), `timeRange` (1.0), `standaloneMgmt` (1.0),
`uiConfigSync` (1.0).

### A.4.3 Gateway — ~82–86 components (model-dependent)

Gateway-specific: `vpn`, `sslVpn`, `wireguard`, `ipsecFailover`, `vpnUsers`,
`firewallConfig`, `attackDefense`, `natAlg`, `natPf`, `oneToOneNat`,
`disableNat`, `sessionLimit`, `bandwidthCtrl`, `qos`, `acl`, `aclDisable`,
`urlFiltering`, `ips`, `ipsThreat`, `macFilter` (`macfilter`),
`ipMacBinding`, `clientIpBinding`, `clientOpt`, `clientTrafficRequire`,
`wanIpv4`, `wanIpv6`, `wanMac`, `wanBasicSetting`, `wanLoadBalance`,
`connect`, `onlineDetection`, `network`, `networkTraffic`, `lanDns`,
`iptv`, `dsl`, `lte`, `speedTest`, `staticRouting`, `policyRouting`,
`routingTable`, `ddns`, `ddnsStats`, `ctTable`, `portforward`, `portInfo`,
`port`, `speedDuplex`, `mirror`, `poe`, `snmpAdvance`, `hwOffload`, `jumbo`,
`echoServer`, `upnp`, `mdns`, `ldapClassRules` (via `ldap`), `arpInform`,
`arpTable`, `abnormalDetect`, `abnormalDt`, `trafficStat`, `serviceType`,
`rebootSchedule`, `sideParams`, `facebookV2`, `igmp`, `timeRange`,
`ipGroup`/`ipPortGroup`/`ipv6Group`/`ipv6PortGroup`, `echoServer`,
`sslVpnResourceGroups`/`sslVpnResources`/`sslVpnUserGroups`.
Model additions: `dsl`, `lte` (ER706W); `sdwan`, `virtualWan` (ER7206/ER8411).
WiFi models add: `bandSteering`, `mesh`, `roaming`, `ppskV3`.

### A.4.4 OLT — ~57 components

OLT-specific: `centralManagement` (1.1, **REQUIRED**), `ponPort`, `ponProfile`,
`onuManagement` (1.1), `onuRegister` (1.1), `lineProfile` (1.1),
`serviceProfile`, `dbaProfile`, `mgmtProfile` (1.1), `trafficProfile`,
`boardControl`, `multicastInfo`, `multicastFiltering`, `mvr`, `igmpSnooping`,
`mldSnooping`, `bandWidthControl`, `classOfService` (1.1), `voiceVlan`,
`autoVoip`, `routingTable`, `staticRouting`, `interface`, `dhcpServer` (1.0),
`dhcpRelay` (1.2), `dhcpL2Relay` (1.2), `dhcpFilter`, `arp`, `acl`,
`accessSecurity`, `portSecurity`, `firmwareUpgrade`, `systemReboot`,
`systemReset`, `systemInfo`, `systemMonitor`, `resetAndBackup` (1.1),
`userManagement` (1.2), `diagnostics`, `ethPort`, `servicePort`, `lag`, `stp`,
`lldp`, `lldpMed`, `dldp`, `ddm`, `logs`, `trafficMonitor`, `timeRange`,
`mirroring`, `ethernetOam`, `bootConfig`, `macSddress` (1.1).

## A.5 OLT valid models

| Model | Description |
|---|---|
| `DS-P7001-01` | 1 PON port, pizza-box |
| `DS-P7001-04` | 4 PON ports, pizza-box |
| `DS-P7001-08` | 8 PON ports, pizza-box (reference default) |
| `DS-P7001-16` | 16 PON ports, pizza-box |
| `DS-MCUA` | Chassis OLT |
| `DS-P8000-X2` | Chassis OLT |

## A.6 Message-type quick reference

### Discovery and management base codes

| Code | Name |
|---:|---|
| `1` | DISCOVERY |
| `2` | PRE_ADOPT_REQUEST |
| `3` | PRE_CONNECT_INFO |
| `80` | NOTIFY_REQUEST |
| `144` | NOTIFY_REPLY |
| `256` | INFORM_REQUEST |
| `512` | INFORM_RESPONSE |
| `4096` | SET_REQUEST |
| `8192` | SET_RESPONSE |
| `24576` | GET_REQUEST |
| `28672` | GET_RESPONSE |
| `16384` | FORGET_REQUEST |
| `20480` | FORGET_RESPONSE |
| `32768` | UPGRADE_REQUEST |
| `65536` | UPGRADE_RESPONSE |

### Adoption handshake codes

| Code | Name |
|---:|---|
| `0x100000` | PRE_CONNECT_INFO_RESPONSE |
| `0x100001` | DEVICE_VERIFY_INFO |
| `0x100002` | DEVICE_VERIFY_RESPONSE |
| `0x100003` | SYSTEM_VERIFY_RESULT |
| `0x100004` | DEVICE_NEGOTIATION |
| `0x100005` | SYSTEM_NEGOTIATION |
| `0x100006` | INIT_SYNC_RESULT |
| `0x100009` | VERIFY_RESULT_ACK |
| `0x10000A` | INIT_SYNC_RESULT_ACK |
| `0x100007` | NOTIFY_REQUEST_V2 |
| `0x100008` | NOTIFY_REPLY_V2 |

### File-transfer codes

| Code | Name |
|---:|---|
| `0x160000` | FILE_TRANSFER_REQUEST_V2 |
| `0x170000` | FILE_TRANSFER_RESPONSE_V2 |

## A.7 Port quick reference

| Port | Protocol | Service | Purpose |
|---:|---|---|---|
| 29810 | UDP | Discovery | Device announce + pre-adopt reply |
| 29814 | TCP/TLS | Management | Adoption, INFORM, SET/GET, NOTIFY, file-transfer responses |
| 29815 | TCP/TLS | Transfer | File-transfer handshake + partition requests |
| 29816 | TCP/TLS | RTTY | Remote terminal + reverse tunnels |
| 29817 | TCP/TLS | Device Monitor | Network Check (ping/traceroute) |
| 8043 | HTTPS | Info API / UI | `GET /api/info` (controller ID) + operator UI |
| 8088 | HTTP | UI | Redirects to HTTPS 8043 |

## A.8 Glossary

| Term | Meaning |
|---|---|
| **Adoption** | Process by which the controller takes ownership of a discovered device. |
| **AP / EAP** | Access point (Om\*d\* product prefix "EAP"). |
| **ARP** | Address Resolution Protocol; the gateway reports an ARP table. |
| **Channel** | A logical device↔controller connection (discovery, management, transfer, RTTY, DMP). |
| **Connected** | Device state: adopted and online. |
| **Controller** | The Om\*d\* Software Controller — central SDN management server. |
| **Controller ID** | Unique opaque hex string identifying a controller instance. |
| **DMP** | Device Monitor Protocol — the protobuf channel (29817) for Network Check. |
| **ECSP** | The device/controller wire-protocol family used by Om\*d\*. |
| **ECSPv2** | The current device-protocol generation, targeted by this specification. |
| **FDB** | MAC Forwarding DataBase; switches report it for topology. |
| **Gateway (ER)** | Internet gateway / router (Om\*d\* product prefix "ER"). |
| **GET** | Controller-initiated device-state query (`type 24576`/`28672`). |
| **INFORM** | Periodic device→controller heartbeat/telemetry (`type 256`). |
| **LAG** | Link Aggregation Group. |
| **LLDP** | Link Layer Discovery Protocol; devices report neighbours for topology. |
| **MAC** | Media Access Control address; the device identity key. |
| **NOTIFY** | Device→controller event message (`type 80`). |
| **OLT** | Optical Line Terminal — PON headend. |
| **ONU** | Optical Network Unit — subscriber device under an OLT. |
| **PCAP** | Packet capture file (libpcap v2.4 format). |
| **PoE** | Power over Ethernet. APs consume; switches/gateways provide. |
| **PON** | Passive Optical Network. |
| **RTTY** | Remote TTY — the binary terminal protocol (29816). |
| **SET** | Controller-initiated configuration push (`type 4096`/`8192`). |
| **SFP** | Small Form-factor Pluggable transceiver port. |
| **Site** | Logical grouping of devices and clients under one controller. |
| **SD-WAN** | Software-Defined WAN; supported by ER7206/ER8411. |
| **SSID** | Service Set Identifier — a Wi-Fi network name. |
| **STP** | Spanning Tree Protocol. |
| **Switch** | Managed Ethernet switch. |
| **TLS** | Transport Layer Security; wraps all controller-facing TCP channels. |
| **URI-RPC** | The OLT detail-page operation model: `{uri, params}` → `{deviceType, errcode, message, data}`. |
| **VPN** | Virtual Private Network (IPsec/OpenVPN/PPTP/L2TP/SSL-VPN/WireGuard). |
| **WireGuard** | A modern VPN protocol; gateways report interfaces + tunnels. |

---

Back to: [`README.md`](README.md)