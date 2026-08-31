# DESIGN: Dados OpenCode II — perm via log do OpenCode

> Technical design for implementing DADOS_OPENCODE_PERM_VIA_LOG
> (input apontado ao BRAINSTORM; especificação vigente = `DEFINE_DADOS_OPENCODE_PERM_VIA_LOG.md`)

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | DADOS_OPENCODE_PERM_VIA_LOG |
| **Date** | 2026-08-31 |
| **Author** | design-agent |
| **DEFINE** | [DEFINE_DADOS_OPENCODE_PERM_VIA_LOG.md](./DEFINE_DADOS_OPENCODE_PERM_VIA_LOG.md) |
| **Status** | Ready for Build |
| **Design Confidence** | 0,95 (formato do log e mapeamento run→sessão validados com dados reais) |

---

## Architecture Overview

```text
~/.local/share/opencode/log/opencode.log  (tail 512KB por ciclo)
  │
  │  linhas relevantes:
  │   "run=e1ab5296 message=process session.id=ses_fa80141c..."   → mapa run→sessão
  │   "... run=e1ab5296 message=evaluated permission=external_directory
  │        pattern="..." action.action=ask"                        → pedido pendente
  ▼
perm_signals_from_log(log_path, now) → {session_id: epoch_do_ultimo_ask}
  │
  ▼
scan_opencode_sessions:
  sinais = question(pending/running) [já existe]  ∪  perm do log  [NOVO]
  para cada sinal: frescor ≤ 10 min E sem atividade da sessão posterior ao sinal
  → estado = perm / ask / work / free
```

---

## Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| `perm_signals_from_log` (novo) | Tail 512KB + regex: run→sessão, último `ask` por sessão | Python stdlib (`re`, `Path`) |
| `scan_opencode_sessions` (modif.) | Integra o sinal `perm` com as regras de frescor/prioridade | Python stdlib |
| `tests/test_opencode_sessions.py` (modif.) | Fixtures de log (tmp) para os ATs 001..007 | pytest |

---

## Key Decisions

### Decision 1: Tail de 512KB + regex tolerante

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-31 |

**Context:** O log cresce sem rotação conhecida; só as avaliações recentes importam.

**Choice:** Ler os últimos 512KB, iterar linhas; linha válida precisa conter
` message=evaluated permission=` (extração de `run=`, `action.action=` e timestamp
do prefixo `timestamp=...Z`); linhas sem match são ignoradas. Log inexistente →
sem sinal, sem exceção (AT-005); linha truncada → ignorada (AT-006).

**Rationale:** Custo constante (~5-10ms/ciclo); tolerante a mudança de formato
(R1 — linha sem match degrada suavemente para work/free).

**Alternatives Rejected:**
1. Ler o arquivo inteiro — desnecessário e caro com o tempo
2. Parser estruturado por chave=valor em todas as linhas — custo alto para 2 campos

**Consequences:**
- Se o tail de 512KB cobrir menos que a janela de 10 min (log muito ativo), o
  sinal deixa de aparecer — mitigação: aumentar tail (R3, constante ajustável)

---

### Decision 2: Mapeamento run→sessão com "última atribuição vence"

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-31 |

**Context:** As linhas do log referenciam `run=<id>`; a sessão só aparece em
linhas `message=process session.id=ses_...` (mesmo run).

**Choice:** Percorrer as linhas do tail em ordem; manter `run_map[run] = session_id`
a cada linha `process session.id=`; as avaliações de permissão consultam o mapa
**no estado corrente da iteração** (run ids são reutilizados por turnos diferentes
— a atribuição mais recente antes da avaliação é a válida).

**Rationale:** Validado nos dados: `run=e1ab5296` mapeou exclusivamente para
`ses_fa80141c` (worktree fix-28796) e `run=ab9a76df` para `ses_fa851d22` (migração).

**Alternatives Rejected:**
1. Mapa global construído antes das avaliações — errado: runs mudam de sessão
   entre turnos; a atribuição cronológica é a correta

**Consequences:**
- Uma avaliação cujo `run` ainda não apareceu (process antes do tail) é ignorada

---

### Decision 3: Perm exige frescor de 10 min E ausência de atividade posterior

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-31 |

**Context:** O log registra o pedido UMA vez (write-once) — não há linha "resolvido".
Como saber que o operador já aprovou/negou?

**Choice:** `perm` vale enquanto: (a) idade do ask ≤ **600s**; e (b) nenhuma
atividade da sessão depois do ask (`session.time_updated` ≤ ask_ts + 5s de folga —
a aprovação gera parts novos, que avançam o `time_updated`). Também vence se um
sinal `ask` (question tool) for mais recente.

**Rationale:** A aprovação gera execução imediata → parts atualizam; a negação
também gera texto/turno novo. Sem atividade + ask recente = aguardando o operador.

**Alternatives Rejected:**
1. Procurar `action.action=allow` posterior para o MESMO pattern — o pattern se
   repete (mesmo comando reexecutado) e dá falso negativo
2. Perm permanente até evento — trava o card em amarelo para sempre

**Consequences:**
- Permissão aberta > 10 min volta a `work` (limitação aceita; o operador olha o
  OpenCode de qualquer forma)

---

### Decision 4: Coexistência ask × perm — o mais recente vence

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-31 |

**Context:** Uma sessão pode ter question aberto (ask) e, depois, permissão
(perm) — ou o inverso.

**Choice:** Sinais fundidos por timestamp: o mais recente entre
`question(pending/running)` e `perm(log)` define o estado.

**Rationale:** Consistente com a semântica "o último evento manda" já usada no
detector de tool parts.

**Alternatives Rejected:**
1. Prioridade fixa perm > ask — um ask mais recente seria escondido

**Consequences:**
- Nenhum estado novo no firmware: `ask` e `perm` já existem no vocabulário

---

## File Manifest

| # | File | Action | Purpose | Agent | Dependencies |
|---|------|--------|---------|-------|--------------|
| 1 | `tools/opencode_sessions.py` | Modify | `perm_signals_from_log` + integração no scan (frescor/prioridade) | @python-developer | None |
| 2 | `tests/test_opencode_sessions.py` | Modify | Fixtures de log: AT-001..007 | @test-generator | 1 |
| 3 | `docs/SPEC.md` | Modify | Seção 17: fonte do `perm` (log), regra de frescor, limitação de formato | @code-documenter | 1 |
| 4 | `pytest` + validação na placa | Verify | Operador dispara uma permissão real → card em `perm` | @ci-cd-specialist | 1 |

**Total Files:** 1 código + 1 teste + 1 doc + 1 verificação

---

## Agent Assignment Rationale

| Agent | Files Assigned | Why This Agent |
|-------|----------------|----------------|
| @python-developer | 1 | Coletor OpenCode (regex/tail, stdlib) |
| @test-generator | 2 | Fixtures de log e casos de frescor/prioridade |
| @code-documenter | 3 | SPEC |
| @ci-cd-specialist | 4 | Validação com permissão real |

---

## Code Patterns

### Pattern 1: Tail + regex tolerante

```python
LOG_TAIL_BYTES = 512 * 1024

def perm_signals_from_log(log_path: Path, now: datetime) -> dict[str, float]:
    path = Path(log_path) if log_path else LOG_PATH
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as f:
            f.seek(0, 2); size = f.tell()
            f.seek(max(0, size - LOG_TAIL_BYTES))
            chunk = f.read().decode("utf-8", errors="replace")
    except OSError:
        return {}
    run_map: dict[str, str] = {}
    asks: dict[str, float] = {}
    for line in chunk.splitlines():
        if " message=process session.id=" in line:
            run = _between(line, "run=", " message=")
            sid = _between(line, "session.id=", " messageID=")
            if run and sid: run_map[run] = sid
        elif " message=evaluated permission=" in line and "action.action=ask" in line:
            run = _between(line, "run=", " message=")
            sid = run_map.get(run)
            ts = _log_ts(line)                       # timestamp=...Z → epoch
            if sid and ts: asks[sid] = max(asks.get(sid, 0), ts)
    return asks
```

### Pattern 2: Frescor + atividade posterior

```python
for sid, ask_ts in perm_asks.items():
    if now_ts - ask_ts > 600: continue                       # expirado
    activity = max(session.updated_ms, parts_max_ms.get(sid, 0)) / 1000
    if activity > ask_ts + 5: continue                       # aprovada: part novo
    signals[sid] = ("perm", ask_ts)                          # disputa por timestamp com ask
```

### Pattern 3: Coexistência por timestamp

```python
# signals finais: {sid: (estado, ts)} — question(ask) e perm(log) disputam pelo ts
```

---

## Data Flow

```text
1. Ciclo do daemon: tail do opencode.log (512KB)
2. run→session + última avaliação ask por sessão
3. scan: ask (question) ∪ perm (log) — mais recente vence, frescor 10 min,
   atividade posterior invalida perm
4. Payload: state = ask/perm/work/free → painel (amarelo = perm)
```

---

## Integration Points

| External System | Integration Type | Authentication |
|-----------------|-----------------|----------------|
| `~/.local/share/opencode/log/opencode.log` | Leitura de arquivo (tail) | N/A (local) |

---

## Testing Strategy

| Test Type | Scope | Files | Tools | Coverage Goal |
|-----------|-------|-------|-------|---------------|
| Unit | Parser do log: perm, mapeamento, expiração, aprovação, ausente, truncado | `tests/test_opencode_sessions.py` | pytest + fixtures de log | AT-001..007 |
| Unit | Coexistência ask × perm (mais recente vence) | idem | pytest | AT-007 |
| E2E Hardware | Operador dispara permissão real → card `perm`; aprova → `work` | placa | manual | gate do build |
