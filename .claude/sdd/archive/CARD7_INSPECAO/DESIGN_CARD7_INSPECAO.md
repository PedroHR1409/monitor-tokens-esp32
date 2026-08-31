# DESIGN: Card 7 — inspeção de dia (G4+G9) e seta para o pódio

> Technical design for implementing CARD7_INSPECAO

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | CARD7_INSPECAO |
| **Date** | 2026-08-29 |
| **Author** | design-agent |
| **DEFINE** | [DEFINE_CARD7_INSPECAO.md](./DEFINE_CARD7_INSPECAO.md) |
| **Status** | ✅ Shipped |
| **Design Confidence** | 0,95 (padrões já validados no próprio arquivo em iteração anterior) |

---

## Architecture Overview

```text
┌───────────────────────────── 304×222 ─────────────────────────┐
│ CONSUMO DE TOKENS                                    (título) │ 20px
├──────────────────────────────────────────────────┬────────────┤
│                                                  │            │
│   GRADE 7×6 ENCOSTADA (gap 0)                    │   ▸ / ◂    │ 28px
│   células ~39×31                                 │  faixa     │
│   repouso: paleta GitHub                         │  da seta   │
│   inspeção: não-tocados 75% escuros + BARRA      │            │
│   full-width do dia (2 linhas)                   │            │
│                                                  │            │
└──────────────────────────────────────────────────┴────────────┘
```

Estado global novo: `g_uwInspectDay` (int8; -1 = repouso). A seta é **bidirecional**:
`▸` no repouso (vai ao pódio), `◂` no pódio (volta ao heatmap) — mesma faixa, mesma
posição (a única via entre as visões, conforme o DEFINE).

---

## Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| Título (label) | `CONSUMO DE TOKENS` caps, topo, permanente | LVGL label + cache set_text_if |
| Faixa da seta (objeto clicável) | `▸`/`◂` — única via heatmap ↔ pódio | LVGL label clicável |
| Grade (30 células clicáveis) | Repouso: cor por nível; Inspeção: não-tocadas 75% escuro | lv_obj + remove_style_all |
| Barra de inspeção (objeto full-width) | Dia tocado: 2 linhas de info; toque nela sai | lv_obj + 2 labels |
| Hit-test map | Célula = inspecionar/sair; barra = sair; seta = pódio/voltar; vãos do card = sair da inspeção | Callbacks distintos |

---

## Key Decisions

### Decision 1: Seta bidirecional na mesma faixa

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted (decisão autônoma do design — o DEFINE não cobria a volta do pódio) |
| **Date** | 2026-08-29 |

**Context:** O DEFINE remove o long-press e faz da seta a única via para o pódio —
mas não dizia como VOLTAR do pódio.

**Choice:** A faixa exibe `▸` no repouso (→ pódio) e `◂` no pódio (→ repouso),
sempre na mesma posição.

**Rationale:** Affordance espacial estável (o dedo aprende o lugar); zero custo extra
de layout; espelha o padrão de navegação "voltar" universal.

**Alternatives Rejected:**
1. Toque no pódio volta (tap em qualquer lugar) — conflitaria com toque na barra do pódio (modal)
2. Duas faixas (ida/volta) — desperdiça largura da grade

**Consequences:**
- O ícone deve trocar com a visão (cache de texto já cobre)

---

### Decision 2: Escurecimento por recolor (25% de brilho), sem overlay

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-29 |

**Context:** "75% escurecido" sobre 29 células.

**Choice:** Na inspeção, células não-tocadas recebem `cor/4` por canal (set_color_if
normal); sem objeto overlay.

**Rationale:** Zero objetos novos, usa o cache de cor existente; overlay precisaria
de opacidade + z-order + redimensionamento a cada entrada/saída.

**Alternatives Rejected:**
1. Overlay semitransparente full-width — custo de z-order/gestão de estado
2. Trocar para paleta cinza fixa — perde a pista da cor original do dia

**Consequences:**
- Dias vazios escurecem para quase-preto (aceitável: já eram os mais escuros)

---

### Decision 3: Barra de inspeção = objeto dedicado full-width (não célula esticada)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-29 |

**Context:** "O quadrado deve ocupar a largura toda" — esticar a própria célula
alteraria a geometria do grid e exigiria restaurar depois.

**Choice:** Objeto barra (276×56, centralizado na grade) criado 1x e oculto; na
inspeção: fundo = cor do nível do dia, contorno branco 2px, 2 labels dentro;
clicável (toque nela sai).

**Rationale:** Aparecer/some sem tocar no grid; texto com espaço garantido
(mitiga R3); alvo de toque explícito para "toque nela sai".

**Alternatives Rejected:**
1. Esticar a célula tocada — mexe na geometria compartilhada, restauração frágil
2. Painel separado sem esticar — contraria o requisito (a) do operador

**Consequences:**
- Um objeto permanente a mais oculto (imperceptível em RAM)

---

### Decision 4: Mapa de hit-test explícito

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-29 |

**Context:** Iteração anterior provou que o hit-test do LVGL engole toques em
qualquer objeto clicável da cadeia.

**Choice:**

| Toque em | Repouso | Inspeção | Pódio |
|----------|---------|----------|-------|
| Célula da grade | abre inspeção do dia | **sai** da inspeção | — |
| Barra de inspeção | — | **sai** | — |
| Faixa da seta | → pódio | → pódio (sai junto) | → repouso |
| Card (vãos/título) | nada | **sai** | nada |
| Long-press | **nada** (removido) | nada | nada |

**Rationale:** Regra única — "qualquer toque que não seja a seta sai da inspeção";
navegação entre dias foi explicitamente descartada no DEFINE.

**Alternatives Rejected:**
1. Dimmed cell navega para outro dia — descartado no DEFINE (out of scope)

**Consequences:**
- `usage_cell_cb` e card callback precisam saber o estado de inspeção (g_uwInspectDay)

---

## File Manifest

| # | File | Action | Purpose | Agent | Dependencies |
|---|------|--------|---------|-------|--------------|
| 1 | `src/ui/ui_dashboard.cpp` | Modify | Título, faixa da seta bidirecional, grade encostada, barra de inspeção, mapa de hit-test, remoção do long-press e do label de dia | @build-agent | None |
| 2 | `tests/test_production_contracts.py` | Modify | Contratos de fonte: título presente; long-press do card AUSENTE; seta com handlers | @test-generator | 1 |
| 3 | `docs/SPEC.md`, `README.md` | Modify | Seção do widget atualizada (título, seta, inspeção) | @code-documenter | 1 |
| 4 | `pio run` + flash COM3 + validação | Verify | AT-001..011 na placa | @ci-cd-specialist | 1 |
| 5 | Revisão de diff + `check_secrets.py` | Verify | Gate de qualidade | @code-reviewer | 1-3 |

**Total Files:** 1 código + 1 teste + 2 docs + 2 verificações

---

## Agent Assignment Rationale

| Agent | Files Assigned | Why This Agent |
|-------|----------------|----------------|
| @build-agent | 1 | Iteração 100% LVGL no arquivo que o build anterior já instrumentou; padrões já estabelecidos |
| @test-generator | 2 | Contratos de fonte no estilo `test_production_contracts.py` existente |
| @code-documenter | 3 | SPEC/README no tom do projeto |
| @ci-cd-specialist | 4 | Flash e validação de hardware |
| @code-reviewer | 5 | Revisão final e guard-rail de segredos |

---

## Code Patterns

### Pattern 1: Faixa da seta bidirecional

```cpp
// label dentro da faixa; texto troca com a visao (cache de texto cobre)
const char *arrow = (g_uwView == 0) ? LV_SYMBOL_RIGHT : LV_SYMBOL_LEFT;
set_text_if(g_uwArrow, g_cUwArrow, sizeof(g_cUwArrow), arrow);
```

### Pattern 2: Escurecimento 75% por recolor

```cpp
uint32_t dim_color(uint32_t hex) {
    return RGB( ((hex>>16)&0xFF)/4, ((hex>>8)&0xFF)/4, (hex&0xFF)/4 );  // 25% brilho
}
// no update: inspeting ? dim_color(level_color) : level_color
```

### Pattern 3: Barra de inspeção (criada 1x, oculta; texto/nível por dia)

```cpp
// entrada: cor = nivel do dia; contorno branco 2px; 2 labels com set_text_if
// saida:  lv_obj_add_flag(g_uwInspectBar, LV_OBJ_FLAG_HIDDEN)
```

### Pattern 4: Contrato de fonte (sem hardware)

```python
ui = (ROOT / "src" / "ui" / "ui_dashboard.cpp").read_text(encoding="utf-8")
self.assertIn("CONSUMO DE TOKENS", ui)          # titulo
self.assertNotIn("LV_EVENT_LONG_PRESSED, nullptr);  # card", ui)  # long-press removido
```

---

## Data Flow

```text
1. Toque na célula (repouso) → g_uwInspectDay = d → update_usage_widget()
   │
   ▼
2. update: células não-tocadas recebem dim_color(nível); barra ganha cor do nível,
   contorno branco, 2 linhas de texto (dia extenso + % pico + semana) → visível
   │
   ▼
3. Toque na barra / célula / vão do card → g_uwInspectDay = -1 → repouso
   │
   ▼
4. Seta: repouso → pódio (◂ volta); g_uwInspectDay resetado ao trocar de visão
```

---

## Integration Points

Nenhum externo — iteração confinada ao `ui_dashboard.cpp` (dados já em `usageHistory`).

---

## Testing Strategy

| Test Type | Scope | Files | Tools | Coverage Goal |
|-----------|-------|-------|-------|---------------|
| Contrato de fonte | Título presente; long-press do card ausente; seta com handler | `tests/test_production_contracts.py` | pytest | AT-003 (lado código) |
| Unit (lógica extraída) | Nome de dia por extenso; total da semana parcial (AT-007); % do pico | funções puras em `ui_dashboard.cpp` validadas por revisão + ATs de hardware | pytest se extraídas para helper testável | AT-005..007 |
| E2E Hardware | AT-001..011 completos | placa via COM3 | manual + `/diag` (usage_view) | gate do build |

**Nota:** a lógica de texto (dia extenso, semana) vive em C no firmware — a
verificação primária é de hardware; os contratos de fonte travam regressões
estruturais (remoção do long-press, presença do título).
