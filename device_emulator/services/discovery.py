"""UDP discovery announce service (port 29810).

Confirmed behavior (see doc/DEVICE_PROTOCOL.md §4-5): a device sends its
discovery packet to the controller's discovery port; the controller does
NOT reply over UDP. So this service is announce-only - there is nothing to
listen for in response.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass
from typing import Optional

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
    """Periodically announces a single device to a controller over UDP."""

    def __init__(self, device: Device, config: DiscoveryServiceConfig):
        self.device = device
        self.config = config
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _make_socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if self.config.broadcast:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if self.config.bind_ip:
            sock.bind((self.config.bind_ip, 0))
        return sock

    def announce_once(self) -> None:
        message = self.device.build_discovery_message()
        packet = encode_frame(message.to_json_bytes())
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

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.announce_once()
            except Exception:  # noqa: BLE001 - keep the loop alive on transient errors
                logger.exception("discovery announce failed for %s", self.device.name)
            self._stop_event.wait(self.config.interval_seconds)

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
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
