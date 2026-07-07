"""TLS management-channel client that drives a device to CONNECTED and keeps
it online.

Once the controller has been told to adopt a device it answers the device's
next discovery announce with a UDP pre-adopt reply naming the management port
(see DiscoveryService). This service then opens a TLS connection to that port
and runs the confirmed handshake (see doc/DEVICE_PROTOCOL.md §8):

    device -> PRE_CONNECT_INFO
    device <- PRE_CONNECT_INFO_RESPONSE  (randomKeyForDeviceVerify, username)
    device -> DEVICE_VERIFY_INFO         (auth, randomKeyForSystemVerify)
    device <- DEVICE_VERIFY_RESPONSE     (controller proves itself)
    device -> SYSTEM_VERIFY_RESULT
    device <- VERIFY_RESULT_ACK
    device -> DEVICE_NEGOTIATION
    device <- SYSTEM_NEGOTIATION
    device -> INIT_SYNC_RESULT
    device <- INIT_SYNC_RESULT_ACK       -> device is CONNECTED
    device -> INFORM_REQUEST (every N s)  -> device stays online

The management port is presented behind TLS with a vendor certificate
(CN=localhost); a plain-TCP connection is silently dropped, so the socket is
always wrapped. No client certificate is required.
"""
from __future__ import annotations

import json
import logging
import socket
import ssl
import struct
import threading
import time
from typing import Callable, Optional

from ..devices.base import Device
from ..protocol import adoption, constants
from ..protocol.auth import calculate_device_auth
from ..protocol.framing import encode_frame

logger = logging.getLogger(__name__)

# Sentinel returned by _recv when the read timed out (as opposed to the
# connection being closed, which returns None).
_TIMEOUT = object()

_LENGTH = struct.Struct(">I")


class ManageService:
    """Runs the management-channel handshake and INFORM heartbeat for one
    device in a background thread."""

    def __init__(
        self,
        device: Device,
        *,
        controller_host: str,
        controller_id: str,
        username: str = "admin",
        password: str = "admin",
        adopt_port: int = constants.DEFAULT_ADOPT_TCP_PORT,
        inform_interval: float = constants.DEFAULT_INFORM_INTERVAL_SECONDS,
        on_connected: Optional[Callable[[Device], None]] = None,
        on_closed: Optional[Callable[[Device], None]] = None,
    ) -> None:
        self.device = device
        self.controller_host = controller_host
        self.controller_id = controller_id
        self.username = username
        self.password = password
        self.adopt_port = adopt_port
        self.inform_interval = inform_interval
        self.on_connected = on_connected
        self.on_closed = on_closed

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._seq = 100

    # -- framing helpers -------------------------------------------------
    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _frame(self, mtype: int, body: dict, seq: Optional[int], error: int) -> bytes:
        header = {
            "version": constants.PROTOCOL_VERSION,
            "mac": self.device.mac,
            "type": mtype,
            "device": self.device.device_type,
            "error": error,
        }
        if seq is not None:
            header["seq"] = seq
        payload = json.dumps({"header": header, "body": body}, separators=(",", ":")).encode("utf-8")
        return encode_frame(payload)

    def _send(self, sock: ssl.SSLSocket, mtype: int, body: dict, *, seq: Optional[int] = None, error: int = 0) -> None:
        sock.sendall(self._frame(mtype, body, seq, error))
        logger.debug("manage >> type=%s seq=%s (%s)", hex(mtype), seq, self.device.name)

    @staticmethod
    def _read_exact(sock: ssl.SSLSocket, n: int) -> Optional[bytes]:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _recv(self, sock: ssl.SSLSocket, timeout: float):
        sock.settimeout(timeout)
        try:
            head = self._read_exact(sock, _LENGTH.size)
            if head is None:
                return None
            (length,) = _LENGTH.unpack(head)
            body = self._read_exact(sock, length)
            if body is None:
                return None
            message = json.loads(body)
            header = message.get("header", {})
            logger.debug(
                "manage << type=%s seq=%s err=%s (%s)",
                hex(header.get("type", 0)),
                header.get("seq"),
                header.get("error"),
                self.device.name,
            )
            return message
        except socket.timeout:
            return _TIMEOUT
        except (ValueError, OSError) as exc:
            logger.warning("manage recv failed for %s: %s", self.device.name, exc)
            return None

    # -- connection / state machine -------------------------------------
    def _connect(self) -> ssl.SSLSocket:
        raw = socket.create_connection((self.controller_host, self.adopt_port), timeout=10.0)
        ctx = ssl._create_unverified_context()
        return ctx.wrap_socket(raw, server_hostname=constants.MANAGE_TLS_SERVER_HOSTNAME)

    def _pre_connect(self, sock: ssl.SSLSocket) -> Optional[dict]:
        for _ in range(20):
            if self._stop_event.is_set():
                return None
            self._send(sock, constants.MESSAGE_TYPE_PRE_CONNECT_INFO,
                       adoption.build_pre_connect_body(), seq=self._next_seq())
            message = self._recv(sock, 2.0)
            if message is None:
                return None
            if message is _TIMEOUT:
                continue
            if message.get("header", {}).get("type") == constants.MESSAGE_TYPE_PRE_CONNECT_INFO_RESPONSE:
                return message
        return None

    def _run(self) -> None:
        try:
            sock = self._connect()
        except OSError as exc:
            logger.error("manage connect to %s:%s failed: %s",
                         self.controller_host, self.adopt_port, exc)
            if self.on_closed:
                self.on_closed(self.device)
            return

        logger.info("management channel open for %s (%s:%s)",
                    self.device.name, self.controller_host, self.adopt_port)
        try:
            self._handshake_and_serve(sock)
        finally:
            try:
                sock.close()
            except OSError:
                pass
            if self.on_closed:
                self.on_closed(self.device)

    def _handshake_and_serve(self, sock: ssl.SSLSocket) -> None:
        pre = self._pre_connect(sock)
        if not pre:
            logger.error("no pre-connect response for %s; aborting", self.device.name)
            return
        random_key = pre["body"]["randomKeyForDeviceVerify"]
        username = pre["body"].get("username") or self.username
        # The device's own verify nonce. Must be a full 36-character hyphenated
        # UUID: newer controllers (ECSP 1.7.x, e.g. controller v6.2) reject a
        # randomKeyForSystemVerify shorter than 36 chars. Older controllers
        # accept it too, so this is backward-compatible.
        device_nonce = adoption.new_verify_nonce()
        self._send(
            sock,
            constants.MESSAGE_TYPE_DEVICE_VERIFY_INFO,
            adoption.build_device_verify_body(
                calculate_device_auth(username, self.password, random_key), device_nonce
            ),
            seq=self._next_seq(),
        )

        connected = False
        negotiated = False
        last_inform = 0.0

        while not self._stop_event.is_set():
            message = self._recv(sock, 2.0)
            if message is None:
                logger.info("management channel closed by controller for %s", self.device.name)
                return
            if message is not _TIMEOUT:
                header = message.get("header", {})
                mtype = header.get("type")
                seq = header.get("seq")

                if mtype == constants.MESSAGE_TYPE_DEVICE_VERIFY_RESPONSE:
                    if header.get("error") == 0:
                        self._send(sock, constants.MESSAGE_TYPE_SYSTEM_VERIFY_RESULT, {}, seq=self._next_seq())
                    else:
                        logger.error("device verify rejected for %s (auth failed)", self.device.name)
                        return
                elif mtype == constants.MESSAGE_TYPE_VERIFY_RESULT_ACK:
                    if not negotiated:
                        negotiated = True
                        self._send(
                            sock,
                            constants.MESSAGE_TYPE_DEVICE_NEGOTIATION,
                            adoption.build_negotiation_body(
                                self.device.manage_device_info(),
                                self.controller_id,
                                country_code=self.device.country_code,
                            ),
                            seq=self._next_seq(),
                        )
                elif mtype in (constants.MESSAGE_TYPE_SYSTEM_NEGOTIATION, constants.MESSAGE_TYPE_INIT_SYNC):
                    self._send(sock, constants.MESSAGE_TYPE_INIT_SYNC_RESULT, {}, seq=seq)
                    if not connected:
                        connected = True
                        logger.info("device %s is CONNECTED", self.device.name)
                        if self.on_connected:
                            self.on_connected(self.device)
                elif mtype == constants.MESSAGE_TYPE_INIT_SYNC_RESULT_ACK:
                    if not connected:
                        connected = True
                        logger.info("device %s is CONNECTED", self.device.name)
                        if self.on_connected:
                            self.on_connected(self.device)
                elif mtype == constants.MESSAGE_TYPE_SET_REQUEST:
                    self._send(sock, constants.MESSAGE_TYPE_SET_RESPONSE, {}, seq=seq)
                elif mtype == constants.MESSAGE_TYPE_GET_REQUEST:
                    self._send(sock, constants.MESSAGE_TYPE_GET_RESPONSE, {}, seq=seq)
                elif mtype == constants.MESSAGE_TYPE_NOTIFY_REQUEST:
                    self._send(sock, constants.MESSAGE_TYPE_NOTIFY_REPLY, {}, seq=seq)
                elif mtype == constants.MESSAGE_TYPE_NOTIFY_REQUEST_V2:
                    self._send(sock, constants.MESSAGE_TYPE_NOTIFY_REPLY_V2, {}, seq=seq)
                elif mtype == constants.MESSAGE_TYPE_INFORM_RESPONSE:
                    pass
                else:
                    logger.debug("unhandled management message type=%s for %s",
                                 hex(mtype or 0), self.device.name)

            if connected:
                now = time.monotonic()
                if now - last_inform >= self.inform_interval:
                    last_inform = now
                    self._send(
                        sock,
                        constants.MESSAGE_TYPE_INFORM_REQUEST,
                        adoption.build_inform_body(self.device.manage_device_info()),
                        seq=self._next_seq(),
                    )

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"manage-{self.device.name}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
