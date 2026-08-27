#!/usr/bin/env python3
"""Reducer pequeno e determinístico para estados vindos de eventos estruturados."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

VALID_STATES = frozenset({"work", "ask", "perm", "free", "ended"})
MAX_FUTURE_SKEW_S = 30.0


def parse_aware_timestamp(value) -> datetime | None:
    """Aceita apenas ISO-8601 com timezone; nunca assume fuso silenciosamente."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    state: str
    state_since: datetime | None
    last_event_at: datetime | None
    age_s: int | None
    stale: bool
    ended: bool
    transitions: tuple[str, ...]
    diagnostics: tuple[str, ...]


def reduce_session_events(session_id: str, events: Iterable[dict],
                          now: datetime | None = None,
                          stale_after_s: float | None = 90.0) -> SessionSnapshot:
    """Reduz eventos na ordem recebida e rejeita regressões temporais.

    `stale` não altera o último estado conhecido: ele declara que esse estado virou
    histórico. Assim um comando longo nunca se transforma artificialmente em `ask`,
    `perm` ou `free`.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now precisa conter timezone")
    now = now.astimezone(timezone.utc)

    state = "free"
    state_since = None
    last_at = None
    ended = False
    transitions: list[str] = []
    diagnostics: list[str] = []

    for raw in events:
        if str(raw.get("session_id") or "") != session_id:
            continue
        event_state = str(raw.get("state") or "").lower()
        if event_state not in VALID_STATES:
            diagnostics.append("invalid_state")
            continue
        occurred_at = parse_aware_timestamp(raw.get("timestamp"))
        if occurred_at is None:
            diagnostics.append("invalid_timestamp")
            continue
        if (occurred_at - now).total_seconds() > MAX_FUTURE_SKEW_S:
            diagnostics.append("future_timestamp")
            continue
        if last_at is not None and occurred_at < last_at:
            diagnostics.append("out_of_order")
            continue

        next_state = "free" if event_state == "ended" else event_state
        if next_state != state or not transitions:
            state_since = occurred_at
        state = next_state
        ended = event_state == "ended"
        last_at = occurred_at
        transitions.append(event_state)

    if last_at is None:
        return SessionSnapshot(session_id, "free", None, None, None, True, False,
                               tuple(), tuple(diagnostics))

    age_s = max(0, int((now - last_at).total_seconds()))
    stale = stale_after_s is not None and age_s > stale_after_s
    return SessionSnapshot(session_id, state, state_since, last_at, age_s, stale,
                           ended, tuple(transitions), tuple(diagnostics))
