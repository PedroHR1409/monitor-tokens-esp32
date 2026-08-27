# Monitor.AI Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace tightly coupled scanning with provider adapters, durable event history, projection, App Server fixtures, retention, and multi-host aggregation.

**Architecture:** Provider adapters produce normalized observations. An append-only SQLite store reduces them into current state and hourly usage; standalone, satellite, and aggregator roles share the same projector.

**Tech Stack:** Python 3.11+, sqlite3, dataclasses, ThreadingHTTPServer, unittest.

**Spec:** `docs/superpowers/specs/2026-08-27-monitor-ai-complete-evolution-design.md`

## Global Constraints

- Standalone mode needs no remote service or broker.
- Provider failure is isolated and visible in health.
- Prompts/transcript content are never stored; only normalized metadata and counters.
- Composite identity is `(node_id, provider, session_id)`.

---

### Task 1: Normalized provider boundary

**Files:**
- Create: `tools/providers/__init__.py`, `tools/providers/base.py`, `tools/providers/claude.py`, `tools/providers/codex.py`
- Create: `tests/test_providers.py`
- Modify: `tools/session_daemon.py`

**Interfaces:**
- Produces: `ProviderAdapter.observe(now) -> ProviderResult`, `SessionObservation`, `UsageObservation`, `ProviderHealth`.
- Consumes: existing scanner/meta/quota functions as compatibility helpers.

- [ ] Test normalized IDs, qualities, diagnostics, provider failure isolation, and deterministic ordering.
- [ ] Implement frozen dataclasses and thin Claude/Codex adapters.
- [ ] Replace direct scanner calls in the daemon with an injected adapter list.
- [ ] Run provider and legacy daemon tests; commit `refactor: isolate provider telemetry adapters`.

### Task 2: SQLite migrations and append-only events

**Files:**
- Create: `tools/event_store.py`
- Create: `tests/test_event_store.py`

**Interfaces:**
- Produces: `EventStore.open(path)`, `migrate()`, `append_observations()`, `current_sessions()`, `health()`.
- Consumes: normalized provider observations.

- [ ] Test migration from an empty database, repeated migration, transaction rollback, duplicate event id, out-of-order/future diagnostics, and corrupt/open failure.
- [ ] Implement the exact tables from the design with foreign keys, WAL, busy timeout, and explicit transactions.
- [ ] Keep raw normalized metadata only; assert prompt/tool output fields cannot be serialized into event payloads.
- [ ] Run tests and commit `feat: persist normalized session events in sqlite`.

### Task 3: State projector, preferences, and retention

**Files:**
- Create: `tools/projector.py`
- Modify: `tools/event_store.py`
- Create: `tests/test_projector.py`

**Interfaces:**
- Produces: `project_dashboard(store, now, limits)`, `apply_device_event()`, `run_retention()`.
- Consumes: event/current/usage/preference tables.

- [ ] Test urgency/recency ranking, stale nodes, hide/pin/ack/snooze, event idempotence, raw 30-day retention, and 365-day aggregates.
- [ ] Implement projection without UI truncation; move `_previous_board_ids` stability into durable daemon state.
- [ ] Aggregate usage into hourly provider/model rows and expose 12h/24h/7d series.
- [ ] Run tests and commit `feat: project durable dashboard state and history`.

### Task 4: Structured Codex App Server adapter

**Files:**
- Create: `tools/providers/codex_app_server.py`
- Create: `tests/fixtures/app_server/*.jsonl`
- Create: `tests/test_codex_app_server.py`

**Interfaces:**
- Produces: `AppServerReducer.feed(message)`, `snapshot(thread_id)`, `read_ndjson(stream)`.
- Consumes: version-generated App Server JSON-RPC notifications.

- [ ] Add fixtures for turn start/completion, requestUserInput, command/file approval, plan update, token usage, resolved request, reconnect replay, and unknown events.
- [ ] Implement a tolerant tagged-event reducer that treats `item/completed` as authoritative and exposes schema/version health.
- [ ] Add optional subprocess/NDJSON mode without changing existing Codex launch behavior.
- [ ] Run tests and commit `feat: ingest structured Codex App Server events`.

### Task 5: Multi-host authenticated ingestion

**Files:**
- Create: `tools/node_ingest.py`
- Create: `tests/test_node_ingest.py`
- Modify: `tools/monitor.py`
- Modify: `tools/session_daemon.py`

**Interfaces:**
- Produces: `IngestServer`, `SatelliteSender`, `/api/v2/ingest`, node heartbeat/status.
- Consumes: normalized provider batches and shared token.

- [ ] Test valid ingestion, constant-time auth, body limit, replay/sequence rejection, same session IDs on different nodes, stale heartbeat, and satellite retry.
- [ ] Implement ThreadingHTTPServer handlers with bounded JSON, token header, node ID validation, and store transaction.
- [ ] Add standalone/satellite/aggregator CLI/config roles; standalone collects local data and projects it directly.
- [ ] Run tests and commit `feat: aggregate telemetry from multiple monitor nodes`.

### Task 6: History CLI and daemon integration

**Files:**
- Create: `tools/history.py`
- Modify: `tools/monitor.py`
- Modify: `tools/session_daemon.py`
- Create: `tests/test_history.py`

**Interfaces:**
- Produces: `history summary|export|prune`, JSON/CSV export without transcript content.

- [ ] Test period filtering, provider/model/node grouping, deterministic CSV, retention dry-run, and redaction.
- [ ] Integrate store, projector, adapters, App Server input, node roles, and health into each daemon cycle.
- [ ] Preserve `--once` fixture behavior and protocol-v1 fallback.
- [ ] Run full Python suite and commit `feat: expose durable telemetry history`.

