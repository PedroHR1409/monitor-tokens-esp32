# DESIGN: Estados do OpenCode (ask/perm/work/free pelo último evento)

> Technical design for implementing ESTADOS_OPENCODE

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | ESTADOS_OPENCODE |
| **Date** | 2026-08-31 |
| **Author** | design-agent |
| **DEFINE** | [DEFINE_ESTADOS_OPENCODE.md](./DEFINE_ESTADOS_OPENCODE.md) |
| **Status** | ✅ Shipped |
| **Design Confidence** | 0,95 (cada regra validada contra dados reais durante o build) |

---

## Architecture Overview

```text
[SQLite: parts da sessão]──┐
│  último part (time_updated) ──→ estado base:
│    question pending/running → ask
│    tool running/pending     → work
│    step-start / reasoning   → work
│    text / step-finish /     → free
│    tool completed           → free
│                           │
[opencode.log tail 512KB]──┤
│  run=<id> → session.id    │
│  action.action=ask ───────┘
│         │
│         ▼
│  {sid: (estado, ts)} — o mais recente vence
│         │
│         ▼
│  scan: perm com frescor 10 min + sem atividade posterior;
│         base work/free/ask sem expiração (é o último fato conhecido)
│         fallback por idade apenas para sessão sem parts
▼
[payload: state = ask/perm/work/free] → painel
```

---

## Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| `session_structured_states` (modif.) | Estado base pelo último part (todas as types, janela 24h) | stdlib `json_extract` |
| `perm_signals_from_log` (novo) | Última `action.action=ask` por sessão, mapeando `run`→`session.id` | stdlib `re`/tail 512KB |
| `scan_opencode_sessions` (modif.) | Fusão por timestamp; frescor do perm (10 min) + invalidação por atividade | Python stdlib |

---

## Key Decisions

### Decision 1: Estado base pelo último part, sem expiração

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-31 |

**Context:** `work` por idade mantinha o card em work por 30 min após o fim do turno.

**Choice:** O último part define o estado: `text`/`step-finish`/`tool completed` = free;
`step-start`/`tool running|pending`/`reasoning` = work; `question` pending/running = ask.
Janela de coleta: 24h (a do board). Fallback por idade só para sessão sem parts.

**Rationale:** O último fato conhecido É o estado; idade mede staleness (source_stale),
não estado.

**Alternatives Rejected:**
1. Manter age ≤ 30 min para work — medido: turnos encerrados ficavam "work"

**Consequences:**
- `SIGNAL_MAX_AGE_S` deixa de limitar work/free/ask (só o perm tem frescor)

---

### Decision 2: `perm` via log, com dupla invalidação

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-31 |

**Context:** O pedido de permissão do OpenCode não é persistido no SQLite; o log
registra `evaluated permission=... action.action=ask` write-once.

**Choice:** Última avaliação `ask` por sessão (via mapeamento `run`→`session.id`
cronológico); `perm` vale ≤ 10 min E enquanto não houver atividade da sessão
(`session.time_updated` > ask_ts + 5s) posterior.

**Rationale:** A aprovação/negação gera execução imediata (parts novos) — a
atividade posterior prova que o pedido foi resolvido.

**Alternatives Rejected:**
1. `tool pending` como perm — é estado de pipeline (falso positivo medido)
2. Perm permanente — card preso em amarelo

**Consequences:**
- Permissão aberta > 10 min volta a work/free (limitação documentada)

---

### Decision 3: Janela de contexto por modelo

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-31 |

**Context:** Default 128k produzia 100%+ para o GLM-5.3-Flash, cujo OpenCode exibia
58% com 584k tokens → janela real ≈ 1M.

**Choice:** Tabela `glm → 1M`, `deepseek → 128k`, fallback 128k; override por
`usage.opencode_context_window`; qualidade `estimated` (auto) / `measured` (config);
clamp em 100%.

**Rationale:** Data-driven: 584.252/1.000.000 = 58% — bate exatamente com a UI.

**Alternatives Rejected:**
1. Tabela exaustiva por modelo — sem fonte autoritativa local

**Consequences:**
- Dias quase sem uso mostram "0,0" — aceito (R2 do DEFINE anterior)

---

## File Manifest

| # | File | Action | Purpose | Agent | Dependencies |
|---|------|--------|---------|-------|--------------|
| 1 | `tools/opencode_sessions.py` | Modify | Estados pelo último part; `perm_signals_from_log`; janela por modelo; clamp; nome nunca vazio | @python-developer | None |
| 2 | `tools/session_daemon.py` | Modify | Wiring do log path ao scan; hermeticidade dos testes | @python-developer | 1 |
| 3 | `tests/test_opencode_sessions.py` | Modify | AT-001..008 + fixtures de parts/log | @test-generator | 1, 2 |
| 4 | `docs/SPEC.md`, `README.md` | Modify | Estados/contexto/nomenclatura documentados | @code-documenter | 1, 2 |
| 5 | `pytest` + validação na placa | Verify | ATs com dados reais do operador | @ci-cd-specialist | 1-4 |

**Total Files:** 2 código + 1 teste + 2 docs + 1 verificação

---

## Agent Assignment Rationale

| Agent | Files Assigned | Why This Agent |
|-------|----------------|----------------|
| @python-developer | 1, 2 | Coletor OpenCode (sqlite/json_extract, tail, stdlib) |
| @test-generator | 3 | Fixtures de parts/log e casos de fronteira |
| @code-documenter | 4 | SPEC/README |
| @ci-cd-specialist | 5 | Validação com os dados reais do operador |

---

## Code Patterns

### Pattern 1: Estado pelo último part

```python
if tool == "question" and state in ("pending", "running"):
    signal = "ask"
elif ptype == "tool" and state in ("running", "pending"):
    signal = "work"
elif ptype in ("step-start", "reasoning"):
    signal = "work"
elif ptype in ("text", "step-finish", "tool completed"):
    signal = "free"
latest[sid] = (signal, ts)   # o último vence sempre
```

### Pattern 2: Perm com dupla invalidação

```python
expired = (now - ask_ts).total_seconds() > PERM_FRESH_S          # 10 min
resolved = session_time_updated_ms / 1000 > ask_ts + 5           # atividade posterior
if expired or resolved: signal = None
```

### Pattern 3: Janela por modelo

```python
MODEL_CONTEXT_WINDOWS = (("glm", 1000000), ("deepseek", 128000))
window = configured if configured > 0 else next(
    (w for n, w in MODEL_CONTEXT_WINDOWS if n in model_id.lower()), DEFAULT)
```

---

## Data Flow

```text
1. parts + log → sinais por sessão (base work/free/ask + perm do log)
2. fusão por timestamp (o mais recente vence)
3. scan aplica: base sem expiração; perm com frescor/invalidação
4. payload state → painel
```

---

## Integration Points

| External System | Integration Type | Authentication |
|-----------------|-----------------|----------------|
| `opencode.log` | Leitura de arquivo (tail 512KB) | N/A (local) |

---

## Testing Strategy

| Test Type | Scope | Files | Tools | Coverage Goal |
|-----------|-------|-------|-------|---------------|
| Unit | Estados base pelo último part (work/free/ask) | `tests/test_opencode_sessions.py` | pytest | AT-001..004 |
| Unit | Perm via log (frescor, resolução, ausente, truncado) | idem | pytest | AT-005/006 |
| Unit | Janela por modelo + clamp | idem | pytest | AT-007/008 |
| E2E | Operador valida contra a UI do OpenCode | placa | manual | gate |
