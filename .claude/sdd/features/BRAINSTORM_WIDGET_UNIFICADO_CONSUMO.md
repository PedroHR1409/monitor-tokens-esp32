# BRAINSTORM: Widget unificado de consumo (heatmap 30d + pódio de agentes)

> Sessão exploratória para clarificar intenção e abordagem antes da captura de requisitos

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | WIDGET_UNIFICADO_CONSUMO |
| **Date** | 2026-08-28 |
| **Author** | brainstorm-agent |
| **Status** | ✅ Complete (Defined) |

---

## Initial Idea

**Raw Input:** "Substituir os cards 7/8/9 e a faixa do heatmap 12h por um widget
full-width (~304x160) com duas visões alternadas por toque. Visão 1 (padrão): heatmap
estilo GitHub do consumo diário de tokens em 30 dias — um quadrado por dia, paleta
verde exata do GitHub dark (#161B22, #0E4429, #006D32, #26A641, #39D353), intensidade
relativa ao pico, sem rótulos; o daemon precisa persistir total diário de tokens
(Claude+Codex+OpenCode) em SQLite com retenção de 35 dias e expor stats.history.daily
(aditivo) no POST /sessions. Visão 2 (ao apertar): pódio top 3 dos agentes por consumo
no período selecionado (hoje/7d/30d, chip ciclado por toque, hoje como padrão), cada
barra com ícone do provider (GLM→Z.AI, DeepSeek→DeepSeek) e rótulo de tokens; tocar
numa barra abre modal com as sessões daquele agente ordenadas por gasto (top 6,
stats.usage.top aditivo)."

**Context Gathered:**
- Área inferior atual: 3 cards (tokens hoje, Codex 5h, card rotativo) + faixa heatmap 12h
- SQLite stdlib já configurado (`monitor.toml → storage.database_path`), mas NENHUMA
  persistência de histórico existe hoje — o daemon só agrega em memória
- Parsing aditivo já é padrão no `session_transport.cpp` (campo novo/ausente não quebra)
- Scaffolding de toque/modal já validado (seletor de sessões + card rotativo)
- Coletores das 3 fontes já normalizam tokens por sessão (Claude transcripts com dedup,
  Codex rollout com diff acumulativo, OpenCode turnos no `opencode.db`)
- Ícones por provider já existem (`icon_for_provider()`: GLM→Z.AI, DeepSeek→DeepSeek)

**Technical Context Observed (for Define):**

| Aspect | Observation | Implication |
|--------|-------------|-------------|
| Likely Location | `tools/usage_history.py` (novo), `tools/session_daemon.py`, `src/ui/ui_dashboard.cpp`, `src/sessions/session_transport.cpp`, `include/session_model.h` | Persistência no daemon; widget substitui bloco dos cards inferiores |
| Relevant KB Domains | `python`, `testing`, `shared`, `data-modeling` | Agregação incremental, fixtures de contrato, retenção |
| IaC Patterns | N/A (config local `monitor.toml`) | Sem infra nova |

---

## Discovery Questions & Answers

| # | Question | Answer | Impact |
|---|----------|--------|--------|
| 1 | Estratégia de entrega: tudo junto, duas fases ou build intermediário? | **(b) Duas fases** — Escopo A (heatmap+persistência) valida na placa antes do Escopo B (pódio+modal) | DEFINE/DESIGN/BUILD quebrados em 2 entregas; gap de cota aceito entre elas |
| 2 | Semântica do "consumo do dia": quais tokens contam? | **(a) input + output + reasoning + cache.write** (ignora cache.read) | Consistência com cards/sessões existentes; cache.read não é queima nova |
| 3 | Histórico inicial: do zero, backfill ou contínuo? | **(b) Backfill one-shot** no primeiro ciclo, limitado à cobertura dos arquivos-fonte | Widget nasce útil; dias sem cobertura ficam na cor vazia, sem inventar dado |
| 4 | (Sessão anterior) Card rotativo vs opções fixas para cota | Evoluiu para widget unificado com pódio — usuário escolheu rotação por toque | Visão 2 herda o padrão de estado do operador (sobrevive a refresh) |

**Minimum Questions:** 3 ✅ (mais ~6 decisões pré-validadas nesta sessão, ver Key Decisions)

---

## Sample Data Inventory

| Type | Location | Count | Notes |
|------|----------|-------|-------|
| Ground truth visual | Imagem do heatmap GitHub (dark) fornecida pelo usuário | 1 | Referência exata de paleta/layout |
| Output examples | Payloads reais do `POST /sessions` nos testes (`tests/fixtures/`) | ~6 | Formato do contrato aditivo |
| Related code | `src/ui/ui_dashboard.cpp` (faixa 12h + card rotativo + picker) | 3 blocos | Base de render e scaffolding de modal/toque |
| Related code | `tools/quota.py`, `tools/opencode_sessions.py`, `tools/usage_tracker.py` | 3 módulos | Semântica de tokens e agregação por janela |

**How samples will be used:**

- Paleta/layout validados contra a imagem do GitHub (hardware)
- Fixtures de payload para testes de contrato (30 dias fixos; 3 períodos × 3 providers)
- Reuso direto da semântica de tokens já implementada nos coletores

---

## Approaches Explored

### Approach A: Persistência diária no daemon (SQLite) ⭐ Recommended

**Description:** Tabela `usage_history` (dia local `YYYY-MM-DD`, tokens) com upsert a
cada ciclo + backfill one-shot; payload carrega 30 dias + 3 janelas do pódio inteiros.

**Pros:**
- Sobrevive a restart; consultas triviais
- Heatmap e pódio nunca discordam (mesma fonte)
- Chip de período instantâneo (tudo já vem no payload)
- Backfill reusa o código de agregação diária do pódio

**Cons:**
- Mais uma tabela (prune de 35 dias, rodar por hora)

**Why Recommended:** Confiança 0,95 — padrão KB de agregação incremental + match
direto com o codebase (SQLite stdlib já configurado; dedup de tokens já resolvido).

### Approach B: Recomputar por dia a cada ciclo (sem persistência)

**Description:** Reler as fontes e agregar dia a dia a cada ciclo de 5s.

**Pros/Cons:** Zero estado novo, porém reler centenas de MB por ciclo é inviável e o
histórico morre quando os arquivos-fonte rotacionam.

### Approach C: Acumular no firmware (NVS)

**Description:** A placa acumula localmente os totais recebidos.

**Pros/Cons:** Zero mudança no daemon, mas o dado perde o dono (reset da placa =
história morta), NVS é pequena e sofre desgaste, backfill impossível.

---

## Selected Approach

| Attribute | Value |
|-----------|-------|
| **Chosen** | Approach A |
| **User Confirmation** | 2026-08-28, sessão OpenCode ("Sim") |
| **Reasoning** | Única que sobrevive a restart E respeita o custo do ciclo; reusa tudo que o projeto já tem |

---

## Key Decisions Made

| # | Decision | Rationale | Alternative Rejected |
|---|----------|-----------|----------------------|
| 1 | Entrega em duas fases (A: heatmap; B: pódio+modal) | Risco menor; hardware validado por fase | Build único (cota fora do ar por mais tempo sem ganho) |
| 2 | Consumo = input+output+reasoning+cache.write | Consistência com painel inteiro | Incluir cache.read (infla ~20x) |
| 3 | Backfill one-shot limitado à cobertura dos arquivos | Widget útil na primeira flash | Do zero (30 dias para ficar útil) / contínuo (frágil) |
| 4 | Push integral das janelas (30d + 3 períodos) no payload | Chip instantâneo; board é server, não client | Fetch on-demand (exigiria servidor no PC) |
| 5 | Toque alterna exatamente 2 visões | Simplicidade; padrão do card rotativo | Carrossel >2 visões |
| 6 | "Hoje" pelo fuso do daemon (`daemon.timezone`) | Placa é viewport, não autoridade de data | Fuso da placa (NTP já existe, mas o dado é do PC) |
| 7 | Cap de 6 sessões no modal; total do provider é a soma completa | Ranking honesto; payload ~2-3KB | Lista infinita / cap alterando total |
| 8 | Lacuna de cota aceita entre as fases | Documentada; pódio não replica cota | Manter cards antigos até a fase B (tela em transição) |

---

## Features Removed (YAGNI)

| Feature Suggested | Reason Removed | Can Add Later? |
|-------------------|----------------|----------------|
| Zoom/scroll na janela do heatmap | 30 dias fixo resolve a pergunta | Yes (/iterate) |
| Quebra diária por provider no heatmap | Pódio cobre o recorte por agente | Yes |
| Rótulos (dias/meses) no heatmap | Exigência explícita do usuário | No |
| Fetch on-demand das janelas | Transporte é daemon→board; push resolve | No |
| Deep-link: tocar em sessão do modal abre o detalhe | Fora do MVP do widget | Yes (/iterate) |
| Barras de cota 5h/semanal no pódio | Cota é oficial só do Codex; pódio é consumo | Yes |

---

## Incremental Validations

| Section | Presented | User Feedback | Adjusted? |
|---------|-----------|---------------|-----------|
| Entrega em fases + semântica + backfill | ✅ | (a), (a), (b) confirmados | Yes |
| Abordagens (A/B/C) | ✅ | "Sim" para A | Yes |
| Render/layout (grid 5×7, chip, modal, fuso) | ✅ | "sim" | No |
| Pódio, chip e período (sessão anterior) | ✅ | "Funcionou a rotação" → evoluiu para widget | Yes |
| Paleta GitHub exata + sem rótulos (usuário) | ✅ | Exigência original | N/A |

**Minimum Validations:** 2 ✅

---

## Suggested Requirements for /define

### Problem Statement (Draft)
O painel não mostra consumo de tokens através dos dias nem onde ele se concentra por
agente — a área inferior mostra apenas recortes de curto prazo (12h) e números pontuais.

### Target Users (Draft)
| User | Pain Point |
|------|------------|
| Operador do painel (você) | Não vê tendência de consumo nem o agente mais pesado num relance |

### Success Criteria (Draft)
- [ ] Heatmap 30 dias com paleta GitHub exata, sem rótulos, hoje = última célula
- [ ] Histórico sobrevive a restart do daemon; backfill no primeiro ciclo
- [ ] Pódio ordena os 3 agentes por consumo em hoje/7d/30d; chip instantâneo
- [ ] Modal lista sessões por gasto (top 6) e fecha no backdrop
- [ ] Payload aditivo: firmware antigo ignora campos novos; payload antigo não quebra firmware novo
- [ ] pytest 100%, check_secrets limpo, pio run nos 2 envs, flash validada

### Constraints Identified
- Tools PC só stdlib; protocolo `POST /sessions` aditivo; LVGL 9; área ~304x160
- Fuso do dia local = `daemon.timezone`; "hoje" é autoridade do daemon
- Gap de cota aceito entre as fases

### Out of Scope (Confirmed)
- Zoom/scroll no heatmap; rótulos; quebra diária por provider no heatmap
- Deep-link modal→detalhe de sessão; barras de cota no pódio; fetch on-demand

---

## Session Summary

| Metric | Value |
|--------|-------|
| Questions Asked | 3 (+~6 decisões pré-validadas na sessão) |
| Approaches Explored | 3 |
| Features Removed (YAGNI) | 6 |
| Validations Completed | 5 |
| Duration | ~30 min (continuação de sessão longa) |

---

## Next Step

**Ready for:** `/define .claude/sdd/features/BRAINSTORM_WIDGET_UNIFICADO_CONSUMO.md`

**Nota de phasing:** no DEFINE, capturar Escopo A (heatmap + persistência + payload)
e Escopo B (pódio + modal + `stats.usage.top`) como requisitos separados dentro da
mesma feature, com build/flash na ordem A → B.
