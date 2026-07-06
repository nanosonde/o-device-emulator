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


def synthetic_int(mac: str, salt: str, low: int, high: int) -> int:
    """Deterministic pseudo-random integer in [low, high] for a MAC + metric."""
    seed = _seed_from_mac(mac + salt)
    return low + (seed % max(1, (high - low)))


def synthetic_rate_bps(mac: str, salt: str, low_mbps: int = 1, high_mbps: int = 200) -> int:
    """A deterministic, plausible instantaneous link rate in bits/sec, derived
    from the MAC + metric name. Used for the Overview Upload/Download rate and
    per-interface tx/rx rate fields."""
    mbps = synthetic_int(mac, salt, low_mbps, high_mbps)
    return mbps * 1_000_000


def synthetic_bytes(mac: str, salt: str, uptime_seconds: int, avg_bps: int) -> int:
    """A monotonic byte counter: roughly ``avg_bps`` sustained over the device
    uptime (so it only ever grows), with a small deterministic offset so the
    number does not look perfectly round."""
    base = (max(0, avg_bps) // 8) * max(0, uptime_seconds)
    offset = _seed_from_mac(mac + salt) % 100_000
    return base + offset


def synthetic_packets(byte_count: int, avg_frame: int = 800) -> int:
    """Approximate a packet count from a byte count using an average frame
    size (so tx/rx packet counters stay consistent with the byte counters)."""
    return max(0, byte_count) // max(1, avg_frame)


# A locally-administered OUI used for synthesised client MACs so they never
# collide with the emulated infrastructure devices' MACs.
_CLIENT_OUI = "AC-DE-48"


def synthetic_client_mac(seed: str, index: int) -> str:
    """Derive a stable client MAC (locally-administered OUI + a 3-byte suffix
    hashed from ``seed`` and ``index``) so the same device always reports the
    same clients across restarts."""
    digest = hashlib.sha256(f"{seed}:{index}".encode("utf-8")).digest()
    suffix = "-".join(f"{b:02X}" for b in digest[:3])
    return f"{_CLIENT_OUI}-{suffix}"


# A locally-administered OUI distinct from _CLIENT_OUI, used for synthesised
# per-SSID BSSIDs so they never collide with client or AP MACs.
_BSSID_OUI = "02-1B-2F"


def synthetic_bssid(ap_mac: str, radio_id: int, profile_key: str) -> str:
    """Derive a stable BSSID for one AP radio + SSID profile (keyed on AP MAC,
    radio id, and a stable per-profile identity string), so the same profile
    keeps the same BSSID across restarts and unrelated profile reordering."""
    digest = hashlib.sha256(f"{ap_mac}:{radio_id}:{profile_key}".encode("utf-8")).digest()
    suffix = "-".join(f"{b:02X}" for b in digest[:3])
    return f"{_BSSID_OUI}-{suffix}"
