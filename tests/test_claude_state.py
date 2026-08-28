from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from session_state import infer_state

NOW = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)


def assistant_tool(name: str, tool_id: str = "tool-1", seconds_ago: int = 1) -> dict:
    return {
        "type": "assistant",
        "timestamp": (NOW - timedelta(seconds=seconds_ago)).isoformat(),
        "message": {"content": [{"type": "tool_use", "name": name, "id": tool_id}]},
    }


class ClaudeStateTests(unittest.TestCase):
    def test_permission_request_hook_means_permission(self):
        state, _ = infer_state([assistant_tool("Bash")], NOW, perm_pending=True)
        self.assertEqual("perm", state)

    def test_pending_normal_tool_without_hook_is_work_not_permission(self):
        state, _ = infer_state([assistant_tool("Bash", seconds_ago=60)], NOW)
        self.assertEqual("work", state)

    def test_pending_question_is_ask_even_if_permission_hook_fires(self):
        state, _ = infer_state([assistant_tool("AskUserQuestion")], NOW,
                               perm_pending=True)
        self.assertEqual("ask", state)

    def test_exit_plan_mode_is_ask_even_if_permission_hook_fires(self):
        state, _ = infer_state([assistant_tool("ExitPlanMode")], NOW,
                               perm_pending=True)
        self.assertEqual("ask", state)

    def test_invalid_timestamp_degrades_only_that_session(self):
        obj = assistant_tool("Bash")
        obj["timestamp"] = "invalid"
        state, age = infer_state([obj], NOW)
        self.assertEqual("free", state)
        self.assertEqual(float("inf"), age)


if __name__ == "__main__":
    unittest.main()
