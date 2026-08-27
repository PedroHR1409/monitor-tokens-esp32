# Monitor.AI Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authenticated bidirectional WebSocket transport, HTTP-v2 fallback, idempotent device events, and durable offline snapshots.

**Architecture:** The daemon prefers one WebSocket connection to the board and sends complete protocol-v2 snapshots. HTTP remains a bounded fallback and compatibility endpoints remain available for one migration release.

**Tech Stack:** Python asyncio/websockets, Arduino-ESP32, ArduinoJson, ESP WebSocket/server components, LittleFS, Preferences.

**Spec:** `docs/superpowers/specs/2026-08-27-monitor-ai-complete-evolution-design.md`

## Global Constraints

- Protocol/auth failures reject complete mutations.
- WebSocket is LAN-only unless externally protected by VPN/TLS.
- HTTP v1 remains functional during migration.
- Filesystem snapshots contain no Wi-Fi password or API token.

---

### Task 1: Transport-neutral sequencing and device events

**Files:**
- Create: `tools/device_events.py`
- Create: `tests/test_device_events.py`
- Modify: `tools/protocol_v2.py`
- Modify: `tools/event_store.py`

**Interfaces:**
- Produces: `SequenceState.next()`, `parse_device_event()`, `process_device_event()`.

- [ ] Test daemon instance/sequence resets, duplicate event IDs, invalid composite keys/actions, and ack/snooze values.
- [ ] Implement sequence persistence and idempotent event application.
- [ ] Run tests and commit `feat: add sequenced device event protocol`.

### Task 2: Python WebSocket transport with HTTP fallback

**Files:**
- Create: `tools/device_transport.py`
- Create: `tests/test_device_transport.py`
- Modify: `tools/session_daemon.py`

**Interfaces:**
- Produces: `DeviceTransport.send_snapshot()`, `receive_events()`, `TransportHealth`.

- [ ] Test handshake headers, ping/pong, sequence, reconnect backoff, event acknowledgement, optional dependency absence, and HTTP fallback.
- [ ] Implement a background asyncio WebSocket client; isolate the optional dependency so `doctor` and HTTP-only mode work without it.
- [ ] Integrate a single long-lived transport into daemon startup/shutdown.
- [ ] Run tests and commit `feat: stream snapshots and events over websocket`.

### Task 3: Firmware protocol-v2 atomic parser

**Files:**
- Create: `src/protocol_v2.h`, `src/protocol_v2.cpp`
- Create: `include/protocol_contract.h`
- Modify: `src/session_transport.cpp`, `include/session_model.h`
- Create: `tests/native/test_protocol.cpp`

**Interfaces:**
- Produces: `parse_snapshot_v2(json, StagedSnapshot&, ProtocolError&)`, `apply_staged_snapshot()`.

- [ ] Add host/pure tests for version, limits, identity, quality, progress, health, nodes, and atomic rejection.
- [ ] Implement staged fixed-size structs and only swap global state after complete validation.
- [ ] Keep v1 parsing in a separate function and return HTTP 426 for unsupported versions.
- [ ] Run native tests and production/demo builds; commit `feat: parse protocol v2 atomically on device`.

### Task 4: Firmware WebSocket and HTTP-v2 endpoints

**Files:**
- Create: `src/ws_transport.h`, `src/ws_transport.cpp`
- Modify: `src/session_transport.cpp`, `src/session_transport.h`, `src/main.cpp`, `platformio.ini`

**Interfaces:**
- Produces: authenticated `/ws`, `/api/v2/snapshot`, `/api/v2/events`, transport health.

- [ ] Add contract tests for route presence, token handshake, frame/body limits, ping age, and fallback.
- [ ] Implement the board WebSocket server on a documented port using a pinned library/component compatible with Arduino core 3.3.11.
- [ ] Queue device gesture events and remove them only after daemon acknowledgement.
- [ ] Build both environments and commit `feat: add board websocket and http v2 fallback`.

### Task 5: Persistent offline snapshot and event queue

**Files:**
- Create: `src/snapshot_store.h`, `src/snapshot_store.cpp`
- Modify: `src/main.cpp`, `src/session_transport.cpp`, `partitions.csv`
- Create: `tests/native/test_snapshot_policy.cpp`

**Interfaces:**
- Produces: `snapshot_store_begin/load/schedule/flush`, `should_persist_snapshot()`.

- [ ] Test five-minute throttling, attention-state immediate write, atomic temp rename, invalid CRC/version, and stale restore.
- [ ] Mount LittleFS, load last snapshot before network, force source/transport stale, and persist only accepted v2 snapshots.
- [ ] Persist a bounded event queue in NVS with boot counter and sequence; never persist secrets in filesystem.
- [ ] Build/test and commit `feat: restore historical snapshot after reboot`.

### Task 6: Integrated reconnect and compatibility verification

**Files:**
- Modify: `tests/test_device_transport.py`
- Modify: `tests/test_protocol_v2.py`
- Modify: `README.md`, `docs/HARDWARE_VALIDATION.md`

**Interfaces:**
- Consumes all transport components.

- [ ] Add an integration harness that simulates connect, snapshot, gesture, disconnect, HTTP fallback, reconnect, duplicate replay, and acknowledgement.
- [ ] Verify v1 daemon → new firmware and v2 daemon → HTTP/WebSocket paths with fixtures.
- [ ] Run full Python/native suites and both builds; commit `test: verify websocket fallback and offline recovery`.

