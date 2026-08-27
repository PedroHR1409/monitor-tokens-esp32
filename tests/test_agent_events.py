from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

try:
    from agent_events import reduce_session_events
except ImportError:
    reduce_session_events = None


NOW = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)


def event(state: str, seconds_ago: int, *, session_id: str = "session-full-id") -> dict:
    return {
        "session_id": session_id,
        "state": state,
        "timestamp": (NOW - timedelta(seconds=seconds_ago)).isoformat(),
    }


@unittest.skipIf(reduce_session_events is None, "agent_events ainda nao implementado")
class AgentEventReducerTests(unittest.TestCase):
    def assert_transition(self, states: list[str], expected: str) -> None:
        events = [event(state, len(states) - index) for index, state in enumerate(states)]
        snapshot = reduce_session_events("session-full-id", events, NOW, stale_after_s=90)
        self.assertEqual(expected, snapshot.state)
        self.assertEqual(tuple(states), snapshot.transitions)

    def test_work_permission_work(self):
        self.assert_transition(["work", "perm", "work"], "work")

    def test_work_ask_work(self):
        self.assert_transition(["work", "ask", "work"], "work")

    def test_work_free(self):
        self.assert_transition(["work", "free"], "free")

    def test_permission_free(self):
        self.assert_transition(["perm", "free"], "free")

    def test_ended_session_is_free_and_ended(self):
        snapshot = reduce_session_events(
            "session-full-id", [event("work", 2), event("ended", 1)], NOW)
        self.assertEqual("free", snapshot.state)
        self.assertTrue(snapshot.ended)

    def test_stale_preserves_last_state_as_history(self):
        snapshot = reduce_session_events(
            "session-full-id", [event("work", 600)], NOW, stale_after_s=90)
        self.assertEqual("work", snapshot.state)
        self.assertTrue(snapshot.stale)
        self.assertEqual(600, snapshot.age_s)

    def test_long_command_never_becomes_ask_or_permission(self):
        snapshot = reduce_session_events(
            "session-full-id", [event("work", 1200)], NOW, stale_after_s=90)
        self.assertEqual("work", snapshot.state)
        self.assertNotIn(snapshot.state, ("ask", "perm"))

    def test_out_of_order_event_cannot_restore_old_state(self):
        snapshot = reduce_session_events(
            "session-full-id", [event("work", 5), event("perm", 30)], NOW)
        self.assertEqual("work", snapshot.state)
        self.assertEqual(("work",), snapshot.transitions)
        self.assertIn("out_of_order", snapshot.diagnostics)

    def test_invalid_missing_and_naive_timestamps_degrade_safely(self):
        bad_events = [
            {"session_id": "session-full-id", "state": "work", "timestamp": "bad"},
            {"session_id": "session-full-id", "state": "work"},
            {"session_id": "session-full-id", "state": "work",
             "timestamp": "2026-08-27T12:00:00"},
        ]
        snapshot = reduce_session_events("session-full-id", bad_events, NOW)
        self.assertEqual("free", snapshot.state)
        self.assertTrue(snapshot.stale)
        self.assertEqual(3, len(snapshot.diagnostics))

    def test_far_future_timestamp_is_not_current_and_cannot_pin_state(self):
        future = {
            "session_id": "session-full-id", "state": "perm",
            "timestamp": (NOW + timedelta(days=365)).isoformat(),
        }
        snapshot = reduce_session_events("session-full-id", [future], NOW)
        self.assertEqual("free", snapshot.state)
        self.assertTrue(snapshot.stale)
        self.assertIn("future_timestamp", snapshot.diagnostics)

    def test_event_for_other_session_is_ignored(self):
        snapshot = reduce_session_events(
            "wanted", [event("perm", 1, session_id="other")], NOW)
        self.assertEqual("free", snapshot.state)
        self.assertTrue(snapshot.stale)


class AgentEventModuleContractTests(unittest.TestCase):
    def test_reducer_module_exists(self):
        self.assertIsNotNone(reduce_session_events)


if __name__ == "__main__":
    unittest.main()
