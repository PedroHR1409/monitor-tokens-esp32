# DESIGN: Padronização visual do painel (Cards 1-6, Pódio, Card 7)

> Technical design for implementing VISUAL_PADRAO_PAINEL

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | VISUAL_PADRAO_PAINEL |
| **Date** | 2026-08-29 |
| **Author** | design-agent |
| **DEFINE** | [DEFINE_VISUAL_PADRAO_PAINEL.md](./DEFINE_VISUAL_PADRAO_PAINEL.md) |
| **Status** | ✅ Shipped |
| **Design Confidence** | 0,95 (evolução de widgets já validados; sem peças conceituais novas) |

---

## Architecture Overview

```text
┌──────────────────────────── 304×222 ──────────────────────────┐
│ CONSUMO DE TOKENS (EM MM)                            (título) │ 20px
├────────────────────────────────────────────────┬──────────────┤
│  CARD 7: grade 7×6, células 37×32, GAP 2px     │   ▸ / ◂      │
│  (pitch 39×34, centralizada)                   │ (centrado V) │
├────────────────────────────────────────────────┴──────────────┤
│  VISÃO 2 — PÓDIO (mesma área, título compartilhado):          │
│        [2º]      [1º]      [3º]     ← ordem fixa              │
│      icone     icone     icone     ← cabeçalho                │
│       4,2      7,1       0,6       ← valor em MM              │
│       ▓▓▓      ▓▓▓▓▓▓    ▓         ← barra (altura por rank)  │
│      Codex    Claude    OpenCode  ← nome abaixo               │
└───────────────────────────────────────────────────────────────┘

Nomenclatura (daemon): OpenCode passa a priorizar basename(directory) no campo
`name` do payload — payload/protocolo inalterados.
```

---

## Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| Grade do Card 7 (modif.) | células 37×32 com gap 2px, pitch 39×34 | LVGL (objetos existentes) |
| Faixa da seta (modif.) | container clicável 28×202 com label centrado de verdade | LVGL |
| Barra de inspeção (modif.) | fundo `COLOR_BG` (sem cor de nível); texto sempre branco/dim | LVGL |
| Pódio em colunas (rework) | 3 colunas 2º\|1º\|3º: header (ícone+valor), barra vertical, nome abaixo | LVGL |
| `uw_tokens_str` (modif.) | MM com vírgula decimal, sem sufixo: `7,1` / `0,6` / `0,0` | snprintf |
| `opencode_sessions._project_name` (modif.) | prioriza `basename(directory)` | Python stdlib |

---

## Key Decisions

### Decision 1: Pódio em colunas com altura por RANK (não proporcional)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted (escolha do operador, Q1-a) |
| **Date** | 2026-08-29 |

**Context:** O pódio existente são 3 barras horizontais empilhadas; o AC pede
colunas 2º\|1º\|3º.

**Choice:** 3 colunas de 72px, posições fixas (esq/centro/dir); rank 0→centro,
rank 1→esquerda, rank 2→direita. Alturas de barra: 1º=120px, 2º=88px, 3º=64px,
base alinhada em y=190. Header (ícone 20px + valor MM) acima do topo da barra;
nome do agente abaixo da base.

**Rationale:** Pódio é ranking — altura por rank comunica a ordem instantaneamente;
os valores exatos ficam no cabeçalho.

**Alternatives Rejected:**
1. Altura proporcional ao consumo — vira gráfico de barras, não pódio
2. Colunas de mesma altura com destaque no 1º — hierarquia mais fraca

**Consequences:**
- Estrutura de labels muda (icon/value saem de dentro da barra para o header;
  name sai do interior para baixo)

---

### Decision 2: Formato numérico único em MM, vírgula decimal, unidade no título

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted (escolha do operador, Q2-b) |
| **Date** | 2026-08-29 |

**Context:** Sufixos "M" poluíam e valores pequenos criavam unidades mistas.

**Choice:** `uw_tokens_str` vira: sempre `v/1.000.000` com 1 casa decimal e VÍRGULA
(`7,1`; `0,6`; `0,0`). Título do Card 7: `CONSUMO DE TOKENS (EM MM)`. Aplicado à
barra de inspeção e às colunas do pódio.

**Rationale:** Uma única convenção; a unidade é declarada uma vez no título
(pt-BR usa vírgula — aprovado nos mockups, que usavam "2,5M").

**Alternatives Rejected:**
1. Manter `k` para pequenos — operador rejeitou (Q2)
2. Ponto decimal — contraria o padrão pt-BR já usado nos mockups

**Consequences:**
- Dias quase sem uso mostram "0,0" (R2 do DEFINE — aceitável)

---

### Decision 3: Nomenclatura OpenCode = pasta do `directory`

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted (AC 3) |
| **Date** | 2026-08-29 |

**Context:** `_project_name()` priorizava `title`, que o OpenCode preenche com a
primeira mensagem/resumo ("New session - ...").

**Choice:** Prioridade: `basename(directory)` → `title` → `slug`. Claude (pasta) e
Codex (thread_name) inalterados — as 4 fontes passam a exibir o nome do projeto.

**Rationale:** Consistência total entre cards; o `directory` é o caminho real do
repo (verificado ao vivo: sessões em repos têm directories válidos).

**Alternatives Rejected:**
1. Parsear a 1ª mensagem para "adivinhar" o projeto — frágil e sem fundamento

**Consequences:**
- Sessões fora de repo continuam no fallback (title/slug) — degradação suave

---

### Decision 4: Inspeção sem cor de nível + seta centralizada por container

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted (ACs 1.2 e 1.3) |
| **Date** | 2026-08-29 |

**Context:** Barra de inspeção herdava a cor de nível (verde) e a seta não ficava
centrada verticalmente.

**Choice:** Barra de inspeção com fundo `COLOR_BG` e texto sempre branco/dim
(lógica de contraste por nível removida). Faixa da seta vira CONTAINER clicável
28×202 com o label centrado via `lv_obj_center` (centralização garantida pelo
LVGL, não por heurística de fonte).

**Rationale:** Consistência visual (mesma cor do card) e centralização robusta.

**Alternatives Rejected:**
1. Manter verde com texto adaptado — contraria o AC 1.3
2. Centralizar ajustando y manualmente — frágil com fontes diferentes

**Consequences:**
- `g_cUwInspectBg` e lógica de contraste removidos

---

### Decision 5: Gap 2px com células 37×32

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted (AC 1.1) |
| **Date** | 2026-08-29 |

**Context:** Grade encostada (gap 0) não replicava a distribuição do GitHub.

**Choice:** Pitch 39×34 (célula 37×32 + gap 2), grade 271×202 centralizada na área
de 276×202; título e faixa da seta inalterados.

**Rationale:** Na escala do painel, 2px é o gap que o GitHub usa proporcionalmente;
células continuam grandes e tocáveis.

**Alternatives Rejected:**
1. Gap 3-4px — células encolhem sem ganho visual

**Consequences:**
- Re-alinhamento no update (cache g_cUwY0 já cobre; adicionar pitch ao cache)

---

## File Manifest

| # | File | Action | Purpose | Agent | Dependencies |
|---|------|--------|---------|-------|--------------|
| 1 | `src/ui/ui_dashboard.cpp` | Modify | Gap 2px; seta centralizada (container); inspeção sem verde; pódio em colunas; `uw_tokens_str` em MM | @build-agent | None |
| 2 | `tools/opencode_sessions.py` | Modify | `_project_name`: prioriza `basename(directory)` | @python-developer | None |
| 3 | `tests/test_opencode_sessions.py` | Modify | Novo teste da regra de nome (directory → basename; fallback mantido) | @test-generator | 2 |
| 4 | `tests/test_production_contracts.py` | Modify | Contratos: título com `(EM MM)`; sem formato "M" legado (`.%luM` fora do widget) | @test-generator | 1 |
| 5 | `docs/SPEC.md`, `README.md` | Modify | Seção do widget/pódio/nomenclatura | @code-documenter | 1, 2 |
| 6 | `pio run` + flash + validação na placa | Verify | ATs visuais (gap, pódio, MM) | @ci-cd-specialist | 1 |
| 7 | Revisão de diff + `check_secrets.py` | Verify | Gate de qualidade | @code-reviewer | 1-5 |

**Total Files:** 2 código + 2 testes + 2 docs + 2 verificações

---

## Agent Assignment Rationale

| Agent | Files Assigned | Why This Agent |
|-------|----------------|----------------|
| @build-agent | 1 | LVGL no arquivo que as duas iterações anteriores já instrumentaram |
| @python-developer | 2 | Coletor OpenCode (stdlib, convenções do daemon) |
| @test-generator | 3, 4 | Testes de nome/contratos a partir dos ATs |
| @code-documenter | 5 | SPEC/README |
| @ci-cd-specialist | 6 | Build/flash/hardware |
| @code-reviewer | 7 | Revisão e segredos |

---

## Code Patterns

### Pattern 1: Valor em MM com vírgula (substitui uw_tokens_str)

```python
# firmware (C) — equivalente do exemplo python abaixo
void uw_tokens_str(uint32_t v, char *buf, size_t len) {
    snprintf(buf, len, "%lu,%lu", v / 1000000UL, (v % 1000000UL) / 100000UL);
}   // 7148089 -> "7,1" | 600000 -> "0,6" | 0 -> "0,0"
```

### Pattern 2: Colunas do pódio (posições fixas, rank → coluna)

```cpp
// rank 0 (1o) -> centro | rank 1 (2o) -> esquerda | rank 2 (3o) -> direita
constexpr int16_t COL_X[3] = {22, 102, 182};           // esq, centro, dir
constexpr int16_t BAR_H[3] = {88, 120, 64};            // altura por rank
constexpr uint32_t BAR_C[3] = {theme::HM_L3, theme::HM_L4, theme::HM_L2};
// no render: para cada rank r, provider = g_uwOrder[r], col = rank_to_col[r]
```

### Pattern 3: Regra de nome do projeto (Python)

```python
def _project_name(session: dict) -> str:
    directory = str(session.get("directory") or "")
    if directory.strip() and Path(directory).name.strip():
        return strip_accents(Path(directory).name)[:FULL_NAME_MAX]
    title = strip_accents(str(session.get("title") or ""))[:FULL_NAME_MAX]
    if title.strip():
        return title.strip()
    return strip_accents(str(session.get("slug") or "opencode"))[:FULL_NAME_MAX]
```

---

## Data Flow

```text
1. opencode_sessions._project_name -> campo "name"/"project" do payload (daemon)
2. ui_dashboard: grade (gap 2px) + inspeção (fundo padrão) + valores MM
3. render_usage_podio: rank -> coluna/altura/cor; header ícone+valor; nome abaixo
```

---

## Integration Points

Nenhum novo — mesmos coletores e payload.

---

## Testing Strategy

| Test Type | Scope | Files | Tools | Coverage Goal |
|-----------|-------|-------|-------|---------------|
| Unit | Regra de nome OpenCode (directory→basename; fallback title/slug) | `tests/test_opencode_sessions.py` | pytest | AT-010/011 |
| Contrato de fonte | `(EM MM)` no título; padrão de sufixo `.%luM` removido do widget | `tests/test_production_contracts.py` | pytest | AT-008 |
| Unit | Formato MM (`uw_tokens_str` equivalente) via revisão de código | — | hardware | AT-008/009 |
| E2E Hardware | Gap 2px, seta centrada, inspeção sem verde, pódio 2\|1\|3 com degrade | placa COM3 | manual + `/diag` | AT-001..007 |
