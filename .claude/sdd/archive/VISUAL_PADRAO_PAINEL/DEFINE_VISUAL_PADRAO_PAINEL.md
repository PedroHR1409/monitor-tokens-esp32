# DEFINE: Padronização visual do painel (Cards 1-6, Pódio, Card 7)

> Consistência visual: gaps GitHub no Card 7, pódio em colunas com valores em MM,
> nomenclatura de projetos padronizada nas 4 fontes de sessão.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | VISUAL_PADRAO_PAINEL |
| **Date** | 2026-08-29 |
| **Author** | define-agent |
| **Status** | ✅ Shipped |
| **Clarity Score** | 15/15 |
| **Input** | `BRAINSTORM_VISUAL_PADRAO_PAINEL.md` (ACs redigidos pelo operador + 3 decisões (a/b/c)) |

---

## Problem Statement

O painel cresceu por iterações e ficou visualmente desigual: o pódio usa barras
empilhadas (não é um pódio), valores carregam sufixo "M" redundante, a barra de
inspeção tem tonalidade verde fora do padrão, os gaps do heatmap não replicam o
GitHub e sessões OpenCode exibem a primeira mensagem ("New session - ...") em vez do
nome do projeto.

---

## Target Users

| User | Role | Pain Point |
|------|------|------------|
| Operador do painel | Leitor constante dos 9 blocos da tela | Cada card "fala uma língua"; nomes de sessão ilegíveis; hierarquia do pódio confusa |

---

## Goals

| Priority | Goal | Bloco |
|----------|------|-------|
| **MUST** | Card 7 (repouso): gap fino de ~2px entre células, replicando a distribuição do GitHub; células recalculadas para preencher a grade | 1 |
| **MUST** | Card 7: símbolo da seta centralizado verticalmente na faixa, alinhado ao bloco da grade | 1 |
| **MUST** | Card 7 (inspeção): barra com fundo padrão do card (`COLOR_BG`), sem tonalidade verde; contorno mantido | 1 |
| **MUST** | Título do gráfico: `CONSUMO DE TOKENS (EM MM)` | 1 |
| **MUST** | Pódio: 3 colunas na ordem **2º (esq) \| 1º (centro) \| 3º (dir)**, altura por rank (1º mais alta) | 2 |
| **MUST** | Pódio: acima do topo de cada coluna, `ícone do agente` + `valor em MM sem sufixo` | 2 |
| **MUST** | Pódio: preenchimento das colunas em degrade por rank (1º `#39D353`, 2º `#26A641`, 3º `#006D32`) | 2 |
| **MUST** | Valores numéricos do widget SEMPRE em MM com decimais (`7,1`; `0,6`), sem sufixo k/M — inclusive na barra de inspeção | 2/1 |
| **MUST** | OpenCode: cards exibem o **nome do projeto** (pasta do `directory`), não a 1ª mensagem | 3 |
| **SHOULD** | Regra de nome única documentada para as 4 fontes (Claude=pasta, Codex=thread_name, OpenCode=pasta do directory) | 3 |
| **COULD** | Ajuste fino de espaçamentos gerais se sobrar área morta | todos |

---

## Success Criteria

- [ ] `/diag`-inspecionável: pitch das células = tamanho + 2px (gap) — conferível por coordenadas
- [ ] pytest 100% (testes de nome do projeto OpenCode atualizados; contratos de fonte do pódio/título)
- [ ] `pio run` OK; flash na placa; validação visual dos 3 blocos pelo operador
- [ ] Nenhuma sessão OpenCode exibe "New session" quando há `directory` válido
- [ ] Nenhum valor exibido com sufixo "M"/"k" no Card 7 e pódio

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | Gap GitHub | Repouso | Grade renderizada | Espaço entre células = 2px (pitch = célula + 2) |
| AT-002 | Seta centralizada | Repouso | Medição da faixa | Símbolo centrado verticalmente no trecho da grade (não no card todo) |
| AT-003 | Inspeção sem verde | Toque num dia | Barra aberta | Fundo da barra = `COLOR_BG` padrão; sem cor de nível; contorno/texto mantidos |
| AT-004 | Ordem do pódio | Totais distintos | Visão 2 | Coluna esquerda = 2º, centro = 1º, direita = 3º |
| AT-005 | Altura por rank | Visão 2 | Comparar colunas | 1º mais alta, 2º média, 3º baixa |
| AT-006 | Cabeçalho das colunas | Visão 2 | Acima de cada barra | Ícone do agente + valor em MM, lado a lado |
| AT-007 | Degrade por rank | Visão 2 | Comparar cores | 1º `#39D353`, 2º `#26A641`, 3º `#006D32` |
| AT-008 | Valores em MM | Qualquer valor ≥ 1M | Leitura | Sem sufixo ("7,1"); título com `(EM MM)` |
| AT-009 | Valores < 1M | Sessão/dia com 600k | Leitura | Exibido "0,6" (MM com decimais), não "620k" |
| AT-010 | Nome OpenCode | Sessão com `directory` em repo git | Card renderizado | Nome = pasta do projeto (ex.: "monitor-tokens-esp32") |
| AT-011 | Fallback OpenCode | Sessão sem `directory` | Card renderizado | Cai no title/slug como hoje |
| AT-012 | Sem regressão | Build final | pytest/compileall/secrets/pio | Tudo verde |

---

## Out of Scope

- Rótulos de eixo/mês no heatmap; tooltip flutuante; cores por provider no pódio
- Mudanças de payload/protocolo (o nome do projeto já viaja no campo `name`)
- Redesign dos cards de cota/heatmap além dos ACs listados

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Technical | Área do Card 7 fixa (304×222, título 20px, seta 28px) | Gap 2px reduz célula para ~37×31 |
| Technical | Pódio na mesma área da visão 2 | Colunas cabem: 3 × ~80px de largura |
| Technical | Daemon stdlib-only; payload inalterado | Nome do projeto é regra de preenchimento do campo existente |
| Visual | Paleta estrita (5 verdes GitHub + tema) | Degrade do pódio usa exatamente L4/L3/L2 |

---

## Assumptions & Risk Register

| ID | Assumption | Impact if Wrong | Validated |
|----|-----------|-----------------|-----------|
| R1 | `directory` da sessão OpenCode é o caminho do projeto (com nome de pasta significativo) | Nome cai no fallback (title) — degradação suave | ☑ (verificado ao vivo: directories são repos reais) |
| R2 | Valores < 0,05M exibidos como "0,0" são aceitáveis (dias quase sem uso) | Operador pode pedir fallback para k depois (YAGNI registrado) | ☐ |
| R3 | Pódio em colunas cabe legível em ~304×222 (3 colunas de ~90px) | Reduzir largura das barras internas | ☐ |

---

## Technical Context

| Aspect | Value | Notes |
|--------|-------|-------|
| **Deployment Location** | `src/ui/ui_dashboard.cpp`; `tools/opencode_sessions.py`; `tests/` | UI + regra de nome; sem protocolo |
| **KB Domains** | `shared` (convenções LVGL/stdlib do projeto) | — |
| **IaC Impact** | None | — |

---

## Data Contract (if applicable)

Nenhum campo novo. A regra de nomenclatura altera o PREENCHIMENTO do campo `name`
(por sessão) que já viaja no payload — Claude/Codex inalterados; OpenCode muda a
prioridade: `basename(directory)` → `title` → `slug`.

---

## Clarity Score Breakdown

| Element | Score | Notes |
|---------|-------|-------|
| Problem | 3 | Inconsistências enumeradas item a item |
| Users | 3 | Persona única, dores concretas |
| Goals | 3 | MoSCoW derivado dos ACs do operador |
| Success | 3 | Critérios verificáveis (diag/pytest/hardware) |
| Scope | 3 | Out-of-scope explícito |
| **Total** | **15/15** | Gate superado |

---

## Open Questions

Nenhuma — ACs do operador + 3 decisões (a/b/c) fecham o desenho.

---

## Revision History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-29 | Criação a partir do BRAINSTORM_VISUAL_PADRAO_PAINEL | define-agent |
