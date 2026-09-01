# BUILD REPORT: ESTADOS_OPENCODE

| Attribute | Value |
|-----------|-------|
| **Data** | 2026-08-31 |
| **Executor** | build-agent (via OpenCode) |
| **DESIGN** | `DESIGN_ESTADOS_OPENCODE.md` |
| **Status** | ✅ Shipped |

## Implementado (commits c1741b2 → 6e70abc)

1. **`ask`**: tool `question` em `pending` OU `running` (o OpenCode registra a
   pergunta aberta nos dois estados — medidos ao vivo em 31/08 12:07 e 13:15)
2. **`perm` via log**: `perm_signals_from_log` — tail 512KB do `opencode.log`,
   mapeamento `run=`→`session.id` cronológico, última `action.action=ask` por
   sessão; frescor 10 min + invalidação por atividade posterior
3. **`work`/`free` pelo último part**: step-start/tool running/pending/reasoning =
   work; text/step-finish/tool completed = free (antes: work por até 30 min após
   o fim do turno)
4. **Contexto por modelo**: `context_window_for` — GLM → 1M (validado: 584k
   tokens = 58% na UI do OpenCode), deepseek → 128k, override por config, clamp 100
5. **Hermeticidade**: `run()` dos testes não lê o opencode.db/log reais
6. **Fallback de nome** nunca vazio (catálogo recebia `null`)

## Correções de percurso (cada uma com evidência)

1. Janela 128k errada para GLM (~1M real) — 100%+ em vez de 58% (f167434)
2. `pending` de tool = pipeline, não permissão — falso "perm" durante trabalho
   normal (50f473e)
3. `question` aberta fica em `pending` (e não `running`) — ask perdido (9635fe0)
4. Partes atualizadas in-place: o estado real é o de maior `time_updated` —
   pendings antigos sobreviviam (falso "perm" no 27816) (b62ee76)
5. `work/free` por idade — turnos encerrados ficavam "work" (6e70abc)

## Verificação

- 198→202 testes (4 novos no ciclo); compileall; check_secrets
- Validação ao vivo em 4 rodadas contra o OpenCode real do operador:
  ask detectado com pergunta aberta; work/free batendo com o ciclo do turno;
  contexto 58% (monitor-tokens-esp32) e 59% idênticos à UI

## Cobertura dos ATs

| AT | Verificação |
|----|-------------|
| 001..004 | `tests/test_opencode_sessions.py` (estado base pelo último part + question) |
| 005/006 | `perm_signals_from_log` (frescor/resolução) |
| 007/008 | janela por modelo + clamp |
| Gate final | Operador confirmou ("Funcionou") |

## Pendências

- [x] Commit (6e70abc)
- [x] Archive + SHIPPED (realizado neste ship)
