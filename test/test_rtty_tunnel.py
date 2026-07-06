"""Tests for the RTTY reverse-tunnel TCP forwarding.

Verifies that TUNNEL_ADD opens a local TCP connection and relays data
bidirectionally, and TUNNEL_DELETE closes it. Uses a local echo server as the
tunnel target so no external service is needed.
"""
from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_emulator.protocol import rtty as rtty_proto


def _start_echo_server():
    """Start a local TCP echo server that returns received data. Returns
    (host, port, stop_event, thread)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    stop_event = threading.Event()

    def _serve():
        sock.settimeout(0.5)
        while not stop_event.is_set():
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.settimeout(0.5)
            while not stop_event.is_set():
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                try:
                    conn.sendall(data)
                except OSError:
                    break
            conn.close()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return "127.0.0.1", port, stop_event, thread, sock


def test_tunnel_relay_forwards_data():
    """The _TunnelRelay forwards data from the local socket to a mock RTTY
    socket and vice versa."""
    from device_emulator.services.rtty import _TunnelRelay

    # Start an echo server as the tunnel target.
    host, port, stop_event, srv_thread, srv_sock = _start_echo_server()
    try:
        # Create a pair of connected sockets to simulate the RTTY channel.
        mock_a, mock_b = socket.socketpair()

        # The _TunnelRelay uses the local socket (connecting to echo server)
        # and the RTTY socket (mock_a) for sending frames.
        local_sock = socket.create_connection((host, port), timeout=2.0)
        cleaned_up = []
        tunnel = _TunnelRelay(
            tunnel_id=1,
            local_sock=local_sock,
            rtty_sock=mock_a,
            device_name="test",
            on_close=lambda tid: cleaned_up.append(tid),
        )
        tunnel.start()
        try:
            # Send data via send_to_local (controller → local socket).
            tunnel.send_to_local(b"hello echo\n")
            time.sleep(0.3)
            # The echo server echoes it back; the relay reads it and sends a
            # TCPDATA frame on the RTTY socket (mock_a). Read from mock_b.
            mock_b.settimeout(2.0)
            frame = rtty_proto.read_frame(mock_b)
            assert frame is not None
            assert frame.type == rtty_proto.TCPDATA
            tunnel_id, request_id, data = rtty_proto.parse_tcp_data(frame.payload)
            assert tunnel_id == 1
            assert data == b"hello echo\n"
        finally:
            tunnel.close()
            mock_a.close()
            mock_b.close()
            local_sock.close()
    finally:
        stop_event.set()
        srv_sock.close()
        srv_thread.join(timeout=1.0)


def test_tunnel_delete_closes_tunnel():
    """TUNNEL_DELETE closes the tunnel and cleans up."""
    from device_emulator.services.rtty import _TunnelRelay

    host, port, stop_event, srv_thread, srv_sock = _start_echo_server()
    try:
        mock_a, mock_b = socket.socketpair()
        local_sock = socket.create_connection((host, port), timeout=2.0)
        cleaned_up = []
        tunnel = _TunnelRelay(
            tunnel_id=2,
            local_sock=local_sock,
            rtty_sock=mock_a,
            device_name="test",
            on_close=lambda tid: cleaned_up.append(tid),
        )
        tunnel.start()
        # Close the tunnel.
        tunnel.close()
        # The local socket should be closed.
        try:
            local_sock.sendall(b"test")
            sent_ok = True
        except OSError:
            sent_ok = False
        assert not sent_ok
        mock_a.close()
        mock_b.close()
    finally:
        stop_event.set()
        srv_sock.close()
        srv_thread.join(timeout=1.0)


def test_pack_tunnel_add_roundtrip():
    """TUNNEL_ADD frame pack/parse roundtrip."""
    frame = rtty_proto.pack_tunnel_add(
        tunnel_id=5, local_address=0x7F000001, local_port=8080
    )
    # The frame is a V2 frame: type(1) + length(4) + payload
    assert frame[0] == rtty_proto.TUNNEL_ADD
    tunnel_id, addr, port = rtty_proto.parse_tunnel_add(frame[5:])
    assert tunnel_id == 5
    assert port == 8080


def test_pack_tcp_data_roundtrip():
    """TCPDATA frame pack/parse roundtrip."""
    request_id = b"\x01" * 16
    frame = rtty_proto.pack_tcp_data(
        tunnel_id=3, request_id=request_id, data=b"test data")
    assert frame[0] == rtty_proto.TCPDATA
    tunnel_id, parsed_req_id, data = rtty_proto.parse_tcp_data(frame[5:])
    assert tunnel_id == 3
    assert parsed_req_id == request_id
    assert data == b"test data"