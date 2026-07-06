#!/usr/bin/env python3
"""Flag-driven simulation harness for ad-hoc testing.

Sends one or more discovery announces for a single synthetic device without
needing a YAML config - useful for quickly probing a controller by hand.
See doc/DEVICE_PROTOCOL.md for the packet format it produces.

Example:
    python test/sim_cli.py --controller 192.168.56.1 --type ap \\
        --mac 02:15:6D:00:02:01 --ip 192.168.56.90 --count 3
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.devices.base import DeviceIdentity
from device_emulator.devices.eap import EapDevice
from device_emulator.devices.gateway import GatewayDevice
from device_emulator.devices.switch import SwitchDevice
from device_emulator.services.controller_client import fetch_controller_id
from device_emulator.services.discovery import DiscoveryService, DiscoveryServiceConfig

_DEVICE_CLASSES = {"ap": EapDevice, "switch": SwitchDevice, "gateway": GatewayDevice}
_DEFAULT_MODELS = {"ap": "EAP245", "switch": "TL-SG3210", "gateway": "ER605"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller", required=True, help="Controller host/IP")
    parser.add_argument("--https-port", type=int, default=8043)
    parser.add_argument("--discovery-port", type=int, default=29810)
    parser.add_argument("--type", choices=_DEVICE_CLASSES.keys(), default="ap")
    parser.add_argument("--mac", required=True)
    parser.add_argument("--ip", required=True, help="Device's own (non-loopback) IP")
    parser.add_argument("--model")
    parser.add_argument("--name", default="sim-device")
    parser.add_argument("--count", type=int, default=1, help="Number of announces to send")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args(argv)

    device_cls = _DEVICE_CLASSES[args.type]
    identity = DeviceIdentity(
        name=args.name,
        mac=args.mac,
        model=args.model or _DEFAULT_MODELS[args.type],
    )
    device = device_cls(identity=identity, ip=args.ip)

    print(f"fetching controller id from https://{args.controller}:{args.https_port}/api/info ...")
    device.controller_id = fetch_controller_id(args.controller, https_port=args.https_port)
    print(f"controller_id={device.controller_id}")

    config = DiscoveryServiceConfig(
        controller_host=args.controller,
        port=args.discovery_port,
    )
    service = DiscoveryService(device, config)

    for i in range(args.count):
        service.announce_once()
        print(f"[{i + 1}/{args.count}] sent discovery announce for {device.mac} ({device.device_type})")
        if i + 1 < args.count:
            time.sleep(args.interval)

    return 0


if __name__ == "__main__":
    sys.exit(main())
