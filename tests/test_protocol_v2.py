from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from protocol_v2 import (  # noqa: E402
    MetricQuality,
    SnapshotEnvelope,
    UnsupportedProtocolVersion,
    build_snapshot_v2,
    metric_value,
    validate_snapshot_v2,
)
import session_daemon  # noqa: E402


NOW = datetime(2026, 8, 27, 12, 0, 0, 123000, tzinfo=timezone.utc)


def build_snapshot(**overrides) -> dict:
    values = {
        "sessions": [{"id": "session-7", "tool": "claude", "state": "work",
                      "ctxPct": None, "tokensWin": 42}],
        "catalog": [{"id": "session-8", "tool": "codex", "state": "free"}],
        "usage": {"today": metric_value(42, quality=MetricQuality.MEASURED,
                                           unit="tokens")},
        "quota": {"claude": metric_value(None, quality=MetricQuality.UNKNOWN,
                                            unit="percent")},
        "health": {"claude_hook": "ok"},
        "node_id": "office-node",
        "device_id": "desk-display",
        "daemon_instance_id": "daemon-17",
        "sequence": 9,
        "now": NOW,
    }
    values.update(overrides)
    return build_snapshot_v2(**values)


class SnapshotEnvelopeTests(unittest.TestCase):
    def test_required_envelope_fields_are_stable(self):
        """Removing an envelope identity/block would break a v2 device consumer."""
        snapshot = build_snapshot()
        self.assertEqual(2, snapshot["schema_version"])
        self.assertEqual("snapshot", snapshot["message_type"])
        self.assertEqual("office-node", snapshot["node_id"])
        self.assertEqual("desk-display", snapshot["device_id"])
        self.assertEqual("daemon-17", snapshot["daemon_instance_id"])
        self.assertEqual(9, snapshot["sequence"])
        self.assertEqual({"sessions", "catalog", "stats", "health", "nodes"},
                         {key for key in ("sessions", "catalog", "stats", "health", "nodes")
                          if key in snapshot})
        self.assertIsInstance(SnapshotEnvelope(
            node_id="n", device_id="d", daemon_instance_id="i", sequence=0,
            generated_at_epoch_ms=1), SnapshotEnvelope)

    def test_timestamp_keeps_millisecond_precision(self):
        """Truncating a snapshot timestamp to seconds would break ordering at 5s cadence."""
        snapshot = build_snapshot()
        self.assertEqual(1787832000123, snapshot["generated_at_epoch_ms"])

    def test_capabilities_advertise_optional_v2_semantics(self):
        """Dropping a capability would make receivers silently ignore supported fields."""
        snapshot = build_snapshot()
        self.assertEqual(["metric_quality", "composite_session_keys"],
                         snapshot["capabilities"])

    def test_metric_quality_preserves_unknown_claude_limit(self):
        """Inventing a number for an unknown Claude limit would mislead the UI."""
        unknown = metric_value(None, quality=MetricQuality.UNKNOWN, unit="percent")
        measured = metric_value(42, quality="measured", unit="tokens")
        self.assertEqual({"value": None, "quality": "unknown", "unit": "percent"}, unknown)
        self.assertEqual({"value": 42, "quality": "measured", "unit": "tokens"}, measured)

    def test_unknown_metric_rejects_a_numeric_value(self):
        """A numeric unknown value would reintroduce a fabricated metric into the UI."""
        with self.assertRaises(ValueError):
            metric_value(42, quality=MetricQuality.UNKNOWN, unit="percent")

    def test_claude_legacy_context_percentage_becomes_unknown(self):
        """Forwarding legacy Claude ctxPct would pretend its unproven denominator is known."""
        snapshot = build_snapshot(sessions=[{
            "id": "claude-session", "tool": "claude", "state": "work", "ctxPct": 99,
        }])
        session = snapshot["sessions"][0]
        self.assertIsNone(session["ctxPct"])
        self.assertEqual({"value": None, "quality": "unknown", "unit": "percent"},
                         session["context"])

    def test_sessions_receive_composite_keys(self):
        """Using only session IDs would collide for sessions from separate nodes/providers."""
        snapshot = build_snapshot()
        session = snapshot["sessions"][0]
        self.assertEqual("office-node:claude:session-7", session["session_key"])
        self.assertEqual("office-node", session["node_id"])
        self.assertEqual("claude", session["provider"])
        self.assertEqual("session-7", session["session_id"])

    def test_numeric_bounds_reject_invalid_sequence_and_percent(self):
        """Accepting negative sequences or 101% would violate receiver numeric bounds."""
        with self.assertRaises(ValueError):
            build_snapshot(sequence=-1)
        with self.assertRaises(ValueError):
            metric_value(101, quality="official", unit="percent")

    def test_unsupported_schema_versions_are_rejected(self):
        """Accepting a future major schema could partially mutate an incompatible receiver."""
        snapshot = build_snapshot()
        snapshot["schema_version"] = 3
        with self.assertRaises(UnsupportedProtocolVersion):
            validate_snapshot_v2(snapshot)

    def test_duplicate_catalog_composite_identity_is_rejected(self):
        """A duplicated catalog identity would make an action target ambiguous."""
        snapshot = build_snapshot()
        snapshot["catalog"].append(dict(snapshot["catalog"][0]))
        with self.assertRaises(ValueError):
            validate_snapshot_v2(snapshot)

    def test_malformed_catalog_composite_identity_is_rejected(self):
        """A catalog key that does not match its node/provider/session must not be accepted."""
        snapshot = build_snapshot()
        snapshot["catalog"][0]["session_key"] = "not-a-composite-key"
        with self.assertRaises(ValueError):
            validate_snapshot_v2(snapshot)

    def test_secret_transport_keys_are_rejected_recursively(self):
        """A secret-shaped key at any nesting level must never enter a device snapshot."""
        for key in ("token", "access_token", "x-monitor-token", "refreshToken"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    build_snapshot(health={"nested": {key: "not-for-device"}})

    def test_token_window_count_is_not_treated_as_a_secret(self):
        """Rejecting the public token-window duration would make ordinary v2 snapshots fail."""
        snapshot = build_snapshot(usage={"token_window_h": 12})
        self.assertEqual(12, snapshot["stats"]["usage"]["token_window_h"])


class SessionDaemonProtocolSelectionTests(unittest.TestCase):
    def test_daemon_defaults_to_v2_and_retains_explicit_v1_choice(self):
        """Changing the default or removing v1 would break the staged firmware migration."""
        self.assertEqual(2, session_daemon.parse_args([]).protocol)
        self.assertEqual(1, session_daemon.parse_args(["--protocol", "1"]).protocol)
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                session_daemon.parse_args(["--protocol", "3"])

    def test_daemon_keeps_v1_builder_and_projects_its_data_to_v2(self):
        """A protocol switch must retain the old payload while producing a complete v2 envelope."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            v1 = session_daemon.build_payload_v1(
                root / "claude", root / "missing-index", 6, timezone.utc, now=NOW)
            v2 = session_daemon.build_payload_v2(
                root / "claude", root / "missing-index", 6, timezone.utc,
                node_id="office-node", device_id="desk-display",
                daemon_instance_id="daemon-17", sequence=9, now=NOW)
        self.assertEqual(int(NOW.timestamp()), v1["generated_at_epoch"])
        self.assertEqual(2, v2["schema_version"])
        self.assertEqual("snapshot", v2["message_type"])


if __name__ == "__main__":
    unittest.main()
