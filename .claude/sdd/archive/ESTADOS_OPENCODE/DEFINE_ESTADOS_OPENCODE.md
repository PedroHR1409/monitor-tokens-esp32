# DEFINE: Estados do OpenCode (ask/perm/work/free pelo último evento)

> Detecção do estado REAL das sessões OpenCode: ask/perm via sinais estruturados,
> work/free pelo ciclo do turno (último part) — substituindo a heurística por idade.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | ESTADOS_OPENCODE |
| **Date** | 2026-08-31 |
| **Author** | define-agent |
| **Status** | ✅ Shipped |
| **Clarity Score** | 15/15 |
| **Input** | Iteração pós-ship de `DADOS_OPENCODE_BRANCH_E_CONTEXTO`, com 3 rodadas de validação do operador (cada correção testada ao vivo contra o OpenCode) |

---

## Problem Statement

As sessões OpenCode só exibiam `work`/`free` (por idade da última escrita): o
contexto saía errado (janela 128k para um modelo de ~1M), `ask`/`perm` nunca eram
detectados, e o card mantinha `work` por até 30 min após o fim do turno.

---

## Target Users

| User | Role | Pain Point |
|------|------|------------|
| Operador do painel | Trabalha com múltiplos agentes OpenCode em paralelo | Não sabe quando um agente está trabalhando, perguntando ou esperando aprovação |

---

## Goals

| Priority | Goal |
|----------|------|
| **MUST** | `ask`: tool `question` em `pending` OU `running` (pergunta aberta — validado nos dois estados) |
| **MUST** | `perm` via log do OpenCode (`action.action=ask`), com frescor de 10 min e invalidação por atividade posterior |
| **MUST** | `work`/`free` pelo ÚLTIMO part do turno: step-start/tool running/tool pending/reasoning = work; text/step-finish/tool completed = free |
| **MUST** | Contexto por modelo: GLM ~1M (validado: 584k tokens = 58% na UI), deepseek 128k, override por config |
| **MUST** | Último part por `time_updated` (partes são atualizadas in-place) |
| **SHOULD** | Fallback por idade apenas para sessão sem parts; testes herméticos do banco/log reais |

---

## Success Criteria

- [ ] Conversa ociosa (turno encerrado) = `free` mesmo com parts recentes
- [ ] Conversa processando = `work` (idade do estado ~0s)
- [ ] Pergunta aberta (pending/running) = `ask` nos dois estados observados
- [ ] Permissão aberta = `perm`; aprovada → `work`
- [ ] Contexto bate com a UI do OpenCode (586k tok = 58%)
- [ ] 198+ testes verdes; sem regressão

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | Turno encerrado | Último part = text | Scan | `free` (antes: work por 30 min) |
| AT-002 | Processando | Último part = tool running / step-start | Scan | `work` |
| AT-003 | Pergunta aberta (pending) | Último part = question pending | Scan | `ask` |
| AT-004 | Pergunta aberta (running) | Último part = question running | Scan | `ask` |
| AT-005 | Permissão via log | `action.action=ask` recente, sem atividade posterior | Scan | `perm` |
| AT-006 | Permissão resolvida | Atividade da sessão após o ask | Scan | Volta a work/free |
| AT-007 | Janela por modelo | GLM com 584k de contexto | Scan | ctxPct 58% (janela 1M) |
| AT-008 | Clamp | Contexto > janela | Scan | ctxPct = 100 |

---

## Out of Scope

- Badge do tipo de permissão (bash/edit/external_directory)
- Fonte de `perm` alternativa (API HTTP do OpenCode) — o log cobre hoje
- Firmware/payload (estado via vocabulário existente)

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Technical | Formato do log é de terceiros | Parser tolerante; degradação suave |
| Technical | `pending` de tool ≠ permissão (é pipeline) | Removido do mapeamento (falso positivo medido) |
| Operational | Daemon requer restart para carregar | Comunicado ao operador a cada correção |

---

## Assumptions & Risk Register

| ID | Assumption | Impact if Wrong | Validated |
|----|-----------|-----------------|-----------|
| R1 | Janela do GLM-5.3-Flash ≈ 1M (584k = 58% na UI) | % impreciso — tabela por modelo ajustável | ☑ |
| R2 | `question` pendente/running = ask (dois estados medidos) | Perder ask em um dos estados — corrigido após medição | ☑ |
| R3 | Log do OpenCode não rotaciona no curto prazo | Tail 512KB cobre a janela de 10 min do perm | ☐ |

---

## Technical Context

| Aspect | Value | Notes |
|--------|-------|-------|
| **Deployment Location** | `tools/opencode_sessions.py` | Daemon only |
| **KB Domains** | `shared` | — |
| **IaC Impact** | None | — |

---

## Data Contract (if applicable)

Nenhum campo novo. Fontes: parts do SQLite (estado base) + tail do
`~/.local/share/opencode/log/opencode.log` (`perm`).

---

## Clarity Score Breakdown

| Element | Score | Notes |
|---------|-------|-------|
| Problem | 3 | 3 sintomas com causa medida |
| Users | 3 | Operador, dor concreta |
| Goals | 3 | Cada regra com evidência |
| Success | 3 | Verificável contra a UI do OpenCode |
| Scope | 3 | Explícito |
| **Total** | **15/15** | Gate superado |

---

## Open Questions

Nenhuma — cada regra foi validada contra dados reais durante o build.

---

## Revision History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-31 | Ciclo retroativo: 4 correções validadas ao vivo pelo operador | define-agent |
