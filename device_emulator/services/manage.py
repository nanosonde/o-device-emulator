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
        managed_username: Optional[str] = None,
        managed_password: Optional[str] = None,
        adopt_port: int = constants.DEFAULT_ADOPT_TCP_PORT,
        inform_interval: float = constants.DEFAULT_INFORM_INTERVAL_SECONDS,
        on_connected: Optional[Callable[[Device], None]] = None,
        on_closed: Optional[Callable[[Device], None]] = None,
        on_terminal_setting: Optional[Callable[[Device, dict], None]] = None,
        on_monitor_server: Optional[Callable[[Device, dict], None]] = None,
        on_package_capture: Optional[Callable[[Device, dict], None]] = None,
        on_file_transfer_request: Optional[Callable[[Device, dict], None]] = None,
        reconnect_attempts: int = 5,
        reconnect_delay: float = 1.0,
    ) -> None:
        self.device = device
        self.controller_host = controller_host
        self.controller_id = controller_id
        self.username = username
        self.password = password
        self.managed_username = managed_username or username
        self.managed_password = managed_password or password
        self.adopt_port = adopt_port
        self.inform_interval = inform_interval
        self.on_connected = on_connected
        self.on_closed = on_closed
        self.on_terminal_setting = on_terminal_setting
        self.on_monitor_server = on_monitor_server
        self.on_package_capture = on_package_capture
        self.on_file_transfer_request = on_file_transfer_request
        self.on_transfer_channel: Optional[Callable[[Device, dict], None]] = None
        self.reconnect_attempts = max(0, reconnect_attempts)
        self.reconnect_delay = max(0.0, reconnect_delay)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._seq = 100
        # The live management-channel socket (set while the device is
        # CONNECTED). Used by send_file_transfer_frame to upload packet-capture
        # / backup files on the same connection the controller already
        # associated with the device — the controller's v2 manage server
        # routes FILE_TRANSFER_REQUEST_V2 on this channel, not on 29815.
        self._sock: Optional[ssl.SSLSocket] = None
        self._sock_lock = threading.Lock()
        self._notify_id = 0

    # -- framing helpers -------------------------------------------------
    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _frame(self, mtype: int, body: dict, seq: Optional[int], error: int, dest: Optional[str] = None) -> bytes:
        header = {
            "version": self.device.protocol_version,
            "mac": self.device.mac,
            "type": mtype,
            "device": self.device.device_type,
            "error": error,
            # The controller's notify dispatcher dereferences this unguarded.
            "timestamp": int(time.time() * 1000),
        }
        if dest is not None:
            header["dest"] = dest
        if seq is not None:
            header["seq"] = seq
        payload = json.dumps({"header": header, "body": body}, separators=(",", ":")).encode("utf-8")
        return encode_frame(payload)

    def _send(self, sock: ssl.SSLSocket, mtype: int, body: dict, *, seq: Optional[int] = None, error: int = 0) -> None:
        sock.sendall(self._frame(mtype, body, seq, error))
        logger.debug("manage >> type=%s seq=%s (%s)", hex(mtype), seq, self.device.name)

    def send_file_transfer_frame(self, body: dict) -> bool:
        """Send one ``FILE_TRANSFER_RESPONSE_V2`` (0x170000) frame on the live
        management-channel socket. Used by ``PacketCaptureService`` to upload
        a packet-capture file as base64 partitions.

        The controller is the *requester* in this exchange: its v2 manage
        channel handler only accepts FILE_TRANSFER_**RESPONSE**_V2 from a
        device (routing it to the file-transfer service). Sending
        FILE_TRANSFER_REQUEST_V2 instead hits the handler's ``default`` branch
        and the controller closes the channel. Returns True on success.
        """
        with self._sock_lock:
            sock = self._sock
        if sock is None:
            logger.warning(
                "manage: cannot send FILE_TRANSFER_RESPONSE_V2 for %s (not connected)",
                self.device.name,
            )
            return False
        frame = self._frame(constants.MESSAGE_TYPE_FILE_TRANSFER_RESPONSE_V2, body, seq=self._next_seq(), error=0,
                            dest=self.controller_id)
        try:
            sock.sendall(frame)
            logger.debug("manage >> FILE_TRANSFER_RESPONSE_V2 (%s)", self.device.name)
            return True
        except OSError as exc:
            logger.warning("manage: FILE_TRANSFER_RESPONSE_V2 send failed for %s: %s", self.device.name, exc)
            return False

    def send_notify(self, subject: int, content: dict) -> bool:
        """Send a NOTIFY_REQUEST with the given notify subject value and
        content map. Body shape is ``{nid, sub, nre, ctnt}``.

        Must be NOTIFY_REQUEST, not NOTIFY_REQUEST_V2: the server only
        appends the subject to the event topic (``...notify.<sub>``) for the
        V1 type, and the manager subscribes per-subject. A V2 notify lands on
        the base topic where nothing is listening.
        """
        with self._sock_lock:
            sock = self._sock
        if sock is None:
            logger.warning("manage: cannot send notify for %s (not connected)", self.device.name)
            return False
        self._notify_id += 1
        body = {"nid": self._notify_id, "sub": subject, "nre": 1, "ctnt": content}
        try:
            sock.sendall(self._frame(constants.MESSAGE_TYPE_NOTIFY_REQUEST, body, self._next_seq(), 0,
                                     dest=self.controller_id))
            logger.debug("manage >> NOTIFY sub=%s (%s)", subject, self.device.name)
            return True
        except OSError as exc:
            logger.warning("manage: notify send failed for %s: %s", self.device.name, exc)
            return False

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

    def _capture_managed_account(self, body: object) -> bool:
        if not isinstance(body, dict):
            return False
        account = body.get("userAccount")
        if not isinstance(account, dict):
            return False
        username = account.get("newUsername")
        password = account.get("newPassword") or account.get("compatiblePassword")
        if not isinstance(username, str) or not username:
            return False
        if not isinstance(password, str) or not password:
            return False
        self.managed_username = username
        self.managed_password = password
        logger.info("captured managed Device Account for %s", self.device.name)
        return True

    def _pre_connect(
        self, sock: ssl.SSLSocket, *, rebuild: bool = False
    ) -> Optional[dict]:
        for _ in range(20):
            if self._stop_event.is_set():
                return None
            body = (
                self.device.build_manage_pre_connect_body(
                    self.controller_id, rebuild=True
                )
                if rebuild
                else adoption.build_pre_connect_body()
            )
            self._send(
                sock,
                constants.MESSAGE_TYPE_PRE_CONNECT_INFO,
                body,
                seq=self._next_seq(),
            )
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
            connected_once = False
            reconnect_attempt = 0
            while not self._stop_event.is_set():
                try:
                    sock = self._connect()
                except OSError as exc:
                    if not connected_once or reconnect_attempt >= self.reconnect_attempts:
                        logger.error(
                            "manage connect to %s:%s failed: %s",
                            self.controller_host, self.adopt_port, exc,
                        )
                        break
                    reconnect_attempt += 1
                    logger.warning(
                        "management reconnect for %s failed (%s/%s): %s",
                        self.device.name, reconnect_attempt, self.reconnect_attempts, exc,
                    )
                    if self._stop_event.wait(self.reconnect_delay):
                        break
                    continue

                logger.info(
                    "management channel open for %s (%s:%s)",
                    self.device.name, self.controller_host, self.adopt_port,
                )
                try:
                    session_connected = self._handshake_and_serve(
                        sock, rebuild=connected_once
                    )
                    if session_connected:
                        connected_once = True
                        reconnect_attempt = 0
                finally:
                    with self._sock_lock:
                        self._sock = None
                    try:
                        sock.close()
                    except OSError:
                        pass

                if self._stop_event.is_set() or not connected_once:
                    break
                if reconnect_attempt >= self.reconnect_attempts:
                    logger.error(
                        "management reconnect attempts exhausted for %s",
                        self.device.name,
                    )
                    break
                reconnect_attempt += 1
                logger.info(
                    "reconnecting management channel for %s (%s/%s)",
                    self.device.name, reconnect_attempt, self.reconnect_attempts,
                )
                if self._stop_event.wait(self.reconnect_delay):
                    break
        finally:
            if self.on_closed:
                self.on_closed(self.device)

    def _handshake_and_serve(
        self, sock: ssl.SSLSocket, *, rebuild: bool = False
    ) -> bool:
        with self._sock_lock:
            self._sock = sock
        pre = self._pre_connect(sock, rebuild=rebuild)
        if not pre:
            logger.error("no pre-connect response for %s; aborting", self.device.name)
            return False
        random_key = pre["body"]["randomKeyForDeviceVerify"]
        configured_username = self.managed_username if rebuild else self.username
        configured_password = self.managed_password if rebuild else self.password
        username = pre["body"].get("username") or configured_username
        # The device's own verify nonce. Must be a full 36-character hyphenated
        # UUID: newer controllers reject a randomKeyForSystemVerify shorter than
        # 36 chars. Older controllers accept it too, so this is backward-
        # compatible.
        device_nonce = adoption.new_verify_nonce()
        self._send(
            sock,
            constants.MESSAGE_TYPE_DEVICE_VERIFY_INFO,
            adoption.build_device_verify_body(
                calculate_device_auth(username, configured_password, random_key),
                device_nonce,
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
                return connected
            if message is not _TIMEOUT:
                header = message.get("header", {})
                mtype = header.get("type")
                seq = header.get("seq")

                if mtype == constants.MESSAGE_TYPE_DEVICE_VERIFY_RESPONSE:
                    if header.get("error") == 0:
                        self._send(sock, constants.MESSAGE_TYPE_SYSTEM_VERIFY_RESULT, {}, seq=self._next_seq())
                    else:
                        logger.error("device verify rejected for %s (auth failed)", self.device.name)
                        return False
                elif mtype == constants.MESSAGE_TYPE_VERIFY_RESULT_ACK:
                    if not negotiated:
                        negotiated = True
                        self._send(
                            sock,
                            constants.MESSAGE_TYPE_DEVICE_NEGOTIATION,
                            self.device.build_manage_negotiation_body(self.controller_id),
                            seq=self._next_seq(),
                        )
                elif mtype in (constants.MESSAGE_TYPE_SYSTEM_NEGOTIATION, constants.MESSAGE_TYPE_INIT_SYNC):
                    self._capture_managed_account(message.get("body"))
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
                    # The controller pushes config (and the full initial config
                    # after the first INFORM) via SET_REQUEST; the device must
                    # ack with the matching sequenceId + errcode 0 and echo the
                    # configVersion so the controller records the config as
                    # applied. An empty body makes the controller treat the
                    # config sync as failed and forget the device.
                    req_body = message.get("body") or {}
                    logger.info(
                        "received SET_REQUEST for %s: keys=%s",
                        self.device.name,
                        sorted(req_body) if isinstance(req_body, dict) else [],
                    )
                    self._capture_managed_account(req_body)
                    resp_body = self.device.build_set_response(req_body)
                    # Handle transferChannel BEFORE sending the SET response:
                    # the controller's download flow pushes the SET and checks
                    # the transfer channel cache synchronously in the same HTTP
                    # request, so the device must connect to 29815 before the
                    # SET response is processed.
                    tc = req_body.get("transferChannel") if isinstance(req_body, dict) else None
                    if tc:
                        logger.info("received transferChannel for %s: %s", self.device.name, tc)
                        self.device.handle_transfer_channel(tc)
                        if self.on_transfer_channel:
                            self.on_transfer_channel(self.device, tc)
                    self._send(sock, constants.MESSAGE_TYPE_SET_RESPONSE, resp_body, seq=seq)
                    # Detect a terminalSetting config push and hand it off to
                    # the device. The runner watches device.terminal_setting
                    # and starts/stops the RTTY client service accordingly.
                    ts = req_body.get("terminalSetting") if isinstance(req_body, dict) else None
                    if ts:
                        logger.info("received terminalSetting for %s: %s", self.device.name, ts)
                        self.device.handle_terminal_setting(ts)
                        if self.on_terminal_setting:
                            self.on_terminal_setting(self.device, ts)
                    # monitorServer config push enables Tools → Network Check
                    # (DMP channel, port 29817). See doc §11.5.
                    ms = req_body.get("monitorServer") if isinstance(req_body, dict) else None
                    if ms:
                        logger.info("received monitorServer for %s: %s", self.device.name, ms)
                        self.device.handle_monitor_server(ms)
                        if self.on_monitor_server:
                            self.on_monitor_server(self.device, ms)
                    # packageCapture config push starts/stops a packet capture.
                    # The runner wires the capture/transfer service. See §11.6.
                    pc = req_body.get("packageCapture") if isinstance(req_body, dict) else None
                    if pc:
                        logger.info("received packageCapture for %s: %s", self.device.name, pc)
                        self.device.handle_package_capture(pc)
                        if self.on_package_capture:
                            self.on_package_capture(self.device, pc)
                elif mtype == constants.MESSAGE_TYPE_GET_REQUEST:
                    self._send(sock, constants.MESSAGE_TYPE_GET_RESPONSE, self.device.build_get_response(message.get("body") or {}), seq=seq)
                elif mtype == constants.MESSAGE_TYPE_NOTIFY_REQUEST:
                    self._send(sock, constants.MESSAGE_TYPE_NOTIFY_REPLY, {}, seq=seq)
                elif mtype == constants.MESSAGE_TYPE_NOTIFY_REQUEST_V2:
                    self._send(sock, constants.MESSAGE_TYPE_NOTIFY_REPLY_V2, {}, seq=seq)
                elif mtype == constants.MESSAGE_TYPE_FILE_TRANSFER_REQUEST_V2:
                    # The controller is asking the device to upload a file
                    # (e.g. the packet capture it just told us to take).
                    req_body = message.get("body") or {}
                    logger.info("received file-transfer request for %s: %s", self.device.name, req_body)
                    if self.on_file_transfer_request:
                        self.on_file_transfer_request(self.device, req_body)
                elif mtype == constants.MESSAGE_TYPE_INFORM_RESPONSE:
                    pass
                else:
                    logger.debug("unhandled management message type=%s for %s",
                                 hex(mtype or 0), self.device.name)

            if connected:
                now = time.monotonic()
                if now - last_inform >= self.inform_interval:
                    last_inform = now
                    inform_body = self.device.manage_inform_body()
                    self._send(
                        sock,
                        constants.MESSAGE_TYPE_INFORM_REQUEST,
                        inform_body,
                        seq=self._next_seq(),
                    )
        return connected

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
