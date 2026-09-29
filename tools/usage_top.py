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

from commandcode_sessions import scan_commandcode_sessions
from opencode_sessions import scan_opencode_sessions
from session_meta import read_git_branch
from session_state import session_display_name, strip_accents

PERIODS = (("d1", 1), ("d7", 7), ("d30", 30))
PROVIDERS = ("claude", "codex", "opencode", "commandcode")
TOP_N = 6
NAME_MAX = 25

# O claude d30 reler caudas de transcripts ativos (que mudam de mtime a cada ciclo,
# matando qualquer cache por arquivo) custa ~4s por ciclo — mais que o intervalo do
# daemon. Ranking de podio nao precisa de frescor de 5s: resultado cacheado por TTL.
_TOP_TTL_S = 60.0
_top_cache: dict = {"key": None, "at": 0.0, "data": None}

# TTL POR PERIODO (caminho de producao, ttl_s=None): d1 acompanha o ciclo, d7 e
# d30 sao janelas historicas — reprocessa-las a cada 5s custava ~40s/ciclo e
# fazia o painel atualizar de minuto em minuto. `ttl_s` explicito (API antiga e
# testes) preserva o cache unico de um periodo so.
_PERIOD_TTL_S = {"d1": 60.0, "d7": 300.0, "d30": 900.0}
_period_cache: dict = {}


def build_cached(claude_dir: Path, codex_index: Path, opencode_db: Path | None,
                 tz: timezone, now: datetime | None = None,
                 top_n: int = TOP_N, ttl_s: float | None = _TOP_TTL_S,
                 codex_rollouts_dir: Path | None = None,
                 commandcode_dir: Path | None = None) -> dict:
    import time as _time
    now = now or datetime.now(timezone.utc)
    key = (str(claude_dir), str(codex_index), str(opencode_db),
           str(codex_rollouts_dir), str(commandcode_dir))
    mono = _time.monotonic()
    if ttl_s is not None:
        # Caminho legado (um TTL para os tres periodos): usado pelos testes.
        if (_top_cache["data"] is not None and _top_cache["key"] == key
                and mono - _top_cache["at"] < ttl_s):
            return _top_cache["data"]
        data = build(claude_dir, codex_index, opencode_db, tz, now, top_n,
                     codex_rollouts_dir=codex_rollouts_dir,
                     commandcode_dir=commandcode_dir)
        _top_cache.update(key=key, at=mono, data=data)
        return data

    out: dict = {}
    for period_key, days in PERIODS:
        hit = _period_cache.get(period_key)
        if (hit is not None and hit["key"] == key
                and mono - hit["at"] < _PERIOD_TTL_S[period_key]):
            out[period_key] = hit["data"]
            continue
        midnight = (now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
                    - timedelta(days=days - 1))
        data = _build_period(claude_dir, codex_index, opencode_db, midnight,
                             tz, now, top_n, codex_rollouts_dir, commandcode_dir)
        _period_cache[period_key] = {"key": key, "at": mono, "data": data}
        out[period_key] = data
    return out


def _build_period(claude_dir: Path, codex_index: Path, opencode_db: Path | None,
                  midnight: datetime, tz: timezone, now: datetime,
                  top_n: int, codex_rollouts_dir: Path | None,
                  commandcode_dir: Path | None = None) -> dict:
    return {
        "claude": _claude(claude_dir, midnight, tz, top_n),
        "codex": _codex(codex_index, midnight, tz, now, top_n,
                        rollouts_dir=codex_rollouts_dir),
        "opencode": _opencode(opencode_db, midnight, tz, now, top_n),
        "commandcode": _commandcode(commandcode_dir, midnight, tz, now, top_n),
    }


def build(claude_dir: Path, codex_index: Path, opencode_db: Path | None,
          tz: timezone, now: datetime | None = None, top_n: int = TOP_N,
          codex_rollouts_dir: Path | None = None,
          commandcode_dir: Path | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    out: dict = {}
    for key, days in PERIODS:
        midnight = (now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
                    - timedelta(days=days - 1))
        out[key] = _build_period(claude_dir, codex_index, opencode_db, midnight,
                                 tz, now, top_n, codex_rollouts_dir, commandcode_dir)
    return out


def _entry(total: int, sessions: list[dict], top_n: int) -> dict:
    ordered = sorted(sessions, key=lambda s: (-s["tokens"], s["name"]))[:top_n]
    return {"total": total, "sessions": [
        {"id": s["id"], "name": s["name"][:NAME_MAX], "tokens": s["tokens"]}
        for s in ordered if s["tokens"] > 0]}


def _claude(projects_dir: Path, since: datetime, tz: timezone, top_n: int) -> dict:
    from session_daemon import meta_of, project_name_of, read_tail_json_objects
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
            proj = (project_name_of(objs, project.name, limit=NAME_MAX)
                    if objs else project.name[:NAME_MAX])
            branch, _, _ = meta_of(objs) if objs else ("", "", "")
            name = session_display_name(proj, branch)[:NAME_MAX]
            sessions.append({"id": path.stem[:36], "name": name, "tokens": tokens})
    return _entry(total, sessions, top_n)


def _codex(index_path: Path, since: datetime, tz: timezone,
           now: datetime, top_n: int,
           rollouts_dir: Path | None = None) -> dict:
    """Total e top de sessoes do Codex na janela.

    A identidade vem do indice E dos rollouts no disco: o session_index parou de
    receber sessoes novas (15/09/2026) e o pódio exibia 0 mesmo com o Codex
    rodando no dia — os coletores de sessoes usam a MESMA uniao. Mtime do rollout
    abaixo de `since` ja pula a sessao sem abrir o arquivo (mesma regra do
    _claude); `rollouts_dir=None` (tests hermeticos) desliga a varredura."""
    from session_daemon import codex_meta, recent_rollouts

    total = 0
    sessions: list[dict] = []
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
        pass                       # indice ausente: os rollouts recentes ainda valem

    if rollouts_dir is not None:
        window_s = max((now - since).total_seconds(), 0.0)
        for rid in recent_rollouts(rollouts_dir, window_s, now.timestamp()):
            latest.setdefault(rid, {"id": rid, "thread_name": "codex"})

    # Pre-filtro barato: rollout nao tocado desde `since` nao tem token novo na
    # janela — pula sem abrir o arquivo (que chega a dezenas de MB). E o que
    # impede o d30 de reler todo o diretorio a cada recalculo. Somente com
    # rollouts_dir (producao): no modo hermetico nao varre disco real.
    candidates: list[tuple[str, dict]] = list(latest.items())
    if rollouts_dir is not None:
        from session_meta import _rollout_for
        candidates = []
        for tid, obj in latest.items():
            path = _rollout_for(str(tid), rollouts_dir)
            try:
                fresco = path is None or path.stat().st_mtime >= since.timestamp()
            except OSError:
                continue
            if fresco:
                candidates.append((tid, obj))

    for tid, obj in candidates:
        meta = codex_meta(str(tid), since, rollouts_dir=rollouts_dir)
        tokens = meta["tokens"]
        if tokens <= 0:
            continue
        total += tokens
        branch = strip_accents(read_git_branch(meta["cwd"]))[:NAME_MAX]
        project = strip_accents(obj.get("thread_name") or "codex")[:NAME_MAX]
        name = session_display_name(project, branch)[:NAME_MAX]
        sessions.append({"id": str(tid)[:36], "name": name, "tokens": tokens})
    return _entry(total, sessions, top_n)


def _opencode(opencode_db: Path | None, since: datetime, tz: timezone,
              now: datetime, top_n: int) -> dict:
    if opencode_db is None:
        return _entry(0, [], top_n)
    # O scanner de sessoes e deliberadamente limitado a 24h para o board ao vivo.
    # O podio historico precisa usar todas as mensagens da janela, inclusive sessoes
    # ja encerradas.
    from opencode_sessions import turn_token_events
    total = sum(tokens for _, tokens in turn_token_events(opencode_db, since))
    sessions = scan_opencode_sessions(now, token_since=since, database=opencode_db,
                                      include_old=True)
    entries = [{"id": s["id"], "name": s["project"], "tokens": s["tokensWin"]}
               for s in sessions]
    return _entry(total, entries, top_n)


def _commandcode(projects_dir: Path | None, since: datetime, tz: timezone,
                 now: datetime, top_n: int) -> dict:
    if projects_dir is None:
        return _entry(0, [], top_n)
    # Mesmo motivo do OpenCode: sessoes antigas continuam contribuindo para d7/d30
    # mesmo quando ja nao devem ocupar um card ao vivo.
    from commandcode_sessions import turn_token_events
    total = sum(tokens for _, tokens in turn_token_events(projects_dir, since))
    sessions = scan_commandcode_sessions(now, token_since=since, directory=projects_dir,
                                         include_old=True)
    entries = [{"id": s["id"], "name": s["project"], "tokens": s["tokensWin"]}
               for s in sessions]
    return _entry(total, entries, top_n)
