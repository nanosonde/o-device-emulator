"""Protocol-level constants for the device/controller wire protocol.

All values here are derived from doc/DEVICE_PROTOCOL.md. Values marked
CONFIRMED were validated against a live controller; others are provisional.
"""

# Ports (CONFIRMED - published vendor port list + live controller logs)
DISCOVERY_UDP_PORT = 29810
MANAGER_V1_TCP_PORT = 29811  # legacy ("v4-adapted" firmware)
ADOPT_V1_TCP_PORT = 29812  # legacy
UPGRADE_V1_TCP_PORT = 29813  # legacy
MANAGER_V2_TCP_PORT = 29814  # current ("v5-adapted" firmware)
TRANSFER_V2_TCP_PORT = 29815
RTTY_TCP_PORT = 29816
DEVICE_MONITOR_TCP_PORT = 29817
MGMT_HTTPS_PORT = 8043
MGMT_HTTP_PORT = 8088

# Discovery packets older than this (header.timestamp vs now, in ms) are
# dropped by the controller as "overdue discovery" (CONFIRMED).
DISCOVERY_COOLDOWN_MS = 20000

# Protocol version advertised in header.version (CONFIRMED format,
# required field).
PROTOCOL_VERSION = "2.0.0"
PROTOCOL_VER_CAP = 3

# Device type strings for header.device (CONFIRMED via live discovery test
# for "ap"; "switch"/"gateway" consistent with the controller's device-type set).
DEVICE_TYPE_AP = "ap"
DEVICE_TYPE_SWITCH = "switch"
DEVICE_TYPE_GATEWAY = "gateway"

# Message type codes (header.type). Only DISCOVERY is live-confirmed; the
# rest are provisional, documented for completeness.
MESSAGE_TYPE_UNKNOWN = -1
MESSAGE_TYPE_DISCOVERY = 1
MESSAGE_TYPE_PRE_ADOPT_REQUEST = 2
MESSAGE_TYPE_PRE_CONNECT_INFO = 3
MESSAGE_TYPE_ADOPT_REQUEST = 16
MESSAGE_TYPE_ADOPT_RESPONSE = 32
MESSAGE_TYPE_NOTIFY_REQUEST = 80
MESSAGE_TYPE_NOTIFY_REPLY = 144
MESSAGE_TYPE_EVENT_PORTAL_QUERY = 64
MESSAGE_TYPE_EVENT_PORTAL_AUTH = 128
MESSAGE_TYPE_EVENT_PORTAL_AUTH_RESPONSE = 352
MESSAGE_TYPE_INFORM_REQUEST = 256
MESSAGE_TYPE_INFORM_RESPONSE = 512
MESSAGE_TYPE_SET_REQUEST = 4096
MESSAGE_TYPE_SET_RESPONSE = 8192
MESSAGE_TYPE_INIT_SYNC = 4352
MESSAGE_TYPE_FORGET_REQUEST = 16384
MESSAGE_TYPE_FORGET_RESPONSE = 20480
MESSAGE_TYPE_GET_REQUEST = 24576
MESSAGE_TYPE_GET_RESPONSE = 28672
MESSAGE_TYPE_UPGRADE_REQUEST = 32768
MESSAGE_TYPE_UPGRADE_RESPONSE = 65536
MESSAGE_TYPE_REBUILD_REQUEST = 36864
MESSAGE_TYPE_REBUILD_RESPONSE = 40960

# Default discovery announce interval (not controller-mandated; chosen to be
# a reasonable, low-chatter default similar to real device behavior).
DEFAULT_ANNOUNCE_INTERVAL_SECONDS = 10
