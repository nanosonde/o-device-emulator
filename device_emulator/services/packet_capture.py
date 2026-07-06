"""Packet Capture client service — produces a synthetic libpcap capture and
transfers it to the controller when a ``packageCapture`` SET key is pushed.

The controller's Tools → Packet Capture feature (§11.6) pushes a
``packageCapture`` config block to the device over the management channel to
start/stop a capture. The config fields: ``operation``
(``"start"``/``"stop"``), ``nid`` (the capture session id), and
``captureInfo`` (``duration``, ``totalSize``, ``interface``, ``vlanId``,
``vlanId``, ``channel``, ``filterRules``, ``srcMac``/``destMac``/``srcPort``/
``destPort``/``srcIp``/``destIp``/``protocol``). The capture file is
transferred on port 29815 (``TRANSFER_V2_TCP_PORT``).

This service:

1. Builds a deterministic, MAC-seeded synthetic libpcap capture from the
   ``captureInfo`` parameters via ``device_emulator.protocol.pcap`` (the
   capture contains valid, Wireshark-parseable ARP/ICMP/TCP/UDP frames —
   there is no real traffic to capture).
2. Opens a TLS connection to ``controller_host:29815`` (the controller's
   file-transfer / capture channel). All other controller-facing channels use
   TLS with a vendor certificate (CN=localhost, no client cert), so the
   capture channel is assumed to as well.
3. Streams the pcap file with a simple length-prefixed framing
   (4-byte big-endian payload length + bytes). The exact 29815 transfer
    framing is only partially characterized (PROVISIONAL — see
   doc/DEVICE_PROTOCOL.md §11.6), so this is a best-effort transfer; the
   generated pcap file itself is fully valid regardless of whether the
   controller accepts the framing.

The service runs once in a background thread (it is not a long-lived
keep-alive channel like the DMP/RTTY clients): build → connect → send →
close. A ``stop`` operation cancels any in-flight transfer.

See ``doc/DEVICE_PROTOCOL.md`` §11.6 for the full protocol reference.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import ssl
import struct
import threading
from typing import Callable, Optional

from ..devices.base import Device
from ..protocol import constants
from ..protocol import pcap as pcap_mod
from ..protocol.framing import encode_frame

logger = logging.getLogger(__name__)

# How long to wait for the controller's file-transfer port before giving up.
CONNECT_TIMEOUT = 10.0
# Reconnect/transfer is single-shot; if it fails we don't retry forever.
MAX_TRANSFER_ATTEMPTS = 1
# The controller splits a download into 512KB partitions (fileSize / 524288),
# so mirror that when it doesn't give an explicit byte range.
TRANSFER_PARTITION_BYTES = 512 * 1024
# Notify subject value for file transfer — routes the notify to the controller's
# file-transfer listener.
NOTIFY_SUBJECT_FILE_TRANSFER = 6
# File-type value identifying a packet-capture file.
CAPTURE_FILE_NOTIFY_TYPE = 1


class PacketCaptureService:
    """Builds a synthetic pcap for a ``packageCapture`` "start" operation and
    transfers it to the controller on port 29815.

    The service is created by the runner when the device receives a
    ``packageCapture`` SET key with ``operation == "start"``. It runs once
    (build → transfer → exit); it is not a long-lived keep-alive channel.
    """

    def __init__(
        self,
        device: Device,
        *,
        controller_host: str,
        capture_info: Optional[dict] = None,
        nid: str = "",
        transfer_port: int = constants.TRANSFER_V2_TCP_PORT,
        use_tls: bool = True,
        on_closed: Optional[Callable[[Device], None]] = None,
    ) -> None:
        self.device = device
        self.controller_host = controller_host
        self.capture_info = capture_info or {}
        self.nid = nid
        self.transfer_port = transfer_port
        self.use_tls = use_tls
        self.on_closed = on_closed
        # The fileName the controller reassembles partitions under. Derived
        # from the device MAC + the capture session nid so it is unique per
        # capture and stable across the partition messages.
        safe_mac = device.mac.replace("-", "").replace(":", "")
        self._file_name = f"{safe_mac}_{nid or 'capture'}.pcap"

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[ssl.SSLSocket] = None
        self._last_pcap: Optional[bytes] = None

    # -- capture generation ------------------------------------------------
    def _build_pcap(self) -> bytes:
        """Build the synthetic pcap byte buffer for this device + captureInfo."""
        packets = pcap_mod.build_synthetic_packets(
            self.device, self.capture_info
        )
        return pcap_mod.to_pcap_bytes(packets)

    def _write_pcap_file(self) -> tuple[str, bytes]:
        """Also write the capture to a temp file (useful for manual inspection
        / tcpdump) and return (path, bytes)."""
        data = self._build_pcap()
        path = pcap_mod.temp_pcap_path(self.device.mac, "-" + self.nid if self.nid else "")
        try:
            with open(path, "wb") as f:
                f.write(data)
            logger.info(
                "packet capture for %s written to %s (%d bytes, %d packets)",
                self.device.name, path, len(data), _packet_count(data),
            )
        except OSError as exc:
            logger.warning("could not write pcap temp file %s: %s", path, exc)
        return path, data

    # -- transfer ----------------------------------------------------------
    def _frame_transfer_message(self, partition: int, data_b64: str, *, err_code: int = 0) -> bytes:
        """Build one ECSP FILE_TRANSFER_RESPONSE_V2 frame carrying one base64
        partition of the pcap.

        The body matches the file-transfer response shape (see
        doc/DEVICE_PROTOCOL.md §11.6): ``{fileTransfer: {errCode, fileName,
        fileType, compression, data, partition}}``.
        """
        header = {
            "mac": self.device.mac,
            "type": constants.MESSAGE_TYPE_FILE_TRANSFER_RESPONSE_V2,
            "device": self.device.device_type,
            "version": self.device.protocol_version,
            "error": 0,
            "seq": partition,
        }
        body = {
            "fileTransfer": {
                "errCode": err_code,
                "fileName": self._file_name,
                "fileType": "pcap",
                "compression": "none",
                "data": data_b64,
                "partition": partition,
            }
        }
        payload = json.dumps({"header": header, "body": body}, separators=(",", ":")).encode("utf-8")
        return encode_frame(payload)

    def _manage(self):
        manage = getattr(self.device, "manage_service", None)
        if manage is None or not getattr(manage, "_sock", None):
            return None
        return manage

    def announce_file(self) -> bool:
        """Tell the controller the capture is ready via a FILE_TRANSFER notify.

        This is the step that makes the whole flow work: the controller only
        creates its file reassembly cache (and only then requests
        partitions) once it knows the file's name/size/md5 for this capture's
        ``cmdId``. Without this notify it silently drops any partition the
        device pushes and the UI reports "Failed to capture packets".
        """
        manage = self._manage()
        if manage is None:
            logger.warning(
                "packet capture: management channel not connected for %s; "
                "cannot announce capture file", self.device.name,
            )
            return False
        data = self._last_pcap
        if data is None:
            data = self._build_pcap()
            self._last_pcap = data
        content = {
            "errCode": 0,
            "cmdId": self.nid,
            "type": CAPTURE_FILE_NOTIFY_TYPE,
            "fileInfos": [
                {
                    "fileName": self._file_name,
                    "filePath": "/tmp/" + self._file_name,
                    "fileSize": len(data),
                    "md5": hashlib.md5(data).hexdigest(),
                }
            ],
        }
        ok = manage.send_notify(NOTIFY_SUBJECT_FILE_TRANSFER, content)
        if ok:
            logger.info(
                "packet capture: announced %s (%d bytes, md5=%s) for %s",
                self._file_name, len(data),
                content["fileInfos"][0]["md5"][:8], self.device.name,
            )
        return ok

    def handle_transfer_request(self, req_body: dict) -> bool:
        """Serve one controller FILE_TRANSFER_REQUEST_V2 by replying with the
        requested byte range as a FILE_TRANSFER_RESPONSE_V2 partition."""
        manage = self._manage()
        if manage is None:
            return False
        req = req_body.get("fileTransfer") if isinstance(req_body, dict) else None
        if not isinstance(req, dict):
            req = req_body if isinstance(req_body, dict) else {}
        data = self._last_pcap
        if data is None:
            data = self._build_pcap()
            self._last_pcap = data

        partition = int(req.get("partition") or 0)
        start = req.get("startIndex")
        end = req.get("endIndex")
        if start is None:
            start = partition * TRANSFER_PARTITION_BYTES
        start = max(0, int(start))
        # endIndex is inclusive; the controller omits it for all but the last
        # partition.
        stop = len(data) if end is None else min(len(data), int(end) + 1)
        chunk = data[start:stop]

        body = {
            "fileTransfer": {
                "errCode": 0,
                "fileName": req.get("fileName") or self._file_name,
                "fileType": "pcap",
                "compression": "none",
                "data": base64.b64encode(chunk).decode("ascii"),
                "partition": partition,
            }
        }
        ok = manage.send_file_transfer_frame(body)
        logger.info(
            "packet capture: served partition %d (%d bytes) for %s -> %s",
            partition, len(chunk), self.device.name, "ok" if ok else "failed",
        )
        return ok

    # -- lifecycle ---------------------------------------------------------
    def _run(self) -> None:
        if self._stop_event.is_set():
            return
        _path, data = self._write_pcap_file()
        self._last_pcap = data
        # Real hardware captures for the requested duration before the file is
        # available; the controller's UI shows progress for that long.
        duration = float(self.capture_info.get("duration") or 0)
        if duration > 0 and self._stop_event.wait(min(duration, 300.0)):
            return
        if self._stop_event.is_set():
            return
        self.announce_file()
        if self.on_closed:
            self.on_closed(self.device)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"pcap-{self.device.name}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


def _packet_count(pcap_bytes: bytes) -> int:
    """Count the packet records in a serialized pcap buffer (global header is
    24 bytes; each record is 16 bytes + incl_len)."""
    if len(pcap_bytes) < 24:
        return 0
    offset = 24
    count = 0
    while offset + 16 <= len(pcap_bytes):
        incl_len = struct.unpack_from("<I", pcap_bytes, offset + 8)[0]
        offset += 16 + incl_len
        count += 1
    return count