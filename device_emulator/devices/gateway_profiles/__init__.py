"""Multi-model gateway negotiation profiles.

Each module in this package defines the negotiation-time constants
(``PROTOCOL_VERSION``, ``COMPONENTS_V2``, ``DEV_CAP``, ``DEVICE_MISC``,
``DEVICE_INFO_TEMPLATE``) for a specific gateway model.  The
:func:`get_profile` function maps a model string (e.g. ``"ER605"``) to the
appropriate profile module.

A profile module may also define optional capability flags that the
emulator consults at runtime to decide which INFORM sections to emit:

- ``SUPPORT_LTE`` – the model has an LTE/4G modem (e.g. ER706W).
- ``SUPPORT_SDWAN`` – the model supports SD-WAN (e.g. ER7206, ER8411).
- ``SUPPORT_DISCRETE_WAN`` – the model supports multi-WAN / discrete WAN.
- ``SUPPORT_WAN_LOAD_BALANCE`` – the model supports WAN load-balance.
- ``SUPPORT_POE`` – the model has PoE-out LAN ports.
- ``SUPPORTS_IPV6`` – the model reports IPv6 on the WAN port (default True).
"""
from __future__ import annotations

import importlib
from typing import Any

# Model-string → module-name mapping.  Matching is case-insensitive on the
# model string's alphanumeric prefix (e.g. "er605", "ER706W", "er8411").
_MODEL_MODULES: dict[str, str] = {
    "er605": "er605",
    "er706": "er706w",
    "er706w": "er706w",
    "er7206": "er7206",
    "er8411": "er8411",
}

# Default profile used when the model is not recognised.
_DEFAULT_MODULE = "er605"


def get_profile(model: str | None) -> Any:
    """Return the profile module for *model* (falls back to ER605)."""
    key = (model or "").strip().lower().replace("-", "").replace(" ", "")
    # Try exact match first, then prefix match (e.g. "er706" → "er706w").
    mod_name = _MODEL_MODULES.get(key)
    if mod_name is None:
        for prefix, name in _MODEL_MODULES.items():
            if key.startswith(prefix):
                mod_name = name
                break
    if mod_name is None:
        mod_name = _DEFAULT_MODULE
    return importlib.import_module(f"device_emulator.devices.gateway_profiles.{mod_name}")