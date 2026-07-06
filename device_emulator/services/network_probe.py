"""Synthetic Network Check probe responses (ping, traceroute).

The controller's Tools → Network Check feature sends ping/traceroute probe
requests to the device via the device-monitor (DMP) channel. The device
executes the probe and returns the results. Since the emulator has no real
network to probe, we synthesize deterministic-but-plausible results.
"""
from __future__ import annotations

import json

from .. import stats


def handle_probe(device, path: str, data: bytes) -> bytes:
    """Handle a DMP probe request and return the response data bytes.

    The *path* field in the DMP message header indicates the probe type:
    ``"/ping"`` → ping, ``"/traceroute"`` → traceroute. The request *data*
    may contain a JSON payload with the target host.

    Returns a JSON-encoded response payload (the controller parses this from
    the protobuf ``data`` field).
    """
    if "/ping" in path or path.endswith("ping"):
        return _ping_response(device, data)
    if "/traceroute" in path or path.endswith("traceroute"):
        return _traceroute_response(device, data)
    # Unknown probe type — return an empty response.
    return b""


def _ping_response(device, data: bytes) -> bytes:
    """Synthesize a ping result: 4 replies with deterministic RTTs."""
    target = _extract_target(data) or "8.8.8.8"
    rtts = [stats.synthetic_int(device.mac, f"ping{i}", 5, 50) for i in range(4)]
    result = {
        "target": target,
        "packetsSent": 4,
        "packetsReceived": 4,
        "packetsLost": 0,
        "lossRate": 0,
        "minRtt": min(rtts),
        "maxRtt": max(rtts),
        "avgRtt": sum(rtts) // len(rtts),
        "rtts": rtts,
        "ip": target,
        "isIp": True,
        "status": "success",
    }
    return json.dumps(result).encode("utf-8")


def _traceroute_response(device, data: bytes) -> bytes:
    """Synthesize a traceroute result: a few hops with deterministic RTTs."""
    target = _extract_target(data) or "8.8.8.8"
    hops = []
    for i in range(4):
        hop_ip = f"10.0.{i + 1}.1"
        rtt1 = stats.synthetic_int(device.mac, f"tr{i}a", 5, 50)
        rtt2 = stats.synthetic_int(device.mac, f"tr{i}b", 5, 50)
        rtt3 = stats.synthetic_int(device.mac, f"tr{i}c", 5, 50)
        hops.append({
            "hop": i + 1,
            "ip": hop_ip,
            "rtts": [rtt1, rtt2, rtt3],
            "status": "success",
        })
    # The last hop is the target.
    hops.append({
        "hop": len(hops) + 1,
        "ip": target,
        "rtts": [stats.synthetic_int(device.mac, "trf1", 5, 50)] * 3,
        "status": "success",
    })
    result = {
        "target": target,
        "hops": hops,
        "hopCount": len(hops),
        "status": "success",
    }
    return json.dumps(result).encode("utf-8")


def _extract_target(data: bytes) -> str | None:
    """Try to extract the target host from the request JSON data."""
    if not data:
        return None
    try:
        payload = json.loads(data)
        return payload.get("target") or payload.get("host") or payload.get("ip")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None