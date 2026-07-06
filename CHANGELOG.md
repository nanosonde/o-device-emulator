# Changelog

All commits in reverse chronological order (newest first). Each entry shows
the committer date and the full commit message.

---

## 2026-08-13

```
feat: implement all remaining backlog items for full device emulation

Implements the 7 prioritized backlog items, completing full emulation for all
device types:

1. OLT PON/ONU + QoS/L3/IGMP/security URI-RPC operations (already done in
   prior commit — OLT detail-ops dispatch table with 138 GET URIs + 160 SET
   URIs).

2. OLT firmware upgrade execution:
   - The `upgrade` config push (OLT upgrade config = {reboot, interval}) and
     `system-tools/firmware/upgrade` SET now record per-device upgrade state
     in `olt_detail_ops._UPGRADE_STATE`.
   - `system-tools/image-table/list` GET reflects the new firmware version.
   - `system-tools/firmware/upgrade/status` GET returns the upgrade status.

3. AP SSID operation CRUD semantics:
   - `EapDevice._apply_ssid_config` now processes the SSID profile `operation` field
     with proper CRUD semantics: operation==1 (add), ==2 (delete), ==3 (update).
   - A SET with no operations (all 0/missing) is treated as a full snapshot
     (the confirmed full-config-sync behavior).
   - CRUD deltas modify the existing profile list: add appends, delete removes
     by id/index/name, update modifies fields while preserving the stable
     profile_key (so client assignments stay stable).
   - Constants: _SSID_OP_ADD=1, _SSID_OP_DELETE=2, _SSID_OP_UPDATE=3.

4. Gateway wireless INFORM sections (WiFi-capable models):
   - Gateways with `wireless > 0` (e.g. ER706W) now emit per-radio
     `wSettings_<band>G`, `radioTraffic_<band>G`, `ssidStats_<band>G` plus
     `mesh` and `roaming` INFORM sections.
   - Wired-only gateways (ER605, wireless=0) do not emit them.
   - New method: `GatewayDevice._wireless_sections()`.

5. RTTY reverse-tunnel TCP forwarding:
   - `RttyService._handle_tunnel_add` now opens a real TCP connection to the
     specified local address:port and relays data bidirectionally via
     TCPDATA/SSHDATA/HTTPSDATA frames.
   - New `_TunnelRelay` class: background thread reading local socket → RTTY
     channel, with `send_to_local()` for controller→local forwarding.
   - `_handle_tunnel_data` dispatches to the correct tunnel by tunnel_id.
   - Tunnels are cleaned up on TUNNEL_DELETE and on RTTY connection drop.

6. IP auto-detection in registry:
   - `build_device` with `ip: auto` (or missing ip) now auto-detects the host's
     primary non-loopback IPv4 via a UDP socket connect trick.
   - New function: `registry._detect_local_ip()`.
   - No longer raises ValueError for `ip: auto`.

7. Gateway VoIP / telephony sections:
   - Added VoIP SET keys to _CAPTURED_SET_KEYS: voipDeviceSetting,
     callForwarding, callBlocking, callLog, voiceMail, voiceMailDownload,
     voiceMailSettings, voipViaIpv6, numberAdvancedSetting.
   - Added VoIP GET echo keys for all above.
   - New `_voip_section()` method emits `callLogInform` INFORM section with
     synthetic call-log entries when voipDeviceSetting is pushed.

Tests: 22 new tests (3 OLT firmware upgrade, 6 SSID CRUD, 7 gateway wireless,
4 gateway VoIP, 4 RTTY tunnel relay). 271 tests pass; daemon --dry-run OK.
```

## 2026-08-13

```
feat(gateway): full gateway device emulation + live-validation fixes

Complete the remaining features for full wired-gateway emulation:

- Config-driven INFORM sections: routingTable, ddns, qos, portforward, and
  ipsThreat now reflect the controller-pushed SET config (matching how the
  switch echoes staticRouting). ipsThreat is omitted entirely when IPS is
  disabled.
- Full SET ack coverage: every feature key present in a SET body is acked
  with {key: {errcode: 0}} (the full gateway SET key set, not a subset). An empty
  SET body still returns the base ack (an empty {} would make the controller
  forget the device).
- Full GET response coverage: complete GET key map echoes all captured
  configs; dedicated response bodies for arptable, dnsCache, dpiProtocols,
  and the pushed wanIpv6 config.
- Complete deviceInfo: INFORM deviceInfo carries the full gateway INFORM
  deviceInfo fields (sm/cerVer/ipv6List/fac/temp/txRate/rxRate); negotiation
  deviceInfo carries encryptedHwId/hwId/oemId/modelId/speeds/mask. WAN port
  reports publicWanIp and the full ip4 entry (gw2/priDns2/sndDns2).
- cfgResults now reports a rolling history of recent SET responses (capped
  at 10); the vpn.wireguard sub-field (gateway wireguard client-to-site
  config) is populated from the pushed VPN config's client_Wireguards.
- Confirmed VPN config field names against verified v6.2.14.11 formats:
  the VPN config uses server_IPSecs/server_OpenVPNs/server_PPTPs/server_L2TPs/
  client_Wireguards (not the legacy ipsecTunnels/ipSecs guesses);
  the SSL-VPN config uses users/locks/sslVpnServer (not sslVpnUsers).

Wireless gateway sections (ssidStats/radioTraffic/wSettings/mesh/roaming)
and VoIP sections remain out of scope. 18 new tests (221 total, all passing).

Live-validated against controller v6.2.14.11: ER605 gateway reaches
CONNECTED, receives SET_REQUEST with 31 config keys (incl. wanIpv4/wanIpv6/
wanMac), and INFORM heartbeats process without errors. Three bugs found and
fixed during live validation:

- fix(discovery): format uptime as "N days HH:MM:SS" in discovery body
  (raw str(seconds) caused an array index error in
  the controller's discovery handler)
- fix(gateway): split INFORM-only gateway INFORM deviceInfo fields (sm/cerVer/
  ipv6List/temp/fan/rps/txRate/rxRate) from negotiation deviceInfo via
  manage_inform_body() override — leaking them into the negotiation body
  stalled the adoption handshake (AdoptSuccessTimeout)
- fix(gateway): correct field type mismatches — txRate/rxRate are Integer
  (not accumulated bytes), publicWanIp is Integer flag (not IP string),
  temp is Integer (not float)
```

## 2026-08-10 21:38:07+02:00

```
feat(gateway): multi-model profiles, all missing INFORM sections, config-driven VPN, complete SET/GET round-trip

Add multi-model gateway profile system (ER605/ER706W/ER7206/ER8411) with
per-model capability flags (LTE, SD-WAN, multi-WAN, PoE, IPv6). Implement
all remaining gateway INFORM body sections: sdwan, virtualWanInfo, lte,
clientTraffic, abnormalDt, eventInform, aclHit, portalDuration,
applicationsTraffic, poe, monitor, lastCfgResult, cfgResults, and IPv6
on the WAN port. Make VPN/SSL-VPN/WireGuard telemetry config-driven from
controller-pushed SET configs. Add per-feature gateway SET response ack
sub-objects in build_set_response and echo all captured configs in
build_get_response. 46 new tests (203 total, all passing).
```

## 2026-08-07 17:04:21+02:00

```
fix(ap): fix provisioning and reconnect
```

## 2026-08-06 19:20:29+02:00

```
fix(tools): handle backup compression
```

## 2026-08-06 19:15:42+02:00

```
feat(tools): add controller backup encryption tools
```

## 2026-08-06 18:55:28+02:00

```
chore: add service log and aggregate commands
```

## 2026-08-06 18:45:19+02:00

```
docs: document local controller URL usage
```

## 2026-08-06 18:42:25+02:00

```
chore: add emulator just commands
```

## 2026-08-06 18:13:24+02:00

```
docs: align documentation and comments with the code

Audit of README/STATUS/DEVICE_PROTOCOL/config.example against the
implementation, fixing the claims that no longer matched:

- STATUS: correct the ECSP version for controller 6.2.14.11 to 1.8.6;
 drop the "jumbo" claim from the switch (only the gateway captures it)
 and list what the switch actually echoes; fix the network_probe.py
 path; note that supports_poe is a SwitchDevice model attribute, not a
 YAML key; state that supportCluster is omitted from OLT discovery.
- DEVICE_PROTOCOL: 7.2 said the management header omits `timestamp`,
 but ManageService always sends it (and 11.8 requires it); align the
 OLT device-misc note with the emitted body; normalise the 10.9 module
 paths to full device_emulator/... paths.
- config.example: adoption is confirmed for OLTs too; fix the 8 -> 7
 section cross-reference; document the country_code,
 local_uplink_port and gateway `wireless` keys the registry accepts.
- discovery.py: match the OLT builder docstring to the returned body.
- sim_cli: the OLT default model TL-OLT2008 is not in
 olt_profile.VALID_MODELS, so the controller would reject it as
 incompatible; use olt_profile.DEFAULT_MODEL like the registry does.
- docker-compose: rename the controller container to
 the controller container.
```

## 2026-08-06 17:58:23+02:00

```
refactor(olt): unify OLT configuration
```

## 2026-08-06 17:47:38+02:00

```
chore: clean terminology and lint findings
```

## 2026-08-06 17:41:08+02:00

```
chore: promote controller tools to root directory
```

## 2026-08-05 21:37:35+02:00

```
feat(ap): configurable wireless client count, multi-SSID per radio, port traffics

- EapDevice.wireless_client_count (0-5, default 5): validated in
 registry.build_device, round-robin distributed across supported radios
 in clients.synthesize_site_clients.
- Multi-SSID effective state per radio: _active_ssids_by_radio /
 _apply_ssid_config replace the old scalar single-SSID model, supporting
 multiple active controller-pushed SSID profiles per radio (add/rename/
 delete, hidden SSIDs, explicit-empty vs never-configured). Uses the
 documented conservative snapshot interpretation for the SSID profile
 `operation` field
 (UNCONFIRMED - live SET capture was attempted but blocked by a bug in
 the lab controller build; see /memories/repo/ap-wlan-ssid-set-dtos.md).
- _radio_client_assignments: single source of truth round-robining clients
 across a radio's active SSID profiles, feeding the client/SSID stats sections.
- stats.synthetic_bssid: stable per-SSID-profile BSSID (distinct OUI from
 client MACs).
- AP portTraffics INFORM section (AP downlink port traffics, confirmed format)
 for multi-port AP downlink traffic counters.
- Docs: STATUS.md, doc/DEVICE_PROTOCOL.md §7.8, config.example.yaml.
- 22 new tests (148/148 passing).
```

## 2026-08-05 18:56:02+02:00

```
feat: align controller-pushed device configuration
```

## 2026-08-05 17:42:58+02:00

```
feat(ap): add mesh, LAN-port status, and PoE/power-draw INFORM sections

The EAP emulator advertised mesh, lanPort, and powerControl components in
its components_v2 manifest but never emitted the corresponding INFORM
sections. This adds three new sections to EapDevice.manage_inform_extra():

- uplinkPortStatus (AP uplink port status): the AP's wired uplink LAN port
 status (port, portType, duplex, link, speed).
- portStatus (AP downlink port status): downlink LAN ports for multi-port APs
 (same field set; emitted only when lan_ports > 1).
- poeInform (AP PoE status): the AP's PoE consumer status (remain, percent,
 total, poeStartUp). Reports a 25W 802.3at budget with synthetic draw for
 PoE-powered APs; zero budget for non-PoE APs.
- mesh (mesh info): mesh/wireless-uplink info. Wired APs report status=0
 (inactive) with empty lists; wireless_uplink=true reports status=1
 with a synthetic parent candidate.

Field formats were determined from the mesh, AP uplink port status,
AP downlink port status, and AP PoE status formats from the controller.

Config knobs added: lan_ports (default 1), supports_poe (default true),
wireless_uplink (default false), wired through registry.py.

Verified live against the controller v6.2: AP reaches CONNECTED,
the UI displays 'PoE Power Used: 16.10W / 25.00W', the mesh section
correctly reports inactive for a wired AP, and zero controller
deserialization errors across 100+ INFORM cycles. All 108 tests pass.
```

## 2026-08-04 17:44:01+02:00

```
docs: correct README.md and STATUS.md to reflect implemented Tools (Network Check + Packet Capture)

- README.md: add pcap.py, packet_capture.py, transfer_channel.py to Package
 Layout; mention Terminal/Network Check/Packet Capture in Scope and intro.
- STATUS.md: mark all three Tools tab features ✅ (Terminal, Network Check,
 Packet Capture); remove stale 'not host-published'/'PROVISIONAL'/'live UI
 pending' caveats; update per-device Tools lines (AP/switch/gateway/OLT);
 clean up Remaining work item 1 (done) and item 5 (OLT adoption confirmed).
```

## 2026-08-04 17:27:56+02:00

```
feat: implement Tools: Network Check and Packet Capture

Network Check (ping/traceroute):
- Wire DeviceMonitorService to monitorServer SET-key lifecycle
- Serve synthetic ping/traceroute probes via DMP channel (port 29817)
- 16 new tests (test_network_check.py)

Packet Capture (live-verified end-to-end against controller v6.2.14.11):
- packageCapture SET ack with {errCode: 0} (fixes 'No device response')
- Valid libpcap generator with ARP/ICMP/TCP/UDP frames (correct checksums)
- File-transfer protocol: device announces via NOTIFY_REQUEST (sub=6),
 serves FILE_TRANSFER_REQUEST_V2 byte-range partitions as
 FILE_TRANSFER_RESPONSE_V2 base64 chunks
- transferChannel SET-key: synchronous pre-connect on port 29815
- 12 new tests (test_packet_capture.py)

Protocol findings (doc/DEVICE_PROTOCOL.md §11.6-11.9, doc/research/DTO_RECOVERY_NOTES.md):
- NOTIFY_REQUEST (V1) required for subject-routed notifies (V2 drops to
 base topic where nothing listens)
- ECSP header: dest=omadacId and timestamp=epoch_ms required for notify
 dispatcher (unguarded dereference → error if absent)
- Transfer channel: simple pre-connect with token (no verify/negotiation)
- File transfer: controller REQUESTS (0x160000), device RESPONDS (0x170000)

All 97 tests pass.
```

## 2026-08-04 07:38:52+02:00

```
chore: clean internal references from tracked docs/code, sync docs with impl

- Move field-name notes to doc/research/DTO_RECOVERY_NOTES.md
 (gitignored) so tracked files are free of internal-analysis references.
- Clean code comments: remove internal-analysis references
 from olt.py, olt_profile.py, gateway.py, gateway_profile.py,
 switch.py, switch_profile.py, constants.py, discovery.py, device_monitor.py,
 rtty.py. Keep protocol facts (field names, wire formats, controller
 behavior) in comments.
- DEVICE_PROTOCOL.md: remove all internal-analysis references;
 add §7.8 gateway VPN/firewall/QoS/DDNS telemetry and switch
 LAG/DDM/STP sections; add §11 device-monitor/Network Check protocol
 reference (protobuf schema, ECSP framing, handshake, SET keys).
- STATUS.md: remove archive reference from Tools remaining-work item.
- README.md: add device_monitor.py/network_probe.py to Package Layout;
 update Scope to mention all four device types (incl. OLT) and the new
 switch LAG/SFP-DDM/STP and gateway VPN/firewall/QoS/DDNS telemetry.
- Fix stale PROVISIONAL docstring in olt.py (OLT is live-validated).

63 tests pass, dry-run OK, no lint errors.
```

## 2026-08-03 22:15:41+02:00

```
feat: implement gateway VPN/firewall/QoS/DDNS, switch LAG/DDM/STP, DMP protocol

Gateway (gateway.py):
- Add 9 new INFORM sections: vpn (IPsec/OpenVPN/PPTP-L2TP), sslVpn,
 wireguard, ddns, qos, ctTable, portforward, networkTraffic, ipsThreat
- Extend build_set_response to capture ~24 feature config keys
- Extend build_get_response to echo vpn/sslVpn/ddnsStats/sessionLimit
- 13 new tests in test_gateway_services.py

Switch (switch.py, switch_profile.py):
- Add 3 new INFORM sections: lag, ddm (nested SFP DDM objects), stpInform
- Extend build_set_response/build_get_response for lag/stp/portStp
- Add ddm/ddmInform/stpInform components to switch_profile.py
- 9 new tests in test_switch_l3_runtime.py

Tools DMP protocol (new files):
- protocol/device_monitor.py: hand-coded protobuf wire codec for
 the monitor message format with ECSP packet framing
- services/device_monitor.py: DeviceMonitorService TLS client (port 29817)
- services/network_probe.py: synthetic ping/traceroute responses

All field types verified by analyzing the controller and protobuf formats. Live-validated against
controller v6.2.14.11: all 3 devices reach CONNECTED with zero errors.
63 tests pass.
```

## 2026-08-03 19:41:22+02:00

```
docs: mark RTTY terminal path CONFIRMED live and document emulator client

- DEVICE_PROTOCOL.md §10: promote the terminal path from PROVISIONAL to
 CONFIRMED (verified live against controller 6.2.14.11). Fix the REGISTER
 payload (single trailing \0 => exactly 4 split segments) and the HEARTBEAT
 payload (4-byte uptime int, not empty). Add §10.9 documenting the emulator's
 RttyService/DummyShell client, capability wiring, and lab gotchas (29816 not
 host-published; proxy must tunnel WebSocket upgrades).
- STATUS.md: Tools -> Terminal now works (switch verified); Network Check and
 Packet Capture still pending.
- README.md: mention terminal support and the new rtty/rtty_shell modules.
```

## 2026-08-03 19:28:46+02:00

```
feat: add RTTY terminal client for Tools->Terminal

Implements the device side of the RTTY remote-terminal protocol so an
emulated device serves the controller's Tools -> Terminal feature end-to-end.

- protocol/rtty.py: RTTY wire protocol (V1/V2 frames, all 17 message types).
 REGISTER payload is version(1)+devid\0description\0token\0 (exactly 4 split
 segments; an extra \0 makes the controller drop the connection). HEARTBEAT
 carries a 4-byte uptime int (empty payload => BufferUnderflow on controller).
- services/rtty.py: RttyService client - TLS connect to controller:29816,
 REGISTER, reply LOGIN with sid+code0, relay TERMDATA to/from DummyShell,
 periodic HEARTBEAT, LOGOUT cleanup, reconnect loop.
- services/rtty_shell.py: DummyShell - line-buffered fake BusyBox shell
 (ls/cd/cat/echo/uname/ip/ps/... + prompt) driving the terminal session.
- devices advertise terminal support: devCap {supportTerminal, terminalSupport}
 on AP (eap.py) and switch/gateway (wired.py); adoption.build_negotiation_body
 gains dev_cap/device_misc params.
- manage.py detects terminalSetting in SET_REQUEST and fires on_terminal_setting;
 runner.py starts/stops RttyService per device based on the enable flag and the
 SSL.enable / token / port / heartbeatFrequency it carries.

Verified live against controller 6.2.14.11: switch adopts, controller pushes
the terminal setting, device REGISTERs, browser terminal shows the prompt and runs
commands.
```

## 2026-08-03 17:29:28+02:00

```
docs: document terminal/remote-access WebSocket+RTTY protocol (§10)

Documented from controller v6.2.14.11:

Browser ↔ controller: STOMP 1.2 over a WebSocket at /{omadacId}/ws/status.
Terminal keystrokes sent as STOMP SEND with a terminalCmd message; output
delivered as terminalConnectAck (15) / terminalCmdAck (16) / terminalDeviceClose
(17) events on /user/queue/ws/{omadacId}/sites/{siteId}/status. Session
open/close/reconnect via REST under .../terminal/session/*.

Controller ↔ device: custom RTTY binary protocol over TLS on port 29816
(the RTTY transport, the RTTY package). Two frame
variants (V1 3-byte hdr, V2 5-byte hdr). 17 message types identified
(REGISTER, LOGIN, LOGOUT, TERMDATA, HEARTBEAT, ACK, TCPDATA, HTTPSDATA,
SSHDATA, TELNETDATA, TUNNEL_ADD/DELETE, STANDALONE_AUTH, ...). Remote
Access reverse tunnels (HTTP/HTTPS/SSH/Telnet) reuse the RTTY transport.

Device receives the terminal setting config (enable/token/port/ssl/heartbeat/
spAesKey/spIv) via the management SET channel before connecting.

Browser-facing STOMP/REST framing marked CONFIRMED; device-side RTTY byte
layouts marked PROVISIONAL pending live capture of port 29816.
```

## 2026-08-03 17:12:23+02:00

```
feat(switch): implement Layer 3 / static routing support for TL-SG3210 v3

The TL-SG3210 v3 is a Layer-3 switch supporting static routing. The switch
profile already advertised the staticRouting/routingTable/loopback/vlanIf/
network/ipGroup components, but the INFORM body and SET/GET handling were
missing, so the controller's Tools -> Routing Table and Config -> Routing ->
Static Route features had no data.

- switch.py: add routingTable INFORM section (switch INFORM routing ->
 switch routing table with destIp/nextHop/distance) reporting the directly-
 connected network, a default route via the upstream gateway, and any
 operator-configured static routes; add loopback INFORM section
 (switch loopback status); capture staticRouting/loopbackInterface/vlanIf SET
 pushes in build_set_response and echo them in build_get_response.
- test_topology.py: add tests for the routing table, static routing
 SET/GET round-trip, and loopback interface SET + INFORM.
- STATUS.md / DEVICE_PROTOCOL.md: document the switch L3 / static routing
 support.

Validated end-to-end against controller v6.2.14.11: the switch reaches
CONNECTED, Tools -> Routing Table shows all route entries, and a static
route added via the controller UI round-trips through the device back into
the routing table.
```

## 2026-08-03 16:54:16+02:00

```
fix(olt): validate against controller v6.2 and fix wire formats

Validated the OLT device type end-to-end against a live controller
(v6.2.14.11, ECSP 1.8.6): discovery -> adoption -> CONNECTED (status 14)
with periodic INFORM heartbeats populating uptime/CPU/memory/traffic
telemetry. Corrected the wire formats based on the live controller
(the earlier analysis had two
key details wrong):

Discovery (OLT discovery v2 body):
- Uses the switch/gateway controller/id convention, NOT the AP-style
 controllerSetting/controllerId. The OLT discovery controller setting v2 maps its
 controllerId field with JSON key "id" and the body wrapper maps
 controllerSetting with JSON key "controller".
- deviceMisc is the base device-misc (modelType/category/supportCluster), not
 ponPortCount/lagCount (those live in the adopt deviceInfo).
- upTime is a JSON integer (Long), not a string.

Negotiation (DEVICE_NEGOTIATION -> OLT adopt response v2 body):
- The body is parsed directly as the OLT adopt response v2 body, NOT the generic
 components_v2/devCap/deviceMisc envelope. It carries components
 (map of string to string: OLT component -> "ver.funcVer"), deviceInfo
 (OLT adopt device info v2) and isFactoryDefault.
- components must be non-null (controller errors on null) and include
 centralManagement (else adopt flags incompatible). The component keys/
 versions come from the controller's own OLT component enum.

INFORM (OLT INFORM body -> OLT INFORM device info):
- deviceInfo is the OLT INFORM device info (name/upTime/ip/cpuUti/memUti/down/up/
 onuCount/portOnuCount), NOT the adopt OLT adopt device info v2. onuCount must
 be non-null or the controller errors in the monitor handler.
- Added Device.manage_inform_body() so the OLT can override the full INFORM
 body format (manage.py now calls it instead of building deviceInfo+extra).

Compatibility:
- The controller's model whitelist
 accepts only DS-P7001-01/04/08/16, DS-MCUA, DS-P8000-X2. The default model
 is now DS-P7001-08 (the earlier TL-OLT2008 was flagged compatible:10 and
 rejected with errorCode -39060).

Docs updated to CONFIRMED throughout (DEVICE_PROTOCOL.md §4.4/§7.9/§9.1,
STATUS.md, README.md).
```

## 2026-08-02 22:04:44+02:00

```
feat(olt): add OLT (PON optical line terminal) device type

Implement the fourth emulated device type alongside AP, switch, and
gateway. The OLT is a V2 wired device (ECSP 2.2.0) that reuses the AP-style
long-name deviceInfo field set plus PON-specific identity fields
(hwId/oemId/lagCount/ponPortCount/wirelessLinked). Discovery uses the
AP-style controllerSetting.controllerId nesting; the INFORM body reports
per-PON-port trafficStat (port stat with multicast/broadcast counters).

The wire formats are derived from the controller formats
and are PROVISIONAL
(not yet live-validated against a controller).

- protocol/constants.py: DEVICE_TYPE_OLT = "olt"
- protocol/discovery.py: build_olt_discovery_body()
- devices/olt_profile.py + devices/olt.py: OltDevice + profile
- devices/registry.py: wire OLT into the type map
- tests for the OLT discovery/negotiation/inform formats
- doc/DEVICE_PROTOCOL.md: new §4.4 (OLT discovery), §7.9 (OLT adoption &
 INFORM), §9.1 checklist; updated §3.1 type table and §8 constants
- config.example.yaml, README.md, STATUS.md: OLT device and status notes
```

## 2026-08-02 20:29:27+02:00

```
feat: report client, traffic, radio, DHCP and health telemetry in INFORM

Enrich each device type's management-channel INFORM so the controller's
Clients page and per-device detail tabs populate:

- Access point: report ip/txRate/rxRate and a formatted upTime in deviceInfo,
 wireless clients (the `clients` section), and per-radio wSettings/radioTraffic/ssidStats.
 Fixes the AP HEARTBEAT MISSED (WirelessInfo string formats), blank uptime/IP,
 and device-health scoring.
- Switch: report wired clients, per-port byte/packet counters, PoE budget, a
 non-zero CPU, and the fixed LLDP-table/1/0/N port identifiers.
- Gateway: report LAN clients, DHCP leases, WAN/per-port traffic, WAN latency
 and the ARP table.

Add synthetic-but-deterministic client/counter helpers (stats.py,
devices/clients.py) wired in by the runner. Document the new INFORM sections and
field formats in DEVICE_PROTOCOL.md 7.8, add STATUS.md, and update tests.
```

## 2026-08-02 16:03:30+02:00

```
refactor: remove unused gateway_port_section

The gateway INFORM portInfo section is now built by GatewayDevice._port_info_section (commit 6811392), leaving topology.gateway_port_section with no callers. Drop the dead function.
```

## 2026-07-31 22:06:58+02:00

```
feat(gateway): populate detail-page tabs and ack config pushes

The controller's device detail page (Overview, Ports -> WAN, topology) renders
from device data stored in the controller's DB, which is populated from the
device's periodic INFORM body. The emulator previously sent only deviceInfo
plus a minimal topology portInfo/lldp in INFORM and acked the controller's
config pushes (SET_REQUEST) with an empty body, so:

- the controller treated config sync as FAILED and forgot the device right
 after the first INFORM (immediate management-channel close, ADOPT FAILED);
- the detail-page tabs showed no data (--).

Fixes (grounded in the controller formats):

* Device.build_set_response() now echoes the request sequenceId + configVersion
 with errcode 0, so the controller records the config as applied and keeps
 the device CONNECTED. Device.build_get_response() defaults to an empty ack.
* GatewayDevice.manage_inform_extra() now reports a full portInfo (all 5 ports,
 WAN port with ip/netmask + nested ip4 port entry for gw/priDns/sndDns),
 a routingTable, and lldp. internetState/internetV6 are set on every port
 (the controller's port-inform decoder unboxes them without a null check).
* topology.gateway_port_section uses the field name portInfos (+ duplex).
* GatewayDevice.build_set/get_response remember/echo the controller-pushed
 wanIpv4/wanMac for live GET queries.
* manage.py dispatches SET/GET to the device methods.

Verified end-to-end against controller v6.2: all three devices reach and stay
CONNECTED (3/3 adopt success); the ER605 detail page Overview tab shows Model,
MAC, Controller Connection IP, LAN IP, Firmware, Uptime, and the downlink
switch; the Ports -> WAN tab shows MAC, IP Address, Gateway, and DNS Server.

Doc DEVICE_PROTOCOL.md §7 updated: SET_RESPONSE must echo configVersion (not
empty), and a new §7.7 documents the INFORM body formats (gateway INFORM
body / port status / port IPv4 entry / INFORM routing) that populate the
detail-page tabs. README scope updated.

Tests: 31 pass (test_topology updated for the new gateway INFORM sections).
```

## 2026-07-07 21:33:09+02:00

```
feat: report wired topology so devices link in the topology map

The controller draws its topology map (gateway -> switch -> AP) from LLDP,
port-status and MAC-forwarding data the devices report per INFORM component;
without it adopted devices float unconnected. Report that data, driven by an
'uplink' relationship declared in the config.

- devices/topology.py: TopologyNeighbors model + builders for the switch
 'port'/'lldp'/'fdb', gateway 'portInfo'/'lldp' and AP 'lanInfo' INFORM
 sections
- devices/base: per-device uplink/uplink_port/local_uplink_port config +
 resolved 'topology' neighbours; manage_inform_extra() hook merged into the
 INFORM body (services/manage)
- eap/switch/gateway: emit their topology INFORM sections from the neighbours
- services/runner: _resolve_topology() turns each device's declared uplink
 into bidirectional neighbour links
- registry/config.example: 'uplink' + 'uplink_port' per device
- docs + tests (test_topology.py)

Validated live on controller v6.2.10.17: an emulated gateway (ER605),
switch (TL-SG3210) and AP (EAP245) appear correctly linked
gateway -> switch -> AP in the topology map, from the YAML uplink wiring.
```

## 2026-07-07 19:38:44+02:00

```
refactor: shared WiredDevice base and consistent profiles

Now that all three device types are understood, tidy the device model:

- devices/wired.py: new WiredDevice base that captures the shared switch/
 gateway management-channel logic (protocol version 2.2, short-name
 deviceInfo built from a profile template, and the devCap/deviceMisc
 negotiation body). SwitchDevice/GatewayDevice shrink to their per-type
 bits (discovery body, extra deviceInfo fields, destOmadacId flag).
- Consistent per-type negotiation profiles: rename eap_components.py ->
 eap_profile.py and give all three profiles PROTOCOL_VERSION + COMPONENTS_V2
 (wired ones also DEV_CAP/DEVICE_MISC/DEVICE_INFO_TEMPLATE). Devices source
 their protocol version from the profile.
- base.Device.manage_device_info() is now an explicit abstract contract;
 clarified the management-channel docstrings (AP 'wireless' default vs the
 wired override).
- Docs/comments tightened; README package layout and internal notes updated.

Behavior-preserving: negotiation bodies are byte-equivalent per type; 25
tests pass and all three types (EAP245/TL-SG3210/ER605) still adopt to
Connected + compatible=0 on controller v6.2.
```

## 2026-07-07 19:26:27+02:00

```
feat: support switch and gateway adoption

Extend full adoption to all three device types. Previously only access points
completed the management-channel handshake; switches and gateways stalled at
negotiation because they need per-type protocol version, deviceInfo format,
capability descriptor and component manifest.

- devices/base: per-device protocol_version field (threaded into discovery and
 management headers) and build_manage_negotiation_body(); format_uptime helper
- devices/switch_profile.py, devices/gateway_profile.py: component manifest,
 devCap and static device-info fields (generated from the controller's model
 templates for TL-SG3210 v3.0 and ER605 v1.0)
- devices/switch, devices/gateway: protocol_version 2.2.0, short-name
 deviceInfo, per-type components_v2 + devCap + deviceMisc negotiation body
 (switch adds controllerSetting.destOmadacId)
- services/manage: send the device's own negotiation body / protocol version
- docs + tests

Validated live on controller v6.2.10.17: an emulated AP (EAP245), switch
(TL-SG3210) and gateway (ER605) all reach status 14 (Connected) with
compatible=0 (no warning icon).
```

## 2026-07-07 19:07:50+02:00

```
fix: report device as compatible to clear incompatibility warning

An adopted access point showed a red warning icon in the controller UI:
"The device is not compatible with the current controller." The controller's
compatibility check returns "not compatible" (grid field
compatible=7) when the device's negotiation reports an empty component set,
and separately classifies the advertised ECSP protocol version.

- constants: advertise protocol version 2.3.0 (matches the EAP V2 "fit"
 version both v5.15 and v6.2 expect; avoids the LOW_MINOR_VER classification)
- devices/eap_components.py: the access-point component manifest
 ({component: version}) a real EAP245 v3.0 reports
- devices: manage_components_v2() (non-empty for APs, empty otherwise)
- protocol/adoption + services/manage: send components_v2 in DEVICE_NEGOTIATION
- docs + tests

Validated end-to-end: the emulated AP is now reported as compatible
(compatible=0, no warning icon) and Connected on BOTH controller v5.15.24.19
and v6.2.10.17.
```

## 2026-07-07 18:27:03+02:00

```
fix: support controller v6.2 (ECSP 1.7.3) with 36-char verify nonce

Newer controllers (ECSP 1.7.x, e.g. the lab controller image =
v6.2.10.17) reject a randomKeyForSystemVerify shorter than 36 characters
with INVALID_DEVICE_RANDOMKEY, before checking the auth - so the previous
32-char uuid4().hex surfaced as adopt error -39002/-39003 'username or
password is incorrect'. Send a full 36-char hyphenated UUID instead, which
is accepted by both v5.15 and v6.2.

- protocol/adoption.py: add new_verify_nonce() (36-char UUID) with rationale
- services/manage.py: use it for randomKeyForSystemVerify
- docs: note the 36-char requirement, cipherCap advertisement, and that the
 discovery + full adoption handshake is validated against v5.15 AND v6.2
- test: assert the verify nonce is a 36-char UUID

Validated end-to-end: emulated AP reaches status 14 (Connected) on both
controller v5.15.24.19 and v6.2.10.17.
```

## 2026-07-07 17:49:02+02:00

```
feat: implement full device adoption over the TLS management channel

Port the confirmed adoption handshake into the package so the emulator can
drive a device from discovery all the way to the controller's Connected
(online) state, not just make it appear adoptable.

- protocol/auth.py: uppercase-hex SHA256/MD5 device auth calculation
- protocol/adoption.py: pre-connect / verify / negotiation / inform bodies
- services/manage.py: TLS management-channel client running the full
 pre-connect -> verify (mutual) -> negotiate -> init-sync -> inform loop
- services/discovery.py: keep a persistent socket to catch the controller's
 pre-adopt UDP reply and hand off to the management client
- services/runner.py + daemon: adopt: config block (enabled/username/
 password/port/inform_interval); adoptable devices announce with the
 factory sentinel controller id and negotiate with the real one
- devices: manage_device_info() for negotiation/inform payloads
- docs/config: document the now-confirmed adoption sequence; add tests

Validated end-to-end against a live controller: an emulated AP reaches
status 14 (Connected) and stays online via the INFORM heartbeat.
```

## 2026-07-06 12:32:54+02:00

```
chore: initial commit
```

