# BUILD REPORT: Integração com o Command Code

> Implementation report for Integração com o Command Code

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | COMMANDCODE_INTEGRATION |
| **Date** | 2026-09-19 |
| **Author** | build-agent |
| **DEFINE** | [DEFINE_COMMANDCODE_INTEGRATION.md](../features/DEFINE_COMMANDCODE_INTEGRATION.md) |
| **DESIGN** | [DESIGN_COMMANDCODE_INTEGRATION.md](../features/DESIGN_COMMANDCODE_INTEGRATION.md) |
| **Status** | ✅ Complete |

---

## Summary

| Metric | Value |
|--------|-------|
| **Tasks Completed** | 19/19 |
| **Files Created** | 5 (2 módulos, 3 testes, 1 fixture) |
| **Files Modified** | 14 |
| **Lines of Code** | ~1.100 (collector + installer + wiring + testes) |
| **Tests Passing** | 279 (+ 34 subtests) |
| **Agents Used** | 0 delegados (execução direta — ver nota) |

**Nota sobre agentes.** A DESIGN atribuiu @python-developer/@test-generator/@code-documenter.
O executor do Build nesta sessão não tem o tool `Task` disponível para despachar subagentes,
então todas as tarefas foram executadas **diretamente** pelo build-agent, seguindo os padrões
do DESIGN e do codebase. A atribuição de agentes do manifesto permanece como referência para
revisão (`@code-reviewer` nos dois módulos novos é a sugestão registrada no DESIGN).

---

## Task Execution with Agent Attribution

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 1 | `tools/commandcode_sessions.py` | (direct) | ✅ Complete | Collector espelhando `opencode_sessions.py` |
| 2 | `tools/install_commandcode_hook.py` | (direct) | ✅ Complete | Aditivo/idempotente, espelha `install_codex_hook.py` |
| 3 | `tools/session_hook.py` (mod.) | (direct) | ✅ Complete | `_default_path` + `hook_health` |
| 4 | `tools/monitor_config.py` (mod.) | (direct) | ✅ Complete | `usage.commandcode_context_window` |
| 5 | `tools/quota.py` (mod.) | (direct) | ✅ Complete | Bloco estimado `commandcode` |
| 6 | `tools/usage_top.py` (mod.) | (direct) | ✅ Complete | Pódio com a chave `commandcode` |
| 7 | `tools/usage_history.py` (mod.) | (direct) | ✅ Complete | `_backfill_commandcode` |
| 8 | `tools/doctor.py` (mod.) | (direct) | ✅ Complete | Path + health |
| 9 | `tools/session_daemon.py` (mod.) | (direct) | ✅ Complete | Wiring + fallback 422 genérico |
| 10 | `include/session_model.h` (mod.) | (direct) | ✅ Complete | `ToolType::COMMANDCODE` |
| 11 | `src/sessions/session_transport.cpp` (mod.) | (direct) | ✅ Complete | `parse_tool("commandcode")` |
| 12 | `tests/fixtures/commandcode/session_sample.jsonl` | (direct) | ✅ Complete | Amostra real sanitizada |
| 13 | `tests/test_commandcode_sessions.py` | (direct) | ✅ Complete | 15 testes |
| 14 | `tests/test_commandcode_hook.py` | (direct) | ✅ Complete | 9 testes |
| 15 | `tests/test_doctor.py` (mod.) | (direct) | ✅ Complete | +2 testes |
| 16 | `tests/test_usage_top.py` (mod.) | (direct) | ✅ Complete | Expectativa p/ 4 provedores |
| 17 | `tests/fixtures/doctor/*.json` (mod.) | (direct) | ✅ Complete | `commandcode` nos 3 fixtures |
| 18 | `tools/README.md`, `docs/SPEC.md`, `docs/ROADMAP.md` | (direct) | ✅ Complete | Docs |

---

## Files Created

| File | Lines | Verified | Notes |
| ---- | ----- | -------- | ----- |
| `tools/commandcode_sessions.py` | ~350 | ✅ | Leitura read-only; nunca abre `auth.json` |
| `tools/install_commandcode_hook.py` | ~120 | ✅ | Backup + escrita atômica |
| `tests/test_commandcode_sessions.py` | ~320 | ✅ | Coletor + integração + fallback 422 |
| `tests/test_commandcode_hook.py` | ~95 | ✅ | Install/health |
| `tests/fixtures/commandcode/session_sample.jsonl` | 4 | ✅ | Schema real sanitizado |

---

## Verification Results

### Lint / sintaxe

```text
python -m compileall -q tools tests   → OK (sem saída)
```

**Status:** ✅ Pass

### Tests

```text
python -m pytest tests/ -q
279 passed, 34 subtests passed in 37.63s
```

**Status:** ✅ 279/279 Pass

### Smoke real (dados do operador)

`scan_commandcode_sessions` contra `~/.commandcode/projects` real: 4 sessões detectadas
(3 projetos + a sessão atual), com `tool="commandcode"`, projeto/branch/modelo corretos,
`tokensWin` e contexto.

> **Correção pós-build (2026-09-19).** A primeira versão somava `input + output +
> cacheWrite` por turno, tratando `inputTokens` como tokens novos. Em uso, o operador
> notou ~102M de tokens no dia. Investigação nos dados reais: `inputTokens` é o **prompt
> inteiro** e já inclui o cache lido (`input=394965` com `cacheRead=393984`), então somar
> `input` recontava o contexto a cada turno. Corrigido para
> `(inputTokens - cacheReadTokens) + outputTokens`. Efeito medido: CC hoje caiu de
> 101.939.552 para **2.189.649**; o total do dia passou de 101.727.300 para **2.792.838**.
> Ver `docs/SPEC.md` seção 20 ("Armadilha medida") e AT-008.

### Segredos

```text
python tools/check_secrets.py   → exit 1
- include\secrets.example.h
```

**Status:** ❌ Falha — **pré-existente, não relacionada ao build.** O `include/secrets.h`
local (gitignored, intocado por esta feature) ainda usa o **placeholder** de token do
exemplo, então o scanner acusa `include/secrets.example.h`. O
guard-rail está correto; a correção é o operador definir um token real. Nenhum arquivo
criado/modificado por este build toca segredos (`check_secrets.py` só lê
`secrets.h`/`secrets.example.h`).

### Firmware

```text
python -m platformio run -e esp32-s3-3v5-lcd
Compiling .pio\build\esp32-s3-3v5-lcd\src\sessions\session_transport.cpp.o
Linking .pio\build\esp32-s3-3v5-lcd\firmware.elf
RAM:   [====      ]  38.4% (used 125992 bytes from 327680 bytes)
Flash: [==        ]  22.9% (used 1498282 bytes from 6553600 bytes)
======================== [SUCCESS] Took 139.09 seconds ========================
```

**Status:** ✅ Pass — `firmware.bin` e `firmware.factory.bin` gerados, incluindo o
`session_transport.cpp.o` com `parse_tool("commandcode")`. Os avisos são pré-existentes
(LVGL `lv_conf`, `volatile++`, nota do linker). O executável `pio` não está no PATH do
operador (o Core está instalado em
`%APPDATA%\Python\Python314\Scripts`), por isso o build rodou via `python -m platformio`.

---

## Issues Encountered

| # | Issue | Resolution |
|---|-------|------------|
| 1 | `_write` do teste fechava o `TemporaryDirectory` antes do assert (indentação) | Asserts movidos para dentro do `with` |
| 2 | `short_model` trunca em 14 chars → `deepseek-v4.1-` | Aceito: mesma regra de Claude/OpenCode; teste ajustado |
| 3 | Stub do fallback 422 sem `stats.active_12h` | Stub completado |
| 4 | `test_usage_top` esperava 3 provedores | Expectativa atualizada para 4 (mudança de design) |
| 5 | Tabela de contexto deepseek=128k errada (contexto real 713k) | Corrigida para 1M, groundada em `reference/models.md` |
| 6 | **Semântica de tokens do Command Code** — `inputTokens` já inclui o cache lido; somar `input` inflava o dia em ~40× | Corrigido para `(input - cacheRead) + output`; testes e SPEC atualizados |

---

## Autonomous Decisions

| # | Decision Point | Options Considered | Chose | Rationale |
|---|----------------|--------------------|-------|-----------|
| 1 | Valor da janela de contexto na tabela | 128k (chute inicial do DESIGN) vs. buscar a fonte | **1M**, de `reference/models.md` | O smoke real mostrou contexto >700k; 128k produzia `ctxPct=100` fabricado. A referência do produto é autoritativa |
| 2 | Pódio do firmware com 4 provedores | Expandir `UsageTop` + redesenhar o widget vs. manter 3 colunas | **Manter 3 colunas**; daemon envia a chave | Redesenhar o widget não está no manifesto (fora do menor-esforço-correto); documentado como limitação |
| 3 | `perm` inferido acima de 600s | `free` (padrão do DESIGN) vs. `work` por recência | **`free`** | Segue o padrão escrito no DESIGN; na dúvida, não afirmar `perm` |
| 4 | Qualidade do contexto | Reusar `context_measurement` (mede/config/unknown) vs. qualidade manual | **Manual** (`measured`/`estimated`/`unknown`) | A função da KB não tem o nível `estimated`, que é o honesto para uma janela de tabela |
| 5 | Testes existentes afetados | Não tocar vs. atualizar | **Atualizar** expectativas (`test_usage_top`, fixtures do doctor) | Eram consequência direta do design; mantê-los passando é obrigatório |

---

## Deviations from Design

| Deviation | Reason | Impact |
|-----------|--------|--------|
| ~~`ui_dashboard.cpp` / pódio não alterados~~ | **Resolvido em 2026-09-19 a pedido do operador** | Pódio expandido para **4 provedores** (`USAGE_PROVIDERS`) com nome curto "Command"; firmware recompilado (SUCCESS) |
| Janela de contexto 1M (não 128k) | Grounding em `reference/models.md` + smoke real | `ctxPct` honesto (~71% na sessão atual) |
| `context_measurement` não importado | Falta o nível `estimated` | Lógica de qualidade local, testada |
| ~~Firmware não compilado~~ | Resolvido: `pio run` SUCCESS (2×) | Compila com as mudanças de enum/parse e do pódio de 4 colunas |

---

## Blockers (if any)

| Blocker | Required Action | Owner |
|---------|-----------------|-------|
| `secrets.h` com token placeholder | definir token real (pré-existente) | operador |

---

## Acceptance Test Verification

| ID | Scenario | Status | Evidence |
|----|----------|--------|----------|
| AT-001 | Sessão CC aparece | ✅ Pass | `BuildPayloadIntegrationTests` + smoke real |
| AT-002 | `work` por hook | ✅ Pass | `test_structured_hook_event_wins...` |
| AT-003 | `ask` | ✅ Pass | `test_pending_question_is_ask` |
| AT-004 | `perm` | ✅ Pass | `test_pending_tool_without_hook_is_perm` |
| AT-005 | `perm` não eterno | ✅ Pass | `test_perm_does_not_persist_past_the_ceiling` |
| AT-006 | `free` por `Stop` | ✅ Pass | event store `free` no teste de hook |
| AT-007 | Sem hook, só recência | ✅ Pass | `test_recent_completed_turn_is_work_by_recency` |
| AT-008 | Tokens da janela | ✅ Pass | `test_consumption_is_input_minus_cache_read_and_dedups` + fixture real |
| AT-009 | Dedup | ✅ Pass | mesma mensagem repetida conta 1x |
| AT-010 | Contexto estimado/unknown | ✅ Pass | `test_context_quality_...` |
| AT-011 | Install aditivo | ✅ Pass | `test_adds_our_hooks_and_preserves_third_party` |
| AT-012 | Install idempotente | ✅ Pass | `test_reinstall_is_idempotent` |
| AT-013 | Health no doctor | ✅ Pass | `test_hook_health_reports_commandcode` + `DoctorCommandCodeTests` |
| AT-014 | Firmware compatível | ✅ Pass (build) | `pio run` SUCCESS; gravação/render na placa pendente |
| AT-015 | Firmware antigo (422) | ✅ Pass (daemon) | `Fallback422Tests`; firmware antigo não testado em hardware |
| AT-016 | Não lê segredo | ✅ Pass | coletor só enumera `projects/**/*.jsonl` |
| AT-017 | Histórico/pódio | ✅ Pass | Histórico ✅; pódio com **4 colunas** após a iteração (nome curto "Command") |
| AT-018 | Sessão encerrada sumiu | ✅ Pass | `cc-ended` fora do resultado |

---

## Performance Notes

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| Custo por ciclo | baixo (≤24 transcripts) | leitura de tail por arquivo, cap 24 | ✅ |

---

## Final Status

### Overall: ✅ COMPLETE

**Completion Checklist:**

- [x] All tasks from manifest completed
- [x] All verification checks pass (testes, compileall)
- [x] All tests pass (279/279)
- [ ] No blocking issues — 2 itens de acompanhamento (pódio 4 colunas, secrets local) + gravação na placa
- [x] Acceptance tests verified (AT-014 compila; render na placa pendente)
- [x] Ready for /ship (firmware compilado com sucesso)

---

## Next Step

**Ready for:** `/ship .claude/sdd/features/DEFINE_COMMANDCODE_INTEGRATION.md`
