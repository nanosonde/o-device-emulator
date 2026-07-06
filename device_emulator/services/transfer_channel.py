"""File-transfer channel client — connects to the controller's transfer server
(port 29815) and serves ``FILE_TRANSFER_REQUEST_V2`` partition requests.

The controller pushes a ``transferChannel`` SET config (``port``, ``token``,
``aesKey``, ``iv``) to tell the device to open a TLS connection to port 29815.
This connection runs the same V2 pre-connect/verify/negotiation handshake as
the management channel (29814), then the controller sends
``FILE_TRANSFER_REQUEST_V2`` messages requesting byte-range partitions of the
capture file. The device replies with ``FILE_TRANSFER_RESPONSE_V2`` messages
carrying base64-encoded data.

This service is analogous to ``DeviceMonitorService`` (DMP, 29817) and
``RttyService`` (RTTY, 29816): a per-device background thread that connects,
handshakes, and serves requests on a controller-facing channel.
"""
from __future__ import annotations

import json
import logging
import socket
import ssl
import threading
import time
from typing import Callable, Optional

from ..devices.base import Device
from ..protocol import constants
from ..protocol import adoption
from ..protocol.framing import encode_frame

logger = logging.getLogger(__name__)

RECONNECT_DELAY = 5.0


class TransferChannelService:
    """Per-device file-transfer channel client (port 29815).

    Created by the runner when the device receives a ``transferChannel`` SET
    key. Connects to the controller's transfer server, runs the V2 handshake,
    and serves ``FILE_TRANSFER_REQUEST_V2`` partition requests by delegating
    to the ``PacketCaptureService`` (or any file-serving callback).
    """

    def __init__(
        self,
        device: Device,
        *,
        controller_host: str,
        controller_id: str,
        token: str,
        transfer_port: int = constants.TRANSFER_V2_TCP_PORT,
        username: str = "admin",
        password: str = "admin",
        on_file_request: Optional[Callable[[Device, dict], bool]] = None,
        on_closed: Optional[Callable[[Device], None]] = None,
    ) -> None:
        self.device = device
        self.controller_host = controller_host
        self.controller_id = controller_id
        self.token = token
        self.transfer_port = transfer_port
        self.username = username
        self.password = password
        self.on_file_request = on_file_request
        self.on_closed = on_closed

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[ssl.SSLSocket] = None
        self._seq = 200

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _frame(self, mtype: int, body: dict, seq: Optional[int], error: int) -> bytes:
        header = {
            "version": self.device.protocol_version,
            "mac": self.device.mac,
            "type": mtype,
            "device": self.device.device_type,
            "error": error,
            "timestamp": int(time.time() * 1000),
            "dest": self.controller_id,
        }
        if seq is not None:
            header["seq"] = seq
        payload = json.dumps({"header": header, "body": body}, separators=(",", ":")).encode("utf-8")
        return encode_frame(payload)

    def _send(self, sock, mtype: int, body: dict, *, seq: Optional[int] = None, error: int = 0) -> None:
        sock.sendall(self._frame(mtype, body, seq, error))
        logger.debug("transfer >> type=%s seq=%s (%s)", hex(mtype), seq, self.device.name)

    @staticmethod
    def _read_exact(sock, n: int) -> Optional[bytes]:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _recv(self, sock, timeout: float):
        import struct
        sock.settimeout(timeout)
        try:
            head = self._read_exact(sock, 4)
            if head is None:
                return None
            (length,) = struct.unpack(">I", head)
            body = self._read_exact(sock, length)
            if body is None:
                return None
            message = json.loads(body)
            header = message.get("header", {})
            logger.debug("transfer << type=%s seq=%s err=%s (%s)",
                         hex(header.get("type", 0)), header.get("seq"), header.get("error"),
                         self.device.name)
            return message
        except socket.timeout:
            return _TIMEOUT
        except (ValueError, OSError) as exc:
            logger.warning("transfer recv failed for %s: %s", self.device.name, exc)
            return None

    def _connect(self) -> ssl.SSLSocket:
        raw = socket.create_connection((self.controller_host, self.transfer_port), timeout=10.0)
        ctx = ssl._create_unverified_context()
        return ctx.wrap_socket(raw, server_hostname=constants.MANAGE_TLS_SERVER_HOSTNAME)

    def _handshake(self, sock) -> bool:
        """Run the transfer channel handshake.

        Simpler than the management channel: the device sends PRE_CONNECT_INFO
        with the transfer ``token``, and the controller responds with
        PRE_CONNECT_INFO_RESPONSE carrying just ``{errCode: 0}`` — no
        verify/negotiation. If errCode is 0 the channel is established."""
        pre_connect_body = adoption.build_pre_connect_body()
        pre_connect_body["token"] = self.token
        self._send(sock, constants.MESSAGE_TYPE_PRE_CONNECT_INFO,
                   pre_connect_body, seq=self._next_seq())
        pre = self._recv(sock, 5.0)
        if not pre or pre is _TIMEOUT:
            logger.error("transfer: no pre-connect response for %s", self.device.name)
            return False
        header = pre.get("header", {})
        err = header.get("error", 0)
        if err != 0:
            logger.error("transfer: pre-connect rejected for %s (err=%s)", self.device.name, err)
            return False
        body = pre.get("body") or {}
        resp_err = body.get("errCode", 0)
        if resp_err != 0:
            logger.error("transfer: pre-connect errCode=%s for %s", resp_err, self.device.name)
            return False
        logger.info("transfer: channel established for %s", self.device.name)
        return True

    def _serve(self, sock) -> None:
        import struct
        sock.settimeout(60.0)
        while not self._stop_event.is_set():
            try:
                head = self._read_exact(sock, 4)
                if head is None:
                    logger.info("transfer: channel closed for %s", self.device.name)
                    return
                (length,) = struct.unpack(">I", head)
                body = self._read_exact(sock, length)
                if body is None:
                    return
                message = json.loads(body)
                header = message.get("header", {})
                mtype = header.get("type")
                seq = header.get("seq")
                logger.debug("transfer << type=%s seq=%s (%s)", hex(mtype or 0), seq, self.device.name)

                if mtype == constants.MESSAGE_TYPE_FILE_TRANSFER_REQUEST_V2:
                    req_body = message.get("body") or {}
                    logger.info("transfer: file-transfer request for %s: %s", self.device.name, req_body)
                    if self.on_file_request:
                        ok = self.on_file_request(self.device, req_body)
                        if not ok:
                            self._send(sock, constants.MESSAGE_TYPE_FILE_TRANSFER_RESPONSE_V2,
                                      {"fileTransfer": {"errCode": 1}}, seq=seq)
                    else:
                        self._send(sock, constants.MESSAGE_TYPE_FILE_TRANSFER_RESPONSE_V2,
                                  {"fileTransfer": {"errCode": 1}}, seq=seq)
                elif mtype == constants.MESSAGE_TYPE_SET_REQUEST:
                    resp = self.device.build_set_response(message.get("body") or {})
                    self._send(sock, constants.MESSAGE_TYPE_SET_RESPONSE, resp, seq=seq)
                elif mtype == constants.MESSAGE_TYPE_INFORM_RESPONSE:
                    pass
                else:
                    logger.debug("transfer: unhandled type=%s for %s", hex(mtype or 0), self.device.name)
            except socket.timeout:
                continue
            except (OSError, ssl.SSLError) as exc:
                logger.info("transfer: connection error for %s: %s", self.device.name, exc)
                return

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                sock = self._connect()
                self._sock = sock
                logger.info("transfer: connected to %s:%s for %s",
                           self.controller_host, self.transfer_port, self.device.name)
                if self._handshake(sock):
                    self._serve(sock)
                sock.close()
            except (OSError, ssl.SSLError) as exc:
                logger.debug("transfer: connect failed for %s: %s", self.device.name, exc)
            self._sock = None
            if self._stop_event.is_set():
                break
            self._stop_event.wait(RECONNECT_DELAY)
        if self.on_closed:
            self.on_closed(self.device)

    def connect_and_handshake(self) -> bool:
        """Connect to 29815 and complete the pre-connect handshake
        synchronously. Returns True if the channel is established."""
        try:
            sock = self._connect()
            self._sock = sock
            logger.info("transfer: connected to %s:%s for %s",
                       self.controller_host, self.transfer_port, self.device.name)
            if self._handshake(sock):
                return True
            sock.close()
            self._sock = None
        except (OSError, ssl.SSLError) as exc:
            logger.warning("transfer: connect failed for %s: %s", self.device.name, exc)
            self._sock = None
        return False

    def start_serve_loop(self) -> None:
        """Start the serve loop in a background thread (after
        connect_and_handshake succeeded)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._serve_loop, name=f"transfer-{self.device.name}", daemon=True
        )
        self._thread.start()

    def _serve_loop(self) -> None:
        if self._sock is None:
            return
        try:
            self._serve(self._sock)
        finally:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            if self.on_closed:
                self.on_closed(self.device)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"transfer-{self.device.name}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


_TIMEOUT = object()