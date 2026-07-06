# Project Status

Status of the `o-device-emulator` against a live controller:
which controller-visible features each emulated device type reports, and what is
still missing. Most telemetry is delivered by enriching the management-channel
INFORM bodies (see [doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md) §7.7–§7.8).

## How this was assessed

- Controller: Docker image `mbentley/omada-controller:6.2` (controller `6.2.14.11`,
  ECSP 1.8.6), single site, minimal onboarding (local admin account, country,
  terms). See [tools/docker-compose.yml](tools/docker-compose.yml).
- All four emulated devices (`EAP245` AP, `TL-SG3210` switch, `ER605` gateway,
  `DS-P7001-08` OLT) were adopted and reach **CONNECTED**. The OLT was
  live-validated against controller v6.2.14.11 (see
  [doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md) §4.4 / §7.9).
- Every device-detail tab/page in the controller UI was walked through, and the
  controller's per-device REST detail objects (`.../gateways|switches|eaps/{mac}`)
  were inspected to see which fields are populated vs. empty.

## Legend

- ✅ Implemented — reported by the emulator and shown by the controller.
- △ Partial — reported by the emulator; full visibility needs a controller-side
  prerequisite (e.g. a configured WLAN) or accrues over time.
- ❌ Missing — the controller has a place for it but the emulator sends nothing,
  so it renders as `--`, `No Data`, `undefined`, `0`, or an empty table.

## What already works (all device types)

- ✅ Discovery → adoption handshake → **CONNECTED**, held online via INFORM.
- ✅ Identity: model, model/hardware version, firmware version, MAC.
- ✅ Live CPU % and Memory % (Overview gauges + the rolling CPU/Mem graph points).
- ✅ Controller Connection IP.
- ✅ Config-push acknowledgement (`SET_REQUEST` → echo `configVersion`), incl.
  General settings (name, LED, remember-device) not being rejected.
- ✅ Topology / Network View: wired uplink & downlinks via LLDP / FDB / lanInfo
  (gateway → switch → AP edges are drawn).
- ✅ Gateway only: LAN IP, uptime, WAN port IPv4 (Ports → WAN), routing table.
- ✅ Switch only: device IP, uptime, per-port link up/down, STP / loopback /
  VLAN-interface / LAG / static-routing settings echoed.
- ✅ **Connected clients** on the Clients page and per-device client tables
  (AP wireless stations, switch wired clients, gateway LAN clients / DHCP
  leases), with MAC / IP / name / vendor / per-client traffic.
- ✅ **Interface traffic**: per-port byte/packet counters and instantaneous
  rates (switch `port`, gateway `trafficStat`), gateway Overview
  Upload/Download rate, AP `deviceInfo` tx/rx rate.
- ✅ AP **uptime** + **IP** in the grid, radio **mode** and per-radio
  **traffic**, and reported wireless clients.
- ✅ Switch **PoE** budget, and the Tools → **LLDP Neighbor Table** now renders.
- ✅ **Tools → Terminal**: the emulator serves the controller's in-browser shell
  over the device RTTY channel (port `29816`) with a dummy BusyBox-style shell.
  Verified live on the switch. See [doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md) §10.9.
- ✅ Gateway **DHCP leases**, **ARP** table, and WAN **latency**.

> Data is synthetic-but-deterministic (MAC-seeded, uptime-scaled); see
> `device_emulator/stats.py` and `device_emulator/devices/clients.py`. The exact
> INFORM sections/fields are documented in
> [doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md) §7.8.

## Cross-cutting gaps (affect every device type)

These were the highest-value items and are now implemented:

- ✅ **Real traffic throughput.** Overview Upload/Download rate and per-device
  tx/rx are reported (gateway `trafficStat`, switch `port`, AP `deviceInfo`).
- ✅ **Connected clients.** The Clients page and per-device client tables
  populate from the devices' INFORM (`clients` / `client` / `dhcpClient`
  sections). See [doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md) §7.8.
- △ **Device Health scoring** now works for the **AP** and **gateway** (they
  score once the controller's 10-minute health cycle runs after they connect;
  the AP required the uptime / client-`time` format fixes to become healthy).
  The **switch always shows HEALTH "No Data"** — the controller (6.2) has **no
  switch health calculator** (only the AP and gateway health calculators
  exist), so switches are not scored, for real or emulated devices alike.
  This is by controller design, not an emulator gap.
- ✅ **Tools tab: all three tools work.**
  - ✅ **Terminal** — the emulator implements the device-side RTTY client
    (controller port `29816`), so **Tools → Terminal** opens a working shell
    backed by a dummy BusyBox-style shell. Verified live on the switch. See
    [doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md) §10.9.
  - ✅ **Network Check** — the device-monitor (DMP) client is wired to the
    `monitorServer` SET-key lifecycle: the runner starts/stops
    `DeviceMonitorService` (TLS to controller port `29817`) on the push, and
    the service serves synthetic ping/traceroute probe responses
    (`device_emulator/services/network_probe.py`). The device-side channel and codec are
    complete and verified with a loopback DMP server. Full controller-UI
    verification (clicking Run in the Network Check panel) requires a
    WebSocket-capable reverse proxy to the controller (see
    `tools/controller_proxy.py`); the lab controller's `29817` is
    reachable via socat forward.
  - ✅ **Packet Capture** (AP) — **works end-to-end live** (controller v6.2):
    a `packageCapture` SET key with `operation: "start"` is acked with
    `packageCapture: {errCode: 0}`; `PacketCaptureService` builds a valid
    libpcap capture, waits the requested `duration`, then announces the file
    with a `NOTIFY_REQUEST` (`sub: 6` = `NotifySubjectEnum.FILE_TRANSFER`,
    `type: 1`, carrying `fileName`/`fileSize`/`md5`). The controller pushes a
    `transferChannel` SET; the device connects to port 29815 synchronously
    (pre-connect with `token`), and the controller sends
    `FILE_TRANSFER_REQUEST_V2` byte-range requests which the device serves as
    `FILE_TRANSFER_RESPONSE_V2` base64 partitions. The controller reassembles,
    verifies the md5, and the **Download .pcap Files** button delivers the
    capture file. Verified live: Start → "Succeeded" → Download → file
    delivered. See [doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md) §11.6.

## Access Point — `EAP245` (type `ap`)

Emulator now sends: `deviceInfo` (with `ip`, `txRate`, `rxRate`, formatted
`upTime`) + `lanInfo` + wireless `clients` + per-radio `wSettings` /
`radioTraffic` / `ssidStats` + **`uplinkPortStatus`** / **`portStatus`** (AP
LAN-port status) + **`poeInform`** (PoE / power draw) + **`mesh`** (mesh /
wireless-uplink info).

- ✅ **Uptime** and **IP** now shown in the grid/Info (uptime must use the
  `"<N> days HH:MM:SS"` format; raw seconds fail the controller's parser).
- ✅ **Radio mode** and **per-radio traffic** reported; **wireless clients**
  reported (`clients` section).
- ✅ **Force Provision automatic reconnect** — after the controller closes
  the AP management channel, the emulator reconnects with `rebuild:1` using
  the site's Device Account learned from the initial `userAccount` sync,
  returns to `CONNECTED`, and accepts the full SSID/radio configuration again
  without a manual Retry (live-confirmed on controller v6.2.14.11). Optional
  `adopt.managed_username` / `managed_password` settings provide a fallback.
- ✅ **Multi-SSID per radio** — the AP tracks *multiple* active controller-
  pushed SSID profiles per radio (not just one), assigns up to
  **`wireless_client_count`** (0-5, default 5) simulated wireless clients
  round-robin across the active SSIDs on each radio, and reports one
  `ssidStats_*` row per active profile (including zero-client profiles), each
  with a stable per-profile BSSID. VLAN/guest flow from the pushed SSID's
  `vlanId`/`portal`/`ssidIsolation`. The exact SSID `operation`
  add/update/delete numeric semantics have not been live-captured, so the
  emulator uses the documented conservative fallback (each SET's SSID list is
  the authoritative snapshot, filtering `operation == 2` / empty `ssidName`)
  — UNCONFIRMED, revisit after a live SSID CRUD capture. Full `ssid_2G` and
  `ssid_5G` snapshot delivery is live-confirmed against controller 6.2.14.11.
- ✅ **Radio channel width / utilisation / interference** and **wireless-client
  classification** require a **WLAN/SSID configured on the controller** (the AP
  reports the data in `wSettings_*` / `clients[].ssid` / `ssidStats_*`, but
  with no matching WLAN the controller shows `undefined` and the AP's clients
  appear as wired via the gateway). The SSID and radio config (channel /
  channel-width / txPower) are **controller-pushed**, not device-side
  properties: the controller sends the WLAN/SSID via `ssid_2G` / `ssid_5G` /
  `ssid_5G2` / `ssid_6G` SET keys (the SSID config section →
  `ssidName`) and the radio config via `wirelessBasic_<band>G` →
  the wireless basic config section (`channel`/`chanWidth`/`txPower`); the AP captures both
  in `build_set_response` and reports the applied values in its INFORM
  (`clients[].ssid` / `ssidStats_*.ssid` / `wSettings_<band>G.ch|bw|txPower`),
  and `build_get_response` echoes the applied config so the WLAN / Radio config
  tabs stay in sync. Before any push the AP reports synthetic defaults
  (`_DEFAULT_SSID` / `_RADIOS`) so the INFORM is well-formed. AP negotiation
  advertises populated `channelInfo` and `radioCap` lists; empty/malformed
  values prevent the controller from resolving radios and generating the SSID
  SET keys. See [doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md) §7.8.
- ✅ **AP LAN-port status** — `uplinkPortStatus` (the AP uplink port status
  section: `port`, `portType`, `duplex`, `link`, `speed`) for the wired uplink
  port, and `portStatus` (the AP downlink port status section, same field set)
  for any downlink LAN ports on multi-port APs. Field shapes documented in
  doc/DEVICE_PROTOCOL.md §7.8. Config: `lan_ports` (default 1).
- ✅ **AP downlink LAN-port traffic** — `portTraffics` (the AP downlink port
  traffic section: `port`, `rxP`, `txP`, `rx`, `tx`, `rxDP`, `txDP`, `rxEP`,
  `txEP`) reports
  deterministic traffic counters for downlink LAN ports on multi-port APs
  (omitted for a single-port AP, whose only port is the uplink).
- ✅ **PoE / power draw** — `poeInform` (the AP PoE status section: `remain`,
  `percent`, `total`, `poeStartUp`) reports the AP's received PoE budget (PoE
  *consumer*,
  802.3at PoE+ 25 W). Non-PoE APs (`supports_poe: false`) report a zero budget.
  Config: `supports_poe` (default true).
- ✅ **Mesh / wireless-uplink info** — `mesh` (the mesh info section:
  `status`, `meshRid`, `isolatedAPs`, `childAPs`, `candidateParents`) reports
  an inactive/non-mesh
  state (`status: 0`, empty lists) for a wired AP, or an active mesh uplink
  with a synthetic parent candidate for `wireless_uplink: true`. Config:
  `wireless_uplink` (default false).
- ✅ **Tools:** **Terminal** works (RTTY client, §10.9); **Network Check**
  serves synthetic ping/traceroute via DMP (§11); **Packet Capture** works
  end-to-end (§11.6). See the cross-cutting Tools item above.

## Switch — `TL-SG3210` (type `switch`)

Emulator now sends: `deviceInfo` + per-port link `status` + per-port traffic,
`lldp`, `fdb`, wired `client` list, `poe`, and the Layer-3 `routingTable` +
`loopback` status.

- ✅ **Per-port traffic statistics** — `tx`/`rx`/`txP`/`rxP` on linked ports
  (Ports tab TX SUM / RX SUM populate).
- ✅ **PoE budget** reported (`poe`); zero for the non-PoE TL-SG3210, real
  per-port draw for PoE models (the `SwitchDevice.supports_poe` model
  attribute, set by the per-model switch profile — not a YAML config key).
- ✅ **Wired client list** (`client` → the switch client stats section).
- ✅ **Tools → LLDP Neighbor Table** renders (fixed `port`/`standardPort` keys).
- ✅ **Layer 3 / static routing** — the TL-SG3210 v3 is a Layer-3 switch. The
  INFORM now carries a `routingTable` section (the switch inform routing
  section → `routingTables` → the routing table entries with
  `destIp`/`nextHop`/`distance`) so **Tools → Routing Table** populates with
  the directly-connected network, a default route via the upstream gateway,
  and any operator-configured static routes. The switch acks `staticRouting`
  SET pushes (the static routing config section → `staticRoutings` list of
  static routing entries) and echoes the applied config on GET, so the
  **Routing** config tab and the routing table stay in sync. Loopback
  interface (`loopbackInterface` SET / `loopback` INFORM) and VLAN-interface
  (`vlanIf`) config pushes are also acked/echoed.
- ✅ **LAG runtime status** — the INFORM now carries a `lag` section
  (the switch LAG inform section → `lags` list of LAG status entries with
  `lag`/`stMembers`/`duplex`/`status` + `rates`) so the Ports → LAG tab
  populates with synthetic LAG groups on linked ports.
- ✅ **SFP / DDM runtime status** — the INFORM now carries a `ddm` section
  (the switch DDM info section → `ports` list of per-port DDM info entries
  with nested temperature / voltage / bias-current / tx-power / rx-power
  sub-objects, each with raw value + high/low alarm/warn thresholds + status)
  for the 2 SFP ports (`sfpBeginNum:9`, `sfpNum:2`).
- ✅ **Per-port runtime STP state** — the INFORM now carries a `stpInform`
  section (the switch STP info section → `ports` list of per-port STP entries
  with `port`/`standardPort`/`stpState`/`stpVlan`) so Tools → STP status
  populates.
- ✅ **Tools:** **Terminal** works (RTTY client, §10.9); **Network Check**
  serves synthetic ping/traceroute via DMP (§11); **Packet Capture** works
  end-to-end (§11.6). See the cross-cutting Tools item above.

## Gateway — `ER605` (type `gateway`)

Emulator now sends: `deviceInfo` + `portInfo` (WAN IPv4 + IPv6 + `latency`),
`trafficStat`, `client`, `dhcpClient`, `arp`, `lldp`, `routingTable`, **`vpn`**,
**`sslVpn`**, **`wireguard`**, **`ddns`**, **`qos`**, **`ctTable`**,
**`portforward`**, **`networkTraffic`**, **`ipsThreat`**, **`sdwan`**,
**`virtualWanInfo`**, **`lte`**, **`clientTraffic`**, **`abnormalDt`**,
**`eventInform`**, **`aclHit`**, **`portalDuration`**, **`applicationsTraffic`**,
**`poe`**, **`lastCfgResult`**, **`cfgResults`**, **`monitor`**, and IPv6 on
the WAN port (`ip2`/`netmask2`/`ip6` in `portInfo`).

- ✅ **WAN / per-port traffic** — `trafficStat` (bytes/packets/rates) drives the
  Overview Upload/Download rate and per-port traffic.
- ✅ **DHCP client / lease list** (`dhcpClient`) and **LAN clients** (`client`).
- ✅ **ARP table** (`arp`) and WAN **latency** (`portInfo.latency`).
- ✅ **VPN status** — `vpn` section (the gateway VPN stats section): IPsec
  tunnels (the IPsec tunnel section), OpenVPN tunnels (the OpenVPN tunnel
  section), and PPTP/L2TP tunnels (the PPTP/L2TP tunnel section), each with
  up/down bytes/packets, uptime, and identity.
- ✅ **SSL VPN** — `sslVpn` section (the SSL VPN inform section): active
  connections (the SSL VPN tunnel section) and license locks (the SSL VPN lock
  entry section).
- ✅ **WireGuard** — `wireguard` section (the WireGuard stats section):
  interface stats (the WireGuard interface entry section) and peer tunnels
  (the WireGuard tunnel entry section).
- ✅ **DDNS status** — `ddns` section (the gateway DDNS inform section → the
  DDNS entry section with `domain`/`interface`/`ip`/`status`/`lastUpdated`).
- ✅ **QoS / bandwidth-control** — `qos` section (the gateway QoS inform
  section → the QoS data entry section with per-port `throughputs` list of
  class data entries and `voip` VoIP data entries).
- ✅ **Connection-tracking** — `ctTable` section (the gateway connection-
  tracking inform section with `ctMax`/`ctNum` session counts).
- ✅ **Port forwarding** — `portforward` section (the gateway port-forwarding
  stats inform section → the port-forwarding stats section with `users`/
  `upnps` lists).
- ✅ **IPS threats** — `ipsThreat` section (`IpsThreatInfo` → `IpsThreatData`
  with time/severity/description/src/dst IP).
- ✅ **Network traffic** — `networkTraffic` section (the gateway network
  traffic inform section → the network traffic section with per-VLAN rx/tx
  + DHCP utilisation).
- ✅ **SET/GET round-trip** — `build_set_response` now captures
  `firewallConfig`/`natAlg`/`sessionLimit`/`bandwidthCtrl`/`iptv`/
  `attackDefense`/`ddns`/`vpn`/`portforward`/`qos`/`onlineDetection` and
  more; `build_get_response` echoes `vpn`/`sslVpn`/`ddnsStats`/
  `sessionLimit` under their gateway GET response keys.
- ✅ **Config-driven INFORM sections** — `routingTable`, `ddns`, `qos`,
  `portforward`, and `ipsThreat` now reflect the controller-pushed SET config
  (matching how the switch echoes `staticRouting`), instead of hardcoded
  synthetic data. `ipsThreat` is omitted entirely when IPS is disabled.
- ✅ **Full SET ack coverage** — every feature key present in a SET body is
  with `{key: {errcode: 0}}` (the full gateway SET key set, not a subset).
  An empty SET body still returns the base ack (an empty `{}` would make the
  controller forget the device).
- ✅ **Full GET response coverage** — `build_get_response` echoes all captured
  configs under the complete GET key map, plus dedicated response bodies
  (`arptable`, `dnsCache`, `dpiProtocols`) and the pushed `wanIpv6` config.
- ✅ **Complete deviceInfo** — INFORM `deviceInfo` carries the full
  gateway inform device-info fields (`sm`/`cerVer`/`ipv6List`/`fac`/`temp`/
  `txRate`/`rxRate`) and the negotiation `deviceInfo` carries
  `encryptedHwId`/`hwId`/
  `oemId`/`modelId`/`speeds`/`mask`. The WAN port reports `publicWanIp` and the
  full `ip4` entry (`gw2`/`priDns2`/`sndDns2`).
- ✅ **cfgResults history + vpn.wireguard** — `cfgResults` now reports a rolling
  history of recent SET responses (capped at 10); the `vpn.wireguard` sub-field
  (the gateway VPN client-to-site WireGuard section) is populated from pushed
  VPN config `client_Wireguards`.
- ✅ **Multi-model gateway profiles** — ER605 (default), ER706W (LTE+VPN),
  ER7206 (SD-WAN+multi-WAN), ER8411 (high-end dual-WAN+SFP). The `model`
  config key selects the profile; each has different port counts, VPN
  capacity specs, and capability flags (LTE, SD-WAN, multi-WAN, PoE).
- ✅ **Config-driven VPN telemetry** — IPsec/OpenVPN/PPTP/L2TP/SSL-VPN/
  WireGuard tunnel counts and identity now reflect the controller-pushed
  `vpn`/`sslVpn`/`wireguard` SET config instead of hardcoded synthetic
  defaults. Traffic stats remain synthetic.
- ✅ **Complete SET/GET round-trip** — `build_set_response` now adds
  per-feature gateway configure-response ack sub-objects
  (`{key: {errcode: 0}}`) for all 40+ captured feature config keys.
  `build_get_response` echoes ALL captured configs under their gateway GET
  response keys (not just 4).
- ✅ **Multi-WAN / LTE / SD-WAN / load-balance** — `sdwan`, `virtualWanInfo`,
  and `lte` INFORM sections now emitted on supporting models (ER706W,
  ER7206, ER8411). The ER605 does not support these (no `supportLte`/
  `supportSdWan`/`supportDiscreteWan` flags).
- ✅ **Tools:** **Terminal** works (RTTY client, §10.9); **Network Check**
  serves synthetic ping/traceroute via DMP (§11); **Packet Capture** works
  end-to-end (§11.6). See the cross-cutting Tools item above.

## OLT — `DS-P7001-08` (type `olt`) — CONFIRMED (controller v6.2.14.11)

The OLT (PON optical line terminal) is live-validated end-to-end against
controller v6.2.14.11: discovery → adoption → **CONNECTED** (status 14) with
periodic INFORM heartbeats. The discovery body uses the long-name `deviceInfo`
+ the switch/gateway `controller`/`id` convention (NOT the AP-style
`controllerSetting`), with `deviceMisc` = the base device-misc section, of
whose fields (`modelType`/`category`/`supportCluster`) the emulator sends
`modelType` and `category` — `supportCluster` is optional and omitted. The
`DEVICE_NEGOTIATION` body is parsed by the controller as the OLT adoption
response body (`components` string map + `deviceInfo` OLT adopt device-info +
`isFactoryDefault`). The INFORM body uses the OLT inform body: `deviceInfo`
(the OLT inform device-info section with `onuCount`/`portOnuCount`/`cpuUti`/
`memUti`/`upTime`) + per-PON-port `trafficStat` + `lldp`.

- ✅ **Discovery → adoption → CONNECTED** — confirmed live (status 14,
  compatible 0). The controller's model whitelist accepts only
  `DS-P7001-01/04/08/16`, `DS-MCUA`, `DS-P8000-X2`; any other model is flagged
  `compatible: 10` (incompatible) and rejected at adoption.
- ✅ **Uptime / CPU / Memory / download / upload** populate in the controller
  grid from the OLT INFORM.
- ✅ **PON / ONU management** — the controller's OLT management subsystem
  (PON ports, ONU profiles, ONU management, DDM status) is now served via
  synthetic URI-RPC responses. `pon/pon-port/informations/list` returns
  PON port information entries; `pon/onu/management/information/list`
  returns ONU information entries with serial/MAC/status/optical power;
  `pon/onu/management/information/get` returns the nested ONU detail config.
  See the OLT detail-page operations item below.
- ✅ **QoS / L3 / IGMP multicast / security / system detail-page data** —
  all served via synthetic URI-RPC responses (see the OLT detail-page
  operations item below). The firmware-upgrade config (the OLT upgrade config
  section = `{reboot, interval}`) is acked/captured by `build_set_response`;
  the upgrade execution itself is acked via `system-tools/reboot/now`.
- ✅ **`controllerInfo` / `highAbility` / `upgrade` config push handling** —
  `OltDevice.build_set_response` now acks and captures the two OLT SET keys
  (`controllerInfo` → the controller-info section, `highAbility` → the
  high-ability config section) plus the OLT config body `upgrade` field.
  URI-based SET / GET detail requests receive the correct generic
  device-response-body wrapper. See
  [doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md) §7.9.3.
- ✅ **OLT detail-page operations (URI-RPC)** — the emulator now dispatches
  all OLT detail-page operations via a synthetic URI-RPC handler table
  (`device_emulator/devices/olt_detail_ops.py`). The full URI surface (230+
  operations across 30+ subsystems) was mapped from the controller's OLT
  management surface; the response field names from the controller's OLT
  management API definitions. GET (read) URIs return realistic synthetic
  payloads matching the controller's OLT management response shapes so every
  detail-page tab has non-empty data:
  - ✅ **PON ports** — `pon/pon-port/informations/list` (the PON port info
    section: portId/onuNum/status/maxBandwidth/opticalVcc/opticalBias/
    opticalPower), `pon/pon-port/configs/list`,
    `pon/auto-service-ports/list`, `pon/service-ports/list` (the service-port
    section), `pon/onu-register/autofinds/list`.
  - ✅ **ONU management** — `pon/onu/management/information/list`
    (the ONU info section: onuId/serialNumber/macAddress/adminStatus/
    onlineStatus/configStatus/lineProfile/serviceProfile/receivedOpticalPower/
    transmittedOpticalPower) and `.../get` (the ONU detail config section with
    nested basic/capability/opticalLink/software info).
  - ✅ **PON profiles** — DBA profiles (the DBA profile section), line
    profiles (the line profile section + t-conts + gem-ports + gem-mappings),
    service profiles (the service profile section + eth/pots ports), traffic
    profiles (the traffic profile section).
  - ✅ **L2 — Ethernet ports** — `eth-port/port/unit1/list`
    (the Ethernet unit-1 port section: port/speed/duplex/linkStatus/mediaType),
    port mode, port isolation.
  - ✅ **L2 — VLAN** — `vlan/8021q/vlan-configs/list` (the VLAN config section:
    vlanId/vlanName/unTaggedPorts/taggedPorts), per-port VLAN config, GVRP.
  - ✅ **L2 — LAG** — `lag/lag-table/list` (the LAG config section),
    `lag/lacp-config` (the LAG global section), static LAG.
  - ✅ **L2 — STP** — `stp/summary/summarys/get` (the STP summary section),
    global config, parameters, per-port STP, MSTP instances/region.
  - ✅ **L2 — LLDP** — global config, per-port config, neighbor info, local
    info, statistics.
  - ✅ **L2 — MAC address** — `mac-address/list` (the MAC address section).
  - ✅ **L3 — routing** — `routing-table/ipv4-tables/list`, `static-routing/
    ipv4-configs/list`, IPv6 variants, interface configs, routing configs.
  - ✅ **L3 — ARP** — `arp/arp-tables/list` (the ARP table section),
    gratuitous/proxy ARP, static ARP.
  - ✅ **Multicast — IGMP** — `igmp/global-config/get`
    (the IGMP global config section), VLAN configs, port configs, static groups.
  - ✅ **Multicast — MLD** — global config, VLAN/port configs, static groups.
  - ✅ **Multicast — MVR** — `mvr/config/configs/get` (the MVR config section),
    group configs, port configs, static-group members, multicast statistics.
  - ✅ **Security — ACL** — `acl/configs/list` (the ACL config section),
    IP/IPv6/MAC/combined rules, ACL bindings (port/VLAN).
  - ✅ **Security — port security / access security** — port-security configs,
    SSH config.
  - ✅ **QoS** — DSCP, per-port CoS, scheduler, auto-VoIP, voice-VLAN
    (global/port/OUI).
  - ✅ **System** — `system-info/configs/get` (the system-info section with
    20 fields), LED config, system time, CPU/memory monitor
    (`system-monitor/cpu|memory/list`), board control/service/status (the
    board-info section with nested boardDetail/boardControl/linkBackupConfig),
    boot config, image table.
  - ✅ **DDM** — `ddm/status/info/get` (the DDM status result section:
    per-PON-port temperature/voltage/biasCurrent/txPower/rxPower with
    alarm/warn flags), port config, thresholds (rx-power/tx-power/voltage).
  - ✅ **SNMP** — global config, v1-v2c communities, v3 users/groups, views,
    notifications/traps, RMON alarms/events/histories/statistics.
  - ✅ **Maintenance** — logs (info/local/remote/backup), OAM (basic/discovery/
    link-monitor/statistics), DLDP (global/ports), mirror sessions, CFM
    (MA-groups/local-mep/remote-mep).
  - ✅ **User management** — `user-management/users/list` (the OLT user
    section).
  - ✅ **Diagnostics** — ping/tracert configs and results.
  - ✅ **System tools** — `system-tools/reboot/now` (returns status),
    `config/backup`/`config/save`/`config/restore` (return status),
    `boot-config/list`, `image-table/list`, `factory-reset`.
  SET (mutation) URIs are universally acked with `errcode: 0`; status-returning
  operations (reboot, backup) return a small status object. Uncovered URIs
  return `data: null` with `errcode: 0` (empty section, no error). All synthetic
  data is deterministic per-device (MAC-seeded) via `device_emulator/stats.py`.
  See [doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md) §7.9.3.

## Remaining work (not yet implemented)

All previously identified gaps are now implemented. The items below are
complete; this section is retained for historical reference.

1. ~~**Tools tab** (all types): Terminal, Network Check, and Packet Capture.~~
   ✅ All three Tools features are implemented and live-verified. See the
   cross-cutting Tools item above and [doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md) §10.9 / §11.
2. **AP wireless visibility**: configure a WLAN/SSID on the controller so the
   reported radios/clients classify as wireless (controller-side prerequisite).
   The emulator now correctly captures the controller-pushed SSID (`ssid_2G` /
   `ssid_5G` SET keys → the SSID config section → `ssidName`) and reports it in
   INFORM `clients[].ssid` / `ssidStats_*.ssid`; `build_get_response` echoes
   the applied config. Channel width / utilisation / interference were already
   reported in `wSettings_*`; the remaining △ is purely the controller-side
   WLAN/SSID setup. **SSID CRUD semantics** (the SSID `operation` 1=add,
   2=delete, 3=update) are now implemented in `_apply_ssid_config` — the AP
   processes per-entry CRUD
   deltas against the existing profile list, with a full-snapshot fallback
   when no operations are present.
3. ~~**Gateway services**: VPN / firewall-NAT-session / IPTV-QoS / DDNS runtime.~~
   ✅ Implemented — `vpn`/`sslVpn`/`wireguard`/`ddns`/`qos`/`ctTable`/
   `portforward`/`networkTraffic`/`ipsThreat` sections now sent; SET/GET
   round-trip for feature configs.
4. ~~**Switch**: LAG / SFP / DDM runtime and per-port STP runtime state.~~
   ✅ Implemented — `lag`/`ddm`/`stpInform` sections now sent; LAG/STP SET/GET
   round-trip.
5. **OLT**: discovery → adoption → CONNECTED is confirmed live (see the OLT
   section above). The `controllerInfo` / `highAbility` / `upgrade` config-push
   handling is implemented (see the OLT section above). OLT detail-page
   operations (PON/ONU, profiles, QoS, L3, IGMP multicast, security, DDM, SNMP,
   system, users, diagnostics, system-tools) are now implemented via a
   synthetic URI-RPC dispatch table — every GET URI returns a realistic
  payload matching the controller's OLT management response shapes, and
  every SET URI is acked (see the OLT section above and §7.9.3). **OLT firmware
  upgrade
   execution** is implemented: the `upgrade` config push and
   `system-tools/firmware/upgrade` SET record the upgrade state, which is
   reflected in the `system-tools/image-table/list` GET and
   `system-tools/firmware/upgrade/status` GET.
6. **Gateway multi-model + missing sections**: ✅ Implemented — multi-model
  profiles (ER605/ER706W/ER7206/ER8411), all remaining gateway inform-body
  sections (sdwan, virtualWanInfo, lte, clientTraffic, abnormalDt, eventInform,
  aclHit,
   portalDuration, applicationsTraffic, poe, lastCfgResult, cfgResults, monitor,
   IPv6 on WAN port), config-driven VPN telemetry, complete SET/GET round-trip
   with per-feature acks.
7. **Gateway full emulation**: ✅ Implemented — config-driven INFORM sections
   (routingTable/ddns/qos/portforward/ipsThreat now reflect pushed config), full
  SET ack coverage (every gateway SET key in the SET body is acked), full
  GET response coverage (complete GET key map + `arptable`/`dnsCache`/
  `dpiProtocols`/`wanIpv6` dedicated bodies), complete gateway inform
  device-info + negotiation identity fields, WAN port `publicWanIp`/`gw2`/
  `priDns2`/`sndDns2`, `cfgResults` rolling history, `vpn.wireguard` sub-
  field, and confirmed VPN config field names (the gateway VPN config / SSL
  VPN config / WireGuard config sections).
- ✅ **Wireless gateway sections** — WiFi-capable gateway models (`wireless >
  0`, e.g. ER706W) now emit per-radio `wSettings_<band>G` /
  `radioTraffic_<band>G` / `ssidStats_<band>G` plus `mesh` / `roaming`
  INFORM sections. A wired-only gateway (ER605, `wireless=0`) does not emit
  them.
- ✅ **VoIP / telephony sections** — the gateway now captures
  `voipDeviceOsgSetting` / `callForwarding` / `callBlocking` / `callLog` /
  `voiceMail` / `voiceMailDownload` / `voiceMailSettings` / `voipViaIpv6` /
  `numberAdvancedSetting` SET keys (echoed on GET) and emits a
  `callLogInform` INFORM section (synthetic call-log entries per VoIP port)
  when `voipDeviceOsgSetting` has been pushed.

The exact INFORM sections and field names for everything already implemented are
documented in [doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md) §7.8.

