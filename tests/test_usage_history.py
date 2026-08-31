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

import usage_history
from usage_tracker import codex_series  # noqa: F401  (contrato de janela do dia)

TZ = timezone(timedelta(hours=-3))
NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _write_transcript(project: Path, name: str, events: list[tuple[datetime, int]]) -> Path:
    project.mkdir(parents=True, exist_ok=True)
    path = project / name
    lines = []
    for i, (ts, tokens) in enumerate(events):
        lines.append(json.dumps({
            "type": "assistant", "timestamp": ts.isoformat(),
            "message": {"id": f"msg-{name}-{i}", "model": "claude-test",
                        "usage": {"input_tokens": tokens, "output_tokens": 0,
                                  "cache_creation_input_tokens": 0}},
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_rollout(directory: Path, name: str,
                   events: list[tuple[datetime, int]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    lines = []
    for ts, cumulative in events:
        lines.append(json.dumps({
            "timestamp": ts.isoformat(),
            "payload": {"info": {"total_token_usage": {"total_tokens": cumulative}}},
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "monitor-ai.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_upsert_same_day_updates_instead_of_duplicating(self):
        usage_history.record_today(self.db, 100, TZ, NOW)
        usage_history.record_today(self.db, 250, TZ, NOW)
        con = sqlite3.connect(self.db)
        rows = con.execute("SELECT day, tokens FROM usage_history").fetchall()
        con.close()
        self.assertEqual(1, len(rows))
        self.assertEqual(250, rows[0][1])

    def test_daily_window_is_oldest_first_and_zero_pads(self):
        base = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        for offset in (5, 1, 0):                     # gravados fora de ordem
            day = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc) - timedelta(days=offset)
            usage_history.record_today(self.db, 100 + offset, TZ, day)
        window = usage_history.daily_window(self.db, TZ, now=NOW)
        self.assertEqual(30, len(window))
        self.assertEqual(0, window[0])               # 30 dias atras: sem dado
        self.assertEqual(105, window[24])            # offset 5 (23/08)
        self.assertEqual(101, window[28])            # ontem (offset 1)
        self.assertEqual(100, window[29])            # hoje (offset 0)

    def test_restart_survives_because_rows_live_in_sqlite(self):
        usage_history.record_today(self.db, 900, TZ, NOW)
        # "restart" = nova conexao; is_empty/daily_window reabrem o banco
        self.assertFalse(usage_history.is_empty(self.db))
        self.assertEqual(900, usage_history.daily_window(self.db, TZ, now=NOW)[-1])

    def test_prune_removes_only_days_beyond_retention(self):
        con = sqlite3.connect(self.db)
        con.execute(usage_history._SCHEMA)
        con.execute("INSERT INTO usage_history VALUES ('2026-07-01', 10)")   # 58 dias
        con.execute("INSERT INTO usage_history VALUES ('2026-08-20', 20)")   # 8 dias
        con.commit(); con.close()
        removed = usage_history.prune(self.db, tz=TZ, now=NOW)
        self.assertEqual(1, removed)
        window = usage_history.daily_window(self.db, TZ, now=NOW)
        self.assertEqual(20, sum(window))

    def test_backfill_inserts_only_days_without_live_row(self):
        today = usage_history.local_today(TZ, NOW).isoformat()
        usage_history.record_today(self.db, 555, TZ, NOW)     # linha viva de hoje
        projects = Path(self._tmp.name) / "projects"
        yesterday = NOW - timedelta(days=1)
        _write_transcript(projects / "p", "s.jsonl",
                          [(yesterday - timedelta(hours=1), 700), (NOW, 999)])
        usage_history.backfill(self.db, claude_dir=projects, rollouts_dir=None,
                               opencode_db=None, tz=TZ, now=NOW)
        window = usage_history.daily_window(self.db, TZ, now=NOW)
        self.assertEqual(700, window[28])            # ontem reconstruido
        self.assertEqual(555, window[29])            # hoje NAO foi sobrescrito pelo 999

    def test_backfill_deduplicates_message_ids_across_days(self):
        projects = Path(self._tmp.name) / "projects"
        ts = NOW - timedelta(days=2)
        # mesma message.id repetida (re-serializacao) dentro do mesmo arquivo
        path = projects / "p"
        path.mkdir(parents=True)
        (path / "s.jsonl").write_text(
            "\n".join(json.dumps({"type": "assistant", "timestamp": ts.isoformat(),
                                  "message": {"id": "dup-1", "usage": {
                                      "input_tokens": 50, "output_tokens": 0,
                                      "cache_creation_input_tokens": 0}}})
                      for _ in range(3)) + "\n", encoding="utf-8")
        usage_history.backfill(self.db, claude_dir=projects, rollouts_dir=None,
                               opencode_db=None, tz=TZ, now=NOW)
        window = usage_history.daily_window(self.db, TZ, now=NOW)
        self.assertEqual(50, window[27])             # contado uma unica vez


class CodexBackfillTests(unittest.TestCase):
    def test_codex_daily_buckets_follow_cumulative_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            rollouts = Path(tmp) / "codex"
            day1 = datetime(2026, 8, 26, 15, 0, tzinfo=timezone.utc)
            day2 = datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc)
            _write_rollout(rollouts, "rollout-1.jsonl",
                           [(day1, 100), (day1 + timedelta(hours=1), 350),
                            (day2, 600)])
            db = Path(tmp) / "hist.db"
            buckets = usage_history.backfill(db, claude_dir=None, rollouts_dir=rollouts,
                                             opencode_db=None, tz=TZ, now=NOW)
            self.assertGreaterEqual(buckets.get("2026-08-26", 0), 350)
            window = usage_history.daily_window(db, TZ, now=NOW)
            # 26/08 = -2 dias (indice 27), 27/08 = ontem (indice 28): deltas 350 e 250
            self.assertEqual(350, window[27])
            self.assertEqual(250, window[28])

    def test_codex_restart_counter_counts_as_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            rollouts = Path(tmp) / "codex"
            day1 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
            _write_rollout(rollouts, "rollout-1.jsonl",
                           [(day1, 5000), (day1 + timedelta(hours=1), 30)])
            db = Path(tmp) / "hist.db"
            usage_history.backfill(db, claude_dir=None, rollouts_dir=rollouts,
                                   opencode_db=None, tz=TZ, now=NOW)
            window = usage_history.daily_window(db, TZ, now=NOW)
            self.assertEqual(5000 + 30, window[28])   # restart soma como uso real


class PayloadIntegrationTests(unittest.TestCase):
    def test_history_block_present_with_db_and_absent_without(self):
        import session_daemon
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "hist.db"
            payload = session_daemon.build_payload_v1(
                root / "claude", root / "missing-index", 6, TZ, now=NOW,
                history_db=db)
            self.assertEqual(30, len(payload["stats"]["history"]["daily"]))
            self.assertTrue(db.is_file())            # persistiu o dia corrente

            payload_sem = session_daemon.build_payload_v1(
                root / "claude", root / "missing-index", 6, TZ, now=NOW)
            self.assertNotIn("history", payload_sem["stats"])

    def test_v2_projects_history_block(self):
        import session_daemon
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = session_daemon.build_payload_v2(
                root / "claude", root / "missing-index", 6, TZ,
                node_id="n", device_id="d", daemon_instance_id="i", sequence=1,
                now=NOW, history_db=root / "hist.db")
        self.assertEqual(30, len(payload["stats"]["usage"]["history"]["daily"]))


if __name__ == "__main__":
    unittest.main()
