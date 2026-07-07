"""Orchestrates per-device services: discovery announce loops and, when
adoption is enabled, the TLS management channel that drives a device to
CONNECTED and keeps it online."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from ..devices.base import Device
from ..devices.topology import LinkNeighbor, TopologyNeighbors
from ..protocol import constants
from .controller_client import ControllerInfoError, fetch_controller_id
from .discovery import DiscoveryService, DiscoveryServiceConfig
from .manage import ManageService

logger = logging.getLogger(__name__)


@dataclass
class Runner:
    controller_host: str
    https_port: int = 8043
    discovery_port: int = 29810
    discovery_interval: float = 10.0
    discovery_bind_ip: Optional[str] = None
    discovery_broadcast: bool = False

    # Adoption (management channel) settings.
    adopt_enabled: bool = False
    adopt_username: str = "admin"
    adopt_password: str = "admin"
    adopt_port: int = constants.DEFAULT_ADOPT_TCP_PORT
    inform_interval: float = constants.DEFAULT_INFORM_INTERVAL_SECONDS

    _devices: list[Device] = field(default_factory=list)
    _services: list[DiscoveryService] = field(default_factory=list)
    _discovery_by_mac: dict[str, DiscoveryService] = field(default_factory=dict)
    _manage_by_mac: dict[str, ManageService] = field(default_factory=dict)
    _controller_id: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _stopped: bool = False

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
            device.controller_id = (
                constants.FACTORY_CONTROLLER_ID if self.adopt_enabled else controller_id
            )
            message = device.build_discovery_message()
            adopt_note = " (adoptable)" if self.adopt_enabled else ""
            summaries.append(
                f"{device.name} ({device.device_type}, mac={device.mac}, ip={device.ip}): "
                f"{len(message.to_json_bytes())} byte discovery body OK{adopt_note}"
            )
        return summaries

    def _make_discovery(self, device: Device) -> DiscoveryService:
        config = DiscoveryServiceConfig(
            controller_host=self.controller_host,
            port=self.discovery_port,
            interval_seconds=self.discovery_interval,
            bind_ip=self.discovery_bind_ip,
            broadcast=self.discovery_broadcast,
        )
        on_pre_adopt = self._on_pre_adopt if self.adopt_enabled else None
        return DiscoveryService(device, config, on_pre_adopt=on_pre_adopt)

    def _on_pre_adopt(self, device: Device, body: dict[str, Any]) -> None:
        """Controller answered a discovery announce with a pre-adopt reply:
        stop announcing (further announces abort adoption) and open the
        management channel."""
        with self._lock:
            discovery = self._discovery_by_mac.pop(device.mac, None)
            if discovery is not None:
                discovery.stop(timeout=0.1)
            adopt_port = int(body.get("adoptPort") or self.adopt_port)
            manage = ManageService(
                device,
                controller_host=self.controller_host,
                controller_id=self.resolve_controller_id(),
                username=self.adopt_username,
                password=self.adopt_password,
                adopt_port=adopt_port,
                inform_interval=self.inform_interval,
                on_closed=self._on_manage_closed,
            )
            self._manage_by_mac[device.mac] = manage
        logger.info("adopting %s via management channel on port %s", device.name, adopt_port)
        manage.start()

    def _on_manage_closed(self, device: Device) -> None:
        """Management channel ended: resume discovery so the device can be
        re-adopted."""
        with self._lock:
            self._manage_by_mac.pop(device.mac, None)
            if self._stopped:
                return
            device.controller_id = constants.FACTORY_CONTROLLER_ID
            discovery = self._make_discovery(device)
            self._discovery_by_mac[device.mac] = discovery
        logger.info("management channel for %s ended; resuming discovery", device.name)
        discovery.start()

    def start(self) -> None:
        self._stopped = False
        controller_id = self.resolve_controller_id()
        self._resolve_topology()
        for device in self._devices:
            device.controller_id = (
                constants.FACTORY_CONTROLLER_ID if self.adopt_enabled else controller_id
            )
            service = self._make_discovery(device)
            self._services.append(service)
            self._discovery_by_mac[device.mac] = service
            service.start()
            logger.info(
                "started discovery service for %s%s",
                device.name,
                " (adoptable)" if self.adopt_enabled else "",
            )

    def stop(self) -> None:
        self._stopped = True
        for manage in list(self._manage_by_mac.values()):
            manage.stop()
        self._manage_by_mac.clear()
        for service in list(self._discovery_by_mac.values()):
            service.stop()
        self._services.clear()
        self._discovery_by_mac.clear()

    def _resolve_topology(self) -> None:
        """Turn each device's declared ``uplink`` into concrete, bidirectional
        neighbour links (so devices can report LLDP/port/FDB/lanInfo that let
        the controller draw the topology map)."""
        by_name = {d.name: d for d in self._devices}
        downlink_counter: dict[str, int] = {}
        for device in self._devices:
            device.topology = TopologyNeighbors()
        for device in self._devices:
            if not device.uplink:
                continue
            parent = by_name.get(device.uplink)
            if parent is None:
                logger.warning(
                    "device %s declares unknown uplink %r; skipping topology link",
                    device.name,
                    device.uplink,
                )
                continue
            # Port on the parent facing this child (explicit or auto-assigned),
            # and this child's own port facing the parent.
            idx = downlink_counter.get(parent.name, 0) + 1
            downlink_counter[parent.name] = idx
            remote_port = device.uplink_port or idx
            local_port = device.local_uplink_port or 1
            device.topology.uplink = LinkNeighbor(
                mac=parent.mac,
                model=parent.identity.model,
                device_type=parent.device_type,
                local_port=local_port,
                remote_port=remote_port,
            )
            parent.topology.downlinks.append(
                LinkNeighbor(
                    mac=device.mac,
                    model=device.identity.model,
                    device_type=device.device_type,
                    local_port=remote_port,
                    remote_port=local_port,
                )
            )
