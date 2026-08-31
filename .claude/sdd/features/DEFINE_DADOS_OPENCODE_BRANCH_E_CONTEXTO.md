# DEFINE: Dados do OpenCode — branch de worktree, contexto e nomenclatura por branch

> Correção dos dados de sessão OpenCode: branch de worktrees via gitdir, contexto
> com default de 128k e nomenclatura de card por branch nas 3 fontes.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | DADOS_OPENCODE_BRANCH_E_CONTEXTO |
| **Date** | 2026-08-31 |
| **Author** | define-agent |
| **Status** | ✅ Complete (Designed) |
| **Clarity Score** | 15/15 |
| **Input** | `BRAINSTORM_DADOS_OPENCODE_BRANCH_E_CONTEXTO.md` (com análise de dados reais) |

---

## Problem Statement

Sessões OpenCode em worktrees mostram branch "sem git" (o `.git` de worktree é um
arquivo, não pasta), o contexto fica sempre vazio (janela não configurada, default 0)
e o nome do card não distingue trabalho paralelo (duas sessões do mesmo projeto
aparecem com o nome do worktree, e a do repo principal aparece com o nome do projeto).

---

## Target Users

| User | Role | Pain Point |
|------|------|------------|
| Operador do painel | Trabalha com múltiplos worktrees/feature branches simultâneos | Não sabe de qual branch é cada card; contexto do modelo invisível; nomes ambiguos |

---

## Goals

| Priority | Goal |
|----------|------|
| **MUST** | `read_git_branch` worktree-aware: quando `<dir>/.git` for ARQUIVO, parsear `gitdir:` e ler `<gitdir>/HEAD` (retorna a branch do worktree) |
| **MUST** | Contexto OpenCode: default **128000** quando `usage.opencode_context_window` não configurado (override mantido); `ctxPct` passa a ser exibido |
| **MUST** | Nomenclatura unificada nas 3 fontes (Claude/Codex/OpenCode): nome do card = **branch** quando ela não é `main`/`master`; **nome do projeto** quando principal ou sem git |
| **SHOULD** | `monitor.toml` exemplo e SPEC documentam o default de contexto e a regra de nome |
| **COULD** | Benefício colateral: sessões Codex em worktrees passam a ter branch correta |

---

## Success Criteria

- [ ] pytest 100%: fixture de worktree (`.git` arquivo → gitdir → HEAD), regra de
      nome (branch vs projeto), default de contexto (0 → 128000, override respeitado)
- [ ] Na placa: card da sessão "Fluxo git" mostra `fix-28796-ajustes`, card "Migração
      Fase 7" mostra `feat/27816-remover-monolitico`, card do monitor mostra
      `monitor-tokens-esp32`
- [ ] Detalhe da sessão: branch correta no worktree; contexto em % preenchido
- [ ] `pio run` OK; compileall/check_secrets limpos

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | Branch de worktree | `<dir>/.git` é arquivo apontando para gitdir | `read_git_branch(dir)` | Retorna a branch do worktree (do HEAD do gitdir) |
| AT-002 | Repo principal | `<dir>/.git` é pasta | `read_git_branch(dir)` | Comportamento atual preservado |
| AT-003 | Sem git | Diretório sem `.git` | `read_git_branch(dir)` | Retorna "sem git" como hoje |
| AT-004 | Contexto default | Sem config de janela | Sessão OpenCode com tokens | `ctxPct = tokens/128000` (qualidade estimada) |
| AT-005 | Contexto override | `usage.opencode_context_window = 200000` | Sessão OpenCode | `ctxPct` usa 200000 |
| AT-006 | Nome = branch | Sessão em branch `fix-28796-ajustes` | Card renderizado | Nome do card = `fix-28796-ajustes` |
| AT-007 | Nome = projeto | Sessão em branch `master`/`main` | Card renderizado | Nome do card = nome do projeto |
| AT-008 | Regra nas 3 fontes | Claude, Codex e OpenCode com branch não-principal | Payload montado | Os 3 exibem a branch |
| AT-009 | Sem regressão | Build final | pytest/compileall/secrets/pio | Tudo verde |

---

## Out of Scope

- Tabela de janela de contexto por modelo específico (128k default + override resolve)
- Mostrar projeto+branch juntos no nome do card
- Mudanças de payload/protocolo (campos `branch` e `name` já existem)
- Pódio, heatmap, inspeção

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Technical | `read_git_branch` é usada por Claude E Codex também | Correção beneficia todas as fontes; testes existentes não podem quebrar |
| Technical | Daemon stdlib-only | Parse do gitdir com `Path`/string ops |
| Technical | Nome do card truncado em 10 chars (grid) e 25 (catálogo) | Branch longa trunca — comportamento existente |
| Visual | Painel exibe o nome como vier no campo `name` | Sem mudança de firmware |

---

## Assumptions & Risk Register

| ID | Assumption | Impact if Wrong | Validated |
|----|-----------|-----------------|-----------|
| R1 | 128k é aproximação aceitável para GLM/DeepSeek no uso do operador | % impreciso — ajustável por config sem deploy | ☐ |
| R2 | Branch `feat/27816-remover-monolitico` exibida com "/" — JSON/transporte aceitam | Se o transporte rejeitar, sanitizar "/" → "-" | ☐ |

---

## Technical Context

| Aspect | Value | Notes |
|--------|-------|-------|
| **Deployment Location** | `tools/session_meta.py` (read_git_branch), `tools/opencode_sessions.py` (default de contexto + `_project_name` → regra), `tools/session_daemon.py` (aplicar regra nas scans Claude/Codex), `tests/` | Correção concentrada no daemon |
| **KB Domains** | `shared` | Convenções stdlib/pytest |
| **IaC Impact** | None | — |

---

## Data Contract (if applicable)

Nenhum campo novo. Campos `branch` e `name` já existem no payload — muda o
PREENCHIMENTO (branch correta em worktrees; `name` = branch não-principal).

---

## Clarity Score Breakdown

| Element | Score | Notes |
|---------|-------|-------|
| Problem | 3 | 3 sintomas com causa-raiz comprovada por dados |
| Users | 3 | Operador multi-worktree, dor concreta |
| Goals | 3 | MoSCoW objetivo, correções pontuais |
| Success | 3 | Critérios verificáveis em testes e na placa |
| Scope | 3 | Out-of-scope explícito |
| **Total** | **15/15** | Gate superado |

---

## Open Questions

Nenhuma — a única ambiguidade (identidade do card) foi resolvida pelo operador (c).

---

## Revision History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-31 | Criação a partir do BRAINSTORM com análise de dados | define-agent |
