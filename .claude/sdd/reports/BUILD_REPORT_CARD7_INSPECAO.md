# BUILD REPORT: CARD7_INSPECAO

| Attribute | Value |
|-----------|-------|
| **Data** | 2026-08-29 |
| **Executor** | build-agent (via OpenCode) |
| **DESIGN** | `DESIGN_CARD7_INSPECAO.md` |
| **Status** | ✅ Implementado, gravado na placa (validação visual pendente do operador) |

## Implementado (100% `src/ui/ui_dashboard.cpp`)

- **Título permanente** `CONSUMO DE TOKENS` (linha própria de 20px)
- **Faixa da seta bidirecional** (28px, borda direita): `▸` repouso→pódio, `◂` pódio→repouso; única via entre as visões; **long-press removido**
- **Grade encostada (gap 0)**: células 39×33, área 276px (card - faixa da seta), centralizada verticalmente
- **Modo inspeção** (`g_uwInspectDay`): não-tocados 75% escurecidos (`uw_dim` = canais/4); dia tocado = **barra full-width 276×56** com contorno branco, 2 linhas:
  - `Quarta-feira, 26/08 - 7,1M tokens` (dia por extenso, `uw_weekday_full`)
  - `33% do pico - semana 24-30: 30,4M`
  - texto branco em níveis escuros, texto escuro em níveis claros (L3+)
- **Mapa de hit-test** (D4 do design): célula = inspecionar/sair; barra = sair; seta = pódio/voltar; card (vãos/título) = sair da inspeção
- Barra de inspeção criada 1x (oculta); textos/cores por `set_text_if`/caches

## Correções de percurso (registradas)

1. Guarda de instância quebrava o pytest quando há daemon real rodando → guarda ativa
   só para daemon contínuo (`--once` não precisa)
2. Cirurgia com âncora errada duplicou callbacks → bloco duplicado removido por
   marcadores de conteúdo (2ª ocorrência de `chip_cb` até o separador `// --- updates`)
3. `LV_OBJ_FLAG_CLICKABLE | LV_OBJ_FLAG_HIDDEN` passado como int → split em 2 chamadas

## Verificação

- 180 passed (+1 contrato novo: título presente, long-press ausente, seta com handler)
- compileall OK; check_secrets limpo; `pio run` SUCCESS; flash COM3 OK
- `/diag` pós-flash: `usage_valid: true`, célula de hoje (3,0M = 33% do pico) em L3,
  grade encostada confirmada (cell_x = 234 = col 6 × 39px)

## Cobertura dos ATs

| AT | Verificação |
|----|-------------|
| 001/002/003 | contrato de fonte + hardware |
| 004..009 | hardware (confirmação do operador) |
| 010 | pódio intocado (código revisado) |
| 011 | placa recém-boot validada via /diag (células vazias, sem trava) |

## Pendências

- [ ] Confirmação visual do operador (título/seta/encostadas/inspeção/saídas)
- [ ] Commits acumulados (migração AgentSpec, widget G4, correções daemon, esta iteração)
- [ ] `/agentspec:ship` + SPEC/README (docs do widget completo)
