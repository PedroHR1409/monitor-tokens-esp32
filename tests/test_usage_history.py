from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import usage_history
from usage_model import UsageBreakdown
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


def _write_detailed_rollout(directory: Path, name: str,
                            events: list[tuple[datetime, dict]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("\n".join(json.dumps({
        "timestamp": ts.isoformat(),
        "payload": {"info": {"total_token_usage": usage}},
    }) for ts, usage in events) + "\n", encoding="utf-8")
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

    def test_prune_honours_an_explicit_retention_from_config(self):
        """The daemon passes storage.retention_days; ignoring it made the TOML
        setting decorative while a hardcoded constant decided the disk."""
        con = sqlite3.connect(self.db)
        con.execute(usage_history._SCHEMA)
        con.execute("INSERT INTO usage_history VALUES ('2026-08-15', 10)")   # 13 dias
        con.execute("INSERT INTO usage_history VALUES ('2026-08-20', 20)")   # 8 dias
        con.commit(); con.close()
        removed = usage_history.prune(self.db, keep_days=10, tz=TZ, now=NOW)
        self.assertEqual(1, removed)
        remaining = usage_history.daily_window(self.db, TZ, now=NOW)
        self.assertEqual(20, sum(remaining))

    def test_default_retention_matches_the_config_default(self):
        """A default divergent from StorageSettings.retention_days is the config/code
        disconnection this feature closed: 35 here against 30 in monitor.toml."""
        from monitor_config import StorageSettings

        self.assertEqual(StorageSettings().retention_days, usage_history.RETENTION_DAYS)

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

    def test_forced_backfill_repairs_existing_day(self):
        projects = Path(self._tmp.name) / "projects"
        yesterday = NOW - timedelta(days=1)
        _write_transcript(projects / "p", "s.jsonl", [(yesterday, 700)])
        usage_history.record_today(self.db, 100, TZ, yesterday)
        usage_history.backfill(self.db, claude_dir=projects, rollouts_dir=None,
                               opencode_db=None, tz=TZ, now=NOW,
                               replace_existing=True)
        con = sqlite3.connect(self.db)
        try:
            value = con.execute("SELECT tokens FROM usage_history WHERE day = ?",
                                (yesterday.date().isoformat(),)).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(700, value)

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

    def test_hourly_backfill_preserves_closed_hours_and_refreshes_current_hour(self):
        projects = Path(self._tmp.name) / "projects"
        projects.mkdir()
        closed_hour = NOW - timedelta(days=1)
        current_hour = NOW.replace(minute=0, second=0, microsecond=0)

        def event(at: datetime, tokens: int) -> UsageBreakdown:
            return UsageBreakdown(
                at=at, provider="claude", model="claude-test",
                input_tokens=tokens, output_tokens=0, reasoning_tokens=0,
                cache_write_tokens=0, consumed_tokens=tokens)

        with patch("usage_tracker.claude_usage_events", return_value=[
                event(closed_hour, 100), event(current_hour, 200)]):
            usage_history.backfill_hourly(
                self.db, claude_dir=projects, rollouts_dir=None,
                opencode_db=None, now=NOW, days=30,
                replace_existing_since=current_hour)

        with patch("usage_tracker.claude_usage_events", return_value=[
                event(closed_hour, 7000), event(current_hour, 9000)]):
            usage_history.backfill_hourly(
                self.db, claude_dir=projects, rollouts_dir=None,
                opencode_db=None, now=NOW, days=30,
                replace_existing_since=current_hour)

        con = sqlite3.connect(self.db)
        try:
            rows = {row[0]: row[1:] for row in con.execute(
                "SELECT hour_start_utc, input_tokens, consumed_tokens "
                "FROM usage_history_hourly WHERE provider = 'claude' "
                "AND model = 'claude-test'")}
        finally:
            con.close()
        self.assertEqual((100, 100), rows[usage_history._hour_key(closed_hour)])
        self.assertEqual((9000, 9000), rows[usage_history._hour_key(current_hour)])


class CodexBackfillTests(unittest.TestCase):
    def test_codex_excludes_cached_input_from_consumption(self):
        with tempfile.TemporaryDirectory() as tmp:
            rollouts = Path(tmp) / "codex"
            day = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
            _write_detailed_rollout(rollouts, "rollout-detailed.jsonl", [
                (day, {"input_tokens": 1000, "cached_input_tokens": 900,
                       "output_tokens": 50, "reasoning_output_tokens": 25,
                       "cache_write_input_tokens": 10, "total_tokens": 1050}),
                (day + timedelta(hours=1),
                 {"input_tokens": 1600, "cached_input_tokens": 1400,
                  "output_tokens": 80, "reasoning_output_tokens": 40,
                  "cache_write_input_tokens": 20, "total_tokens": 1680}),
            ])
            db = Path(tmp) / "hist.db"
            usage_history.backfill(db, claude_dir=None, rollouts_dir=rollouts,
                                   opencode_db=None, tz=TZ, now=NOW)
            window = usage_history.daily_window(db, TZ, now=NOW)
            self.assertEqual(340, window[28])

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

    def test_force_backfill_fills_days_the_daemon_was_off(self):
        """Com o backfill limitado ao boot vazio, todo dia sem daemon virava 0
        para sempre (medido: 12–14/09/2026 sumiram do heatmap). `force_backfill`
        (boot do daemon e virada do dia local) repovoa sem tocar linhas vivas."""
        import session_daemon
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "hist.db"
            projects = root / "claude" / "proj"
            _write_transcript(projects, "ontem.jsonl",
                              [(NOW - timedelta(days=1), 7000)])
            # Estado anterior ao fix: linha viva de hoje, dia parado sem linha.
            usage_history.record_today(db, 100, TZ, NOW)
            payload = session_daemon.build_payload_v1(
                root / "claude", root / "missing-index", 6, TZ, now=NOW,
                history_db=db, codex_rollouts_dir=root / "rollouts")
            self.assertEqual(0, payload["stats"]["history"]["daily"][28])  # ontem = 0
            payload = session_daemon.build_payload_v1(
                root / "claude", root / "missing-index", 6, TZ, now=NOW,
                history_db=db, force_backfill=True,
                codex_rollouts_dir=root / "rollouts")
            self.assertEqual(7000, payload["stats"]["history"]["daily"][28])

    def test_startup_backfill_preserves_closed_days_and_refreshes_today(self):
        import session_daemon
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            projects = root / "claude" / "proj"
            yesterday = NOW - timedelta(days=1)
            _write_transcript(projects, "usage.jsonl", [
                (yesterday, 7000), (NOW, 8000)])
            db = root / "hist.db"
            usage_history.record_today(db, 123, TZ, yesterday)

            with patch.object(session_daemon, "CODEX_SESSIONS", root / "missing-codex"):
                history = session_daemon._record_daily_history(
                    db, root / "claude", TZ, NOW, 999,
                    opencode_db=None, force_backfill=True,
                    rollouts_dir=None, commandcode_dir=None)

        self.assertEqual(123, history["daily"][28])  # dia fechado preservado
        self.assertEqual(999, history["daily"][29])  # dia corrente atualizado

    def test_daily_history_uses_custom_codex_rollouts_directory(self):
        import session_daemon
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollouts = root / "custom-codex" / "sessions"
            _write_rollout(rollouts, "rollout-custom.jsonl", [
                (NOW - timedelta(hours=1), 200), (NOW, 500)])
            history = session_daemon._record_daily_history(
                root / "history.db", root / "claude", TZ, NOW, 0,
                opencode_db=None, force_backfill=True, rollouts_dir=rollouts,
                commandcode_dir=None)
        self.assertEqual(500, history["daily"][-1])

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
