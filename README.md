# o-device-emulator

A Python library and YAML-driven daemon focused exclusively on emulating
TP-L\*nk Om\*d\* devices in lab environments for security investigations and
deeper technical understanding.

The project can emulate access point, switch, and gateway/router profiles and
emit the UDP discovery traffic that makes an emulated device appear in a real
network controller so it can be selected for adoption. With adoption enabled,
it also completes the full management-channel handshake and keeps the device
reported as **Connected** (online) with periodic heartbeats.

## Quick Start

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp config.example.yaml config.yaml
.venv/bin/python device_emulator_daemon.py --config config.yaml --dry-run
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
  body builders, management-channel handshake bodies, and the device auth
  calculation.
- `device_emulator/devices/`: base, access point, switch, gateway, registry.
- `device_emulator/services/`: discovery announce, TLS management client,
  controller info client, runner.
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

## Scope

Discovery (the UDP announce that makes a device appear as adoptable in the
controller) is implemented and validated end-to-end for all three device
types. Adoption over the TLS management channel (port 29814) — pre-connect,
mutual device verification, capability negotiation, initial sync, and the
steady-state inform/heartbeat loop that holds the device **Connected** — is
implemented and validated end-to-end for access points; enable it via the
`adopt:` block in the config. Switch/gateway discovery works, but their
management-channel details are not separately confirmed. The discovery and
adoption flows are validated against both controller v5.15 and v6.2. See
[doc/DEVICE_PROTOCOL.md](doc/DEVICE_PROTOCOL.md) for the full protocol
reference.

## Validation

- Importing the package succeeds.
- Daemon `--dry-run` resolves all configured devices.
- CLI simulation starts with expected defaults.
- State file write/read works with the configured path.

## Intended Use

Use only in controlled lab or test environments where you have explicit
authorization.
