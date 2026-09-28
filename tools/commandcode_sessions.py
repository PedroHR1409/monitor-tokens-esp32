"""Coletor de sessoes do Command Code a partir dos transcripts JSONL locais.

O Command Code grava uma sessao por arquivo em
`~/.commandcode/projects/<slug>/<id>.jsonl`: um header `{"type":"session", ...}` com
`id`/`cwd` e, depois, entradas `{"type":"message", ...}` com o turno, `usage`
(inputTokens/outputTokens/cacheReadTokens/cacheWriteTokens), `model` e `effort`.

Le APENAS `projects/**/*.jsonl`. Nunca abre `auth.json` (contem a API key). Ver
Decisao 2 do DESIGN_COMMANDCODE_INTEGRATION.

Estados (Decisao 1): os hooks nativos gravam eventos em
`~/.commandcode/monitor-ai-events.json` e o reducer ja existente decide o estado;
a inferencia cobre o que o hook nao cobre:
  ask  = tool_use de `ask_user_question` sem tool_result correspondente;
  perm = tool_use pendente sem PreToolUse/PostToolUse posterior (aguardando
         aprovacao), com teto de PERM_MARKER_MAX_AGE_S.
Sem evento e sem pendencia, o estado vem da recencia (WORK_MAX_AGE_S) — nunca
inventa ask/perm, mesma regra do Codex.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_events import reduce_session_events
from session_hook import load_event_store
from session_state import (PERM_MARKER_MAX_AGE_S, WORK_MAX_AGE_S, parse_ts,
                           session_display_name, strip_accents)
from session_meta import read_git_branch
from usage_model import UsageBreakdown

FULL_NAME_MAX = 38
SOURCE_STALE_AFTER_S = 300.0
SCAN_CANDIDATES = 24
SESSION_MAX_AGE_S = 24 * 3600

# Pergunta do produto: sinal deterministico de `ask` (tools/tools no Command Code).
QUESTION_TOOLS = frozenset({"ask_user_question"})

# Denominador de contexto POR MODELO. O transcript NAO traz a janela (diferente do
# Codex), entao o valor vem do catalogo publico do produto (reference/models.md,
# consultado em 2026-09-19): praticamente todo modelo listado tem 1M. Override por
# usage.commandcode_context_window no monitor.toml. Sem match -> 0 (desconhecido).
DEFAULT_CONTEXT_WINDOW = 0
MODEL_CONTEXT_WINDOWS = (("deepseek", 1000000), ("glm", 1000000), ("z-ai", 1000000),
                         ("qwen", 1000000), ("gemini", 1000000), ("moonshot", 1000000),
                         ("claude", 1000000), ("minimax", 1000000))

# prefixo do modelo -> provedor do icone no firmware (src/assets/*_icon.png).
PROVIDERS_BY_MODEL = (("deepseek", "deepseek"), ("glm", "zai"))


def projects_dir() -> Path:
    override = os.environ.get("MONITOR_COMMANDCODE_DIR", "").strip()
    return Path(override) if override else Path.home() / ".commandcode" / "projects"


def event_store_path() -> Path:
    return Path.home() / ".commandcode" / "monitor-ai-events.json"


def context_window_for(model_id: str, configured: int) -> int:
    """Janela de contexto: config explicita > tabela por modelo > 0 (desconhecida)."""
    if configured > 0:
        return configured
    model = (model_id or "").lower()
    for needle, window in MODEL_CONTEXT_WINDOWS:
        if needle in model:
            return window
    return DEFAULT_CONTEXT_WINDOW


def provider_of(model_id: str) -> str:
    """'deepseek/deepseek-v4.1-flash' -> 'deepseek'; '' = icone padrao."""
    model = (model_id or "").lower()
    for needle, provider in PROVIDERS_BY_MODEL:
        if needle in model:
            return provider
    return ""


def short_model(model_id: str) -> str:
    """Corta o prefixo do provedor e a data de release longa (mesma regra dos outros)."""
    m = strip_accents(model_id or "")
    if "/" in m:
        m = m.split("/", 1)[1]
    parts = m.split("-")
    while parts and parts[-1].isdigit() and len(parts[-1]) >= 6:
        parts.pop()
    return "-".join(parts)[:14]


def _read_objects(path: Path) -> list:
    """Todas as entradas validas do arquivo, tolerando linha ruim."""
    out = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        return []
    return out


def _messages(objs: list) -> list:
    return [o for o in objs if o.get("type") == "message"]


def _content_blocks(obj: dict) -> list:
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content")
    return content if isinstance(content, list) else []


def _pending_tool_use(messages: list):
    """(nome, timestamp) do ultimo tool_use do assistente sem tool_result.

    Um tool_use pendente e o sinal de que a chamada ainda nao concluiu: se for
    `ask_user_question` e uma pergunta (`ask`); se nenhum hook registrou a chamada,
    esta aguardando aprovacao (`perm`). None quando nao ha pendencia.
    """
    last_assistant = next(
        (o for o in reversed(messages) if (o.get("message") or {}).get("role") == "assistant"),
        None)
    if last_assistant is None:
        return None, None
    pending = [block for block in _content_blocks(last_assistant)
               if isinstance(block, dict) and block.get("type") == "tool_use"]
    if not pending:
        return None, None
    resolved = {
        str(block.get("tool_use_id") or "")
        for o in messages if (o.get("message") or {}).get("role") == "user"
        for block in _content_blocks(o)
        if isinstance(block, dict) and block.get("type") == "tool_result"
    }
    for block in reversed(pending):
        if str(block.get("id") or "") not in resolved:
            return block.get("name"), parse_ts(last_assistant.get("timestamp"))
    return None, None


def _usage_events(messages: list) -> list:
    """Uma entrada por mensagem do assistente com usage, dedup por messageId.

    Semantica de consumo NAO obvia neste produto: o `inputTokens` do Command Code e o
    **prompt inteiro** (ja inclui o cache lido), e `cacheReadTokens` e o subconjunto
    cacheado — medido numa sessao real: input=394965 com cacheRead=393984. Somar
    `input` a cada turno reconta o contexto inteiro e infla o numero em ordens de
    grandeza (medido: 26M numa sessao de 15 min). O que o turno efetivamente queima
    de novo e `input - cacheRead + output`; `cacheWriteTokens` fica dentro do `input`
    (nao somado). O contexto da janela e o prompt inteiro = `inputTokens`.
    """
    seen: set = set()
    out: list = []
    for obj in messages:
        message = obj.get("message") or {}
        if message.get("role") != "assistant":
            continue
        usage = obj.get("usage")
        if not isinstance(usage, dict):
            continue
        key = str((message.get("meta") or {}).get("messageId") or obj.get("id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        stamp = parse_ts(obj.get("timestamp"))
        if stamp is None:
            continue
        prompt = int(usage.get("inputTokens") or 0)
        cached = int(usage.get("cacheReadTokens") or 0)
        tokens = max(0, prompt - cached) + int(usage.get("outputTokens") or 0)
        out.append({"id": key, "at": stamp, "tokens": tokens, "context": prompt,
                    "message": message, "usage": usage, "model": obj.get("model")})
    return out


def _age_s(value: datetime | None, now: datetime) -> float:
    if value is None:
        return float("inf")
    return max((now - value).total_seconds(), 0.0)


def _derive_state(messages: list, snapshot, path: Path, now: datetime) -> tuple:
    """(state, age_s). O hook manda; o transcript desempata. Nunca inventa ask/perm."""
    name, pending_at = _pending_tool_use(messages)
    if name in QUESTION_TOOLS and pending_at is not None:
        return "ask", _age_s(pending_at, now)
    recent_hook = (snapshot.last_event_at is not None and pending_at is not None
                   and snapshot.last_event_at >= pending_at)
    if name is not None and pending_at is not None and not recent_hook:
        # Aguardando aprovacao. Evidencia velha deixa de afirmar (Decisao 1).
        age = _age_s(pending_at, now)
        return ("perm", age) if age <= PERM_MARKER_MAX_AGE_S else ("free", age)
    if snapshot.last_event_at is not None:
        return snapshot.state, float(snapshot.age_s or 0)
    # Sem hook: recencia. Nunca inventa ask/perm (mesma regra do Codex).
    try:
        age = max((now.timestamp() - path.stat().st_mtime), 0.0)
    except OSError:
        age = float("inf")
    return ("work" if age <= WORK_MAX_AGE_S else "free"), age


def scan_commandcode_sessions(now: datetime, token_since: datetime | None = None, *,
                              directory: Path | None = None,
                              ctx_window: int = 0,
                              event_path: Path | None = None) -> list:
    """Mesma forma de scan_claude_sessions/scan_codex_sessions: um dict por sessao.

    `directory=None` usa projects_dir(); path ausente devolve [] (nunca levanta)."""
    root = Path(directory) if directory is not None else projects_dir()
    try:
        candidates = sorted(root.glob("*/*.jsonl"),
                            key=lambda p: p.stat().st_mtime, reverse=True)[:SCAN_CANDIDATES]
    except OSError:
        return []
    store = load_event_store(event_path or event_store_path())
    since_epoch = token_since.timestamp() if token_since else None
    out = []
    for path in candidates:
        objs = _read_objects(path)
        if not objs:
            continue
        messages = _messages(objs)
        if not messages:
            continue
        header = next((o for o in objs if o.get("type") == "session"), {})
        session_id = str(header.get("id") or path.stem)
        cwd = str(header.get("cwd") or "")
        last_ts = max((parse_ts(o.get("timestamp")) for o in messages
                       if parse_ts(o.get("timestamp")) is not None), default=None)
        age = _age_s(last_ts, now)
        if age > SESSION_MAX_AGE_S:
            continue

        snapshot = reduce_session_events(
            session_id, [store[session_id]] if session_id in store else [],
            now, SOURCE_STALE_AFTER_S)
        if snapshot.ended:
            continue
        state, state_age = _derive_state(messages, snapshot, path, now)

        events = _usage_events(messages)
        tokens_win = sum(e["tokens"] for e in events
                         if since_epoch is None or e["at"].timestamp() >= since_epoch)
        context_tokens = events[-1]["context"] if events else 0
        model_id = next((str(o.get("model") or "") for o in reversed(messages)
                         if o.get("model")), "")
        effort = next((str(o.get("effort") or "") for o in reversed(messages)
                       if o.get("effort")), "")
        window = context_window_for(model_id, ctx_window)
        if ctx_window > 0:
            quality = "measured"
        elif window > 0:
            quality = "estimated"
        else:
            quality = "unknown"
        has_ctx = window > 0 and context_tokens > 0
        ctx_pct = min(100, round(context_tokens * 100 / window)) if has_ctx else 0

        branch = strip_accents(read_git_branch(cwd))[:20]
        project = Path(cwd.replace("\\", "/")).name if cwd else path.parent.name
        project_raw = strip_accents(project)[:FULL_NAME_MAX]
        full = session_display_name(project_raw, branch)
        out.append({
            "id": session_id,
            "project": full,
            "full": full,
            "_project_raw": project_raw,
            "branch": branch,
            "model": short_model(model_id),
            "provider": provider_of(model_id),
            "effort": strip_accents(effort)[:8],
            "tokensWin": tokens_win,
            "ctxPct": ctx_pct,
            "context": {"value": ctx_pct if has_ctx else None,
                        "quality": quality if context_tokens > 0 else "unknown",
                        "unit": "percent"},
            "context_tokens": context_tokens,
            "tool": "commandcode",
            "state": state,
            "elapsed": int(state_age) if state_age != float("inf") else 0,
            "source_stale": state_age == float("inf") or state_age > SOURCE_STALE_AFTER_S,
            "source_age_s": None if state_age == float("inf") else int(state_age),
            "diagnostic": "" if ctx_window > 0 else "context_estimated",
            "_age": age,
            "_structured": snapshot.last_event_at is not None,
            "_perm_marker_age_s": None,
        })
    return out


def window_tokens(directory: Path | None, since_epoch: float | None = None) -> int:
    """Consumo (input+output+cacheWrite) desde `since_epoch`; alimenta a cota 5h."""
    root = Path(directory) if directory is not None else projects_dir()
    try:
        candidates = sorted(root.glob("*/*.jsonl"),
                            key=lambda p: p.stat().st_mtime, reverse=True)[:SCAN_CANDIDATES]
    except OSError:
        return 0
    total = 0
    for path in candidates:
        for event in _usage_events(_messages(_read_objects(path))):
            if since_epoch is None or event["at"].timestamp() >= since_epoch:
                total += event["tokens"]
    return total


def turn_token_events(directory: Path | None, since: datetime | None = None):
    """Pares (datetime_utc, tokens) por turno, mais antigo primeiro (backfill diario)."""
    for event in turn_usage_events(directory, since):
        yield event.at, event.consumed_tokens


def turn_usage_events(directory: Path | None, since: datetime | None = None):
    """Eventos detalhados por mensagem; preserva dedup e semântica de consumo."""
    root = Path(directory) if directory is not None else projects_dir()
    try:
        candidates = sorted(root.glob("*/*.jsonl"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    start_ts = since.timestamp() if since else None
    for path in candidates:
        for event in _usage_events(_messages(_read_objects(path))):
            if event["tokens"] <= 0:
                continue
            if start_ts is not None and event["at"].timestamp() < start_ts:
                continue
            message = event.get("message") or {}
            usage = event.get("usage") or {}
            prompt = max(int(usage.get("inputTokens") or 0), 0)
            cached = max(int(usage.get("cacheReadTokens") or 0), 0)
            cache_write = (max(int(usage.get("cacheWriteTokens") or 0), 0)
                           if "cacheWriteTokens" in usage else None)
            input_tokens = max(prompt - cached - (cache_write or 0), 0)
            output_tokens = max(int(usage.get("outputTokens") or 0), 0)
            reasoning = (max(int(usage.get("reasoningTokens") or 0), 0)
                         if "reasoningTokens" in usage else None)
            yield UsageBreakdown(
                at=event["at"], provider="commandcode",
                model=str(event.get("model") or message.get("model") or "unknown"),
                input_tokens=input_tokens, output_tokens=output_tokens,
                reasoning_tokens=reasoning, cache_write_tokens=cache_write,
                consumed_tokens=event["tokens"])


def count_active_12h(directory: Path | None, now: datetime, window_s: float) -> int:
    """Sessoes com mensagem na janela; espelha count_active_12h dos outros."""
    root = Path(directory) if directory is not None else projects_dir()
    cutoff = (now - timedelta(seconds=window_s)).timestamp()
    count = 0
    try:
        candidates = list(root.glob("*/*.jsonl"))
    except OSError:
        return 0
    for path in candidates:
        messages = _messages(_read_objects(path))
        stamps = [parse_ts(o.get("timestamp")) for o in messages]
        stamps = [s for s in stamps if s is not None]
        if stamps and max(stamps).timestamp() >= cutoff:
            count += 1
    return count
