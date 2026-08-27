# Monitor.AI Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish protocol-v2 semantics, honest metrics, exact hook states, reproducible builds, configuration, diagnostics, services, CI, and current documentation.

**Architecture:** Keep the current scanner and HTTP transport working while extracting stable contracts into focused Python modules. New protocol/configuration APIs are consumed by later telemetry and firmware plans; existing CLI flags remain compatible.

**Tech Stack:** Python 3.11+ standard library, unittest, Arduino/PlatformIO, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-27-monitor-ai-complete-evolution-design.md`

## Global Constraints

- Production starts empty; demo data requires `MONITOR_DEMO_DATA=1`.
- No secret may be logged, committed, or returned by diagnostics.
- Unknown Claude context limits remain unknown; never assume a 1M denominator.
- Existing Claude/Codex workflows and protocol-v1 firmware remain usable during migration.
- Arduino, Arduino_GFX, LVGL, and the existing hardware remain in place.

---

### Task 1: Protocol-v2 Python contract

**Files:**
- Create: `tools/protocol_v2.py`
- Create: `tests/test_protocol_v2.py`
- Modify: `tools/session_daemon.py`

**Interfaces:**
- Produces: `SnapshotEnvelope`, `metric_value()`, `build_snapshot_v2()`, `validate_snapshot_v2()`.
- Consumes: current normalized session dictionaries and statistics.

- [ ] Write failing tests for required envelope fields, millisecond timestamp, capabilities, metric quality, composite session keys, numeric bounds, and unsupported versions.
- [ ] Run `python -m unittest tests.test_protocol_v2 -v`; expect import failure.
- [ ] Implement immutable dataclasses/enums and validation. Required construction shape:

```python
snapshot = build_snapshot_v2(
    sessions=sessions, catalog=catalog, usage=usage, quota=quota, health=health,
    node_id=config.node_id, device_id=config.device_id,
    daemon_instance_id=instance_id, sequence=sequence, now=now,
)
assert snapshot["schema_version"] == 2
assert snapshot["message_type"] == "snapshot"
```

- [ ] Add `--protocol 1|2` to the daemon; default to 2 and preserve the existing builder as `build_payload_v1()`.
- [ ] Run new tests plus `tests.test_session_daemon`; expect pass.
- [ ] Commit with `feat: add versioned protocol v2 contract`.

### Task 2: Honest cross-agent usage and context quality

**Files:**
- Create: `tools/usage_model.py`
- Modify: `tools/usage_tracker.py`
- Modify: `tools/session_meta.py`
- Modify: `tools/session_daemon.py`
- Create: `tests/test_usage_model.py`
- Modify: `tests/test_usage_dedup.py`

**Interfaces:**
- Produces: `UsageSeries(provider, buckets, total, quality)`, `combine_usage()`, `context_measurement()`.
- Consumes: Claude transcript samples and Codex rollout totals.

- [ ] Test that Claude-only data is labelled `claude`, compatible Claude+Codex buckets combine, missing Codex never masquerades as combined, and incompatible periods stay separate.
- [ ] Test Claude context with no measured/configured limit returns `{pct: 0, quality: "unknown"}`.
- [ ] Run both test modules; expect failures demonstrating the old Claude-only/1M behavior.
- [ ] Implement provider-labelled series and add Codex hourly/daily accumulation from rollout cumulative token events.
- [ ] Replace `context_usage()`'s unconditional default denominator with measured compaction metadata or explicit `MONITOR_CLAUDE_CONTEXT_WINDOW`; preserve raw current tokens.
- [ ] Run the full Python suite and commit `fix: make usage and context provenance explicit`.

### Task 3: Hook-first question state and non-blocking hooks

**Files:**
- Modify: `tools/session_hook.py`
- Modify: `tools/install_hook.py`
- Modify: `tools/install_codex_hook.py`
- Modify: `tests/test_session_hook.py`
- Modify: `tests/test_claude_state.py`

**Interfaces:**
- Produces: `state_for_action(action, tool_name) -> str` with exact question mapping.
- Consumes: provider hook JSON fields `tool_name|toolName`.

- [ ] Add failing tests proving `PreToolUse/AskUserQuestion` and `ExitPlanMode` record `ask`, question-related `PermissionRequest` never records `perm`, and completion returns to `work`.
- [ ] Implement `state_for_action`; include `AskUserQuestion`, `ExitPlanMode`, `request_user_input`, and `requestUserInput` without treating unknown tools as questions.
- [ ] Mark informational command hooks asynchronous where supported; keep installation fixtures exact and idempotent.
- [ ] Run hook/state tests and commit `fix: derive question state directly from hooks`.

### Task 4: User configuration and redaction

**Files:**
- Create: `tools/monitor_config.py`
- Create: `tests/test_monitor_config.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `MonitorConfig.load(path=None, environ=os.environ)`, `config_path()`, `redacted_dict()`.
- Consumes: TOML plus `MONITOR_*` environment variables.

- [ ] Test platform config paths, default standalone role, TOML parsing, environment precedence, validation, and redaction.
- [ ] Implement frozen nested dataclasses for daemon, device, storage, node, transport, usage, alerts, and service settings using `tomllib`.
- [ ] Provide `write_example(path)` that contains no real secret and writes with restrictive permissions where supported.
- [ ] Run tests and commit `feat: add typed runtime configuration`.

### Task 5: Unified CLI and doctor

**Files:**
- Create: `tools/monitor.py`
- Create: `tools/doctor.py`
- Create: `tests/test_doctor.py`
- Modify: `tools/session_daemon.py`

**Interfaces:**
- Produces: commands `run`, `once`, `doctor`, `config init|show`, `hooks check` and `CheckResult(code, status, message, detail)`.
- Consumes: `MonitorConfig`, hook health, provider paths, SQLite/device probes.

- [ ] Write fixture-based tests for healthy, warning, and failing checks; assert JSON output contains no configured tokens/passwords.
- [ ] Implement composable checks for config, token length, paths, hooks, Python, PlatformIO, storage, device health, and protocol compatibility.
- [ ] Move daemon argument parsing into `run(args, config)` while preserving direct `session_daemon.py` execution.
- [ ] Verify `python tools/monitor.py doctor --fixture tests/fixtures/doctor/healthy.json` exits 0 and real doctor only reports environmental findings.
- [ ] Commit `feat: add monitor CLI and diagnostics`.

### Task 6: Per-user service management

**Files:**
- Create: `tools/service_manager.py`
- Create: `tests/test_service_manager.py`
- Modify: `tools/monitor.py`

**Interfaces:**
- Produces: `render_windows_task()`, `render_systemd_unit()`, `service_install/remove/status(dry_run)`.
- Consumes: absolute Python/repository/config paths.

- [ ] Test quoting of paths with spaces, idempotent dry-runs, Windows XML content, systemd unit hardening, and no administrator-only destination.
- [ ] Implement Windows Scheduled Task via generated XML and `schtasks`, and Linux user unit under `~/.config/systemd/user`.
- [ ] Add CLI `service install|remove|status --dry-run`; never mutate real service state in tests.
- [ ] Run tests and commit `feat: manage daemon as a user service`.

### Task 7: Reproducible dependencies and CI

**Files:**
- Modify: `platformio.ini`
- Create: `pyproject.toml`
- Create: `.github/workflows/ci.yml`
- Modify: `tests/test_production_contracts.py`

**Interfaces:**
- Produces: exact dependency versions and CI gates.

- [ ] Add failing contract tests rejecting caret/range firmware dependencies and requiring CI commands.
- [ ] Pin verified versions: LVGL 9.5.0, GFX Library 1.6.7, ArduinoJson 7.4.3; keep the exact pioarduino 55.03.311 archive.
- [ ] Add Python metadata with optional `websocket` dependency consumed by the transport plan.
- [ ] Add CI for unittest, compileall, secret scan, production build, demo build, and native tests.
- [ ] Run contracts and both PlatformIO builds; commit `ci: pin dependencies and verify all builds`.

### Task 8: Current documentation split

**Files:**
- Modify: `README.md`
- Rewrite: `docs/SPEC.md`
- Create: `docs/HISTORY.md`
- Create: `docs/HARDWARE_VALIDATION.md`

**Interfaces:**
- Produces: current setup/architecture docs, preserved incident history, hardware-only checklist.

- [ ] Add a documentation contract test for AXS15231B touch, protocol v2, doctor, service, explicit metric provenance, and absence of superseded MVP claims in current SPEC.
- [ ] Move historical phase/incident narrative to `HISTORY.md`; make `SPEC.md` describe only current behavior and link the evolution design.
- [ ] Document direct CLI compatibility, service install, config, security boundary, and exact verification commands.
- [ ] Run all tests and builds; commit `docs: align setup and architecture with protocol v2`.

