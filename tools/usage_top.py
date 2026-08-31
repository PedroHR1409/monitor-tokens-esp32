"""Agregacao de consumo por agente nas janelas 1/7/30 dias (card de podio).

Reutiliza os MESMOS coletores das sessoes ao vivo — o total de cada provider aqui e
a soma completa das sessoes dele, e o cap de 6 no modal nunca altera o ranking.
Semantica de tokens identica ao historico diario: input+output+reasoning+
cache.write (Claude via dedup por message.id, Codex via diff acumulado do rollout,
OpenCode pelos turnos do banco local).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from opencode_sessions import scan_opencode_sessions
from session_state import strip_accents

PERIODS = (("d1", 1), ("d7", 7), ("d30", 30))
PROVIDERS = ("claude", "codex", "opencode")
TOP_N = 6
NAME_MAX = 25

# O claude d30 reler caudas de transcripts ativos (que mudam de mtime a cada ciclo,
# matando qualquer cache por arquivo) custa ~4s por ciclo — mais que o intervalo do
# daemon. Ranking de podio nao precisa de frescor de 5s: resultado cacheado por TTL.
_TOP_TTL_S = 60.0
_top_cache: dict = {"key": None, "at": 0.0, "data": None}


def build_cached(claude_dir: Path, codex_index: Path, opencode_db: Path | None,
                 tz: timezone, now: datetime | None = None,
                 top_n: int = TOP_N, ttl_s: float = _TOP_TTL_S) -> dict:
    import time as _time
    now = now or datetime.now(timezone.utc)
    key = (str(claude_dir), str(codex_index), str(opencode_db))
    mono = _time.monotonic()
    if (_top_cache["data"] is not None and _top_cache["key"] == key
            and mono - _top_cache["at"] < ttl_s):
        return _top_cache["data"]
    data = build(claude_dir, codex_index, opencode_db, tz, now, top_n)
    _top_cache.update(key=key, at=mono, data=data)
    return data


def build(claude_dir: Path, codex_index: Path, opencode_db: Path | None,
          tz: timezone, now: datetime | None = None, top_n: int = TOP_N) -> dict:
    now = now or datetime.now(timezone.utc)
    out: dict = {}
    for key, days in PERIODS:
        midnight = (now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
                    - timedelta(days=days - 1))
        out[key] = {
            "claude": _claude(claude_dir, midnight, tz, top_n),
            "codex": _codex(codex_index, midnight, tz, now, top_n),
            "opencode": _opencode(opencode_db, midnight, tz, now, top_n),
        }
    return out


def _entry(total: int, sessions: list[dict], top_n: int) -> dict:
    ordered = sorted(sessions, key=lambda s: (-s["tokens"], s["name"]))[:top_n]
    return {"total": total, "sessions": [
        {"id": s["id"], "name": s["name"][:NAME_MAX], "tokens": s["tokens"]}
        for s in ordered if s["tokens"] > 0]}


def _claude(projects_dir: Path, since: datetime, tz: timezone, top_n: int) -> dict:
    from session_daemon import project_name_of, read_tail_json_objects
    from usage_tracker import session_tokens

    total = 0
    sessions: list[dict] = []
    if not projects_dir.is_dir():
        return _entry(0, [], top_n)
    start_ts = since.timestamp()
    for project in projects_dir.iterdir():
        if not project.is_dir():
            continue
        for path in project.glob("*.jsonl"):
            try:
                if path.stat().st_mtime < start_ts:
                    continue            # nao foi tocado na janela: pula sem abrir
            except OSError:
                continue
            tokens = session_tokens(path, since)
            if tokens <= 0:
                continue
            total += tokens
            try:
                objs = read_tail_json_objects(path)
            except OSError:
                objs = []
            name = (project_name_of(objs, project.name, limit=NAME_MAX)
                    if objs else project.name[:NAME_MAX])
            sessions.append({"id": path.stem[:36], "name": name, "tokens": tokens})
    return _entry(total, sessions, top_n)


def _codex(index_path: Path, since: datetime, tz: timezone,
           now: datetime, top_n: int) -> dict:
    from session_daemon import codex_meta

    total = 0
    sessions: list[dict] = []
    if not index_path.is_file():
        return _entry(0, [], top_n)
    latest: dict[str, dict] = {}
    try:
        with index_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("id"):
                    latest[str(obj["id"])] = obj
    except OSError:
        return _entry(0, [], top_n)

    for tid, obj in latest.items():
        meta = codex_meta(str(tid), since)
        tokens = meta["tokens"]
        if tokens <= 0:
            continue
        total += tokens
        name = strip_accents(obj.get("thread_name") or "codex")[:NAME_MAX]
        sessions.append({"id": str(tid)[:36], "name": name, "tokens": tokens})
    return _entry(total, sessions, top_n)


def _opencode(opencode_db: Path | None, since: datetime, tz: timezone,
              now: datetime, top_n: int) -> dict:
    if opencode_db is None:
        return _entry(0, [], top_n)
    sessions = scan_opencode_sessions(now, token_since=since, database=opencode_db)
    entries = [{"id": s["id"], "name": s["project"], "tokens": s["tokensWin"]}
               for s in sessions]
    return _entry(sum(e["tokens"] for e in entries), entries, top_n)
