# 1 — Introduction

> This is part of the **Om\*d\*-Compatible Device Specification**. Start at
> [`README.md`](README.md) for an overview and reading order.

## 1.1 Purpose

This specification defines the requirements a network device MUST fulfil to be
discovered, adopted, managed, and monitored by a **TP-L\*nk Om\*d\* Software
Controller** (hereafter "the controller"). A device that implements this
specification can join an Om\*d\*-managed site, reach the **Connected** state,
and serve the operator-facing Tools features (remote terminal, network check,
packet capture).

The intended reader is an engineer who must design and build such a device —
for example, a new access-point, switch, gateway/router, or PON optical line
terminal — and who has **no prior knowledge of Om\*d\* products or technology**.

## 1.2 Scope

### In scope

- The role of a managed device within an Om\*d\* Software-Defined Networking
  (SDN) site.
- The wire protocol a device uses to be **discovered** and **adopted** by the
  controller.
- The steady-state message exchange that keeps a device online and lets the
  controller push configuration.
- The four auxiliary channels that implement operator Tools: remote terminal,
  network check, packet capture, and file transfer.
- The four managed device classes — EAP (access point), switch, gateway, and
  OLT — and the features in which they differ.
- Feature comparison tables and a glossary.

### Out of scope

- The controller's own internal architecture and its REST/STOMP management
  APIs. The controller is treated as a black box; only its observable wire
  behaviour toward devices is specified.
- Controller installation, licensing, backup file formats, and operator UI
  workflows.
- Implementation language, operating system, or hardware platform of the
  device. This document is deliberately language- and platform-agnostic.
- Any earlier controller or device-protocol generation. This specification
  describes the **current** (ECSP v2) protocol only. The deprecated ECSP v1
  generation is documented in [Appendix B — Legacy Protocol](appendix-b-legacy-protocol.md)
  for implementations that must maintain or migrate legacy firmware.

### Target version

This specification targets **Om\*d\* Controller v6.2.x** (device protocol
generation 2). Earlier controller versions and the earlier device-protocol
generation (legacy TCP management/adopt/upgrade ports and their associated
handshake) are **out of scope and not supported** by Controller v6.

## 1.3 What is Om\*d\* SDN?

Om\*d\* is an SDN platform for managing network infrastructure from a single
point — the controller. The controller discovers devices on the network,
adopts them into a *site*, pushes configuration to them, monitors their
health, and offers operator tools such as a remote terminal, network
diagnostics, and packet capture.

A *site* is a logical grouping of devices and the clients they serve — for
example, one office building or one branch. Within a site, devices form a
forwarding topology (gateway → switch → access point → wireless client) that
the controller visualises automatically from information the devices report.

The device's job is therefore not to configure itself, but to **register** with
the controller, **accept** configuration the controller pushes, **report** its
state periodically, and **serve** the operator Tools on demand.

## 1.4 Audience assumptions

This document assumes the reader:

- Understands general networking (IP, TCP, UDP, TLS, Ethernet, MAC addresses,
  VLANs, routing).
- Understands JSON and (for one auxiliary channel) Protocol Buffers.
- Is **not** familiar with Om\*d\*, TP-L\*nk product naming, or the controller's
  internal design.

No programming language is assumed. Where an algorithm is given, it is written
as language-neutral pseudocode.

## 1.5 How to read this document set

| If you want to… | Read |
|---|---|
| Understand the big picture first | [2 — Concepts](02-concepts.md) |
| See the system architecture and channels | [3 — Architecture](03-architecture.md) |
| Learn the message envelope and framing | [4 — Wire Protocol](04-wire-protocol.md) |
| Implement discovery and the adoption handshake | [5 — Discovery & Adoption](05-discovery-and-adoption.md) |
| Implement steady-state operation | [6 — Steady-State Operation](06-steady-state.md) |
| Implement Terminal, Network Check, or Packet Capture | [7 — Auxiliary Channels](07-auxiliary-channels.md) |
| Know what differs per device type | [8 — Device Types](08-device-types.md) |
| Compare features across types or models | [Appendix A — Feature Matrix](appendix-a-feature-matrix.md) |

## 1.6 Terminology

| Term | Meaning |
|---|---|
| **Controller** | The Om\*d\* Software Controller — the central SDN management server. |
| **Site** | A logical grouping of devices and clients under one controller. |
| **Device** | A network element managed by the controller (AP, switch, gateway, or OLT). |
| **EAP** | Om\*d\*'s product prefix for access points (e.g. EAP245). Used interchangeably with "AP". |
| **Switch** | A managed Ethernet switch. |
| **Gateway** | An Internet gateway / router (Om\*d\* product prefix "ER"). |
| **OLT** | Optical Line Terminal — the headend of a GPON/EPON passive optical network. |
| **ONU** | Optical Network Unit — a subscriber device under an OLT. |
| **Adoption** | The process by which the controller takes ownership of a discovered device. |
| **Connected** | The device state meaning "adopted and online". |
| **INFORM** | A periodic heartbeat/telemetry message a Connected device sends to the controller. |
| **SET / GET** | Controller-initiated configuration-push (SET) and device-query (GET) messages. |
| **NOTIFY** | A device-to-controller event message carrying a subject code. |
| **RTTY** | The remote-terminal protocol (over TLS) that powers the Tools → Terminal feature. |
| **DMP** | Device Monitor Protocol — the protobuf channel that powers Network Check. |
| **ECSP** | The name of the device/controller wire-protocol family used by Om\*d\*. |
| **Controller ID** | A unique identifier string owned by a controller instance. |

## 1.7 Document conventions

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**,
**SHOULD**, **SHOULD NOT**, **RECOMMENDED**, **MAY**, and **OPTIONAL** in this
document are to be interpreted as described in RFC 2119.

Additional conventions:

- **Byte order**: multi-byte integer fields are **big-endian** unless stated
  otherwise. An explicit `(BE)` or `(LE)` annotation is used where it matters.
- **Hex**: hexadecimal values are written `0x`-prefixed (e.g. `0x100004`).
- **MAC addresses**: written hyphenated and uppercase, e.g. `AA-BB-CC-DD-EE-FF`.
- **JSON**: examples show compact JSON. Field order is not significant unless
  stated otherwise.
- **Types**: `uint8/16/32` = unsigned 8/16/32-bit integer; `bytes` = a byte
  sequence; `string` = UTF-8 text; `bool` = true/false.
- **Diagrams**: Mermaid diagrams render in the VS Code Markdown preview and
  any Mermaid viewer; ASCII diagrams show byte layouts and frame structure.

A reference to another document, e.g. `[§4.2](04-wire-protocol.md#42-header)`,
links into the relevant section.

## 1.8 Minimum viable device

The smallest device implementation that can be discovered, adopted, and reach
the **Connected** state requires only:

1. UDP discovery announces (see [§5](05-discovery-and-adoption.md)).
2. The adoption handshake over TLS (see [§5.4](05-discovery-and-adoption.md#54-adoption-handshake)).
3. Periodic INFORM heartbeats (see [§6.1](06-steady-state.md#61-inform-heartbeat)).

All other features (SET/GET handling, terminal, network check, packet capture)
are layered on top of this minimum. A device MAY implement the minimum first
and add features incrementally — but a device that does not ack SET requests
risks being forgotten by the controller (see [§6.2](06-steady-state.md#62-set--set-response)).

---

Next: [2 — Concepts](02-concepts.md)