from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import session_daemon
import usage_top


TZ = timezone(timedelta(hours=-3))
NOW = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)


def _write_transcript(project: Path, name: str, events: list[tuple[datetime, int]]) -> None:
    project.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, (ts, tokens) in enumerate(events):
        lines.append(json.dumps({
            "type": "assistant", "timestamp": ts.isoformat(),
            "sessionId": name,
            "message": {"id": f"m-{name}-{i}", "model": "claude-test",
                        "usage": {"input_tokens": tokens, "output_tokens": 0,
                                  "cache_creation_input_tokens": 0}},
        }))
    (project / f"{name}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


class ClaudeTopTests(unittest.TestCase):
    def test_orders_by_spend_and_caps_at_six_with_full_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp)
            for i in range(8):
                ts = NOW - timedelta(hours=i + 1)
                _write_transcript(projects / f"p{i}", f"sess{i}", [(ts, 1000 - i)])
            out = usage_top._claude(projects, NOW - timedelta(days=7), TZ, 6)
        self.assertEqual(sum(1000 - i for i in range(8)), out["total"])  # total completo
        self.assertEqual(6, len(out["sessions"]))
        self.assertEqual(1000, out["sessions"][0]["tokens"])             # mais pesada 1a
        self.assertEqual(995, out["sessions"][5]["tokens"])              # cap corta as 2 menores

    def test_window_excludes_sessions_older_than_since(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp)
            old = NOW - timedelta(days=20)
            fresh = NOW - timedelta(hours=2)
            _write_transcript(projects / "old", "antiga", [(old, 5000)])
            _write_transcript(projects / "new", "recente", [(fresh, 10)])
            out = usage_top._claude(projects, NOW - timedelta(days=7), TZ, 6)
        self.assertEqual(10, out["total"])
        self.assertEqual("new", out["sessions"][0]["name"])   # fallback: nome da pasta


class PayloadTopTests(unittest.TestCase):
    def test_payload_carries_three_periods_and_legacy_omits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "hist.db"
            payload = session_daemon.build_payload_v1(
                root / "claude", root / "missing-index", 6, TZ, now=NOW,
                history_db=db)
            top = payload["stats"]["usage"]["top"]
            self.assertEqual({"d1", "d7", "d30"}, set(top.keys()))
            for period in top.values():
                self.assertEqual({"claude", "codex", "opencode"}, set(period.keys()))
                for provider in period.values():
                    self.assertIn("total", provider)
                    self.assertIn("sessions", provider)

            legacy = session_daemon.build_payload_v1(
                root / "claude", root / "missing-index", 6, TZ, now=NOW)
            self.assertNotIn("usage", legacy["stats"])

    def test_opencode_provider_zero_still_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = session_daemon.build_payload_v1(
                root / "claude", root / "missing-index", 6, TZ, now=NOW,
                history_db=root / "hist.db")
            zero = payload["stats"]["usage"]["top"]["d1"]["opencode"]
            self.assertEqual(0, zero["total"])
            self.assertEqual([], zero["sessions"])


class BuildCachedTests(unittest.TestCase):
    def test_ttl_reuses_result_and_rebuilds_after_expiry(self):
        calls = {"n": 0}
        original = usage_top.build

        def fake_build(*a, **k):
            calls["n"] += 1
            return {"d1": {"claude": {"total": calls["n"], "sessions": []}}}

        usage_top.build = fake_build
        usage_top._top_cache.update(key=None, at=0.0, data=None)
        try:
            root = Path(".")
            first = usage_top.build_cached(root, root, None, TZ, NOW, ttl_s=60)
            second = usage_top.build_cached(root, root, None, TZ, NOW, ttl_s=60)
            self.assertEqual(1, calls["n"])                       # TTL: 1 build
            self.assertIs(first, second)
            expired = usage_top.build_cached(root, root, None, TZ, NOW, ttl_s=0)
            self.assertEqual(2, calls["n"])                       # expirado: rebuild
            self.assertEqual(2, expired["d1"]["claude"]["total"])
        finally:
            usage_top.build = original
            usage_top._top_cache.update(key=None, at=0.0, data=None)


if __name__ == "__main__":
    unittest.main()
