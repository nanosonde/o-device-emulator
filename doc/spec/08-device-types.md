# 8 — Device Types

> Prerequisite: [6 — Steady-State Operation](06-steady-state.md). This
> document specifies the per-class differences. For cross-class comparison
> tables, see [Appendix A](appendix-a-feature-matrix.md).

Om\*d\* manages four device classes. All share the same envelope, framing, and
adoption handshake (see [§4](04-wire-protocol.md) and
[§5](05-discovery-and-adoption.md)); they differ in:

- the **discovery body shape** (controller-ID field path and field naming),
- the **`deviceInfo` field naming** (long-name vs short-name),
- the **negotiation capabilities** and **component manifest**,
- the **INFORM extra sections** (telemetry),
- the **config-push SET keys** the controller uses,
- any class-specific **semantics** (PoE role, WiFi, mesh, URI-RPC).

## 8.1 Common base

Every device carries:

| Field | Description |
|---|---|
| `mac` | Device MAC (hyphenated uppercase) — the identity key. |
| `model` | Product model string. |
| `model_version` / `modelVersion` | Model/hardware revision. |
| `firmware_version` / `firmwareVersion` | Running firmware version. |
| `hardware_version` / `hardwareVersion` | Hardware board version. |
| `name` | Device host name. |
| `ip` | Management IP address. |
| `uptime` | Time since boot. |
| CPU/memory utilisation | Reported in `deviceInfo` (names vary by class). |

Cross-cutting features available to all classes (started via SET keys):

| Feature | SET key | Channel |
|---|---|---|
| Remote Terminal | `terminalSetting` | RTTY 29816 |
| Network Check | `monitorServer` | DMP 29817 |
| Packet Capture | `packageCapture` | transfer 29815 |
| File Transfer | `transferChannel` | transfer 29815 |

All classes SHOULD advertise `devCap.supportTerminal:true` (and
`terminalSupport:true`) in negotiation so the device appears in the operator
Terminal picker.

## 8.2 EAP (Access Point)

**Role:** Wi-Fi access. Provides wireless connectivity via multiple radios
(2.4 GHz + 5 GHz). The controller pushes WLAN/SSID and radio configuration via
SET keys; the AP reports applied values back in INFORM.

### 8.2.1 Identity

| Property | Value |
|---|---|
| `header.device` | `ap` |
| `header.version` | `2.3.0` |
| Discovery controller-ID path | `controllerSetting.controllerId` |
| `deviceInfo` naming | **long** (`modelVersion`, `firmwareVersion`, `hardwareVersion`, `upTime`) |
| `upTime` format | string `"<N> days HH:MM:SS"` |

### 8.2.2 Discovery body

```json
{
  "deviceInfo": { "ip", "model", "modelVersion", "firmwareVersion",
                  "hardwareVersion", "name", "upTime", "cpuUti", "memUti",
                  "wirelessLinked", "p2p" },
  "deviceMisc": { "customizeRegion": <country_code> },
  "controllerSetting": { "controllerId": "<controller ID>" }
}
```

- `deviceMisc.customizeRegion` and `controllerSetting.controllerId` are
  **required** — omitting either causes the controller to drop the announce.
- `wirelessLinked` MUST be `false` for a wired AP (the controller refuses to
  adopt a wireless-uplink AP that has no available uplink APs).

### 8.2.3 Negotiation capabilities

The AP negotiation body (DEVICE_NEGOTIATION, step 7 of the handshake) carries
radio-specific capability beyond the common fields:

| Field | Description |
|---|---|
| `channelInfo` | Per-radio list: `{radioId, band, channelList:[{fr, vl, mPow, cFlag, dFlag, lm}]}`. |
| `radioCap` | Per-radio: `{radioId, supportSsidNum: 8}` — up to 8 SSIDs per radio. |
| `devCap` | `{supportTerminal:true, terminalSupport:true}`. |
| `deviceMisc` | `{customizeRegion: <country_code>}`. |

Radio defaults (reference): radio 0 = 2.4 GHz (channels 1/6/11), radio 1 = 5 GHz
(channels 36/40/44/48).

### 8.2.4 Component manifest

The AP component manifest (`components_v2`) is large (~75 components).
Notable AP-specific components: `ssid` (2.3), `ssidInform` (2.0), `wlanBasic`
(2.0), `wlanAdv` (1.0), `wlanInform` (2.0), `mesh` (1.1), `meshInform` (2.0),
`bandSteer` (1.1), `portal` (2.0), `portalAct` (2.0), `rogueAp` (3.0),
`roaming` (1.1), `clientInform` (2.0), `lanPort` (1.0), `powerControl` (1.0),
plus the cross-cutting `terminalSetting`, `packageCapture`, `transferChannel`.
The full list is enumerated in [Appendix A.4](appendix-a-feature-matrix.md#a4-component-manifests).

> The manifest MUST be non-empty. An empty manifest causes the controller to
> flag the device incompatible.

### 8.2.5 INFORM extra sections

| Section | Purpose |
|---|---|
| `lanInfo` | Wired uplink port (`rate`, `duplex`, `port`). |
| `uplinkPortStatus` | Uplink LAN port status (link/speed/duplex/PoE telemetry). |
| `portStatus` | Downlink LAN ports (same field set). |
| `portTraffics` | Per-downlink-port traffic (multi-port APs only). |
| `poeInform` | PoE **consumer** status — power budget received from the switch. |
| `mesh` | Mesh topology (`status` 0 = disabled for wired, 1 = active for wireless-uplink). |
| `clients` | Associated wireless clients (`mac`, `rid`, `ssid`, `snr`, `rssi`, `rate`, `down`/`up`, `ip`, `vlan`, `guest`). |
| `wSettings_2G` / `wSettings_5G` | Per-radio settings (`region`, `ch`, `bw`, `rdMode`, `txPower`, utilisation). |
| `radioTraffic_2G` / `radioTraffic_5G` | Per-radio traffic (`rx`/`tx`). |
| `ssidStats_2G` / `ssidStats_5G` | Per-SSID stats (`id`, `ssid`, `clntNum`, `down`/`up`, `bssid`). |

### 8.2.6 Config-push SET keys (per radio, `<band>G` suffix)

| SET key | Drives |
|---|---|
| `ssid_2G` / `ssid_5G` / `ssid_5G2` / `ssid_6G` | SSID configuration; affects `clients[].ssid`, `ssidStats_*`. SSID CRUD `operation`: 1=add, 2=delete, 3=update. |
| `wirelessBasic_2G` / `wirelessBasic_5G` / … | Radio enable, channel width, channel, TX power, wireless mode; affects `wSettings_*`. |
| `wirelessAdv_2G` / `wirelessAdv_5G` / … | Advanced wireless config (captured for GET echo). |

### 8.2.7 Special semantics

- **PoE role**: consumer (powered by the switch). Reports `poeInform`.
- **WiFi**: native (two radios).
- **Mesh**: `wirelessLinked=false` → `mesh.status=0` (disabled). Set
  `wirelessLinked=true` only for wireless-uplink APs.

## 8.3 Switch

**Role:** Managed L2/L3 switch. Wired fabric, port-level telemetry, topology
(LLDP/FDB), PoE provider, L3 static routing, LAG, SFP-DDM, STP.

### 8.3.1 Identity

| Property | Value |
|---|---|
| `header.device` | `switch` |
| `header.version` | `2.2.0` |
| Discovery controller-ID path | `controller.id` |
| `deviceInfo` naming | **short** (`modelVer`, `fwVer`, `hwVer`, `time`) |
| `upTime` format | string `"<N> days HH:MM:SS"` |
| Extra discovery field | `stackId` (top-level) |

### 8.3.2 Discovery body

```json
{
  "deviceInfo": { "ip", "model", "modelVer", "fwVer", "hwVer", "time" },
  "deviceMisc": { "portNum": <port_count> },
  "controller": { "id": "<controller ID>" },
  "stackId": ""
}
```

### 8.3.3 Negotiation capabilities

Switches advertise a port matrix in `devCap` (reference: TL-SG3210):

| `devCap` field | Value (example) | Description |
|---|---|---|
| `portNum` | 10 | Total ports. |
| `giNum` | 10 | Gigabit ports. |
| `sfpBeginNum` / `sfpNum` | 9 / 2 | SFP port range. |
| `lagNum` / `lagMember` | 8 / 8 | LAG groups / members per group. |
| `poePortNum` / `poePortLimit` | 8 / 300 | PoE ports / total budget (W). |
| `vlan` | 4094 | Max VLANs. |
| `dot1x` | 100 | 802.1x clients. |
| `maxMirrorGroup` / `maxMirroredPort` | 1 / 9 | Port mirroring. |
| `cpuTempThreshold` etc. | 80 | Temperature thresholds. |

`deviceMisc`: `{category:"L2 SWITCH", modelType:"NORMAL", portNum:10}`.

### 8.3.4 Component manifest

~69 components. Notable switch-specific: `staticRouting` (1.1), `routingTable`
(1.1), `loopback` (1.1), `vlanIf` (1.1), `network` (1.1), `lag` (1.1), `ddm`/
`ddmInform`, `stp`/`stpInform`, `port`/`portInform`, `fdbInform`, `igmpSnoop`/
`mldSnoop`, `dot1x`, `acl` (1.2), `qosRate`, `dhcpServer`/`dhcpRelay`/
`dhcpL2Relay`, `mirroring`, `voiceVlan`, `ouiBasedVlan`, `managementVlan`,
plus cross-cutting `terminalSetting`, `transferChannel`. Full list in
[Appendix A.4](appendix-a-feature-matrix.md#a4-component-manifests).

### 8.3.5 INFORM extra sections

| Section | Purpose |
|---|---|
| `port` | Per-port link status + traffic (`standardPort:"1/0/N"`, `status`, `speed`, `duplex`, `stpState`, `rx`/`tx`). |
| `lldp` | LLDP neighbour table (`port`, `standardPort`, `neighbors[{chassisId, portId, name}]`). |
| `fdb` | MAC forwarding table (`port`, `standardPort`, `macs[{mac}]`) — places wired APs under the switch. |
| `client` | Learned wired clients (`mac`, `name`, `vendor`, `ip`, `vid`, `port`, `standardPort`, `rx`/`tx`). |
| `poe` | PoE **provider** status (`total`, `remain`, `percent`, `ports[{standardPort, state, p, pdClass}]`). Zero budget for non-PoE models. |
| `routingTable` | L3 routing table (`destIp` CIDR, `nextHop`, `distance`, optional `nextHops` for ECMP). |
| `loopback` | Loopback interface (`enable`, `type`). |
| `lag` | LAG groups (`lag`, `stMembers`, `duplex`, `status`, `rates`). |
| `ddm` | SFP digital diagnostics — nested `tem`/`vol`/`bc`/`tx`/`rx` with raw value + alarm/warn thresholds. |
| `stpInform` | Per-port STP state (`port`, `standardPort`, `stpState` [0=disabled, 1=forwarding, 2=learning, 3=listening, 4=blocking, 5=discarding], `stpVlan`). |

### 8.3.6 Config-push SET keys

`staticRouting`, `loopbackInterface`, `vlanIf`, `lag`, `stp`, `portStp` —
captured and echoed by GET.

### 8.3.7 Special semantics

- **PoE role**: provider (delivers power to APs). Reports `poe`. Zero budget
  for non-PoE models.
- **WiFi**: none.
- **L3 routing**: directly-connected (distance 0), default route (distance 1),
  and operator-configured static routes from `staticRouting` SET.

## 8.4 Gateway

**Role:** Internet gateway/router. Site default route and DHCP server.
Aggregates all site clients. The richest device type — WAN/LAN ports, VPN
(IPsec/OpenVPN/PPTP/L2TP/SSL-VPN/WireGuard), firewall/NAT, QoS, DDNS, routing,
SD-WAN, LTE, PoE, and optionally integrated Wi-Fi and VoIP.

### 8.4.1 Identity

| Property | Value |
|---|---|
| `header.device` | `gateway` |
| `header.version` | `2.2.0` |
| Discovery controller-ID path | `controller.id` |
| `deviceInfo` naming | **short** + `cerVer`, `wireless` |
| `upTime` format | string `"<N> days HH:MM:SS"` |

### 8.4.2 Discovery body

```json
{
  "deviceInfo": { "ip", "model", "modelVer", "fwVer", "cerVer", "hwVer",
                  "time", "wireless": <0|1> },
  "deviceMisc": { "portNum": <port_count>, "customizeRegion": <country_code> },
  "controller": { "id": "<controller ID>" }
}
```

`wireless > 0` marks a WiFi-capable gateway (emits `wSettings_*`/
`radioTraffic_*`/`ssidStats_*`/`mesh`/`roaming` sections).

### 8.4.3 Gateway model comparison

The gateway class has multiple models with differing capabilities. The model
string selects the profile.

| Capability | ER605 | ER706W | ER7206 | ER8411 |
|---|---|---|---|---|
| Ports | 5 | 5 | 9 (incl. SFP 10G) | 9 (incl. 2× SFP 10G) |
| LTE | ❌ | ✅ | ❌ | ❌ |
| SD-WAN | ❌ | ❌ | ✅ | ✅ |
| Multi-WAN (discrete) | ❌ | ✅ | ✅ | ✅ |
| WAN load balance | ❌ | ✅ | ✅ | ✅ |
| VPN-over-USB | ❌ | ✅ | ❌ | ❌ |
| Integrated Wi-Fi | ❌ | ✅ (Wi-Fi 5) | ❌ | ❌ |

VPN and rule capacities (full table in [Appendix A.2](appendix-a-feature-matrix.md#a2-gateway-model-comparison)):

| Capacity | ER605 | ER706W | ER7206 | ER8411 |
|---|---:|---:|---:|---:|
| IPsec tunnels | 20 | 50 | 100 | 200 |
| OpenVPN / PPTP / L2TP | 10 each | 50 each | 100 each | 200 each |
| VPN users | 240 | 500 | 1000 | 2000 |
| SSL-VPN connections | 500 | 1000 | 2000 | 5000 |
| SSL-VPN users | 512 | 512 | 1024 | 2048 |
| WireGuard tunnels | 20 | 50 | 100 | 200 |
| ACL rules | 64 | 128 | 256 | 512 |
| Static routes | 64 | 64 | 64 | 128 |
| Policy routes | 64 | 64 | 64 | 128 |
| Port forward | 32 | 64 | 64 | 128 |
| QoS rules | 32 | 32 | 32 | 64 |
| IP groups | 512 | 512 | 512 | 1024 |

### 8.4.4 Component manifest

The largest manifest (~82–86 components depending on model). Base ER605 has
~82; ER706W adds `dsl`, `lte`; ER7206/ER8411 add `dsl`, `sdwan`, `virtualWan`.
Notable: `vpn`, `sslVpn`, `wireguard`, `firewallConfig`, `attackDefense`,
`natPf`, `oneToOneNat`, `acl`, `qos`, `ddns`, `staticRouting`,
`policyRouting`, `sdwan` (selected models), `lte` (ER706W), `bandSteering`/
`mesh`/`roaming` (WiFi models), plus cross-cutting keys. Full list in
[Appendix A.4](appendix-a-feature-matrix.md#a4-component-manifests).

### 8.4.5 INFORM extra sections

The gateway has the most extensive INFORM. Notable sections:

| Section | Purpose |
|---|---|
| `portInfo` | Per-port status; WAN port carries `ip`, `netmask`, `publicWanIp`, `latency`, IPv4/IPv6 DNS/gateway. |
| `routingTable` | Routing tables (`id`, `destIp`, `nextHop`, `interfaceName`, `metric`). |
| `client` | All LAN clients (gateway aggregates the site). |
| `dhcpClient` | DHCP server leases. |
| `trafficStat` | Per-port byte/packet counters + rates. |
| `arp` | ARP table (one entry per LAN client). |
| `vpn` | IPsec (`ipSecs`), OpenVPN (`openvpn`), PPTP/L2TP (`tuns`), WireGuard (`wireguard`). |
| `sslVpn` | Active SSL-VPN connections + license locks. |
| `wireguard` | Site-to-site WireGuard interfaces + tunnels. |
| `ddns` | DDNS entries. |
| `qos` | Per-port QoS class throughput. |
| `ctTable` | Connection tracking (`ctMax`, `ctNum`). |
| `portforward` | Port forwarding rules. |
| `networkTraffic` | Per-network traffic (IPv4/IPv6 rx/tx, DHCP utilisation). |
| `ipsThreat` | IPS threat data. |
| `sdwan` | SD-WAN tunnels (capability-gated). |
| `virtualWanInfo` | Multi-WAN virtual interfaces (capability-gated). |
| `lte` | LTE APN configs (capability-gated). |
| `poe` | PoE provider (capability-gated). |
| `wSettings_*` / `radioTraffic_*` / `ssidStats_*` / `mesh` / `roaming` | Wireless sections (only when `wireless > 0`). |

### 8.4.6 Config-push SET keys

The largest SET-key surface (~80+ keys), grouped:

- **WAN/connectivity:** `wanIpv4`, `wanIpv6`, `wanMac`, `wanBasicSetting`,
  `wanLoadBalance`, `connect`, `onlineDetection`, `virtualWan`, `network`,
  `lanDns`, `iptv`, `dsl`, `lte`, `speedTest`.
- **Security/firewall/NAT:** `firewallConfig`, `attackDefense`, `natAlg`,
  `sessionLimit`, `bandwidthCtrl`, `qos`, `natPf`, `oneToOneNat`, `disableNat`,
  `acl`, `urlFiltering`, `ips`, `signatureList`, `macFilter`, `ipMacBinding`.
- **VPN:** `vpn`, `vpnUsers`, `sslVpn`, `wireguard`, `ipsecFailover`,
  `radiusProfile`.
- **Routing:** `staticRouting`, `policyRouting`.
- **Services:** `snmp`, `led`, `ssh`, `lldp`, `upnp`, `mdns`, `hwOffload`,
  `jumbo`, `ddns`, `mail`, `ldap`, `dnsProxy`, `dnsCache`, `dpiProtocols`.
- **SD-WAN:** `sdwan`, `port`, `speedDuplex`, `mirror`, `poe`.
- **Wireless (WiFi models):** `bandSteering`, `mesh`, `roaming`, `ppskV3`.
- **VoIP:** `voipDeviceOsgSetting`, `callForwarding`, `callBlocking`,
  `callLog`, `voiceMail`.

### 8.4.7 Special semantics

- **PoE role**: provider (capability-gated; all current models: no).
- **WiFi**: optional (`wireless > 0`; ER706W = Wi-Fi 5).
- **VPN config key naming**: the `vpn` SET uses underscore-prefixed keys:
  `server_IPSecs`, `server_OpenVPNs`, `server_PPTPs`, `server_L2TPs`,
  `autoIPSecs`, `manualIPSecs`, `client_Wireguards`. SSL-VPN uses `users` +
  `sslVpnServer.enable`. WireGuard uses `interfaces`/`peers`.

## 8.5 OLT (Optical Line Terminal)

**Role:** PON headend. Manages PON ports and registered ONUs. The most
architecturally distinct class — it uses URI-based RPC for detail-page
operations instead of named config keys.

### 8.5.1 Identity

| Property | Value |
|---|---|
| `header.device` | `olt` |
| `header.version` | `2.2.0` |
| Discovery controller-ID path | `controller.id` (switch-style) |
| `deviceInfo` naming | **long** (AP-style: `modelVersion`, `firmwareVersion`, `hardwareVersion`, `upTime`) |
| `upTime` format | integer (seconds) — unlike the string other classes use |
| `deviceMisc` | `{modelType:"NORMAL", category:"OLT"}` |

The OLT mixes AP-style long-name `deviceInfo` keys with switch-style
`controller.id`.

### 8.5.2 Valid models

The controller accepts only these OLT models as compatible:

| Model | Description |
|---|---|
| `DS-P7001-01` | 1 PON port, pizza-box |
| `DS-P7001-04` | 4 PON ports, pizza-box |
| `DS-P7001-08` | 8 PON ports, pizza-box (reference default) |
| `DS-P7001-16` | 16 PON ports, pizza-box |
| `DS-MCUA` | Chassis OLT |
| `DS-P8000-X2` | Chassis OLT |

Any other model → incompatible → adoption refused.

### 8.5.3 Negotiation capabilities

Unlike other wired classes, the OLT negotiation body is parsed as a distinct
shape: `{components: Map<String,String>, deviceInfo: <OLT device info>, isFactoryDefault: Boolean}`.

- The `components` map MUST include `centralManagement` — omitting it flags
  the device incompatible (value 4).
- `deviceInfo` carries `hwId`/`oemId`/`lagCount`/`ponPortCount`/`wirelessLinked`.
- `devCap`: `{ponPortCount, lagCount}`.

### 8.5.4 Component manifest

~57 components, OLT-specific vocabulary. Notable: `centralManagement` (1.1,
**required**), `ponPort`, `onuManagement` (1.1), `onuRegister` (1.1),
`lineProfile` (1.1), `serviceProfile`, `dbaProfile`, `mgmtProfile` (1.1),
`trafficProfile`, `ponProfile`, `boardControl`, `multicastInfo`,
`multicastFiltering`, `mvr`, `igmpSnooping`, `mldSnooping`, `bandWidthControl`,
`classOfService` (1.1), `voiceVlan`, `autoVoip`, `routingTable`,
`staticRouting`, `dhcpServer`/`dhcpRelay` (1.2)/`dhcpL2Relay` (1.2),
`accessSecurity`, `portSecurity`, `firmwareUpgrade`, `systemReboot`,
`resetAndBackup` (1.1), `userManagement` (1.2), `diagnostics`, `ethPort`,
`servicePort`, `lag`, `stp`, `lldp`/`lldpMed`, `dldp`, `ddm`, `snmp`, `logs`,
`trafficMonitor`, `timeRange`, `mirroring`, `ethernetOam`, `bootConfig`.
Full list in [Appendix A.4](appendix-a-feature-matrix.md#a4-component-manifests).

### 8.5.5 INFORM body

The OLT overrides the full INFORM body (not just extra sections):

| Section | Purpose |
|---|---|
| `deviceInfo` | `{name, upTime, ip, memUti, cpuUti, down, up, onuCount, portOnuCount}`. `onuCount` MUST be non-null (null → controller error). |
| `trafficStat` | `{up, down, portStats:[{port, linkStatus, rx, tx, rxP, txP, status}]}`. |
| `trafficTimeStamp` | Uptime timestamp (integer). |
| `lldp` | LLDP neighbour table. |

### 8.5.6 Config-push SET keys (minimal)

The OLT has the smallest config-push surface — only:

| SET key | Purpose |
|---|---|
| `controllerInfo` | Controller identity. |
| `highAbility` | High-ability flags. |
| `upgrade` | Firmware upgrade (not a SetKey enum member). |

No `OltGetKeyEnum` exists (no GET keys).

### 8.5.7 Detail-page operations (URI-based RPC)

The OLT detail page uses a generic URI-RPC wrapper instead of named config
keys:

```
Request:  { "uri": "<operation path>", "params": { ... } }
Response: { "deviceType": <int>, "errcode": <int>, "message": <str>, "data": <obj|null> }
```

This dispatches **230+ operations** across 30+ subsystems (PON ports, ONU
management, ONU detail, line/service/DBA/traffic profiles, VLAN/LAG/STP/MAC,
routing/ARP, multicast IGMP/MLD/MVR, security ACL/port-security, system
info/board-control/DDM/SNMP/user-management, firmware upgrade, diagnostics).
All GET (read) URIs return synthetic payloads; all SET (mutation) URIs are
acked with `data: null`.

## 8.6 Clients and topology

### 8.6.1 Clients

End-hosts (wireless or wired) are reported consistently across devices:

| Field | Description |
|---|---|
| `mac`, `ip`, `name`, `vendor` | Identity. |
| `wireless` | Wireless or wired. |
| `host_mac`, `host_port` | Infrastructure device + port attached to (0 = wireless). |
| `ssid`, `radio_id` | SSID + radio (wireless only). |
| `vlan`, `rssi`, `snr`, `rate` | VLAN, signal, rate. |
| `down_bps`, `up_bps` | Instantaneous rates. |

APs report wireless clients; switches report wired clients per port; the
gateway aggregates all site clients as DHCP leases (it is the default route +
DHCP server).

### 8.6.2 Topology

The controller builds the network topology from information devices report in
INFORM — not from live GET queries:

| Section | Used by | Output |
|---|---|---|
| `lanInfo` | APs | Wired uplink port (`rate`, `duplex`, `port`). |
| `lldp` | Switches, gateways, OLTs | LLDP neighbours per port (`chassisId`, `portId`, `name`). |
| `fdb` | Switches | MAC forwarding table — places wired APs under the switch. |

The controller correlates LLDP/FDB adjacency into a successor tree
(gateway → switch → AP).

---

Next: [Appendix A — Feature Matrix](appendix-a-feature-matrix.md)