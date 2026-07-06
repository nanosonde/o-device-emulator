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
from ..devices.clients import synthesize_site_clients
from ..protocol import constants
from .controller_client import ControllerInfoError, fetch_controller_id
from .discovery import DiscoveryService, DiscoveryServiceConfig
from .manage import ManageService
from .rtty import RttyService
from .device_monitor import DeviceMonitorService
from .packet_capture import PacketCaptureService
from .transfer_channel import TransferChannelService

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
    managed_username: Optional[str] = None
    managed_password: Optional[str] = None
    adopt_port: int = constants.DEFAULT_ADOPT_TCP_PORT
    inform_interval: float = constants.DEFAULT_INFORM_INTERVAL_SECONDS

    _devices: list[Device] = field(default_factory=list)
    _services: list[DiscoveryService] = field(default_factory=list)
    _discovery_by_mac: dict[str, DiscoveryService] = field(default_factory=dict)
    _manage_by_mac: dict[str, ManageService] = field(default_factory=dict)
    _rtty_by_mac: dict[str, RttyService] = field(default_factory=dict)
    _dmp_by_mac: dict[str, DeviceMonitorService] = field(default_factory=dict)
    _pcap_by_mac: dict[str, PacketCaptureService] = field(default_factory=dict)
    _transfer_by_mac: dict[str, TransferChannelService] = field(default_factory=dict)
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
                managed_username=self.managed_username,
                managed_password=self.managed_password,
                adopt_port=adopt_port,
                inform_interval=self.inform_interval,
                on_closed=self._on_manage_closed,
                on_terminal_setting=self._on_terminal_setting,
                on_monitor_server=self._on_monitor_server,
                on_package_capture=self._on_package_capture,
                on_file_transfer_request=self._on_file_transfer_request,
            )
            manage.on_transfer_channel = self._on_transfer_channel
            self._manage_by_mac[device.mac] = manage
            device.manage_service = manage
        logger.info("adopting %s via management channel on port %s", device.name, adopt_port)
        manage.start()

    def _on_manage_closed(self, device: Device) -> None:
        """Management channel ended: resume discovery so the device can be
        re-adopted."""
        with self._lock:
            self._manage_by_mac.pop(device.mac, None)
            # Stop the RTTY client — the controller will re-push
            # terminalSetting if/when the device is re-adopted.
            rtty = self._rtty_by_mac.pop(device.mac, None)
            # Stop the device-monitor (Network Check) client too.
            dmp = self._dmp_by_mac.pop(device.mac, None)
            # Stop the file-transfer channel.
            tch = self._transfer_by_mac.pop(device.mac, None)
        if rtty is not None:
            rtty.stop()
            logger.info("stopped RTTY client for %s (management closed)", device.name)
        if dmp is not None:
            dmp.stop()
            logger.info("stopped DMP client for %s (management closed)", device.name)
        if tch is not None:
            tch.stop()
            logger.info("stopped transfer channel for %s (management closed)", device.name)
        with self._lock:
            if self._stopped:
                return
            device.controller_id = constants.FACTORY_CONTROLLER_ID
            discovery = self._make_discovery(device)
            self._discovery_by_mac[device.mac] = discovery
        logger.info("management channel for %s ended; resuming discovery", device.name)
        discovery.start()

    def _on_terminal_setting(self, device: Device, setting: dict) -> None:
        """The controller pushed a ``terminalSetting`` config. Start or stop
        the RTTY client service based on the ``enable`` flag."""
        enable = bool(setting.get("enable", False))
        with self._lock:
            existing = self._rtty_by_mac.get(device.mac)
        if enable:
            token = str(setting.get("token") or "")
            rtty_port = int(setting.get("port") or constants.RTTY_TCP_PORT)
            # The controller sends TLS config as ``SSL: {enable: bool}`` (not a
            # plain ``ssl`` boolean); fall back to the lowercase form and to
            # TLS-on if neither is present.
            ssl_cfg = setting.get("SSL")
            if isinstance(ssl_cfg, dict):
                use_tls = bool(ssl_cfg.get("enable", True))
            else:
                use_tls = bool(setting.get("ssl", True))
            heartbeat_freq = float(setting.get("heartbeatFrequency") or 10)
            if not token:
                logger.warning(
                    "terminalSetting for %s has no token; not starting RTTY",
                    device.name,
                )
                return
            if existing is not None:
                # Already running — update the token for next reconnect
                existing.update_token(token)
                logger.info("RTTY client already running for %s; token updated", device.name)
                return
            rtty = RttyService(
                device,
                controller_host=self.controller_host,
                token=token,
                rtty_port=rtty_port,
                use_tls=use_tls,
                heartbeat_interval=heartbeat_freq,
            )
            with self._lock:
                self._rtty_by_mac[device.mac] = rtty
            device.rtty_service = rtty
            rtty.start()
            logger.info(
                "started RTTY client for %s -> %s:%s (tls=%s)",
                device.name, self.controller_host, rtty_port, use_tls,
            )
        else:
            # terminal disabled — stop the RTTY client if running
            if existing is not None:
                existing.stop()
                with self._lock:
                    self._rtty_by_mac.pop(device.mac, None)
                device.rtty_service = None
                logger.info("stopped RTTY client for %s (terminal disabled)", device.name)

    def _on_monitor_server(self, device: Device, setting: dict) -> None:
        """The controller pushed a ``monitorServer`` config. Start (or stop)
        the device-monitor (DMP) client so Tools → Network Check probes are
        served. Mirrors ``_on_terminal_setting``: a present ``token`` enables
        the channel; an empty/disabled config stops it."""
        token = str(setting.get("token") or "")
        with self._lock:
            existing = self._dmp_by_mac.get(device.mac)
        if not token:
            # No token → monitoring disabled; stop any running DMP client.
            if existing is not None:
                existing.stop()
                with self._lock:
                    self._dmp_by_mac.pop(device.mac, None)
                device.dmp_service = None
                logger.info("stopped DMP client for %s (monitorServer disabled)", device.name)
            return
        monitor_port = int(setting.get("port") or constants.DEVICE_MONITOR_TCP_PORT)
        # ``protocol`` is typically "tls" or "tcp"; default to TLS (all
        # controller-facing channels use TLS with a vendor cert).
        protocol = str(setting.get("protocol") or "tls").lower()
        use_tls = protocol in ("tls", "ssl", "tlsv1", "tlsv1.2", "tlsv1.3")
        path = str(setting.get("path") or "/")
        if existing is not None:
            # Already running — restart with the new token/port so the change
            # takes effect immediately (the DMP client has no update_token).
            existing.stop()
            with self._lock:
                self._dmp_by_mac.pop(device.mac, None)
            logger.info("restarting DMP client for %s (config updated)", device.name)
        dmp = DeviceMonitorService(
            device,
            controller_host=self.controller_host,
            token=token,
            monitor_port=monitor_port,
            use_tls=use_tls,
            path=path,
        )
        with self._lock:
            self._dmp_by_mac[device.mac] = dmp
        device.dmp_service = dmp
        dmp.start()
        logger.info(
            "started DMP client for %s -> %s:%s (tls=%s, path=%s)",
            device.name, self.controller_host, monitor_port, use_tls, path,
        )

    def _on_package_capture(self, device: Device, setting: dict) -> None:
        """The controller pushed a ``packageCapture`` config. For a ``start``
        operation, build a synthetic pcap and transfer it on port 29815. For
        ``stop``, cancel any in-flight capture. See doc §11.6."""
        operation = str(setting.get("operation") or "").lower()
        capture_info = setting.get("captureInfo") or {}
        nid = str(setting.get("nid") or "")
        if operation == "start":
            # Stop any prior in-flight capture for this device first.
            with self._lock:
                existing = self._pcap_by_mac.pop(device.mac, None)
            if existing is not None:
                existing.stop()
                device.packet_capture_service = None
            svc = PacketCaptureService(
                device,
                controller_host=self.controller_host,
                capture_info=capture_info,
                nid=nid,
            )
            with self._lock:
                self._pcap_by_mac[device.mac] = svc
            device.packet_capture_service = svc
            svc.start()
            logger.info(
                "started packet capture for %s (nid=%s, duration=%s, totalSize=%s)",
                device.name, nid, capture_info.get("duration", ""),
                capture_info.get("totalSize", ""),
            )
        elif operation == "stop":
            with self._lock:
                existing = self._pcap_by_mac.pop(device.mac, None)
            if existing is not None:
                existing.stop()
                device.packet_capture_service = None
                logger.info("stopped packet capture for %s", device.name)
        else:
            logger.debug(
                "packageCapture unknown operation=%s for %s", operation, device.name
            )

    def _on_file_transfer_request(self, device: Device, req_body: dict) -> None:
        """The controller is requesting a partition of the capture file."""
        with self._lock:
            svc = self._pcap_by_mac.get(device.mac)
        if svc is None:
            logger.warning(
                "file-transfer request for %s but no capture is pending", device.name
            )
            return
        svc.handle_transfer_request(req_body)

    def _on_transfer_channel(self, device: Device, setting: dict) -> None:
        """The controller pushed a ``transferChannel`` config. Connect to 29815
        **synchronously** — the controller's download flow pushes the SET and
        checks the transfer channel cache in the same HTTP request, so the
        channel must be established before the SET response is processed."""
        token = str(setting.get("token") or "")
        with self._lock:
            existing = self._transfer_by_mac.get(device.mac)
        if not token:
            if existing is not None:
                existing.stop()
                with self._lock:
                    self._transfer_by_mac.pop(device.mac, None)
                device.transfer_channel_service = None
                logger.info("stopped transfer channel for %s", device.name)
            return
        port = int(setting.get("port") or constants.TRANSFER_V2_TCP_PORT)
        if existing is not None:
            existing.stop()
            with self._lock:
                self._transfer_by_mac.pop(device.mac, None)
        svc = TransferChannelService(
            device,
            controller_host=self.controller_host,
            controller_id=self.resolve_controller_id(),
            token=token,
            transfer_port=port,
            username=self.adopt_username,
            password=self.adopt_password,
            on_file_request=self._on_file_request,
        )
        if svc.connect_and_handshake():
            with self._lock:
                self._transfer_by_mac[device.mac] = svc
            device.transfer_channel_service = svc
            svc.start_serve_loop()
            logger.info("transfer channel established for %s -> %s:%s", device.name, self.controller_host, port)
        else:
            logger.warning("transfer channel handshake failed for %s", device.name)

    def _on_file_request(self, device: Device, req_body: dict) -> bool:
        """Serve a FILE_TRANSFER_REQUEST_V2 on the transfer channel."""
        with self._lock:
            svc = self._pcap_by_mac.get(device.mac)
        if svc is None:
            logger.warning("file request for %s but no capture is pending", device.name)
            return False
        return svc.handle_transfer_request(req_body)

    def start(self) -> None:
        self._stopped = False
        controller_id = self.resolve_controller_id()
        self._resolve_topology()
        synthesize_site_clients(self._devices)
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
        for pcap in list(self._pcap_by_mac.values()):
            pcap.stop()
        self._pcap_by_mac.clear()
        for tch in list(self._transfer_by_mac.values()):
            tch.stop()
        self._transfer_by_mac.clear()
        for dmp in list(self._dmp_by_mac.values()):
            dmp.stop()
        self._dmp_by_mac.clear()
        for rtty in list(self._rtty_by_mac.values()):
            rtty.stop()
        self._rtty_by_mac.clear()
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
