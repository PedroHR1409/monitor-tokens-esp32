"""Coletor de sessoes do OpenCode a partir do banco local (SQLite).

O OpenCode grava tudo em `~/.local/share/opencode/opencode.db`: a tabela `session`
tem agente/modelo/totais de tokens, a `message` guarda os tokens por turno e o
`directory` permite derivar a branch git igual ao que ja e feito para Claude/Codex.
Sessao, modelo, effort (`variant`), tokens e contexto saem daqui sem nenhum parsing
de transcript — e mais preciso que o Claude e mais leve que o Codex.

Nao existe cota de servidor nem sinal de permissao estruturado, entao:
- `ctxPct` so e calculado se a janela do modelo for declarada em
  `usage.opencode_context_window` (0 = desconhecido, como no Claude sem teto).
- estados detectados: `work` (atividade recente) e `free`; `ask`/`perm` ficam
  para quando o OpenCode publicar sinais estruturados.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from session_state import session_display_name, strip_accents, WORK_MAX_AGE_S
from session_meta import read_git_branch

DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"

FULL_NAME_MAX = 38
SOURCE_STALE_AFTER_S = 300.0
# Janela de busca dos sinais estruturados (ask/perm) e idade maxima do sinal.
SIGNAL_WINDOW_S = 3600.0
SIGNAL_MAX_AGE_S = 3600.0
# Janela de contexto POR MODELO (APROXIMACAO, validada contra o % do OpenCode:
# 584k tokens exibidos como 58% -> glm-5.3-flash ~ 1M). Override por
# usage.opencode_context_window no monitor.toml (vale para todas as sessoes).
DEFAULT_CONTEXT_WINDOW = 128000
MODEL_CONTEXT_WINDOWS = (("glm", 1000000), ("deepseek", 128000))


def context_window_for(model_id: str, provider_id: str, configured: int) -> int:
    """Janela de contexto: config explicita > tabela por modelo > default."""
    if configured > 0:
        return configured
    for needle, window in MODEL_CONTEXT_WINDOWS:
        if needle in (model_id or "").lower() or needle in (provider_id or "").lower():
            return window
    return DEFAULT_CONTEXT_WINDOW

# providerID/modelID -> provedor do icone no firmware (src/assets/*_icon.png).
PROVIDERS_BY_MODEL = (("glm", "zai"), ("deepseek", "deepseek"))
PROVIDERS_BY_DB = (("deepseek", "deepseek"), ("zai", "zai"), ("z-dot", "zai"))


def db_path() -> Path:
    override = os.environ.get("MONITOR_OPENCODE_DB", "").strip()
    return Path(override) if override else DB_PATH


def provider_of(model_id: str, provider_id: str) -> str:
    """'glm-5.3-flash' -> 'zai'; 'deepseek-chat' -> 'deepseek'; '' = icone padrao."""
    model = (model_id or "").lower()
    for needle, provider in PROVIDERS_BY_MODEL:
        if needle in model:
            return provider
    db = (provider_id or "").lower()
    for needle, provider in PROVIDERS_BY_DB:
        if needle in db:
            return provider
    return ""


def short_model(model_id: str) -> str:
    """Mesma regra do daemon para o Codex: corta a data de release longa."""
    parts = strip_accents(model_id or "").split("-")
    while parts and parts[-1].isdigit() and len(parts[-1]) >= 6:
        parts.pop()
    return "-".join(parts)[:14]


def _rows(db: Path, query: str, params: tuple = ()) -> list[dict]:
    if not db.is_file():
        return []
    try:
        con = sqlite3.connect("file:{}?mode=ro".format(db.as_posix()), uri=True)
    except sqlite3.Error:
        return []
    con.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in con.execute(query, params)]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _project_name(session: dict, branch: str) -> str:
    """Nome do card pela regra unica: branch nao-principal vence o projeto.

    Projeto = pasta do `directory` (o `title` do OpenCode e a primeira mensagem/
    resumo, que nao identifica o projeto) com fallback title/slug."""
    directory = str(session.get("directory") or "")
    project = ""
    if directory.strip() and Path(directory).name.strip():
        project = strip_accents(Path(directory).name)[:FULL_NAME_MAX]
    if not project:
        project = (strip_accents(str(session.get("title") or "")).strip()
                   or strip_accents(str(session.get("slug") or "opencode")))[:FULL_NAME_MAX]
    display = session_display_name(project, branch)[:FULL_NAME_MAX]
    return display or "opencode"


def _message_totals(messages: list[dict], since_epoch: float | None) -> tuple[int, int]:
    """(tokens na janela, tokens de contexto da ultima resposta).

    O input se repete a cada turno (o prompt inteiro vai de novo), e o cache.read
    acompanha: somar os dois como "consumo" inflaria o card com re-leitura. Entao a
    janela conta input+output+reasoning+cache.write (o que o turno efetivamente
    queimou), enquanto o CONTEXTO usa a ultima resposta inteira: input+cache+output
    e exatamente o que estava na janela do modelo naquele turno.
    """
    window = 0
    context = 0
    for message in messages:
        data = message.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                continue
        if not isinstance(data, dict) or data.get("role") != "assistant":
            continue
        tokens = data.get("tokens") or {}
        if not isinstance(tokens, dict):
            continue
        cache = tokens.get("cache") or {}
        created = (message.get("time_created") or 0) / 1000.0
        if since_epoch is None or created >= since_epoch:
            window += (int(tokens.get("input") or 0) + int(tokens.get("output") or 0)
                       + int(tokens.get("reasoning") or 0) + int(cache.get("write") or 0))
        if tokens.get("output"):
            context = (int(tokens.get("input") or 0) + int(cache.get("read") or 0)
                       + int(cache.get("write") or 0) + int(tokens.get("output") or 0))
    return window, context


def scan_opencode_sessions(now: datetime, token_since: datetime | None = None,
                           database: Path | None = None, ctx_window: int = 0) -> list:
    """Mesma forma do scan_claude_sessions/scan_codex_sessions: um dict por sessao."""
    db = database if database is not None else db_path()
    sessions = _rows(db, "SELECT * FROM session WHERE time_archived IS NULL "
                         "ORDER BY time_updated DESC")
    signals = session_structured_states(db, now - timedelta(seconds=SIGNAL_WINDOW_S))
    if not sessions:
        return []

    since_epoch = token_since.timestamp() if token_since else None
    out = []
    for session in sessions:
        sid = str(session["id"])
        updated_ms = session.get("time_updated") or session.get("time_created") or 0
        last = datetime.fromtimestamp(updated_ms / 1000.0, tz=timezone.utc)
        age = max((now - last).total_seconds(), 0.0)
        if age > 24 * 3600:
            continue               # db cresce para sempre; sem isso o scan degrada

        model = {}
        try:
            model = json.loads(session.get("model") or "{}")
        except (json.JSONDecodeError, TypeError):
            pass
        model_id = str(model.get("id") or "")
        provider_db = str(model.get("providerID") or "")
        directory = str(session.get("directory") or "")

        messages = _rows(db, "SELECT data, time_created, time_updated FROM message "
                             "WHERE session_id = ?", (sid,))
        tokens_win, context_tokens = _message_totals(messages, since_epoch)

        state = "work" if age <= WORK_MAX_AGE_S else "free"
        state_age = age
        signal = signals.get(sid)
        if signal:
            signal_state, signal_created = signal
            signal_age = max((now - datetime.fromtimestamp(signal_created, tz=timezone.utc))
                             .total_seconds(), 0.0)
            if signal_age <= SIGNAL_MAX_AGE_S:
                state = signal_state
                state_age = signal_age
        window = context_window_for(model_id, provider_db, ctx_window)
        ctx_quality = "measured" if ctx_window > 0 else "estimated"
        ctx_pct = (min(100, int(context_tokens * 100 / window))
                   if window > 0 and context_tokens > 0 else 0)
        branch = strip_accents(read_git_branch(directory))[:20]
        out.append({
            "id": sid,
            "project": _project_name(session, branch),
            "full": _project_name(session, branch),
            "branch": branch,
            "model": short_model(model_id),
            "provider": provider_of(model_id, provider_db),
            "effort": strip_accents(str(model.get("variant") or ""))[:8],
            "tokensWin": tokens_win,
            "ctxPct": ctx_pct,
            "context": {"value": ctx_pct if window > 0 and context_tokens > 0 else None,
                        "quality": ctx_quality if context_tokens > 0 else "unknown",
                        "unit": "percent"},
            "context_tokens": context_tokens,
            "tool": "opencode",
            "state": state,
            "elapsed": int(state_age),  # firmware exige uint64 no JSON (422 senao)
            "source_stale": state == "work" and age > SOURCE_STALE_AFTER_S,
            "source_age_s": int(state_age),
            "diagnostic": "" if ctx_window > 0 else "context_estimated",
            "_age": age,
        })
    return out


def window_tokens(database: Path | None, since_epoch: float | None = None) -> int:
    """Consumo (input+output+reasoning+cache.write) do OpenCode desde `since_epoch`.

    Mesma semantica do tokensWin por sessao, mas agregado — alimenta o card
    rotativo de consumo 5h. `database=None` cai no banco do usuario."""
    messages = _rows(database if database is not None else db_path(),
                     "SELECT data, time_created FROM message WHERE time_created >= ?",
                     (0 if since_epoch is None else int(since_epoch * 1000),))
    total, _ = _message_totals(messages, None)
    return total


def session_structured_states(database: Path | None, since: datetime) -> dict[str, tuple[str, float]]:
    """Sinais estruturados de estado por sessao, do ULTIMO tool part de cada uma.

    A pergunta ao usuario deixa a tool `question` em "running" ate ser respondida
    (estado `ask`). O pedido de PERMISSAO do OpenCode nao e persistido no SQLite
    (tabela permission vazia e "pending" e estado de pipeline), entao `perm` nao e
    detectavel por esta fonte. Devolve {session_id: (estado, epoch_s)}."""
    # Partes sao ATUALIZADAS IN-PLACE (mesmo id: pending -> running -> completed).
    # O estado real da sessao vem da parte com o maior time_updated — nunca de um
    # pending antigo que sobreviveu no historico (falso "perm" medido em 31/08).
    rows = _rows(database if database is not None else db_path(),
                 "SELECT session_id, data, time_updated FROM part "
                 "WHERE time_updated >= ? AND json_extract(data, '$.type') = 'tool' "
                 "ORDER BY time_updated ASC",
                 (int(since.timestamp() * 1000),))
    latest: dict[str, tuple[str, float]] = {}
    for row in rows:
        try:
            part = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            continue
        state = ((part.get("state") or {}).get("status") or "")
        tool = part.get("tool") or ""
        signal = None
        # "pending" NAO e perm: e estado de pipeline (tool criada antes de executar
        # e atualizada in-place segundos depois) — mapear para perm gerava falso
        # positivo durante trabalho normal (medido 31/08). E o pedido de PERMISSAO
        # do OpenCode nao e persistido no SQLite (tabela permission vazia) — perm
        # fica indisponivel para esta fonte ate um sinal persistido existir.
        if tool == "question" and state == "running":
            signal = "ask"
        # O ULTIMO tool part vence SEMPRE (sinal ou nao) — um running posterior
        # invalida um sinal anterior.
        latest[row["session_id"]] = (signal or "", (row["time_updated"] or 0) / 1000.0)
    return {sid: value for sid, value in latest.items() if value[0]}


def turn_token_events(database: Path | None, since: datetime | None = None):
    """Pares (datetime_utc, tokens) por turno do OpenCode, mais antigo primeiro.

    Mesma semântica do tokensWin (input+output+reasoning+cache.write); consumido
    pelo backfill do histórico diário. `since` filtra por time_created."""
    params: tuple = ()
    query = "SELECT data, time_created FROM message"
    if since is not None:
        query += " WHERE time_created >= ?"
        params = (int(since.timestamp() * 1000),)
    for message in _rows(database if database is not None else db_path(), query, params):
        data = message.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                continue
        if not isinstance(data, dict) or data.get("role") != "assistant":
            continue
        tokens = data.get("tokens") or {}
        if not isinstance(tokens, dict):
            continue
        cache = tokens.get("cache") or {}
        total = (int(tokens.get("input") or 0) + int(tokens.get("output") or 0)
                 + int(tokens.get("reasoning") or 0) + int(cache.get("write") or 0))
        if total <= 0:
            continue
        created = message.get("time_created") or 0
        yield datetime.fromtimestamp(created / 1000.0, tz=timezone.utc), total


def count_active_12h(database: Path | None, now: datetime, window_s: float) -> int:
    """Sessoes do OpenCode com mensagem na janela; espelha count_active_12h."""
    cutoff = now - timedelta(seconds=window_s)
    rows = _rows(database if database is not None else db_path(),
                 "SELECT DISTINCT m.session_id AS sid FROM message m "
                 "JOIN session s ON s.id = m.session_id "
                 "WHERE m.time_created >= ? AND s.time_archived IS NULL",
                 (int(cutoff.timestamp() * 1000),))
    return len(rows)
