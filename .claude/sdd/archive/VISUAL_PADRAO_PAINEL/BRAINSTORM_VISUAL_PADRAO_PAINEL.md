# BRAINSTORM: Padronização visual do painel (Cards 1-6, Pódio, Card 7)

> Sessão exploratória para a camada de consistência visual da plataforma

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | VISUAL_PADRAO_PAINEL |
| **Date** | 2026-08-29 |
| **Author** | brainstorm-agent |
| **Status** | ✅ Shipped |
| **Origem** | Requisito do operador com critérios de aceite já redigidos (AC 1-3) |

---

## Initial Idea

**Raw Input:** "As telas de Consumo de Tokens (Card 7), Pódio de Agentes e os Cards 1
a 6 devem possuir interface visual consistente, com espaçamentos adequados e
nomenclatura padronizada dos projetos." + 3 blocos de critérios de aceite (gaps
GitHub no Card 7, seta centralizada, inspeção sem verde; pódio em colunas 2º|1º|3º
com ícone+valor no cabeçalho e sem sufixo M; DeepSeek/GLM mostrando nome de projeto
em vez da 1ª mensagem, com regra única para as 4 fontes).

**Context Gathered:**
- Card 7: grade encostada (gap 0) — o AC pede o gap fino do GitHub (~2px)
- Seta: faixa alinhada ao topo da grade; símbolo não fica centralizado na faixa
- Inspeção: barra usa a cor de nível do dia (verde) — AC pede fundo padrão do card
- Pódio: hoje são 3 barras horizontais empilhadas (rank top-down) — AC pede pódio
  de colunas 2º|1º|3º
- OpenCode: `_project_name()` prioriza `title` da sessão (que o OpenCode preenche
  com a 1ª mensagem/resumo) — daí "New session - ..." e prompts nos cards
- Claude/Codex já exibem nome de projeto (pasta / thread_name)

---

## Discovery Questions & Answers

| # | Question | Answer | Impact |
|---|----------|--------|--------|
| 1 | Layout do pódio em colunas | **(a)** Pódio clássico: altura das colunas por RANK (1º alta, 2º média, 3º baixa); ícone no topo, valor, barra, nome embaixo | Redesign das barras horizontais em 3 colunas 2º\|1º\|3º |
| 2 | Valores sem "M" — e abaixo de 1M? | **(b)** Tudo em milhões com decimais (`0,6`) + título do gráfico ganha `(EM MM)` declarando a unidade | Formato numérico único; sem sufixos em lugar nenhum do widget |
| 3 | Cor das colunas do pódio | **(c)** Degrade de pódio: 1º `#39D353`, 2º `#26A641`, 3º `#006D32` | Hierarquia por cor dentro da paleta GitHub estrita |

---

## Sample Data Inventory

| Type | Location | Count | Notes |
|------|----------|-------|-------|
| Sessões reais OpenCode | `opencode.db` (title = 1ª mensagem) | ~10 | Caso de teste da regra de nomenclatura |
| Mockups | `docs/mockups/` | 16 | Referência da linguagem visual aprovada |

---

## Approaches Explored

### Approach A: Ajuste fino sobre o implementado ⭐ Recommended

**Description:** Todas as mudanças são cirúrgicas nos widgets existentes (Card 7 e
Pódio) + regra de nome no coletor OpenCode. Nenhum layout novo, nenhuma tela nova.

**Pros:**
- Menor risco; cada AC mapeia 1-2 pontos de código conhecidos
- Mantém toda a linguagem visual já aprovada (paleta GitHub, títulos, hit-test)

**Cons:**
- Pódio muda de barras horizontais para colunas (a maior peça nova)

**Why Recommended:** Os ACs são de consistência e correção — não pedem nada
conceitualmente novo; reinventaria o que o operador já aprovou.

---

## Selected Approach

| Attribute | Value |
|-----------|-------|
| **Chosen** | Approach A |
| **User Confirmation** | 2026-08-29 (respostas a, b, c) |
| **Reasoning** | ACs de padronização; evolução direta do já validado em hardware |

---

## Key Decisions Made

| # | Decision | Rationale | Alternative Rejected |
|---|----------|-----------|----------------------|
| 1 | Pódio em colunas 2º\|1º\|3º com altura por rank | Ranking instantâneo; formato pódio clássico | Barras horizontais atuais; altura proporcional ao consumo |
| 2 | Valores em MM sem sufixo; unidade declarada no título `(EM MM)` | Formato único; título carrega a unidade uma vez só | Sufixos k/M misturados |
| 3 | Colunas com degrade 1º/2º/3º = L4/L3/L2 | Hierarquia por cor na paleta estrita | Cor por provider; cor única |
| 4 | Gap fino do GitHub (~2px) na grade do Card 7 | Replicar a distribuição exata do gráfico de contribuições | Gap 0 atual |
| 5 | Inspeção com fundo padrão do card (sem verde) | Consistência; o dia já é identificado pela posição/texto | Fundo na cor de nível |
| 6 | OpenCode: nome do projeto = pasta do `directory` (fallback title/slug) | Mesma regra do Claude; elimina "New session - ..." | Priorizar `title` |

---

## Features Removed (YAGNI)

| Feature Suggested | Reason Removed | Can Add Later? |
|-------------------|----------------|----------------|
| Sufixo k para valores pequenos | Operador escolheu MM uniforme com decimais | Yes (se `0,0` aparecer com frequência) |
| Cor por provider no pódio | Escolhido degrade de rank | Yes |
| Rótulos de eixo/mês no heatmap | Fora do escopo dos ACs | Yes |

---

## Incremental Validations

| Section | Presented | User Feedback | Adjusted? |
|---------|-----------|---------------|-----------|
| Pódio em colunas (Q1) | ✅ | (a) altura por rank | No |
| Formato numérico (Q2) | ✅ | (b) MM uniforme + título `(EM MM)` | Yes |
| Cores do pódio (Q3) | ✅ | (c) degrade L4/L3/L2 | No |

**Minimum Validations:** 2 ✅ (mais os ACs escritos pelo próprio operador)

---

## Suggested Requirements for /define

### Problem Statement (Draft)
O painel inconsistente: pódio em barras empilhadas (não pódio), valores com sufixo
"M" poluindo, inspeção com tonalidade verde fora do padrão, gaps irregulares no
heatmap e sessões OpenCode exibindo a 1ª mensagem em vez do nome do projeto.

### Target Users (Draft)
| User | Pain Point |
|------|------------|
| Operador do painel | Leitura desigual entre cards; nomes de sessão ilegíveis ("New session - 2026-08-28...") |

### Success Criteria (Draft)
- [ ] Card 7: gap ~2px entre células (distribuição GitHub); seta centralizada na faixa; inspeção com fundo padrão (sem verde)
- [ ] Título do gráfico: `CONSUMO DE TOKENS (EM MM)`
- [ ] Pódio: colunas na ordem 2º\|1º\|3º, altura por rank, degrade L2/L3/L4, ícone + valor (sem M) acima da barra, nome do agente abaixo
- [ ] Cards de sessão: DeepSeek/GLM/Claude/Codex exibem nome de projeto com a mesma regra
- [ ] pytest/compileall/check_secrets verdes; `pio run` OK; flash validado

### Constraints Identified
- Área fixa 304×222 (Card 7); pódio ocupa o mesmo bloco (visão 2)
- Paleta estrita: só os 5 verdes GitHub + cores de tema existentes
- Daemon só stdlib; payload sem mudança (nome do projeto já viaja no campo `name`)

### Out of Scope (Confirmed)
- Rótulos de eixo/mês; tooltip flutuante; cores por provider; mudanças de protocolo

---

## Session Summary

| Metric | Value |
|--------|-------|
| Questions Asked | 3 |
| Approaches Explored | 1 (ajuste fino) + variantes por pergunta |
| Features Removed (YAGNI) | 3 |
| Validations Completed | 3 |
| Duration | ~10 min |

---

## Next Step

**Ready for:** `/define .claude/sdd/features/BRAINSTORM_VISUAL_PADRAO_PAINEL.md`
