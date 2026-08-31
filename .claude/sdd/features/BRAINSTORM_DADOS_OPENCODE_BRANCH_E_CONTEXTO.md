# BRAINSTORM: Dados do OpenCode — branch de worktree, contexto e nomenclatura por branch

> Sessão exploratória com análise de dados reais (opencode.db + filesystem)

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | DADOS_OPENCODE_BRANCH_E_CONTEXTO |
| **Date** | 2026-08-31 |
| **Author** | brainstorm-agent |
| **Status** | ✅ Complete (Defined) |
| **Origem** | Relato do operador: branch incorreta, contexto vazio, nomes "misturados" nos worktrees |

---

## Initial Idea

**Raw Input:** "Os dados do OpenCode não estão sendo recuperados corretamente: (1) ao
abrir o card de uma sessão, branch incorreta e contexto sempre vazio; (2) dois
worktrees ativos no projeto lakehouse-tech-fabric mas os dois cards vêm com o nome
'fix-28796-ajustes' e um deveria ser 'feat-27816-remover-monolitico'."

---

## Data Analysis (ground truth — 4 sessões ativas em 24h)

| Sessão (title) | `directory` no banco | Branch real (git) |
|---|---|---|
| Fluxo git: push, pipeline CI/CD | `orca/workspaces/lakehouse-tech-fabric/fix-28796-ajustes` | `fix-28796-ajustes` |
| Retomar sessão Codex no OpenCode | `Desktop/Projetos/monitor-tokens-esp32` | `master` |
| Encontrar script updateFromGit | `orca/workspaces/lakehouse-tech-fabric/fix-28796-ajustes` | `fix-28796-ajustes` |
| Migração Fase 7: remover monolítico | `Desktop/Projetos/lakehouse-tech-fabric` (repo principal) | `feat/27816-remover-monolitico` |

### ACHADO 1 — Branch: `.git` de worktree é ARQUIVO (bug confirmado)

Em worktrees, `<dir>/.git` é um arquivo (`gitdir: <repo>/.git/worktrees/<nome>`), não
uma pasta. `read_git_branch()` tenta `<dir>/.git/HEAD` → falha → retorna "sem git".
Correção: parsear o `gitdir` e ler `<gitdir>/HEAD` (que é o HEAD do worktree).
Beneficia também sessões Codex em worktrees (mesma função).

### ACHADO 2 — Contexto: config ausente (comportamento "honesto", mas inútil)

`monitor.toml` do operador NÃO tem `usage.opencode_context_window` → default 0 →
`ctxPct` fica "desconhecido" de propósito. Correção: default de **128000** para
sessões OpenCode (GLM/DeepSeek — janela típica), com override por config; documento
marca a aproximação.

### ACHADO 3 — Nomes: NÃO há mistura de dados

Os dois cards "fix-28796-ajustes" são **duas sessões distintas no MESMO worktree**
(nome correto pela regra atual de basename). A sessão que o operador esperava como
"feat-27816-remover-monolitico" é a "Migração Fase 7" — que roda no REPO PRINCIPAL
com a branch `feat/27816-remover-monolitico` (não é um worktree). A demanda real é
de IDENTIDADE: o card deve mostrar a branch quando ela é o que distingue o trabalho.

---

## Discovery Questions & Answers

| # | Question | Answer | Impact |
|---|----------|--------|--------|
| 1 | Qual identidade o card exibe? | **(c)** Branch não-principal no nome do card; projeto quando a branch é principal (master/main) — para as 3 fontes | Regra unificada de nomenclatura; `fix-28796-ajustes` / `feat-27816-remover-monolitico` / `monitor-tokens-esp32` |

---

## Approaches Explored

### Approach A: Correção objetiva + regra de branch no nome ⭐ Recommended

**Description:** (1) `read_git_branch` worktree-aware via gitdir; (2) contexto
OpenCode com default 128k configurável; (3) nome do card = branch quando não
principal, projeto quando principal — regra única para Claude/Codex/OpenCode.

**Why Recommended:** Resolve os 3 sintomas com correções objetivas baseadas em dados;
a regra (c) reproduz exatamente a expectativa do operador.

---

## Selected Approach

| Attribute | Value |
|-----------|-------|
| **Chosen** | Approach A |
| **User Confirmation** | 2026-08-31 ("c") |
| **Reasoning** | Única regra que distingue worktrees/feature branches como o operador espera |

---

## Key Decisions Made

| # | Decision | Rationale | Alternative Rejected |
|---|----------|-----------|----------------------|
| 1 | `read_git_branch` lê HEAD via gitdir quando `.git` é arquivo | Comportamento real do git em worktrees | Tratar worktree como "sem git" |
| 2 | Contexto OpenCode default 128k, override em `usage.opencode_context_window` | % útil desde o 1º boot; aproximação documentada | Permanecer vazio até configurar |
| 3 | Nome do card = branch não-principal; projeto na principal | Distingue trabalho paralelo; evita cards "master" | Nome sempre projeto (indistinguível) |

---

## Features Removed (YAGNI)

| Feature Suggested | Reason Removed | Can Add Later? |
|-------------------|----------------|----------------|
| Mostrar projeto+branch juntos no card | Nome truncado em 10 chars viraria ruído | Yes |
| Tabela de janela por modelo (GLM/DeepSeek específicos) | Sem fonte autoritativa local; 128k default + config resolve | Yes |

---

## Incremental Validations

| Section | Presented | User Feedback | Adjusted? |
|---------|-----------|---------------|-----------|
| Análise de dados (3 achados) | ✅ | Confirmando que ses4 é o repo principal | N/A |
| Regra de nomenclatura (Q1) | ✅ | (c) | No |

**Minimum Validations:** 2 ✅

---

## Suggested Requirements for /define

### Problem Statement (Draft)
Sessões OpenCode em worktrees mostram branch "sem git", contexto sempre vazio (sem
janela configurada) e o nome do card não distingue branches de trabalho paralelo.

### Success Criteria (Draft)
- [ ] Sessão em worktree mostra a branch do worktree (fix-28796-ajustes) no detalhe
- [ ] Contexto OpenCode exibido em % com default 128k (override por config)
- [ ] Card: branch não-principal no nome; projeto quando principal — nas 3 fontes
- [ ] Testes: worktree fixture, regra de nome, default de contexto

### Out of Scope (Confirmed)
- Tabela de janela por modelo; mudanças de payload; pódio/heatmap

---

## Session Summary

| Metric | Value |
|--------|-------|
| Questions Asked | 1 |
| Approaches Explored | 3 (regra de nome) |
| Features Removed (YAGNI) | 2 |
| Validations Completed | 2 |
| Duration | ~15 min (análise de dados inclusa) |

---

## Next Step

**Ready for:** `/define .claude/sdd/features/BRAINSTORM_DADOS_OPENCODE_BRANCH_E_CONTEXTO.md`
