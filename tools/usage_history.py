"""Histórico diário de tokens do Monitor.AI — persistência, janela e backfill.

O heatmap de 30 dias precisa de um total por dia local que sobreviva a restart do
daemon e à rotação dos arquivos-fonte (transcripts e rollouts somem com o tempo).
Este módulo é a única fonte de verdade desse histórico: tudo que o painel exibe
(heatmap, pódio, detalhe) lê daqui, então nunca há dois números discordando.

Semântica de consumo (fixada no DEFINE): input + output + reasoning + cache.write.
cache.read é re-leitura de contexto, não queima nova — incluiria ~3,4M contra ~150k
reais num dia típico e esconderia a vareração que importa.

O backfill é one-shot (primeiro boot com tabela vazia) e usa INSERT OR IGNORE:
nunca sobrescreve linha viva, e dias sem cobertura nos arquivos ficam de fora
(em vez de serem inventados como 0) — a janela do payload completa com 0 depois.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from session_state import parse_ts

RETENTION_DAYS = 35
WINDOW_DAYS = 30

_SCHEMA = ("CREATE TABLE IF NOT EXISTS usage_history ("
           "day TEXT PRIMARY KEY, tokens INTEGER NOT NULL)")


@contextmanager
def _connect(db_path: Path):
    # fecha de verdade (o with de sqlite3 so faz commit) — no Windows, handle
    # aberto impede o cleanup do tempdir nos testes
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.execute(_SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def local_today(tz: timezone, now: datetime | None = None) -> date:
    observed = (now or datetime.now(timezone.utc)).astimezone(tz)
    return observed.date()


def record_today(db_path: Path, tokens: int, tz: timezone,
                 now: datetime | None = None) -> str:
    """UPSERT do total de hoje; devolve o dia local gravado (YYYY-MM-DD)."""
    day = local_today(tz, now).isoformat()
    with _connect(db_path) as con:
        con.execute("INSERT INTO usage_history(day, tokens) VALUES (?, ?) "
                    "ON CONFLICT(day) DO UPDATE SET tokens = excluded.tokens",
                    (day, max(int(tokens), 0)))
    return day


def daily_window(db_path: Path, tz: timezone, days: int = WINDOW_DAYS,
                 now: datetime | None = None) -> list[int]:
    """Exatamente `days` ints, oldest-first; dias ausentes = 0."""
    today = local_today(tz, now)
    start = today - timedelta(days=days - 1)
    rows: dict[str, int] = {}
    with _connect(db_path) as con:
        for day, tokens in con.execute(
                "SELECT day, tokens FROM usage_history WHERE day >= ?",
                (start.isoformat(),)):
            rows[day] = int(tokens)
    return [rows.get((start + timedelta(days=i)).isoformat(), 0)
            for i in range(days)]


def prune(db_path: Path, keep_days: int = RETENTION_DAYS, tz: timezone = timezone.utc,
          now: datetime | None = None) -> int:
    """Remove dias fora da retenção; devolve quantas linhas saíram."""
    cutoff = local_today(tz, now) - timedelta(days=keep_days)
    with _connect(db_path) as con:
        cursor = con.execute("DELETE FROM usage_history WHERE day < ?",
                             (cutoff.isoformat(),))
        return cursor.rowcount if cursor.rowcount > 0 else 0


def is_empty(db_path: Path) -> bool:
    with _connect(db_path) as con:
        return con.execute("SELECT COUNT(*) FROM usage_history").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Backfill one-shot: reconstrói dias passados a partir das MESMAS fontes e
# semântica dos coletores ao vivo — heatmap e cards nunca discordam.
# ---------------------------------------------------------------------------

def backfill(db_path: Path, *, claude_dir: Path | None, rollouts_dir: Path | None,
             opencode_db: Path | None, tz: timezone, now: datetime | None = None,
             days: int = WINDOW_DAYS) -> dict[str, int]:
    """Preenche apenas dias sem linha (INSERT OR IGNORE). Devolve o que gravou."""
    buckets: dict[date, int] = {}
    seen: set = set()
    observed = now or datetime.now(timezone.utc)
    window_start = observed.astimezone(tz).replace(hour=0, minute=0, second=0,
                                                   microsecond=0) - timedelta(days=days - 1)

    if claude_dir is not None and claude_dir.is_dir():
        _backfill_claude(claude_dir, window_start, tz, buckets, seen)
    if rollouts_dir is not None and rollouts_dir.is_dir():
        _backfill_codex(rollouts_dir, window_start, tz, buckets)
    if opencode_db is not None and Path(opencode_db).is_file():
        _backfill_opencode(opencode_db, window_start, tz, buckets)

    inserted: dict[str, int] = {}
    with _connect(db_path) as con:
        for day, tokens in sorted(buckets.items()):
            if tokens <= 0:
                continue
            cursor = con.execute("INSERT OR IGNORE INTO usage_history(day, tokens) "
                                 "VALUES (?, ?)", (day.isoformat(), tokens))
            if cursor.rowcount:
                inserted[day.isoformat()] = tokens
    return inserted


def _backfill_claude(projects_dir: Path, window_start: datetime, tz: timezone,
                     buckets: dict[date, int], seen: set) -> None:
    # Imports tardios de propósito: usage_tracker e pesado e este modulo e o unico
    # consumidor do backfill; evita ciclo de import na inicializacao do daemon.
    from usage_tracker import _iter_today_events, dedup_tokens

    start_ts = window_start.timestamp()
    for project in projects_dir.iterdir():
        if not project.is_dir():
            continue
        for path in project.glob("*.jsonl"):
            try:
                if path.stat().st_mtime < start_ts:
                    continue
                for obj, ts in _iter_today_events(path, window_start):
                    tokens = dedup_tokens(seen, obj)
                    if tokens:
                        day = ts.astimezone(tz).date()
                        buckets[day] = buckets.get(day, 0) + tokens
            except OSError:
                continue


def _backfill_codex(rollouts_dir: Path, window_start: datetime, tz: timezone,
                    buckets: dict[date, int]) -> None:
    # Mesma logica de delta acumulado do codex_series (usage_tracker): contador
    # menor = restart do rollout, e o novo acumulado tambem e uso real da janela.
    from usage_tracker import _rollout_total_events

    start_ts = window_start.timestamp()
    try:
        rollouts = rollouts_dir.rglob("rollout-*.jsonl")
        for path in rollouts:
            try:
                if path.stat().st_mtime < start_ts:
                    continue
                events = sorted(_rollout_total_events(path), key=lambda item: item[0])
            except OSError:
                continue
            previous = None
            for timestamp, cumulative in events:
                if timestamp < window_start:
                    previous = cumulative
                    continue
                delta = (cumulative if previous is None or cumulative < previous
                         else cumulative - previous)
                previous = cumulative
                if delta > 0:
                    day = timestamp.astimezone(tz).date()
                    buckets[day] = buckets.get(day, 0) + delta
    except OSError:
        return


def _backfill_opencode(opencode_db: Path, window_start: datetime, tz: timezone,
                       buckets: dict[date, int]) -> None:
    from opencode_sessions import turn_token_events

    for timestamp, tokens in turn_token_events(opencode_db, window_start):
        day = timestamp.astimezone(tz).date()
        buckets[day] = buckets.get(day, 0) + tokens
