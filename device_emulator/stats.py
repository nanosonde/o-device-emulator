"""Synthetic, per-device-deterministic runtime statistics.

Real devices report jittery-but-stable CPU/memory/traffic counters. This
module derives small, deterministic variations from a device's MAC so
repeated runs look plausible without needing real traffic - kept minimal
since only discovery (which carries cpuUti/memUti for APs) is a confirmed
part of the wire protocol so far.
"""
from __future__ import annotations

import hashlib


def _seed_from_mac(mac: str) -> int:
    digest = hashlib.sha256(mac.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def synthetic_percent(mac: str, salt: str, low: int = 2, high: int = 40) -> int:
    """Deterministic pseudo-random percentage in [low, high] for a given MAC
    and named metric (e.g. "cpu", "mem")."""
    seed = _seed_from_mac(mac + salt)
    return low + (seed % max(1, (high - low)))
