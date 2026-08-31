# DEFINE: Dados OpenCode II — perm via log do OpenCode

> Detectar o estado `perm` das sessões OpenCode a partir do log do OpenCode
> (`action.action=ask`), única fonte persistida do pedido de permissão.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | DADOS_OPENCODE_PERM_VIA_LOG |
| **Date** | 2026-08-31 |
| **Author** | define-agent |
| **Status** | ✅ Complete (Designed) |
| **Clarity Score** | 15/15 |
| **Input** | `BRAINSTORM_DADOS_OPENCODE_PERM_VIA_LOG.md` (dados validados: 40 ocorrências, run→sessão confirmado) |

---

## Problem Statement

Quando o OpenCode aguarda aprovação do usuário (permissão de bash/edit/external_directory),
nada é persistido no SQLite — o painel mostra `work` enquanto o operador tem um
diálogo de permissão aberto, e o `perm` fica indisponível para esta fonte.

---

## Target Users

| User | Role | Pain Point |
|------|------|------------|
| Operador do painel | Aprova permissões nos agentes | O card mostra `work` (verde) enquanto o agente está parado esperando a aprovação dele |

---

## Goals

| Priority | Goal |
|----------|------|
| **MUST** | Novo sinal `perm`: parse do tail do `opencode.log` — mapear `run=<id>` → `session.id` e localizar a última avaliação `evaluated permission=... action.action=ask` por sessão |
| **MUST** | Regra de frescor: `perm` somente se a avaliação `ask` for a evidência mais recente da sessão (sem part de tool com `time_updated` posterior) e com idade ≤ 10 min |
| **MUST** | Sem regressão: `ask` (question pending/running), contexto, nomenclatura e demais estados intactos |
| **SHOULD** | Caminho do log configurável (`usage.opencode_log_path`? não — usar o padrão do OpenCode com override por constante) |
| **SHOULD** | Documentar na SPEC a fonte do sinal e a limitação (formato do log pode mudar entre versões) |
| **COULD** | Diferenciar o tipo de permissão no detalhe (bash/edit/external_directory) |

---

## Success Criteria

- [ ] pytest 100% (parser do log: run→sessão, ask recente, allow posterior, log ausente)
- [ ] Na placa: sessão com diálogo de permissão aberto mostra `perm` (amarelo); após aprovar, volta a `work`
- [ ] Sem regressão: 198+ testes verdes, compileall, check_secrets

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | Perm ativa | Log com `ask` às T e sem atividade da sessão após T | Scan em T+2min | Estado `perm` |
| AT-002 | Aprovada | Mesmo log + part da sessão com `time_updated` > T | Scan | Volta a `work`/`free` |
| AT-003 | Ask expirado | `ask` às T, scan em T+15min, sem atividade | Scan | Não fica `perm` preso (work/free por recência) |
| AT-004 | Mapeamento de runs | Múltiplos `run=` no tail | Parse | Cada avaliação mapeia à sessão correta |
| AT-005 | Log ausente | Arquivo de log não existe | Scan | Sem erro, sem `perm` (fallback normal) |
| AT-006 | Log truncado/meio-line | Tail corta uma linha ao meio | Parse | Linha inválida ignorada sem exceção |
| AT-007 | Coexistência | `question pending` (ask) E `ask` de permissão | Scan | Sinal mais recente vence |
| AT-008 | Sem regressão | Suite completa | pytest | Todos verdes |

---

## Out of Scope

- API HTTP do OpenCode; histórico completo de permissões; badge do tipo de permissão
- Qualquer mudança de firmware/payload (estado via campo `state` existente)

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Technical | Formato do log é de terceiros (muda entre versões) | Parser tolerante: linha sem match = ignorada |
| Technical | Log cresce indefinidamente (não rotaciona?) | Ler só o tail (~512KB) por ciclo |
| Technical | Ciclo de 5s | Tail + regex ≤ ~10ms; sem leitura do arquivo inteiro |
| Operational | Caminho do log: `%LOCALAPPDATA%`/`~/.local/share/opencode/log/opencode.log` | Constante com override por env se necessário |

---

## Assumptions & Risk Register

| ID | Assumption | Impact if Wrong | Validated |
|----|-----------|-----------------|-----------|
| R1 | O formato `evaluated permission=... action.action=ask` se mantém | Sem `perm` (fallback work/free) — degradação suave | ☑ (40 ocorrências hoje) |
| R2 | `run=` mapeia 1:1 para a sessão do ciclo | perm na sessão errada → mapear pelo `process session.id=` mais próximo no log | ☑ |
| R3 | Tail de 512KB cobre ≥ 10 min de log | Aumentar tail | ☐ |

---

## Technical Context

| Aspect | Value | Notes |
|--------|-------|-------|
| **Deployment Location** | `tools/opencode_sessions.py` (parser + integração no scan), `tests/` | Daemon only, sem firmware |
| **KB Domains** | `shared` | stdlib regex |
| **IaC Impact** | None | — |

---

## Data Contract (if applicable)

Nenhum campo novo no payload — `state` já carrega `perm` (vocabulário existente do
firmware e já renderizado em amarelo).

---

## Clarity Score Breakdown

| Element | Score | Notes |
|---------|-------|-------|
| Problem | 3 | Sintoma específico com causa provada no log |
| Users | 3 | Operador aprovando permissões |
| Goals | 3 | MoSCoW objetivo |
| Success | 3 | ATs com fixtures de log |
| Scope | 3 | Out-of-scope explícito |
| **Total** | **15/15** | Gate superado |

---

## Open Questions

Nenhuma — a fonte foi validada com dados reais (40 ocorrências + mapeamento run→sessão).

---

## Revision History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-31 | Criação a partir do BRAINSTORM com análise do log | define-agent |
