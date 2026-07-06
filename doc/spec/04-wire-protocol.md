# 4 — Wire Protocol

> Prerequisite: [3 — Architecture](03-architecture.md). This document defines
> the message envelope and framing shared by **all** JSON-based channels
> (discovery and the management channel). The device-monitor (protobuf) and
> RTTY (binary) channels define their own framing, described in
> [§7](07-auxiliary-channels.md).

## 4.1 Message envelope

Every JSON-channel message is a single JSON document with two top-level
objects:

```json
{ "header": { ... }, "body": { ... } }
```

- `header` carries routing and protocol metadata (identity, type, sequence).
- `body` carries the message payload, whose shape is determined by
  `header.type` and the device class.

The device MUST emit compact JSON with no insignificant whitespace. Field
order within an object is not significant.

## 4.2 Wire framing

All JSON channels (UDP discovery and the TLS management channel) use the same
length-prefixed framing:

```
 Byte offset
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    JSON length (uint32, BE)                    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
:                        UTF-8 JSON body                         :
:                       (length bytes, no NUL)                   :
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

| Field | Type | Description |
|---|---|---|
| `JSON length` | `uint32` (BE) | Length in bytes of the following JSON document. |
| `JSON body` | `bytes` | A UTF-8-encoded JSON document (the envelope of §4.1). No trailing terminator. |

On the **discovery channel** (UDP 29810) this frame is sent as plaintext JSON
inside a single UDP datagram. On the **management channel** (TCP 29814) the
same frame is carried inside a TLS stream; the device MUST wrap the socket in
TLS before sending (see [§3.3](03-architecture.md#33-tls-requirements)). A
plain-TCP connection to 29814 is silently dropped by the controller.

## 4.3 `header` fields

| Field | Type | Required | Description |
|---|---|---|---|
| `mac` | string | **MUST** | Device MAC, hyphenated uppercase `AA-BB-CC-DD-EE-FF`. The device's identity key. |
| `type` | int | **MUST** | Message-type code (see [§4.5](#45-message-type-constants)). |
| `device` | string | **MUST** | Device-class string: `ap`, `switch`, `gateway`, or `olt`. |
| `version` | string | **MUST** | Protocol version, e.g. `"2.3.0"` (AP) or `"2.2.0"` (switch/gateway/OLT). Omitting it causes the controller to reject the packet. See [§4.4](#44-protocol-versioning). |
| `verCap` | int | **MUST** | Version-capability bitmask. The value `3` is accepted by Controller v6.2.x and routes the device onto the current (V2) protocol branch. |
| `timestamp` | int (epoch ms) | **MUST** | Epoch time in **milliseconds**. The controller drops discovery announces whose timestamp is older than the discovery cooldown (20 000 ms) relative to the controller's clock, so keep this close to current time. |
| `seq` | int | SHOULD | Sequence number. Device-initiated management messages SHOULD use an incrementing sequence; controller replies echo the request's `seq`. |
| `error` | int | OPTIONAL | Response error code; `0` on requests. |
| `compress` | string | OPTIONAL | If present (e.g. `"lzo-2.07"`), the body is compressed. Omit for plain JSON. |
| `dest` | string | OPTIONAL | Destination controller ID. Required in NOTIFY messages (see [§6.4](06-steady-state.md#64-notify)). |
| `ip` | string | OPTIONAL | Filled in by the controller from the packet source address; not required in requests. |

## 4.4 Protocol versioning

The controller compares the device's advertised `version` against a per-class
"fit" version. A device advertising too low a version is flagged incompatible.

| Device class | `header.version` | `header.device` |
|---|---|---|
| EAP (access point) | `"2.3.0"` | `ap` |
| Switch | `"2.2.0"` | `switch` |
| Gateway | `"2.2.0"` | `gateway` |
| OLT | `"2.2.0"` | `olt` |

`verCap` MUST be `3` (the value accepted by Controller v6.2.x; it routes the
device onto the current protocol branch).

## 4.5 Message-type constants

`header.type` selects the message. The table below lists the codes used in
this specification. Names are descriptive labels for the numeric codes.

### Discovery and management base codes

| Code | Name | Direction | Channel |
|---:|---|---|---|
| `1` | DISCOVERY | device → controller | UDP 29810 |
| `2` | PRE_ADOPT_REQUEST | controller → device | UDP 29810 |
| `3` | PRE_CONNECT_INFO | device → controller | TLS 29814 |
| `80` | NOTIFY_REQUEST | device → controller | TLS 29814 |
| `144` | NOTIFY_REPLY | controller → device | TLS 29814 |
| `256` | INFORM_REQUEST | device → controller | TLS 29814 |
| `512` | INFORM_RESPONSE | controller → device | TLS 29814 |
| `4096` | SET_REQUEST | controller → device | TLS 29814 |
| `8192` | SET_RESPONSE | device → controller | TLS 29814 |
| `24576` | GET_REQUEST | controller → device | TLS 29814 |
| `28672` | GET_RESPONSE | device → controller | TLS 29814 |
| `16384` | FORGET_REQUEST | controller → device | TLS 29814 |
| `20480` | FORGET_RESPONSE | device → controller | TLS 29814 |
| `32768` | UPGRADE_REQUEST | controller → device | TLS 29814 |
| `65536` | UPGRADE_RESPONSE | device → controller | TLS 29814 |

### Adoption handshake codes (hex)

These are exchanged on the TLS management channel (29814) during adoption.
Device-initiated members carry an incrementing `seq`; controller replies echo
it.

| Code | Name | Direction |
|---:|---|---|
| `0x100000` | PRE_CONNECT_INFO_RESPONSE | controller → device |
| `0x100001` | DEVICE_VERIFY_INFO | device → controller |
| `0x100002` | DEVICE_VERIFY_RESPONSE | controller → device |
| `0x100003` | SYSTEM_VERIFY_RESULT | device → controller |
| `0x100004` | DEVICE_NEGOTIATION | device → controller |
| `0x100005` | SYSTEM_NEGOTIATION | controller → device |
| `0x100006` | INIT_SYNC_RESULT | device → controller |
| `0x100009` | VERIFY_RESULT_ACK | controller → device |
| `0x10000A` | INIT_SYNC_RESULT_ACK | controller → device |
| `0x100007` | NOTIFY_REQUEST_V2 | device → controller (not subject-routed — see [§6.4](06-steady-state.md#64-notify)) |
| `0x100008` | NOTIFY_REPLY_V2 | controller → device |

### File-transfer codes

| Code | Name | Direction | Notes |
|---:|---|---|---|
| `0x160000` | FILE_TRANSFER_REQUEST_V2 | controller → device | Requests one partition of a file. |
| `0x170000` | FILE_TRANSFER_RESPONSE_V2 | device → controller | Carries one base64-encoded partition. Sent on the management channel (29814), not on 29815. |

> Codes not listed here (e.g. portal-event codes 64/128/352, adopt 16/32,
> init-sync 4352, rebuild 36864/40960) are reserved. The adopt/init-sync/
> rebuild codes belong to the deprecated ECSP v1 flow — see
> [Appendix B — Legacy Protocol](appendix-b-legacy-protocol.md). An ECSP v2
> device MUST NOT emit them.

## 4.6 JSON serialization rules

- **Encoding**: UTF-8.
- **Whitespace**: compact, no padding (`{"a":1}` not `{ "a": 1 }`).
- **Field order**: not significant unless stated otherwise.
- **Numbers**: emitted as JSON numbers; MAC and controller IDs are strings.
- **Timestamps**: integer epoch **milliseconds**.
- **Booleans**: JSON `true`/`false`, not `0`/`1`, unless a section specifies
  a numeric flag.

## 4.7 Timestamp freshness

The controller applies a **20 000 ms** discovery cooldown. A DISCOVERY
announce whose `header.timestamp` is older than 20 seconds relative to the
controller's clock is dropped as stale. The device SHOULD set `timestamp` to
the current epoch milliseconds at send time.

---

Next: [5 — Discovery & Adoption](05-discovery-and-adoption.md)