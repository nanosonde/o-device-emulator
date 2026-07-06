"""Tests for YAML daemon configuration routing."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator_daemon import build_runner


def test_build_runner_uses_local_controller_url_host_and_port():
    runner = build_runner(
        {
            "controller_url": "https://127.0.0.1:8043",
            "devices": [
                {
                    "name": "local-ap",
                    "type": "ap",
                    "mac": "02:15:6d:00:01:01",
                    "ip": "192.168.56.101",
                }
            ],
        }
    )

    assert runner.controller_host == "127.0.0.1"
    assert runner.https_port == 8043


def test_build_runner_routes_separate_managed_device_credentials():
    runner = build_runner(
        {
            "controller_url": "https://127.0.0.1:8043",
            "adopt": {
                "username": "adopt-user",
                "password": "adopt-password",
                "managed_username": "managed-user",
                "managed_password": "managed-password",
            },
            "devices": [
                {
                    "name": "local-ap",
                    "type": "ap",
                    "mac": "02:15:6d:00:01:01",
                    "ip": "192.168.56.101",
                }
            ],
        }
    )

    assert runner.adopt_username == "adopt-user"
    assert runner.adopt_password == "adopt-password"
    assert runner.managed_username == "managed-user"
    assert runner.managed_password == "managed-password"