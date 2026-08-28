#!/usr/bin/env python3
"""
Monitor.AI — daemon local.

Le as sessoes do Claude Code e do Codex CLI nesta maquina e empurra o resumo para o
ESP32 via HTTP (POST /sessions). Ver docs/SPEC.md secao 5.

Uso:
    python tools/session_daemon.py --host 192.168.2.165
    python tools/session_daemon.py --interval 3
    python tools/session_daemon.py --once            # um ciclo, para debug

Depende apenas da biblioteca padrao do Python.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from session_state import (PERM_MARKER_MAX_AGE_S, conversational_events, infer_state,
                           parse_ts, strip_accents)
from agent_events import MAX_FUTURE_SKEW_S, reduce_session_events
from session_hook import hook_health, load_event_store
from session_meta import CODEX_SESSIONS, codex_meta, read_git_branch, context_usage
from usage_tracker import collect as collect_usage, collect_series, session_tokens
from quota import collect as collect_quota
from opencode_sessions import (count_active_12h as count_opencode_12h,
                               db_path as opencode_default_db,
                               scan_opencode_sessions)
from protocol_v2 import build_snapshot_v2
from monitor_config import MonitorConfig

MAX_SESSIONS = 6

# Ordem de urgencia: o que precisa de voce sobe. Empate resolve por recencia.
STATE_PRIORITY = {"perm": 0, "ask": 1, "work": 2, "free": 3}

DISMISS_FILE = Path(__file__).parent / ".dismissed.json"
PERM_FILE = Path.home() / ".claude" / "monitor-ai-perm.json"
CLAUDE_EVENT_FILE = Path.home() / ".claude" / "monitor-ai-events.json"
CODEX_EVENT_FILE = Path.home() / ".codex" / "monitor-ai-events.json"
SOURCE_STALE_AFTER_S = 90.0

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
        transcript_state, transcript_age = infer_state(
            objs, now,
            perm_pending=(structured and snapshot.state == "perm")
            or session_id in perm_pending)
        if transcript_state == "ask":
            state, age = transcript_state, transcript_age
        elif structured:
            if snapshot.ended:
                continue
            state = snapshot.state
            age = float(snapshot.age_s or 0)
        else:
            state, age = transcript_state, transcript_age
        source_stale = snapshot.stale if structured else (
            age == float("inf") or age > SOURCE_STALE_AFTER_S)
        diagnostic = ",".join(snapshot.diagnostics)
        if parse_ts(convs[-1].get("timestamp")) is None:
            diagnostic = ",".join(filter(None, (diagnostic, "invalid_timestamp")))
        full = project_name_of(objs, folder, limit=FULL_NAME_MAX)
        branch, model, effort = meta_of(objs)
        tokens_win = session_tokens(path, now - timedelta(seconds=SESSION_TOKEN_WINDOW_S))
        context = context_usage(objs)
        results.append({
            "id": session_id,
            "project": full,
            "full": full,
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
        })
    return results


def scan_codex_sessions(index_path: Path, now: datetime,
                        token_since: datetime | None = None,
                        event_path: Path | None = None) -> list:
    if not index_path.is_file():
        return []
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
        return []

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
        if snapshot.ended:
            continue
        state = snapshot.state
        state_age = snapshot.age_s if snapshot.age_s is not None else 0
        diagnostic = ",".join(snapshot.diagnostics)
        if snapshot.last_event_at is None:
            diagnostic = "no_structured_event"
        full = strip_accents(obj.get("thread_name") or "codex")[:FULL_NAME_MAX]
        # O indice do Codex so tem id/nome/updated_at; modelo, effort, cwd e uso de
        # tokens estao no rollout da sessao, que casa pelo id.
        cx = codex_meta(tid, token_since)
        context = cx["context"]
        out.append({
            "id": tid,
            "project": full,
            "full": full,
            "branch": strip_accents(read_git_branch(cx["cwd"]))[:20],
            "model": short_model(cx["model"]),
            "effort": strip_accents(cx["effort"])[:8],
            "tokensWin": cx["tokens"],
            "ctxPct": cx["ctx_pct"],
            "context": {"value": context["pct"] if context["quality"] != "unknown" else None,
                        "quality": context["quality"], "unit": "percent"},
            "context_tokens": context["tokens"],
            "tool": "codex",
            "state": state,
            "elapsed": state_age,
            "source_stale": snapshot.stale,
            "source_age_s": snapshot.age_s,
            "diagnostic": diagnostic,
            "_age": age,
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


def hook_warnings(sessions: list, health: dict) -> list:
    """Avisos para o operador quando um agente esta no board sem hook instalado.

    Nao basta o hook estar ausente: sem sessao daquele agente nao ha nada a avisar. E
    nao basta a sessao existir: com hook instalado o estado vem por evento e o silencio
    e informacao legitima. O aviso e a interseccao dos dois, que e exatamente o caso em
    que o painel exibiria `?` para tudo sem dizer por que.
    """
    rotulos = (("claude", "Claude Code", "install_hook.py"),
               ("codex", "Codex", "install_codex_hook.py"))
    return ["hook do {} nao instalado e ha sessao dele no board: os estados virao como "
            "'?'. Rode `python tools/{}` e reinicie as sessoes.".format(nome, script)
            for tool, nome, script in rotulos
            if not health.get(tool) and any(s["tool"] == tool for s in sessions)]


def build_payload_v1(claude_dir: Path, codex_index: Path, max_sessions: int,
                     tz: timezone, now: datetime | None = None,
                     hidden: set | None = None, pinned: set | None = None,
                     opencode_db: Path | None = None,
                     opencode_ctx_window: int = 0) -> dict:
    """Payload legÃ­vel pelo firmware v1 durante a migraÃ§Ã£o do protocolo.

    `opencode_db=None` desliga a coleta do OpenCode (tests hermeticos); o daemon
    passa o caminho real (padrao do usuario ou --opencode-db)."""
    now = now or datetime.now(timezone.utc)
    dismissed = load_dismissed()
    hidden = hidden or set()
    pinned = pinned or set()

    token_since = now - timedelta(seconds=SESSION_TOKEN_WINDOW_S)
    todas = (scan_claude_sessions(claude_dir, now)
             + scan_codex_sessions(codex_index, now, token_since))
    if opencode_db is not None:
        todas += scan_opencode_sessions(now, token_since, database=opencode_db,
                                        ctx_window=opencode_ctx_window)
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
    _previous_board_ids = [s["id"] for s in top]
    no_board = {s["id"] for s in top}
    for s in top:
        s.pop("_age", None)

    # Catalogo do seletor: tudo que existe e nao esta no board, inclusive o que foi
    # escondido por engano — e justamente assim que se traz um card de volta.
    catalogo = [s for s in todas if s["id"] not in no_board]
    catalogo.sort(key=lambda s: s["_age"])
    catalogo = [{"id": s["id"], "name": s["full"][:25],
                 "provider": s.get("provider", ""), "tool": s["tool"], "state": s["state"]}
                for s in catalogo[:CATALOG_MAX]]

    usage = collect_usage(claude_dir, tz, now)
    return {
        "generated_at": now.isoformat(),
        "generated_at_epoch": int(now.timestamp()),
        "sessions": top,
        "catalog": catalogo,
        "stats": {
            "tokens_today": usage["tokens_today"],
            "spark": usage["spark"],
            "spark_end_hour": usage["spark_end_hour"],
            "active_12h": (count_active_12h(claude_dir, codex_index, now)
                           + (count_opencode_12h(opencode_db, now, ACTIVE_WINDOW_S)
                              if opencode_db is not None else 0)),
            "token_window_h": SESSION_TOKEN_WINDOW_H,
            "total_sessions": total,
            "quota": collect_quota(claude_dir, now),
        },
    }


# Compatibilidade para integraÃ§Ãµes Python existentes; o daemon usa os builders versionados.
build_payload = build_payload_v1


def build_payload_v2(claude_dir: Path, codex_index: Path, max_sessions: int,
                     tz: timezone, *, node_id: str, device_id: str,
                     daemon_instance_id: str, sequence: int,
                     now: datetime | None = None, hidden: set | None = None,
                     pinned: set | None = None, opencode_db: Path | None = None,
                     opencode_ctx_window: int = 0) -> dict:
    """Projeta os dados normalizados atuais no envelope estÃ¡vel do protocolo v2."""
    generated = now or datetime.now(timezone.utc)
    v1 = build_payload_v1(claude_dir, codex_index, max_sessions, tz, generated,
                          hidden=hidden, pinned=pinned, opencode_db=opencode_db,
                          opencode_ctx_window=opencode_ctx_window)
    legacy_stats = v1["stats"]
    series = collect_series(claude_dir, CODEX_SESSIONS, tz, generated)
    usage = {"series": [{"provider": item.provider, "buckets": dict(item.buckets),
                           "total": item.total, "quality": item.quality}
                          for item in series],
             "active_12h": legacy_stats["active_12h"],
             "token_window_h": legacy_stats["token_window_h"],
             "total_sessions": legacy_stats["total_sessions"]}
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
        tag = {"claude": "CL", "codex": "CX", "opencode": "OC"}.get(s["tool"], "??")
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


def add_arguments(ap: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add daemon flags to either the legacy parser or the unified CLI."""
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--interval", type=float, default=None)
    ap.add_argument("--claude-dir", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--codex-index", default=str(Path.home() / ".codex" / "session_index.jsonl"))
    ap.add_argument("--opencode-db", default=None,
                    help="caminho do opencode.db (padrao: ~/.local/share/opencode/opencode.db)")
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

    # Relido a cada ciclo de proposito: os arquivos de hook sao globais e outra
    # ferramenta pode reescreve-los com o daemon ja rodando — foi assim que aconteceu.
    avisos_anteriores: list = []

    while True:
        hidden = fetch_id_list(base, "/hidden", "hidden", token=transport_token)
        pinned = fetch_id_list(base, "/pinned", "pinned", token=transport_token)
        opencode_db = (Path(args.opencode_db) if getattr(args, "opencode_db", None)
                       else opencode_default_db())
        ctx_window = config.usage.opencode_context_window
        if args.protocol == 1:
            payload = build_payload_v1(claude_dir, codex_index, args.max_sessions, tz,
                                       hidden=hidden, pinned=pinned,
                                       opencode_db=Path(opencode_db) if opencode_db else None,
                                       opencode_ctx_window=ctx_window)
            st = payload["stats"]
        else:
            sequence += 1
            payload = build_payload_v2(
                claude_dir, codex_index, args.max_sessions, tz, node_id=node_id,
                device_id=device_id, daemon_instance_id=daemon_instance_id,
                sequence=sequence, hidden=hidden, pinned=pinned,
                opencode_db=Path(opencode_db) if opencode_db else None,
                opencode_ctx_window=ctx_window)
            st = payload["stats"]["usage"]
        today_tokens = usage_total_for_log(st)
        status = post_sessions(url, payload, timeout=config.transport.timeout_s,
                               token=transport_token)
        if status == 422 and any(s.get("tool") == "opencode"
                                 for s in payload.get("sessions", [])):
            # Firmware sem suporte a "opencode" rejeita o POST inteiro (422) — melhor
            # degradar para Claude/Codex do que derrubar o painel. Avisa uma vez so:
            # repetir a cada ciclo vira ruido (mesma regra dos avisos de hook).
            # Timeout/erro de rede NAO cai aqui (status 0): reenviar sem OpenCode
            # nesse caso atrasaria o ciclo e imprimiria um aviso falso.
            if not getattr(run, "_opencode_fallback_warned", False):
                print("[daemon] AVISO: firmware nao aceita sessoes OpenCode (422); "
                      "reenviando sem elas. Compile e grave o firmware novo "
                      "(pio run -t upload) para exibir OpenCode com icone por modelo.",
                      file=sys.stderr)
                run._opencode_fallback_warned = True
            if args.protocol == 1:
                payload = build_payload_v1(claude_dir, codex_index, args.max_sessions,
                                           tz, hidden=hidden, pinned=pinned)
                st = payload["stats"]
            else:
                payload = build_payload_v2(
                    claude_dir, codex_index, args.max_sessions, tz, node_id=node_id,
                    device_id=device_id, daemon_instance_id=daemon_instance_id,
                    sequence=sequence, hidden=hidden, pinned=pinned)
                st = payload["stats"]["usage"]
            today_tokens = usage_total_for_log(st)
            status = post_sessions(url, payload, timeout=config.transport.timeout_s,
                                   token=transport_token)
        ok = 200 <= status < 300

        # So imprime quando o diagnostico MUDA: repetir o mesmo aviso a cada 5s vira
        # ruido e o operador para de ler justamente a linha que importa.
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
            today_tokens, format_summary(payload)))

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
