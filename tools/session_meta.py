#!/usr/bin/env python3
"""
Metadados extras exibidos na tela de detalhe do Monitor.AI: modelo e branch.

Por que existe um modulo so para isso:

* **Branch** — o transcript do Claude Code traz um campo `gitBranch`, mas ele vale
  "HEAD" quando o diretorio nao e um repositorio git, o que aparecia na tela como se
  fosse o nome de uma branch. Ler `<cwd>/.git/HEAD` direto do disco resolve os dois
  problemas de uma vez: diz a branch ATUAL (nao um retrato de quando o turno rodou) e
  distingue "sem git" de "detached HEAD".

* **Codex** — o `session_index.jsonl` so tem id/thread_name/updated_at, entao modelo e
  branch vinham vazios. Os arquivos `~/.codex/sessions/AAAA/MM/DD/rollout-*.jsonl`
  carregam `payload.model` e `payload.cwd`, e o UUID no nome do arquivo e o mesmo id do
  indice — o que permite casar um com o outro sem abrir todos os arquivos.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from session_state import parse_ts
from usage_model import context_measurement

CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
ROLLOUT_HEAD_BYTES = 96 * 1024   # model/cwd ficam no comeco do arquivo

# Intervalo minimo entre duas varreduras do diretorio de rollouts.
#
# Sem isso, CADA id sem rollout refazia o rglob inteiro. Medido em 27/08/2026: o
# session_index tem 53 ids e existem 37 rollouts, mas so 5 se cruzam — os outros 48
# eram 48 varreduras completas por ciclo, 0,83s de um ciclo de 1,27s. O id ausente e o
# caso NORMAL (thread antiga cujo rollout nao existe mais), nao a excecao, entao o
# preco tem que ser pago uma vez por janela e nao uma vez por id.
#
# 10s e o teto de atraso para uma sessao nova aparecer com modelo/effort na tela — bem
# abaixo dos 90s de SOURCE_STALE_AFTER_S, entao nunca e ela que decide o estado.
REINDEX_MIN_INTERVAL_S = 10.0


def read_git_branch(cwd: str | None) -> str:
    """Branch atual lida de <cwd>/.git/HEAD.

    "" = nao e repositorio git. "detached" = HEAD solto (sem branch nomeada).
    """
    if not cwd:
        return ""                      # nem sabemos o diretorio
    base = Path(cwd)
    head = base / ".git" / "HEAD"
    try:
        raw = head.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        # Distingue "o projeto nao usa git" de "nao sabemos": mostrar campo vazio nos
        # dois casos esconde a diferenca, e "HEAD" (o que o transcript devolvia) parecia
        # nome de branch.
        return "sem git" if base.is_dir() else ""
    if raw.startswith("ref:"):
        return raw.split("/")[-1]
    return "detached" if raw else ""


def _rollout_index() -> dict:
    """{session_id: caminho do rollout}. So lista nomes de arquivo, nao abre nenhum."""
    out = {}
    if not CODEX_SESSIONS.is_dir():
        return out
    try:
        for p in CODEX_SESSIONS.rglob("rollout-*.jsonl"):
            # rollout-<timestamp>-<uuid>.jsonl
            stem = p.stem
            uuid = stem.split("-", 2)[-1] if stem.count("-") >= 2 else ""
            # o uuid tem hifens; pega o sufixo apos o timestamp
            parts = stem.split("-")
            if len(parts) >= 6:
                uuid = "-".join(parts[-5:])
            if uuid:
                prev = out.get(uuid)
                if prev is None or p.stat().st_mtime > prev.stat().st_mtime:
                    out[uuid] = p
    except OSError:
        pass
    return out


_cache: dict = {}
_cache_at: float = 0.0     # time.monotonic() da ultima varredura; 0 = nunca
_meta_cache: dict = {}


def _rollout_for(session_id: str) -> Path | None:
    """Caminho do rollout do id, revarrendo o disco no maximo a cada janela.

    Antes, um id sem rollout disparava uma varredura por chamada. Aqui a varredura e
    do INDICE, nao do id: se ela acabou de rodar, o id continua ausente e nao ha o que
    reprocurar. Ver REINDEX_MIN_INTERVAL_S.
    """
    global _cache, _cache_at
    agora = time.monotonic()
    if not _cache and not _cache_at:
        _cache, _cache_at = _rollout_index(), agora
    path = _cache.get(session_id)
    if path is None and (agora - _cache_at) >= REINDEX_MIN_INTERVAL_S:
        _cache, _cache_at = _rollout_index(), agora
        path = _cache.get(session_id)
    return path


def _codex_vazio() -> dict:
    context = context_measurement(0)
    return {"model": "", "cwd": "", "effort": "", "tokens": 0,
            "ctx_pct": context["pct"], "context": context}


def codex_meta(session_id: str, since=None) -> dict:
    """Metadados de uma sessao do Codex a partir do seu rollout.

    Devolve {model, cwd, effort, tokens, ctx_pct}. Tudo isso existe no rollout — o que faltava
    antes era procurar: `turn_context.model`, `turn_context.effort` e o acumulado em
    `event_msg.info.total_token_usage.total_tokens`.

    `tokens` respeita a janela `since`: como o total e ACUMULATIVO, os tokens da janela
    sao (ultimo total) - (ultimo total anterior a `since`). Isso evita somar turno a
    turno e, de quebra, nao conta duas vezes se um evento se repetir.

    `ctx_pct` e mais simples aqui do que no Claude: o Codex publica a janela do modelo
    em `model_context_window` (258.400 medido) e o tamanho do prompt de cada turno em
    `last_token_usage.input_tokens`. Nao precisa inferir nada — e o unico dos dois
    agentes que entrega os dois numeros de forma explicita.
    """
    path = _rollout_for(session_id)
    if path is None:
        return _codex_vazio()

    try:
        st = path.stat()
    except OSError:
        return _codex_vazio()

    # Rollouts chegam a 2MB; reparsear a cada ciclo de 5s seria desperdicio. Se o
    # arquivo nao mudou de tamanho, o resultado tambem nao mudou.
    key = (str(path), st.st_size, since.isoformat() if since else "")
    hit = _meta_cache.get(key)
    if hit is not None:
        return hit

    model = cwd = effort = ""
    total_now = 0
    total_window = 0
    previous_total = None
    ctx_now = 0
    ctx_window = 0

    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = obj.get("payload")
                if not isinstance(payload, dict):
                    continue

                # turn_context traz o modelo e o effort do turno; o ultimo vale.
                if payload.get("model"):
                    model = str(payload["model"])
                if payload.get("effort"):
                    effort = str(payload["effort"])
                if payload.get("cwd"):
                    cwd = str(payload["cwd"])

                # A janela aparece em dois lugares: solta no `task_started` e dentro
                # do `info` do `token_count`. Aceita as duas para nao depender da ordem.
                if payload.get("model_context_window"):
                    ctx_window = int(payload["model_context_window"])

                info = payload.get("info")
                if isinstance(info, dict):
                    tu = info.get("total_token_usage")
                    if isinstance(tu, dict) and tu.get("total_tokens") is not None:
                        total_now = int(tu["total_tokens"])
                        ts = parse_ts(obj.get("timestamp"))
                        if since and ts:
                            if ts < since:
                                previous_total = total_now
                            else:
                                delta = (total_now if previous_total is None
                                         or total_now < previous_total
                                         else total_now - previous_total)
                                total_window += max(delta, 0)
                                previous_total = total_now
                    if info.get("model_context_window"):
                        ctx_window = int(info["model_context_window"])
                    # input_tokens do ULTIMO turno = tamanho do prompt = contexto vigente.
                    # Nao e o acumulado: cresce com a conversa e cai quando o Codex poda.
                    lt = info.get("last_token_usage")
                    if isinstance(lt, dict) and lt.get("input_tokens") is not None:
                        ctx_now = int(lt["input_tokens"])
    except OSError:
        return _codex_vazio()

    tokens = total_window if since else total_now
    context = context_measurement(ctx_now, measured_limit=ctx_window)

    out = {"model": model, "cwd": cwd, "effort": effort,
           "tokens": max(tokens, 0), "ctx_pct": context["pct"], "context": context}
    if len(_meta_cache) > 64:
        _meta_cache.clear()
    _meta_cache[key] = out
    return out


# ---------------------------------------------------------------------------
# Ocupacao da janela de contexto
# ---------------------------------------------------------------------------
# O tamanho da janela NAO vem no transcript: o campo `model` traz "claude-opus-5",
# sem o sufixo que distingue a janela de 1M da de 200k. Medido neste ambiente:
# sessoes chegaram a 998.258 e 999.631 tokens, o que ja descarta 200k. Inferir pelo
# nome do modelo produziria alarme falso em praticamente toda sessao.
#
# A fonte confiavel e o proprio historico. Quando o Claude Code compacta sozinho ele
# grava `compactMetadata` com {"trigger":"auto","preTokens":N} — N e o teto real
# daquela sessao. Gatilhos medidos aqui: 1.003.479, 1.002.810, 647.702 e 301.596;
# como variam, o valor e aprendido POR SESSAO em vez de assumido global.


def _ctx_of(obj: dict) -> int:
    """Tokens de contexto de uma resposta = tudo que entrou no prompt dela."""
    u = (obj.get("message") or {}).get("usage")
    if not isinstance(u, dict):
        return 0
    return (int(u.get("input_tokens") or 0)
            + int(u.get("cache_read_input_tokens") or 0)
            + int(u.get("cache_creation_input_tokens") or 0))


def _configured_context_window() -> int:
    """Limite Claude declarado pelo operador, sem aceitar valores inválidos."""
    try:
        return max(int(os.environ.get("MONITOR_CLAUDE_CONTEXT_WINDOW", "") or 0), 0)
    except ValueError:
        return 0


def context_usage(objs: list) -> dict:
    """Contexto Claude com tokens brutos e qualidade explícita do denominador."""
    atual = 0
    pico = 0
    teto_medido = 0
    for o in objs:
        c = _ctx_of(o)
        if c > 0:
            atual = c          # a ULTIMA resposta e o contexto vigente
            pico = max(pico, c)
        cm = o.get("compactMetadata")
        if isinstance(cm, dict) and cm.get("trigger") == "auto":
            pre = int(cm.get("preTokens") or 0)
            if pre > 0:
                teto_medido = max(teto_medido, pre)

    # Um limite de compactação contraditório é histórico, não uma medida da janela
    # atual; nesse caso só uma configuração explícita pode produzir uma porcentagem.
    medido = teto_medido if teto_medido >= pico else 0
    return context_measurement(atual, measured_limit=medido,
                               configured_limit=_configured_context_window())
