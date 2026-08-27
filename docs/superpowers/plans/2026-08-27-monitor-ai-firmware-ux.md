# Monitor.AI Firmware and UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add runtime provisioning, authenticated OTA, health/activity pages, plan progress, and safe configurable alert controls to the ESP32 dashboard.

**Architecture:** Runtime configuration is versioned in NVS and drives network/time/brightness/alerts. LVGL screens are split by responsibility and navigate through horizontal gestures while preserving the existing dashboard interactions.

**Tech Stack:** Arduino-ESP32, Preferences, WiFi/DNSServer/WebServer, Update, LittleFS, LVGL 9.5, ArduinoJson.

**Spec:** `docs/superpowers/specs/2026-08-27-monitor-ai-complete-evolution-design.md`

## Global Constraints

- Provisioning and OTA never reveal stored credentials.
- OTA requires a configured token of at least 16 bytes.
- Device controls never approve or execute agent commands.
- Existing card detail/hide/pin behavior remains available.

---

### Task 1: Versioned runtime device configuration

**Files:**
- Create: `src/device_config.h`, `src/device_config.cpp`
- Modify: `include/config.h`, `src/device_time.cpp`, `src/session_transport.cpp`
- Create: `tests/native/test_device_config.cpp`

**Interfaces:**
- Produces: `DeviceConfig`, `device_config_begin/get/save/reset`, CRC/version validation.

- [ ] Test defaults, secrets.h migration, length bounds, CRC, version rejection, timezone, brightness and alert ranges.
- [ ] Implement NVS double-buffered records; runtime values override compile-time fallback.
- [ ] Route Wi-Fi, auth, timezone, brightness, names, and alert thresholds through configuration.
- [ ] Build/test and commit `feat: store versioned runtime device configuration`.

### Task 2: SoftAP captive provisioning

**Files:**
- Create: `src/provisioning.h`, `src/provisioning.cpp`
- Modify: `src/main.cpp`, `src/session_transport.cpp`
- Modify: `tests/test_production_contracts.py`

**Interfaces:**
- Produces: `provisioning_should_start()`, `provisioning_begin/loop/stop`, authenticated reset confirmation.

- [ ] Add contracts for unique AP name, DNS captive response, form limits, redacted status, atomic save, and reboot.
- [ ] Implement first-boot/invalid/repeated-failure SoftAP portal using DNSServer and WebServer.
- [ ] Add a long-press empty-dashboard confirmation flow that resets runtime network configuration only after explicit confirmation.
- [ ] Build and commit `feat: provision monitor over captive portal`.

### Task 3: Authenticated OTA and version health

**Files:**
- Create: `src/ota_update.h`, `src/ota_update.cpp`
- Modify: `src/session_transport.cpp`, `src/session_model.h`, `src/main.cpp`
- Create: `include/version.h`

**Interfaces:**
- Produces: `/update` page/upload, `FirmwareInfo`, update status.

- [ ] Add route/security contracts for strong token, upload size/type, Update errors, inactive partition, and no unauthenticated form.
- [ ] Implement streaming upload with `Update.begin/write/end`; reboot only after successful verification.
- [ ] Expose semantic firmware version, build ID, schema versions, running partition, and last OTA result in health.
- [ ] Build both environments and commit `feat: update firmware securely over lan`.

### Task 4: Split UI and navigation shell

**Files:**
- Create: `src/ui/ui_common.h/.cpp`, `src/ui/ui_navigation.h/.cpp`, `src/ui/ui_dashboard_screen.h/.cpp`
- Modify: `src/ui_dashboard.cpp`, `src/ui_dashboard.h`, `src/main.cpp`, `include/ui_theme.h`

**Interfaces:**
- Produces: `ui_navigation_init()`, `ui_show_page()`, reusable cached label/color helpers.

- [ ] Add build contracts preventing duplicate global state and requiring dashboard/activity/health pages.
- [ ] Move existing dashboard behavior without visual semantic changes into a focused screen module.
- [ ] Implement horizontal swipe navigation and page indicator; ensure vertical list gestures and card long-press are not stolen.
- [ ] Build demo/production and commit `refactor: split dashboard into navigable screens`.

### Task 5: Activity and health pages

**Files:**
- Create: `src/ui/ui_activity_screen.h/.cpp`, `src/ui/ui_health_screen.h/.cpp`
- Modify: `include/session_model.h`, `src/session_transport.cpp`, `include/ui_theme.h`

**Interfaces:**
- Produces: activity period selector, provider/model/node summaries, health diagnostics and action buttons.

- [ ] Add formatting tests/contracts for 12h/24h/7d, quality labels, missing data, stale nodes, versions and errors.
- [ ] Implement Activity with provider totals, hourly bars/heatmap, model summary, node chips, and selected-session plan progress.
- [ ] Implement Health with RSSI, transport/payload age, daemon/hooks/storage/nodes, firmware/schema, heap/uptime/filesystem/OTA and provisioning actions.
- [ ] Build both environments and commit `feat: add activity and health screens`.

### Task 6: Plan progress and safe alert controls

**Files:**
- Create: `src/ui/ui_alerts.h/.cpp`
- Modify: `src/ui/ui_dashboard_screen.cpp`, `src/ui/ui_activity_screen.cpp`, `src/session_transport.cpp`, `include/session_model.h`
- Create: `tests/native/test_alert_policy.cpp`

**Interfaces:**
- Produces: `alert_level(session, now, config)`, ack/snooze/hide/pin device events.

- [ ] Test attention escalation, stale suppression, acknowledgement, snooze expiry, night dim, and absence of approve/deny/execute actions.
- [ ] Add compact plan completed/total indicator on cards and current step in detail/activity.
- [ ] Add explicit acknowledge and configurable snooze actions; queue v2 device events and display pending/offline status.
- [ ] Build/test and commit `feat: surface progress and configurable attention alerts`.

### Task 7: Final docs and hardware checklist

**Files:**
- Modify: `README.md`, `docs/SPEC.md`, `docs/HARDWARE_VALIDATION.md`
- Modify: `tests/test_production_contracts.py`

**Interfaces:**
- Produces: end-to-end operator documentation and precise unverified hardware checklist.

- [ ] Document first boot, portal, service, WebSocket/HTTP fallback, OTA, pages, gestures, history, multi-host, App Server option, recovery and security boundary.
- [ ] Add hardware checks for portal DNS, actual credential join, OTA success/rollback, touch navigation, reconnect, restored snapshot, display performance and flash wear cadence.
- [ ] Run the completion audit: full Python/native tests, secret scan, production/demo builds, fixture doctor, git status, and requirement-to-evidence matrix.
- [ ] Commit `docs: complete monitor appliance operations guide`.

