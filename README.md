# o-device-emulator

A Python library and YAML-driven daemon focused exclusively on emulating
TP-L\*nk Om\*d\* devices in lab environments for security investigations and
deeper technical understanding.

The project can emulate access point, switch, gateway/router, and OLT
(PON optical line terminal) profiles and emit the UDP discovery traffic that
makes an emulated device appear in a real network controller so it can be
selected for adoption. With adoption enabled, it also completes the full
management-channel handshake and keeps the device reported as **Connected**
(online) with periodic heartbeats, and can report a wired **topology** (declare
each device's `uplink`) so the devices appear connected in the controller's
topology map. It also serves the controller's **Tools** tab: **Terminal**
(an RTTY client backed by a dummy shell, §10.9), **Network Check** (synthetic
ping/traceroute via the device-monitor channel, §11), and **Packet Capture**
(valid libpcap generation + file-transfer channel, §11.6). The AP, switch,
gateway, and OLT types are all validated end-to-end against a live controller.

## Quick Start

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp config.example.yaml config.yaml
.venv/bin/python device_emulator_daemon.py --config config.yaml --dry-run
```

## Controller Quick Start (Just)

Install [just](https://github.com/casey/just) and Docker with the Compose
plugin. From the repository root, start a local controller and its HTTP
proxy:

```bash
just controller-start
just proxy-start
```

The proxy listens at `http://127.0.0.1:8090`. Use `just proxy-status` to
confirm it is running and inspect its recent log output. The available recipes
and their descriptions are listed by `just` (or `just help`).

When finished, stop the local services while preserving controller data:

```bash
just proxy-stop
just controller-stop
```

## Main Components

- `device_emulator_daemon.py`: YAML-driven daemon entry point (primary interface).
- `device_emulator/`: reusable package (protocol, devices, services, state, stats).
- `config.example.yaml`: annotated local example configuration.
- `test/config.test.yaml`: local test-oriented configuration.
- `test/sim_cli.py`: flag-driven simulation harness for ad-hoc testing.
- `test/`: home for all test-only configs, notes, and scripts.

## Package Layout

- `device_emulator/protocol/`: packet framing, message envelope, discovery
  body builders, management-channel handshake bodies, the device auth
  calculation, the RTTY terminal wire protocol (`rtty.py`), the device-monitor
  protobuf wire codec (`device_monitor.py`), and the libpcap file generator
  (`pcap.py`).
- `device_emulator/devices/`: device model (`base` + `wired` bases; `eap`,
  `switch`, `gateway`, `olt` types; `registry`; `topology` reporting), plus
  per-type negotiation profiles (`eap_profile`, `switch_profile`,
  `gateway_profile`, `olt_profile`).
- `device_emulator/services/`: discovery announce, TLS management client,
  controller info client, runner, the RTTY terminal client (`rtty.py`)
  with its dummy shell (`rtty_shell.py`), the device-monitor client
  (`device_monitor.py`) with its synthetic probe responder
  (`network_probe.py`), the packet-capture service (`packet_capture.py`),
  and the file-transfer channel client (`transfer_channel.py`).
- `device_emulator/state.py`: persistence helpers.
- `device_emulator/stats.py`: counters and synthetic runtime stats.

The daemon builds device objects from YAML, starts the service loops from a
shared runner, and persists state snapshots when configured.

## Data Directory Policy

- `data/` is runtime output.
- Generated state files are intentionally ignored.
- Keep only placeholder files in versioned content.

## Documentation

- [doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md): protocol and payload
  reference for this implementation.
- [STATUS.md](STATUS.md): current project status and the backlog of
  controller-visible features each device type still lacks (per-type gaps
  identified by walking the controller UI against the live emulator).

## Scope

Discovery (the UDP announce that makes a device appear as adoptable in the
controller) is implemented and validated end-to-end for all four device
types. Adoption over the TLS management channel (port 29814) — pre-connect,
mutual device verification, capability negotiation, initial sync, and the
steady-state inform/heartbeat loop that holds the device **Connected** — is
implemented and validated end-to-end for **access points, switches,
gateways, and OLTs** (each reported as compatible, no warning). Enable it
via the `adopt:` block in the config. The discovery and adoption flows are
validated against both controller v5.15 and v6.2.

Controller **Force Provision** is also supported: after the controller closes
the management channel, the emulator automatically reconnects in rebuild mode
and accepts the full configuration again. The emulator learns the site's
Device Account from the controller's initial `userAccount` sync; optional
`adopt.managed_username` / `adopt.managed_password` values are available as
fallbacks for controllers that do not send it.

The steady-state device also **acks the controller's config pushes**
(`SET_REQUEST`) by echoing the pushed `configVersion`, so the controller
records the config as applied and keeps the device `CONNECTED` (an empty ack
makes the controller forget the device). Each device type also reports rich
per-device telemetry in its periodic INFORM so the controller's detail pages
and the site **Clients** page populate: connected clients (AP wireless
stations, switch wired clients, gateway LAN clients / DHCP leases), per-port
and WAN traffic counters/rates, AP radio settings/traffic, switch PoE / LAG /
SFP-DDM / STP, and gateway ARP / WAN latency / VPN / firewall / QoS / DDNS.
Values are synthetic-but-deterministic (MAC-seeded, uptime-scaled).

The emulator also serves the controller's **Tools** tab:

- **Terminal** — RTTY client (port 29816) backed by a dummy BusyBox-style
  shell (§10.9).
- **Network Check** — device-monitor (DMP) client (port 29817) serving
  synthetic ping/traceroute probe responses (§11).
- **Packet Capture** — builds a valid libpcap capture, announces it via
  NOTIFY, and serves file-transfer requests over a transfer channel
  (port 29815) so the controller can download the `.pcap` file (§11.6).

See [doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md) §7 for the full protocol
reference and [STATUS.md](STATUS.md) for what is and isn't implemented.

## Validation

- Importing the package succeeds.
- Daemon `--dry-run` resolves all configured devices.
- CLI simulation starts with expected defaults.
- State file write/read works with the configured path.

## Intended Use

Use only in controlled lab or test environments where you have explicit
authorization.
