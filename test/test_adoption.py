"""Unit tests for the management-channel (adoption) protocol helpers: the
auth calculation and the handshake body builders. These are pure functions,
so they run without a live controller (see doc/DEVICE_PROTOCOL.md §8 for the
live-verified sequence)."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.protocol import adoption, constants
from device_emulator.devices.registry import build_device
from device_emulator.services.manage import ManageService
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
    # Capability fields the controller expects to be present.
    for key in ("components", "components_v2", "channelInfo", "radioCap", "devCap"):
        assert key in body
    assert body["channelInfo"] == []


def test_negotiation_body_includes_components_v2():
    # An empty component manifest makes the controller flag the device as
    # incompatible; a supplied manifest must be carried through.
    comps = {"lan": "1.0", "ssid": "2.3"}
    body = adoption.build_negotiation_body({}, "cid", components_v2=comps)
    assert body["components_v2"] == comps


def test_inform_body_shape():
    info = {"name": "fake"}
    body = adoption.build_inform_body(info)
    assert body["deviceInfo"] is info
    assert body["configVersion"] == "0"


def test_manage_service_reconnects_after_connected_session(monkeypatch):
    device = build_device(
        {"name": "ap", "type": "ap", "mac": "02:15:6d:00:00:20", "ip": "192.168.56.20"}
    )
    on_closed = Mock()
    service = ManageService(
        device,
        controller_host="controller",
        controller_id="cid",
        on_closed=on_closed,
        reconnect_attempts=1,
        reconnect_delay=0,
    )
    connected_sockets = [Mock(), Mock()]
    socket_queue = list(connected_sockets)
    monkeypatch.setattr(service, "_connect", lambda: socket_queue.pop(0))
    session_count = 0

    def serve(_, *, rebuild=False):
        nonlocal session_count
        session_count += 1
        assert rebuild is (session_count == 2)
        if session_count == 2:
            service._stop_event.set()
        return True

    monkeypatch.setattr(service, "_handshake_and_serve", serve)

    service._run()

    assert session_count == 2
    assert all(sock.close.called for sock in connected_sockets)
    on_closed.assert_called_once_with(device)


def test_manage_service_rebuild_uses_managed_credentials(monkeypatch):
    device = build_device(
        {"name": "ap", "type": "ap", "mac": "02:15:6d:00:00:20", "ip": "192.168.56.20"}
    )
    device.controller_id = constants.FACTORY_CONTROLLER_ID
    service = ManageService(
        device,
        controller_host="controller",
        controller_id="cid",
        username="adopt-user",
        password="adopt-password",
        managed_username="managed-user",
        managed_password="managed-password",
    )
    pre_connect = {
        "header": {"type": constants.MESSAGE_TYPE_PRE_CONNECT_INFO_RESPONSE},
        "body": {
            "randomKeyForDeviceVerify": "nonce",
            "username": "managed-user",
        },
    }
    verify_rejected = {
        "header": {
            "type": constants.MESSAGE_TYPE_DEVICE_VERIFY_RESPONSE,
            "error": 1,
        },
        "body": {},
    }
    responses = [pre_connect, verify_rejected]

    def receive(_, __):
        return responses.pop(0)

    send = Mock()
    monkeypatch.setattr(service, "_recv", receive)
    monkeypatch.setattr(service, "_send", send)

    assert service._handshake_and_serve(Mock(), rebuild=True) is False
    assert send.call_args_list[0].args[1] == constants.MESSAGE_TYPE_PRE_CONNECT_INFO
    assert send.call_args_list[0].args[2]["rebuild"] == 1
    assert send.call_args_list[1].args[1] == constants.MESSAGE_TYPE_DEVICE_VERIFY_INFO
    assert send.call_args_list[1].args[2]["auth"] == calculate_device_auth(
        "managed-user", "managed-password", "nonce"
    )


def test_manage_service_captures_provisioned_device_account():
    device = build_device(
        {"name": "ap", "type": "ap", "mac": "02:15:6d:00:00:20", "ip": "192.168.56.20"}
    )
    service = ManageService(
        device,
        controller_host="controller",
        controller_id="cid",
        managed_username="fallback-user",
        managed_password="fallback-password",
    )

    captured = service._capture_managed_account({
        "userAccount": {
            "newUsername": "provisioned-user",
            "newPassword": "provisioned-password",
        }
    })

    assert captured is True
    assert service.managed_username == "provisioned-user"
    assert service.managed_password == "provisioned-password"


def test_manage_service_ignores_incomplete_device_account():
    device = build_device(
        {"name": "ap", "type": "ap", "mac": "02:15:6d:00:00:20", "ip": "192.168.56.20"}
    )
    service = ManageService(
        device,
        controller_host="controller",
        controller_id="cid",
        managed_username="fallback-user",
        managed_password="fallback-password",
    )

    assert service._capture_managed_account({"userAccount": {"newUsername": "user"}}) is False
    assert service.managed_username == "fallback-user"
    assert service.managed_password == "fallback-password"


def test_manage_service_initial_handshake_failure_falls_back_without_reconnect(monkeypatch):
    device = build_device(
        {"name": "ap", "type": "ap", "mac": "02:15:6d:00:00:20", "ip": "192.168.56.20"}
    )
    on_closed = Mock()
    service = ManageService(
        device,
        controller_host="controller",
        controller_id="cid",
        on_closed=on_closed,
        reconnect_attempts=1,
        reconnect_delay=0,
    )
    sock = Mock()
    connect = Mock(return_value=sock)
    monkeypatch.setattr(service, "_connect", connect)
    monkeypatch.setattr(service, "_handshake_and_serve", Mock(return_value=False))

    service._run()

    connect.assert_called_once_with()
    sock.close.assert_called_once_with()
    on_closed.assert_called_once_with(device)
