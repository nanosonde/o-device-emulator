"""Persistence helpers: keep per-device state (currently: uptime_start) across
daemon restarts, keyed by MAC address, written atomically to a JSON file."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any

logger = logging.getLogger(__name__)


def load_state(path: str) -> dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("failed to load state file %s: %s (starting fresh)", path, exc)
        return {}


def save_state(path: str, state: dict[str, Any]) -> None:
    if not path:
        return
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def apply_device_state(device: Any, state: dict[str, Any]) -> None:
    """Restore a device's persisted uptime_start, if present."""
    entry = state.get(device.mac)
    if entry and "uptime_start" in entry:
        device.uptime_start = entry["uptime_start"]


def collect_device_state(devices: list[Any], existing: dict[str, Any]) -> dict[str, Any]:
    """Merge current device identity/uptime into the persisted state dict."""
    state = dict(existing)
    for device in devices:
        state[device.mac] = device.to_state_dict()
    return state
