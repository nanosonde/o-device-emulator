"""UDP discovery announce service (port 29810).

Confirmed behavior (see doc/DEVICE_PROTOCOL.md §4-5): an unmanaged device
sends its discovery packet to the controller's discovery port and the
controller does NOT reply over UDP - so ordinarily this service is
announce-only.

The one exception is adoption (see §8): once an operator has told the
controller to adopt the device, the controller answers the device's *next*
announce with a UDP pre-adopt reply (header.type == PRE_ADOPT_REQUEST) naming
the TLS management port. To catch that reply the service keeps a single
persistent socket (rather than an ephemeral per-announce socket) and, when an
`on_pre_adopt` callback is supplied, listens on it between announces.
"""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..devices.base import Device
from ..protocol import constants
from ..protocol.framing import encode_frame

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryServiceConfig:
    controller_host: str
    port: int = constants.DISCOVERY_UDP_PORT
    interval_seconds: float = constants.DEFAULT_ANNOUNCE_INTERVAL_SECONDS
    bind_ip: Optional[str] = None
    broadcast: bool = False


class DiscoveryService:
    """Periodically announces a single device to a controller over UDP.

    If `on_pre_adopt` is provided, the service also listens on its socket for
    the controller's pre-adopt reply and invokes the callback (once) with the
    parsed reply body. It then stops announcing, since further announces while
    the controller is adopting cause the adoption to fail (CONFIRMED, §8).
    """

    def __init__(
        self,
        device: Device,
        config: DiscoveryServiceConfig,
        on_pre_adopt: Optional[Callable[[Device, dict[str, Any]], None]] = None,
    ):
        self.device = device
        self.config = config
        self.on_pre_adopt = on_pre_adopt
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._pre_adopt_fired = False

    def _make_socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if self.config.broadcast:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if self.config.bind_ip:
            sock.bind((self.config.bind_ip, 0))
        return sock

    def _packet(self) -> bytes:
        message = self.device.build_discovery_message()
        return encode_frame(message.to_json_bytes())

    def announce_once(self) -> None:
        packet = self._packet()
        sock = self._make_socket()
        try:
            sock.sendto(packet, (self.config.controller_host, self.config.port))
            logger.debug(
                "announced %s (%s) to %s:%s",
                self.device.name,
                self.device.mac,
                self.config.controller_host,
                self.config.port,
            )
        finally:
            sock.close()

    def _handle_reply(self, data: bytes, addr: tuple) -> None:
        try:
            length = int.from_bytes(data[:4], "big")
            envelope = json.loads(data[4 : 4 + length].decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            logger.debug("ignoring undecodable UDP reply from %s: %s", addr, exc)
            return
        header = envelope.get("header", {}) or {}
        if header.get("type") == constants.MESSAGE_TYPE_PRE_ADOPT_REQUEST:
            body = envelope.get("body", {}) or {}
            logger.info(
                "received pre-adopt reply for %s (adoptPort=%s)",
                self.device.name,
                body.get("adoptPort"),
            )
            if self.on_pre_adopt and not self._pre_adopt_fired:
                self._pre_adopt_fired = True
                self.on_pre_adopt(self.device, body)

    def _run(self) -> None:
        # Announce-only path (no adoption listening): keep the original
        # simple, socket-per-announce behavior.
        if self.on_pre_adopt is None:
            while not self._stop_event.is_set():
                try:
                    self.announce_once()
                except Exception:  # noqa: BLE001 - keep the loop alive on transient errors
                    logger.exception("discovery announce failed for %s", self.device.name)
                self._stop_event.wait(self.config.interval_seconds)
            return

        # Adoption-aware path: one persistent socket that both announces and
        # listens for the controller's pre-adopt reply.
        sock = self._make_socket()
        try:
            while not self._stop_event.is_set() and not self._pre_adopt_fired:
                try:
                    sock.sendto(self._packet(), (self.config.controller_host, self.config.port))
                    logger.debug("announced %s (%s)", self.device.name, self.device.mac)
                except Exception:  # noqa: BLE001
                    logger.exception("discovery announce failed for %s", self.device.name)

                deadline = time.monotonic() + self.config.interval_seconds
                while (
                    not self._stop_event.is_set()
                    and not self._pre_adopt_fired
                    and time.monotonic() < deadline
                ):
                    sock.settimeout(min(1.0, max(0.05, deadline - time.monotonic())))
                    try:
                        data, addr = sock.recvfrom(65535)
                    except socket.timeout:
                        continue
                    except OSError as exc:
                        logger.debug("discovery recv error for %s: %s", self.device.name, exc)
                        break
                    self._handle_reply(data, addr)
        finally:
            sock.close()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"discovery-{self.device.name}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        thread = self._thread
        # The pre-adopt callback runs inside this service's own thread and may
        # ask the runner to stop it; joining self would deadlock/raise, so in
        # that case just signal and let the loop unwind.
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
            self._thread = None
