# BRAINSTORM: Dados OpenCode II — perm via log, sessão "desaparecida"

> Sessão exploratória com análise de dados reais (log do OpenCode + opencode.db)

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | DADOS_OPENCODE_PERM_VIA_LOG |
| **Date** | 2026-08-31 |
| **Author** | brainstorm-agent |
| **Status** | ✅ Shipped |
| **Origem** | "Não está identificando ask e perm (mantém work) — erro agora na conversa docs/27816-execucao-producao, que nem aparece na tela" |

---

## Initial Idea

**Raw Input:** "Ainda não está identificando ask e perm, mantendo como work em
sessões DeepSeek e GLM-5.3-Flash. O erro está acontecendo agora com a conversa
docs/27816-execucao-producao. Essa sessão em específico nem aparece na tela agora."

---

## Data Analysis (ground truth)

| Achado | Evidência |
|--------|-----------|
| A sessão EXISTE e estava no payload | Log do daemon: `27816-execucao-produ[OC:work]` — é a sessão "Migração Fase 7" (repo principal) com a branch NOVA `docs/27816-execucao-producao` (troca de branch renomeia o card pela regra de nomenclatura) |
| `perm` NÃO está no SQLite | Tabela `permission` vazia; parts de tool ficam `pending` por segundos como estado de PIPELINE (não permissão) |
| **`perm` ESTÁ NO LOG do OpenCode** | `~/.local/share/opencode/log/opencode.log` registra cada avaliação: `evaluated permission=external_directory pattern="..." action.action=ask` — 40 ocorrências |
| Mapeável à sessão | Linhas `run=e1ab5296 message=process session.id=ses_fa80141c...` → run = sessão do worktree fix-28796 — EXATAMENTE a que o operador viu pedindo permissão |
| A sessão "não aparecer" era a troca de branch | O card existia; o nome mudou de `27816-remover-monoli` para `27816-execucao-produ` quando a branch mudou (regra de nomenclatura funcionando) |

---

## Discovery Questions & Answers

| # | Question | Answer | Impact |
|---|----------|--------|--------|
| 1 | Fonte do sinal `perm` | Log do OpenCode: `action.action=ask` (não persiste no SQLite) | Novo coletor: parser do tail do log |

---

## Approaches Explored

### Approach A: Parser do log do OpenCode ⭐ Recommended

**Description:** Tail do `opencode.log` (~últimos 512KB por ciclo): mapear
`run=<id> → session.id`, localizar a última avaliação `action.action=ask` por
sessão; se recente (≤ 10 min) e sem atividade posterior da sessão (parts com
`time_updated` maior), estado = `perm`.

**Pros:** Única fonte real do sinal; stdlib; custo baixo (tail + regex).
**Cons:** Parse de log de terceiros (formato pode mudar entre versões do OpenCode).
**Why Recommended:** É ONDE o dado vive — não há alternativa persistida.

### Approach B: API local do OpenCode (se `opencode serve` ativo)

Descartada por ora: requer servidor HTTP ativo e descoberta de porta; o log já
resolve sem premissas.

---

## Selected Approach

| Attribute | Value |
|-----------|-------|
| **Chosen** | Approach A |
| **User Confirmation** | 2026-08-31 (apresentado com os dados; operador pediu a correção) |
| **Reasoning** | O log é a única fonte persistida do sinal de permissão |

---

## Key Decisions Made

| # | Decision | Rationale | Alternative Rejected |
|---|----------|-----------|----------------------|
| 1 | `perm` via log (tail 512KB, regex de `evaluated permission` + `action.action=ask`) | Fonte real do sinal | Tabela permission (vazia); tool `pending` (é pipeline) |
| 2 | Janela de frescor do sinal: 10 min sem atividade posterior da sessão | Após aprovar/negar, a sessão volta a trabalhar (parts > log) | Sinal vale para sempre |
| 3 | `ask` permanece pela tool `question` (pending/running) | Validado ao vivo nos dois estados | Mover para o log (question não gera avaliação de permissão) |

---

## Features Removed (YAGNI)

| Feature Suggested | Reason Removed | Can Add Later? |
|-------------------|----------------|----------------|
| Parse do `run=` completo (histórico) | Só o tail recente interessa | Yes |
| Diferenciar permission=bash/edit/external_directory no card | O estado `perm` é único | Yes |

---

## Incremental Validations

| Section | Presented | User Feedback | Adjusted? |
|---------|-----------|---------------|-----------|
| Achados (log = fonte de perm; sessão existia; nome mudou por branch) | ✅ | Operador reportou os sintomas; dados confirmados | N/A |
| Approach A | ✅ | Este documento | No |

**Minimum Validations:** 2 ✅

---

## Suggested Requirements for /define

### Problem Statement (Draft)
O estado `perm` do OpenCode é invisível: o pedido de permissão não é persistido no
SQLite e tools `pending` são estado de pipeline — o painel mostra `work` enquanto o
OpenCode aguarda aprovação do usuário.

### Success Criteria (Draft)
- [ ] Sessão com `action.action=ask` recente no log (sem atividade posterior) → estado `perm` no card
- [ ] Após aprovar (atividade posterior / allow no log) → volta a `work`
- [ ] Sem regresseão: ask (question tool), contexto, nomenclatura intactos

### Out of Scope (Confirmed)
- API HTTP do OpenCode; histórico completo de permissões; badge por tipo de permissão

---

## Session Summary

| Metric | Value |
|--------|-------|
| Questions Asked | 1 (fonte) |
| Approaches Explored | 2 |
| Features Removed (YAGNI) | 3 |
| Validations Completed | 2 |
| Duration | ~15 min (análise de dados inclusa) |

---

## Next Step

**Ready for:** `/define .claude/sdd/features/BRAINSTORM_DADOS_OPENCODE_PERM_VIA_LOG.md`
