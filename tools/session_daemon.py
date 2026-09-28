#!/usr/bin/env python3
"""
Monitor.AI — daemon local.

Le as sessoes do Claude Code e do Codex CLI nesta maquina e empurra o resumo para o
ESP32 via HTTP (POST /sessions). Ver docs/SPEC.md secao 5.

Uso:
    python tools/session_daemon.py --host 192.168.0.50
    python tools/session_daemon.py --interval 3
    python tools/session_daemon.py --once            # um ciclo, para debug

Depende apenas da biblioteca padrao do Python.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from session_state import (PERM_MARKER_MAX_AGE_S, WORK_MAX_AGE_S,
                           conversational_events, infer_state,
                           parse_ts, session_display_name, strip_accents)
from agent_events import MAX_FUTURE_SKEW_S, reduce_session_events
from codex_paths import CODEX_EVENT_FILE, CODEX_HOME, CODEX_SESSION_INDEX
from session_hook import hook_health, load_event_store
from session_meta import (CODEX_SESSIONS, CODEX_STATE_DB, codex_meta,
                          codex_threads, read_git_branch, context_usage,
                          recent_rollouts)
from usage_tracker import collect as collect_usage, collect_series, session_tokens
from quota import collect as collect_quota
from opencode_sessions import (LOG_PATH as OPENCODE_LOG_PATH,
                               count_active_12h as count_opencode_12h,
                               db_path as opencode_default_db,
                               scan_opencode_sessions, window_tokens)
from commandcode_sessions import (count_active_12h as count_commandcode_12h,
                                  projects_dir as commandcode_default_dir,
                                  scan_commandcode_sessions,
                                  window_tokens as commandcode_window_tokens)
import usage_history
import usage_top
from alert_severity import (Thresholds, severity_for, thresholds_from,
                            worst_severity)
from notify import notify
from protocol_v2 import build_snapshot_v2
from monitor_config import MonitorConfig

MAX_SESSIONS = 6

# Ordem de urgencia: o que precisa de voce sobe. Empate resolve por recencia.
STATE_PRIORITY = {"perm": 0, "ask": 1, "work": 2, "free": 3}

# Ferramentas que TODO firmware conhece. Um POST 422 com um tool fora daqui e sinal de
# firmware antigo: o daemon reenvia so com a base. Antes o gatilho era "opencode" fixo,
# o que repetia o problema a cada provedor novo. Ver Decisao 7 do DESIGN.
BASELINE_TOOLS = frozenset({"claude", "codex"})

# Espelham os defaults de AlertSettings (monitor_config.py). Existem para os
# testes hermeticos e para build_payload rodar sem um objeto de config em maos;
# em producao quem manda e sempre o monitor.toml.
DEFAULT_WARNING_AFTER_S = 90
DEFAULT_CRITICAL_AFTER_S = 300
DEFAULT_SNOOZE_MINUTES = 15

DISMISS_FILE = Path(__file__).parent / ".dismissed.json"
PERM_FILE = Path.home() / ".claude" / "monitor-ai-perm.json"
CLAUDE_EVENT_FILE = Path.home() / ".claude" / "monitor-ai-events.json"
SOURCE_STALE_AFTER_S = 90.0
HOURLY_REFRESH_INTERVAL_S = 60.0
_hourly_history_refresh: dict[Path, datetime] = {}

# Quantos transcripts (mais recentes) inspecionar por ciclo. Ha ~65 sessoes; ler o
# tail de todas a cada 5s seria desperdicio, e as antigas nunca ganhariam um card.
SCAN_CANDIDATES = 24

# Janela dos tokens exibidos na tela de detalhe de cada sessao. O numero de horas vai
# no payload junto com o valor: assim o rotulo da tela e montado a partir da MESMA
# constante que gerou o dado, e nao ha como ficar escrito "24h" mostrando 12h.
SESSION_TOKEN_WINDOW_H = 12
SESSION_TOKEN_WINDOW_S = SESSION_TOKEN_WINDOW_H * 3600
TAIL_BYTES = 32 * 1024

# Codex: o indice fornece identidade/recencia; estado vem exclusivamente dos hooks.
# Sem evento estruturado, degrada para `free` stale e nunca inventa `ask`/`perm`.
# O limite de 10 caracteres pertence somente a renderizacao no firmware. O payload
# preserva o nome para identidade, detalhes e diagnosticos.
NAME_MAX = 10


def load_monitor_api_token() -> str:
    """Token local sem log: ambiente vence o secrets.h ignorado pelo Git."""
    from_env = os.environ.get("MONITOR_API_TOKEN", "").strip()
    if from_env:
        return from_env
    secrets_path = Path(__file__).resolve().parents[1] / "include" / "secrets.h"
    try:
        text = secrets_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'^\s*#define\s+MONITOR_API_TOKEN\s+"([^"]+)"',
                      text, re.MULTILINE)
    return match.group(1) if match else ""


MONITOR_API_TOKEN = load_monitor_api_token()


def authenticated_request(url: str, *, data: bytes | None = None,
                          method: str = "GET", headers: dict | None = None,
                          token: str | None = None):
    request_headers = dict(headers or {})
    effective_token = MONITOR_API_TOKEN if token is None else token
    if effective_token:
        request_headers["X-Monitor-Token"] = effective_token
    return urllib.request.Request(url, data=data, method=method, headers=request_headers)


def short_model(model: str) -> str:
    """'claude-haiku-4-5-20251001' -> 'haiku-4-5' | 'gpt-5.6-sol' -> 'gpt-5.6-sol'.
    Corta a data de release, que nao cabe nem informa nada na tela de detalhe."""
    m = strip_accents(model or "").replace("claude-", "")
    parts = m.split("-")
    # descarta sufixo puramente numerico e longo (data de release)
    while parts and parts[-1].isdigit() and len(parts[-1]) >= 6:
        parts.pop()
    return "-".join(parts)[:14]

# Janela da metrica de sessoes ativas exibida no card de tokens.
ACTIVE_WINDOW_S = 12 * 3600

# Janela para APARECER no board. Medido: das 74 sessoes em disco, 72 estavam `free`,
# entao o grid gastava cards mostrando coisa parada ha dias. So entra no board quem teve
# atividade real nas ultimas 4h; havendo mais que MAX_SESSIONS, ficam as mais recentes.
BOARD_WINDOW_S = 4 * 3600

FULL_NAME_MAX = 38   # nome completo para a tela de detalhe (sem truncar em 10)
CATALOG_MAX = 9      # quantas linhas cabem na tela do seletor (ver ui_dashboard)
_previous_board_ids: list[str] = []


def dedupe_display_names(sessions: list) -> None:
    """Quando 2+ sessoes VISIVEIS colidem no mesmo texto de card, troca so essas
    para "projeto/branch" (in-place).

    `session_display_name` mostra so a branch quando ela nao e main/master —
    identifica melhor UMA sessao, mas nao previa DUAS sessoes do MESMO projeto
    na MESMA branch ao mesmo tempo: ambas viram o mesmo texto e ficam
    indistinguiveis entre si. Se a colisao for por projeto (branch main/ausente,
    "_project_raw" ja igual ao texto atual), nao ha o que ganhar combinando."""
    counts: dict[str, int] = {}
    for s in sessions:
        counts[s["full"]] = counts.get(s["full"], 0) + 1
    for s in sessions:
        if counts[s["full"]] < 2:
            continue
        raw = s.get("_project_raw") or s["full"]
        if raw == s["full"]:
            continue
        combined = f"{raw}/{s['full']}"[:FULL_NAME_MAX]
        s["project"] = combined
        s["full"] = combined


def rank_sessions(sessions: list, previous_ids: list[str] | tuple[str, ...]) -> list:
    """Urgencia, recencia e, somente no empate exato, ordem visual anterior."""
    previous = {session_id: index for index, session_id in enumerate(previous_ids)}
    fallback = len(previous)
    return sorted(sessions, key=lambda session: (
        bool(session.get("source_stale", False)),
        STATE_PRIORITY.get(session.get("state"), len(STATE_PRIORITY)),
        session.get("_age", float("inf")),
        previous.get(session.get("id"), fallback),
        str(session.get("id") or ""),
    ))


def _structured_snapshot(session_id: str, store: dict, now: datetime):
    raw = store.get(session_id)
    events = [raw] if isinstance(raw, dict) else []
    return reduce_session_events(session_id, events, now, SOURCE_STALE_AFTER_S)


def _fresh_activity_age(activity_epoch: float | None, now_epoch: float) -> int | None:
    """Idade de atividade local recente, rejeitando timestamps muito futuros."""
    if activity_epoch is None:
        return None
    age = now_epoch - float(activity_epoch)
    if age < -MAX_FUTURE_SKEW_S or age > WORK_MAX_AGE_S:
        return None
    return int(max(age, 0.0))


def read_tail_json_objects(path: Path, initial_bytes: int = TAIL_BYTES,
                           max_bytes: int = 512 * 1024) -> list:
    """Ultimos objetos JSON validos do arquivo, em ordem cronologica.

    Le so o fim (transcripts passam de varios MB) e cresce a janela ate encontrar
    pelo menos um evento de conversa, ja que o fim costuma ser so bookkeeping."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    window = initial_bytes
    best: list = []
    while window <= max_bytes:
        try:
            with path.open("rb") as f:
                f.seek(max(0, size - window))
                chunk = f.read()
        except OSError:
            return best
        objs = []
        for raw in chunk.split(b"\n"):
            if not raw.strip():
                continue
            try:
                objs.append(json.loads(raw))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue   # linha cortada na borda da janela
        if objs:
            best = objs
            if conversational_events(objs) or window >= size:
                return best
        if window >= size:
            break
        window *= 4
    return best


def load_json_map(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def load_dismissed() -> set:
    try:
        data = json.loads(DISMISS_FILE.read_text(encoding="utf-8"))
        return {str(n) for n in data}
    except (OSError, json.JSONDecodeError, ValueError):
        return set()


def filter_dismissed(sessions: list, dismissed_ids: set) -> list:
    return [session for session in sessions if session.get("id") not in dismissed_ids]


def meta_of(objs: list) -> tuple:
    """(branch, modelo, effort) para a tela de detalhe.

    A branch vem de <cwd>/.git/HEAD, nao do campo `gitBranch` do transcript: aquele
    campo vale "HEAD" quando o diretorio nem e repositorio git, e isso aparecia na tela
    como se fosse o nome de uma branch. Ler do disco tambem da a branch ATUAL, e nao um
    retrato de quando o turno rodou.
    """
    cwd = next((o["cwd"] for o in reversed(objs) if o.get("cwd")), None)
    branch = read_git_branch(cwd)
    model = ""
    effort = next((o["effort"] for o in reversed(objs)
                   if o.get("type") == "assistant" and o.get("effort")), "")
    for o in reversed(objs):
        if o.get("type") == "assistant":
            m = o.get("message")
            if isinstance(m, dict) and m.get("model"):
                if "synthetic" in str(m["model"]).lower():
                    continue   # mensagem sintetica (erro/interrupcao), nao e o modelo
                model = m["model"]
                break
    return strip_accents(branch)[:20], short_model(model), strip_accents(effort)[:8]


def project_name_of(objs: list, fallback: str, limit: int = NAME_MAX) -> str:
    """Nome legivel: vem do cwd dos eventos, nao do nome sanitizado da pasta,
    que fica ilegivel."""
    cwd = next((o["cwd"] for o in reversed(objs) if o.get("cwd")), None)
    name = Path(cwd.replace("\\", "/")).name if cwd else fallback
    return strip_accents(name)[:limit]


def scan_claude_sessions(projects_dir: Path, now: datetime,
                         event_path: Path | None = None,
                         legacy_perm_path: Path | None = None) -> list:
    """Uma entrada por SESSAO (arquivo .jsonl), nao por projeto — o mesmo projeto
    pode aparecer em mais de um card se tiver varias sessoes abertas."""
    if not projects_dir.is_dir():
        return []

    candidates = []
    for project in projects_dir.iterdir():
        if not project.is_dir():
            continue
        for path in project.glob("*.jsonl"):
            try:
                candidates.append((path.stat().st_mtime, path, project.name))
            except OSError:
                continue
    candidates.sort(reverse=True)

    # Marcas do hook PermissionRequest. Sao descartadas se velhas: se o Claude Code
    # morrer com um dialogo de permissao aberto, ninguem chama o hook de limpeza e a
    # marca ficaria presa no arquivo, deixando a sessao eternamente em `perm`.
    perm_raw = load_json_map(legacy_perm_path or PERM_FILE)
    now_epoch = now.timestamp()
    perm_pending = {
        sid for sid, ts in perm_raw.items()
        if isinstance(ts, (int, float)) and (now_epoch - ts) <= PERM_MARKER_MAX_AGE_S
    }
    event_store = load_event_store(event_path or CLAUDE_EVENT_FILE)
    results = []
    for _, path, folder in candidates[:SCAN_CANDIDATES]:
        objs = read_tail_json_objects(path)
        if not objs:
            continue
        convs = conversational_events(objs)
        if not convs:
            continue           # sessao sem nenhum turno real: ignora
        session_id = str(convs[-1].get("sessionId") or path.stem)
        snapshot = _structured_snapshot(session_id, event_store, now)
        structured = snapshot.last_event_at is not None
        conversation_at = parse_ts(convs[-1].get("timestamp"))
        if (conversation_at is not None
                and (conversation_at - now).total_seconds() > MAX_FUTURE_SKEW_S):
            conversation_at = None
        structured_current = (structured and
                              (conversation_at is None
                               or snapshot.last_event_at >= conversation_at))
        marker_ts = perm_raw.get(session_id)
        marker_current = (
            session_id in perm_pending
            and (conversation_at is None or marker_ts >= conversation_at.timestamp()))
        transcript_state, transcript_age = infer_state(
            objs, now,
            perm_pending=(structured_current and snapshot.state == "perm")
            or marker_current)
        if structured_current and snapshot.ended:
            continue
        if transcript_state == "ask":
            state, age = transcript_state, transcript_age
        elif structured_current:
            state = snapshot.state
            age = float(snapshot.age_s or 0)
        else:
            state, age = transcript_state, transcript_age
        # A marca de perm so sustenta `expired` enquanto for a evidencia MAIS RECENTE.
        # Se um evento estruturado chegou depois dela, a permissao ja foi resolvida e a
        # marca apenas nao foi limpa — exibir `perm?` ali seria afirmar coisa errada
        # sobre uma sessao saudavel, que e exatamente o que este projeto evita.
        marker_age_s = None
        if isinstance(marker_ts, (int, float)):
            evidence_at = [at for at in (snapshot.last_event_at, conversation_at)
                           if at is not None]
            newer_evidence = (evidence_at
                              and max(evidence_at).timestamp() > marker_ts)
            if not newer_evidence:
                marker_age_s = now_epoch - marker_ts

        source_stale = snapshot.stale if structured_current else (
            age == float("inf") or age > SOURCE_STALE_AFTER_S)
        diagnostic = ",".join(snapshot.diagnostics)
        if not structured:
            diagnostic = ",".join(filter(None, (diagnostic, "no_structured_event")))
        elif not structured_current and conversation_at is not None:
            diagnostic = ",".join(filter(None, (diagnostic,
                                                   "transcript_newer_than_event")))
        if parse_ts(convs[-1].get("timestamp")) is None:
            diagnostic = ",".join(filter(None, (diagnostic, "invalid_timestamp")))
        branch, model, effort = meta_of(objs)
        project_raw = project_name_of(objs, folder, limit=FULL_NAME_MAX)
        full = session_display_name(project_raw, branch)
        tokens_win = session_tokens(path, now - timedelta(seconds=SESSION_TOKEN_WINDOW_S))
        context = context_usage(objs)
        results.append({
            "id": session_id,
            "project": full,
            "full": full,
            "_project_raw": project_raw,
            "branch": branch,
            "model": model,
            "effort": effort,
            "tokensWin": tokens_win,
            "ctxPct": context["pct"],
            "context": {"value": context["pct"] if context["quality"] != "unknown" else None,
                        "quality": context["quality"], "unit": "percent"},
            "context_tokens": context["tokens"],
            "tool": "claude",
            "state": state,
            "elapsed": int(age) if age != float("inf") else 0,
            "source_stale": source_stale,
            "source_age_s": None if age == float("inf") else int(age),
            "diagnostic": diagnostic,
            "_age": age,
            "_structured": structured,
            "_activity_age_s": (None if age == float("inf") else int(age)),
            "_perm_marker_age_s": marker_age_s,
        })
    return results


def scan_codex_sessions(index_path: Path, now: datetime,
                        token_since: datetime | None = None,
                        event_path: Path | None = None,
                        rollouts_dir: Path | None = None,
                        state_db: Path | None = None) -> list:
    """Sessoes do Codex: identidade/recencia vem do indice E dos rollouts.

    `rollouts_dir=None` (tests hermeticos) desliga a varredura de rollouts. Em
    producao o daemon passa CODEX_SESSIONS: o session_index parou de receber
    sessoes novas (15/09/2026), entao sem o rollout a sessao nem aparecia — e o
    mtime do rollout e tambem o unico sinal de vida quando nao ha evento de
    hook (codex session_hook nunca gravou evento nesta maquina)."""
    latest = {}
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
                    latest[obj["id"]] = obj    # append-only: ultima ocorrencia vence
    except OSError:
        pass    # indice ausente/corrompido: os rollouts recentes ainda valem

    # Sessoes que existem so no disco: rollout recente entra como identidade, e
    # um id que JA esta no indice ganha a recencia do rollout quando ela for
    # maior (o indice ficou para tras de versoes novas do Codex).
    recentes = (recent_rollouts(rollouts_dir, 24 * 3600, now.timestamp())
                if rollouts_dir is not None else {})
    for rid, mtime in recentes.items():
        ts_iso = datetime.fromtimestamp(mtime, timezone.utc).isoformat()
        atual = latest.get(rid)
        if atual is None:
            latest[rid] = {"id": rid, "thread_name": "codex", "updated_at": ts_iso}
        else:
            idx_ts = parse_ts(atual.get("updated_at"))
            if idx_ts is None or idx_ts.timestamp() < mtime:
                atual["updated_at"] = ts_iso

    # O índice append-only não acompanha todas as versões do Codex. A tabela
    # `threads` é a fonte viva da UI atual e vence índice/rollout quando estiver
    # mais recente.
    thread_rows = codex_threads(state_db) if state_db is not None else {}
    for tid, thread in thread_rows.items():
        atual = latest.get(tid)
        if atual is None:
            latest[tid] = dict(thread)
            recentes[tid] = thread["updated_epoch"]
            continue
        db_ts = parse_ts(thread.get("updated_at"))
        idx_ts = parse_ts(atual.get("updated_at"))
        if db_ts is not None and (idx_ts is None or db_ts > idx_ts):
            atual.update(thread)
        recentes[tid] = max(recentes.get(tid, 0.0), thread["updated_epoch"])

    event_store = load_event_store(event_path or CODEX_EVENT_FILE)
    out = []
    for tid, obj in latest.items():
        tid = str(tid)
        ts = parse_ts(obj.get("updated_at"))
        if ts is not None and (ts - now).total_seconds() > MAX_FUTURE_SKEW_S:
            ts = None
        age = (now - ts).total_seconds() if ts else float("inf")
        age = max(age, 0.0)
        snapshot = _structured_snapshot(tid, event_store, now)
        activity_epoch = recentes.get(tid)
        activity_age = _fresh_activity_age(activity_epoch, now.timestamp())
        activity_after_event = (
            activity_age is not None
            and (snapshot.last_event_at is None
                 or activity_epoch > snapshot.last_event_at.timestamp() + 2.0))
        if snapshot.ended and not activity_after_event:
            continue
        state = snapshot.state
        state_age = snapshot.age_s if snapshot.age_s is not None else 0
        diagnostic = ",".join(snapshot.diagnostics)
        if activity_after_event:
            # Um evento antigo `free`/`ended` nao pode apagar atividade nova. O
            # Codex atualiza a thread e o rollout durante o turno; os hooks podem
            # estar ausentes ou ainda sem confianca nesta instalacao.
            state = "work"
            state_age = activity_age
            diagnostic = ("no_structured_event" if snapshot.last_event_at is None
                          else "activity_after_structured_event")
        elif snapshot.last_event_at is None:
            diagnostic = "no_structured_event"
        # A atividade local tambem repara hooks ausentes/atrasados, mas um evento
        # estruturado mais recente continua sendo a fonte autoritativa.
        # O indice do Codex so tem id/nome/updated_at; modelo, effort, cwd e uso de
        # tokens estao no rollout da sessao, que casa pelo id.
        cx = codex_meta(tid, token_since)
        thread = thread_rows.get(tid, {})
        cwd = cx["cwd"] or thread.get("cwd", "")
        branch = strip_accents(read_git_branch(cwd))[:20]
        project_raw = strip_accents(obj.get("thread_name") or "codex")[:FULL_NAME_MAX]
        full = session_display_name(project_raw, branch)
        context = cx["context"]
        out.append({
            "id": tid,
            "project": full,
            "full": full,
            "_project_raw": project_raw,
            "branch": strip_accents(read_git_branch(cwd))[:20],
            "model": short_model(cx["model"] or thread.get("model", "")),
            "effort": strip_accents(cx["effort"] or thread.get("effort", ""))[:8],
            "tokensWin": cx["tokens"],
            "ctxPct": cx["ctx_pct"],
            "context": {"value": context["pct"] if context["quality"] != "unknown" else None,
                        "quality": context["quality"], "unit": "percent"},
            "context_tokens": context["tokens"],
            "tool": "codex",
            "state": state,
            "elapsed": state_age,
            "source_stale": snapshot.stale and not activity_after_event,
            "source_age_s": (activity_age if activity_after_event else snapshot.age_s),
            "diagnostic": diagnostic,
            "_age": age,
            "_structured": snapshot.last_event_at is not None,
            "_activity_age_s": activity_age,
            "_perm_marker_age_s": None,
        })
    return out


def count_active_12h(projects_dir: Path, codex_index: Path, now: datetime) -> int:
    """Sessoes com atividade REAL na janela [agora-12h, agora], sem repetir.

    Nao serve contar arquivo existente: ha 74 sessoes no disco, quase todas paradas ha
    dias. Tambem nao serve usar so a mtime — qualquer escrita de bookkeeping a bumpa
    sem que tenha havido turno de conversa. Entao a mtime e usada apenas como filtro
    barato (mtime velha => impossivel ter atividade na janela) e, nos poucos arquivos
    que sobrevivem a ele, confirma-se com o timestamp do ultimo evento conversacional.

    A deduplicacao e por id de sessao: um arquivo/thread conta uma vez so, por mais
    eventos que tenha tido na janela.
    """
    cutoff = now - timedelta(seconds=ACTIVE_WINDOW_S)
    cutoff_ts = cutoff.timestamp()
    active: set = set()

    if projects_dir.is_dir():
        for project in projects_dir.iterdir():
            if not project.is_dir():
                continue
            for path in project.glob("*.jsonl"):
                try:
                    if path.stat().st_mtime < cutoff_ts:
                        continue          # filtro barato: nem abre o arquivo
                except OSError:
                    continue
                objs = read_tail_json_objects(path)
                convs = conversational_events(objs)
                if not convs:
                    continue
                ts = parse_ts(convs[-1].get("timestamp"))
                if ts and ts >= cutoff:    # atividade de conversa de verdade
                    active.add("claude:" + str(convs[-1].get("sessionId") or path.stem))

    if codex_index.is_file():
        try:
            with codex_index.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    tid = obj.get("id")
                    ts = parse_ts(obj.get("updated_at"))
                    if tid and ts and ts >= cutoff:
                        active.add("codex:" + str(tid))   # set: nunca conta duas vezes
        except OSError:
            pass

    return len(active)


def fetch_id_list(base_url: str, path: str, key: str, timeout: float = 3.0,
                  token: str | None = None) -> set:
    """Le uma lista de ids mantida pelo device (escondidas ou fixadas).

    O estado mora no ESP32 porque quem escondeu/escolheu foi o dedo do usuario no
    painel. Device fora do ar devolve conjunto vazio — degrada, nao quebra.
    """
    try:
        with urllib.request.urlopen(authenticated_request(base_url + path, token=token),
                                    timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {str(x) for x in data.get(key, [])}
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return set()


def fetch_snooze(base_url: str, token: str | None = None, timeout: float = 3.0) -> int:
    """Segundos restantes de mudo, lidos da placa.

    Duracao relativa e nao timestamp: os dois relogios sao independentes e segundos
    restantes nao tem fuso nem skew (mesmo racional de `elapsed`, SPEC secao 5).
    Device fora do ar devolve 0 — degrada, nao quebra, igual ao fetch_id_list.
    """
    try:
        with urllib.request.urlopen(
                authenticated_request(base_url + "/snooze", token=token),
                timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return max(0, int(data.get("snooze_s", 0)))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError, TypeError):
        return 0


# Pares (sessao, estado) que ja receberam toast. Vive no processo de proposito:
# reiniciar o daemon re-avisa, e isso e correto — quem reiniciou perdeu o contexto
# tambem. Persistir em disco faria o operador perder o unico aviso de um perm real
# so porque o daemon foi reiniciado no meio.
_toasted: set = set()


def maybe_toast(sessions: list, snooze_s: int) -> int:
    """Notifica quem acabou de cruzar `critical`. Uma vez por (sessao, estado).

    Mesmo principio do aviso de hook, que so imprime quando o diagnostico MUDA:
    repetir treina o operador a ignorar justamente o aviso que importa.
    """
    if snooze_s > 0:
        return 0          # mudo e mudo: cobre inclusive escalada nascida depois
    disparados, vivos = 0, set()
    for s in sessions:
        chave = (s["id"], s["state"])
        vivos.add(chave)
        if s.get("severity") != "critical" or chave in _toasted:
            continue
        # Marca ANTES de olhar o resultado: canal indisponivel nao pode virar nova
        # tentativa a cada 5s. Canal quebrado e assunto do `doctor`, nao do loop.
        _toasted.add(chave)
        elapsed = int(s.get("elapsed") or 0)
        if notify("Monitor.AI",
                  "{} aguarda voce: {} ha {}min".format(
                      s.get("project") or s["id"][:8], s["state"], max(1, elapsed // 60))):
            disparados += 1
    # Par que saiu da lista pode avisar de novo: seria um bloqueio NOVO, nao repeticao.
    _toasted.intersection_update(vivos)
    return disparados


def hook_warnings(sessions: list, health: dict) -> list:
    """Avisa quando falta hook ou quando atividade atual nao gerou evento."""
    rotulos = (("claude", "Claude Code", "install_hook.py"),
               ("codex", "Codex", "install_codex_hook.py"),
               ("commandcode", "Command Code", "install_commandcode_hook.py"))
    warnings = []
    for tool, nome, script in rotulos:
        rows = [s for s in sessions if s.get("tool") == tool]
        if not rows:
            continue
        if not health.get(tool):
            warnings.append(
                "hook do {} nao instalado e ha sessao dele no board. Rode "
                "`python tools/{}` e reinicie as sessoes.".format(nome, script))
            continue
        active_without_event = any(
            s.get("state") in {"work", "ask", "perm"}
            and int(s.get("elapsed") or 0) <= WORK_MAX_AGE_S
            and any(tag in str(s.get("diagnostic") or "") for tag in (
                "no_structured_event", "activity_after_structured_event",
                "transcript_newer_than_event"))
            for s in rows)
        if active_without_event:
            if tool == "codex":
                detail = "Revise e confie a definicao em `/hooks`, depois reinicie a sessao."
            else:
                detail = "Confira se outro programa substituiu o hook e reinstale-o."
            warnings.append(
                "ha atividade recente do {} sem evento atual do hook; o daemon "
                "recuperou o estado do historico local. {}".format(nome, detail))
    return warnings


def build_payload_v1(claude_dir: Path, codex_index: Path, max_sessions: int,
                     tz: timezone, now: datetime | None = None,
                     hidden: set | None = None, pinned: set | None = None,
                     opencode_db: Path | None = None,
                     opencode_ctx_window: int = 0,
                     history_db: Path | None = None,
                     opencode_log_path: Path | None = None,
                     thresholds: Thresholds | None = None,
                     snooze_minutes: int = DEFAULT_SNOOZE_MINUTES,
                     force_backfill: bool = False,
                     codex_rollouts_dir: Path | None = None,
                     codex_state_db: Path | None = None,
                     commandcode_dir: Path | None = None,
                     commandcode_ctx_window: int = 0,
                     retention_days: int = usage_history.RETENTION_DAYS,
                     hourly_retention_days: int = usage_history.HOURLY_RETENTION_DAYS) -> dict:
    """Payload legÃ­vel pelo firmware v1 durante a migraÃ§Ã£o do protocolo.

    `opencode_db=None` desliga a coleta do OpenCode (tests hermeticos); o daemon
    passa o caminho real (padrao do usuario ou --opencode-db). `history_db=None`
    desliga o historico diario pelos mesmos motivos; com caminho, o total do dia
    (3 fontes) e persistido e `stats.history.daily` entra como campo aditivo."""
    now = now or datetime.now(timezone.utc)
    dismissed = load_dismissed()
    hidden = hidden or set()
    pinned = pinned or set()

    token_since = now - timedelta(seconds=SESSION_TOKEN_WINDOW_S)
    todas = (scan_claude_sessions(claude_dir, now)
             + scan_codex_sessions(codex_index, now, token_since,
                                   rollouts_dir=codex_rollouts_dir,
                                   state_db=codex_state_db))
    if opencode_db is not None:
        todas += scan_opencode_sessions(now, token_since, database=opencode_db,
                                        ctx_window=opencode_ctx_window,
                                        log_path=opencode_log_path)
    if commandcode_dir is not None:
        todas += scan_commandcode_sessions(now, token_since, directory=commandcode_dir,
                                           ctx_window=commandcode_ctx_window)
    todas = filter_dismissed(todas, dismissed)
    visiveis = [s for s in todas if s["id"] not in hidden]

    # Entra no board quem teve atividade nas ultimas BOARD_WINDOW_S — sem isso o grid
    # enchia de sessao parada ha dias (medido: 72 de 74 em `free`) — OU quem foi fixado
    # pelo seletor, que e uma escolha explicita e por isso ignora a janela.
    sessions = [s for s in visiveis
                if s["_age"] <= BOARD_WINDOW_S or s["id"] in pinned]

    # Atencao primeiro; dentro do mesmo estado, recencia. A ordem anterior so desempata
    # eventos exatamente contemporaneos, evitando troca visual sem violar a recencia.
    global _previous_board_ids
    sessions = rank_sessions(sessions, _previous_board_ids)

    total = len(sessions)
    top = sessions[:max_sessions]
    dedupe_display_names(top)
    _previous_board_ids = [s["id"] for s in top]
    no_board = {s["id"] for s in top}
    # Severidade calculada aqui, e nao dentro de cada coletor: a regra e uma so para os
    # tres agentes, e um coletor novo nao pode esquecer de aplica-la. Campo aditivo do
    # protocolo — firmware antigo ignora (validado em session_transport.cpp).
    limiares = thresholds or Thresholds(warning_after_s=DEFAULT_WARNING_AFTER_S,
                                        critical_after_s=DEFAULT_CRITICAL_AFTER_S)
    for s in top:
        # `elapsed` e o mesmo numero que o card exibe como tempo no estado: a escalada
        # tem que casar com o que o operador ve, nao com uma segunda medida de idade.
        s["severity"] = severity_for(
            s["state"], s.get("elapsed") or 0,
            structured=bool(s.get("_structured")),
            perm_marker_age_s=s.get("_perm_marker_age_s"),
            thresholds=limiares)
    for s in top:
        s.pop("_age", None)
        s.pop("_structured", None)
        s.pop("_activity_age_s", None)
        s.pop("_perm_marker_age_s", None)
        s.pop("_project_raw", None)

    # Catalogo do seletor: tudo que existe e nao esta no board, inclusive o que foi
    # escondido por engano — e justamente assim que se traz um card de volta.
    catalogo = [s for s in todas if s["id"] not in no_board]
    catalogo.sort(key=lambda s: s["_age"])
    catalogo = catalogo[:CATALOG_MAX]
    dedupe_display_names(catalogo)
    catalogo = [{"id": s["id"], "name": s["full"][:25],
                 "provider": s.get("provider", ""), "tool": s["tool"], "state": s["state"]}
                for s in catalogo]

    usage = collect_usage(claude_dir, tz, now)
    active_12h = count_active_12h(claude_dir, codex_index, now)
    if opencode_db is not None:
        active_12h += count_opencode_12h(opencode_db, now, ACTIVE_WINDOW_S)
    if commandcode_dir is not None:
        active_12h += count_commandcode_12h(commandcode_dir, now, ACTIVE_WINDOW_S)
    stats = {
        "tokens_today": usage["tokens_today"],
        "spark": usage["spark"],
        "spark_end_hour": usage["spark_end_hour"],
        "active_12h": active_12h,
        "token_window_h": SESSION_TOKEN_WINDOW_H,
        "total_sessions": total,
        "quota": collect_quota(claude_dir, now, opencode_db=opencode_db,
                               commandcode_dir=commandcode_dir),
    }
    if history_db is not None:
        stats["history"] = _record_daily_history(history_db, claude_dir, tz, now,
                                                 usage["tokens_today"],
                                                 opencode_db=opencode_db,
                                                 force_backfill=force_backfill,
                                                 rollouts_dir=codex_rollouts_dir,
                                                 commandcode_dir=commandcode_dir,
                                                 retention_days=retention_days)
        _record_hourly_history(
            history_db, claude_dir, now, rollouts_dir=codex_rollouts_dir,
            opencode_db=opencode_db, commandcode_dir=commandcode_dir,
            retention_days=hourly_retention_days,
            force_backfill=force_backfill)
        # ttl_s=None: caminho de producao do cache POR PERIODO (d1/d7/d30 com TTLs
        # proprios). Sem isto cai no caminho legado (um TTL para os tres periodos),
        # que reprocessa o d30 inteiro a cada 60s — medido em 42s com o volume atual
        # de sessoes, o suficiente para o ciclo do daemon (5s) atrasar dezenas de
        # segundos e o painel parecer "stale".
        stats["usage"] = {"top": usage_top.build_cached(
            claude_dir, codex_index, opencode_db, tz, now, ttl_s=None,
            codex_rollouts_dir=codex_rollouts_dir,
            commandcode_dir=commandcode_dir)}
    return {
        "generated_at": now.isoformat(),
        "generated_at_epoch": int(now.timestamp()),
        "sessions": top,
        "catalog": catalogo,
        "stats": stats,
        # A placa arma o mudo no toque, mas a duracao e do operador (monitor.toml).
        # Mandar aqui evita um valor compilado no firmware discordando da config.
        "snooze_minutes": snooze_minutes,
    }


def _record_daily_history(history_db: Path, claude_dir: Path, tz: timezone,
                          now: datetime, claude_today: int, *,
                          opencode_db: Path | None,
                          force_backfill: bool = False,
                          rollouts_dir: Path | None = None,
                          commandcode_dir: Path | None = None,
                          retention_days: int = usage_history.RETENTION_DAYS) -> dict:
    """Persiste o total do dia (3 fontes) e devolve o bloco stats.history.

    Codex entra pelo mesmo diff acumulado do codex_series (total = janela do dia
    local); OpenCode pelo window_tokens desde a meia-noite local. Backfill roda
    quando a tabela esta vazia (primeiro boot) E quando `force_backfill` — o
    INSERT OR IGNORE protege as linhas vivas, entao re-rodar so preenche dias que
    o daemon ficou desligado: com o backfill limitado ao boot vazio, qualquer dia
    sem daemon virava 0 para sempre (medido: 12–14/09/2026 sumiram do heatmap)."""
    from usage_tracker import codex_series

    codex = codex_series(CODEX_SESSIONS, tz, now)
    codex_today = codex.total if codex else 0
    day_start = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    opencode_today = (window_tokens(opencode_db, day_start.timestamp())
                      if opencode_db is not None else 0)
    commandcode_today = (commandcode_window_tokens(commandcode_dir, day_start.timestamp())
                         if commandcode_dir is not None else 0)
    total_today = claude_today + codex_today + opencode_today + commandcode_today

    if force_backfill or usage_history.is_empty(history_db):
        gravados = usage_history.backfill(
            history_db, claude_dir=claude_dir, rollouts_dir=rollouts_dir,
            opencode_db=opencode_db, tz=tz, now=now,
            commandcode_dir=commandcode_dir,
            replace_existing=force_backfill)
        print(f"[daemon] backfill do historico: {len(gravados)} dias "
              f"({sum(gravados.values()):,} tokens)", file=sys.stderr)
    usage_history.record_today(history_db, total_today, tz, now)
    usage_history.prune(history_db, keep_days=retention_days, tz=tz, now=now)
    return {"daily": usage_history.daily_window(history_db, tz, now=now)}


def _record_hourly_history(history_db: Path, claude_dir: Path, now: datetime, *,
                           rollouts_dir: Path | None, opencode_db: Path | None,
                           commandcode_dir: Path | None,
                           retention_days: int = usage_history.HOURLY_RETENTION_DAYS,
                           force_backfill: bool = False) -> None:
    """Atualiza buckets horários no máximo por minuto, sem afetar o payload atual."""
    observed = (now.replace(tzinfo=timezone.utc) if now.tzinfo is None
                else now.astimezone(timezone.utc))
    key = Path(history_db)
    previous = _hourly_history_refresh.get(key)
    try:
        empty = usage_history.hourly_is_empty(key)
        day_changed = previous is not None and previous.date() != observed.date()
        if (not force_backfill and not empty and not day_changed and previous is not None
                and (observed - previous).total_seconds() < HOURLY_REFRESH_INTERVAL_S):
            return

        # Marca a tentativa antes de ler as fontes para também limitar retries quando um
        # arquivo de origem está temporariamente inacessível. O próximo ciclo tenta em 60s.
        _hourly_history_refresh[key] = observed
        days = (min(usage_history.WINDOW_DAYS, max(int(retention_days), 1))
                if force_backfill or empty else 1)
        usage_history.backfill_hourly(
            key, claude_dir=claude_dir, rollouts_dir=rollouts_dir,
            opencode_db=opencode_db, commandcode_dir=commandcode_dir,
            now=observed, days=days)
        usage_history.prune_hourly(key, keep_days=retention_days, now=observed)
    except Exception as exc:
        print(f"[daemon] histórico horário indisponível: {exc}", file=sys.stderr)


# Compatibilidade para integraÃ§Ãµes Python existentes; o daemon usa os builders versionados.
build_payload = build_payload_v1


def build_payload_v2(claude_dir: Path, codex_index: Path, max_sessions: int,
                     tz: timezone, *, node_id: str, device_id: str,
                     daemon_instance_id: str, sequence: int,
                     now: datetime | None = None, hidden: set | None = None,
                     pinned: set | None = None, opencode_db: Path | None = None,
                     opencode_ctx_window: int = 0,
                     history_db: Path | None = None,
                     opencode_log_path: Path | None = None,
                     thresholds: Thresholds | None = None,
                     snooze_minutes: int = DEFAULT_SNOOZE_MINUTES,
                     force_backfill: bool = False,
                     codex_rollouts_dir: Path | None = None,
                     codex_state_db: Path | None = None,
                     commandcode_dir: Path | None = None,
                     commandcode_ctx_window: int = 0,
                     retention_days: int = usage_history.RETENTION_DAYS,
                     hourly_retention_days: int = usage_history.HOURLY_RETENTION_DAYS) -> dict:
    """Projeta os dados normalizados atuais no envelope estÃ¡vel do protocolo v2."""
    generated = now or datetime.now(timezone.utc)
    v1 = build_payload_v1(claude_dir, codex_index, max_sessions, tz, generated,
                          hidden=hidden, pinned=pinned, opencode_db=opencode_db,
                          opencode_ctx_window=opencode_ctx_window,
                          history_db=history_db, opencode_log_path=opencode_log_path,
                          thresholds=thresholds, snooze_minutes=snooze_minutes,
                          force_backfill=force_backfill,
                          codex_rollouts_dir=codex_rollouts_dir,
                          codex_state_db=codex_state_db,
                          commandcode_dir=commandcode_dir,
                          commandcode_ctx_window=commandcode_ctx_window,
                          retention_days=retention_days,
                          hourly_retention_days=hourly_retention_days)
    legacy_stats = v1["stats"]
    series = collect_series(claude_dir, CODEX_SESSIONS, tz, generated)
    usage = {"series": [{"provider": item.provider, "buckets": dict(item.buckets),
                           "total": item.total, "quality": item.quality}
                          for item in series],
             "active_12h": legacy_stats["active_12h"],
             "token_window_h": legacy_stats["token_window_h"],
             "total_sessions": legacy_stats["total_sessions"]}
    if "history" in legacy_stats:
        usage["history"] = legacy_stats["history"]
    if "usage" in legacy_stats:
        usage["top"] = legacy_stats["usage"]["top"]
    return build_snapshot_v2(
        sessions=v1["sessions"], catalog=v1["catalog"], usage=usage,
        quota=legacy_stats["quota"], health=hook_health(), node_id=node_id,
        device_id=device_id, daemon_instance_id=daemon_instance_id,
        sequence=sequence, now=generated,
    )


def post_sessions(url: str, payload: dict, timeout: float = 5.0,
                  token: str | None = None) -> int:
    """Status HTTP do POST: 2xx = ok; 422 = firmware rejeitou; 0 = falha de rede.

    A distincao importa: 422 com sessao OpenCode e sinal de firmware antigo (fallback
    util); timeout/erro de rede nao e — reenviar sem OpenCode atrasa e engana."""
    body = json.dumps(payload).encode("utf-8")
    req = authenticated_request(url, data=body, method="POST",
                                headers={"Content-Type": "application/json"}, token=token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        print(f"[daemon] falha ao enviar para {url}: HTTP Error {e.code}", file=sys.stderr)
        return e.code
    except (urllib.error.URLError, OSError) as e:
        print(f"[daemon] falha ao enviar para {url}: {e}", file=sys.stderr)
        return 0


def format_summary(payload: dict) -> str:
    parts = []
    for s in payload["sessions"]:
        tag = {"claude": "CL", "codex": "CX", "opencode": "OC",
               "commandcode": "CC"}.get(s["tool"], "??")
        parts.append("{}[{}:{}]".format(s["project"], tag, s["state"]))
    return ", ".join(parts) or "(nenhuma sessao)"


def usage_total_for_log(usage: dict) -> int:
    """Total diário para o log, sem exigir o campo legado de um payload v2."""
    if "tokens_today" in usage:
        return int(usage["tokens_today"] or 0)
    series = usage.get("series")
    if not isinstance(series, list):
        return 0
    return sum(int(item.get("total") or 0) for item in series if isinstance(item, dict))


def refresh_transport_timestamp(payload: dict, *, previous_epoch: int = 0,
                                now: datetime | None = None) -> int:
    """Refresh the envelope timestamp after collection has finished.

    Collectors can take longer than the firmware freshness window (especially on
    a first history backfill).  The timestamp describes when the snapshot is
    ready for transport, not when the filesystem scan started.  Keep the v1
    seconds field and v2 milliseconds field monotonic within one daemon process.
    """
    current = now or datetime.now(timezone.utc)
    if "generated_at_epoch" in payload:
        epoch = max(int(current.timestamp()), int(previous_epoch) + 1)
        payload["generated_at_epoch"] = epoch
        payload["generated_at"] = datetime.fromtimestamp(epoch, timezone.utc).isoformat()
        return epoch
    if "generated_at_epoch_ms" in payload:
        epoch_ms = max(int(current.timestamp() * 1000), int(previous_epoch) + 1)
        payload["generated_at_epoch_ms"] = epoch_ms
        return epoch_ms
    return int(previous_epoch)


def add_arguments(ap: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add daemon flags to either the legacy parser or the unified CLI."""
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--interval", type=float, default=None)
    ap.add_argument("--claude-dir", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--codex-index", default=str(CODEX_SESSION_INDEX))
    ap.add_argument("--codex-rollouts", default=str(CODEX_SESSIONS),
                    help="diretorio dos rollouts do Codex (padrao: $CODEX_HOME/sessions)")
    ap.add_argument("--codex-state-db", default=str(CODEX_STATE_DB),
                    help="SQLite de estado do Codex (padrao: $CODEX_HOME/state_5.sqlite)")
    ap.add_argument("--opencode-db", default=None,
                    help="caminho do opencode.db (padrao: ~/.local/share/opencode/opencode.db)")
    ap.add_argument("--commandcode-projects", default=None,
                    help="diretorio dos transcripts do Command Code "
                         "(padrao: ~/.commandcode/projects)")
    ap.add_argument("--max-sessions", type=int, default=MAX_SESSIONS)
    ap.add_argument("--tz-offset", type=float, default=-3.0,
                    help="fuso para o corte do dia (padrao -3 = horario de Brasilia)")
    ap.add_argument("--protocol", type=int, choices=(1, 2), default=1,
                    help="versao do payload (padrao: 1, a unica servida pelo firmware "
                         "atual; use 2 quando o endpoint /api/v2/snapshot existir)")
    ap.add_argument("--once", action="store_true")
    return ap


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    return add_arguments(ap).parse_args(argv)


def run(args: argparse.Namespace, config: MonitorConfig) -> int:
    """Run the daemon from parsed options and one immutable config snapshot."""
    host = args.host if args.host is not None else config.device.host
    port = args.port if args.port is not None else config.device.port
    interval = args.interval if args.interval is not None else config.daemon.interval_s

    base = "http://{}:{}".format(host, port)
    url = base + ("/api/v2/snapshot" if args.protocol == 2 else "/sessions")
    tz = timezone(timedelta(hours=args.tz_offset))
    claude_dir, codex_index = Path(args.claude_dir), Path(args.codex_index)
    node_id = os.environ.get("MONITOR_NODE_ID", "").strip() or os.environ.get("COMPUTERNAME", "monitor")
    device_id = os.environ.get("MONITOR_DEVICE_ID", "").strip() or host
    transport_token = config.transport.api_token or MONITOR_API_TOKEN
    daemon_instance_id = "{}-{}".format(node_id, uuid.uuid4().hex)
    sequence = 0

    print("[daemon] Monitor.AI -> {} a cada {}s (dia em UTC{:+g}, board = ultimas {:.0f}h)"
          .format(url, interval, args.tz_offset, BOARD_WINDOW_S / 3600))
    print("[daemon] CODEX_HOME={}".format(CODEX_HOME))

    # Guarda de instancia unica: dois daemons postando no mesmo segundo geram o
    # mesmo generated_at_epoch e o anti-replay da placa derruba um deles com 409.
    guard = None
    if not getattr(args, "once", False):
        # Guarda so para o daemon continuo (--once e um ciclo solto, inofensivo);
        # sem este escape, o pytest do run() falha quando ha um daemon real rodando.
        guard = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            guard.bind(("127.0.0.1", 8770))
        except OSError:
            print("[daemon] JA EXISTE outro daemon rodando (porta de guarda 8770 "
                  "ocupada). Encerrando esta instancia.", file=sys.stderr)
            return 1

    # Relido a cada ciclo de proposito: os arquivos de hook sao globais e outra
    # ferramenta pode reescreve-los com o daemon ja rodando — foi assim que aconteceu.
    avisos_anteriores: list = []

    # CLI sempre tem o attr (argparse); SimpleNamespace de testes nao tem ->
    # None, para a varredura de rollouts nao vazar disco real nos testes.
    codex_rollouts_dir = (Path(args.codex_rollouts)
                          if getattr(args, "codex_rollouts", None) else None)
    codex_state_db = (Path(args.codex_state_db)
                      if getattr(args, "codex_state_db", None) else None)

    limiares = thresholds_from(config.alerts)
    snooze_minutes = config.alerts.snooze_minutes
    severidade_anterior = None
    last_transport_epoch = 0
    # Backfill do historico no boot e a cada virada do dia local: INSERT OR
    # IGNORE protege as linhas vivas, e o dia local (e nao o UTC) decide quando
    # repovoar — dias com o daemon desligado entram na proxima rodada. None =
    # primeiro ciclo forca o backfill (boot).
    ultimo_dia_backfill = None

    while True:
        hidden = fetch_id_list(base, "/hidden", "hidden", token=transport_token)
        pinned = fetch_id_list(base, "/pinned", "pinned", token=transport_token)
        snooze_s = fetch_snooze(base, token=transport_token)
        # CLI sempre tem o attr (argparse); SimpleNamespace de testes nao tem ->
        # fica None para nao vazar o banco real do operador nos testes.
        if hasattr(args, "opencode_db"):
            opencode_db = (Path(args.opencode_db) if args.opencode_db
                           else opencode_default_db())
        else:
            opencode_db = None
        ctx_window = config.usage.opencode_context_window
        # CLI sempre tem o attr; SimpleNamespace de testes nao tem -> None, para nao
        # vazar o diretorio real do operador nos testes.
        if hasattr(args, "commandcode_projects"):
            commandcode_dir = (Path(args.commandcode_projects)
                               if args.commandcode_projects
                               else commandcode_default_dir())
        else:
            commandcode_dir = None
        commandcode_ctx = config.usage.commandcode_context_window
        history_db = Path(config.storage.database_path)
        opencode_log_path = OPENCODE_LOG_PATH
        dia_backfill = usage_history.local_today(tz)
        force_backfill = (ultimo_dia_backfill is None
                          or dia_backfill != ultimo_dia_backfill)
        ultimo_dia_backfill = dia_backfill
        if args.protocol == 1:
            payload = build_payload_v1(claude_dir, codex_index, args.max_sessions, tz,
                                       hidden=hidden, pinned=pinned,
                                       opencode_db=Path(opencode_db) if opencode_db else None,
                                       opencode_ctx_window=ctx_window,
                                       history_db=history_db,
                                       opencode_log_path=opencode_log_path,
                                       thresholds=limiares,
                                       snooze_minutes=snooze_minutes,
                                       force_backfill=force_backfill,
                                       codex_rollouts_dir=codex_rollouts_dir,
                                       codex_state_db=codex_state_db,
                                       commandcode_dir=commandcode_dir,
                                       commandcode_ctx_window=commandcode_ctx,
                                       retention_days=config.storage.retention_days,
                                       hourly_retention_days=config.storage.hourly_retention_days)
            st = payload["stats"]
        else:
            sequence += 1
            payload = build_payload_v2(
                claude_dir, codex_index, args.max_sessions, tz, node_id=node_id,
                device_id=device_id, daemon_instance_id=daemon_instance_id,
                sequence=sequence, hidden=hidden, pinned=pinned,
                opencode_db=Path(opencode_db) if opencode_db else None,
                opencode_ctx_window=ctx_window, history_db=history_db,
                opencode_log_path=opencode_log_path, thresholds=limiares,
                snooze_minutes=snooze_minutes, force_backfill=force_backfill,
                codex_rollouts_dir=codex_rollouts_dir,
                codex_state_db=codex_state_db,
                commandcode_dir=commandcode_dir,
                commandcode_ctx_window=commandcode_ctx,
                retention_days=config.storage.retention_days,
                hourly_retention_days=config.storage.hourly_retention_days)
            st = payload["stats"]["usage"]
        last_transport_epoch = refresh_transport_timestamp(
            payload, previous_epoch=last_transport_epoch)
        today_tokens = usage_total_for_log(st)
        status = post_sessions(url, payload, timeout=config.transport.timeout_s,
                               token=transport_token)
        if status == 422 and any(s.get("tool") not in BASELINE_TOOLS
                                 for s in payload.get("sessions", [])):
            # Firmware antigo rejeita o POST inteiro (422) quando recebe um tool que nao
            # conhece — melhor degradar para Claude/Codex do que derrubar o painel. Avisa
            # uma vez so: repetir a cada ciclo vira ruido (mesma regra dos avisos de hook).
            # Timeout/erro de rede NAO cai aqui (status 0): reenviar nesse caso atrasaria o
            # ciclo e imprimiria um aviso falso.
            if not getattr(run, "_unknown_tool_fallback_warned", False):
                print("[daemon] AVISO: firmware nao aceita um dos provedores (422); "
                      "reenviando so com Claude/Codex. Compile e grave o firmware novo "
                      "(pio run -t upload) para exibir OpenCode/Command Code.",
                      file=sys.stderr)
                run._unknown_tool_fallback_warned = True
            if args.protocol == 1:
                payload = build_payload_v1(claude_dir, codex_index, args.max_sessions,
                                           tz, hidden=hidden, pinned=pinned,
                                           thresholds=limiares,
                                           snooze_minutes=snooze_minutes,
                                           codex_rollouts_dir=codex_rollouts_dir,
                                           codex_state_db=codex_state_db,
                                           retention_days=config.storage.retention_days)
                st = payload["stats"]
            else:
                payload = build_payload_v2(
                    claude_dir, codex_index, args.max_sessions, tz, node_id=node_id,
                    device_id=device_id, daemon_instance_id=daemon_instance_id,
                    sequence=sequence, hidden=hidden, pinned=pinned,
                    thresholds=limiares, snooze_minutes=snooze_minutes,
                    codex_rollouts_dir=codex_rollouts_dir,
                    codex_state_db=codex_state_db,
                    retention_days=config.storage.retention_days)
                st = payload["stats"]["usage"]
            today_tokens = usage_total_for_log(st)
            status = post_sessions(url, payload, timeout=config.transport.timeout_s,
                                   token=transport_token)
        retried = False
        if status == 0:
            # Timeout/erro de rede: a placa pode estar reassociando o Wi-Fi OU a
            # resposta se perdeu depois de aplicado (medido: retry volta 409 do
            # anti-replay — o payload JÁ estava na placa). Uma retomada curta
            # resolve a maioria; 4xx da 1a tentativa nao cai aqui (sem retry cego).
            time.sleep(1.5)
            retried = True
            status = post_sessions(url, payload, timeout=config.transport.timeout_s,
                                   token=transport_token)
        if status == 409 and retried:
            # Anti-replay confirmou que a 1a tentativa foi aplicada; resposta e que
            # se perdeu. Tratar como sucesso evita marcar FALHOU um ciclo saudavel.
            status = 200
            print("[daemon] payload ja aplicado na 1a tentativa (resposta perdida "
                  "na rede); 409 do anti-replay tratado como OK")
        ok = 200 <= status < 300

        # So imprime quando o diagnostico MUDA: repetir o mesmo aviso a cada 5s vira
        # ruido e o operador para de ler justamente a linha que importa.
        # Toast so depois do POST: o painel e o canal principal e nao deve esperar
        # pelo secundario. Suprimido enquanto o mudo da placa estiver armado.
        if ok:
            maybe_toast(payload["sessions"], snooze_s)

        # Severidade agregada no log, e so quando MUDA — mesma regra dos avisos de
        # hook logo abaixo: repetir a cada 5s vira ruido.
        severidade = worst_severity([s.get("severity", "none")
                                     for s in payload["sessions"]])
        if severidade != severidade_anterior:
            if severidade != "none":
                print("[daemon] alerta: {}{}".format(
                    severidade, " (mudo {}s)".format(snooze_s) if snooze_s else ""),
                    file=sys.stderr)
            elif severidade_anterior and severidade_anterior != "none":
                print("[daemon] alerta encerrado.", file=sys.stderr)
            severidade_anterior = severidade

        avisos = hook_warnings(payload["sessions"], hook_health())
        if avisos != avisos_anteriores:
            for aviso in avisos:
                print("[daemon] AVISO: " + aviso, file=sys.stderr)
            if not avisos and avisos_anteriores:
                print("[daemon] hooks de volta: estados voltam a vir por evento.")
            avisos_anteriores = avisos
        print("[daemon] {} [{}] {} cards | {} ativas 12h | {:,} tok hoje | {}".format(
            datetime.now().strftime("%H:%M:%S"),
            "OK" if ok else "FALHOU",
            len(payload["sessions"]), st["active_12h"],
            today_tokens, format_summary(payload)), flush=True)

        if args.once:
            break
        time.sleep(interval)
    return 0


def main() -> int:
    args = parse_args()
    try:
        config = MonitorConfig.load()
    except ValueError as error:
        print("[daemon] configuracao invalida: {}".format(error), file=sys.stderr)
        return 2
    return run(args, config)


if __name__ == "__main__":
    raise SystemExit(main())
