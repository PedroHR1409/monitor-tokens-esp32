from __future__ import annotations

import json
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import redirect_stdout

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import session_daemon
import session_meta
from monitor_config import MonitorConfig
from session_hook import record_event


NOW = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)


class TransportTimestampTests(unittest.TestCase):
    def test_refreshes_v1_timestamp_after_slow_collection(self):
        payload = {"generated_at": "old", "generated_at_epoch": 100}
        result = session_daemon.refresh_transport_timestamp(
            payload, previous_epoch=100, now=NOW)
        self.assertEqual(int(NOW.timestamp()), result)
        self.assertEqual(result, payload["generated_at_epoch"])
        self.assertEqual(NOW.isoformat(), payload["generated_at"])

    def test_keeps_v1_timestamp_monotonic_within_daemon(self):
        payload = {"generated_at": "old", "generated_at_epoch": 100}
        result = session_daemon.refresh_transport_timestamp(
            payload, previous_epoch=int(NOW.timestamp()), now=NOW)
        self.assertEqual(int(NOW.timestamp()) + 1, result)

    def test_refreshes_v2_millisecond_timestamp(self):
        payload = {"generated_at_epoch_ms": 100}
        result = session_daemon.refresh_transport_timestamp(
            payload, previous_epoch=100, now=NOW)
        expected = int(NOW.timestamp() * 1000)
        self.assertEqual(expected, result)
        self.assertEqual(expected, payload["generated_at_epoch_ms"])


class DaemonOptionTests(unittest.TestCase):
    def test_configured_timezone_is_used_when_no_cli_offset_is_given(self):
        config = MonitorConfig.load("missing-monitor.toml", environ={})
        resolved = session_daemon._resolve_timezone(SimpleNamespace(tz_offset=None), config)
        self.assertEqual("America/Sao_Paulo", resolved.key)

    def test_cli_timezone_offset_overrides_configured_timezone(self):
        config = MonitorConfig.load("missing-monitor.toml", environ={})
        resolved = session_daemon._resolve_timezone(SimpleNamespace(tz_offset=0.0), config)
        self.assertEqual(0, resolved.utcoffset(None).total_seconds())

    def test_max_sessions_cannot_exceed_firmware_capacity(self):
        with self.assertRaises(SystemExit):
            session_daemon.parse_args(["--max-sessions", "7"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "between 1 and 6"):
                session_daemon.build_payload_v1(
                    root / "claude", root / "index", 7, timezone.utc, now=NOW)


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

    def test_state_database_discovers_live_thread_when_index_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "state.sqlite"
            connection = sqlite3.connect(db)
            connection.execute(
                "CREATE TABLE threads ("
                "id TEXT PRIMARY KEY, title TEXT, name TEXT, updated_at INTEGER, "
                "updated_at_ms INTEGER, cwd TEXT, model TEXT, reasoning_effort TEXT, "
                "archived INTEGER)"
            )
            connection.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("db-live", "Live Codex", "", int(NOW.timestamp()),
                 int(NOW.timestamp() * 1000), str(root), "gpt-live", "high", 0),
            )
            connection.commit()
            connection.close()

            sessions = session_daemon.scan_codex_sessions(
                root / "missing-index.jsonl", NOW,
                event_path=root / "missing-events.json",
                state_db=db)

        self.assertEqual(["db-live"], [item["id"] for item in sessions])
        self.assertEqual("work", sessions[0]["state"])
        self.assertEqual("Live Codex", sessions[0]["project"])
        self.assertEqual("gpt-live", sessions[0]["model"])


class CodexRolloutDiscoveryTests(unittest.TestCase):
    """O session_index parou de receber sessoes novas (15/09/2026) e os hooks do
    Codex nunca gravaram evento nesta maquina: a sessao nova nem aparecia e, quando
    aparecia pelo indice, sempre ficava `free`. O rollout no disco e a identidade
    E o sinal de vida."""

    ROLLOUT = ("rollout-2026-09-15T10-40-04-"
               "01a0a54b-d23e-7d10-b980-539fde366c30.jsonl")
    SID = "01a0a54b-d23e-7d10-b980-539fde366c30"

    def write_rollout(self, directory: Path, mtime: datetime) -> None:
        path = directory / "2026" / "08" / "27" / self.ROLLOUT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"timestamp":"2026-08-27T14:00:00Z","payload":{}}\n',
                        encoding="utf-8")
        epoch = mtime.timestamp()
        os.utime(path, (epoch, epoch))

    def test_session_only_on_disk_is_discovered_and_turn_is_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_rollout(root / "sessions", NOW)
            sessions = session_daemon.scan_codex_sessions(
                root / "session_index.jsonl", NOW, rollouts_dir=root / "sessions")
        self.assertEqual([self.SID], [s["id"] for s in sessions])
        self.assertEqual("work", sessions[0]["state"])   # rollout fresco = turno vivo
        self.assertEqual("no_structured_event", sessions[0]["diagnostic"])
        self.assertEqual(0, sessions[0]["elapsed"])

    def test_index_recency_wins_when_newer_than_rollout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_rollout(root / "sessions", NOW - timedelta(minutes=10))
            index = root / "session_index.jsonl"
            index.write_text(json.dumps({
                "id": self.SID, "thread_name": "proj",
                "updated_at": NOW.isoformat()}) + "\n", encoding="utf-8")
            sessions = session_daemon.scan_codex_sessions(
                index, NOW, rollouts_dir=root / "sessions")
        self.assertEqual(0, sessions[0]["_age"])         # indice mais novo vence
        self.assertEqual("work", sessions[0]["state"])   # rollout de 10min = dentro da janela

    def test_idle_rollout_beyond_work_window_is_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_rollout(root / "sessions", NOW - timedelta(hours=2))
            sessions = session_daemon.scan_codex_sessions(
                root / "session_index.jsonl", NOW, rollouts_dir=root / "sessions")
        self.assertEqual("free", sessions[0]["state"])

    def test_rollout_scan_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_rollout(root / "sessions", NOW)
            sessions = session_daemon.scan_codex_sessions(
                root / "session_index.jsonl", NOW)
        self.assertEqual([], sessions)    # hermetico: sem rollouts_dir, nada vaza

    def test_structured_event_wins_over_rollout_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_rollout(root / "sessions", NOW)
            events = root / "events.json"
            record_event({"session_id": self.SID}, "free", events, NOW)
            sessions = session_daemon.scan_codex_sessions(
                root / "session_index.jsonl", NOW, event_path=events,
                rollouts_dir=root / "sessions")
        self.assertEqual("free", sessions[0]["state"])   # hook vence o mtime


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


class MetaModelTests(unittest.TestCase):
    def test_synthetic_model_is_skipped_for_the_real_one(self):
        """Mensagem assistant `<synthetic>` (erro/interrupcao do harness) nao e
        modelo: a tela de detalhe mostrava `<synthetic>` quando ela era a ultima
        da sessao (medido no card k1co). O modelo real anterior vence."""
        objs = [
            {"type": "assistant",
             "message": {"model": "claude-opus-5", "content": []}},
            {"type": "assistant",
             "message": {"model": "<synthetic>", "content": []}},
        ]
        branch, model, effort = session_daemon.meta_of(objs)
        self.assertEqual("opus-5", model)
        self.assertEqual("", branch)

    def test_only_synthetic_models_leaves_model_empty(self):
        objs = [{"type": "assistant",
                 "message": {"model": "<synthetic>", "content": []}}]
        _, model, _ = session_daemon.meta_of(objs)
        self.assertEqual("", model)


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

    def test_v2_uses_the_configured_claude_context_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "claude" / "project"
            project.mkdir(parents=True)
            transcript = {
                "type": "assistant", "sessionId": "claude-context-configured",
                "timestamp": NOW.isoformat(), "cwd": str(root / "project"),
                "message": {"model": "claude-test", "content": [],
                            "usage": {"input_tokens": 50_000}},
            }
            (project / "session.jsonl").write_text(json.dumps(transcript) + "\n",
                                                    encoding="utf-8")
            with patch.dict(os.environ, {"MONITOR_CLAUDE_CONTEXT_WINDOW": ""}):
                payload = session_daemon.build_payload_v2(
                    root / "claude", root / "missing-index", 6, timezone.utc,
                    node_id="office-node", device_id="desk-display",
                    daemon_instance_id="daemon-18", sequence=10, now=NOW,
                    claude_context_window=100_000)
        session = payload["sessions"][0]
        self.assertIsNone(session["ctxPct"])
        self.assertEqual(50, session["context"]["value"])
        self.assertEqual("configured", session["context"]["quality"])

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
             patch.object(session_daemon, "post_sessions", return_value=200) as posted, \
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
             patch.object(session_daemon, "post_sessions", return_value=200) as posted, \
             patch.object(session_daemon, "hook_warnings", return_value=[]):
            self.assertEqual(0, session_daemon.run(args, config))
        self.assertTrue(posted.call_args.args[0].startswith("http://monitor-ai.local:80/"))

    def test_run_uses_resolved_host_as_v2_device_id_without_mocking_the_builder(self):
        """Passing args.host=None into v2 would reject the unified CLI defaults."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = SimpleNamespace(host=None, port=None, interval=None,
                                   tz_offset=0.0, claude_dir=str(root / "claude"),
                                   codex_index=str(root / "codex-index"), max_sessions=6,
                                   protocol=2, once=True)
            config = MonitorConfig.load(root / "monitor.toml", environ={})
            with patch.object(session_daemon, "fetch_id_list", return_value=set()), \
                 patch.object(session_daemon, "post_sessions", return_value=200) as posted, \
                 patch.object(session_daemon, "hook_warnings", return_value=[]):
                self.assertEqual(0, session_daemon.run(args, config))
        self.assertEqual("monitor-ai.local", posted.call_args.args[1]["device_id"])

    def test_run_posts_the_configured_token_without_logging_it(self):
        """Ignoring config.transport.api_token would diagnose a credential then omit it on POST."""
        configured_token = "config-token-header-only-123456"

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        captured = []
        def receive(request, timeout):
            captured.append(request)
            return Response()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = SimpleNamespace(host="test-device", port=80, interval=1.0,
                                   tz_offset=0.0, claude_dir=str(root / "claude"),
                                   codex_index=str(root / "codex-index"), max_sessions=6,
                                   protocol=1, once=True)
            config = MonitorConfig.load(root / "monitor.toml", environ={
                "MONITOR_API_TOKEN": configured_token,
            })
            output = io.StringIO()
            with patch.object(session_daemon, "fetch_id_list", return_value=set()), \
                 patch.object(session_daemon, "fetch_snooze", return_value=0), \
                 patch.object(session_daemon, "hook_warnings", return_value=[]), \
                 patch.object(session_daemon.urllib.request, "urlopen", side_effect=receive), \
                 redirect_stdout(output):
                self.assertEqual(0, session_daemon.run(args, config))
        self.assertEqual(configured_token, captured[0].get_header("X-monitor-token"))
        self.assertNotIn(configured_token, output.getvalue())

    def test_run_uses_toml_token_for_hidden_and_pinned_gets(self):
        """Falling back to the legacy token on GET would make TOML-only auth inconsistent."""
        toml_token = "toml-token-for-get-only-123456"
        legacy_token = "legacy-token-must-not-win-654321"

        class Response:
            def __init__(self, payload: bytes):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return self.payload

        requests = []
        def receive(request, timeout):
            requests.append(request)
            if request.full_url.endswith("/hidden"):
                return Response(b'{"hidden": []}')
            if request.full_url.endswith("/pinned"):
                return Response(b'{"pinned": []}')
            if request.full_url.endswith("/snooze"):
                return Response(b'{"snooze_s": 0}')
            self.fail("unexpected request")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_file = root / "monitor.toml"
            config_file.write_text('[transport]\napi_token = "{}"\n'.format(toml_token),
                                   encoding="utf-8")
            config = MonitorConfig.load(config_file, environ={})
            args = SimpleNamespace(host="test-device", port=80, interval=1.0,
                                   tz_offset=0.0, claude_dir=str(root / "claude"),
                                   codex_index=str(root / "codex-index"), max_sessions=6,
                                   protocol=1, once=True)
            previous = session_daemon.MONITOR_API_TOKEN
            session_daemon.MONITOR_API_TOKEN = legacy_token
            output = io.StringIO()
            try:
                with patch.object(session_daemon, "post_sessions", return_value=200), \
                     patch.object(session_daemon, "hook_warnings", return_value=[]), \
                     patch.object(session_daemon.urllib.request, "urlopen", side_effect=receive), \
                     redirect_stdout(output):
                    self.assertEqual(0, session_daemon.run(args, config))
            finally:
                session_daemon.MONITOR_API_TOKEN = previous
        self.assertEqual(["/hidden", "/pinned", "/snooze"],
                         [request.full_url.removeprefix("http://test-device:80")
                          for request in requests])
        self.assertEqual([toml_token] * 3,
                         [request.get_header("X-monitor-token") for request in requests])
        self.assertNotIn(toml_token, output.getvalue())


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


def _session(session_id: str, state: str, severity: str, elapsed: int = 600,
            project: str = "proj") -> dict:
    return {"id": session_id, "state": state, "severity": severity,
            "elapsed": elapsed, "project": project}


class MaybeToastTests(unittest.TestCase):
    """Covers session_daemon.maybe_toast's dedupe/snooze contract."""

    def setUp(self):
        # _toasted is module-level state; leaving it dirty across tests would
        # make an earlier test's toast silently suppress a later one.
        session_daemon._toasted.clear()

    def tearDown(self):
        session_daemon._toasted.clear()

    def test_fires_once_per_session_state_pair(self):
        """Firing twice for the same (session, state) would train the operator
        to ignore the exact warning that matters."""
        sessions = [_session("s1", "perm", "critical")]
        with patch.object(session_daemon, "notify", return_value=True) as mock_notify:
            first = session_daemon.maybe_toast(sessions, 0)
            second = session_daemon.maybe_toast(sessions, 0)
        self.assertEqual(1, first)
        self.assertEqual(0, second)
        mock_notify.assert_called_once()

    def test_snooze_suppresses_even_critical_sessions(self):
        """Muted must mean muted -- covering even escalations that started after
        the snooze was set, not just the ones already known when it began."""
        sessions = [_session("s1", "perm", "critical")]
        with patch.object(session_daemon, "notify", return_value=True) as mock_notify:
            result = session_daemon.maybe_toast(sessions, 15)
        self.assertEqual(0, result)
        mock_notify.assert_not_called()

    def test_only_critical_severity_fires(self):
        """warning/expired/none sessions must never produce a toast -- only
        `critical` is loud enough to interrupt the operator."""
        sessions = [
            _session("s1", "perm", "warning"),
            _session("s2", "perm", "expired"),
            _session("s3", "work", "none"),
        ]
        with patch.object(session_daemon, "notify", return_value=True) as mock_notify:
            result = session_daemon.maybe_toast(sessions, 0)
        self.assertEqual(0, result)
        mock_notify.assert_not_called()

    def test_pair_leaving_the_list_can_alert_again_later(self):
        """A session dropping off the board and returning to `critical` is a new
        block, not a repeat of the one that already fired."""
        sessions = [_session("s1", "perm", "critical")]
        with patch.object(session_daemon, "notify", return_value=True) as mock_notify:
            first = session_daemon.maybe_toast(sessions, 0)
            middle = session_daemon.maybe_toast([], 0)
            third = session_daemon.maybe_toast(sessions, 0)
        self.assertEqual(1, first)
        self.assertEqual(0, middle)
        self.assertEqual(1, third)
        self.assertEqual(2, mock_notify.call_count)

    def test_broken_channel_does_not_become_a_retry_loop(self):
        """The pair is marked as toasted before the notify() result is known, so
        a broken channel does not retry every poll cycle -- that failure is the
        doctor's job to surface, not the daemon loop's."""
        sessions = [_session("s1", "perm", "critical")]
        with patch.object(session_daemon, "notify", return_value=False) as mock_notify:
            first = session_daemon.maybe_toast(sessions, 0)
            second = session_daemon.maybe_toast(sessions, 0)
        self.assertEqual(0, first)
        self.assertEqual(0, second)
        mock_notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
