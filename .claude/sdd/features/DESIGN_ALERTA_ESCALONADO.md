# DESIGN: Alerta escalonado + snooze + toast no PC

> Severidade nasce no daemon como função pura; o firmware traduz em pulso de backlight;
> o snooze mora na placa e volta ao daemon pelo mesmo caminho de `hidden`/`pinned`

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | ALERTA_ESCALONADO |
| **Date** | 2026-09-08 |
| **Author** | design-agent |
| **Status** | ✅ Complete (Built) |
| **Input** | `.claude/sdd/features/DEFINE_ALERTA_ESCALONADO.md` (clareza 15/15) |
| **Abordagem** | Approach A do brainstorm — daemon decide severidade, firmware decide estética |
| **Confiança (daemon)** | **0.95** — KB `python`/`testing` carregada + `@python-developer` e `@test-generator` disponíveis |
| **Confiança (firmware)** | **0.80** — nenhuma KB cobre LVGL/embedded e não existe agente C++; padrões extraídos do próprio codebase, verificados arquivo por arquivo |

---

## Architecture Overview

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                        PC (daemon, Python stdlib)                             │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  monitor.toml [alerts]                                                        │
│  warning_after_s / critical_after_s / snooze_minutes                          │
│         │  (já parseado e validado por monitor_config — nada a mudar)         │
│         ▼                                                                     │
│  ┌──────────────────────┐      state, elapsed, structured, perm_marker_age    │
│  │  alert_severity.py   │◄────────────────────────────────────────────┐       │
│  │  (função PURA)       │                                             │       │
│  │  severity_for()      │                              ┌──────────────┴─────┐ │
│  │  worst_severity()    │                              │ scan_*_sessions()  │ │
│  └──────┬───────────────┘                              │ (já existente)     │ │
│         │ none|warning|critical|expired                 └────────────────────┘ │
│         ▼                                                                     │
│  ┌──────────────────────┐  severity=="critical" e sem snooze  ┌─────────────┐ │
│  │  session_daemon.py   ├────────────────────────────────────► │ notify.py   │ │
│  │  build_payload_v1/v2 │  1× por (id, estado)                │ subprocess  │ │
│  └──────┬───────────────┘                                      └──────┬──────┘ │
│         │ POST /sessions                          GET /snooze         │        │
│         │ (+ campo aditivo "severity")            (segundos restantes)│        │
└─────────┼──────────────────────────────────────────────▲──────────────┼────────┘
          │                                              │              ▼
          │                                              │      ┌───────────────┐
          │                                              │      │ PowerShell /  │
          │                                              │      │ notify-send   │
          │                                              │      └───────────────┘
┌─────────▼──────────────────────────────────────────────┴───────────────────────┐
│                        ESP32-S3 (firmware)                                      │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  session_transport.cpp ──► SessionData.severity  ──► worst_severity()           │
│         │                                                    │                  │
│         │  snooze.cpp (NVS)                                  │                  │
│         │  snooze_until ◄── toque no header (ui_dashboard)    │                  │
│         │         │                                          │                  │
│         │         └── ativo? ──► severidade forçada a NONE ───┤                  │
│         │                                                    ▼                  │
│         │                                     ┌──────────────────────────────┐  │
│         │                                     │ device_time.cpp              │  │
│         │  apply_schedule (30s) ──► s_base ──►│ pulse_tick(sev, now)  ~70ms  │  │
│         │  (dia 255 / noite 60)               │ triangular, sem float        │  │
│         │                                     └──────────┬───────────────────┘  │
│         │                                                ▼                      │
│         │                                     ledcWrite(PIN_LCD_BACKLIGHT)      │
│         │                                     ZERO invalidação LVGL             │
│         ▼                                                                       │
│  ui_dashboard.cpp: card `expired` (roxo + "perm?"), relógio "· mudo 12m",        │
│                    borda de alerta ESTÁTICA (deixa de pulsar — ver Decisão 4)    │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| `alert_severity.py` | Função pura `(estado, elapsed, procedência, idade da marca) → severidade` + agregação pela pior | Python 3.10+ stdlib; `@dataclass(frozen=True, slots=True)` (KB `python/concepts/dataclasses.md`) |
| `notify.py` | Toast nativo por `subprocess`; `available()` para o `doctor` | Python stdlib (`subprocess`, `shutil`, `sys`) |
| `session_daemon.py` (mod.) | Injeta `severity` no payload, lê `GET /snooze`, dispara toast 1× por par | Python stdlib |
| `doctor.py` (mod.) | Checagem do canal de notificação (valida A-003 na máquina real) | Python stdlib |
| `snooze.{h,cpp}` | `snooze_until` persistido em NVS; segundos restantes | C++ / `Preferences` (padrão de `id_list.cpp`) |
| `device_time.{h,cpp}` (mod.) | `s_base` pelo horário + `device_backlight_pulse_tick()` triangular | C++ / LEDC PWM |
| `session_transport.cpp` (mod.) | Parse de `severity`, `GET /snooze`, `POST /snooze/clear`, campos no `/diag` | C++ / WebServer + ArduinoJson |
| `ui_dashboard.cpp` (mod.) | Header clicável, indicação de mudo, card `expired`, borda estática | C++ / LVGL 9 |
| `main.cpp` (mod.) | Tick de ~70ms chamando `pulse_tick` | C++ |

---

## Key Decisions

### Decision 1: A severidade é calculada no daemon e viaja como campo aditivo

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-08 |

**Context:** Os limiares moram no `monitor.toml` (PC) e o toast nasce no PC, mas o pulso
acontece na placa. Alguém tem que decidir onde a regra vive — e a mesma regra em dois
lugares é a divergência config↔código que esta feature existe para corrigir.

**Choice:** `alert_severity.py` calcula a severidade no daemon; o valor viaja como campo
`severity` por sessão no `POST /sessions`; o firmware só traduz severidade em parâmetros
de pulso.

**Rationale:** A regra passa a existir **uma única vez**, em Python, coberta por
`unittest`. Mudar `critical_after_s` no TOML muda o comportamento em ≤1 ciclo (~5s) sem
reflash — que é um critério de sucesso do DEFINE. O contrato continua falando vocabulário
de domínio ("severidade"), não de apresentação ("brilho 180"), respeitando a regra 3 do
`CLAUDE.md`. E a retrocompatibilidade está **verificada**, não suposta:
`handle_sessions_post` (`session_transport.cpp:222-285`) valida `id`, `state`, `tool` e
`elapsed` por whitelist e ignora qualquer campo extra.

**Alternatives Rejected:**
1. **Firmware calcula com limiares em `config.h`** — rejeitado porque trocar um limiar exigiria reflash e o daemon recalcularia a mesma regra de qualquer forma para o toast, duplicando-a em C++ e Python com metade coberta por teste.
2. **Daemon manda amplitude e período prontos** — rejeitado porque acopla o protocolo à UI: toda mudança visual viraria mudança de protocolo.

**Consequences:**
- Aceito: um campo novo no protocolo e um endpoint novo no firmware.
- Ganho: regra única e testável; limiar ajustável sem reflash; firmware dono da estética.

---

### Decision 2: `expired` decai para `none` após 20 minutos — e isso refina o DEFINE

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted — **com tensão registrada** |
| **Date** | 2026-09-08 |

**Context:** A severidade `expired` existe porque a marca de `perm` morre aos 600s
(`PERM_MARKER_MAX_AGE_S`) e o alerta não deve desistir em silêncio. Mas a marca fica órfã
para sempre quando o Claude Code morre com o diálogo aberto — é literalmente o cenário
que a constante protege. Sem limite, uma marca órfã produziria `expired` eterno, logo
pulso eterno. O projeto já pagou por esse erro: a SPEC registra um `perm` falso medido em
**191 horas**, mitigado com decaimento por idade.

**Choice:** `expired` vale enquanto a marca tem menos de `EXPIRED_MAX_AGE_S = 1200s`
(2× a vida da marca). Passado isso, a severidade cai para `none`.

**Rationale:** Reaplica o padrão de mitigação que o projeto já usa três vezes
(`PERM_MARKER_MAX_AGE_S`, `WORK_MAX_AGE_S`, e o `PERM_MAX_AGE_S` histórico da fase 4):
evidência velha demais deixa de sustentar afirmação. O operador recebe 10 minutos de
`critical` mais 10 de `expired` — 20 minutos de sinal para uma permissão que se responde
em minutos. Alerta que não desliga sozinho deixa de ser alerta e vira ruído de fundo.

**Alternatives Rejected:**
1. **Sem limite** — rejeitado: pulso eterno por marca órfã é pior que o bug de 191 horas, porque agora o sintoma é a tela inteira piscando.
2. **Limite igual ao da marca (600s)** — rejeitado: `expired` nasceria já morto, sem janela de sinalização própria.

**Consequences:**
- **Tensão explícita com o DEFINE:** o critério *"`perm` que atinge 600s ainda travado permanece sinalizado em 100% dos casos; 0 quedas silenciosas para `free`"* passa a valer **enquanto a evidência é utilizável** (até 20 min), não indefinidamente. Isso precisa de `/agentspec:iterate` no DEFINE se o operador discordar do recorte.
- Ganho: nenhuma classe de bug de alerta preso.

---

### Decision 3: Agregação pela pior severidade, com `critical` acima de `expired`

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-08 |

**Context:** O backlight é um recurso único e global; a severidade é por sessão.

**Choice:** Ordem `none` < `warning` < `expired` < `critical`; o máximo manda no pulso.

**Rationale:** Espelha o `STATE_PRIORITY` que `session_daemon.py:49` já usa para resolver
a mesma disputa no nível de estado — uma segunda escala de prioridade com regra diferente
seria uma inconsistência gratuita. `critical` fica acima de `expired` porque é sinal exato
vivo, e uma admissão de ignorância não deve gritar mais alto que um sinal válido.

**Alternatives Rejected:**
1. **A sessão mais antiga manda** — rejeitado: um `critical` recém-nascido ficaria abafado por um `warning` velho.
2. **A última a escalar manda** — rejeitado: cadência mudaria sem o operador entender por quê.

**Consequences:**
- Aceito: com duas sessões em severidades diferentes, o pulso não identifica *qual* delas — quem identifica é o card.
- Ganho: uma escala de prioridade só, coerente com a existente.

---

### Decision 4: A borda de alerta para de pulsar; o pulso passa para o backlight

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-08 |

**Context:** `update_alert()` (`ui_dashboard.cpp:1142`) hoje alterna a cor da borda da tela
a cada `ALERT_PERIOD_MS` (600ms), chamando `lv_obj_set_style_border_color` e
`_border_width`. Num render FULL, cada troca invalida a tela — ou seja, **o alerta atual
já custa cerca de 3 frames por segundo**, exatamente o padrão que a fase 4 eliminou nos
textos com os guards `set_text_if`/`set_color_if`.

**Choice:** A borda passa a ser **estática** (cor do pior estado, largura fixa, escrita só
quando a cor muda) e o movimento migra inteiramente para o backlight.

**Rationale:** Duas fontes de pulso competindo produziriam batimento visual sem
significado. Mais importante: mover o movimento para o PWM **reduz** o custo de render em
vez de aumentá-lo, o que faz o critério de sucesso do DEFINE (`maxUpdateMs` não aumenta)
passar com folga em lugar de ficar no limite. A borda continua sendo o "quem/o quê" (cor
do estado); o backlight passa a ser o "quão urgente".

**Alternatives Rejected:**
1. **Manter a borda pulsando e somar o backlight** — rejeitado: dois pulsos independentes batendo entre si, e mantém as ~3 invalidações/s.
2. **Remover a borda por completo** — rejeitado: perderia a única indicação de *cor de estado* em nível de tela.

**Consequences:**
- Aceito: é uma **mudança de comportamento existente**, além da adição de feature — precisa constar na seção nova do `docs/SPEC.md`.
- Ganho: custo de render do alerta cai; linguagem visual fica com um eixo por dimensão.

---

### Decision 5: O snooze viaja como segundos restantes, não como timestamp

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-08 |

**Context:** O snooze nasce na placa (foi o dedo do operador) e o daemon precisa saber
para suprimir o toast. Os dois lados têm relógios independentes.

**Choice:** `GET /snooze` devolve `{"snooze_s": <segundos restantes>}`; zero significa não
silenciado.

**Rationale:** É a mesma escolha que a SPEC seção 5 já justifica para `elapsed` — *"evita
deriva de relógio entre PC e ESP32"*. Duração relativa não tem fuso, não tem skew e não
depende de o NTP ter sincronizado.

**Alternatives Rejected:**
1. **Timestamp absoluto** — rejeitado: reintroduz skew de relógio e exige NTP válido dos dois lados.

**Consequences:**
- Aceito: o daemon não sabe *quando* o mudo começou, só quanto falta (que é tudo o que ele precisa).
- Ganho: nenhuma aritmética de fuso no caminho crítico.

---

### Decision 6: Título e corpo do toast passam por ambiente, nunca por string de shell

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-08 |

**Context:** O nome exibido da sessão vem do campo `cwd` do transcript — um caminho de
sistema de arquivos controlado pelo usuário, que pode conter aspas, `$`, backtick e ponto
e vírgula. Interpolá-lo num comando PowerShell seria injeção de comando.

**Choice:** O script PowerShell é uma constante fixa que lê `$env:MONITOR_TOAST_TITLE` e
`$env:MONITOR_TOAST_BODY`; o Python passa os valores em `env=`. No Linux vão como `argv`
de `notify-send`. Nunca `shell=True`.

**Rationale:** Elimina a classe de bug por construção, em vez de tentar escapar
corretamente. `argv` e ambiente não são parseados por shell.

**Alternatives Rejected:**
1. **Interpolar com escape** — rejeitado: escape correto de PowerShell é sutil e um erro vira execução de comando.

**Consequences:**
- Aceito: o script fica menos legível numa linha só de comando.
- Ganho: nenhuma superfície de injeção; `check_secrets.py` segue sendo o único guard-rail necessário.

---

## File Manifest

| # | File | Action | Purpose | Agent | Dependencies |
|---|------|--------|---------|-------|--------------|
| 1 | `tools/alert_severity.py` | Create | Função pura de severidade + agregação pela pior | @python-developer | None |
| 2 | `tools/notify.py` | Create | Toast nativo por `subprocess` + `available()` | @python-developer | None |
| 3 | `tools/session_daemon.py` | Modify | Injeta `severity`, lê `GET /snooze`, dispara toast 1×/par | @python-developer | 1, 2 |
| 4 | `tools/doctor.py` | Modify | Checagem do canal de notificação (valida A-003) | @python-developer | 2 |
| 5 | `tools/README.md` | Modify | Mapa dos 2 módulos novos (exigência do projeto) | @code-documenter | 1, 2 |
| 6 | `include/session_model.h` | Modify | `enum class SeverityLevel` + campo em `SessionData` | (general) | None |
| 7 | `include/config.h` | Modify | Períodos, amplitudes e intervalo do tick de pulso | (general) | None |
| 8 | `include/ui_theme.h` | Modify | Constantes visuais do mudo e do card `expired` | (general) | None |
| 9 | `src/drivers/device_time.h` | Modify | Assinaturas de `s_base` e `pulse_tick` | (general) | 6, 7 |
| 10 | `src/drivers/device_time.cpp` | Modify | `apply_schedule` define base; pulso triangular sem float | (general) | 9 |
| 11 | `src/sessions/snooze.h` | Create | Interface do `snooze_until` em NVS | (general) | None |
| 12 | `src/sessions/snooze.cpp` | Create | Persistência via `Preferences` (padrão `id_list.cpp`) | (general) | 11 |
| 13 | `src/sessions/session_transport.cpp` | Modify | Parse de `severity`, `GET /snooze`, `POST /snooze/clear`, `/diag` | (general) | 6, 11 |
| 14 | `src/main.cpp` | Modify | Tick de ~70ms chamando `device_backlight_pulse_tick` | (general) | 10, 13 |
| 15 | `src/ui/ui_dashboard.cpp` | Modify | Header clicável, mudo no relógio, card `expired`, borda estática | (general) | 6, 8, 11 |
| 16 | `tests/fixtures/alerts/event_store.json` | Create | Fixture derivada do event store real (27 sessões) | @test-generator | None |
| 17 | `tests/test_alert_severity.py` | Create | Matriz de severidade por `subTest` | @test-generator | 1, 16 |
| 18 | `tests/test_notify.py` | Create | Dispatch por plataforma e `available()` com `subprocess` fake | @test-generator | 2 |
| 19 | `tests/test_session_daemon.py` | Modify | `severity` no payload, toast 1×, supressão por snooze | @test-generator | 3 |
| 20 | `tests/test_doctor.py` | Modify | Checagem do canal de notificação | @test-generator | 4 |
| 21 | `docs/SPEC.md` | Modify | Seção numerada nova: fonte da verdade do alerta escalonado | @code-documenter | 1-15 |
| 22 | `docs/ROADMAP.md` | Modify | Item #1 sai de "planejado" | @code-documenter | None |

**Total Files:** 22 (5 criados no daemon/testes, 2 criados no firmware, 15 modificados)

**Não muda:** `tools/monitor_config.py`. Verificado — `[alerts]` já é parseado
(`monitor_config.py:141-143`), validado (`_non_negative_int` nos três campos, mais
`critical_after_s >= warning_after_s` em `:293-294`) e já consta no `EXAMPLE_TOML`
(`:188`). A infraestrutura de configuração está completa; só faltava consumidor.

---

## Agent Assignment Rationale

> Agentes descobertos em `.claude/agents/**/*.md` — 18 disponíveis.

| Agent | Files Assigned | Why This Agent |
|-------|----------------|----------------|
| @python-developer | 1, 2, 3, 4 | Especialidade declarada: "clean patterns, dataclasses, type hints, generators" — que é exatamente a forma de `alert_severity.py` (dataclass frozen + função pura) e do dispatch de `notify.py` |
| @test-generator | 16, 17, 18, 19, 20 | Especialidade declarada em pytest/unittest + fixtures; o projeto usa `unittest.TestCase` com `subTest` em 18 de 18 arquivos de teste |
| @code-documenter | 5, 21, 22 | Documentação é o eixo dos três: o mapa de `tools/`, a seção da SPEC e o roadmap |
| **(general)** | 6-15 | **Nenhum dos 18 agentes cobre C++, embedded, LVGL ou PWM.** Os 10 arquivos de firmware ficam com o executor do Build, guiados pelos padrões abaixo — que foram extraídos do codebase (não inventados) e têm arquivo e linha citados |

**Agent Discovery:**
- Escaneado: `.claude/agents/**/*.md` — 18 agentes em 6 categorias.
- Casado por: tipo de arquivo, palavras-chave de propósito, padrão de caminho, domínio de KB.
- **Lacuna registrada:** metade do manifesto (10 de 22 arquivos) é C++ embedded sem especialista. Isso derruba a confiança do lado firmware para 0.80 e é o motivo de os padrões de código abaixo citarem arquivo e linha de origem em vez de descreverem intenção.

**Revisão sugerida ao Build:** @code-reviewer nos arquivos 1-4 depois de escritos, e
@shell-script-specialist especificamente sobre a constante PowerShell do arquivo 2 — o
único trecho de shell real da feature.

---

## Code Patterns

### Pattern 1: Severidade como função pura (`tools/alert_severity.py`)

```python
"""Severidade do alerta: uma regra, um lugar, coberta por teste.

Os limiares chegam do monitor.toml (já validados por monitor_config, que garante
critical_after_s >= warning_after_s — esta função não precisa se defender disso).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# Importado, NAO redefinido: a vida da marca de perm tem um dono só
# (session_state.py:58). Duas cópias divergiriam na primeira mudança.
from session_state import PERM_MARKER_MAX_AGE_S

# Ordem de urgência. `critical` supera `expired` porque é sinal exato vivo: uma
# admissão de ignorância não deve gritar mais alto que um sinal válido.
SEVERITY_ORDER: tuple[str, ...] = ("none", "warning", "expired", "critical")

# Só estado que bloqueia o agente escala. `work` e `free` nunca alertam.
ALERTING_STATES = frozenset({"ask", "perm"})

# Marca de perm velha demais para afirmar, mas nova demais para ignorar. Ver
# Decisão 2 do DESIGN: 2x PERM_MARKER_MAX_AGE_S. Passado isso, evidência morta.
EXPIRED_MAX_AGE_S = 1200.0


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Limiares em segundos, vindos de AlertSettings."""
    warning_after_s: int
    critical_after_s: int


def severity_for(state: str, elapsed_s: float, *, structured: bool,
                 perm_marker_age_s: float | None,
                 thresholds: Thresholds) -> str:
    """Severidade de UMA sessão. Pura: mesma entrada, mesma saída, sempre.

    `structured` = o estado veio de evento de hook (exato). Estado inferido tem
    teto em `warning` e nunca dispara toast — mesma cultura de procedência
    explícita da cota (ver tools/quota.py).

    `perm_marker_age_s` = idade da marca deixada pelo hook PermissionRequest, ou
    None quando não há marca. Marca entre PERM_MARKER_MAX_AGE_S e
    EXPIRED_MAX_AGE_S produz `expired`: o painel admite que não sabe em vez de
    voltar para `free` em silêncio.
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
    """Pulso é global: a pior severidade manda (espelha STATE_PRIORITY)."""
    return max(severities, key=SEVERITY_ORDER.index, default="none")
```

### Pattern 2: Toast sem superfície de injeção (`tools/notify.py`)

```python
"""Toast nativo do sistema. Stdlib puro — nada de pip install (regra 2)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

# Constante FIXA: título e corpo entram por ambiente, nunca interpolados. O nome da
# sessão vem de `cwd` (caminho controlado pelo usuário, pode ter aspas, $ e ;) —
# interpolar seria injeção de comando. Ver Decisão 6.
_WINDOWS_PS = (
    "Add-Type -AssemblyName System.Windows.Forms;"
    "$n = New-Object System.Windows.Forms.NotifyIcon;"
    "$n.Icon = [System.Drawing.SystemIcons]::Information;"
    "$n.Visible = $true;"
    "$n.ShowBalloonTip(10000, $env:MONITOR_TOAST_TITLE, $env:MONITOR_TOAST_BODY,"
    " [System.Windows.Forms.ToolTipIcon]::Warning);"
    "Start-Sleep -Seconds 6;"
    "$n.Dispose()"
)


def _powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


def available() -> tuple[bool, str]:
    """Canal de notificação existe nesta máquina? Sem efeito colateral — o doctor
    chama isto para validar a suposição A-003 do DEFINE."""
    if sys.platform.startswith("win"):
        found = _powershell()
        return (bool(found), found or "powershell/pwsh nao encontrado no PATH")
    found = shutil.which("notify-send")
    return (bool(found), found or "notify-send ausente (instale libnotify-bin)")


def notify(title: str, body: str, *, timeout_s: float = 12.0) -> bool:
    """Dispara o toast. NUNCA levanta: alerta que derruba o daemon é pior que
    alerta que não aparece — o painel continua sendo o canal principal."""
    env = dict(os.environ, MONITOR_TOAST_TITLE=title, MONITOR_TOAST_BODY=body)
    if sys.platform.startswith("win"):
        shell = _powershell()
        cmd = [shell, "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_PS] if shell else None
    else:
        sender = shutil.which("notify-send")
        cmd = [sender, "--urgency=critical", title, body] if sender else None
    if not cmd:
        return False
    try:
        done = subprocess.run(cmd, env=env, timeout=timeout_s,
                              capture_output=True, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0
```

### Pattern 3: Toast uma vez por par (`tools/session_daemon.py`)

```python
# Dispara 1x por (sessao, estado) — o mesmo principio do aviso de hook, que só
# imprime quando o diagnostico MUDA (ver comentario em session_daemon.py:797).
# O set vive no processo: reiniciar o daemon re-avisa, e isso é correto — quem
# reiniciou perdeu o contexto também.
_toasted: set[tuple[str, str]] = set()


def maybe_toast(sessions: list, snooze_s: int) -> int:
    """Notifica cada sessão que acabou de cruzar `critical`. Mudo é mudo."""
    if snooze_s > 0:
        return 0
    fired, live = 0, set()
    for s in sessions:
        key = (s["id"], s["state"])
        live.add(key)
        if s.get("severity") != "critical" or key in _toasted:
            continue
        # Marca ANTES de checar o resultado: canal indisponível não deve virar
        # nova tentativa a cada 5s. O doctor é quem reporta canal quebrado.
        _toasted.add(key)
        if notify("Monitor.AI",
                  "{} aguarda voce · {} ha {}".format(
                      s["project"], s["state"], format_elapsed(s["elapsed"]))):
            fired += 1
    # Par que saiu da lista pode avisar de novo: é um bloqueio novo, não repetição.
    _toasted.intersection_update(live)
    return fired


def fetch_snooze(base_url: str, token: str | None = None, timeout: float = 3.0) -> int:
    """Segundos restantes de mudo, do painel. Device fora do ar -> 0: degrada, não
    quebra (mesma política de fetch_id_list)."""
    try:
        with urllib.request.urlopen(
                authenticated_request(base_url + "/snooze", token=token),
                timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return max(0, int(data.get("snooze_s", 0)))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError, TypeError):
        return 0
```

### Pattern 4: Pulso de backlight sem invalidar tela (`src/drivers/device_time.cpp`)

```cpp
// O schedule deixa de escrever o PWM e passa a definir o BASE. Quem escreve e o
// tick de pulso. Sem isso, o tick de 30s do main.cpp atropelaria o pulso em <=30s
// (ver src/main.cpp:76).
static uint8_t s_base = BRIGHTNESS_DAY;

void device_backlight_apply_schedule() {
    int h, m;
    if (!device_time_now(h, m)) return;      // sem relogio: fica no brilho de dia
    const bool night = (h >= NIGHT_START_HOUR) || (h < NIGHT_END_HOUR);
    s_base = night ? BRIGHTNESS_NIGHT : BRIGHTNESS_DAY;
}

struct PulseSpec { uint16_t periodMs; uint8_t low; uint8_t high; };

static PulseSpec pulse_spec(SeverityLevel sev, uint8_t base) {
    switch (sev) {
        case SeverityLevel::WARNING:
        case SeverityLevel::EXPIRED: {
            const uint8_t delta = (uint8_t)((uint16_t)base * PULSE_WARN_AMPLITUDE_PCT / 100);
            const uint16_t period = (sev == SeverityLevel::EXPIRED)
                                  ? PULSE_EXPIRED_PERIOD_MS : PULSE_WARN_PERIOD_MS;
            return { period,
                     (uint8_t)(base > delta ? base - delta : 0),
                     (uint8_t)((uint16_t)base + delta > 255 ? 255 : base + delta) };
        }
        case SeverityLevel::CRITICAL:
            // Faixa ABSOLUTA de proposito: precisa furar o base noturno de 60.
            return { PULSE_CRIT_PERIOD_MS, PULSE_CRIT_LOW, PULSE_CRIT_HIGH };
        default:
            return { 0, base, base };
    }
}

// Chamado a cada PULSE_TICK_MS do loop. Onda triangular em inteiros: sem float,
// sem sin(), sem alocacao. Nenhuma chamada LVGL -> ZERO invalidacao de tela.
void device_backlight_pulse_tick(SeverityLevel sev, uint32_t nowMs) {
    const PulseSpec p = pulse_spec(sev, s_base);
    if (!p.periodMs) { device_backlight_set(s_base); return; }
    const uint32_t half  = p.periodMs / 2;
    const uint32_t phase = nowMs % p.periodMs;
    const uint32_t rise  = (phase < half) ? phase : (p.periodMs - phase);
    // device_backlight_set ja tem guarda de idempotencia (device_time.cpp:83-88):
    // so chega no ledcWrite quando o valor muda de verdade.
    device_backlight_set((uint8_t)(p.low + ((uint32_t)(p.high - p.low) * rise) / half));
}
```

### Pattern 5: Snooze em NVS (`src/sessions/snooze.cpp`)

```cpp
// Mesmo padrao de id_list.cpp: Preferences, chave curta, escrita so no toque.
#include <Preferences.h>
#include "snooze.h"
#include "config.h"

static uint32_t s_untilMs = 0;   // millis() alvo; 0 = sem mudo

void snooze_begin() {
    // Millis reinicia no boot, entao mudo nao sobrevive a reset — e nem deveria:
    // quem religou o painel quer ver o estado real.
    s_untilMs = 0;
}

void snooze_arm(uint32_t minutes) {
    s_untilMs = millis() + minutes * 60000UL;
}

uint32_t snooze_remaining_s() {
    if (!s_untilMs) return 0;
    const uint32_t now = millis();
    if ((int32_t)(s_untilMs - now) <= 0) { s_untilMs = 0; return 0; }
    return (s_untilMs - now) / 1000UL;
}
```

### Pattern 6: Estrutura de configuração (`monitor.toml`)

```toml
# Já existe e já é validado por monitor_config.py — esta feature só passa a CONSUMIR.
# Nenhuma chave nova: os três campos abaixo saem de zero consumidores para um cada.
[alerts]
warning_after_s = 90      # pulso lento começa aqui
critical_after_s = 300    # pulso rápido + toast; >= warning_after_s (validado)
snooze_minutes = 15       # janela do mudo por toque no header
```

### Pattern 7: Teste orientado a tabela na convenção do projeto

```python
# O KB (testing/concepts/parametrize.md) ensina @pytest.mark.parametrize, mas os 18
# arquivos de teste deste repo usam unittest.TestCase com subTest e ZERO parametrize.
# Padrao do projeto ganha do padrao do KB — ver skill sdd-design, Step 5.
import unittest

CASES = (
    # (estado,  elapsed, structured, marca,  esperado)
    ("perm",         10,       True,  None,  "none"),
    ("perm",        120,       True,  None,  "warning"),
    ("perm",        400,       True,  None,  "critical"),
    ("ask",         400,      False,  None,  "warning"),   # teto de procedencia
    ("perm",        400,       True,  700.0, "expired"),   # marca vencida
    ("perm",        400,       True, 1500.0, "none"),      # marca morta (Decisao 2)
    ("work",       9999,       True,  None,  "none"),
    ("free",       9999,       True,  None,  "none"),
)


class SeverityTests(unittest.TestCase):
    def test_matrix(self):
        limiares = Thresholds(warning_after_s=90, critical_after_s=300)
        for state, elapsed, structured, marca, esperado in CASES:
            with self.subTest(state=state, elapsed=elapsed, structured=structured):
                self.assertEqual(esperado, severity_for(
                    state, elapsed, structured=structured,
                    perm_marker_age_s=marca, thresholds=limiares))
```

---

## Data Flow

```text
1. monitor_config carrega [alerts] do monitor.toml (já validado: critical >= warning)
   │
   ▼
2. scan_claude_sessions / scan_codex_sessions / opencode produzem, por sessão:
   state, elapsed, structured (last_event_at is not None), idade da marca de perm
   │
   ▼
3. severity_for(...) -> "none" | "warning" | "critical" | "expired"   [função pura]
   │
   ▼
4. build_payload_v1/v2 injeta "severity" em cada item de sessions[]   [campo aditivo]
   │
   ├──► 5a. fetch_snooze(base) -> segundos restantes de mudo
   │        │
   │        ▼
   │    5b. maybe_toast(sessions, snooze_s): 1 toast por (id, estado) em critical
   │        │                                 (suprimido se snooze_s > 0)
   │        ▼
   │    notify.py -> subprocess -> PowerShell / notify-send
   │
   ▼
6. POST /sessions -> handle_sessions_post parseia severity (campo extra é ignorado
   por firmware antigo — verificado em session_transport.cpp:222-285)
   │
   ▼
7. Firmware: worst_severity(cards ocupados e não-stale); snooze ativo força NONE
   │
   ├──► 8a. device_backlight_pulse_tick(sev, millis()) a cada ~70ms -> ledcWrite
   │        (ZERO chamada LVGL)
   │
   └──► 8b. ui_dashboard: borda estática na cor do estado; card `expired` roxo +
            "perm?"; relógio do header com "· mudo 12m" enquanto silenciado
```

---

## Integration Points

| External System | Integration Type | Authentication |
|-----------------|-----------------|----------------|
| Painel ESP32-S3 (`POST /sessions`) | HTTP JSON, campo `severity` aditivo | Header `X-Monitor-Token`, comparação constant-time (já existente) |
| Painel ESP32-S3 (`GET /snooze`) | HTTP JSON, `{"snooze_s": N}` | Header `X-Monitor-Token` via `require_auth()` — mesma guarda de `/hidden` |
| Painel ESP32-S3 (`POST /snooze/clear`) | HTTP, desfaz o mudo sem tocar no painel | `require_auth()`, simétrico a `/hidden/clear` |
| Windows Notification Center | `subprocess` → `powershell -NoProfile -NonInteractive` | Escopo de usuário; sem admin |
| libnotify (Linux) | `subprocess` → `notify-send` | Sessão do usuário (D-Bus) |

---

## Testing Strategy

| Test Type | Scope | Files | Tools | Coverage Goal |
|-----------|-------|-------|-------|---------------|
| Unit | `severity_for`, `worst_severity` | `tests/test_alert_severity.py` | `unittest` + `subTest` | 100% dos ramos (matriz de 8+ casos) |
| Unit | `notify`/`available`, dispatch por plataforma | `tests/test_notify.py` | `unittest` + monkeypatch de `subprocess.run` e `shutil.which` | Windows, Linux, canal ausente, timeout |
| Integration | `severity` no payload, toast 1×, supressão por snooze | `tests/test_session_daemon.py` (mod.) | `unittest` + fixtures herméticas | Caminhos principais |
| Integration | Checagem do canal no `doctor` | `tests/test_doctor.py` (mod.) | `unittest` + fixtures existentes | Canal ok / ausente |
| Hardware (manual) | Pulso, mudo, `expired`, modo noturno | — | Placa + `GET /diag` | AT-001, 002, 004, 005, 009, 013, 014 |

**Cobertura dos testes de aceitação do DEFINE:**

| AT | Como é coberto |
|----|----------------|
| AT-001 warning | `test_alert_severity` (matriz) + verificação manual do pulso |
| AT-002 crítico + toast | `test_alert_severity` + `test_session_daemon::maybe_toast` |
| AT-003 teto de procedência | `test_alert_severity` — caso `structured=False` |
| AT-004 marca expirada | `test_alert_severity` — casos 700s e 1500s |
| AT-005 snooze silencia | `test_session_daemon` (supressão) + manual (relógio/pulso) |
| AT-006 mudo é mudo | `test_session_daemon::maybe_toast(snooze_s>0)` retorna 0 |
| AT-007 agregação (pior vence) | `test_alert_severity::worst_severity` — caso `warning` + `critical` |
| AT-008 agregação com `expired` | `test_alert_severity::worst_severity` — caso `warning` + `expired` |
| AT-009 crítico no escuro | Manual na placa: faixa absoluta 40↔255 contra base 60 |
| AT-010 limiar sem reflash | `test_session_daemon` com `Thresholds` alternativos |
| AT-011 toast não repete | `test_session_daemon` — segundo ciclo não dispara |
| AT-012 retrocompatibilidade | Já **verificado por leitura** (`session_transport.cpp:222-285`); regressão coberta por `test_production_contracts` |
| AT-013 sem alerta, sem pulso | `test_alert_severity` (`work`/`free` → `none`) + manual |
| AT-014 snooze expira | `test_session_daemon` com `snooze_s=0` após janela |

---

## Error Handling

| Error Type | Handling Strategy | Retry? |
|------------|-------------------|--------|
| Painel fora do ar no `GET /snooze` | Devolve 0 (não silenciado) — degrada, não quebra; mesma política de `fetch_id_list` | Não (próximo ciclo) |
| PowerShell / `notify-send` ausente | `notify()` devolve `False`; par marcado como avisado para não tentar a cada 5s; `doctor` reporta | Não |
| `subprocess` travado | `timeout_s=12`; exceção capturada, ciclo do daemon segue | Não |
| Firmware antigo sem `severity` | Campo ignorado por whitelist — verificado; nenhum 422 | N/A |
| `severity` desconhecida no firmware | `parse_severity` cai em `NONE` (vocabulário fechado, falha segura como `parse_state`) | N/A |
| NTP não sincronizado | `apply_schedule` retorna sem mexer no base; pulso segue no base de dia | Não |
| Marca de `perm` órfã | `EXPIRED_MAX_AGE_S` derruba para `none` em 20 min (Decisão 2) | N/A |

---

## Configuration

| Config Key | Type | Default | Description |
|------------|------|---------|-------------|
| `alerts.warning_after_s` | int | `90` | Segundos em `ask`/`perm` para começar o pulso lento |
| `alerts.critical_after_s` | int | `300` | Segundos para pulso rápido + toast; validado como `>= warning_after_s` |
| `alerts.snooze_minutes` | int | `15` | Janela do mudo ao toque no header |
| `EXPIRED_MAX_AGE_S` | float (const.) | `1200.0` | Idade máxima da marca de `perm` para sustentar `expired` — constante de código, não config (Decisão 2) |
| `PULSE_TICK_MS` | int (`config.h`) | `70` | Passo do pulso; ~10 amostras no período crítico |
| `PULSE_WARN_PERIOD_MS` | int (`config.h`) | `2000` | Período do pulso de `warning` |
| `PULSE_CRIT_PERIOD_MS` | int (`config.h`) | `700` | Período do crítico — razão 2,86× sobre warning (critério exige ≥ 2,5×) |
| `PULSE_EXPIRED_PERIOD_MS` | int (`config.h`) | `1200` | Período do `expired` |
| `PULSE_WARN_AMPLITUDE_PCT` | int (`config.h`) | `30` | Amplitude do warning como % do base |
| `PULSE_CRIT_LOW` / `_HIGH` | int (`config.h`) | `40` / `255` | Faixa absoluta do crítico — fura o base noturno de 60 |

---

## Security Considerations

- **Injeção de comando eliminada por construção.** O nome da sessão vem de `cwd`, um caminho controlado pelo usuário. Título e corpo entram por `env=` (Windows) e `argv` (Linux); nunca `shell=True`, nunca interpolação (Decisão 6).
- **`GET /snooze` e `POST /snooze/clear` exigem `require_auth()`** — mesma guarda de token e comparação constant-time de `/hidden` e `/pinned`. Nenhum endpoint novo sem autenticação.
- **O toast não carrega segredo.** Corpo = nome do projeto, estado e tempo. Nenhum token, nenhum caminho absoluto. `check_secrets.py` segue como guard-rail.
- **`timeout` obrigatório no `subprocess`** — um PowerShell travado não pode parar o ciclo do daemon.
- **Nada de novo no orçamento de corpo HTTP.** O campo aditivo custa ~25 B × ≤6 sessões contra `HTTP_MAX_BODY_BYTES = 16384`.
- **Escopo de usuário mantido** — nenhuma elevação, nenhum serviço novo (regra 6 do `CLAUDE.md`).

---

## Observability

| Aspect | Implementation |
|--------|----------------|
| Logging | O daemon imprime a severidade agregada **só quando muda**, seguindo o princípio já aplicado aos avisos de hook (`session_daemon.py:797`) — repetir a cada 5s treina o operador a não ler |
| Metrics | `GET /diag` ganha `alert.severity` (severidade agregada vigente), `alert.snooze_s` (mudo restante) e `alert.pulse_level` (último valor de PWM) — o painel prova o alerta de fora, sem depender de impressão visual, que é a razão de existir do `/diag` |
| Tracing | N/A — sem sistema distribuído |
| Diagnóstico local | `python tools/monitor.py doctor` ganha a checagem do canal de notificação, transformando a suposição A-003 do DEFINE em verificação executável |

---

## Pipeline Architecture (if applicable)

**Não aplicável.** A feature não introduz pipeline, ETL, fonte de dados nem modelo
analítico: consome campos que o daemon já calcula e persiste um único escalar na placa.
As seções de DAG, particionamento, estratégia incremental, evolução de schema e gates de
qualidade não têm conteúdo honesto a receber aqui e foram deliberadamente deixadas vazias
em vez de preenchidas com material inventado.

---

## Contract Gate

`tools/spec-linter/` **não existe neste repositório**, como já registrado na fase Define.
O `exit_code_contract` do `WORKFLOW_CONTRACTS.yaml` classifica linter indisponível como
**exit 2 (ERROR)**, cuja regra é *"record a VISIBLE skip and proceed — never assume PASS
on exit 2"*.

- **Verdict:** não obtido (linter ausente).
- **Ação:** skip registrado visivelmente; conformidade verificada à mão contra as 17 seções do `DESIGN_TEMPLATE.md` — todas presentes.
- **Nunca assumido:** PASS.

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-09-08 | design-agent | Versão inicial a partir de `DEFINE_ALERTA_ESCALONADO.md`. 6 ADRs inline. Descoberto que `monitor_config.py` não precisa de mudança (`[alerts]` já parseado e validado). Decisão 2 refina um critério do DEFINE — tensão registrada. Decisão 4 muda comportamento existente (borda deixa de pulsar) |

---

## Next Step

**Ready for:** `/ship .claude/sdd/features/DEFINE_ALERTA_ESCALONADO.md`

> Construido em 2026-09-08. Relatorio:
> `.claude/sdd/reports/BUILD_REPORT_ALERTA_ESCALONADO.md` — 4 desvios
> registrados, sendo o principal o `Popen` em vez de `run` no notify.
