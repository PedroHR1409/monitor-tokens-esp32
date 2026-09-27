from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import install_commandcode_hook
import session_hook


THIRD_PARTY = {"hooks": {"PreToolUse": [{"hooks": [
    {"type": "command", "command": "powershell -NoProfile -Command audit"}]}]}}


class BuildHooksConfigTests(unittest.TestCase):
    def test_adds_our_hooks_and_preserves_third_party(self):
        result = install_commandcode_hook.build_hooks_config(
            THIRD_PARTY, '"py" "session_hook.py" commandcode')
        hooks = result["hooks"]
        self.assertEqual(set(install_commandcode_hook.EVENTS), set(hooks))
        pre = hooks["PreToolUse"]
        commands = [h["command"] for group in pre for h in group["hooks"]]
        self.assertIn("powershell -NoProfile -Command audit", commands)
        self.assertTrue(any("commandcode pre_tool_use" in c for c in commands))

    def test_reinstall_is_idempotent(self):
        command = '"py" "session_hook.py" commandcode'
        once = install_commandcode_hook.build_hooks_config(THIRD_PARTY, command)
        twice = install_commandcode_hook.build_hooks_config(once, command)
        for event in install_commandcode_hook.EVENTS:
            ours = [g for g in twice["hooks"][event]
                    if install_commandcode_hook._is_ours(g)]
            self.assertEqual(1, len(ours), event)

    def test_remove_strips_only_ours(self):
        command = '"py" "session_hook.py" commandcode'
        installed = install_commandcode_hook.build_hooks_config(THIRD_PARTY, command)
        removed = install_commandcode_hook.build_hooks_config(installed, command, remove=True)
        remaining = [g for event in removed["hooks"].values() for g in event]
        self.assertFalse(any(install_commandcode_hook._is_ours(g) for g in remaining))
        self.assertTrue(any("audit" in str(g) for g in remaining))

    def test_invalid_hooks_shape_raises(self):
        with self.assertRaises(ValueError):
            install_commandcode_hook.build_hooks_config({"hooks": []}, "x")

    def test_main_writes_atomically_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps(THIRD_PARTY), encoding="utf-8")
            with patch.object(sys, "argv", ["install", "--path", str(path)]):
                self.assertEqual(0, install_commandcode_hook.main())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("PreToolUse", data["hooks"])
            backups = list(Path(tmp).glob("*.bak"))
            self.assertEqual(1, len(backups))


class HookHealthTests(unittest.TestCase):
    def test_default_path_targets_the_commandcode_store(self):
        path = session_hook._default_path("commandcode")
        self.assertEqual(".commandcode", path.parent.name)
        self.assertEqual("monitor-ai-events.json", path.name)

    def test_hook_health_reports_commandcode(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text(json.dumps(install_commandcode_hook.build_hooks_config(
                {}, '"py" "session_hook.py" commandcode')), encoding="utf-8")
            with patch.object(session_hook, "COMMANDCODE_SETTINGS", settings):
                self.assertTrue(session_hook.hook_health()["commandcode"])

    def test_hook_health_false_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(session_hook, "COMMANDCODE_SETTINGS",
                              Path(tmp) / "missing.json"):
                self.assertFalse(session_hook.hook_health()["commandcode"])


if __name__ == "__main__":
    unittest.main()
