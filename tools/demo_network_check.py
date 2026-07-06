"""Live demo of the Network Check (DMP) device-side channel.

Boots a tiny loopback TLS server that mimics the controller's device-monitor
server (port 29817), starts the emulator's real DeviceMonitorService against
it, and has the "controller" send a /ping and /traceroute probe. The device's
synthetic probe responses are printed to prove the round-trip works
end-to-end (TLS -> ECSP framing -> protobuf register -> probe -> JSON
response -> decode).

Run:
    .venv/bin/python tools/demo_network_check.py
"""
from __future__ import annotations

import json
import socket
import ssl
import threading
import time

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.devices.registry import build_device
from device_emulator.protocol import device_monitor as dmp
from device_emulator.services.device_monitor import DeviceMonitorService

CERT = "/tmp/demo-cert.pem"
KEY = "/tmp/demo-key.pem"
HOST = "127.0.0.1"
PORT = 12917  # non-privileged loopback stand-in for 29817


def _make_device():
    return build_device(
        {
            "name": "demo-ap",
            "type": "ap",
            "model": "EAP245",
            "mac": "AA-BB-CC-DD-EE-01",
            "ip": "192.168.56.53",
        }
    )


def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def controller_server(device, token: str, ready: threading.Event, done: threading.Event, log: list):
    """Loopback controller: accept one device connection, validate its register,
    then send a ping and a traceroute probe and capture the responses."""
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
            # 1. Read the device's REGISTER message.
            msg = dmp.read_ecsp_packet(tls)
            assert msg is not None, "device sent no register"
            log.append(("register", msg.header.mac.hex(":"), msg.header.token.decode(), msg.header.path))
            # Validate token (the controller verifies this server-side).
            assert msg.header.token.decode() == token, "token mismatch"
            assert msg.header.mac == bytes(int(o, 16) for o in device.mac.split("-")), "mac mismatch"

            # Send an explicit register ACK (the real controller does this;
            # the device's _register consumes the first inbound message as the
            # register reply, so the probes must come AFTER it, not instead of
            # it).
            ack = dmp.MonitorMessage(
                header=dmp.MonitorMessageHeader(
                    mac=msg.header.mac,
                    token=msg.header.token,
                    path="/",
                    version="1.0",
                    msg_type=dmp.MSG_EMPTY,
                    seq=0,
                    error_code=0,
                    epoch_ms=int(time.time() * 1000),
                ),
                data=b"",
            )
            tls.sendall(dmp.pack_ecsp_packet(ack.encode()))

            # 2. Send a /ping probe and read the response.
            probe = dmp.MonitorMessage(
                header=dmp.MonitorMessageHeader(
                    mac=msg.header.mac,
                    token=msg.header.token,
                    path="/ping",
                    version="1.0",
                    msg_type=dmp.MSG_EMPTY,
                    seq=1001,
                    need_reply=True,
                    epoch_ms=int(time.time() * 1000),
                ),
                data=json.dumps({"target": "8.8.8.8"}).encode(),
            )
            tls.sendall(dmp.pack_ecsp_packet(probe.encode()))
            resp = dmp.read_ecsp_packet(tls)
            ping_result = json.loads(resp.data.decode()) if resp and resp.data else {}
            log.append(("ping_response", ping_result))

            # 3. Send a /traceroute probe and read the response.
            probe2 = dmp.MonitorMessage(
                header=dmp.MonitorMessageHeader(
                    mac=msg.header.mac,
                    token=msg.header.token,
                    path="/traceroute",
                    version="1.0",
                    msg_type=dmp.MSG_EMPTY,
                    seq=1002,
                    need_reply=True,
                    epoch_ms=int(time.time() * 1000),
                ),
                data=json.dumps({"target": "1.1.1.1"}).encode(),
            )
            tls.sendall(dmp.pack_ecsp_packet(probe2.encode()))
            resp2 = dmp.read_ecsp_packet(tls)
            trace_result = json.loads(resp2.data.decode()) if resp2 and resp2.data else {}
            log.append(("traceroute_response", trace_result))
    except Exception as exc:  # noqa: BLE001
        log.append(("error", repr(exc)))
    finally:
        srv.close()
        done.set()


def main() -> int:
    device = _make_device()
    token = "demo-token-12345"

    log: list = []
    ready = threading.Event()
    done = threading.Event()
    srv_thread = threading.Thread(
        target=controller_server, args=(device, token, ready, done, log), daemon=True
    )
    srv_thread.start()
    ready.wait(5.0)

    # Start the real emulator DeviceMonitorService against the loopback server.
    svc = DeviceMonitorService(
        device,
        controller_host=HOST,
        token=token,
        monitor_port=PORT,
        use_tls=True,
        path="/",
        heartbeat_interval=30.0,
    )
    svc.start()

    # Wait for the controller to finish its probe round-trip.
    done.wait(10.0)
    svc.stop()
    srv_thread.join(timeout=3.0)

    print("=" * 72)
    print("NETWORK CHECK (DMP) LIVE DEMO — controller ↔ emulated device")
    print("=" * 72)
    for entry in log:
        kind = entry[0]
        if kind == "register":
            _, mac, tok, path = entry
            print("\n[1] REGISTER received from device")
            print(f"    mac  = {mac}  (matches device {device.mac})")
            print(f"    token= {tok!r}  (matches pushed token)")
            print(f"    path = {path!r}")
        elif kind == "ping_response":
            print("\n[2] /ping probe → device replied with synthetic ping result:")
            r = entry[1]
            print(f"    target={r.get('target')}  status={r.get('status')}")
            print(f"    sent={r.get('packetsSent')}  recv={r.get('packetsReceived')}  loss={r.get('lossRate')}")
            print(f"    rtts={r.get('rtts')}  min/avg/max={r.get('minRtt')}/{r.get('avgRtt')}/{r.get('maxRtt')}")
        elif kind == "traceroute_response":
            print("\n[3] /traceroute probe → device replied with synthetic traceroute:")
            r = entry[1]
            print(f"    target={r.get('target')}  status={r.get('status')}  hops={r.get('hopCount')}")
            for hop in r.get("hops", []):
                print(f"      hop {hop['hop']:>2}  {hop['ip']:<15}  rtts={hop['rtts']}")
        elif kind == "error":
            print(f"\n[!] error: {entry[1]}")
            return 1
    print("\n" + "=" * 72)
    print("Round-trip OK: TLS + ECSP + protobuf register + probe + JSON response.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())