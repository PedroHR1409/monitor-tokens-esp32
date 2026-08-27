#!/usr/bin/env python3
"""
Cota de uso dos dois agentes, lida so de arquivos locais.

A assimetria entre os dois e o ponto central deste modulo, e ela e real:

* **Codex — numero oficial.** Cada evento `token_count` do rollout carrega o bloco
  `rate_limits` que o SERVIDOR devolveu, com `used_percent` e `resets_at` prontos.
  Nao ha inferencia nenhuma: e a mesma cota que o `codex` mostra no terminal.

* **Claude — estimativa.** Varri `~/.claude` inteiro: nao existe `used_percent`,
  `utilization` nem `five_hour` em disco. O unico campo de cota e `quotaLimits`, que
  so aparece com `"status":"rejected"` — ou seja, DEPOIS de voce ja ter sido
  bloqueado. Serve para dizer "quando volta", nunca para avisar "esta acabando".
  Entao o maximo honesto e o CONSUMO somado dos transcripts. Consumo nao e cota: sem
  saber o teto do plano, virar percentual seria inventar denominador.

Por isso o percentual do Claude so aparece se voce declarar o teto em
`MONITOR_CLAUDE_5H_BUDGET` (tokens na janela de 5h). Sem ele, o valor vai como
tokens absolutos e a tela rotula "estimado". Um numero calibrado por voce continua
sendo estimativa, mas pelo menos e uma estimativa cujo denominador voce escolheu.

Janela de 5h: e a janela curta do Codex (`window_minutes == 300`) e a mesma cadencia
do bloco do Claude, o que deixa os dois cards comparaveis lado a lado.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from session_meta import CODEX_SESSIONS
from session_state import parse_ts
from usage_tracker import _iter_today_events, dedup_tokens

# Classificacao das janelas pelo tamanho declarado, NUNCA pela posicao em
# primary/secondary. Medido nos rollouts reais: o mesmo campo `primary` ja veio com
# 300 (5h) num evento e 10080 (semanal) em outro, e `secondary` as vezes e null. Casar
# por `window_minutes` e a unica leitura que sobrevive as duas formas.
WINDOW_5H_MIN = 300
WINDOW_WEEK_MIN = 10080

# Rollouts chegam a 2 MB e a cota e global da conta: nao adianta varrer todos. O bloco
# `rate_limits` e reescrito a cada turno, entao o fim dos arquivos mais recentes tem o
# valor mais fresco.
QUOTA_TAIL_BYTES = 128 * 1024
QUOTA_ROLLOUTS = 3

CLAUDE_WINDOW_H = 5
CLAUDE_WINDOW_S = CLAUDE_WINDOW_H * 3600


def claude_budget() -> int:
    """Teto de tokens da janela de 5h declarado pelo usuario. 0 = nao declarado."""
    try:
        return max(0, int(os.environ.get("MONITOR_CLAUDE_5H_BUDGET", "0")))
    except ValueError:
        return 0


def _empty_codex() -> dict:
    return {"ok": False, "h5_pct": 0, "week_pct": 0, "h5_reset": 0,
            "week_reset": 0, "plan": "", "credits": "", "age_s": 0}


def _windows_of(rl: dict):
    """Todos os buckets de janela de um bloco `rate_limits`, sem assumir a chave."""
    for name in ("primary", "secondary"):
        win = rl.get(name)
        if isinstance(win, dict):
            yield win


def _window_is_current(win_minutes: int, resets_at, event_ts: float,
                       now_ts: float) -> bool:
    """A janela descrita por esse evento ainda e a janela de agora?

    Sem esta checagem, ficar dias sem abrir o Codex faria o painel exibir com toda a
    confianca o percentual da semana passada. O criterio sai do proprio dado: se
    `resets_at` ja passou, aquela janela virou e o `used_percent` descreve um periodo
    encerrado. Sem `resets_at`, resta a idade do evento — um numero de 5h medido ha
    mais de 5h fala de uma janela que ja rolou.
    """
    if resets_at:
        return float(resets_at) > now_ts
    return event_ts > 0 and (now_ts - event_ts) < win_minutes * 60


def _tail_lines(path: Path, nbytes: int) -> list:
    """Ultimas linhas COMPLETAS do arquivo. A primeira e descartada porque o corte em
    offset fixo quase sempre cai no meio de uma linha (e pode partir um UTF-8)."""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            f.seek(max(0, size - nbytes))
            raw = f.read()
    except OSError:
        return []
    lines = raw.split(b"\n")
    if size > nbytes and lines:
        lines = lines[1:]
    return lines


def codex_quota(sessions_dir: Path | None = None,
                now: datetime | None = None) -> dict:
    """Cota oficial do Codex: {'ok', 'h5_pct', 'week_pct', resets, 'plan', 'credits'}.

    Percorre os rollouts mais recentes e fica com o `rate_limits` de maior timestamp
    que tenha cada janela. Um evento pode trazer so a semanal (o outro bucket vem
    null), entao as duas janelas sao resolvidas de forma independente — e cada uma
    passa por `_window_is_current`, para que um rollout parado ha dias nao entregue o
    percentual de uma janela ja encerrada como se fosse o de agora.
    """
    base = sessions_dir if sessions_dir is not None else CODEX_SESSIONS
    now_ts = (now or datetime.now(timezone.utc)).timestamp()
    if not base.is_dir():
        return _empty_codex()

    try:
        rollouts = sorted(base.rglob("rollout-*.jsonl"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return _empty_codex()

    best_h5 = best_week = best_meta = None   # (timestamp, valor)

    for path in rollouts[:QUOTA_ROLLOUTS]:
        for raw in _tail_lines(path, QUOTA_TAIL_BYTES):
            if b"rate_limits" not in raw:
                continue                      # filtro barato antes do json.loads
            try:
                obj = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            payload = obj.get("payload")
            if not isinstance(payload, dict):
                continue
            rl = payload.get("rate_limits")
            if not isinstance(rl, dict):
                continue
            ts = parse_ts(obj.get("timestamp"))
            key = ts.timestamp() if ts else 0.0

            for win in _windows_of(rl):
                pct = win.get("used_percent")
                if not isinstance(pct, (int, float)) or isinstance(pct, bool):
                    continue
                minutes = win.get("window_minutes")
                if minutes not in (WINDOW_5H_MIN, WINDOW_WEEK_MIN):
                    continue
                resets_at = int(win.get("resets_at") or 0)
                if not _window_is_current(minutes, resets_at, key, now_ts):
                    continue          # janela ja virou: o percentual e de outro periodo
                entry = (key, round(float(pct)), resets_at)
                if minutes == WINDOW_5H_MIN:
                    if best_h5 is None or key >= best_h5[0]:
                        best_h5 = entry
                elif best_week is None or key >= best_week[0]:
                    best_week = entry

            if rl.get("plan_type") and (best_meta is None or key >= best_meta[0]):
                credits = rl.get("credits")
                balance = ""
                if isinstance(credits, dict) and credits.get("balance") is not None:
                    # Vem com 10 casas decimais ("93.8120090000"); a tela tem 96px.
                    try:
                        balance = f"{float(credits['balance']):.2f}"
                    except (TypeError, ValueError):
                        balance = str(credits["balance"])[:12]
                best_meta = (key, str(rl["plan_type"]), balance)

    if best_h5 is None and best_week is None:
        return _empty_codex()

    # Idade da LEITURA, que e diferente de "a janela ainda nao virou". Dentro da mesma
    # janela de 5h o percentual anda rapido: medido 37% as 15:04 e 100% as 18:11 do
    # mesmo dia. Se o Codex nao esta rodando no CLI, o rollout para de crescer e o
    # ultimo numero envelhece sem nenhum sinal — foi assim que o painel exibiu 37% com
    # tres horas de atraso. Quem consome decide o que fazer com a idade; aqui ela so
    # nao pode ficar escondida.
    read_at = (best_h5 or best_week)[0]
    age_s = max(0, int(now_ts - read_at)) if read_at else 0

    return {
        "ok": True,
        "h5_pct": best_h5[1] if best_h5 else 0,
        "h5_reset": best_h5[2] if best_h5 else 0,
        "week_pct": best_week[1] if best_week else 0,
        "week_reset": best_week[2] if best_week else 0,
        "plan": best_meta[1] if best_meta else "",
        "credits": best_meta[2] if best_meta else "",
        "age_s": age_s,
    }


def claude_consumption(projects_dir: Path, now: datetime | None = None,
                       budget: int | None = None) -> dict:
    """Consumo estimado do Claude na janela de 5h: {'ok', 'tokens', 'pct', 'budget'}.

    `pct` so e preenchido se houver teto declarado; 0 significa "sem denominador",
    e a tela mostra os tokens em vez de um percentual inventado.
    """
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(seconds=CLAUDE_WINDOW_S)
    since_ts = since.timestamp()
    budget = claude_budget() if budget is None else budget

    if not projects_dir.is_dir():
        return {"ok": False, "tokens": 0, "pct": 0, "budget": budget}

    total = 0
    # Uma mensagem vira varias linhas no transcript, uma por bloco de conteudo, todas
    # com o mesmo `usage`. Sem deduplicar por message.id o consumo saia 2,4x maior.
    vistos: set = set()
    for project in projects_dir.iterdir():
        if not project.is_dir():
            continue
        for path in project.glob("*.jsonl"):
            try:
                if path.stat().st_mtime < since_ts:
                    continue          # nao foi tocado na janela: pula sem abrir
            except OSError:
                continue
            try:
                for obj, _ in _iter_today_events(path, since):
                    total += dedup_tokens(vistos, obj)
            except OSError:
                continue

    pct = min(999, round(100 * total / budget)) if budget > 0 else 0
    return {"ok": True, "tokens": total, "pct": pct, "budget": budget}


def collect(projects_dir: Path, now: datetime | None = None,
            sessions_dir: Path | None = None) -> dict:
    """Bloco `quota` do payload: o oficial e o estimado, cada um marcado como tal."""
    cx = codex_quota(sessions_dir, now)
    cl = claude_consumption(projects_dir, now)
    return {
        "window_h": CLAUDE_WINDOW_H,
        "codex": {
            "ok": cx["ok"],
            "official": True,
            "h5_pct": cx["h5_pct"],
            "week_pct": cx["week_pct"],
            "h5_reset": cx["h5_reset"],
            "week_reset": cx["week_reset"],
            "plan": cx["plan"],
            "credits": cx["credits"],
            "age_s": cx["age_s"],
        },
        "claude": {
            "ok": cl["ok"],
            "official": False,
            "tokens": cl["tokens"],
            "pct": cl["pct"],
        },
    }
