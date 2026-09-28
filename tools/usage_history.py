"""Históricos diário e horário de tokens do Monitor.AI.

O heatmap de 30 dias precisa de um total por dia local que sobreviva a restart do
daemon e à rotação dos arquivos-fonte (transcripts e rollouts somem com o tempo).
Este módulo é a única fonte de verdade desse histórico: tudo que o painel exibe
(heatmap, pódio, detalhe) lê daqui, então nunca há dois números discordando.

Semântica de consumo (fixada no DEFINE): input + output + reasoning + cache.write.
cache.read é re-leitura de contexto, não queima nova — incluiria ~3,4M contra ~150k
reais num dia típico e esconderia a vareração que importa.

O backfill diário automático preenche apenas dias sem linha. A substituição de uma
linha existente continua disponível na API de baixo nível para uma reparação explícita,
mas não é usada no boot nem na atualização automática do daemon.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from session_state import parse_ts

# Alinhado a StorageSettings.retention_days (monitor_config). O daemon passa o valor
# do config explicitamente; esta constante e so o default de chamadas diretas.
RETENTION_DAYS = 30
HOURLY_RETENTION_DAYS = 365
WINDOW_DAYS = 30

_SCHEMA = ("CREATE TABLE IF NOT EXISTS usage_history ("
           "day TEXT PRIMARY KEY, tokens INTEGER NOT NULL)")
_HOURLY_SCHEMA = ("CREATE TABLE IF NOT EXISTS usage_history_hourly ("
                  "hour_start_utc TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, "
                  "input_tokens INTEGER CHECK(input_tokens IS NULL OR input_tokens >= 0), "
                  "output_tokens INTEGER CHECK(output_tokens IS NULL OR output_tokens >= 0), "
                  "reasoning_tokens INTEGER CHECK(reasoning_tokens IS NULL OR reasoning_tokens >= 0), "
                  "cache_write_tokens INTEGER CHECK(cache_write_tokens IS NULL OR cache_write_tokens >= 0), "
                  "consumed_tokens INTEGER NOT NULL CHECK(consumed_tokens >= 0), "
                  "PRIMARY KEY(hour_start_utc, provider, model))")


@contextmanager
def _connect(db_path: Path):
    # fecha de verdade (o with de sqlite3 so faz commit) — no Windows, handle
    # aberto impede o cleanup do tempdir nos testes
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.execute(_SCHEMA)
        con.execute(_HOURLY_SCHEMA)
        con.execute("CREATE INDEX IF NOT EXISTS usage_history_hourly_by_hour "
                    "ON usage_history_hourly(hour_start_utc)")
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


def hourly_is_empty(db_path: Path) -> bool:
    with _connect(db_path) as con:
        return con.execute("SELECT COUNT(*) FROM usage_history_hourly").fetchone()[0] == 0


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hour_key(value: datetime) -> str:
    hour = _utc_datetime(value).replace(minute=0, second=0, microsecond=0)
    return hour.isoformat(timespec="seconds")


def hourly_range(db_path: Path, start: datetime, end: datetime) -> list[dict]:
    """Linhas ordenadas para intervalo UTC semiaberto [start, end)."""
    start_key = _utc_datetime(start).isoformat(timespec="seconds")
    end_key = _utc_datetime(end).isoformat(timespec="seconds")
    columns = ("hour_start_utc", "provider", "model", "input_tokens",
               "output_tokens", "reasoning_tokens", "cache_write_tokens",
               "consumed_tokens")
    with _connect(db_path) as con:
        rows = con.execute(
            "SELECT " + ", ".join(columns) + " FROM usage_history_hourly "
            "WHERE julianday(hour_start_utc) >= julianday(?) "
            "AND julianday(hour_start_utc) < julianday(?) "
            "ORDER BY hour_start_utc, provider, model", (start_key, end_key))
        return [dict(zip(columns, row)) for row in rows]


def prune_hourly(db_path: Path, keep_days: int = HOURLY_RETENTION_DAYS,
                 now: datetime | None = None) -> int:
    """Remove buckets anteriores à retenção horária UTC configurada."""
    observed = _utc_datetime(now or datetime.now(timezone.utc))
    cutoff = (observed - timedelta(days=max(int(keep_days), 0)))
    cutoff = cutoff.replace(minute=0, second=0, microsecond=0)
    cutoff_key = cutoff.isoformat(timespec="seconds")
    with _connect(db_path) as con:
        cursor = con.execute("DELETE FROM usage_history_hourly WHERE hour_start_utc < ?",
                             (cutoff_key,))
        return cursor.rowcount if cursor.rowcount > 0 else 0


def backfill_hourly(db_path: Path, *, claude_dir: Path | None,
                    rollouts_dir: Path | None, opencode_db: Path | None,
                    commandcode_dir: Path | None = None,
                    now: datetime | None = None, days: int = WINDOW_DAYS,
                    replace_existing_since: datetime | None = None) -> dict[str, int]:
    """Agrega eventos por hora UTC/provedor/modelo e faz upsert idempotente.

    Buckets anteriores a ``replace_existing_since`` só são inseridos se ainda não
    existirem. O daemon usa esse corte na hora UTC corrente; assim, reiniciar ou perder
    uma fonte não reescreve horas fechadas. Buckets sem eventos nunca são removidos.
    """
    span = min(max(int(days), 0), WINDOW_DAYS)
    if span == 0:
        return {}
    observed = _utc_datetime(now or datetime.now(timezone.utc))
    since = (observed.replace(hour=0, minute=0, second=0, microsecond=0)
             - timedelta(days=span - 1))
    refresh_key = (_hour_key(replace_existing_since)
                   if replace_existing_since is not None else None)
    aggregates: dict[tuple[str, str, str], dict] = {}

    def add(event) -> None:
        if event.consumed_tokens <= 0:
            return
        key = (_hour_key(event.at), str(event.provider or "unknown"),
               str(event.model or "unknown"))
        bucket = aggregates.setdefault(key, {
            "input": 0, "output": 0, "reasoning": 0, "cache_write": 0,
            "known": {"input": True, "output": True,
                      "reasoning": True, "cache_write": True},
            "consumed": 0,
        })
        for name, value in (("input", event.input_tokens),
                            ("output", event.output_tokens),
                            ("reasoning", event.reasoning_tokens),
                            ("cache_write", event.cache_write_tokens)):
            if value is None:
                bucket["known"][name] = False
            else:
                bucket[name] += max(int(value), 0)
        bucket["consumed"] += max(int(event.consumed_tokens), 0)

    def collect(events) -> None:
        try:
            for event in events:
                add(event)
        except (OSError, sqlite3.Error, TypeError, ValueError, KeyError, AttributeError):
            # Uma fonte parcial/temporariamente indisponível não invalida as demais.
            return

    # Imports tardios mantêm o caminho diário independente dos coletores detalhados.
    if claude_dir is not None and Path(claude_dir).is_dir():
        from usage_tracker import claude_usage_events
        collect(claude_usage_events(Path(claude_dir), since))
    if rollouts_dir is not None and Path(rollouts_dir).is_dir():
        from usage_tracker import codex_usage_events
        collect(codex_usage_events(Path(rollouts_dir), since))
    if opencode_db is not None and Path(opencode_db).is_file():
        from opencode_sessions import turn_usage_events
        collect(turn_usage_events(Path(opencode_db), since))
    if commandcode_dir is not None and Path(commandcode_dir).is_dir():
        from commandcode_sessions import turn_usage_events
        collect(turn_usage_events(Path(commandcode_dir), since))

    recorded: dict[str, int] = {}
    with _connect(db_path) as con:
        for key, bucket in sorted(aggregates.items()):
            components = tuple(bucket[name] if bucket["known"][name] else None
                               for name in ("input", "output", "reasoning", "cache_write"))
            values = (*key, *components, bucket["consumed"])
            insert = (
                "INSERT INTO usage_history_hourly "
                "(hour_start_utc, provider, model, input_tokens, output_tokens, "
                "reasoning_tokens, cache_write_tokens, consumed_tokens) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ")
            if refresh_key is not None and key[0] >= refresh_key:
                con.execute(
                    insert + "ON CONFLICT(hour_start_utc, provider, model) DO UPDATE SET "
                    "input_tokens=excluded.input_tokens, output_tokens=excluded.output_tokens, "
                    "reasoning_tokens=excluded.reasoning_tokens, "
                    "cache_write_tokens=excluded.cache_write_tokens, "
                    "consumed_tokens=excluded.consumed_tokens", values)
            else:
                con.execute(insert + "ON CONFLICT(hour_start_utc, provider, model) "
                            "DO NOTHING", values)
            recorded["|".join(key)] = bucket["consumed"]
    return recorded


# ---------------------------------------------------------------------------
# Backfill one-shot: reconstrói dias passados a partir das MESMAS fontes e
# semântica dos coletores ao vivo — heatmap e cards nunca discordam.
# ---------------------------------------------------------------------------

def backfill(db_path: Path, *, claude_dir: Path | None, rollouts_dir: Path | None,
             opencode_db: Path | None, tz: timezone, now: datetime | None = None,
             days: int = WINDOW_DAYS, commandcode_dir: Path | None = None,
             replace_existing: bool = False) -> dict[str, int]:
    """Reconstrói o histórico; opcionalmente substitui linhas existentes."""
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
    if commandcode_dir is not None and Path(commandcode_dir).is_dir():
        _backfill_commandcode(commandcode_dir, window_start, tz, buckets)

    recorded: dict[str, int] = {}
    with _connect(db_path) as con:
        for day, tokens in sorted(buckets.items()):
            if tokens <= 0:
                continue
            if replace_existing:
                cursor = con.execute(
                    "INSERT INTO usage_history(day, tokens) VALUES (?, ?) "
                    "ON CONFLICT(day) DO UPDATE SET tokens = excluded.tokens",
                    (day.isoformat(), tokens))
            else:
                cursor = con.execute("INSERT OR IGNORE INTO usage_history(day, tokens) "
                                     "VALUES (?, ?)", (day.isoformat(), tokens))
            if cursor.rowcount:
                recorded[day.isoformat()] = tokens
    return recorded


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


def _backfill_commandcode(projects_dir: Path, window_start: datetime, tz: timezone,
                          buckets: dict[date, int]) -> None:
    from commandcode_sessions import turn_token_events

    for timestamp, tokens in turn_token_events(projects_dir, window_start):
        day = timestamp.astimezone(tz).date()
        buckets[day] = buckets.get(day, 0) + tokens
