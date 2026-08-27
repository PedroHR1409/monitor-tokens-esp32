from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

try:
    from session_hook import load_event_store, record_event
except ImportError:
    load_event_store = record_event = None

try:
    from install_codex_hook import build_hooks_config
except ImportError:
    build_hooks_config = None

from install_hook import EVENTS as CLAUDE_EVENTS


NOW = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)


@unittest.skipIf(record_event is None, "session_hook ainda nao implementado")
class SessionHookTests(unittest.TestCase):
    def test_permission_is_explicit_and_tool_completion_returns_to_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            payload = {"session_id": "complete-id", "tool_name": "Bash"}
            self.assertTrue(record_event(payload, "permission_request", path, NOW))
            self.assertEqual("perm", load_event_store(path)["complete-id"]["state"])
            self.assertTrue(record_event(payload, "work", path, NOW + timedelta(seconds=1)))
            self.assertEqual("work", load_event_store(path)["complete-id"]["state"])

    def test_normal_tool_execution_never_creates_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            record_event({"session_id": "id", "tool_name": "Bash"}, "work", path, NOW)
            self.assertEqual("work", load_event_store(path)["id"]["state"])

    def test_question_tool_never_creates_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            record_event({"session_id": "id", "tool_name": "AskUserQuestion"},
                         "permission_request", path, NOW)
            self.assertEqual("work", load_event_store(path)["id"]["state"])

    def test_old_event_cannot_overwrite_newer_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            payload = {"session_id": "id"}
            record_event(payload, "free", path, NOW)
            self.assertFalse(record_event(payload, "permission_request", path,
                                          NOW - timedelta(seconds=10)))
            self.assertEqual("free", load_event_store(path)["id"]["state"])

    def test_poisoned_future_event_is_replaced_by_current_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            path.write_text(json.dumps({"id": {
                "session_id": "id", "state": "perm",
                "timestamp": (NOW + timedelta(days=365)).isoformat(),
            }}), encoding="utf-8")
            self.assertTrue(record_event({"session_id": "id"}, "work", path, NOW))
            self.assertEqual("work", load_event_store(path)["id"]["state"])

    def test_full_ids_remain_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            for suffix in ("A", "B"):
                record_event({"session_id": "123456789012345-" + suffix}, "work", path, NOW)
            self.assertEqual(2, len(load_event_store(path)))

    def test_invalid_payload_does_not_write_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            self.assertFalse(record_event({}, "work", path, NOW))
            self.assertEqual({}, load_event_store(path))


class SessionHookModuleContractTests(unittest.TestCase):
    def test_hook_module_exists(self):
        self.assertIsNotNone(record_event)

    def test_codex_installer_module_exists(self):
        self.assertIsNotNone(build_hooks_config)

    def test_claude_installer_tracks_complete_lifecycle(self):
        self.assertEqual({
            "SessionStart": "free", "UserPromptSubmit": "work",
            "PreToolUse": "work", "PermissionRequest": "permission_request",
            "PostToolUse": "work", "Stop": "free", "SessionEnd": "ended",
        }, CLAUDE_EVENTS)


@unittest.skipIf(build_hooks_config is None, "installador Codex ainda nao implementado")
class CodexHookInstallerTests(unittest.TestCase):
    def test_config_preserves_existing_hooks_and_adds_structured_lifecycle(self):
        existing = {"description": "user hooks", "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "existing-command"}]}]
        }}
        result = build_hooks_config(existing, 'python "session_hook.py" codex')
        self.assertEqual("existing-command",
                         result["hooks"]["Stop"][0]["hooks"][0]["command"])
        expected = {
            "SessionStart": "free", "UserPromptSubmit": "work",
            "PreToolUse": "work", "PermissionRequest": "permission_request",
            "PostToolUse": "work", "Stop": "free", "SessionEnd": "ended",
        }
        for event_name, action in expected.items():
            commands = [handler["command"]
                        for group in result["hooks"][event_name]
                        for handler in group["hooks"]]
            self.assertTrue(any(command.endswith(" " + action) for command in commands),
                            event_name)

    def test_rebuilding_config_is_idempotent(self):
        once = build_hooks_config({}, 'python "session_hook.py" codex')
        twice = build_hooks_config(once, 'python "session_hook.py" codex')
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
