from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import commandcode_sessions
import session_daemon
from monitor_config import MonitorConfig


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "commandcode"
NOW = datetime(2026, 9, 19, 15, 0, tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _header(sid: str, cwd: str, moment: datetime) -> dict:
    return {"type": "session", "version": 3, "id": sid, "timestamp": _iso(moment), "cwd": cwd}


def _user(text: str, moment: datetime, message_id: str) -> dict:
    return {"type": "message", "id": "u-" + message_id, "parentId": None,
            "timestamp": _iso(moment),
            "message": {"role": "user", "content": [{"type": "text", "text": text}],
                        "meta": {"source": "user", "messageId": message_id}}}


def _assistant(moment: datetime, *, content: list, message_id: str,
               input_tokens: int = 0, output_tokens: int = 0, cache_read: int = 0,
               cache_write: int = 0, model: str = "deepseek/deepseek-v4.1-flash",
               effort: str = "low") -> dict:
    return {"type": "message", "id": "a-" + message_id, "parentId": "u-" + message_id,
            "timestamp": _iso(moment),
            "message": {"role": "assistant", "content": content,
                        "meta": {"source": "model", "messageId": message_id}},
            "usage": {"inputTokens": input_tokens, "outputTokens": output_tokens,
                      "cacheReadTokens": cache_read, "cacheWriteTokens": cache_write,
                      "costUsd": 0.0},
            "model": model, "effort": effort}


def _tool_use(call_id: str, name: str) -> dict:
    return {"type": "tool_use", "id": call_id, "name": name, "input": {}}


def _tool_result(call_id: str, moment: datetime) -> dict:
    return {"type": "message", "id": "r-" + call_id, "parentId": "a",
            "timestamp": _iso(moment),
            "message": {"role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": call_id,
                                     "content": [{"type": "text", "text": "ok"}]}]}}


def _write(root: Path, slug: str, sid: str, entries: list, mtime: datetime | None = None) -> Path:
    directory = root / slug
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (sid + ".jsonl")
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    if mtime is not None:
        stamp = mtime.timestamp()
        os.utime(path, (stamp, stamp))
    return path


def _write_events(path: Path, events: dict) -> Path:
    path.write_text(json.dumps(events), encoding="utf-8")
    return path


class CollectorTests(unittest.TestCase):
    def test_recent_completed_turn_is_work_by_recency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "proj", "cc-work", [
                _header("cc-work", str(root / "proj"), NOW - timedelta(seconds=20)),
                _user("faca X", NOW - timedelta(seconds=15), "m1"),
                _assistant(NOW - timedelta(seconds=10), message_id="m2",
                           content=[_tool_use("call_1", "read_file")]),
                _tool_result("call_1", NOW - timedelta(seconds=9)),
            ], mtime=NOW - timedelta(seconds=10))
            sessions = commandcode_sessions.scan_commandcode_sessions(
                NOW, NOW - timedelta(hours=12), directory=root,
                event_path=root / "missing-events.json")
        self.assertEqual(1, len(sessions))
        session = sessions[0]
        self.assertEqual("commandcode", session["tool"])
        self.assertEqual("work", session["state"])
        self.assertEqual("deepseek", session["provider"])
        self.assertEqual("deepseek-v4.1-", session["model"])   # short_model trunca em 14
        self.assertEqual("low", session["effort"])

    def test_pending_question_is_ask(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "proj", "cc-ask", [
                _header("cc-ask", str(root / "proj"), NOW - timedelta(seconds=20)),
                _assistant(NOW - timedelta(seconds=5), message_id="m1",
                           content=[_tool_use("call_1", "ask_user_question")]),
            ], mtime=NOW - timedelta(seconds=5))
            sessions = commandcode_sessions.scan_commandcode_sessions(
                NOW, NOW - timedelta(hours=12), directory=root,
                event_path=root / "missing-events.json")
        self.assertEqual("ask", sessions[0]["state"])

    def test_pending_tool_without_hook_is_perm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "proj", "cc-perm", [
                _header("cc-perm", str(root / "proj"), NOW - timedelta(seconds=20)),
                _assistant(NOW - timedelta(seconds=5), message_id="m1",
                           content=[_tool_use("call_1", "shell_command")]),
            ], mtime=NOW - timedelta(seconds=5))
            sessions = commandcode_sessions.scan_commandcode_sessions(
                NOW, NOW - timedelta(hours=12), directory=root,
                event_path=root / "missing-events.json")
        self.assertEqual("perm", sessions[0]["state"])

    def test_perm_does_not_persist_past_the_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "proj", "cc-old-perm", [
                _header("cc-old-perm", str(root / "proj"), NOW - timedelta(seconds=800)),
                _assistant(NOW - timedelta(seconds=700), message_id="m1",
                           content=[_tool_use("call_1", "shell_command")]),
            ], mtime=NOW - timedelta(seconds=700))
            sessions = commandcode_sessions.scan_commandcode_sessions(
                NOW, NOW - timedelta(hours=12), directory=root,
                event_path=root / "missing-events.json")
        self.assertNotEqual("perm", sessions[0]["state"])

    def test_structured_hook_event_wins_and_ended_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "proj", "cc-free", [
                _header("cc-free", str(root / "proj"), NOW - timedelta(seconds=30)),
                _assistant(NOW - timedelta(seconds=20), message_id="m1", content=[]),
            ], mtime=NOW - timedelta(seconds=20))
            _write(root, "proj", "cc-ended", [
                _header("cc-ended", str(root / "proj"), NOW - timedelta(seconds=30)),
                _assistant(NOW - timedelta(seconds=20), message_id="m2", content=[]),
            ], mtime=NOW - timedelta(seconds=20))
            events = root / "events.json"
            _write_events(events, {
                "cc-free": {"session_id": "cc-free", "state": "free",
                            "timestamp": _iso(NOW - timedelta(seconds=8)),
                            "event": "Stop", "tool": "", "cwd": ""},
                "cc-ended": {"session_id": "cc-ended", "state": "ended",
                             "timestamp": _iso(NOW - timedelta(seconds=8)),
                             "event": "SessionEnd", "tool": "", "cwd": ""},
            })
            sessions = commandcode_sessions.scan_commandcode_sessions(
                NOW, NOW - timedelta(hours=12), directory=root, event_path=events)
        ids = {s["id"] for s in sessions}
        self.assertIn("cc-free", ids)
        self.assertNotIn("cc-ended", ids)
        self.assertEqual("free", next(s for s in sessions if s["id"] == "cc-free")["state"])

    def test_consumption_is_input_minus_cache_read_and_dedups(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "proj", "cc-tokens", [
                _header("cc-tokens", str(root / "proj"), NOW - timedelta(seconds=30)),
                _assistant(NOW - timedelta(seconds=20), message_id="dup",
                           content=[], input_tokens=10000, cache_read=9000,
                           output_tokens=50),
                _assistant(NOW - timedelta(seconds=19), message_id="dup",
                           content=[], input_tokens=10000, cache_read=9000,
                           output_tokens=50),
            ], mtime=NOW - timedelta(seconds=19))
            sessions = commandcode_sessions.scan_commandcode_sessions(
                NOW, NOW - timedelta(hours=12), directory=root,
                event_path=root / "missing-events.json")
        # input e o prompt inteiro (inclui o cache lido): o consumo novo e
        # (input - cacheRead) + output = 1000 + 50; a mensagem duplicada conta 1x.
        self.assertEqual(1050, sessions[0]["tokensWin"])

    def test_context_quality_unknown_without_window_and_estimated_per_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "proj", "cc-ctx", [
                _header("cc-ctx", str(root / "proj"), NOW - timedelta(seconds=30)),
                _assistant(NOW - timedelta(seconds=20), message_id="m1", content=[],
                           input_tokens=1000, output_tokens=10, cache_read=100,
                           model="gpt-5.6-sol"),
            ], mtime=NOW - timedelta(seconds=20))
            sessions = commandcode_sessions.scan_commandcode_sessions(
                NOW, NOW - timedelta(hours=12), directory=root,
                event_path=root / "missing-events.json")
        self.assertEqual("unknown", sessions[0]["context"]["quality"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "proj", "cc-ctx2", [
                _header("cc-ctx2", str(root / "proj"), NOW - timedelta(seconds=30)),
                _assistant(NOW - timedelta(seconds=20), message_id="m1", content=[],
                           input_tokens=64000, output_tokens=10),
            ], mtime=NOW - timedelta(seconds=20))
            sessions = commandcode_sessions.scan_commandcode_sessions(
                NOW, NOW - timedelta(hours=12), directory=root,
                event_path=root / "missing-events.json")
        self.assertEqual("estimated", sessions[0]["context"]["quality"])
        self.assertEqual(6, sessions[0]["ctxPct"])        # 64010 / 1M (reference/models.md)

    def test_session_older_than_a_day_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "proj", "cc-old", [
                _header("cc-old", str(root / "proj"), NOW - timedelta(hours=30)),
                _assistant(NOW - timedelta(hours=25), message_id="m1", content=[]),
            ], mtime=NOW - timedelta(hours=25))
            sessions = commandcode_sessions.scan_commandcode_sessions(
                NOW, NOW - timedelta(hours=26), directory=root,
                event_path=root / "missing-events.json")
        self.assertEqual([], sessions)

    def test_missing_directory_degrades_to_empty(self):
        self.assertEqual([], commandcode_sessions.scan_commandcode_sessions(
            NOW, NOW, directory=Path("nao-existe"), event_path=Path("nao-existe.json")))

    def test_aggregates_window_tokens_and_turn_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "proj", "cc-agg", [
                _header("cc-agg", str(root / "proj"), NOW - timedelta(seconds=30)),
                _assistant(NOW - timedelta(seconds=20), message_id="m1", content=[],
                           input_tokens=10, output_tokens=20),
            ], mtime=NOW - timedelta(seconds=20))
            since = (NOW - timedelta(hours=1)).timestamp()
            self.assertEqual(30, commandcode_sessions.window_tokens(root, since))
            events = list(commandcode_sessions.turn_token_events(root, NOW - timedelta(hours=1)))
            self.assertEqual([30], [tokens for _, tokens in events])
            self.assertEqual(1, commandcode_sessions.count_active_12h(root, NOW, 12 * 3600))

    def test_real_fixture_parses_with_correct_consumption(self):
        events = commandcode_sessions._usage_events(
            commandcode_sessions._messages(
                commandcode_sessions._read_objects(FIXTURES / "session_sample.jsonl")))
        self.assertEqual(1, len(events))
        # input=20972 (prompt inteiro), cacheRead=7296, output=222 -> 13676 + 222
        self.assertEqual(20972 - 7296 + 222, events[0]["tokens"])
        self.assertEqual(20972, events[0]["context"])


class BuildPayloadIntegrationTests(unittest.TestCase):
    def test_commandcode_session_reaches_the_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "proj", "cc-int", [
                _header("cc-int", str(root / "proj"), NOW - timedelta(seconds=20)),
                _assistant(NOW - timedelta(seconds=5), message_id="m1", content=[]),
            ], mtime=NOW - timedelta(seconds=5))
            payload = session_daemon.build_payload_v1(
                root / "claude", root / "index", 6, timezone.utc, now=NOW,
                commandcode_dir=root)
        session = next(s for s in payload["sessions"] if s["tool"] == "commandcode")
        self.assertEqual("cc-int", session["id"])
        self.assertEqual(1, payload["stats"]["active_12h"])

    def test_absent_directory_is_hermetic(self):
        payload = session_daemon.build_payload_v1(
            Path("nao-existe"), Path("nao-existe-index"), 6, timezone.utc, now=NOW)
        self.assertNotIn("commandcode", {s["tool"] for s in payload["sessions"]})


class Fallback422Tests(unittest.TestCase):
    def test_run_retries_without_the_unknown_tool(self):
        if hasattr(session_daemon.run, "_unknown_tool_fallback_warned"):
            del session_daemon.run._unknown_tool_fallback_warned
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = SimpleNamespace(host="dev", port=80, interval=1.0, tz_offset=0.0,
                                   claude_dir=str(root / "claude"),
                                   codex_index=str(root / "index"), max_sessions=6,
                                   protocol=1, once=True)
            config = MonitorConfig.load(root / "monitor.toml", environ={})
            first = {"sessions": [{"id": "cc-1", "tool": "commandcode", "state": "free",
                                   "elapsed": 1, "severity": "none"}],
                     "catalog": [], "stats": {"active_12h": 1}}
            second = {"sessions": [], "catalog": [], "stats": {"active_12h": 0}}
            calls: list = []

            def fake_post(url, payload, timeout=5.0, token=None):
                calls.append(payload)
                return 422 if len(calls) == 1 else 200

            with patch.object(session_daemon, "fetch_id_list", return_value=set()), \
                 patch.object(session_daemon, "fetch_snooze", return_value=0), \
                 patch.object(session_daemon, "hook_warnings", return_value=[]), \
                 patch.object(session_daemon, "build_payload_v1",
                              side_effect=[first, second]), \
                 patch.object(session_daemon, "post_sessions", side_effect=fake_post):
                self.assertEqual(0, session_daemon.run(args, config))
        self.assertEqual(2, len(calls))
        self.assertEqual([], calls[1]["sessions"])


class ConfigCommandCodeWindowTests(unittest.TestCase):
    def test_default_window_is_zero(self):
        config = MonitorConfig.load("missing-monitor.toml", environ={})
        self.assertEqual(0, config.usage.commandcode_context_window)

    def test_negative_window_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.toml"
            path.write_text("[usage]\ncommandcode_context_window = -1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                MonitorConfig.load(path, environ={})


if __name__ == "__main__":
    unittest.main()
