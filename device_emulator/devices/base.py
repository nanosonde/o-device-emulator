"""Base class for emulated network devices.

Each device knows how to build its own discovery announcement (the one
protocol phase confirmed against a live controller - see
doc/DEVICE_PROTOCOL.md). Adoption/inform (TCP channels) are not yet
confirmed; devices expose extension points for that but the daemon's
supported behavior today is discovery only.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..protocol import constants
from ..protocol.messages import DeviceMessage, MessageHeader
from .topology import TopologyNeighbors

logger = logging.getLogger(__name__)


def _normalize_mac(mac: str) -> str:
    """Normalize a MAC address to the hyphenated uppercase form seen on the
    wire in live testing (e.g. "AA-BB-CC-DD-EE-FF")."""
    cleaned = mac.replace(":", "-").replace(".", "-").upper()
    return cleaned


def format_uptime(seconds: int) -> str:
    """Format an uptime as "<N> days HH:MM:SS" (the form switches and gateways
    report in their management-channel device info)."""
    days, rem = divmod(max(0, seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{days} days {hours:02d}:{minutes:02d}:{secs:02d}"


@dataclass
class DeviceIdentity:
    name: str
    mac: str
    model: str
    model_version: str = "1.0"
    firmware_version: str = "1.0.0 Build 20240101 Rel.12345"
    hardware_version: str = "1.0"


@dataclass
class Device:
    """Base class for an emulated network device.

    Subclasses (EapDevice, SwitchDevice, GatewayDevice) set `device_type` and
    implement `build_discovery_body()`.
    """

    identity: DeviceIdentity
    ip: str
    device_type: str = field(init=False, default="")
    # ECSP protocol version advertised in header.version. The controller
    # classifies this per device type; subclasses override it (access points
    # use 2.3.0, switches/gateways use 2.2.0).
    protocol_version: str = field(init=False, default=constants.PROTOCOL_VERSION)
    controller_id: Optional[str] = None
    uptime_start: float = field(default_factory=time.time)
    country_code: int = 0

    # Topology wiring (optional). ``uplink``/``uplink_port``/``local_uplink_port``
    # come from config; ``topology`` is resolved by the runner into the concrete
    # neighbour set used to report LLDP/port/FDB/lanInfo (see devices/topology.py).
    uplink: Optional[str] = None
    uplink_port: Optional[int] = None
    local_uplink_port: Optional[int] = None
    topology: TopologyNeighbors = field(init=False, default_factory=TopologyNeighbors)

    # Synthetic connected clients this device reports in its INFORM (populated
    # by the runner from a shared site roster; see devices/clients.py). The
    # gateway also fills ``dhcp_leases`` with the aggregate of all site clients.
    reported_clients: list[Any] = field(init=False, default_factory=list)
    dhcp_leases: list[Any] = field(init=False, default_factory=list)

    # RTTY (terminal) support. The controller pushes a ``terminalSetting``
    # config via SET_REQUEST; the runner starts/stops the RTTY client service
    # based on its ``enable`` flag. See doc/DEVICE_PROTOCOL.md §10.
    terminal_setting: dict[str, Any] = field(init=False, default_factory=dict)
    rtty_service: Any = None  # set by the runner (RttyService instance)

    # The management-channel service (set by the runner). PacketCaptureService
    # uses it to upload the capture file on the live management socket.
    manage_service: Any = None

    # Device-Monitor (Network Check) support. The controller pushes a
    # ``monitorServer`` config via SET_REQUEST; the runner starts/stops the
    # device-monitor (DMP) client service so Tools → Network Check probes are
    # served. See doc/DEVICE_PROTOCOL.md §11.
    monitor_server_config: dict[str, Any] = field(init=False, default_factory=dict)
    dmp_service: Any = None  # set by the runner (DeviceMonitorService instance)

    # Packet Capture support. The controller pushes a ``packageCapture``
    # config via SET_REQUEST to start/stop a packet capture; the runner starts
    # the capture/transfer service for a ``start`` operation. See
    # doc/DEVICE_PROTOCOL.md §11.6.
    package_capture_config: dict[str, Any] = field(init=False, default_factory=dict)
    packet_capture_service: Any = None  # set by the runner

    # File-transfer channel. The controller pushes a ``transferChannel`` config
    # via SET_REQUEST to tell the device to open a TLS connection to port 29815
    # (the transfer server); the runner starts/stops the transfer channel
    # service. The controller sends FILE_TRANSFER_REQUEST_V2 on this channel
    # to download capture/backup files.
    transfer_channel_config: dict[str, Any] = field(init=False, default_factory=dict)
    transfer_channel_service: Any = None  # set by the runner

    @property
    def mac(self) -> str:
        return _normalize_mac(self.identity.mac)

    @property
    def name(self) -> str:
        return self.identity.name

    @property
    def uptime_seconds(self) -> int:
        return max(0, int(time.time() - self.uptime_start))

    def build_discovery_body(self) -> dict[str, Any]:
        raise NotImplementedError

    def manage_device_info(self) -> dict[str, Any]:
        """The ``deviceInfo`` object sent over the management channel during
        and after adoption (negotiation + INFORM heartbeats).

        The shape is device-type-specific (access points use a long-name field
        set; switches/gateways use short names), so concrete device classes
        implement it.
        """
        raise NotImplementedError

    def manage_components_v2(self) -> dict[str, str]:
        """The component manifest ({name: version}) reported during
        negotiation. The controller treats an empty manifest as incompatible
        (and shows a warning), so subclasses that support adoption return a
        realistic, non-empty set. Empty by default.
        """
        return {}

    def manage_dev_cap(self) -> dict[str, Any]:
        """Device capability flags reported in the negotiation body's
        ``devCap`` section. Devices that support the controller's
        Tools → Terminal (RTTY) advertise ``{"supportTerminal": True}`` so
        the controller's terminal device picker includes them. Subclasses
        may add additional capability flags. Empty by default; the
        ``WiredDevice`` base and AP both override this to enable terminal.
        """
        return {}

    def build_manage_pre_connect_body(
        self, controller_id: str, *, rebuild: bool = False
    ) -> dict[str, Any]:
        """Build the type-specific V2 management pre-connect body."""
        from ..protocol import adoption

        body = self.build_discovery_body()
        controller_setting = body.get("controllerSetting")
        if isinstance(controller_setting, dict):
            controller_setting["controllerId"] = controller_id
        controller = body.get("controller")
        if isinstance(controller, dict):
            controller["id"] = controller_id
        body.update(adoption.build_pre_connect_body(rebuild=int(rebuild)))
        return body

    def manage_inform_extra(self) -> dict[str, Any]:
        """Extra keyed sections merged into the periodic INFORM body (on top of
        ``deviceInfo``/``configVersion``). Wired devices use this to report the
        ``port`` link status and ``lldp`` neighbour table that drive the
        controller's topology map. Empty by default.
        """
        return {}

    def manage_inform_body(self) -> dict[str, Any]:
        """Build the full periodic INFORM body. The default mirrors the
        confirmed AP/switch/gateway shape: ``{deviceInfo, configVersion}`` plus
        the per-type ``manage_inform_extra()`` sections. Device types whose
        INFORM ``deviceInfo`` differs from their negotiation ``deviceInfo``
        (notably the OLT, whose inform uses a different field set than the
        adoption body) override this to supply the correct shape. See
        doc/DEVICE_PROTOCOL.md §7.7/§7.9.
        """
        from ..protocol import adoption

        body = adoption.build_inform_body(self.manage_device_info())
        body.update(self.manage_inform_extra())
        return body

    def build_set_response(self, req_body: dict[str, Any]) -> dict[str, Any]:
        """Acknowledge a SET_REQUEST (config push). The controller requires the
        device to echo the ``sequenceId`` and the pushed ``configVersion`` with
        ``errcode`` 0 so it records the config as applied; an empty body makes
        the controller treat the sync as failed and forget the device. The
        default ack is type-agnostic and sufficient to keep the device online;
        subclasses may add per-feature ack sections."""
        resp: dict[str, Any] = {"errcode": 0}
        if "sequenceId" in req_body:
            resp["sequenceId"] = req_body["sequenceId"]
        if "configVersion" in req_body:
            resp["configVersion"] = req_body["configVersion"]
        # The controller expects a per-key ack object for some SET keys.
        # Without it the controller treats the config as not-applied and
        # reports the feature as failed (e.g. Packet Capture shows "No device
        # response"). ``packageCapture`` maps to a per-key ack with a single
        # ``errCode`` integer (JSON key is ``packageCapture``; see
        # doc/DEVICE_PROTOCOL.md §11.6). Ack with errCode 0 (success) so the
        # controller records the capture start/stop as accepted.
        if isinstance(req_body.get("packageCapture"), dict):
            resp["packageCapture"] = {"errCode": 0}
        return resp

    def handle_terminal_setting(self, setting: dict[str, Any]) -> None:
        """Process a ``terminalSetting`` config push from the controller.

        Called by the management service when a SET_REQUEST body contains a
        ``terminalSetting`` key. Stores the setting and starts/stops the RTTY
        client service based on the ``enable`` flag. The ``rtty_service``
        attribute is managed by the runner, which wires the actual
        ``RttyService`` lifecycle.
        """
        self.terminal_setting = dict(setting)
        enable = bool(setting.get("enable", False))
        if enable:
            logger.info(
                "terminal enabled for %s: token=%s port=%s ssl=%s",
                self.name,
                setting.get("token", "")[:8] + "...",
                setting.get("port", 29816),
                setting.get("ssl", True),
            )
        else:
            logger.info("terminal disabled for %s", self.name)

    def handle_monitor_server(self, setting: dict[str, Any]) -> None:
        """Process a ``monitorServer`` config push from the controller.

        Called by the management service when a SET_REQUEST body contains a
        ``monitorServer`` key. Stores the setting; the ``dmp_service``
        attribute is managed by the runner, which wires the actual
        ``DeviceMonitorService`` lifecycle (start/stop the DMP client based on
        whether a token is present). See doc/DEVICE_PROTOCOL.md §11.5.
        """
        self.monitor_server_config = dict(setting)
        token = str(setting.get("token") or "")
        if token:
            logger.info(
                "monitorServer enabled for %s: token=%s port=%s protocol=%s",
                self.name,
                token[:8] + "...",
                setting.get("port", 29817),
                setting.get("protocol", "tls"),
            )
        else:
            logger.info("monitorServer disabled for %s", self.name)

    def handle_package_capture(self, setting: dict[str, Any]) -> None:
        """Process a ``packageCapture`` config push from the controller.

        Called by the management service when a SET_REQUEST body contains a
        ``packageCapture`` key. Stores the setting; the runner wires the
        actual ``PacketCaptureService`` lifecycle based on the ``operation``
        field (``"start"``/``"stop"``). See doc/DEVICE_PROTOCOL.md §11.6.
        """
        self.package_capture_config = dict(setting)
        operation = str(setting.get("operation") or "").lower()
        if operation == "start":
            cap = setting.get("captureInfo") or {}
            logger.info(
                "packageCapture start for %s: nid=%s duration=%s totalSize=%s",
                self.name,
                setting.get("nid", ""),
                cap.get("duration", ""),
                cap.get("totalSize", ""),
            )
        elif operation == "stop":
            logger.info("packageCapture stop for %s", self.name)
        else:
            logger.debug("packageCapture unknown operation=%s for %s", operation, self.name)

    def handle_transfer_channel(self, setting: dict[str, Any]) -> None:
        """Process a ``transferChannel`` config push from the controller.

        The controller pushes this to tell the device to open a file-transfer
        channel on port 29815 (analogous to ``monitorServer`` for DMP and
        ``terminalSetting`` for RTTY). Stores the config; the runner wires the
        ``TransferChannelService`` lifecycle.
        """
        self.transfer_channel_config = dict(setting)
        token = str(setting.get("token") or "")
        if token:
            logger.info(
                "transferChannel enabled for %s: port=%s token=%s",
                self.name, setting.get("port", 29815), token[:8] + "...",
            )
        else:
            logger.info("transferChannel disabled for %s", self.name)

    def build_get_response(self, req_body: dict[str, Any]) -> dict[str, Any]:
        """Respond to a GET_REQUEST (on-demand config/state query). The default
        is an empty ack (``sequenceId`` + ``errcode`` 0); subclasses override
        this to populate the per-feature response bodies the controller's
        detail-page tabs query."""
        resp: dict[str, Any] = {"errcode": 0}
        if "sequenceId" in req_body:
            resp["sequenceId"] = req_body["sequenceId"]
        return resp

    def build_manage_negotiation_body(self, controller_id: str) -> dict[str, Any]:
        """The DEVICE_NEGOTIATION body sent over the management channel.

        This default is the access-point ("wireless") envelope: the device
        info, component manifest, and capability fields. ``EapDevice`` fills
        ``channelInfo`` and ``radioCap`` with its per-radio capabilities;
        wired devices override the envelope with their own descriptor - see
        ``WiredDevice``.
        """
        from ..protocol import adoption

        return adoption.build_negotiation_body(
            self.manage_device_info(),
            controller_id,
            country_code=self.country_code,
            components_v2=self.manage_components_v2(),
            dev_cap=self.manage_dev_cap(),
        )

    def build_discovery_message(self) -> DeviceMessage:
        if not self.controller_id:
            raise ValueError(
                f"device {self.name!r} has no controller_id set; "
                "fetch it from the controller (GET /api/info) before announcing"
            )
        header = MessageHeader(
            mac=self.mac,
            type=constants.MESSAGE_TYPE_DISCOVERY,
            device=self.device_type,
            version=self.protocol_version,
        )
        body = self.build_discovery_body()
        return DeviceMessage(header=header, body=body)

    def to_state_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mac": self.mac,
            "model": self.identity.model,
            "device_type": self.device_type,
            "ip": self.ip,
            "uptime_start": self.uptime_start,
        }
