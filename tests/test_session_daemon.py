from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import session_daemon
import session_meta
from monitor_config import MonitorConfig
from session_hook import record_event


NOW = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)


class CodexClassificationTests(unittest.TestCase):
    def write_index(self, directory: Path, entries: list[dict]) -> Path:
        path = directory / "session_index.jsonl"
        path.write_text("".join(json.dumps(item) + "\n" for item in entries), encoding="utf-8")
        return path

    def test_recent_index_entry_does_not_invent_ask_or_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = self.write_index(Path(tmp), [{
                "id": "codex-session-1234567890-complete",
                "thread_name": "same-prefix-project-alpha",
                "updated_at": (NOW - timedelta(seconds=45)).isoformat(),
            }])
            sessions = session_daemon.scan_codex_sessions(
                index, NOW, event_path=Path(tmp) / "missing-events.json")
        self.assertEqual("free", sessions[0]["state"])
        self.assertTrue(sessions[0]["source_stale"])

    def test_full_ids_distinguish_equal_names_and_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            entries = [
                {"id": "123456789012345-A", "thread_name": "equal-name",
                 "updated_at": NOW.isoformat()},
                {"id": "123456789012345-B", "thread_name": "equal-name",
                 "updated_at": NOW.isoformat()},
            ]
            sessions = session_daemon.scan_codex_sessions(
                self.write_index(Path(tmp), entries), NOW,
                event_path=Path(tmp) / "missing-events.json")
        self.assertEqual({entry["id"] for entry in entries}, {s["id"] for s in sessions})

    def test_invalid_missing_and_naive_index_timestamps_degrade_per_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            entries = [
                {"id": "invalid-ts", "thread_name": "one", "updated_at": "not-a-date"},
                {"id": "missing-ts", "thread_name": "two"},
                {"id": "naive-ts", "thread_name": "three",
                 "updated_at": "2026-08-27T14:59:00"},
            ]
            sessions = session_daemon.scan_codex_sessions(
                self.write_index(Path(tmp), entries), NOW,
                event_path=Path(tmp) / "missing-events.json")
        self.assertEqual(3, len(sessions))
        self.assertEqual({"free"}, {session["state"] for session in sessions})
        self.assertTrue(all(session["source_stale"] for session in sessions))
        self.assertTrue(all(session["_age"] == float("inf") for session in sessions))

    def test_far_future_index_timestamp_is_stale_not_age_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = self.write_index(Path(tmp), [{
                "id": "future-ts", "thread_name": "future",
                "updated_at": (NOW + timedelta(days=365)).isoformat(),
            }])
            sessions = session_daemon.scan_codex_sessions(
                index, NOW, event_path=Path(tmp) / "missing-events.json")
        self.assertEqual("free", sessions[0]["state"])
        self.assertTrue(sessions[0]["source_stale"])
        self.assertEqual(float("inf"), sessions[0]["_age"])

    def test_explicit_permission_event_is_the_only_path_to_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_id = "codex-permission-complete-id"
            index = self.write_index(root, [{
                "id": session_id, "thread_name": "project", "updated_at": NOW.isoformat()}])
            events = root / "events.json"
            record_event({"session_id": session_id, "tool_name": "Bash"},
                         "permission_request", events, NOW)
            sessions = session_daemon.scan_codex_sessions(index, NOW, event_path=events)
        self.assertEqual("perm", sessions[0]["state"])
        self.assertFalse(sessions[0]["source_stale"])

    def test_long_running_codex_command_remains_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_id = "codex-long-command-complete-id"
            index = self.write_index(root, [{
                "id": session_id, "thread_name": "project",
                "updated_at": (NOW - timedelta(minutes=20)).isoformat()}])
            events = root / "events.json"
            record_event({"session_id": session_id, "tool_name": "Bash"},
                         "work", events, NOW - timedelta(minutes=20))
            sessions = session_daemon.scan_codex_sessions(index, NOW, event_path=events)
        self.assertEqual("work", sessions[0]["state"])
        self.assertTrue(sessions[0]["source_stale"])

    def test_explicitly_ended_codex_session_leaves_the_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_id = "codex-ended-complete-id"
            index = self.write_index(root, [{
                "id": session_id, "thread_name": "project",
                "updated_at": NOW.isoformat()}])
            events = root / "events.json"
            record_event({"session_id": session_id}, "ended", events, NOW)
            sessions = session_daemon.scan_codex_sessions(index, NOW, event_path=events)
        self.assertEqual([], sessions)


class RankingTests(unittest.TestCase):
    def test_attention_states_rank_before_recency(self):
        sessions = [
            {"id": "free", "state": "free", "_age": 1},
            {"id": "work", "state": "work", "_age": 2},
            {"id": "ask", "state": "ask", "_age": 3},
            {"id": "perm", "state": "perm", "_age": 4},
        ]
        ranked = session_daemon.rank_sessions(sessions, previous_ids=[])
        self.assertEqual(["perm", "ask", "work", "free"], [s["id"] for s in ranked])

    def test_previous_order_breaks_exact_recency_ties(self):
        sessions = [
            {"id": "second", "state": "work", "_age": 10},
            {"id": "first", "state": "work", "_age": 10},
        ]
        ranked = session_daemon.rank_sessions(sessions, previous_ids=["first", "second"])
        self.assertEqual(["first", "second"], [s["id"] for s in ranked])

    def test_fresh_work_ranks_before_historical_stale_permission(self):
        sessions = [
            {"id": "old-perm", "state": "perm", "source_stale": True, "_age": 80},
            {"id": "live-work", "state": "work", "source_stale": False, "_age": 2},
        ]
        ranked = session_daemon.rank_sessions(sessions, previous_ids=[])
        self.assertEqual(["live-work", "old-perm"], [s["id"] for s in ranked])


class ClaudeDaemonIntegrationTests(unittest.TestCase):
    def write_transcript(self, root: Path, session_id: str, filename: str) -> None:
        project = root / "project"
        project.mkdir(exist_ok=True)
        obj = {
            "type": "assistant", "sessionId": session_id,
            "timestamp": NOW.isoformat(), "cwd": str(root / "same-name"),
            "message": {"model": "claude-test", "content": [{
                "type": "tool_use", "name": "Bash", "id": "tool-1"}]},
        }
        (project / filename).write_text(json.dumps(obj) + "\n", encoding="utf-8")

    def test_claude_full_ids_and_explicit_permission_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = "123456789012345-claude-A"
            second = "123456789012345-claude-B"
            self.write_transcript(root, first, "a.jsonl")
            self.write_transcript(root, second, "b.jsonl")
            events = root / "events.json"
            record_event({"session_id": second, "tool_name": "Bash"},
                         "permission_request", events, NOW)
            sessions = session_daemon.scan_claude_sessions(
                root, NOW, event_path=events, legacy_perm_path=root / "missing.json")
        self.assertEqual({first, second}, {s["id"] for s in sessions})
        by_id = {s["id"]: s for s in sessions}
        self.assertEqual("work", by_id[first]["state"])
        self.assertEqual("perm", by_id[second]["state"])


class IdentityFilterTests(unittest.TestCase):
    def test_dismiss_filters_by_full_id_not_equal_display_name(self):
        sessions = [
            {"id": "full-A", "project": "same-name"},
            {"id": "full-B", "project": "same-name"},
        ]
        visible = session_daemon.filter_dismissed(sessions, {"full-A"})
        self.assertEqual(["full-B"], [s["id"] for s in visible])


class PayloadFreshnessTests(unittest.TestCase):
    def test_payload_carries_machine_readable_generation_epoch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = session_daemon.build_payload(
                root / "claude", root / "missing-index", 6,
                timezone.utc, now=NOW)
        self.assertEqual(int(NOW.timestamp()), payload["generated_at_epoch"])

    def test_daemon_sends_shared_token_without_putting_it_in_url(self):
        previous = session_daemon.MONITOR_API_TOKEN
        try:
            session_daemon.MONITOR_API_TOKEN = "test-token-not-real"
            request = session_daemon.authenticated_request("http://device/sessions")
        finally:
            session_daemon.MONITOR_API_TOKEN = previous
        self.assertEqual("test-token-not-real", request.get_header("X-monitor-token"))
        self.assertNotIn("test-token-not-real", request.full_url)

    def test_v2_suppresses_out_of_range_legacy_claude_context(self):
        """A legacy 999% Claude estimate must not terminate or contaminate a v2 snapshot."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "claude" / "project"
            project.mkdir(parents=True)
            transcript = {
                "type": "assistant", "sessionId": "claude-context-999",
                "timestamp": NOW.isoformat(), "cwd": str(root / "project"),
                "message": {"model": "claude-test", "content": [{
                    "type": "tool_use", "name": "Bash", "id": "tool-1",
                }], "usage": {"input_tokens": 9_990_000}},
            }
            (project / "session.jsonl").write_text(json.dumps(transcript) + "\n",
                                                    encoding="utf-8")
            payload = session_daemon.build_payload_v2(
                root / "claude", root / "missing-index", 6, timezone.utc,
                node_id="office-node", device_id="desk-display",
                daemon_instance_id="daemon-17", sequence=9, now=NOW)
        session = payload["sessions"][0]
        self.assertIsNone(session["ctxPct"])
        self.assertEqual({"value": None, "quality": "unknown", "unit": "percent"},
                         session["context"])

    def test_default_v2_main_posts_series_payload_without_legacy_tokens_today(self):
        """Reading a v1-only total after POST would crash the default v2 daemon loop."""
        args = SimpleNamespace(host="device", port=80, interval=5.0,
                               tz_offset=0.0, claude_dir="claude",
                               codex_index="codex-index", max_sessions=6,
                               protocol=2, once=True)
        payload = {"sessions": [], "stats": {"usage": {
            "series": [{"provider": "claude", "buckets": {}, "total": 0,
                        "quality": "measured"}],
            "active_12h": 0,
        }}}
        with patch.object(session_daemon, "parse_args", return_value=args), \
             patch.object(session_daemon, "fetch_id_list", return_value=set()), \
             patch.object(session_daemon, "build_payload_v2", return_value=payload), \
             patch.object(session_daemon, "post_sessions", return_value=True) as posted, \
             patch.object(session_daemon, "hook_warnings", return_value=[]):
            session_daemon.main()
        posted.assert_called_once()

    def test_run_accepts_a_config_snapshot_without_breaking_one_cycle_execution(self):
        """Ignoring config.device would make the unified CLI send to the wrong display."""
        args = SimpleNamespace(host=None, port=None, interval=None,
                               tz_offset=0.0, claude_dir="claude",
                               codex_index="codex-index", max_sessions=6,
                               protocol=2, once=True)
        config = MonitorConfig.load("missing-monitor.toml", environ={})
        payload = {"sessions": [], "stats": {"usage": {
            "series": [], "active_12h": 0,
        }}}
        with patch.object(session_daemon, "fetch_id_list", return_value=set()), \
             patch.object(session_daemon, "build_payload_v2", return_value=payload), \
             patch.object(session_daemon, "post_sessions", return_value=True) as posted, \
             patch.object(session_daemon, "hook_warnings", return_value=[]):
            self.assertEqual(0, session_daemon.run(args, config))
        self.assertTrue(posted.call_args.args[0].startswith("http://monitor-ai.local:80/"))


class CodexWindowTokenTests(unittest.TestCase):
    def test_rollout_counter_reset_keeps_new_usage_inside_session_window(self):
        """Clamping a negative cumulative delta would lose post-reset Codex usage."""
        with tempfile.TemporaryDirectory() as tmp:
            rollout = Path(tmp) / "rollout-reset.jsonl"
            events = [
                {"timestamp": (NOW - timedelta(hours=2)).isoformat(), "payload": {"info": {
                    "total_token_usage": {"total_tokens": 100}}}},
                {"timestamp": NOW.isoformat(), "payload": {"info": {
                    "total_token_usage": {"total_tokens": 40}}}},
            ]
            rollout.write_text("".join(json.dumps(event) + "\n" for event in events),
                               encoding="utf-8")
            session_meta._meta_cache.clear()
            with patch.object(session_meta, "_rollout_for", return_value=rollout):
                meta = session_meta.codex_meta("reset-session", NOW - timedelta(hours=1))
        self.assertEqual(40, meta["tokens"])


if __name__ == "__main__":
    unittest.main()
