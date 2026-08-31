# BRAINSTORM: Card 7 — inspeção de dia (G4+G9) e seta para o pódio

> Sessão exploratória de refinamento do widget unificado já implementado

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | CARD7_INSPECAO |
| **Date** | 2026-08-29 |
| **Author** | brainstorm-agent |
| **Status** | ✅ Complete (Defined) |
| **Origem** | Iteração pós-build do `BRAINSTORM_WIDGET_UNIFICADO_CONSUMO` (feedback visual do operador) |

---

## Initial Idea

**Raw Input:** "Manter o visual G4 (quadrados encostados preenchendo o card) mas ao
apertar sobre algum quadrado, abre G9 (modo inspeção). No repouso: espaço lateral
para uma seta apontando para o pódio; remover o label de tokens do topo; inserir
título 'consumo de tokens'. Na inspeção: data com nome completo do dia ('Quarta-
feira'); o quadrado ocupa a largura toda; toque nele ou fora volta ao repouso; 75%
escurecido; pódio acionado só pela seta; long-press desativado."

**Context Gathered:**
- Widget unificado já implementado e validado na placa (grid vertical 40×33 com gap,
  label "dd/mm: tok" no topo, toggle por toque nos vãos + long-press)
- 4 rodadas de mockups (`docs/mockups/`) até convergir: G4 (grade esticada) +
  G9 (inspeção com apagamento e painel) foram aprovados; B2/B3/F/G variante
  descartadas pelo operador
- Dois bugs de render resolvidos nesta iteração: `lv_obj_get_height()` antes do
  layout (container com altura 0) e objetos LVGL nascendo clicáveis (engoliam toque)

---

## Discovery Questions & Answers

| # | Question | Answer | Impact |
|---|----------|--------|--------|
| 1 | O que estica para a largura toda na inspeção? | **(a)** O quadrado do dia vira barra verde full-width com as infos dentro; demais dias 75% apagados | Inspeção = barra protagonista, não painel separado |
| 2 | Formato da seta para o pódio? | **(a)** Faixa vertical na borda direita (~28px, altura toda), seta `▸` centralizada | Grade perde 28px de largura (7 colunas de ~36px); alvo de toque grande |
| 3 | Posição do título "consumo de tokens"? | **(a)** Linha própria no topo (caps apagadas), permanente; grade desce ~20px | Células ~36×31px; título legível nas duas visões |
| 4 | Conteúdo da barra full-width? | **(b)** Duas linhas: `Quarta-feira, 26/08 — 7,1M tokens` + `27% do pico · semana 24-30: 30,4M` | Barra ~56px; mantém o total semanal aprovado no G4 |

---

## Sample Data Inventory

| Type | Location | Count | Notes |
|------|----------|-------|-------|
| Mockups aprovados | `docs/mockups/G4FINAL-repouso.png`, `G4FINAL-inspecao.png` | 2 | Referência visual contratual (quadrados ENCOSTADOS, gap 0) |
| Mockups descartados | `docs/mockups/B2..G7` | 12 | Histórico das alternativas avaliadas |
| Código base | `src/ui/ui_dashboard.cpp` (widget unificado) | — | Grid, paleta, tooltip label a substituir |

---

## Approaches Explored

### Approach A: G4 repouso + G9 inspeção com barra full-width ⭐ Recommended

**Description:** Repouso = grade encostada 7×6 + título + seta lateral. Toque num dia
→ demais 75% apagados, dia vira barra verde full-width com 2 linhas de info. Toque na
barra ou fora → repouso.

**Why Recommended:** Continuidade direta do que o operador aprovou nos mockups;
barra full-width dá espaço real para as duas linhas de informação; seta dedicada
torna o pódio óbvio (o long-press era invisível).

### Approaches B–E (mockups, descartados): tooltip flutuante (B2), barra de info
permanente (B3), valor na célula (F), híbrido com barras semanais (G/G2/G3), tooltip
com sparkline (G7), tooltip ancorado (G5) — todos avaliados em imagem pelo operador.

---

## Selected Approach

| Attribute | Value |
|-----------|-------|
| **Chosen** | Approach A |
| **User Confirmation** | 2026-08-29 ("sim" na validação consolidada) |
| **Reasoning** | Aprovado por.inspecting mockups reais; menor distância entre o aprovado e o implementado |

---

## Key Decisions Made

| # | Decision | Rationale | Alternative Rejected |
|---|----------|-----------|----------------------|
| 1 | Quadrados ENCOSTADOS (gap 0) | Exigência do operador ("quadrados encostados"); leitura mais densa | Gap 2px do mockup anterior |
| 2 | Seta lateral única via para o pódio | Long-press era invisível/descobrível apenas por sorte | Manter long-press + seta (redundante) |
| 3 | Nome do dia por extenso ("Quarta-feira") | Exigência do operador; cabe na barra full-width | Abreviado ("qua-feira") |
| 4 | Barra de inspeção com 2 linhas | Contexto completo (dia + % pico + semana) sem tooltip | 1 linha minimalista |
| 5 | Saída da inspeção: toque na barra OU fora dela | Regra única e simples | Botão X dedicado |
| 6 | Título permanente "consumo de tokens" | Identidade do card; alinhamento com o pedido original | Sem título (tela 100% grade) |

---

## Features Removed (YAGNI)

| Feature Suggested | Reason Removed | Can Add Later? |
|-------------------|----------------|----------------|
| Long-press → pódio | Substituído pela seta; dois caminhos para a mesma ação confundem | No |
| Label "dd/mm: tok" no topo | Substituído pela barra de inspeção | No |
| Tooltip flutuante/ancorado (G5/G7) | Operador escolheu barra full-width | Yes (/iterate) |
| Sparkline da semana no tooltip | Total semanal na barra já responde | Yes |
| Comparação com média do dia-da-semana | Complexidade de cálculo/UX sem pedido | Yes |
| Navegação entre dias dentro da inspeção | Saída + novo toque é simples e suficiente | Yes |
| Contorno branco no "hoje" (repouso) | O próprio dado destaca hoje; contorno poluía | Yes |

---

## Incremental Validations

| Section | Presented | User Feedback | Adjusted? |
|---------|-----------|---------------|-----------|
| 4 perguntas de descoberta | ✅ | (a), (a), (a), (b) | Yes |
| Spec consolidada completa | ✅ | "sim" | No |
| Mockups G4FINAL repouso/inspeção | ✅ | Aprovados como referência visual | N/A |

**Minimum Validations:** 2 ✅

---

## Suggested Requirements for /define

### Problem Statement (Draft)
A primeira versão do widget tinha descoberta ruim (long-press invisível, tooltip que
cobria a grade, quadrados com gap que não preenchiam o card) e a inspeção de dia
não existia como estado dedicado.

### Target Users (Draft)
| User | Pain Point |
|------|------------|
| Operador do painel | Não consegue ver o consumo de um dia específico com conforto e não descobre como ir ao pódio |

### Success Criteria (Draft)
- [ ] Repouso: grade encostada 7×6 preenchendo o card (menos título e faixa da seta)
- [ ] Título "consumo de tokens" permanente; seta `▸` à direita leva ao pódio
- [ ] Toque num dia: demais 75% apagados + barra verde full-width com dia por extenso,
      tokens, % do pico e total da semana
- [ ] Toque na barra ou fora → repouso
- [ ] Long-press sem função; pódio só pela seta
- [ ] pytest/compileall/check_secrets verdes; `pio run` OK; flash validado na placa

### Constraints Identified
- Área 304×222; título ~20px + grade ~202px; faixa da seta 28px (grade ~276px)
- Células ~36×31px encostadas (gap 0)
- Pódio e modal de sessões inalterados

### Out of Scope (Confirmed)
- Tooltip flutuante, sparkline semanal, comparação com média, navegação na inspeção
- Qualquer mudança no pódio (chip de período, modal)

---

## Session Summary

| Metric | Value |
|--------|-------|
| Questions Asked | 4 |
| Approaches Explored | 5 famílias (12 mockups) |
| Features Removed (YAGNI) | 7 |
| Validations Completed | 3 |
| Duration | ~20 min |

---

## Next Step

**Ready for:** `/define .claude/sdd/features/BRAINSTORM_CARD7_INSPECAO.md`
