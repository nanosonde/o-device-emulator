"""Unit tests for state persistence."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.devices.registry import build_device
from device_emulator.state import apply_device_state, collect_device_state, load_state, save_state


def test_state_round_trip(tmp_path):
    state_file = tmp_path / "state.json"
    device = build_device(
        {"name": "lab-eap-01", "type": "ap", "mac": "02:15:6d:00:00:20", "ip": "192.168.56.53"}
    )
    device.uptime_start = 12345.0

    state = collect_device_state([device], {})
    save_state(str(state_file), state)

    reloaded = load_state(str(state_file))
    assert reloaded[device.mac]["uptime_start"] == 12345.0

    device2 = build_device(
        {"name": "lab-eap-01", "type": "ap", "mac": "02:15:6d:00:00:20", "ip": "192.168.56.53"}
    )
    apply_device_state(device2, reloaded)
    assert device2.uptime_start == 12345.0


def test_load_state_missing_file_returns_empty(tmp_path):
    assert load_state(str(tmp_path / "does-not-exist.json")) == {}
