"""Modelos de uso com fonte e qualidade explícitas."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class UsageSeries:
    """Uso de um provedor, indexado pelo começo ISO-8601 de cada hora."""

    provider: str
    buckets: Mapping[str, int]
    total: int
    quality: str


def combine_usage(*series: UsageSeries) -> tuple[UsageSeries, ...]:
    """Combina somente séries que descrevem exatamente o mesmo período.

    Sem uma série Codex, a série Claude continua explicitamente Claude. Períodos
    distintos também não são alinhados por posição: isso inventaria uma hora comum.
    """
    if len(series) < 2:
        return tuple(series)
    first = series[0]
    if (any(item.quality != first.quality for item in series)
            or any(set(item.buckets) != set(first.buckets) for item in series[1:])):
        return tuple(series)
    buckets = {key: sum(item.buckets[key] for item in series) for key in first.buckets}
    providers = "+".join(item.provider for item in series)
    return (UsageSeries(providers, buckets, sum(item.total for item in series), first.quality),)


def context_measurement(tokens: int, *, measured_limit: int | None = None,
                        configured_limit: int | None = None) -> dict:
    """Retorna contexto atual sem transformar um limite ausente em porcentagem."""
    current = max(int(tokens or 0), 0)
    measured = max(int(measured_limit or 0), 0)
    configured = max(int(configured_limit or 0), 0)
    if measured:
        limit, quality = measured, "measured"
    elif configured:
        limit, quality = configured, "configured"
    else:
        return {"tokens": current, "limit": None, "pct": 0, "quality": "unknown"}
    return {"tokens": current, "limit": limit,
            "pct": min(100, round(100 * current / limit)), "quality": quality}
