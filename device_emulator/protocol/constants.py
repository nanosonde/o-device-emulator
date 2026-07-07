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

# Protocol version advertised in header.version. The controller classifies the
# device's ECSP protocol version as [major, minor] and compares it against the
# per-device-type "fit" version it supports; a lower minor is flagged as
# incompatible ("The device is not compatible with the current controller").
# For an access point, both controller v5.15 and v6.2 expect EAP fit version
# 2.3 (EcspFirstVersionEnum V2), so advertise "2.3.0" (major 2 / minor 3) to be
# reported as compatible. verCap 3 = V1|V2 (keeps the device on the V2 branch).
PROTOCOL_VERSION = "2.3.0"
PROTOCOL_VER_CAP = 3

# Device type strings for header.device (CONFIRMED via live discovery test
# for "ap"; "switch"/"gateway" consistent with the controller's device-type set).
DEVICE_TYPE_AP = "ap"
DEVICE_TYPE_SWITCH = "switch"
DEVICE_TYPE_GATEWAY = "gateway"

# Message type codes (header.type). DISCOVERY and the management-channel
# exchange below are live-confirmed; the remaining codes are provisional and
# documented for completeness.
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

# Management-channel handshake message types (header.type) exchanged over the
# TLS connection to MANAGER_V2_TCP_PORT after adoption is initiated. All
# CONFIRMED live against a real controller (see doc/DEVICE_PROTOCOL.md §8).
# Device-initiated messages are the *_INFO / *_RESULT / *_REQUEST members;
# controller-initiated replies are the *_RESPONSE / *_ACK / *_NEGOTIATION
# members.
MESSAGE_TYPE_PRE_CONNECT_INFO_RESPONSE = 0x100000
MESSAGE_TYPE_DEVICE_VERIFY_INFO = 0x100001
MESSAGE_TYPE_DEVICE_VERIFY_RESPONSE = 0x100002
MESSAGE_TYPE_SYSTEM_VERIFY_RESULT = 0x100003
MESSAGE_TYPE_DEVICE_NEGOTIATION = 0x100004
MESSAGE_TYPE_SYSTEM_NEGOTIATION = 0x100005
MESSAGE_TYPE_INIT_SYNC_RESULT = 0x100006
MESSAGE_TYPE_NOTIFY_REQUEST_V2 = 0x100007
MESSAGE_TYPE_NOTIFY_REPLY_V2 = 0x100008
MESSAGE_TYPE_VERIFY_RESULT_ACK = 0x100009
MESSAGE_TYPE_INIT_SYNC_RESULT_ACK = 0x10000A

# The management channel is presented behind TLS; the server offers a vendor
# certificate with CN=localhost and does NOT require a client certificate.
# A plain-TCP connection is silently dropped (CONFIRMED). server_hostname
# used for the SNI/hostname on the client side.
MANAGE_TLS_SERVER_HOSTNAME = "localhost"

# Factory-default controller identifier reported in discovery by an
# unmanaged device. Announcing with this sentinel makes the controller offer
# the device as adoptable ("Pending"); announcing another controller's real
# id instead yields "Managed By Others" (CONFIRMED, see §8).
FACTORY_CONTROLLER_ID = "c21f969b5f03d33d43e04f8f136e7682"

# Default management port the controller directs the device to in its
# pre-adopt reply (body.adoptPort); used as a fallback if that field is
# absent.
DEFAULT_ADOPT_TCP_PORT = MANAGER_V2_TCP_PORT

# Default INFORM heartbeat interval (seconds) once the device is CONNECTED.
# The device sends an INFORM_REQUEST at this cadence to stay online.
DEFAULT_INFORM_INTERVAL_SECONDS = 10.0

# Default discovery announce interval (not controller-mandated; chosen to be
# a reasonable, low-chatter default similar to real device behavior).
DEFAULT_ANNOUNCE_INTERVAL_SECONDS = 10
