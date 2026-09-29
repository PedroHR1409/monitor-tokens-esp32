# DESIGN: Integração com o Command Code

> Quarto provedor no daemon: collector dedicado por transcript JSONL + hooks nativos,
> reusando o event store, o reducer de estado e a infraestrutura de uso já existentes

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | COMMANDCODE_INTEGRATION |
| **Date** | 2026-09-19 |
| **Author** | design-agent |
| **DEFINE** | [DEFINE_COMMANDCODE_INTEGRATION.md](./DEFINE_COMMANDCODE_INTEGRATION.md) — clareza 15/15 |
| **Status** | ✅ Complete (Built) |
| **Abordagem** | Approach A do brainstorm — collector dedicado + hook installer, espelhando o OpenCode |
| **Confiança (daemon)** | **0.95** — KB `python`/`testing` carregada + `@python-developer` e `@test-generator` disponíveis; padrões verificados no próprio codebase |
| **Confiança (firmware)** | **0.80** — nenhuma KB cobre embedded/C++ e não existe agente C++; padrões extraídos do codebase, arquivo e linha citados |

---

## Architecture Overview

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                        PC (daemon, Python stdlib)                             │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ~/.commandcode/projects/<slug>/<id>.jsonl     ~/.commandcode/settings.json    │
│  (transcript: session header + messages)       (hooks do usuario)             │
│         │                                              │                      │
│         │ leitura read-only                            │ sessao/tool call      │
│         ▼                                              ▼                      │
│  ┌───────────────────────┐                    ┌──────────────────────────┐   │
│  │ commandcode_sessions  │                    │ session_hook.py          │   │
│  │ .scan_*()             │                    │  commandcode <action>    │   │
│  │  - meta/usage/ctx     │                    │  -> monitor-ai-events.json│  │
│  │  - inferencia estado  │                    └────────────┬─────────────┘   │
│  └───────┬───────────────┘                                 │                 │
│          │ sessao dict                                     ▼                 │
│          │                                    ~/.commandcode/monitor-ai-     │
│          │                                       events.json                  │
│          │                                          │                        │
│          │              reduce_session_events ──────┘                        │
│          │                        (agent_events, reusado)                    │
│          ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │ session_daemon.build_payload_v1/v2                                    │    │
│  │   scan_claude + scan_codex + scan_opencode + scan_commandcode         │    │
│  │   ranking -> severidade -> catalogo -> POST /sessions                 │    │
│  └───────┬──────────────────────────────────────────────────────────────┘    │
│          │                         quota.collect  <- window_tokens()          │
│          │                         usage_top / usage_history <- turn events   │
│          ▼                                                                    │
└──────────┼────────────────────────────────────────────────────────────────────┘
           │ POST /sessions (tool="commandcode")
           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        ESP32-S3 (firmware)                                    │
├──────────────────────────────────────────────────────────────────────────────┤
│  session_transport.cpp: parse_tool("commandcode") -> ToolType::COMMANDCODE    │
│         │                                                                     │
│         ├─ tool desconhecido (firmware antigo) -> 422 (daemon degrada)        │
│         ▼                                                                     │
│  ui_dashboard.cpp: icon_for_provider(provider, tool) -> icone do vendor       │
│                    (fallback no icone padrao)                                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| `tools/commandcode_sessions.py` | Collector: lê transcripts, deriva estado/metadados/tokens/contexto | Python 3.10+ stdlib; `@dataclass(frozen=True, slots=True)` (KB `python/concepts/dataclasses.md`) |
| `tools/session_hook.py` (mod.) | Reconhecer `provider=commandcode`; event store e `hook_health` do novo agente | Python stdlib (já existente) |
| `tools/install_commandcode_hook.py` | Instalar/remover hooks aditivos em `~/.commandcode/settings.json` | Python stdlib; espelha `install_codex_hook.py` |
| `tools/session_daemon.py` (mod.) | Ligar o collector ao payload, ranking, log e avisos | Python stdlib |
| `tools/quota.py` (mod.) | Bloco `commandcode` estimado (consumo bruto) | Python stdlib |
| `tools/usage_top.py` / `usage_history.py` (mod.) | Pódio e histórico diário com os tokens do Command Code | Python stdlib |
| `tools/monitor_config.py` (mod.) | `commandcode_context_window` opcional | Python stdlib |
| `tools/doctor.py` (mod.) | Checar o caminho dos transcripts | Python stdlib |
| `include/session_model.h` (mod.) | `ToolType::COMMANDCODE` | C++ |
| `src/sessions/session_transport.cpp` (mod.) | `parse_tool("commandcode")` | C++ / ArduinoJson |
| `tools/README.md`, `docs/SPEC.md`, `docs/ROADMAP.md` (mod.) | Mapa, fonte da verdade e roadmap | Markdown |

---

## Key Decisions

### Decision 1: Estado por hooks nativos + inferência de transcript, reusando o reducer existente

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-19 |

**Context:** O Command Code tem `SessionStart`, `PreToolUse`, `PostToolUse`, `Stop` — **não
tem `PermissionRequest`** como o Claude/Codex, e o `PreToolUse` recebe `permission_mode`.
Isso deixa `perm` sem sinal estruturado direto.

**Choice:** Instalar os 4 hooks nativos mapeados para o vocabulário de ações **já
existente** (`SessionStart→free`, `PreToolUse→pre_tool_use`, `PostToolUse→work`,
`Stop→free`) e derivar o estado por:

1. `reduce_session_events` no event store (reusado sem alteração);
2. `ask` quando o último turno do assistente tem `tool_use` de `ask_user_question` sem
   `tool_result` correspondente (transcript manda sobre o hook, como no Claude);
3. `perm` quando há `tool_use` pendente não-pergunta **e** não há `PreToolUse`/`PostToolUse`
   posterior a ele — ou seja, a chamada está esperando aprovação. Validade máxima de
   600s (`PERM_MARKER_MAX_AGE_S`, importado de `session_state.py`, não redefinido);
4. senão, o estado estruturado; sem evento, `work` por recência
   (`WORK_MAX_AGE_S=1800`) e nunca `ask`/`perm` inventados.

**Rationale:** Reusa o reducer determinístico e testado (`agent_events.py`), o
vocabulário de ações (`ACTION_STATE`) e o formato de evento já consumido pelos outros dois
agentes. Nenhum mecanismo paralelo nasce. O teto de 600s reaplica a regra de evidência do
projeto: evidência velha deixa de sustentar afirmação.

**Alternatives Rejected:**
1. **Mod TS (`ModApi`) emitindo `tool_running`/`tool_completed`/`turn_end`** — rejeitado: exigiria um artefato novo (arquivo `.ts`), caminho de instalação e confiança do usuário, para um ganho marginal sobre a inferência.
2. **Só transcript, sem hooks** — rejeitado: perde o determinismo de `work`/`free` e não melhora `perm` (a ausência de hook é justamente o sinal).

**Consequences:**
- Aceito: `perm` é o único estado inferido; A-003 do DEFINE pode reduzir sua fidelidade. O teto de 600s evita o modo de falha pior (perm eterno).
- Ganho: zero dependência de mods; mesma linguagem de estado dos demais provedores.

---

### Decision 2: Collector dedicado e read-only, que nunca abre `auth.json`

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-19 |

**Context:** `~/.commandcode/` contém `auth.json` com uma API key em texto claro. O
collector só precisa de `projects/**/*.jsonl`.

**Choice:** `tools/commandcode_sessions.py` enumera **apenas** `projects_dir()/ **/*.jsonl`,
não importa nem lê nada de `~/.commandcode/` além dos transcripts e do event store do
próprio Monitor.AI. Sem SQLite, sem credenciais.

**Rationale:** O pedido do DEFINE é explícito ("o daemon nunca abre `auth.json`"), e
restringir o escopo de leitura por construção é mais forte que lembrar de não ler.
Segue o padrão do `opencode_sessions.py` (leitura read-only, falha segura para `[]`).

**Alternatives Rejected:**
1. **Ler `auth.json` para descobrir o usuário/plano** — rejeitado: viola a regra de segredos; o painel não precisa disso.

**Consequences:**
- Aceito: se o usuário não tiver `projects/`, o collector devolve `[]` (degradação silenciosa, como os outros).
- Ganho: superfície de segredo nula; `check_secrets.py` segue como único guard-rail.

---

### Decision 3: Event store e health no mesmo mecanismo dos outros agentes, não um paralelo

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-19 |

**Context:** `session_hook._default_path(provider)` decide o arquivo por provedor
(`.codex` → `~/.codex/monitor-ai-events.json`, senão `.claude`). E `hook_health()` só
conhece `claude` e `codex`.

**Choice:** Estender `_default_path` com o ramo `commandcode` →
`~/.commandcode/monitor-ai-events.json`, adicionar `COMMANDCODE_SETTINGS` e incluir
`"commandcode"` em `hook_health()`. O installer usa o mesmo par (script, agente) que
`hook_installed` já detecta — nenhuma nova função de detecção.

**Rationale:** Um mecanismo único de saúde de hook é o que permitiu diagnosticar o
incidente em que o Orca substituiu os hooks do Claude (comentário em `session_hook.py:18-25`).
Duplicar a detecção reintroduziria o ponto cego.

**Alternatives Rejected:**
1. **Event store próprio com schema diferente** — rejeitado: quebraria `load_event_store`/`reduce_session_events` e o `/diag`.

**Consequences:**
- Aceito: `session_hook.py` passa a conhecer um terceiro provedor (o arquivo continua sendo um entrypoint estável — regra 4).
- Ganho: `doctor`/`hooks check` cobrem o novo agente de graça.

---

### Decision 4: Tokens somam `input + output + cacheWrite`, dedup por `messageId`

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-19 |

**Context:** Cada mensagem do assistente traz
`usage:{inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens, costUsd}`.

**Choice:** `tokensWin` e os agregados somam `inputTokens + outputTokens + cacheWriteTokens`
e **excluem** `cacheReadTokens`; a dedup é por `message.messageId`.

**Rationale:** É exatamente a semântica já usada por Claude (`usage_tracker._usage_of`,
`cache_read` excluído de propósito) e OpenCode (`cache.write` incluído, `cache.read`
excluído) — incluir `cacheReadTokens` infla o número com releitura do mesmo contexto. A
dedup por id segue o mesmo motivo do Claude (uma mensagem pode ocupar mais de uma linha).

**Alternatives Rejected:**
1. **Somar tudo** — rejeitado: número incomparável com os outros provedores.
2. **Usar `costUsd` como métrica** — rejeitado no DEFINE (YAGNI): o usuário escolheu só tokens.

**Consequences:**
- Aceito: o número do Command Code fica na mesma régua dos demais.
- Ganho: o pódio e o heatmap permanecem comparáveis.

---

### Decision 5: Cota como consumo bruto no bloco estimado (sem percentual)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-19 |

**Context:** O Command Code não publica `used_percent` nem janela de 5h; só o Codex expõe
número oficial.

**Choice:** `quota.collect` ganha um bloco `commandcode` com
`{ok, official: False, tokens, pct: 0}`, idêntico ao bloco OpenCode (`quota.py:259-263`),
alimentado por `window_tokens(projects_dir, now - 5h)`.

**Rationale:** O próprio `quota.py` documenta que Claude/OpenCode são estimativas por não
terem número no disco; inventar um percentual violaria a política do projeto de
procedência explícita ("não fabricar percentual"). Fabricar denominador seria pior que não
mostrar nada.

**Alternatives Rejected:**
1. **Percentual com orçamento configurável** — rejeitado no DEFINE: exigiria uma config nova sem dado que a justifique.
2. **Omitir o Command Code da cota** — rejeitado: `COULD`, mas o custo é uma linha; o consumo bruto é honesto.

**Consequences:**
- Aceito: `pct` fica em 0 (a barra não enche), como o OpenCode.
- Ganho: o consumo entra no painel sem afirmar o que não se sabe.

---

### Decision 6: Contexto estimado por config/tabela; nunca percentual fabricado

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-19 |

**Context:** Diferente do Codex, o transcript do Command Code **não** traz
`model_context_window`. `usage_model.context_measurement` exige um denominador para
devolver percentual.

**Choice:** `commandcode_context_window` em `[usage]` do `monitor.toml` (default `0`) e
uma tabela `MODEL_CONTEXT_WINDOWS` por prefixo de modelo (padrão `opencode_sessions.py:43`).
Sem denominador resolvido → `quality="unknown"` e **sem** `ctxPct`.

**Rationale:** `context_measurement` já é explícito: *"never fabricates a percentage when
no denominator"* (`usage_model.py:35-48`). Reusar a função com `measured_limit`/
`configured_limit` mantém a regra num só lugar.

**Alternatives Rejected:**
1. **Estimar a janela por heurística do maior `inputTokens` visto** — rejeitado: produziria percentual falso, o pior resultado.
2. **Deixar contexto de fora** — rejeitado: o card perderia um campo que os outros 3 têm.

**Consequences:**
- Aceito: o percentual só aparece quando o usuário configura a janela.
- Ganho: nenhum número inventado na tela.

---

### Decision 7: Firmware ganha o enum e o parse; a compatibilidade é resolvida pelo fallback 422 no daemon

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-19 |

**Context:** `handle_sessions_post` rejeita o POST inteiro com 422 quando
`tool == ToolType::UNKNOWN` (`session_transport.cpp:355`). Adicionar um valor novo de
`tool` quebra firmware antigo. O fallback atual só cobre `opencode` e **não tem teste**.

**Choice:** Adicionar `ToolType::COMMANDCODE` e `parse_tool("commandcode")`. No daemon,
generalizar o fallback 422 existente para reagir a sessões cujo `tool` o firmware não
conhece (hoje o gatilho é `tool == "opencode"`), e **adicionar o teste que hoje falta**
para esse caminho. Sem ícone novo: `icon_for_provider` já resolve por `provider` com
fallback.

**Rationale:** Um provedor novo é exatamente o caso que o fallback existe para cobrir; hoje
ele foi escrito para um único provedor. Generalizar é menos código que somar um `or`.
O ícone por `provider` já entrega a identidade visual sem asset novo (YAGNI do DEFINE).

**Alternatives Rejected:**
1. **Só adicionar uma condição `or tool == "commandcode"`** — rejeitado: repete o problema a cada provedor e mantém o caminho sem teste.
2. **Gerar ícone de marca** — rejeitado no DEFINE: exige asset PNG e ajuste de `icon_convert`.

**Consequences:**
- Aceito: firmware antigo derruba as sessões do Command Code até ser regravado; o painel continua vivo.
- Ganho: o caminho de degradação passa a ser genérico e testado.

---

## File Manifest

| # | File | Action | Purpose | Agent | Dependencies |
|---|------|--------|---------|-------|--------------|
| 1 | `tools/commandcode_sessions.py` | Create | Collector (scan, meta, tokens, contexto, estado) | @python-developer | None |
| 2 | `tools/install_commandcode_hook.py` | Create | Instalador aditivo/idempotente em `~/.commandcode/settings.json` | @python-developer | None |
| 3 | `tools/session_hook.py` | Modify | Ramo `commandcode` em `_default_path` + `hook_health` | @python-developer | None |
| 4 | `tools/session_daemon.py` | Modify | Ligar collector, arg `--commandcode-projects`, fallback 422 genérico, tag `CC` | @python-developer | 1 |
| 5 | `tools/quota.py` | Modify | Bloco `commandcode` (consumo bruto estimado) | @python-developer | 1 |
| 6 | `tools/usage_top.py` | Modify | Pódio por provedor com tokens CC | @python-developer | 1 |
| 7 | `tools/usage_history.py` | Modify | Backfill diário dos tokens CC | @python-developer | 1 |
| 8 | `tools/monitor_config.py` | Modify | `usage.commandcode_context_window` | @python-developer | None |
| 9 | `tools/doctor.py` | Modify | Checagem do diretório de transcripts | @python-developer | 1 |
| 10 | `tools/README.md` | Modify | Mapa dos 2 módulos novos | @code-documenter | 1, 2 |
| 11 | `include/session_model.h` | Modify | `ToolType::COMMANDCODE` | (general) | None |
| 12 | `src/sessions/session_transport.cpp` | Modify | `parse_tool("commandcode")` | (general) | 11 |
| 13 | `tests/fixtures/commandcode/*.jsonl` | Create | Fixtures derivadas dos transcripts reais (sanitizadas) | @test-generator | None |
| 14 | `tests/test_commandcode_sessions.py` | Create | Matriz de estado, tokens, contexto, dedup | @test-generator | 1, 13 |
| 15 | `tests/test_commandcode_hook.py` | Create | Install aditivo, idempotente, remove, health | @test-generator | 2, 3 |
| 16 | `tests/test_session_daemon.py` | Modify | Sessão CC no payload + fallback 422 (caminho hoje sem teste) | @test-generator | 4 |
| 17 | `tests/test_doctor.py` | Modify | Checagem do path do Command Code | @test-generator | 9 |
| 18 | `docs/SPEC.md` | Modify | Seção numerada nova (fonte da verdade do provedor) | @code-documenter | 1-12 |
| 19 | `docs/ROADMAP.md` | Modify | Registrar a integração | @code-documenter | None |

**Total Files:** 19 (11 criados/modificados no daemon e testes, 2 no firmware, 3 de docs, 3 de fixtures)

**Não muda:** `tools/agent_events.py`, `tools/session_state.py`, `tools/session_meta.py`,
`tools/protocol_v2.py`, `src/ui/ui_dashboard.cpp` e `include/icons.h`. Verificado por
leitura: o reducer e a inferência são genéricos; `provider`/`session_key` já caem em
`tool` quando ausente (`protocol_v2.py:105`); o ícone é resolvido por `provider`
(`ui_dashboard.cpp:77-87`).

---

## Agent Assignment Rationale

> Agentes descobertos em `.claude/agents/**/*.md` — 18 disponíveis.

| Agent | Files Assigned | Why This Agent |
|-------|----------------|----------------|
| @python-developer | 1-9 | Especialidade declarada em "clean patterns, dataclasses, type hints" — exatamente a forma do collector (função pura + dataclass) e dos módulos stdlib-ony do daemon |
| @test-generator | 13-17 | Especialidade em pytest/unittest + fixtures; o projeto usa `unittest.TestCase` com `subTest` em 18 de 18 arquivos de teste, e as fixtures vêm de dados reais |
| @code-documenter | 10, 18, 19 | Documentação é o eixo dos três: mapa de `tools/`, seção da SPEC e roadmap |
| (general) | 11-12 | **Nenhum dos 18 agentes cobre C++/embedded.** Os 2 arquivos de firmware ficam com o executor do Build, guiados pelos padrões abaixo (arquivo e linha citados) |

**Agent Discovery:**
- Escaneado: `.claude/agents/**/*.md` — 18 agentes em 7 categorias.
- Casado por: tipo de arquivo, palavras-chave de propósito, padrão de caminho, domínio de KB.
- **Lacuna registrada:** o firmware C++ não tem especialista (mesma lacuna da feature do alerta). Isso mantém a confiança do lado firmware em 0.80.

**Revisão sugerida ao Build:** @code-reviewer em `tools/commandcode_sessions.py` e
`tools/install_commandcode_hook.py` depois de escritos (o installer edita um arquivo de
config compartilhado com outra ferramenta — o ponto de maior risco).

---

## Code Patterns

### Pattern 1: Collector puro, falha segura (`tools/commandcode_sessions.py`)

```python
"""Coletor do Command Code: le os transcripts JSONL e deriva sessao/estado/uso.

Le APENAS projects/**/*.jsonl. Nunca abre auth.json (contem a API key) — ver
Decisao 2 do DESIGN. Arquivo ausente/ilegivel devolve [] como o collector do
OpenCode, para um provedor quebrado nao derrubar o ciclo do daemon.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agent_events import reduce_session_events
from session_state import (
    PERM_MARKER_MAX_AGE_S, WORK_MAX_AGE_S, session_display_name, strip_accents,
)
from session_meta import read_git_branch
from usage_model import context_measurement

SCAN_CANDIDATES = 24
TAIL_BYTES = 64 * 1024
SOURCE_STALE_AFTER_S = 300
MESSAGE_WINDOW_H = 12

# Pergunta do produto: sinal deterministico de `ask`.
QUESTION_TOOLS = frozenset({"ask_user_question"})

# Denominador de contexto: sem isto, quality="unknown" e nenhum percentual.
MODEL_CONTEXT_WINDOWS: dict[str, int] = {}
DEFAULT_CONTEXT_WINDOW = 0


def projects_dir() -> Path:
    override = os.environ.get("MONITOR_COMMANDCODE_DIR", "").strip()
    return Path(override) if override else Path.home() / ".commandcode" / "projects"


def event_store_path() -> Path:
    return Path.home() / ".commandcode" / "monitor-ai-events.json"


@dataclass(frozen=True, slots=True)
class SessionUsage:
    """Tokens de uma mensagem, na mesma regua dos outros provedores."""
    message_id: str
    timestamp: datetime
    tokens: int          # input + output + cacheWrite (cacheRead excluido)
    context_tokens: int  # o que entrou no prompt do ultimo turno
```

### Pattern 2: Leitura de transcript e dedup (`commandcode_sessions.py`)

```python
def _iter_messages(path: Path):
    """Percorre o JSONL tolerando linha ruim (padrao safe_parse da KB)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    yield json.loads(stripped)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _usage_events(path: Path) -> list[SessionUsage]:
    """Uma entrada por mensagem com usage; dedup por messageId.

    Uma mensagem pode ocupar mais de uma linha — a mesma razao do dedup do
    Claude (tools/usage_tracker.py:82-88). Sem isto o total infla.
    """
    seen: set[str] = set()
    out: list[SessionUsage] = []
    for obj in _iter_messages(path):
        if obj.get("type") != "message":
            continue
        message = obj.get("message") or {}
        if message.get("role") != "assistant":
            continue
        usage = obj.get("usage") or {}
        key = str((message.get("meta") or {}).get("messageId") or obj.get("id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        stamp = _timestamp(obj.get("timestamp"))
        if stamp is None:
            continue
        tokens = (int(usage.get("inputTokens") or 0)
                  + int(usage.get("outputTokens") or 0)
                  + int(usage.get("cacheWriteTokens") or 0))
        context = (int(usage.get("inputTokens") or 0)
                   + int(usage.get("cacheReadTokens") or 0)
                   + int(usage.get("cacheWriteTokens") or 0)
                   + int(usage.get("outputTokens") or 0))
        out.append(SessionUsage(key, stamp, tokens, context))
    return out
```

### Pattern 3: Estado — hook manda, transcript desempata (`commandcode_sessions.py`)

```python
def _pending_tool_use(path: Path):
    """Ultimo tool_use do assistente sem tool_result correspondente. None se nao ha.

    Um tool_use pendente e o sinal de que a chamada ainda nao concluiu: se for
    `ask_user_question` e uma pergunta (`ask`); se nenhum hook PreToolUse/
    PostToolUse a registrou, esta aguardando aprovacao (`perm`) — Decisao 1.
    """
    messages = [obj for obj in _iter_messages(path) if obj.get("type") == "message"]
    last_assistant = next(
        (obj for obj in reversed(messages)
         if (obj.get("message") or {}).get("role") == "assistant"), None)
    if last_assistant is None:
        return None, None
    pending = [block for block in (last_assistant.get("message") or {}).get("content", [])
               if isinstance(block, dict) and block.get("type") == "tool_use"]
    if not pending:
        return None, None
    resolved = {
        str(block.get("tool_use_id") or "")
        for obj in messages if (obj.get("message") or {}).get("role") == "user"
        for block in (obj.get("message") or {}).get("content", [])
        if isinstance(block, dict) and block.get("type") == "tool_result"
    }
    for block in reversed(pending):
        if str(block.get("id") or "") not in resolved:
            return block.get("name"), _timestamp(last_assistant.get("timestamp"))
    return None, None


def _derive_state(path: Path, snapshot, now: datetime) -> tuple[str, float]:
    """(state, state_age_s). `snapshot` vem de reduce_session_events (reusado)."""
    name, pending_at = _pending_tool_use(path)
    if name in QUESTION_TOOLS:
        return "ask", _age_s(pending_at, now)
    recent_hook = (snapshot.last_event_at is not None
                   and pending_at is not None
                   and snapshot.last_event_at >= pending_at)
    if name is not None and pending_at is not None and not recent_hook:
        # Aguardando aprovacao. Evidencia velha deixa de afirmar (Decisao 1).
        age = _age_s(pending_at, now)
        return ("perm", age) if age <= PERM_MARKER_MAX_AGE_S else ("free", age)
    if snapshot.last_event_at is not None:
        return snapshot.state, _age_s(snapshot.last_event_at, now)
    # Sem hook: recencia. Nunca inventa ask/perm (mesma regra do Codex).
    age = _age_s(_mtime(path), now)
    return ("work" if age <= WORK_MAX_AGE_S else "free"), age


def scan_commandcode_sessions(now: datetime, since_epoch: float, *,
                              directory: Path | None = None,
                              ctx_window: int = 0) -> list[dict]:
    """Uma entrada por transcript. Path ausente -> [] (nunca levanta)."""
    root = Path(directory) if directory is not None else projects_dir()
    try:
        candidates = sorted(root.glob("*/*.jsonl"),
                            key=lambda p: p.stat().st_mtime, reverse=True)[:SCAN_CANDIDATES]
    except OSError:
        return []
    snapshots = reduce_session_events(event_store_path(), now)
    sessions: list[dict] = []
    for path in candidates:
        # ... monta o dict no mesmo shape de scan_opencode_sessions:
        # id, project, full, branch, model, effort, tokensWin, context,
        # context_tokens, tool="commandcode", state, elapsed, source_stale, diagnostic
        ...
    return sessions
```

### Pattern 4: Installer aditivo e idempotente (`tools/install_commandcode_hook.py`)

```python
"""Instala hooks do Monitor.AI em ~/.commandcode/settings.json.

O arquivo pode conter hooks de TERCEIROS (verificado: ha um wrapper PowerShell
instalado). Por isso o installer so mexe nos grupos que reconhece como seus —
mesmo criterio (_is_ours) do install_codex_hook.py — e faz backup antes de gravar.
"""
HOOKS_FILE = Path.home() / ".commandcode" / "settings.json"
HOOK_SCRIPT = (Path(__file__).parent / "session_hook.py").resolve()

# Subconjunto do vocabulario ja existente em session_hook.ACTION_STATE —
# o Command Code nao emite UserPromptSubmit/PermissionRequest/SessionEnd.
EVENTS = {
    "SessionStart": "free",
    "PreToolUse": "pre_tool_use",
    "PostToolUse": "work",
    "Stop": "free",
}


def _is_ours(group: dict) -> bool:
    for handler in group.get("hooks", []):
        command = str(handler.get("command") or "") if isinstance(handler, dict) else ""
        if "session_hook.py" in command and " commandcode " in (command + " "):
            return True
    return False


def build_hooks_config(existing: dict, command_prefix: str, remove: bool = False) -> dict:
    """Preserva hooks alheios; substitui apenas os nossos. Idempotente."""
    data = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("'hooks' precisa ser um objeto")
    for event, action in EVENTS.items():
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError("hooks.{} precisa ser uma lista".format(event))
        groups[:] = [g for g in groups if not (isinstance(g, dict) and _is_ours(g))]
        if not remove:
            groups.append({"hooks": [{
                "type": "command",
                "command": command_prefix + " " + action,
                "timeout": 3,
            }]})
    return data
```

### Pattern 5: Ramo do provedor em `session_hook.py`

```python
COMMANDCODE_SETTINGS = Path.home() / ".commandcode" / "settings.json"


def hook_health() -> dict:
    """Saude por agente. Um provedor novo entra aqui — nao num detector paralelo."""
    return {"claude": hook_installed(CLAUDE_SETTINGS, "claude"),
            "codex": hook_installed(CODEX_HOOKS, "codex"),
            "commandcode": hook_installed(COMMANDCODE_SETTINGS, "commandcode")}


def _default_path(provider: str) -> Path:
    if provider == "codex":
        base = ".codex"
    elif provider == "commandcode":
        base = ".commandcode"
    else:
        base = ".claude"
    return Path.home() / base / "monitor-ai-events.json"
```

### Pattern 6: Ligação no daemon (`tools/session_daemon.py`)

```python
from commandcode_sessions import (
    count_active_12h as count_commandcode_12h,
    projects_dir as commandcode_default_path,
    scan_commandcode_sessions,
    window_tokens as commandcode_window_tokens,
)

# dentro de build_payload_v1, junto de scan_opencode_sessions:
if commandcode_dir is not None:
    todas += scan_commandcode_sessions(
        now, token_since, directory=commandcode_dir,
        ctx_window=config_commandcode_ctx_window)

# fallback 422 GENERICO (Decisao 7): hoje o gatilho e tool == "opencode"
KNOWN_TOOLS = {"claude", "codex", "opencode", "commandcode"}
if status == 422 and any(s.get("tool") not in KNOWN_TOOLS for s in payload["sessions"]):
    ...  # reenvia sem o provedor desconhecido, avisando uma vez

# format_summary: "commandcode" -> "CC"
```

### Pattern 7: Firmware — enum + parse (padrão do próprio arquivo)

```cpp
// include/session_model.h — enum ToolType (session_model.h:7)
enum class ToolType : uint8_t { CLAUDE = 0, CODEX = 1, OPENCODE = 2, COMMANDCODE = 3, UNKNOWN = 255 };

// src/sessions/session_transport.cpp — parse_tool (session_transport.cpp:91-96)
ToolType parse_tool(const char *name) {
    if (!name) return ToolType::UNKNOWN;
    if (strcmp(name, "claude") == 0) return ToolType::CLAUDE;
    if (strcmp(name, "codex") == 0) return ToolType::CODEX;
    if (strcmp(name, "opencode") == 0) return ToolType::OPENCODE;
    if (strcmp(name, "commandcode") == 0) return ToolType::COMMANDCODE;
    return ToolType::UNKNOWN;   // firmware antigo: 422 -> daemon degrada
}
```

### Pattern 8: Teste orientado a tabela na convenção do projeto

```python
# A KB (testing/concepts/parametrize.md) ensina @pytest.mark.parametrize, mas os
# 18 arquivos de teste deste repo usam unittest.TestCase com subTest e ZERO
# parametrize. Padrao do projeto ganha do padrao da KB.
import unittest

CASES = (
    # (tool_use pendente, hook posterior, idade_s, esperado)
    ("ask_user_question", False, 5.0,   "ask"),
    ("shell_command",     False, 5.0,   "perm"),
    ("shell_command",     True,  5.0,   "work"),
    ("shell_command",     False, 700.0, "free"),   # teto de 600s
    (None,                True,  5.0,   "free"),   # so o evento manda
)


class StateTests(unittest.TestCase):
    def test_matrix(self):
        for tool, hooked, age, esperado in CASES:
            with self.subTest(tool=tool, hooked=hooked, age=age):
                self.assertEqual(esperado, _derive_from(tool, hooked, age))
```

---

## Data Flow

```text
1. Command Code roda uma sessao
   │  hooks -> session_hook.py commandcode <action> -> monitor-ai-events.json
   │  mensagens -> ~/.commandcode/projects/<slug>/<id>.jsonl
   ▼
2. Ciclo do daemon (5s):
   scan_commandcode_sessions(now, token_since, directory, ctx_window)
   │  - reconstroi meta/modelo/effort/usage do transcript (dedup por messageId)
   │  - estado: reduce_session_events(event_store) + inferencia (ask/perm)
   │  - tokensWin / context (estimated|unknown)
   ▼
3. build_payload_v1 concatena com Claude/Codex/OpenCode
   │  ranking -> severidade -> catalogo (tag "CC")
   ├─ collect_quota(..., commandcode window_tokens)  -> bloco estimado
   ├─ _record_daily_history(..., commandcode)         -> heatmap
   └─ usage_top.build_cached(..., commandcode)        -> podio
   ▼
4. POST /sessions  (tool="commandcode")
   │
   ├─ 2xx  -> card no painel (icone por provider)
   └─ 422  -> daemon remove o provedor desconhecido e reenvia (avisa 1x)
```

---

## Integration Points

| External System | Integration Type | Authentication |
|-----------------|-----------------|----------------|
| Transcripts do Command Code | Leitura read-only de JSONL local | N/A (arquivos do usuário; sem credenciais) |
| Hooks do Command Code | `settings.json` + processo de hook (stdin JSON) | Escopo de usuário; sem rede |
| Painel ESP32-S3 (`POST /sessions`) | HTTP JSON, `tool="commandcode"` | Header `X-Monitor-Token` (já existente) |

---

## Testing Strategy

| Test Type | Scope | Files | Tools | Coverage Goal |
|-----------|-------|-------|-------|---------------|
| Unit | `_derive_state`, `_usage_events` (dedup/tokens), contexto, path resolution | `tests/test_commandcode_sessions.py` | `unittest` + `subTest` + `tmp_path`-style temporários | 100% dos ramos dos estados e da semântica de token |
| Unit | `build_hooks_config`, `_is_ours`, backup, remove, idempotência | `tests/test_commandcode_hook.py` | `unittest` + arquivos temporários | Aditivo, idempotente, reversível |
| Unit | `_default_path`/`hook_health` com `commandcode` | `tests/test_commandcode_hook.py` | `unittest` | Presença e ausência |
| Integration | Sessão CC no payload e **fallback 422** | `tests/test_session_daemon.py` (mod.) | `unittest` + fixtures herméticas | Caminho hoje descoberto |
| Integration | Checagem de path no `doctor` | `tests/test_doctor.py` (mod.) | `unittest` + fixtures existentes | Presente / ausente |
| Hardware (manual) | Card renderizado, ícone, degradação com firmware antigo | — | Placa + `GET /diag` | AT-014, AT-015 |

**Cobertura dos testes de aceitação do DEFINE:**

| AT | Como é coberto |
|----|----------------|
| AT-001 sessão aparece | `test_commandcode_sessions` — fixture real com turno recente |
| AT-002 `work` por hook | `test_commandcode_sessions` — event store com `PreToolUse` |
| AT-003 `ask` | `test_commandcode_sessions` — `ask_user_question` pendente |
| AT-004 `perm` | `test_commandcode_sessions` — tool_use sem hook posterior |
| AT-005 `perm` não eterno | `test_commandcode_sessions` — idade 700s |
| AT-006 `free` por `Stop` | `test_commandcode_sessions` — event store `free` |
| AT-007 sem hook, só recência | `test_commandcode_sessions` — store vazio + mtime recente |
| AT-008 tokens da janela | `test_commandcode_sessions` — `cacheReadTokens` fora |
| AT-009 dedup | `test_commandcode_sessions` — duas linhas, mesmo `messageId` |
| AT-010 contexto estimado | `test_commandcode_sessions` — sem denominador → `unknown` |
| AT-011/012 install | `test_commandcode_hook` — preserva alheios; reinstala sem duplicar |
| AT-013 health | `test_commandcode_hook` — `hook_health()["commandcode"]` |
| AT-014/015 firmware | Manual + `test_session_daemon` (fallback 422) |
| AT-016 não lê segredo | Teste de path: o collector só enumera `projects/**/*.jsonl`; `check_secrets.py` no CI |
| AT-017 histórico/pódio | `test_session_daemon` + `test_usage_*` estendidos |
| AT-018 encerrada sumiu | `test_commandcode_sessions` — evento `ended` remove a sessão |

---

## Error Handling

| Error Type | Handling Strategy | Retry? |
|------------|-------------------|--------|
| Diretório `projects/` ausente | `scan_commandcode_sessions` devolve `[]` | Não (próximo ciclo) |
| Linha JSONL inválida | Ignorada no parser (padrão `safe_parse` da KB) | N/A |
| Transcript sem `usage`/`timestamp` | Sessão sem tokens/idade; nunca levanta | N/A |
| `settings.json` inválido ao instalar | `ValueError`/`JSONDecodeError` → erro e `return 1`, sem gravar | Não |
| `settings.json` já existente | Backup `.json.monitor-ai-<stamp>.bak` + escrita atômica | N/A |
| Hook de terceiro no mesmo evento | Preservado; só os grupos do Monitor.AI são substituídos | N/A |
| Firmware sem `commandcode` (422) | Daemon reenvia sem o provedor, avisando **1x** | Sim (1 reenvio) |
| Janela de contexto não configurada | `context.quality="unknown"`, sem `ctxPct` | N/A |
| Fuso do transcript (UTC) vs. dia local | Converter para o fuso do daemon antes de agregar | N/A |

---

## Configuration

| Config Key | Type | Default | Description |
|------------|------|---------|-------------|
| `usage.commandcode_context_window` | int | `0` | Denominador de contexto (0 = não configurado → `unknown`) |
| `MONITOR_COMMANDCODE_DIR` | env | `~/.commandcode/projects` | Sobrescreve o diretório dos transcripts (testes/instalações atípicas) |
| `--commandcode-projects` | CLI | env/default | Mesmo override pelo CLI do daemon |

---

## Security Considerations

- **`auth.json` nunca é lido.** O collector enumera apenas `projects/**/*.jsonl`; a API key do Command Code não entra em nenhum caminho de código (AT-016). `check_secrets.py` segue como guard-rail no CI.
- **Installer não interpola dados do usuário em shell.** O comando é montado com `sys.executable` + o caminho resolvido de `session_hook.py` (`install_codex_hook.py:88`), nunca a partir de conteúdo de arquivo ou de transcript.
- **Escrita atômica + backup** antes de substituir `settings.json`, preservando os hooks de terceiros (o arquivo é compartilhado).
- **Sem segredos no payload.** O card carrega projeto, branch, modelo e tokens; nenhum caminho absoluto de segredo e nenhum token.
- **Escopo de usuário** (regra 6): nenhum admin, nenhum serviço novo.
- **Token do painel** continua via header com comparação constant-time (já existente).

---

## Observability

| Aspect | Implementation |
|--------|----------------|
| Logging | Tag `CC` no `format_summary`; aviso de hook ausente via `hook_warnings` (mesma regra de "avisar só quando muda") |
| Metrics | `GET /diag` já é genérico (freshness/loop/alert); o card CC aparece nos contadores de payload sem campo novo |
| Health | `hook_health()["commandcode"]` alimenta `monitor.py hooks check` e o `doctor` |
| Diagnóstico local | `python tools/monitor.py doctor` ganha a checagem do diretório de transcripts do Command Code |

---

## Pipeline Architecture (if applicable)

**Não aplicável.** A feature não introduz pipeline, ETL, fonte de dados nova nem modelo
analítico: lê arquivos locais de transcript e eventos, como os três coletores existentes.
As seções de DAG, particionamento, estratégia incremental, evolução de schema e gates de
qualidade não têm conteúdo honesto a receber e foram deixadas vazias em vez de preenchidas
com material inventado.

---

## Contract Gate

`tools/spec-linter/` **não existe neste repositório**, como já registrado nas fases
Brainstorm e Define. O `exit_code_contract` do `WORKFLOW_CONTRACTS.yaml` classifica linter
indisponível como **exit 2 (ERROR)**, cuja regra é *"record a VISIBLE skip and proceed —
never assume PASS on exit 2"*.

- **Verdict:** não obtido (linter ausente).
- **Ação:** skip registrado visivelmente; conformidade verificada à mão contra as seções do `DESIGN_TEMPLATE.md` — todas presentes.
- **Nunca assumido:** PASS.

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-09-19 | design-agent | Versão inicial a partir de `DEFINE_COMMANDCODE_INTEGRATION.md`. 7 ADRs inline. `agent_events`/`session_state`/`session_meta`/`protocol_v2`/`icons.h`/`ui_dashboard.cpp` **não** mudam (verificado por leitura). Decisão 7 generaliza o fallback 422 e adiciona o teste que hoje falta |

---

## Next Step

**Ready for:** `/ship .claude/sdd/features/DEFINE_COMMANDCODE_INTEGRATION.md`

### Implementação observada em 2026-09-29

O produto não emite evento de início de prompt. Uma mensagem conversacional mais nova
que o último hook invalida `free`/`ended` antigo e usa a recência do transcript; eventos
de hook posteriores, `ask` e a janela limitada de `perm` mantêm precedência.
