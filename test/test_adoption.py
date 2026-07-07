"""Unit tests for the management-channel (adoption) protocol helpers: the
auth calculation and the handshake body builders. These are pure functions,
so they run without a live controller (see doc/DEVICE_PROTOCOL.md §8 for the
live-verified sequence)."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.protocol import adoption
from device_emulator.protocol.auth import calculate_device_auth, md5_upper, sha256_upper


def test_hash_helpers_are_uppercase():
    # The controller renders every intermediate hash in UPPERCASE hex; since
    # those digests feed into the next hash, casing changes the result.
    assert md5_upper("admin") == hashlib.md5(b"admin").hexdigest().upper()
    assert sha256_upper("x") == hashlib.sha256(b"x").hexdigest().upper()
    assert md5_upper("admin").isupper()
    assert sha256_upper("x").isupper()


def test_calculate_device_auth_matches_reference_formula():
    username, password, random_key = "admin", "admin", "deadbeef"
    inner = hashlib.sha256(
        (username + hashlib.md5(password.encode()).hexdigest().upper()).encode()
    ).hexdigest().upper()
    expected = hashlib.sha256((inner + random_key).encode()).hexdigest().upper()
    assert calculate_device_auth(username, password, random_key) == expected


def test_calculate_device_auth_is_case_sensitive_on_intermediate():
    # A lower-cased intermediate would yield a different (wrong) token.
    username, password, random_key = "admin", "admin", "abc"
    wrong_inner = hashlib.sha256(
        (username + hashlib.md5(password.encode()).hexdigest().lower()).encode()
    ).hexdigest().lower()
    wrong = hashlib.sha256((wrong_inner + random_key).encode()).hexdigest().upper()
    assert calculate_device_auth(username, password, random_key) != wrong


def test_pre_connect_body():
    body = adoption.build_pre_connect_body()
    assert body["needUsername"] is True
    assert body["rebuild"] == 0


def test_verify_nonce_is_36_char_uuid():
    # Newer controllers (ECSP 1.7.x / controller v6.2) reject a
    # randomKeyForSystemVerify shorter than 36 chars; a hyphenated UUID is 36.
    nonce = adoption.new_verify_nonce()
    assert len(nonce) == 36
    assert nonce.count("-") == 4
    # A fresh value each call.
    assert nonce != adoption.new_verify_nonce()


def test_device_verify_body():
    body = adoption.build_device_verify_body("AUTHTOKEN", "nonce123")
    assert body == {"auth": "AUTHTOKEN", "randomKeyForSystemVerify": "nonce123"}


def test_negotiation_body_shape():
    info = {"name": "fake", "model": "EAP245"}
    body = adoption.build_negotiation_body(info, "ctrl-id-abc", country_code=3)
    assert body["deviceInfo"] is info
    assert body["controllerSetting"]["controllerId"] == "ctrl-id-abc"
    assert body["configVersion"] == "0"
    assert body["deviceMisc"]["customizeRegion"] == 3
    # Empty capability placeholders the controller expects to be present.
    for key in ("components", "components_v2", "channelInfo", "radioCap", "devCap"):
        assert key in body


def test_inform_body_shape():
    info = {"name": "fake"}
    body = adoption.build_inform_body(info)
    assert body["deviceInfo"] is info
    assert body["configVersion"] == "0"
