"""YAML-driven daemon entry point for o-device-emulator.

Usage:
    python device_emulator_daemon.py --config config.yaml [--dry-run]

See config.example.yaml for the configuration schema.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from typing import Any

import yaml

from device_emulator.devices.registry import build_device
from device_emulator.services.runner import Runner
from device_emulator.state import apply_device_state, collect_device_state, load_state, save_state

logger = logging.getLogger("device_emulator_daemon")


def load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_runner(config: dict[str, Any]) -> Runner:
    controller_url = config.get("controller_url")
    if not controller_url:
        raise ValueError("config must set 'controller_url' (e.g. https://192.168.56.1:8043)")

    from urllib.parse import urlparse

    parsed = urlparse(controller_url)
    host = parsed.hostname
    https_port = parsed.port or 8043
    if not host:
        raise ValueError(f"could not parse host from controller_url: {controller_url!r}")

    services_cfg = config.get("services", {}) or {}
    adopt_cfg = config.get("adopt", {}) or {}
    runner = Runner(
        controller_host=host,
        https_port=https_port,
        discovery_port=services_cfg.get("discovery_port", 29810),
        discovery_interval=services_cfg.get("discovery_interval", 10.0),
        discovery_bind_ip=services_cfg.get("discovery_bind_ip"),
        discovery_broadcast=services_cfg.get("discovery_broadcast", False),
        adopt_enabled=adopt_cfg.get("enabled", False),
        adopt_username=adopt_cfg.get("username", "admin"),
        adopt_password=adopt_cfg.get("password", "admin"),
        adopt_port=adopt_cfg.get("port", 29814),
        inform_interval=adopt_cfg.get("inform_interval", 10.0),
    )

    devices_cfg = config.get("devices", []) or []
    if not devices_cfg:
        raise ValueError("config must declare at least one device under 'devices:'")
    for device_cfg in devices_cfg:
        runner.add_device(build_device(device_cfg))

    return runner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to a YAML config file")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve devices and validate discovery messages, then exit",
    )
    parser.add_argument(
        "--log-level", default="INFO", help="Logging level (default: INFO)"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    config = load_config(args.config)
    runner = build_runner(config)

    if args.dry_run:
        try:
            summaries = runner.dry_run()
        except Exception as exc:  # noqa: BLE001
            logger.error("dry-run failed: %s", exc)
            return 1
        for summary in summaries:
            print(summary)
        print(f"dry-run OK: {len(summaries)} device(s) resolved")
        return 0

    state_file = config.get("state_file")
    persist = config.get("persist", False)
    state = load_state(state_file) if persist and state_file else {}
    for device in runner.devices:
        if state:
            apply_device_state(device, state)

    stop_event = threading.Event()

    def _handle_signal(signum: int, _frame: Any) -> None:
        logger.info("received signal %s, shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    runner.start()
    logger.info("daemon started with %d device(s)", len(runner.devices))
    try:
        while not stop_event.is_set():
            stop_event.wait(5.0)
            if persist and state_file:
                state = collect_device_state(runner.devices, state)
                save_state(state_file, state)
    finally:
        runner.stop()
        if persist and state_file:
            state = collect_device_state(runner.devices, state)
            save_state(state_file, state)

    return 0


if __name__ == "__main__":
    sys.exit(main())
