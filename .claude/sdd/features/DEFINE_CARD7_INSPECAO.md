# DEFINE: Card 7 — inspeção de dia (G4+G9) e seta para o pódio

> Refinamento do widget unificado: grade encostada com título, seta dedicada ao pódio
> e modo inspeção com barra full-width do dia tocado.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | CARD7_INSPECAO |
| **Date** | 2026-08-29 |
| **Author** | define-agent |
| **Status** | ✅ Complete (Designed) |
| **Clarity Score** | 15/15 |
| **Input** | `BRAINSTORM_CARD7_INSPECAO.md` (brainstorm_document, pré-validado com mockups aprovados) |

---

## Problem Statement

A primeira versão do widget escondia as duas funções principais: o caminho para o
pódio era um long-press indescobrível, a grade não preenchia o card (gap + células
pequenas) e não havia forma confortável de inspecionar o consumo de um dia específico.

---

## Target Users

| User | Role | Pain Point |
|------|------|------------|
| Operador do painel | Único usuário | Não descobre como ver um dia específico nem como chegar ao pódio; a grade desperdiça espaço do card |

---

## Goals

| Priority | Goal |
|----------|------|
| **MUST** | Repouso: título `consumo de tokens` (linha própria ~20px, caps apagadas, permanente) + grade horizontal 7×6 encostada (gap 0) ocupando ~276px de largura |
| **MUST** | Faixa lateral direita (~28px, altura da grade) com seta `▸` → alterna para o pódio; **único** caminho |
| **MUST** | Long-press sem função (removido) |
| **MUST** | Inspeção (toque num dia): dias não-tocados **75% escurecidos**; dia tocado vira **barra verde full-width** (~56px, 2 linhas) |
| **MUST** | Barra de inspeção, linha 1: `Quarta-feira, 26/08 — 7,1M tokens` (dia POR EXTENSO) |
| **MUST** | Barra de inspeção, linha 2: `27% do pico · semana 24-30: 30,4M` |
| **MUST** | Saída da inspeção: toque na barra **ou** em qualquer lugar fora dela → repouso |
| **SHOULD** | Remover o label "dd/mm: tok" do topo (substituído pela barra) |
| **COULD** | Dias vazios mantêm `#161B22` sobre fundo escuro (contraste já ajustado) |

---

## Success Criteria

- [ ] pytest 100% (novos testes de lógica: nome de dia por extenso, total semanal,
      % do pico); compileall e check_secrets limpos
- [ ] `pio run` OK no env de produção
- [ ] Na placa: título visível; grade encostada preenchendo o card; seta leva ao
      pódio; toque num dia abre inspeção com barra full-width; toque na barra/fora
      volta ao repouso; long-press sem efeito
- [ ] Nenhuma regressão no pódio (chip hoje/7d/30d, modal) nem no contrato de payload

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | Repouso | Payload válido recebido | Tela em repouso | Título no topo + grade 7×6 encostada + faixa de seta à direita; sem label de tokens |
| AT-002 | Seta → pódio | Repouso | Toque na faixa da seta | Alternância para o pódio (chip e barras) |
| AT-003 | Long-press neutro | Repouso ou inspeção | Long-press em qualquer lugar | Nenhuma mudança de visão |
| AT-004 | Entrar na inspeção | Repouso | Toque num quadrado | Dias restantes 75% escurecidos; dia tocado = barra verde full-width com 2 linhas |
| AT-005 | Dia por extenso | Dia tocado é quarta-feira | Inspeção aberta | Linha 1 = "Quarta-feira, dd/mm — N tokens" (não abreviado) |
| AT-006 | Contexto na linha 2 | Dia tocado | Inspeção aberta | Linha 2 = "P% do pico · semana dd-dd: T" com valores corretos |
| AT-007 | Semana parcial | Semana da borda (menos de 7 dias na janela) | Inspeção de dia dela | Total da semana soma apenas dias existentes na janela |
| AT-008 | Sair pela barra | Inspeção aberta | Toque na barra | Volta ao repouso (grade intacta) |
| AT-009 | Sair por fora | Inspeção aberta | Toque fora da barra | Volta ao repouso |
| AT-010 | Pódio inalterado | Pódio ativo | Chip/modal | Comportamento atual preservado |
| AT-011 | Sem payload | Placa recém-boot | Antes do 1º POST | Repouso com células vazias; inspeção não trava com daily zerado |

---

## Out of Scope

- Tooltip flutuante/ancorado (G5/G7), sparkline da semana, comparação com média
- Navegação entre dias dentro da inspeção (sai e toca outro)
- Contorno branco permanente no "hoje" (repouso)
- Mudanças no pódio, modal, payload ou daemon (esta iteração é 100% firmware UI)

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Technical | Área do card 304×222; título 20px; faixa da seta 28px | Grade ~276×202 → células ~39×31px (7 col) |
| Technical | LVGL 9: objetos nascem clicáveis — células da grade agora PRECISAM ser clicáveis (mostram inspeção); vãos e card → toggle/seta | Hit-test revisado manualmente |
| Technical | % do pico e total da semana calculados no firmware a partir de `usageHistory.daily` | Sem mudança de payload/daemon |
| Operational | Flash via COM3 reseta a placa | Validar com daemon do operador rodando |

---

## Assumptions & Risk Register

| ID | Assumption | Impact if Wrong | Validated |
|----|-----------|-----------------|-----------|
| R1 | Células ~39×31px acomodem a barra de inspeção de 2 linhas (56px) sem colisão com o título | Ajustar alturas (título 18px / barra 52px) | ☐ |
| R2 | 75% de escurecimento é alcançável escurecendo a cor do nível (divisão) sem objeto overlay | Usar overlay semitransparente sobre a grade | ☐ |
| R3 | Fonte montserrat_14 comporta "Quarta-feira, 26/08 — 7,1M tokens" em 276px | Abreviar mês ou reduzir para montserrat_12 | ☐ |

---

## Technical Context

| Aspect | Value | Notes |
|--------|-------|-------|
| **Deployment Location** | `src/ui/ui_dashboard.cpp` (exclusivo) | Nenhum outro arquivo muda |
| **KB Domains** | `shared` (convenções LVGL do projeto) | Padrões de set_text_if/set_color_if, hit-test |
| **IaC Impact** | None | — |

---

## Data Contract (if applicable)

Nenhum dado novo: tudo derivado de `usageHistory.daily` (já existente). Sem mudança
de payload, daemon ou protocolo.

---

## Clarity Score Breakdown

| Element | Score | Notes |
|---------|-------|-------|
| Problem | 3 | Descoberta (long-press) e inspeção de dia, específicos |
| Users | 3 | Persona única com dor nomeada |
| Goals | 3 | MoSCoW linha a linha, MUSTs todos com critério visual objetivo |
| Success | 3 | Critérios verificáveis na placa + suíte Python |
| Scope | 3 | Out-of-scope explícito; iteração 100% firmware UI |
| **Total** | **15/15** | Gate 12/15 superado |

---

## Open Questions

Nenhuma — as 4 perguntas do brainstorm foram respondidas e os mockups aprovados são
a referência visual contratual.

---

## Revision History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-29 | Criação a partir do BRAINSTORM_CARD7_INSPECAO | define-agent |
