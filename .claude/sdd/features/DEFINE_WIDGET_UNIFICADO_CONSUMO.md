# DEFINE: Widget unificado de consumo (heatmap 30d + pódio de agentes)

> Widget full-width no rodapé do Monitor.AI: heatmap estilo GitHub do consumo diário
> de tokens (30 dias) e pódio top 3 dos agentes com drill-down de sessões, alimentados
> por histórico persistido no daemon.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | WIDGET_UNIFICADO_CONSUMO |
| **Date** | 2026-08-28 |
| **Author** | define-agent |
| **Status** | ✅ Complete (Designed) |
| **Clarity Score** | 15/15 |
| **Input** | `BRAINSTORM_WIDGET_UNIFICADO_CONSUMO.md` (brainstorm_document, pré-validado) |

---

## Problem Statement

O painel não mostra o consumo de tokens através dos dias nem onde ele se concentra por
agente: a área inferior exibe apenas recortes de curto prazo (heatmap de 12h) e
números pontuais de cota, então o operador não percebe tendências nem identifica o
agente mais pesado num relance.

---

## Target Users

| User | Role | Pain Point |
|------|------|------------|
| Operador do painel (dono do dispositivo) | Único usuário; acompanha seus agentes Claude/Codex/OpenCode na mesa | Não vê tendência de consumo ao longo dos dias nem qual agente queima mais; precisa cruzar 4 widgets para deduzir isso |

---

## Goals

| Priority | Goal | Fase |
|----------|------|------|
| **MUST** | Persistir total diário de tokens (Claude+Codex+OpenCode) em SQLite com retenção ≥ 35 dias, sobrevivendo a restart | A |
| **MUST** | Heatmap estilo GitHub de 30 dias: um quadrado por dia, paleta exata `#161B22/#0E4429/#006D32/#26A641/#39D353`, intensidade relativa ao pico, sem rótulos | A |
| **MUST** | Expor `stats.history.daily` (30 ints, oldest-first) como campo **aditivo** no `POST /sessions`; backfill one-shot no primeiro ciclo limitado à cobertura dos arquivos-fonte | A |
| **MUST** | Widget full-width com toque alternando as 2 visões; escolha do operador sobrevive a refresh | A/B |
| **MUST** | Pódio top 3 dos agentes por consumo no período, com ícone do provider (GLM→Z.AI, DeepSeek→DeepSeek) e rótulo de tokens; total = soma completa | B |
| **MUST** | Modal de drill-down: sessões do provider ordenadas por gasto (top 6), estado vazio explícito, fecha no backdrop | B |
| **SHOULD** | Chip de período hoje/7d/30d na visão 2, ciclado por toque, padrão "hoje", instantâneo (janelas já no payload `stats.usage.top`) | B |
| **SHOULD** | Backfill documentado: dias sem cobertura ficam na cor vazia, sem inventar dado | A |
| **COULD** | Empate no pódio com tie-break determinístico por nome do provider | B |

---

## Success Criteria

- [ ] `pytest tests/ -q` 100% verde, incluindo: upsert no mesmo dia, sobrevivência a
      restart, zero-padding de instalação jovem, prune > 35 dias, formato do payload
      (30 ints) e agregação 1/7/30 com cap de 6 e total intacto
- [ ] `python tools/check_secrets.py` limpo; nenhum token em logs/payload (redação
      `***redacted***` mantida)
- [ ] `pio run` OK nos envs `esp32-s3-3v5-lcd` e `esp32-s3-3v5-lcd-demo`
- [ ] Na placa: paleta do heatmap confere com GitHub dark; hoje = última célula;
      ciclo de payload não reverte visão nem período escolhidos
- [ ] Payload **sem** os campos novos não é rejeitado pelo firmware novo; payload
      **com** os campos novos não quebra firmware antigo
- [ ] Ciclo do daemon continua ≤ intervalo configurado (5s padrão) com a agregação
      nova (persistência + backfill não degradam o ciclo além de 1s no primeiro boot)

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | Upsert diário | Dois ciclos do daemon no mesmo dia local | Segundo ciclo persiste | 1 linha do dia, tokens somados (não duplicados) |
| AT-002 | Restart do daemon | Histórico com N dias persistidos | Daemon parado e iniciado | N dias intactos e presentes no próximo payload |
| AT-003 | Instalação jovem | < 30 dias de histórico | Payload montado | `stats.history.daily` com exatamente 30 entradas; faltantes = 0 |
| AT-004 | Retenção | Histórico com dia > 35 dias | Prune horário roda | Linhas antigas removidas; janela de 30 intacta |
| AT-005 | Escala de cor | Janela com pico P | Dia com 0 / 1-25% / 26-50% / 51-75% / >75% de P | Quadrados nas cores vazia/L1/L2/L3/L4 exatas |
| AT-006 | Hoje | Dia local corrente com consumo parcial | Payload novo chega | Última célula reflete o parcial; data = fuso `daemon.timezone` |
| AT-007 | Compatibilidade de protocolo | Firmware novo | Payload sem `stats.history.daily`/`stats.usage.top` | Aceito; feature inativa sem erro |
| AT-008 | Compatibilidade reversa | Firmware antigo (pré-widget) | Payload com os campos novos | Campos ignorados; nenhum 422 |
| AT-009 | Alternância de visão | Visão 1 ativa | Toque curto no widget | Alterna heatmap ↔ pódio; 2 payloads depois, escolha mantida |
| AT-010 | Ranking do pódio | Totais distintos por provider no período | Visão 2 renderiza | Ordem exata, rank 1 primeiro, com ícone e rótulo de tokens |
| AT-011 | Provider sem uso | Provider com 0 tokens no período | Visão 2 renderiza | Barra presente com "0" (3 agentes sempre visíveis) |
| AT-012 | Cap do modal | Provider com 9 sessões no período | Modal aberto | 6 sessões mais pesadas, ordenadas desc.; total do pódio segue = soma das 9 |
| AT-013 | Modal vazio | Provider sem sessões no período | Modal aberto | Estado vazio explícito ("sem sessoes"), não lista em branco |
| AT-014 | Fechar modal | Modal aberto | Toque no backdrop | Modal fecha; pódio restaurado no mesmo período |
| AT-015 | Hardware | Firmware A e B gravados | Uso real por 1 ciclo de payload | Sem cards/faixa antigos residuais; toque chip > barra > visão sem conflito |

---

## Out of Scope

- Zoom/scroll ou janela configurável no heatmap (30 dias fixo)
- Rótulos de dia/mês no heatmap (exigência do usuário)
- Quebra diária por provider dentro do heatmap (pódio cobre o recorte por agente)
- Fetch on-demand das janelas (transporte permanece daemon→board, push integral)
- Deep-link do modal para a tela de detalhe da sessão (candidato a `/iterate`)
- Barras/percentuais de cota oficial (Codex 5h/semanal) no pódio
- Multi-nó (consolidação por `node_id`) no histórico

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Technical | Tools PC só stdlib (Python 3.10+), sem `pip install` | Persistência via `sqlite3`; sem ORM/agendador |
| Technical | Protocolo `POST /sessions` só aditivo | Campos novos opcionais; sem renomear/mover existentes |
| Technical | LVGL 9 + ArduinoJson 7; área alvo ~304×160 px | Grid e pódio dimensionados para o espaço; PSRAM disponível |
| Technical | Fuso do "hoje" = `daemon.timezone` (padrão `America/Sao_Paulo`) | Dia local calculado no daemon; placa é viewport |
| Operational | Gap de cota entre as fases (cards 7/8/9 saem no Escopo A) | Aceito e documentado; pódio não replica cota |
| Operational | Hooks de estado têm caminhos estáveis | Nenhuma mudança em `tools/session_hook.py` etc. |

---

## Assumptions & Risk Register

| ID | Assumption | Impact if Wrong | Validated |
|----|-----------|-----------------|-----------|
| R1 | Arquivos-fonte (transcripts, rollouts, `opencode.db`) retêm ≥ alguns dias de histórico para o backfill | Backfill cobre menos dias; heatmap começa mais vazio (honesto, não quebra) | ☐ |
| R2 | Payload +2-4 KB (30 ints + top sessions) cabe no budget de parse do ArduinoJson na ESP32-S3 | Parse falha → reduzir cap de sessões para 4 ou nomes para 16 chars | ☐ |
| R3 | Ciclo de 5s continua cumprido com upsert + agregação incremental (cache por mtime/já existente) | Aumentar intervalo do ciclo ou mover agregação pesada para o prune horário | ☐ |
| R4 | 30 ints + top sessions não expõem segredo (apenas contagens e nomes de projeto truncados) | Vazamento → redigir nomes como no catálogo (já truncado) | ☑ |

---

## Technical Context

| Aspect | Value | Notes |
|--------|-------|-------|
| **Deployment Location** | `tools/usage_history.py` (novo), `tools/session_daemon.py`, `src/ui/ui_dashboard.cpp`, `src/sessions/session_transport.cpp`, `include/session_model.h`, `include/ui_theme.h` | Persistência no daemon; widget substitui o bloco dos cards inferiores |
| **KB Domains** | `python`, `testing`, `shared`, `data-modeling` | Agregação incremental, fixtures de contrato, modelagem do histórico |
| **IaC Impact** | None | Só o SQLite local já configurado (`storage.database_path`) |

---

## Data Contract (if applicable)

### Source Inventory
| Source | Type | Volume | Freshness | Owner |
|--------|------|--------|-----------|-------|
| Transcripts Claude (`~/.claude/projects`) | Arquivos JSONL locais | ~100 arquivos | Contínuo (hooks + turnos) | daemon |
| Rollouts Codex (`~/.codex/sessions`) | Arquivos JSONL locais | ~40 threads ativas | Contínuo enquanto o Codex roda | daemon |
| OpenCode (`~/.local/share/opencode/opencode.db`) | SQLite (readonly) | Centenas de mensagens/dia | Contínuo | daemon |

### Schema Contract
| Column | Type | Constraints | PII? |
|--------|------|-------------|------|
| `usage_history.day` | TEXT | PK, formato `YYYY-MM-DD` local | No |
| `usage_history.tokens` | INTEGER | NOT NULL, ≥ 0 | No |
| `stats.history.daily` | JSON array | Exatamente 30 ints, oldest-first | No |
| `stats.usage.top.{d1,d7,d30}.{claude,codex,opencode}` | JSON object | `total` int; `sessions[]` ≤ 6 (id, name ≤ 25, tokens) | No (nomes truncados) |

### Freshness & Completeness
- Total do dia atualizado a cada ciclo do daemon (5s padrão); prune horário.
- Dias sem cobertura de backfill = 0 explícito (nunca estimado).

---

## Clarity Score Breakdown

| Element | Score | Notes |
|---------|-------|-------|
| Problem | 3 | Uma frase, específico, acionável |
| Users | 3 | Persona única com dor explícita (produto pessoal de mesa) |
| Goals | 3 | MoSCoW com fase (A/B) e critério por goal |
| Success | 3 | Critérios mensuráveis e testáveis (pytest/hardware/protocolo) |
| Scope | 3 | Out-of-scope explícito com 7 exclusões |
| **Total** | **15/15** | Gate 12/15 superado — sem gaps a perguntar |

---

## Next Step

`/ship .claude/sdd/features/DESIGN_WIDGET_UNIFICADO_CONSUMO.md`

## Open Questions

Nenhuma em aberto — as 3 perguntas de descoberta e as ~6 decisões pré-validadas na
sessão foram todas resolvidas e registradas no BRAINSTORM.

---

## Revision History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-28 | Criação a partir do BRAINSTORM validado | define-agent |
