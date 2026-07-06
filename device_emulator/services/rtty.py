"""RTTY client service — connects to the controller's RTTY server (port 29816)
and serves terminal sessions for an emulated device.

Once the controller pushes a terminal setting config (``enable: true``,
``token``, ``port``, ``ssl``) to the device over the management channel, the
device is expected to open a TLS connection to the controller's RTTY server,
send a ``REGISTER`` frame with the shared ``token``, and then relay shell I/O
for each ``LOGIN`` session the controller initiates.

This service runs in a background thread per device. It:

1. Opens a TLS connection to ``controller_host:rtty_port`` (default 29816).
2. Sends ``REGISTER`` (version, devid=MAC, description, token).
3. Waits for the controller's ``REGISTER`` reply (``err=0`` = OK).
4. Enters a serve loop:
   - ``LOGIN`` (controller → device): start a new ``DummyShell`` for that
     ``sid``; reply ``LOGIN`` with ``code=0`` (success).
   - ``TERMDATA`` (controller → device): feed the keystroke bytes into the
     shell for that ``sid``; send the shell output back as ``TERMDATA``.
   - ``LOGOUT`` (controller → device): close that session's shell.
   - ``HEARTBEAT`` (controller → device): reply with ``HEARTBEAT``.
   - ``ACK`` (controller → device): flow-control ack (ignored).
   - ``WINSIZE`` (controller → device): resize the terminal (ignored — the
     dummy shell doesn't use winsize).
5. Sends periodic ``HEARTBEAT`` frames to keep the connection alive.

See ``doc/DEVICE_PROTOCOL.md`` §10 for the full protocol reference.
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
from ..protocol import rtty as rtty_proto
from .rtty_shell import DummyShell

logger = logging.getLogger(__name__)

# How often the device sends a HEARTBEAT frame (seconds).
DEFAULT_HEARTBEAT_INTERVAL = 10.0
# Reconnect delay after a dropped connection (seconds).
RECONNECT_DELAY = 5.0


class RttyService:
    """RTTY client for one device. Connects to the controller's RTTY server
    and serves terminal sessions.

    The service is created when the device receives a terminal setting
    config push (``enable: true``) over the management channel. It is stopped
    when ``enable: false`` is pushed or the device goes offline.
    """

    def __init__(
        self,
        device: Device,
        *,
        controller_host: str,
        token: str,
        rtty_port: int = constants.RTTY_TCP_PORT,
        use_tls: bool = True,
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL,
        on_closed: Optional[Callable[[Device], None]] = None,
    ) -> None:
        self.device = device
        self.controller_host = controller_host
        self.token = token
        self.rtty_port = rtty_port
        self.use_tls = use_tls
        self.heartbeat_interval = heartbeat_interval
        self.on_closed = on_closed

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[ssl.SSLSocket] = None
        self._sessions: dict[str, DummyShell] = {}
        self._sessions_lock = threading.Lock()
        self._tunnels: dict[int, _TunnelRelay] = {}
        self._tunnels_lock = threading.Lock()
        self._last_heartbeat_sent = 0.0

    # -- connection -------------------------------------------------------
    def _connect(self) -> ssl.SSLSocket:
        raw = socket.create_connection(
            (self.controller_host, self.rtty_port), timeout=10.0
        )
        if self.use_tls:
            ctx = ssl._create_unverified_context()
            return ctx.wrap_socket(
                raw, server_hostname=constants.MANAGE_TLS_SERVER_HOSTNAME
            )
        return raw  # type: ignore[return-value]

    def _register(self, sock) -> bool:
        """Send REGISTER and wait for the controller's reply."""
        description = f"{self.device.name} ({self.device.device_type})"
        frame = rtty_proto.pack_register_request(
            version=rtty_proto.MIN_PROTOCOL_VERSION,
            devid=self.device.mac,
            description=description,
            token=self.token,
        )
        sock.sendall(frame)
        logger.debug("rtty >> REGISTER (%s)", self.device.name)

        reply = rtty_proto.read_frame(sock)
        if reply is None:
            logger.error("rtty: no REGISTER reply for %s", self.device.name)
            return False
        if reply.type != rtty_proto.REGISTER:
            logger.error(
                "rtty: unexpected REGISTER reply type=%s for %s",
                reply.type, self.device.name,
            )
            return False
        err, msg = rtty_proto.parse_register_response(reply.payload)
        if err != rtty_proto.REGISTER_OK:
            logger.error(
                "rtty: REGISTER rejected for %s: err=%s msg=%s",
                self.device.name, err, msg,
            )
            return False
        logger.info("rtty: REGISTER OK for %s", self.device.name)
        return True

    # -- serve loop -------------------------------------------------------
    def _serve(self, sock) -> None:
        """Main serve loop: read frames and dispatch."""
        sock.settimeout(self.heartbeat_interval * 2)
        while not self._stop_event.is_set():
            try:
                frame = rtty_proto.read_frame(sock)
            except socket.timeout:
                # Send a heartbeat on timeout if we haven't recently
                self._maybe_send_heartbeat(sock)
                continue
            if frame is None:
                logger.info("rtty: connection closed by controller for %s", self.device.name)
                return
            self._handle_frame(sock, frame)
            self._maybe_send_heartbeat(sock)

    def _handle_frame(self, sock, frame: rtty_proto.RttyFrame) -> None:
        mtype = frame.type
        if mtype == rtty_proto.LOGIN:
            self._handle_login(sock, frame.payload)
        elif mtype == rtty_proto.TERMDATA:
            self._handle_termdata(sock, frame.payload)
        elif mtype == rtty_proto.LOGOUT:
            self._handle_logout(frame.payload)
        elif mtype == rtty_proto.HEARTBEAT:
            logger.debug("rtty << HEARTBEAT (%s)", self.device.name)
        elif mtype == rtty_proto.ACK:
            self._handle_ack(frame.payload)
        elif mtype == rtty_proto.WINSIZE:
            logger.debug("rtty << WINSIZE (%s)", self.device.name)
        elif mtype == rtty_proto.TUNNEL_ADD:
            self._handle_tunnel_add(frame.payload)
        elif mtype == rtty_proto.TUNNEL_DELETE:
            self._handle_tunnel_delete(frame.payload)
        elif mtype == rtty_proto.SSHDATA:
            self._handle_tunnel_data(frame, "ssh")
        elif mtype == rtty_proto.TELNETDATA:
            self._handle_tunnel_data(frame, "telnet")
        elif mtype == rtty_proto.TCPDATA:
            self._handle_tunnel_data(frame, "tcp")
        elif mtype == rtty_proto.HTTPSDATA:
            self._handle_tunnel_data(frame, "https")
        elif mtype == rtty_proto.STANDALONE_AUTH:
            self._handle_standalone_auth(frame.payload)
        else:
            logger.debug("rtty: unhandled frame type=%s for %s", mtype, self.device.name)

    def _handle_login(self, sock, payload: bytes) -> None:
        """Controller wants to open a terminal session for a sid."""
        try:
            sid = rtty_proto.parse_login(payload)
        except ValueError as exc:
            logger.warning("rtty: bad LOGIN payload: %s", exc)
            return
        with self._sessions_lock:
            if sid not in self._sessions:
                shell = DummyShell(
                    device_name=self.device.name,
                    device_type=self.device.device_type,
                )
                self._sessions[sid] = shell
                logger.info("rtty: LOGIN sid=%s for %s", sid[:8], self.device.name)
        # Reply with LOGIN code=0 (success)
        sock.sendall(rtty_proto.pack_login_response(sid, rtty_proto.LOGIN_OK))
        # Send an initial prompt so the terminal shows something
        shell = self._sessions.get(sid)
        if shell is not None:
            initial = b"\r\n" + shell.prompt()
            sock.sendall(rtty_proto.pack_termdata_raw(sid, initial))

    def _handle_termdata(self, sock, payload: bytes) -> None:
        """Controller sent keystroke data for a sid."""
        try:
            sid, data = rtty_proto.parse_termdata(payload)
        except ValueError as exc:
            logger.warning("rtty: bad TERMDATA payload: %s", exc)
            return
        with self._sessions_lock:
            shell = self._sessions.get(sid)
        if shell is None:
            logger.warning("rtty: TERMDATA for unknown sid=%s", sid[:8])
            return
        output = shell.feed(data)
        if output:
            sock.sendall(rtty_proto.pack_termdata_raw(sid, output))

    def _handle_logout(self, payload: bytes) -> None:
        """Controller closed a terminal session."""
        try:
            sid = rtty_proto.parse_logout(payload)
        except ValueError as exc:
            logger.warning("rtty: bad LOGOUT payload: %s", exc)
            return
        with self._sessions_lock:
            self._sessions.pop(sid, None)
        logger.info("rtty: LOGOUT sid=%s for %s", sid[:8], self.device.name)

    def _handle_ack(self, payload: bytes) -> None:
        """Flow-control ACK from the controller (bytes acknowledged)."""
        try:
            sid, ack = rtty_proto.parse_ack(payload)
        except ValueError:
            return
        logger.debug("rtty << ACK sid=%s ack=%s", sid[:8], ack)

    # -- tunnel / remote-access handlers ---------------------------------
    def _handle_tunnel_add(self, payload: bytes) -> None:
        """TUNNEL_ADD: the controller wants a reverse tunnel to a local port.

        The controller asks the device to open a reverse tunnel so it can
        reach a service on the device's local network (e.g. the device's web
        UI, SSH, or a TCP port). The device connects to the specified
        ``local_addr:local_port`` and relays data bidirectionally via
        ``TCPDATA``/``SSHDATA``/``HTTPSDATA`` frames on the RTTY channel.

        For SSH/HTTPS tunnels, the controller sends credentials via
        ``STANDALONE_AUTH`` before the data frames; for TCP tunnels the data
        frames flow directly. Each tunnel is identified by a ``tunnel_id``
        (1 byte) and carries a ``request_id`` (16 bytes) per data frame for
        multiplexing.

        The emulator opens a real TCP connection to ``local_addr:local_port``
        and spawns a relay thread that forwards controller→tunnel data to the
        local socket and local socket→controller data back as ``TCPDATA``
        frames.
        """
        try:
            tunnel_id, local_addr, local_port = rtty_proto.parse_tunnel_add(payload)
        except ValueError as exc:
            logger.warning("rtty: bad TUNNEL_ADD: %s", exc)
            return
        import struct as _s
        addr_str = socket.inet_ntoa(_s.pack(">I", local_addr))
        logger.info(
            "rtty: TUNNEL_ADD id=%s -> %s:%s for %s",
            tunnel_id, addr_str, local_port, self.device.name,
        )
        # Open a TCP connection to the local target and start a relay thread.
        with self._tunnels_lock:
            if tunnel_id in self._tunnels:
                logger.warning("rtty: tunnel id=%s already exists for %s",
                               tunnel_id, self.device.name)
                return
        try:
            target_sock = socket.create_connection(
                (addr_str, local_port), timeout=5.0
            )
        except OSError as exc:
            logger.warning(
                "rtty: tunnel connect to %s:%s failed for %s: %s",
                addr_str, local_port, self.device.name, exc,
            )
            return
        tunnel = _TunnelRelay(
            tunnel_id=tunnel_id,
            local_sock=target_sock,
            rtty_sock=self._sock,
            device_name=self.device.name,
            on_close=self._cleanup_tunnel,
        )
        with self._tunnels_lock:
            self._tunnels[tunnel_id] = tunnel
        tunnel.start()

    def _handle_tunnel_delete(self, payload: bytes) -> None:
        try:
            tunnel_id = rtty_proto.parse_tunnel_delete(payload)
        except ValueError as exc:
            logger.warning("rtty: bad TUNNEL_DELETE: %s", exc)
            return
        logger.info("rtty: TUNNEL_DELETE id=%s for %s", tunnel_id, self.device.name)
        self._cleanup_tunnel(tunnel_id)

    def _cleanup_tunnel(self, tunnel_id: int) -> None:
        """Close and remove a tunnel relay."""
        with self._tunnels_lock:
            tunnel = self._tunnels.pop(tunnel_id, None)
        if tunnel is not None:
            tunnel.close()

    def _handle_tunnel_data(self, frame: rtty_proto.RttyFrame, kind: str) -> None:
        """Relay controller→tunnel data to the local socket.

        ``TCPDATA``/``HTTPSDATA`` carry ``tunnel_id(1) + request_id(16) + data``.
        ``SSHDATA``/``TELNETDATA`` carry ``tunnel_id(1) + data`` (no request_id).
        """
        try:
            if kind in ("tcp", "https"):
                tunnel_id, _request_id, data = rtty_proto.parse_tcp_data(frame.payload) \
                    if kind == "tcp" else rtty_proto.parse_https_data(frame.payload)
            else:
                tunnel_id, data_str = (
                    rtty_proto.parse_ssh_data(frame.payload) if kind == "ssh"
                    else rtty_proto.parse_telnet_data(frame.payload)
                )
                data = data_str.encode("utf-8", errors="replace")
        except ValueError as exc:
            logger.warning("rtty: bad %s payload: %s", kind.upper(), exc)
            return
        with self._tunnels_lock:
            tunnel = self._tunnels.get(tunnel_id)
        if tunnel is None:
            logger.debug("rtty: %s for unknown tunnel id=%s", kind.upper(), tunnel_id)
            return
        tunnel.send_to_local(data)

    def _handle_standalone_auth(self, payload: bytes) -> None:
        try:
            tunnel_id, creds = rtty_proto.parse_standalone_auth(payload)
        except ValueError as exc:
            logger.warning("rtty: bad STANDALONE_AUTH: %s", exc)
            return
        logger.info("rtty: STANDALONE_AUTH id=%s (auto-login)", tunnel_id)

    # -- heartbeat --------------------------------------------------------
    def _maybe_send_heartbeat(self, sock) -> None:
        now = time.monotonic()
        if now - self._last_heartbeat_sent >= self.heartbeat_interval:
            try:
                uptime = int(getattr(self.device, "uptime_seconds", 0) or 0)
                sock.sendall(rtty_proto.pack_heartbeat(uptime))
                self._last_heartbeat_sent = now
                logger.debug("rtty >> HEARTBEAT (%s)", self.device.name)
            except OSError as exc:
                logger.warning("rtty: heartbeat send failed for %s: %s", self.device.name, exc)

    # -- lifecycle --------------------------------------------------------
    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                sock = self._connect()
            except OSError as exc:
                logger.warning(
                    "rtty: connect to %s:%s failed for %s: %s",
                    self.controller_host, self.rtty_port, self.device.name, exc,
                )
                if self._stop_event.wait(RECONNECT_DELAY):
                    break
                continue

            self._sock = sock
            logger.info(
                "rtty: connected to %s:%s for %s",
                self.controller_host, self.rtty_port, self.device.name,
            )
            try:
                if not self._register(sock):
                    sock.close()
                    self._sock = None
                    if self._stop_event.wait(RECONNECT_DELAY):
                        break
                    continue
                self._serve(sock)
            except OSError as exc:
                logger.warning("rtty: connection error for %s: %s", self.device.name, exc)
            finally:
                try:
                    sock.close()
                except OSError:
                    pass
                self._sock = None
                with self._sessions_lock:
                    self._sessions.clear()
                # Close all active tunnels (their rtty_sock is gone).
                with self._tunnels_lock:
                    tunnels = list(self._tunnels.values())
                    self._tunnels.clear()
                for tunnel in tunnels:
                    tunnel.close()

            if self._stop_event.wait(RECONNECT_DELAY):
                break

        if self.on_closed:
            self.on_closed(self.device)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"rtty-{self.device.name}", daemon=True
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

    # -- config updates ---------------------------------------------------
    def update_token(self, token: str) -> None:
        """Update the registration token (used when the controller re-pushes
        the terminal setting with a new token). The new token takes effect on the
        next reconnect."""
        self.token = token


class _TunnelRelay:
    """Bidirectional relay between a local TCP socket and the RTTY channel.

    Created when the controller sends ``TUNNEL_ADD``. The device opens a TCP
    connection to the local target and relays data:
    - controller → ``TCPDATA``/``SSHDATA``/``HTTPSDATA`` frame → local socket
    - local socket → ``TCPDATA`` frame → controller

    The relay runs in a background thread reading from the local socket and
    forwarding to the RTTY channel. Incoming RTTY data is written to the local
    socket by the main serve loop via :meth:`send_to_local`.

    A single ``request_id`` (all-zeros) is used for ``TCPDATA`` frames from the
    device → controller direction (the controller multiplexes on ``tunnel_id``).
    """

    def __init__(
        self,
        tunnel_id: int,
        local_sock: socket.socket,
        rtty_sock,
        device_name: str,
        on_close: Callable[[int], None],
    ) -> None:
        self.tunnel_id = tunnel_id
        self.local_sock = local_sock
        self.rtty_sock = rtty_sock
        self.device_name = device_name
        self.on_close = on_close
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # request_id for device→controller TCPDATA (16 bytes, all zeros).
        self._request_id = b"\x00" * 16

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._relay, name=f"rtty-tunnel-{self.tunnel_id}", daemon=True
        )
        self._thread.start()

    def _relay(self) -> None:
        """Read from the local socket and forward to the RTTY channel."""
        self.local_sock.settimeout(1.0)
        while not self._stop_event.is_set():
            try:
                data = self.local_sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                # Local connection closed.
                break
            try:
                frame = rtty_proto.pack_tcp_data(
                    self.tunnel_id, self._request_id, data)
                self.rtty_sock.sendall(frame)
            except OSError:
                break
        logger.debug("rtty: tunnel relay id=%s ended for %s",
                     self.tunnel_id, self.device_name)
        self.on_close(self.tunnel_id)

    def send_to_local(self, data: bytes) -> None:
        """Write controller→tunnel data to the local socket."""
        if self._stop_event.is_set():
            return
        try:
            self.local_sock.sendall(data)
        except OSError:
            self.on_close(self.tunnel_id)

    def close(self) -> None:
        self._stop_event.set()
        try:
            self.local_sock.close()
        except OSError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None