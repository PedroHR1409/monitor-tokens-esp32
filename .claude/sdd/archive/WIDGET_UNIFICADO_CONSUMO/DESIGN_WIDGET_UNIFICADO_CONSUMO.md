# DESIGN: Widget unificado de consumo (heatmap 30d + pódio de agentes)

> Technical design for implementing WIDGET_UNIFICADO_CONSUMO

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | WIDGET_UNIFICADO_CONSUMO |
| **Date** | 2026-08-28 |
| **Author** | design-agent |
| **DEFINE** | [DEFINE_WIDGET_UNIFICADO_CONSUMO.md](./DEFINE_WIDGET_UNIFICADO_CONSUMO.md) |
| **Status** | ✅ Shipped |
| **Design Confidence** | 0,95 (KB `python`/`testing`/`shared` + agentes casados no manifest) |

---

## Architecture Overview

```text
┌────────────────────────────── PC (daemon) ──────────────────────────────┐
│                                                                         │
│  [Transcripts Claude]──┐                                                │
│  [Rollouts Codex]──────┼─→ [Agregadores por sessão (existentes)]        │
│  [opencode.db]─────────┘            │                                   │
│                                     ▼                                   │
│                     [usage_history.py  (NOVO)]                          │
│                      • total do dia → UPSERT SQLite                     │
│                      • backfill one-shot (1º boot)                      │
│                      • prune > 35 dias (1x/hora)                        │
│                      • janelas 1/7/30 → pódio (Escopo B)                │
│                                     │                                   │
│                                     ▼                                   │
│         [build_payload_v1/v2] += stats.history.daily (A)                │
│                              += stats.usage.top     (B)                 │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │ POST /sessions (HTTP, aditivo)
                                      ▼
┌──────────────────────────── ESP32-S3 (LVGL 9) ──────────────────────────┐
│  [session_transport.cpp] parse aditivo → UsageHistory + ProviderTop     │
│                                     │                                   │
│                                     ▼                                   │
│  [ui_dashboard.cpp] WIDGET UNIFICADO (~304x160, estado do operador)     │
│   ┌─ Visão 1: heatmap 30d (5 semanas × 7 dias, paleta GitHub)           │
│   └─ Visão 2: pódio top 3 + chip hoje/7d/30d + modal de sessões         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Phasing:** Escopo A = persistência + `stats.history.daily` + visão 1 (heatmap) +
alternância de visão. Escopo B = `stats.usage.top` + visão 2 (pódio, chip, modal).

---

## Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| `tools/usage_history.py` (novo) | Persistência diária: upsert, janela 30d, backfill, prune; leitura para payload | Python 3.10+, `sqlite3` (stdlib) |
| `tools/session_daemon.py` (modif.) | Integra: persiste por ciclo, dispara backfill, injeta campos novos nos builders | Python stdlib |
| `tools/usage_tracker.py` / `quota.py` / `opencode_sessions.py` (modif.) | Agregação por janela 1/7/30 reusando coletores existentes (sem contador novo) | Python stdlib |
| `include/session_model.h` (modif.) | `UsageHistory { daily[30]; valid }` + structs de pódio (Escopo B) | C++ header |
| `src/sessions/session_transport.cpp` (modif.) | Parse aditivo dos dois blocos JSON | ArduinoJson 7 |
| `src/ui/ui_dashboard.cpp` (modif.) | Widget unificado: alternância, heatmap, pódio, chip, modal | LVGL 9 |
| `include/ui_theme.h` (modif.) | Paleta GitHub (`HM_EMPTY`, `HM_L1..L4`) | C++ constexpr |
| `tests/test_usage_history.py` (novo) + fixtures | Contratos de persistência, payload e agregação | pytest |

---

## Key Decisions

### Decision 1: Histórico em SQLite no daemon, com backfill one-shot

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-28 |

**Context:** Nenhuma persistência existe; o heatmap precisa de 30 dias que sobrevivam
a restart e a rotação dos arquivos-fonte.

**Choice:** Tabela `usage_history(day TEXT PK, tokens INTEGER NOT NULL)`; upsert por
ciclo antes do POST; prune `DELETE WHERE day < date('now','-35 days')` 1x/hora;
backfill no primeiro boot (flag em `storage` — detecta tabela vazia), limitado à
cobertura real das fontes.

**Rationale:** Única abordagem que sobrevive a restart E respeita o custo do ciclo de
5s; reusa o SQLite já configurado (`storage.database_path`) e a semântica de tokens já
implementada nos coletores (confiança 0,95).

**Alternatives Rejected:**
1. Recomputar por ciclo — reler centenas de MB a cada 5s; histórico morre com a rotação
2. Acumular na NVS da placa — dado sem dono, desgaste de flash, sem backfill

**Consequences:**
- Uma tabela nova para manter (prune simples)
- Histórico honesto e durável; dias sem cobertura = 0 explícito

---

### Decision 2: Push integral das janelas (sem fetch on-demand)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-28 |

**Context:** O chip de período precisa trocar sem latência; o transporte é
unidirecional (daemon→board; a placa é HTTP server mas o dado mora no PC).

**Choice:** Todo payload carrega `daily[30]` (Escopo A) e as 3 janelas × 3 providers
com top-6 sessões (Escopo B, ~2-4 KB).

**Rationale:** Trocar de período vira troca de ponteiro no firmware; zero novos
endpoints. Cap 6 + nome 25 chars mantém o parse confortável no ArduinoJson.

**Alternatives Rejected:**
1. Board buscar do PC — exigiria servidor HTTP no PC e descoberta de IP (inversão do transporte)
2. Só o período "hoje" no payload — chip precisaria esperar ciclo novo a cada troca

**Consequences:**
- Payload cresce ~1,6 KB (A) + ~2-3 KB (B) — aceitável na ESP32-S3
- Mitigação se R2 falhar: cap 6→4 sessões ou nome 25→16 chars (DEFINIDO no risco R2)

---

### Decision 3: Escala do heatmap relativa ao pico da janela

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-28 |

**Context:** "Alto consumo" é relativo (dia de 50k vs 5M); tiers absolutos exigiriam
calibração manual por usuário.

**Choice:** Nível = faixa de `tokens_dia / pico_30d`: vazio (0), L1 (1-25%), L2
(26-50%), L3 (51-75%), L4 (>75%).

**Rationale:** Mesma leitura visual do GitHub independente da escala absoluta;
nenhuma configuração nova.

**Alternatives Rejected:**
1. Tiers absolutos fixos (ex.: 1M por nível) — inútil entre perfis de uso distintos
2. Escala logarítmica — pior de explicar; pico relativo já comprime a cauda

**Consequences:**
- Um dia isolado de pico "achata" o resto (comportamento igual ao GitHub — aceito)

---

### Decision 4: Agregação reusa os coletores existentes (zero contadores novos)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-28 |

**Context:** Três fontes com semântica de tokens já normalizada e dedup resolvido.

**Choice:** Janelas 1/7/30 e total diário saem das MESMAS funções que alimentam
sessões hoje (`session_tokens(path, since)`, `codex_meta(tid, since)`,
`opencode_sessions` por turno). Semântica fixada: `input+output+reasoning+cache.write`.

**Rationale:** Heatmap, pódio e tela de detalhe nunca podem discordar; uma única
fonte de verdade por provider elimina a classe inteira de bugs de divergência.

**Alternatives Rejected:**
1. Contador paralelo dedicado — segunda verdade, diverge com o tempo
2. Somar no firmware a partir de sessões — a placa não vê histórico, só o board atual

**Consequences:**
- Custo de agregação por ciclo (mitigado pelos caches de mtime/tamanho já existentes)

---

## File Manifest

| # | File | Action | Purpose | Agent | Dependencies |
|---|------|--------|---------|-------|--------------|
| 1 | `tools/usage_history.py` | Create | Persistência diária, janela 30d, backfill, prune | @python-developer | None |
| 2 | `tests/test_usage_history.py` | Create | Contratos AT-001..004 + formato do payload | @test-generator | 1 |
| 3 | `tools/session_daemon.py` | Modify | Integra persistência/backfill; injeta `stats.history.daily` (A) e `stats.usage.top` (B) | @python-developer | 1 |
| 4 | `tools/usage_tracker.py`, `tools/quota.py`, `tools/opencode_sessions.py` | Modify | Helpers de agregação por janela 1/7/30 (Escopo B) | @python-developer | 1 |
| 5 | `tests/test_session_daemon.py`, `tests/test_quota.py` | Modify | AT-003, AT-007/008 (contrato), AT-010..012 (agregação) | @test-generator | 3, 4 |
| 6 | `include/session_model.h` | Modify | `UsageHistory` + structs de pódio | @build-agent | None |
| 7 | `src/sessions/session_transport.cpp` | Modify | Parse aditivo dos dois blocos | @build-agent | 6 |
| 8 | `include/ui_theme.h` | Modify | Paleta GitHub `HM_*` | @build-agent | None |
| 9 | `src/ui/ui_dashboard.cpp` | Modify | Remove cards/faixa 12h; widget unificado, heatmap, pódio, chip, modal (fases A e B) | @build-agent | 6, 7, 8 |
| 10 | `docs/SPEC.md`, `README.md` | Modify | Seção do widget; deprecação das seções 12/15 | @code-documenter | 9 |
| 11 | Revisão final de diff + `check_secrets.py` | Verify | Gate de segurança e qualidade | @code-reviewer | 1-10 |
| 12 | `pio run` nos 2 envs + flash COM3 + validação na placa | Verify | AT-005/006/009/013..015 | @ci-cd-specialist | 9 |

**Total Files:** 9 código + 3 verificação

---

## Agent Assignment Rationale

| Agent | Files Assigned | Why This Agent |
|-------|----------------|----------------|
| @python-developer | 1, 3, 4 | Especialista Python do `.claude/agents/python/`; stdlib-only e convenções do daemon |
| @test-generator | 2, 5 | Geração de testes a partir de critérios de aceite (AT-001..012) |
| @build-agent | 6, 7, 8, 9 | Orquestrador do build; firmware C++/LVGL não tem especialista dedicado no conjunto de 18 — delegação direta com padrões do codebase |
| @code-documenter | 10 | Atualização de SPEC/README no estilo existente |
| @code-reviewer | 11 | Revisão de diff, segredos e consistência com as regras duras |
| @ci-cd-specialist | 12 | Builds PlatformIO, flash e validação de hardware |

**Agent Discovery:** varredura de `.claude/agents/**/*.md` (18 agentes); casamento
por tipo de arquivo + palavras-chave (sqlite/pytest/lvgl/flash). Sem especialista C++
no conjunto — assumido pelo @build-agent com os padrões do próprio `src/` (confiança 0,80,
validada no hardware na fase de verificação).

---

## Code Patterns

### Pattern 1: UPSERT diário com janela fixa (SQLite stdlib)

```python
# tools/usage_history.py — idempotente por dia; usa o banco já configurado
DAY = "date('now', 'localtime')"

def record_today(db_path: Path, tokens: int) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO usage_history(day, tokens) VALUES "
            f"({DAY}, ?) ON CONFLICT(day) DO UPDATE SET tokens = excluded.tokens",
            (tokens,))

def daily_window(db_path: Path, days: int = 30) -> list[int]:
    rows = dict(con.execute(
        "SELECT day, tokens FROM usage_history "
        f"WHERE day >= date('now', 'localtime', '{-days + 1} days')"))
    today = date.today()
    return [rows.get((today - timedelta(days=i)).isoformat(), 0)
            for i in range(days - 1, -1, -1)]        # oldest-first
```

### Pattern 2: Campo aditivo no payload (builders versionados)

```python
# tools/session_daemon.py — campo NOVO, nunca renomear existentes
"stats": {
    ...,  # campos existentes intocados
    "history": {"daily": usage_history.daily_window(db)},          # Escopo A
    "usage": {**usage, "top": usage_top.build(db, ...)},           # Escopo B
}
```

### Pattern 3: Parse aditivo no transporte (firmware)

```cpp
// src/sessions/session_transport.cpp — ausente = feature inativa, NUNCA 422
JsonArray hist = st["history"]["daily"].as<JsonArray>();
if (!hist.isNull()) {
    int i = 0;
    for (JsonVariant v : hist) {
        if (i >= USAGE_DAYS) break;
        usageHistory.daily[i++] = v | 0UL;
    }
    usageHistory.valid = (i == USAGE_DAYS);
}
```

### Pattern 4: Render com cache de redraw (LVGL, convenção do ui_dashboard)

```cpp
// um objeto por célula criado 1x; cor via set_color_if (cache uint32_t)
for (int i = 0; i < USAGE_DAYS; i++) {
    uint32_t hex = heatmap_color(usageHistory.daily[i], peak);
    set_color_if(g_uwCell[i], g_cUwCell[i], hex, lv_obj_set_style_bg_color);
}
```

---

## Data Flow

```text
1. Ciclo do daemon (5s): coletores leem as 3 fontes (caches de mtime evitam re-ler)
   │
   ▼
2. Agregação: total do dia → UPSERT em usage_history; 1º boot → backfill one-shot
   │
   ▼
3. build_payload_v1/v2: stats.history.daily (A) + stats.usage.top (B) — aditivos
   │
   ▼
4. POST /sessions → session_transport.cpp parseia campos novos (tolerante a ausência)
   │
   ▼
5. ui_dashboard.cpp: widget unificado renderiza a visão escolhida pelo operador
   │
   ▼
6. Prune horário remove dias > 35
```

---

## Integration Points

| External System | Integration Type | Authentication |
|-----------------|-----------------|----------------|
| Transcripts Claude (`~/.claude/projects`) | Leitura de arquivos JSONL | N/A (local) |
| Rollouts Codex (`~/.codex/sessions`) | Leitura de arquivos JSONL | N/A (local) |
| OpenCode (`opencode.db`) | SQLite readonly (`file:...?mode=ro`) | N/A (local) |
| Placa ESP32 (`POST /sessions`) | HTTP + header `X-Monitor-Token` | Token compartilhado (já existente) |

---

## Testing Strategy

| Test Type | Scope | Files | Tools | Coverage Goal |
|-----------|-------|-------|-------|---------------|
| Unit | `usage_history` (upsert, janela, prune, backfill) | `tests/test_usage_history.py` | pytest + tmp db | AT-001..004 |
| Unit/Contrato | Payload com campos novos/ausentes | `tests/test_session_daemon.py` | pytest + fixtures herméticos | AT-003, AT-007/008 |
| Unit/Contrato | Agregação 1/7/30 (ordem, cap, zero, tie-break) | `tests/test_quota.py` (ou novo `test_usage_top.py`) | pytest + fixtures | AT-010..012 |
| Unit | Parse de transporte tolerante | `tests/test_production_contracts.py` (padrão) | pytest | AT-007/008 (lado firmware) |
| E2E Hardware | Paleta, hoje, toque, chip, modal, sem resíduos | Placa via COM3 | Manual + `--once` do daemon | AT-005/006/009/013..015 |

**Rastreabilidade:** cada AT do DEFINE mapeia para ≥1 teste acima; AT-015 é o gate
manual de hardware antes do `/ship`.

---

## Next Step

**Ready for:** `/build .claude/sdd/features/DESIGN_WIDGET_UNIFICADO_CONSUMO.md`
(Executar Escopo A → validar na placa → Escopo B → validar na placa, conforme DEFINE)
