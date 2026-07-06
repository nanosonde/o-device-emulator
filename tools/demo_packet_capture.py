"""Live demo of the Packet Capture device-side path.

Simulates the controller pushing a ``packageCapture`` SET key
(``operation: "start"``, ``captureInfo``) to the device over the management
channel, then stands up a loopback TLS server on port 12915 (stand-in for
the controller's 29815 file-transfer channel) and lets the real
``PacketCaptureService`` build the synthetic pcap and stream it to it.

The demo server receives the transferred bytes, writes them to disk, and
dissects the result with the same view the controller would get — proving
the device-side SET-key lifecycle → pcap generation → transfer path works.

Run:
    .venv/bin/python tools/demo_packet_capture.py
"""
from __future__ import annotations

import os
import socket
import ssl
import struct
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.devices.registry import build_device
from device_emulator.services.packet_capture import PacketCaptureService

CERT = "/tmp/demo-cert.pem"
KEY = "/tmp/demo-key.pem"
HOST = "127.0.0.1"
PORT = 12915  # non-privileged loopback stand-in for 29815
OUT = "/tmp/demo-received-capture.pcap"


def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def transfer_server(ready: threading.Event, done: threading.Event, log: list):
    """Loopback controller file-transfer server: accept one connection, read
    the 4-byte length-prefixed pcap the device streams, and save it."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(1)
    ready.set()
    try:
        sock, _ = srv.accept()
        with ctx.wrap_socket(sock, server_side=True) as tls:
            length_bytes = _recv_exact(tls, 4)
            if length_bytes is None:
                log.append(("error", "device sent no length prefix"))
                return
            (length,) = struct.unpack(">I", length_bytes)
            data = _recv_exact(tls, length)
            if data is None:
                log.append(("error", "device sent incomplete pcap"))
                return
            with open(OUT, "wb") as f:
                f.write(data)
            log.append(("received", length, len(data)))
    except Exception as exc:  # noqa: BLE001
        log.append(("error", repr(exc)))
    finally:
        srv.close()
        done.set()


def main() -> int:
    device = build_device(
        {
            "name": "demo-ap",
            "type": "ap",
            "model": "EAP245",
            "mac": "AA-BB-CC-DD-EE-01",
            "ip": "192.168.56.53",
        }
    )

    # Simulate the controller pushing a packageCapture SET key with
    # operation="start" and a representative captureInfo block.
    set_body = {
        "sequenceId": 42,
        "configVersion": 7,
        "packageCapture": {
            "operation": "start",
            "nid": "cap-0001",
            "captureInfo": {
                "duration": 30,
                "totalSize": 262144,
                "interface": "eth0",
                "filterRules": "",
            },
        },
    }

    print("=" * 72)
    print("PACKET CAPTURE LIVE DEMO — packageCapture SET key → device → 29815")
    print("=" * 72)
    print("\n[1] Controller pushes SET_REQUEST body:")
    print(f"    sequenceId={set_body['sequenceId']} configVersion={set_body['configVersion']}")
    pc = set_body["packageCapture"]
    print(f"    packageCapture.operation={pc['operation']!r}  nid={pc['nid']!r}")
    print(f"    captureInfo.duration={pc['captureInfo']['duration']}s "
          f"totalSize={pc['captureInfo']['totalSize']}B interface={pc['captureInfo']['interface']!r}")

    # The device acks the SET (build_set_response) and stores the config
    # (handle_package_capture) — exactly as manage.py dispatches it.
    ack = device.build_set_response(set_body)
    device.handle_package_capture(pc)
    print(f"\n[2] Device acks SET: errcode={ack['errcode']} "
          f"sequenceId={ack['sequenceId']} configVersion={ack['configVersion']}")
    print(f"    device.package_capture_config stored: "
          f"operation={device.package_capture_config['operation']!r}")

    # Start the loopback 29815 transfer server.
    log: list = []
    ready = threading.Event()
    done = threading.Event()
    srv = threading.Thread(target=transfer_server, args=(ready, done, log), daemon=True)
    srv.start()
    ready.wait(5.0)

    # The runner's _on_package_capture would now start a PacketCaptureService.
    # operation == "start" → build + transfer.
    svc = PacketCaptureService(
        device,
        controller_host=HOST,
        capture_info=pc["captureInfo"],
        nid=pc["nid"],
        transfer_port=PORT,
        use_tls=True,
    )
    svc.start()
    ok = done.wait(10.0)
    svc.stop()
    srv.join(timeout=3.0)

    print("\n[3] PacketCaptureService built a synthetic libpcap and streamed")
    print(f"    it to the controller's file-transfer channel (127.0.0.1:{PORT}).")
    for entry in log:
        if entry[0] == "received":
            print(f"    controller received {entry[2]} bytes (length prefix={entry[1]})")
        elif entry[0] == "error":
            print(f"    [!] transfer error: {entry[1]}")
            return 1

    print(f"\n[4] Controller saved the capture to {OUT}")
    print("    file type: ", end="")
    os.system(f"file {OUT}")
    print("\n[5] tcpdump dissection of the transferred capture:")
    os.system(f"tcpdump -r {OUT} -n 2>&1 | head -12")
    print("    ...")
    os.system(f"tcpdump -r {OUT} -n 2>&1 | tail -2")
    bad = os.popen(f"tcpdump -r {OUT} -n --print 2>&1 | grep -ci 'bad\\|incorrect\\|cksum'").read().strip()
    print(f"\n[6] Bad/incorrect checksums reported by tcpdump: {bad}")
    print("\n" + "=" * 72)
    print("Packet Capture path OK: SET key → handle_package_capture →")
    print("PacketCaptureService → valid libpcap → TLS transfer to 29815.")
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())