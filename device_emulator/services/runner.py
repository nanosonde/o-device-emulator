"""Orchestrates per-device services (currently: discovery announce loops)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..devices.base import Device
from .controller_client import ControllerInfoError, fetch_controller_id
from .discovery import DiscoveryService, DiscoveryServiceConfig

logger = logging.getLogger(__name__)


@dataclass
class Runner:
    controller_host: str
    https_port: int = 8043
    discovery_port: int = 29810
    discovery_interval: float = 10.0
    discovery_bind_ip: Optional[str] = None
    discovery_broadcast: bool = False

    _devices: list[Device] = field(default_factory=list)
    _services: list[DiscoveryService] = field(default_factory=list)
    _controller_id: Optional[str] = None

    @property
    def devices(self) -> list[Device]:
        return self._devices

    def add_device(self, device: Device) -> None:
        self._devices.append(device)

    def resolve_controller_id(self) -> str:
        if self._controller_id is None:
            self._controller_id = fetch_controller_id(self.controller_host, https_port=self.https_port)
            logger.info("resolved controller id=%s", self._controller_id)
        return self._controller_id

    def dry_run(self) -> list[str]:
        """Validate all devices resolve to a valid discovery message without
        starting any network services. Returns a list of human-readable
        summaries (used by `--dry-run`)."""
        try:
            controller_id = self.resolve_controller_id()
        except ControllerInfoError as exc:
            raise RuntimeError(
                f"could not reach controller at {self.controller_host}:{self.https_port} "
                f"for --dry-run validation: {exc}"
            ) from exc

        summaries = []
        for device in self._devices:
            device.controller_id = controller_id
            message = device.build_discovery_message()
            summaries.append(
                f"{device.name} ({device.device_type}, mac={device.mac}, ip={device.ip}): "
                f"{len(message.to_json_bytes())} byte discovery body OK"
            )
        return summaries

    def start(self) -> None:
        controller_id = self.resolve_controller_id()
        for device in self._devices:
            device.controller_id = controller_id
            config = DiscoveryServiceConfig(
                controller_host=self.controller_host,
                port=self.discovery_port,
                interval_seconds=self.discovery_interval,
                bind_ip=self.discovery_bind_ip,
                broadcast=self.discovery_broadcast,
            )
            service = DiscoveryService(device, config)
            service.start()
            self._services.append(service)
            logger.info("started discovery service for %s", device.name)

    def stop(self) -> None:
        for service in self._services:
            service.stop()
        self._services.clear()
