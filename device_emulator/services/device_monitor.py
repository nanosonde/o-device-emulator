"""Device-Monitor client service — connects to the controller's DMP server
(port 29817) and serves Network Check probe requests for an emulated device.

Once the controller pushes a ``monitorServer`` config (``token``, ``port``,
``protocol``, ``aesKey``, ``iv``, ``path``, ``domain``, ``compress``,
``content``) to the device over the management channel, the device is expected
to open a TLS connection to the controller's device-monitor server, send a
protobuf monitor message with the shared ``token`` to register, and then
respond to probe/monitor requests (ping, traceroute, component data).

This service runs in a background thread per device. It:

1. Opens a TLS connection to ``controller_host:monitor_port`` (default 29817).
2. Sends a register monitor message (mac, token, path, version).
3. Enters a serve loop:
   - Receives monitor messages from the controller.
   - For probe requests (MSG_EMPTY with a path indicating ping/traceroute),
     synthesizes a plausible response and sends it back.
   - Sends periodic heartbeat messages (MSG_EMPTY with current epoch).
4. Reconnects on disconnection.

See ``doc/DEVICE_PROTOCOL.md`` §11 for the full protocol reference.
"""
from __future__ import annotations

import logging
import socket
import ssl
import threading
import time
from typing import Callable, Optional

from ..devices.base import Device
from ..protocol import constants
from ..protocol import device_monitor as dmp
from . import network_probe

logger = logging.getLogger(__name__)

DEFAULT_HEARTBEAT_INTERVAL = 10.0
RECONNECT_DELAY = 5.0


class DeviceMonitorService:
    """Device-Monitor (DMP) client for one device. Connects to the controller's
    DMP server and serves Network Check probe requests.

    The service is created when the device receives a ``monitorServer`` config
    push over the management channel. It is stopped when the device goes
    offline or the controller disables monitoring.
    """

    def __init__(
        self,
        device: Device,
        *,
        controller_host: str,
        token: str,
        monitor_port: int = constants.DEVICE_MONITOR_TCP_PORT,
        use_tls: bool = True,
        path: str = "/",
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL,
        on_closed: Optional[Callable[[Device], None]] = None,
    ) -> None:
        self.device = device
        self.controller_host = controller_host
        self.token = token
        self.monitor_port = monitor_port
        self.use_tls = use_tls
        self.path = path or "/"
        self.heartbeat_interval = heartbeat_interval
        self.on_closed = on_closed

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[ssl.SSLSocket] = None
        self._seq = 0
        self._last_heartbeat_sent = 0.0

    # -- connection -------------------------------------------------------
    def _connect(self) -> ssl.SSLSocket:
        raw = socket.create_connection(
            (self.controller_host, self.monitor_port), timeout=10.0
        )
        if self.use_tls:
            ctx = ssl._create_unverified_context()
            return ctx.wrap_socket(
                raw, server_hostname=constants.MANAGE_TLS_SERVER_HOSTNAME
            )
        return raw  # type: ignore[return-value]

    def _mac_bytes(self) -> bytes:
        """Convert the device MAC (``AA-BB-CC-DD-EE-FF``) to raw bytes."""
        return bytes(int(octet, 16) for octet in self.device.mac.split("-"))

    def _token_bytes(self) -> bytes:
        """The token from the monitorServer SET config."""
        return self.token.encode("utf-8") if self.token else b""

    def _register(self, sock) -> bool:
        """Send a register monitor message and wait briefly for a reply."""
        pkt = dmp.build_register_message(
            mac_bytes=self._mac_bytes(),
            token_bytes=self._token_bytes(),
            path=self.path,
            version="1.0",
            msg_type=dmp.MSG_EMPTY,
        )
        sock.sendall(pkt)
        logger.info("DMP REGISTER sent for %s (mac=%s, path=%s)",
                     self.device.name, self.device.mac, self.path)
        # Wait briefly for the controller to accept (non-blocking — the
        # controller may not send an explicit ack; it just keeps the channel
        # open).
        sock.settimeout(2.0)
        try:
            msg = dmp.read_ecsp_packet(sock)
            if msg is not None:
                logger.debug("DMP received initial reply: msgType=%s, errorCode=%s",
                             msg.header.msg_type, msg.header.error_code)
                # If the controller sent an error code, registration failed.
                if msg.header.error_code != 0:
                    logger.warning("DMP registration rejected for %s (errorCode=%s)",
                                  self.device.name, msg.header.error_code)
                    return False
        except socket.timeout:
            # No reply is OK — the controller may silently accept.
            pass
        return True

    # -- serve loop -------------------------------------------------------
    def _serve(self, sock) -> None:
        sock.settimeout(self.heartbeat_interval)
        while not self._stop_event.is_set():
            try:
                msg = dmp.read_ecsp_packet(sock)
                if msg is None:
                    logger.info("DMP connection closed for %s", self.device.name)
                    return
                self._handle_message(sock, msg)
            except socket.timeout:
                # No message — send a heartbeat.
                self._maybe_send_heartbeat(sock)
            except (OSError, ssl.SSLError) as exc:
                logger.info("DMP connection error for %s: %s", self.device.name, exc)
                return

    def _handle_message(self, sock, msg: dmp.MonitorMessage) -> None:
        """Handle an incoming DMP message from the controller."""
        msg_type = msg.header.msg_type
        logger.debug("DMP message from controller: type=%s, path=%s, seq=%s",
                     msg_type, msg.header.path, msg.header.seq)

        if msg_type == dmp.MSG_EMPTY:
            # Could be a ping/traceroute probe or a keepalive. The path field
            # indicates the probe type (e.g. "/ping", "/traceroute").
            path = msg.header.path or ""
            response_data = network_probe.handle_probe(self.device, path, msg.data)
            self._send_response(sock, msg.header.seq, response_data)
        elif msg_type == dmp.MSG_COMPONENT_LIST:
            # The controller is requesting component data — send back an
            # empty component list (the emulator reports data via INFORM, not
            # the DMP channel).
            self._send_response(sock, msg.header.seq, b"")
        elif msg_type == dmp.MSG_JSON_COMPONENT_LIST:
            # JSON component list request — respond with an empty list.
            self._send_response(sock, msg.header.seq, b"")
        else:
            logger.debug("DMP unknown message type %s for %s", msg_type, self.device.name)

    def _send_response(self, sock, seq: int, data: bytes) -> None:
        """Send a response monitor message."""
        self._seq += 1
        hdr = dmp.MonitorMessageHeader(
            mac=self._mac_bytes(),
            token=self._token_bytes(),
            path=self.path,
            version="1.0",
            msg_type=dmp.MSG_EMPTY,
            seq=seq,
            epoch_ms=int(time.time() * 1000),
        )
        msg = dmp.MonitorMessage(header=hdr, data=data)
        try:
            sock.sendall(dmp.pack_ecsp_packet(msg.encode()))
        except (OSError, ssl.SSLError) as exc:
            logger.debug("DMP send error for %s: %s", self.device.name, exc)

    def _maybe_send_heartbeat(self, sock) -> None:
        """Send a heartbeat if the interval has elapsed."""
        now = time.time()
        if now - self._last_heartbeat_sent < self.heartbeat_interval:
            return
        self._last_heartbeat_sent = now
        pkt = dmp.build_heartbeat_message(self._mac_bytes(), self._token_bytes(), self._seq)
        try:
            sock.sendall(pkt)
        except (OSError, ssl.SSLError) as exc:
            logger.debug("DMP heartbeat send error for %s: %s", self.device.name, exc)

    # -- lifecycle --------------------------------------------------------
    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                sock = self._connect()
                self._sock = sock
                if self._register(sock):
                    logger.info("DMP connected for %s", self.device.name)
                    self._serve(sock)
                else:
                    logger.warning("DMP registration failed for %s", self.device.name)
                sock.close()
            except (OSError, ssl.SSLError) as exc:
                logger.debug("DMP connection failed for %s: %s", self.device.name, exc)
            self._sock = None
            if self._stop_event.is_set():
                break
            self._stop_event.wait(RECONNECT_DELAY)

        if self.on_closed:
            self.on_closed(self.device)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"dmp-{self.device.name}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=3.0)
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()