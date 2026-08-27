#!/usr/bin/env python3
"""
Deteccao de estado das sessoes — nucleo do Monitor.AI.

Vocabulario fechado (definido com o usuario):
  work : modelo pensando/executando algo
  ask  : modelo fez uma pergunta (AskUserQuestion) e aguarda resposta
  perm : modelo aguarda autorizacao para rodar uma tool (ex: "allow git ...")
  free : sessao existe e o modelo esta livre

Por que este modulo existe (ver docs/SPEC.md 5.1): a versao anterior decidia o
estado olhando a ULTIMA LINHA BRUTA do transcript e a mtime do arquivo. Na pratica
nenhum transcript termina em linha de conversa — todos terminam em bookkeeping
(last-prompt, mode, attachment, atis-latch, system) — entao os ramos user/assistant
eram codigo morto e tudo caia num fallback por idade. Resultado: "ask" significava
apenas "arquivo tocado entre 15s e 90s atras", e "perm" era inalcancavel.

Aqui a decisao e feita sobre EVENTOS DE CONVERSA reais, usando o timestamp do
proprio evento (nao a mtime, que qualquer escrita de bookkeeping bumpa).
"""
from __future__ import annotations

import json
import unicodedata
from datetime import datetime, timezone

from agent_events import MAX_FUTURE_SKEW_S, parse_aware_timestamp

# Tipos de linha que representam conversa de verdade. Todo o resto e bookkeeping.
CONVERSATIONAL = ("user", "assistant")

# Nome da tool que caracteriza "modelo perguntou algo e espera resposta".
ASK_TOOL = "AskUserQuestion"

# NAO EXISTE heuristica de tempo para 'perm'.
#
# Ja existiu: "tool_use sem tool_result ha mais de 8s => provavelmente travada num
# prompt de permissao". Estava errada por construcao. No transcript, uma ferramenta
# EXECUTANDO e uma ferramenta BLOQUEADA em pedido de autorizacao sao literalmente o
# mesmo registro: um tool_use sem tool_result. Qualquer comando que passe do limiar
# (um build, um `timeout 40 python3 ...`, uma captura de serial) era classificado como
# `perm` enquanto na verdade estava trabalhando.
#
# O unico sinal que distingue os dois casos vem de FORA do transcript: o hook
# PermissionRequest do proprio Claude Code (tools/session_hook.py), que so dispara quando
# o harness realmente abre o dialogo de autorizacao e bloqueia a execucao.
# Sem hook ativo, `perm` simplesmente nao acontece — o que e correto: e melhor nao
# afirmar do que afirmar errado.

# Um tool_use sem resposta por mais que isso e sessao abandonada, nao trabalho em curso.
# Generoso de proposito: builds e testes longos precisam continuar contando como `work`.
WORK_MAX_AGE_S = 1800.0

# Idade maxima da marca deixada pelo hook. Protege o caso do Claude Code morrer com um
# dialogo de permissao aberto: a marca ficaria no arquivo sem ninguem para limpa-la.
PERM_MARKER_MAX_AGE_S = 600.0


def parse_ts(value) -> datetime | None:
    """ISO8601 do transcript -> datetime aware. None se ausente/invalido."""
    return parse_aware_timestamp(value)


def strip_accents(text: str) -> str:
    """Remove acentos: a fonte compilada no firmware so tem ASCII, entao 'migração'
    viraria 'migra??o' na tela. Ver docs/SPEC.md 8."""
    norm = unicodedata.normalize("NFKD", text)
    return "".join(c for c in norm if not unicodedata.combining(c) and ord(c) < 128)


def _content_blocks(obj: dict) -> list:
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content")
    return content if isinstance(content, list) else []


def _tool_uses(obj: dict) -> list:
    return [c for c in _content_blocks(obj)
            if isinstance(c, dict) and c.get("type") == "tool_use"]


def _tool_result_ids(obj: dict) -> set:
    return {c.get("tool_use_id") for c in _content_blocks(obj)
            if isinstance(c, dict) and c.get("type") == "tool_result"}


def conversational_events(objs: list) -> list:
    """So eventos de conversa da sessao principal.

    isSidechain=True e turno de subagente — sem isso um subagente rodando faria a
    sessao principal parecer 'work' (ou vice-versa)."""
    return [o for o in objs
            if o.get("type") in CONVERSATIONAL and not o.get("isSidechain")]


def _has_pending_ask(objs: list) -> bool:
    """True se o ultimo evento do assistant tem um AskUserQuestion sem resposta."""
    convs = conversational_events(objs)
    if not convs:
        return False
    last = convs[-1]
    if last.get("type") != "assistant":
        return False
    tools = _tool_uses(last)
    if not any(t.get("name") == ASK_TOOL for t in tools):
        return False
    pending = {t.get("id") for t in tools}
    idx = objs.index(last) if last in objs else -1
    for later in objs[idx + 1:]:
        pending -= _tool_result_ids(later)
    return bool(pending)


def infer_state(objs: list, now: datetime | None = None,
                perm_pending: bool = False) -> tuple[str, float]:
    """Devolve (estado, segundos_no_estado).

    `perm_pending` vem do hook PermissionRequest e tem prioridade sobre a heuristica.
    """
    now = now or datetime.now(timezone.utc)
    convs = conversational_events(objs)
    if not convs:
        return "free", 0.0

    last = convs[-1]
    ts = parse_ts(last.get("timestamp"))
    # Timestamp ruim nunca vira idade zero/trabalho atual. O chamador pode registrar
    # o diagnostico; aqui a sessao degrada isoladamente para free.
    if ts is None:
        return "free", float("inf")
    if (ts - now).total_seconds() > MAX_FUTURE_SKEW_S:
        return "free", float("inf")
    age = max((now - ts).total_seconds(), 0.0)

    # ATENCAO A ORDEM: a checagem do hook NAO pode vir antes da de pergunta.
    #
    # O Claude Code dispara PermissionRequest tambem quando abre um AskUserQuestion, e
    # como a marca do hook tinha prioridade absoluta, uma pergunta com alternativas
    # aparecia como `perm`. O sinal mais ESPECIFICO deve vencer: se o modelo fez uma
    # pergunta e ela nao foi respondida, o estado e `ask`, venha o hook de onde vier.
    # O filtro em session_hook.py ja evita a marca na origem; isto aqui e a segunda linha
    # de defesa, que funciona mesmo se o payload do hook nao trouxer o nome da tool.
    if perm_pending and not _has_pending_ask(objs):
        return "perm", age

    if last.get("type") == "user":
        # Mensagem sua (ou um tool_result voltando): o modelo esta processando.
        return ("work", age) if age <= WORK_MAX_AGE_S else ("free", age)

    # last e do assistant.
    tools = _tool_uses(last)
    if not tools:
        # Turno concluido sem pedir nada -> modelo livre (NAO e 'ask'; 'ask' e
        # exclusivo de AskUserQuestion, conforme definido com o usuario).
        return "free", age

    pending = {t.get("id") for t in tools}
    idx = objs.index(last) if last in objs else -1
    for later in objs[idx + 1:]:
        pending -= _tool_result_ids(later)
    answered = not pending

    if answered:
        return ("work", age) if age <= WORK_MAX_AGE_S else ("free", age)

    # Ha tool_use sem resposta.
    if any(t.get("name") == ASK_TOOL for t in tools):
        return "ask", age          # modelo perguntou e espera voce (sinal exato)
    # Ferramenta emitida e ainda sem retorno = ferramenta EXECUTANDO. Nao ha como o
    # transcript dizer se ela esta bloqueada por permissao; quem diz isso e o hook,
    # tratado la em cima. Entao aqui e trabalho.
    return ("work", age) if age <= WORK_MAX_AGE_S else ("free", age)
