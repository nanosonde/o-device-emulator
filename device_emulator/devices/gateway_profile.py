"""Backward-compatibility shim — re-exports from ``gateway_profiles.er605``.

Existing code that does ``from . import gateway_profile`` or
``from device_emulator.devices import gateway_profile`` continues to work.
New code should use ``device_emulator.devices.gateway_profiles`` directly.
"""
from __future__ import annotations

from .gateway_profiles.er605 import *  # noqa: F401,F403