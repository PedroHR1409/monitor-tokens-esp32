"""Severidade do alerta: uma regra, um lugar, coberta por teste.

Os limiares chegam do monitor.toml (ja validados por monitor_config, que garante
critical_after_s >= warning_after_s -- esta funcao nao precisa se defender disso).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# Importado, NAO redefinido: a vida da marca de perm tem um dono so
# (session_state.py:58). Duas copias divergiriam na primeira mudanca.
from session_state import PERM_MARKER_MAX_AGE_S

# Ordem de urgencia. `critical` supera `expired` porque e sinal exato vivo: uma
# admissao de ignorancia nao deve gritar mais alto que um sinal valido.
SEVERITY_ORDER: tuple[str, ...] = ("none", "warning", "expired", "critical")

# So estado que bloqueia o agente escala. `work` e `free` nunca alertam.
ALERTING_STATES = frozenset({"ask", "perm"})

# Marca de perm velha demais para afirmar, mas nova demais para ignorar. 2x
# PERM_MARKER_MAX_AGE_S. Passado isso, evidencia morta: uma marca orfa (Claude
# Code morreu com o dialogo aberto) produziria alerta eterno.
EXPIRED_MAX_AGE_S = 1200.0


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Limiares em segundos, vindos de AlertSettings."""
    warning_after_s: int
    critical_after_s: int


def thresholds_from(alerts) -> Thresholds:
    """Converte AlertSettings (monitor_config.py) em Thresholds.

    Existe so para o daemon nao precisar conhecer os nomes dos campos de
    AlertSettings em dois lugares -- se o config ganhar um campo novo (ex:
    snooze_minutes), este e o unico ponto que teria que mudar junto.
    """
    return Thresholds(warning_after_s=alerts.warning_after_s,
                      critical_after_s=alerts.critical_after_s)


def severity_for(state: str, elapsed_s: float, *, structured: bool,
                 perm_marker_age_s: float | None,
                 thresholds: Thresholds) -> str:
    """Severidade de UMA sessao. Pura: mesma entrada, mesma saida, sempre.

    `structured` = o estado veio de evento de hook (exato). Estado inferido tem
    teto em `warning` e nunca dispara toast -- mesma cultura de procedencia
    explicita da cota (ver tools/quota.py).

    `perm_marker_age_s` = idade da marca deixada pelo hook PermissionRequest, ou
    None quando nao ha marca. Marca entre PERM_MARKER_MAX_AGE_S e
    EXPIRED_MAX_AGE_S produz `expired`: o painel admite que nao sabe em vez de
    voltar para `free` em silencio.
    """
    if perm_marker_age_s is not None and perm_marker_age_s > PERM_MARKER_MAX_AGE_S:
        return "expired" if perm_marker_age_s <= EXPIRED_MAX_AGE_S else "none"
    if state not in ALERTING_STATES:
        return "none"
    if elapsed_s < thresholds.warning_after_s:
        return "none"
    if elapsed_s < thresholds.critical_after_s:
        return "warning"
    return "warning" if not structured else "critical"


def worst_severity(severities: Iterable[str]) -> str:
    """Pulso e global: a pior severidade manda (espelha STATE_PRIORITY).

    Vocabulario fechado, falha segura: uma severidade desconhecida NAO pode
    derrubar o daemon com ValueError vindo de SEVERITY_ORDER.index (e o que
    `max(..., key=SEVERITY_ORDER.index)` faria sem esta guarda). Segue a mesma
    convencao de parse_state/parse_tool no firmware -- valor fora do
    vocabulario cai para o mais neutro (`none`) em vez de propagar excecao.
    """
    ranked = [s for s in severities if s in SEVERITY_ORDER]
    return max(ranked, key=SEVERITY_ORDER.index, default="none")
