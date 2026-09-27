from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import session_daemon
import session_meta
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


class CodexTopTests(unittest.TestCase):
    SID = "01a0a5b9-6425-7382-8a15-5c810c93abcd"

    def test_session_only_in_rollout_counts_for_the_podium(self):
        """O session_index parou de receber sessoes novas (15/09/2026): o pódio
        exibia 0 no card Codex mesmo com o Codex rodando no dia. O rollout no
        disco entra, pela mesma uniao indice+rollouts dos coletores de sessao."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollouts = root / "sessions"
            path = (rollouts / "2026" / "08" / "28" /
                    ("rollout-2026-08-28T12-00-00-" + self.SID + ".jsonl"))
            path.parent.mkdir(parents=True)
            events = [(NOW - timedelta(hours=1), 500),
                      (NOW - timedelta(minutes=30), 1500)]
            path.write_text("".join(json.dumps({
                "timestamp": ts.isoformat(),
                "payload": {"info": {"total_token_usage": {"total_tokens": total}}}}
            ) + "\n" for ts, total in events), encoding="utf-8")
            epoch = (NOW - timedelta(minutes=5)).timestamp()
            os.utime(path, (epoch, epoch))
            missing = root / "session_index.jsonl"   # indice sem a sessao
            missing.write_text("", encoding="utf-8")
            previous, prev_at = session_meta._cache, session_meta._cache_at
            session_meta._cache, session_meta._cache_at = {}, 0.0
            try:
                with unittest.mock.patch.object(session_meta, "CODEX_SESSIONS",
                                                rollouts):
                    out = usage_top._codex(missing, NOW - timedelta(days=1), TZ,
                                           NOW, 6, rollouts_dir=rollouts)
            finally:
                session_meta._cache, session_meta._cache_at = previous, prev_at
                session_meta._meta_cache.clear()
        self.assertEqual(1500, out["total"])
        self.assertEqual(self.SID[:36], out["sessions"][0]["id"])
        self.assertEqual("codex", out["sessions"][0]["name"])

    def test_rollouts_disabled_keeps_hermetic_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sessions").mkdir()
            path = (root / "sessions" /
                    ("rollout-2026-08-28T12-00-00-" + self.SID + ".jsonl"))
            path.write_text("", encoding="utf-8")
            out = usage_top._codex(root / "missing-index", NOW - timedelta(days=1),
                                   TZ, NOW, 6)
        self.assertEqual(0, out["total"])    # sem rollouts_dir: nao varre disco real


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
                self.assertEqual({"claude", "codex", "opencode", "commandcode"},
                                 set(period.keys()))
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
