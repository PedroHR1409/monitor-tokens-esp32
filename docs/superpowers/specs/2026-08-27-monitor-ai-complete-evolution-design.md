# Monitor.AI Complete Evolution Design

## Objective

Evolve Monitor.AI from a single-computer polling dashboard into a reliable, event-oriented,
updatable appliance while preserving its existing ESP32-S3 hardware, LVGL interface, current
Claude/Codex sessions, deterministic state semantics, and honest treatment of stale or estimated
data.

The implementation covers every improvement approved in the 2026-08-27 project review:

- correct per-agent and combined usage metrics;
- hook-first exact state detection;
- versioned protocol and capability negotiation;
- diagnostics CLI, automatic daemon service, reproducible dependencies, CI, and current docs;
- Wi-Fi/token provisioning and authenticated OTA;
- persistent offline snapshot;
- health, activity, progress, and alert controls in the device UI;
- SQLite event/history storage and provider adapters;
- optional structured Codex App Server ingestion;
- bidirectional WebSocket transport with HTTP fallback;
- multi-host aggregation;
- configurable alerts without remote command approval.

## Non-goals and safety boundaries

- Do not replace the Guition ESP32-S3 display, Arduino core, Arduino_GFX, or LVGL.
- Do not add MQTT or require a broker for a one-device installation.
- Do not approve, deny, or execute agent commands from the display. The display may acknowledge,
  snooze, pin, or hide alerts, but security decisions remain in the agent's trusted client.
- Do not claim Claude quota or context precision when the source does not provide it.
- Do not make App Server mandatory. Existing Claude Code and Codex CLI/App workflows remain usable.

## Delivery decomposition

The architecture is delivered as four ordered subprojects. Each leaves the project deployable:

1. **Foundation** — protocol v2, metric semantics, hook state, configuration, doctor/service,
   dependency pins, CI, and documentation.
2. **Telemetry** — provider interfaces, SQLite history, aggregation, structured App Server input,
   and multi-host ingestion.
3. **Transport** — WebSocket session with HTTP fallback, command/event acknowledgements, and
   persistent snapshots.
4. **Firmware UX** — provisioning, OTA, health/activity pages, plan progress, and alert controls.

## Target architecture

```text
Claude hooks/transcripts ─┐
                         ├─ provider adapters ─ event store (SQLite) ─ state projector
Codex hooks/rollouts ─────┤                                      │
Codex App Server ─────────┘                                      ├─ HTTP v2 fallback
remote Monitor nodes ───────── authenticated ingest ─────────────┤
                                                                └─ WebSocket v2
                                                                       ↕
                                                               ESP32 state cache
                                                                       │
                                                      dashboard / activity / health
```

The daemon is the authority for session selection, history, hidden/pinned/snoozed state, and
metric aggregation. The device remains authoritative only for local configuration and the last
offline display snapshot. A device gesture is an event sent to the daemon and acknowledged with
an event ID. When offline, the device queues a small bounded set of gestures in NVS and retries.

## Protocol v2

Every daemon-to-device snapshot contains:

- `schema_version: 2`;
- `message_type: "snapshot"`;
- monotonically increasing `sequence` scoped to `daemon_instance_id`;
- `generated_at_epoch_ms` with millisecond precision;
- `daemon_instance_id`, `node_id`, and `device_id`;
- `capabilities`, a string array used for optional fields and commands;
- `sessions`, `catalog`, `stats`, `health`, and `nodes` blocks.

Every session uses the stable composite identity `(node_id, provider, session_id)` and includes:

- display metadata and deterministic `work|ask|perm|free` state;
- source age, source freshness, source quality, and diagnostic code;
- model, effort, branch, token window, context value/limit/quality;
- plan completed/total counts and current step when known;
- alert acknowledgement and snooze deadline.

Metrics are typed by provider and quality. `stats.usage` carries `combined`, `claude`, and `codex`
series. A combined value exists only when compatible Claude and Codex values are both known;
otherwise the UI labels the provider rather than presenting a partial value as a total. Quality is
one of `official`, `measured`, `estimated`, `configured`, `historical`, or `unknown`.

The firmware accepts v2 and, during migration, the current unversioned payload as v1. Unsupported
major versions return HTTP 426 and remain visible on the health page as a version mismatch. Numeric
types and array sizes are validated before mutating live state. A snapshot is applied atomically:
invalid optional blocks are rejected rather than partially updating sessions and metrics.

Device-to-daemon events use:

```json
{
  "schema_version": 2,
  "message_type": "device_event",
  "event_id": "device-boot-counter-sequence",
  "device_id": "...",
  "action": "hide|unhide|pin|unpin|ack|snooze|clear",
  "session_key": "node:provider:id",
  "value": 0
}
```

The daemon stores processed event IDs, making retries idempotent.

## Provider adapters and state reduction

`ProviderAdapter` isolates discovery from projection. An adapter returns normalized session
observations and metric samples; it never selects cards or formats device text.

### Claude

- Hooks are authoritative for lifecycle states.
- `PreToolUse` for `AskUserQuestion` or `ExitPlanMode` records `ask` directly.
- `PermissionRequest` records `perm` except for question tools.
- `PostToolUse`, `UserPromptSubmit`, `Stop`, and `SessionEnd` close the corresponding transition.
- Transcripts remain a fallback for metadata, historical usage, and installations without hooks.
- Context percentage stays unknown until a measured limit or explicit configured model/window is
  available. The previous unconditional 1M denominator is removed.

### Codex

- Current lifecycle hooks remain the compatibility-first state source.
- Rollouts remain a fallback for metadata and historical usage, with parser failures isolated per
  session.
- The optional App Server adapter consumes generated-version schemas and normalized events for
  exact turns, user-input requests, approvals, plans, items, and token updates. It may observe a
  monitor-managed App Server or ingest captured NDJSON from another client; it does not silently
  replace how Codex is launched.

### Reduction

Normalized events are append-only in SQLite and reduced into a current-state table. Event order is
provider timestamp, then local receive sequence. Future, duplicate, or out-of-order events are
recorded with diagnostics and excluded from current state. Staleness remains orthogonal to state.

## SQLite storage and multi-host

The standard-library `sqlite3` database lives under the user configuration directory, not inside
the repository. Migrations create:

- `schema_migrations`;
- `nodes` and node heartbeats;
- `session_events` and `session_current`;
- `usage_samples` and hourly aggregates;
- `device_preferences` for hidden, pinned, acknowledged, and snoozed sessions;
- `processed_device_events` for idempotence;
- `daemon_state` for sequence and instance metadata.

Retention defaults to 30 days for raw events and 365 days for hourly aggregates and is configurable.
Database failure never corrupts the device snapshot: the daemon logs the error, continues from the
in-memory observation, and reports degraded storage health.

Multi-host has two roles:

- a **satellite** collects local provider data and POSTs normalized observations to an aggregator;
- an **aggregator** stores local and remote nodes and projects the combined board.

Both roles use the same daemon executable and shared-token authentication. Nodes have explicit IDs,
heartbeats, and stale status. A standalone installation is an aggregator with one local node and
requires no extra configuration.

## Configuration, doctor, and service

`monitor.toml` is loaded from the platform user configuration directory and can be overridden by a
CLI path. Environment variables override secrets only. Non-secret defaults cover board host,
intervals, timezone, retention, roles, WebSocket preference, and alert thresholds. Existing
`secrets.h` values remain a firmware fallback during migration.

The CLI entry point supports:

- `run`, `once`, and the existing daemon flags;
- `doctor` with machine-readable JSON and human output;
- `service install|remove|status`;
- `hooks install|remove|check` wrappers;
- `history` summary/export;
- `config init|show` with secrets redacted.

`doctor` verifies configuration, token strength, provider directories, hook coverage, SQLite,
device discovery, protocol/version compatibility, transport, and PlatformIO availability. It never
prints secret values.

Service installation uses a per-user Windows Scheduled Task on Windows and writes a user-systemd
unit on Linux. Installation is explicit, idempotent, reversible, and supports dry-run. It does not
require administrator privileges when the platform supports a user service.

## Transport

The board keeps HTTP health, diagnostics, provisioning, OTA, and v1/v2 snapshot endpoints. The
daemon prefers one authenticated WebSocket connection and falls back to HTTP after bounded retries.

WebSocket messages are complete protocol-v2 JSON documents. Ping/pong plus snapshot sequence
detects half-open or replayed connections. The shared token is validated during the handshake.
Plain `ws://` is limited to the local network and the health screen visibly labels it `LAN`; remote
multi-host ingestion is host-to-host HTTP and may be placed behind TLS. Documentation requires a
trusted LAN or VPN and never presents the token as Internet-grade perimeter security.

HTTP fallback posts `/api/v2/snapshot` and polls `/api/v2/events`. The existing `/sessions`,
`/hidden`, and `/pinned` endpoints remain for one compatibility release.

## Firmware configuration and provisioning

Runtime device configuration is stored in NVS with a version and CRC:

- Wi-Fi SSID/password;
- API token;
- daemon/device names and transport preference;
- timezone and brightness schedule;
- alert thresholds;
- provisioning-complete flag.

On first boot, invalid configuration, or repeated Wi-Fi failure, the device starts a uniquely named
SoftAP and a captive configuration portal. The portal accepts Wi-Fi, token, names, timezone, and
brightness fields, validates lengths, writes atomically, and reboots. A long press on an empty
dashboard area opens a confirmation screen for provisioning reset; it never exposes stored secrets.

## OTA and persistent snapshot

The existing dual OTA partitions are used by an authenticated `/update` page and upload endpoint.
Firmware version, build ID, schema support, partition, and update status appear on the health page.
An invalid or interrupted upload leaves the running partition untouched. OTA is unavailable until a
strong API token is configured.

The existing filesystem partition stores:

- the last accepted protocol-v2 snapshot;
- compact web assets for provisioning/OTA if needed;
- no Wi-Fi password or API token.

Snapshot writes occur at most every five minutes or on an attention-state transition. The file is
written to a temporary path then renamed. On reboot, it is rendered strictly as historical/stale
until fresh transport data arrives.

## Device UI

LVGL remains the UI framework. The monolithic dashboard file is split into reusable screen,
component, formatting, navigation, and alert modules.

Three swipeable pages are provided:

1. **Dashboard** — existing sessions, quotas, combined/provider-labelled usage, and heatmap.
2. **Activity** — Claude/Codex breakdown, selectable 12h/24h/7d period, model totals, node status,
   and plan progress for the selected session.
3. **Health** — Wi-Fi/RSSI, transport, payload age, daemon/hooks/storage status, node heartbeats,
   firmware/protocol versions, heap, uptime, and OTA/provisioning actions.

Session cards retain short tap for detail and long press for hide. Detail adds current plan step,
source/quality, node, and `ack`/`snooze` actions. Empty-card selection remains. Alerts escalate by
color and border after configurable age, may be acknowledged or snoozed, and never trigger a remote
agent approval. Night dim remains authoritative over non-critical animations.

The dashboard restores previous behavior when optional v2 fields are absent.

## Dependency and repository reproducibility

- Initialize Git without adding local secrets or build artifacts.
- Pin the currently verified Arduino core platform archive and exact library versions rather than
  compatible ranges.
- Add a Python project metadata file with the WebSocket dependency pinned to a compatible major
  version; all non-WebSocket functionality remains standard-library based.
- Add CI for Python tests, secret scanning, Python compilation, production/demo firmware builds,
  and native protocol helper tests.
- Replace historical contradictions in the main SPEC with a current architecture section and move
  incident history to a separate document.

## Error handling and observability

Every subsystem reports a bounded code and human message into daemon health. One bad provider,
remote node, optional metric, database write, or UI field does not invalidate healthy sources. A
protocol or authentication failure rejects the entire mutation. Logs are structured enough for
`doctor --json`, rotate under the user data directory, and redact tokens, passwords, transcript
content, and prompts.

The device health endpoint adds reset reason, firmware/build/schema versions, Wi-Fi RSSI, transport
mode, sequence, snapshot age, filesystem, OTA partition, queued event count, heap, and UI timing.

## Testing and acceptance

### Python

- Unit tests for configuration precedence/redaction, hook question states, provider normalization,
  combined metrics, context quality, SQLite migrations/reduction/retention, multi-host identity,
  service rendering, doctor checks, protocol v1/v2, and event idempotence.
- Integration tests for satellite-to-aggregator ingestion, device-event round trips, HTTP fallback,
  WebSocket reconnect/sequence, and App Server fixture parsing.

### Firmware

- Host tests for protocol validation, version negotiation, composite IDs, event queues, freshness,
  alert decisions, and snapshot-write throttling.
- Production and demo PlatformIO builds.
- Static assertions and fixture contracts for v1/v2 payload limits.
- Hardware-only checks documented for captive portal, OTA rollback behavior, touch navigation,
  WebSocket reconnect, and rendering restored stale snapshots.

### Completion gates

The work is complete only when:

1. every approved roadmap item has implementation and direct evidence;
2. all automated tests and both firmware builds pass;
3. doctor passes in fixture mode and reports only environmental warnings on the real machine;
4. no credential is found outside ignored/runtime storage;
5. README and current SPEC describe the implemented behavior without historical contradictions;
6. unsupported hardware-only behavior is not claimed as physically verified—build/test evidence and
   a precise hardware validation checklist are reported separately.

