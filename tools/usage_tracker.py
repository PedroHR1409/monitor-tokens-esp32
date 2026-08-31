#!/usr/bin/env python3
"""
Tokens consumidos hoje + histograma por hora (sparkline de 12h) do Monitor.AI.

Fonte: os proprios transcripts do Claude Code, que ja trazem o bloco `usage` de cada
turno do assistant (input/output/cache). Nao usa nenhuma API de billing/admin —
requisito explicito do usuario.

Desafio de performance: os transcripts somam ~100 MB. Reler tudo a cada ciclo
travaria a maquina. Duas otimizacoes tornam isso barato:

  1. Arquivo com mtime anterior ao inicio do dia nao pode conter evento de hoje ->
     e descartado sem abrir. Na pratica isso elimina quase todos os MB.
  2. Nos que sobram, a leitura e de tras pra frente em blocos, parando assim que
     aparece um evento anterior ao inicio do dia.

O dia segue o fuso local configurado (padrao GMT-3), de 00:00 a 23:59.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from session_state import parse_ts
from usage_model import UsageSeries, combine_usage

CHUNK = 256 * 1024      # bloco de leitura reversa
MAX_BACK = 8 * 1024 * 1024   # teto por arquivo, evita varrer um transcript gigante
SPARK_HOURS = 12


def day_start(tz: timezone, now: datetime | None = None) -> datetime:
    """00:00 do dia corrente no fuso pedido, como datetime aware."""
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _iter_today_events(path: Path, since: datetime):
    """Eventos do arquivo com timestamp >= `since`, lendo so o fim necessario."""
    size = path.stat().st_size
    back = 0
    lines: list[bytes] = []
    reached_start = False

    while back < size and back < MAX_BACK and not reached_start:
        back = min(size, back + CHUNK)
        with path.open("rb") as f:
            f.seek(size - back)
            chunk = f.read(back)
        lines = chunk.split(b"\n")
        # Se o primeiro evento datado do bloco ja e anterior a `since`, cobrimos o dia.
        for raw in lines:
            if not raw.strip():
                continue
            try:
                ts = parse_ts(json.loads(raw).get("timestamp"))
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                continue   # linha cortada na borda do bloco (pode partir um UTF-8)
            if ts:
                reached_start = ts < since
                break

    for raw in lines:
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue   # linha cortada na borda do bloco (pode partir um UTF-8)
        ts = parse_ts(obj.get("timestamp"))
        if ts and ts >= since:
            yield obj, ts


def _usage_of(obj: dict) -> tuple:
    """(message.id, tokens novos) do evento. ('', 0) quando nao ha usage.

    Cache read fica de fora de proposito: ele domina o total (centenas de milhares) e
    esconderia a variacao real de uso.

    O id sai junto porque somar entrada por entrada CONTA DUPLICADO. O transcript grava
    uma linha por bloco de conteudo da mesma mensagem — `thinking`, `text`, um
    `tool_use` por ferramenta — e todas repetem o MESMO objeto `usage`. Medido em
    27/08/2026 numa janela de 5h: 1117 entradas para 522 mensagens reais, inflando
    3.714.894 tokens onde havia 1.540.194 (2,4x). Verificado que os 373 grupos
    repetidos tinham usage identico e viviam no mesmo arquivo — e repeticao de
    serializacao, nao consumo real. Quem acumula precisa deduplicar por este id.
    """
    if obj.get("type") != "assistant":
        return "", 0
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return "", 0
    u = msg.get("usage")
    if not isinstance(u, dict):
        return "", 0
    tokens = (int(u.get("input_tokens") or 0)
              + int(u.get("output_tokens") or 0)
              + int(u.get("cache_creation_input_tokens") or 0))
    return str(msg.get("id") or ""), tokens


def dedup_tokens(seen: set, obj: dict) -> int:
    """Tokens do evento, ou 0 se esta mensagem ja foi contada.

    Evento sem `message.id` e contado sem deduplicar: nao da para saber se repete, e
    descartar por precaucao subestimaria o consumo real.
    """
    mid, tokens = _usage_of(obj)
    if not tokens:
        return 0
    if mid:
        if mid in seen:
            return 0
        seen.add(mid)
    return tokens


def collect(projects_dir: Path, tz: timezone,
            now: datetime | None = None) -> dict:
    """{'tokens_today', 'spark' (12 buckets, mais antigo primeiro), 'models'}"""
    now = now or datetime.now(timezone.utc)
    start = day_start(tz, now)
    start_ts = start.timestamp()

    total = 0
    models: dict[str, int] = {}
    buckets = [0] * SPARK_HOURS
    # Global ao dia inteiro, nao por arquivo: a deduplicacao acompanha a soma que ela
    # protege. O balde do heatmap recebe o token na PRIMEIRA ocorrencia da mensagem.
    vistos: set = set()
    # bucket 11 = hora corrente; 0 = 11 horas atras
    spark_base = now.astimezone(tz).replace(minute=0, second=0, microsecond=0)
    spark_start = spark_base - timedelta(hours=SPARK_HOURS - 1)

    if not projects_dir.is_dir():
        return {"tokens_today": 0, "spark": buckets, "models": models,
                "spark_end_hour": spark_base.hour}

    for project in projects_dir.iterdir():
        if not project.is_dir():
            continue
        for path in project.glob("*.jsonl"):
            try:
                if path.stat().st_mtime < start_ts:
                    continue        # nao foi tocado hoje: pula sem abrir
            except OSError:
                continue
            try:
                for obj, ts in _iter_today_events(path, start):
                    tok = dedup_tokens(vistos, obj)
                    if not tok:
                        continue
                    total += tok
                    model = (obj.get("message") or {}).get("model")
                    if model:
                        models[model] = models.get(model, 0) + tok
                    local = ts.astimezone(tz)
                    if local >= spark_start:
                        idx = int((local - spark_start).total_seconds() // 3600)
                        if 0 <= idx < SPARK_HOURS:
                            buckets[idx] += tok
            except OSError:
                continue

    return {"tokens_today": total, "spark": buckets, "models": models,
            "spark_end_hour": spark_base.hour}


def _spark_hours(tz: timezone, now: datetime) -> tuple[datetime, list[str]]:
    """Inícios dos mesmos 12 baldes usados pela tela, em formato estável."""
    base = now.astimezone(tz).replace(minute=0, second=0, microsecond=0)
    start = base - timedelta(hours=SPARK_HOURS - 1)
    return start, [(start + timedelta(hours=index)).isoformat()
                   for index in range(SPARK_HOURS)]


def claude_series(projects_dir: Path, tz: timezone,
                  now: datetime | None = None) -> UsageSeries:
    """Uso Claude com a sua proveniência, sem o chamar de uso combinado."""
    observed = now or datetime.now(timezone.utc)
    legacy = collect(projects_dir, tz, observed)
    _, hours = _spark_hours(tz, observed)
    return UsageSeries("claude", dict(zip(hours, legacy["spark"])),
                       legacy["tokens_today"], "measured")


def _rollout_total_events(path: Path):
    """Pares (timestamp, total acumulado) que o rollout do Codex publica."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = obj.get("payload")
                info = payload.get("info") if isinstance(payload, dict) else None
                usage = info.get("total_token_usage") if isinstance(info, dict) else None
                if not isinstance(usage, dict) or usage.get("total_tokens") is None:
                    continue
                timestamp = parse_ts(obj.get("timestamp"))
                if timestamp is None:
                    continue
                try:
                    yield timestamp, max(int(usage["total_tokens"]), 0)
                except (TypeError, ValueError):
                    continue
    except OSError:
        return


def codex_series(rollouts_dir: Path, tz: timezone,
                 now: datetime | None = None) -> UsageSeries | None:
    """Converte contadores acumulados dos rollouts Codex em deltas diários/horários."""
    if not rollouts_dir.is_dir():
        return None
    observed = now or datetime.now(timezone.utc)
    start = day_start(tz, observed)
    start_epoch = start.timestamp()
    spark_start, hours = _spark_hours(tz, observed)
    buckets = {hour: 0 for hour in hours}
    total = 0
    found = False
    try:
        rollouts = rollouts_dir.rglob("rollout-*.jsonl")
        for path in rollouts:
            try:
                if path.stat().st_mtime < start_epoch:
                    continue
            except OSError:
                continue
            events = sorted(_rollout_total_events(path), key=lambda item: item[0])
            if not events:
                continue
            found = True
            previous = None
            for timestamp, cumulative in events:
                if timestamp < start:
                    previous = cumulative
                    continue
                # Um contador menor indica reinício do rollout; o novo acumulado ainda
                # é uso real desta janela, não um delta negativo a descartar.
                delta = (cumulative if previous is None or cumulative < previous
                         else cumulative - previous)
                previous = cumulative
                total += delta
                local = timestamp.astimezone(tz)
                if local >= spark_start:
                    index = int((local - spark_start).total_seconds() // 3600)
                    if 0 <= index < SPARK_HOURS:
                        buckets[hours[index]] += delta
    except OSError:
        return None
    if not found:
        return None
    return UsageSeries("codex", buckets, total, "measured")


def collect_series(projects_dir: Path, rollouts_dir: Path, tz: timezone,
                   now: datetime | None = None) -> tuple[UsageSeries, ...]:
    """Séries visíveis ao daemon; só combina fontes com os mesmos baldes horários."""
    observed = now or datetime.now(timezone.utc)
    claude = claude_series(projects_dir, tz, observed)
    codex = codex_series(rollouts_dir, tz, observed)
    return combine_usage(claude, *(item for item in (codex,) if item is not None))


# Cache por (arquivo, tamanho): recalcular a soma de 24h de um transcript de varios MB a
# cada ciclo de 5s seria desperdicio. Se o arquivo nao cresceu, o valor nao mudou.
_session_cache: dict = {}


def session_tokens(path: Path, since: datetime) -> int:
    """Tokens consumidos por UMA sessao desde `since` (usado para a janela de 24h da
    tela de detalhe)."""
    try:
        st = path.stat()
    except OSError:
        return 0
    key = (str(path), st.st_size, int(st.st_mtime), since.isoformat())
    hit = _session_cache.get(key)
    if hit is not None:
        return hit

    total = 0
    vistos: set = set()
    try:
        for obj, _ in _iter_today_events(path, since):
            total += dedup_tokens(vistos, obj)
    except OSError:
        return 0

    if len(_session_cache) > 64:      # limite defensivo: nao virar vazamento
        _session_cache.clear()
    _session_cache[key] = total
    return total
