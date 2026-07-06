"""Minimal client for the controller's unauthenticated info endpoint.

GET https://<host>:8043/api/info returns the controller's ID, which is
required in every discovery packet (see doc/DEVICE_PROTOCOL.md §7). Uses only
the standard library so the emulator doesn't need an HTTP client dependency;
the controller's TLS certificate is self-signed by default so verification is
disabled here (this only ever talks to a local lab controller).
"""
from __future__ import annotations

import json
import ssl
import urllib.request
from typing import Any

# The controller's info endpoint returns its identifier under this fixed JSON
# key in the `result` object.
_CONTROLLER_ID_KEY = "omadacId"


class ControllerInfoError(RuntimeError):
    pass


def fetch_controller_info(host: str, https_port: int = 8043, timeout: float = 5.0) -> dict[str, Any]:
    """Fetch the controller's /api/info payload.

    Returns the parsed `result` object (contains the controller id,
    `controllerVer`, etc.).
    """
    url = f"https://{host}:{https_port}/api/info"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=ctx) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - surface as a domain-specific error
        raise ControllerInfoError(f"failed to fetch {url}: {exc}") from exc

    if payload.get("errorCode") != 0:
        raise ControllerInfoError(f"controller returned error: {payload}")
    result = payload.get("result")
    if not result or not result.get(_CONTROLLER_ID_KEY):
        raise ControllerInfoError(f"unexpected /api/info response: {payload}")
    return result


def fetch_controller_id(host: str, https_port: int = 8043, timeout: float = 5.0) -> str:
    info = fetch_controller_info(host, https_port=https_port, timeout=timeout)
    return info[_CONTROLLER_ID_KEY]
