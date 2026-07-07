"""Authentication helper for the management-channel handshake.

During adoption the device and controller mutually authenticate over the TLS
management channel (see doc/DEVICE_PROTOCOL.md §8). The device proves it knows
the management credential by returning:

    auth = SHA256( SHA256(username + MD5(password)) + randomKey )

CONFIRMED byte-for-byte against a live controller. The critical subtlety is
that every intermediate hash is rendered as an **UPPERCASE** hex string before
being fed into the next hash - the controller's own implementation uppercases
its hex, and because the intermediate digests are hash *inputs*, the casing
changes the final result. Lower-casing any step makes authentication fail.
"""
from __future__ import annotations

import hashlib


def md5_upper(value: str) -> str:
    """MD5 of `value`, hex-encoded in UPPERCASE (matches the controller)."""
    return hashlib.md5(value.encode("utf-8")).hexdigest().upper()


def sha256_upper(value: str) -> str:
    """SHA-256 of `value`, hex-encoded in UPPERCASE (matches the controller)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


def calculate_device_auth(username: str, password: str, random_key: str) -> str:
    """Compute the device authentication token for the verify exchange.

    `random_key` is the controller-supplied nonce
    (body.randomKeyForDeviceVerify from the pre-connect response).
    """
    inner = sha256_upper(username + md5_upper(password))
    return sha256_upper(inner + random_key)
