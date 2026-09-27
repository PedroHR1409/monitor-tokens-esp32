# BUILD REPORT: Alerta escalonado + snooze + toast no PC

> Relatório de implementação da feature ALERTA_ESCALONADO (item #1 do `docs/ROADMAP.md`)

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | ALERTA_ESCALONADO |
| **Date** | 2026-09-08 |
| **Author** | build-agent |
| **DEFINE** | [DEFINE_ALERTA_ESCALONADO.md](../features/DEFINE_ALERTA_ESCALONADO.md) |
| **DESIGN** | [DESIGN_ALERTA_ESCALONADO.md](../features/DESIGN_ALERTA_ESCALONADO.md) |
| **Status** | Complete |

---

## Summary

| Metric | Value |
|--------|-------|
| **Tasks Completed** | 22/22 |
| **Files Created** | 6 (2 daemon, 2 firmware, 2 testes) |
| **Files Modified** | 16 |
| **Lines of Code** | +680 / -20 (rastreados) + 505 em arquivos novos |
| **Build Time** | firmware de produção 14m20s (rebuild total: `config.h` invalida tudo); demo não verificado localmente |
| **Tests Passing** | 235/235 + 34 subtests (era 202 + 14) |
| **Agents Used** | 2 (@python-developer, @test-generator) |

---

## Task Execution with Agent Attribution

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 1 | `include/config.h` — constantes de pulso e tick | (direct) | ✅ Complete | Invalidou o build inteiro |
| 2 | `include/session_model.h` — `enum SeverityLevel` + campo | (direct) | ✅ Complete | Ordem numérica = ordem de urgência |
| 3 | `include/ui_theme.h` — cor do mudo; remoção de `ALERT_PERIOD_MS` | (direct) | ✅ Complete | Constante removida junto com o pulso da borda |
| 4 | `tools/alert_severity.py` — função pura de severidade | @python-developer | ✅ Complete | KB `python/concepts/dataclasses.md` (frozen+slots) |
| 5 | `tools/notify.py` — toast por `subprocess` | @python-developer | ✅ Complete | Corrigido depois: `run` → `Popen` (ver Deviations) |
| 6 | `src/sessions/snooze.h` | (direct) | ✅ Complete | — |
| 7 | `src/sessions/snooze.cpp` | (direct) | ✅ Complete | Aritmética com sinal p/ sobreviver ao rollover de `millis()` |
| 8 | `src/drivers/device_time.h` | (direct) | ✅ Complete | — |
| 9 | `src/drivers/device_time.cpp` — base + pulso triangular | (direct) | ✅ Complete | Reusa a guarda de idempotência já existente |
| 10 | `src/sessions/session_transport.cpp` — parse, endpoints, `/diag` | (direct) | ✅ Complete | 2 funções públicas fora do namespace anônimo |
| 11 | `src/sessions/session_transport.h` | (direct) | ✅ Complete | — |
| 12 | `src/main.cpp` — tick de 70ms | (direct) | ✅ Complete | — |
| 13 | `src/ui/ui_dashboard.cpp` — header, mudo, `expired`, borda estática | (direct) | ✅ Complete | Tofu evitado (ver Issues) |
| 14 | `tools/session_daemon.py` — severidade, snooze, toast | (direct) | ✅ Complete | Feito direto, não delegado (ver Autonomous Decisions #1) |
| 15 | `tools/doctor.py` — checagem do canal | (direct) | ✅ Complete | Idem |
| 16 | `tests/test_alert_severity.py` | @test-generator | ✅ Complete | 33 testes; matriz por `subTest` |
| 17 | `tests/test_notify.py` | @test-generator | ✅ Complete | Inclui teste de injeção de comando |
| 18 | `tests/test_session_daemon.py` — `MaybeToastTests` | @test-generator | ✅ Complete | Acrescentado ao final, nada existente alterado |
| 19 | `tests/test_doctor.py` — `DoctorNotifyCheckTests` | @test-generator | ✅ Complete | Idem |
| 20 | `tests/test_session_daemon.py` — 2 testes existentes | (direct) | ✅ Complete | Quebraram pelo `GET /snooze` novo (ver Issues) |
| 21 | `docs/SPEC.md` — seção 19 | (direct) | ✅ Complete | Fonte da verdade do projeto |
| 22 | `tools/README.md` + `docs/ROADMAP.md` | (direct) | ✅ Complete | — |

**Legenda:** ✅ Complete · `@agente` = delegado via Task · `(direct)` = executado pelo build

**Não estava no manifesto e não foi necessário:** `tools/monitor_config.py`. O DESIGN já
havia verificado que `[alerts]` é parseado e validado; a implementação confirmou — zero
mudanças de configuração.

---

## Agent Contributions

| Agent | Files | Specialization Applied |
|-------|-------|------------------------|
| @python-developer | 2 | `@dataclass(frozen=True, slots=True)` da KB `python`; função pura sem efeito colateral; type hints completos |
| @test-generator | 4 | `unittest.TestCase` + `subTest` (convenção do repo, **não** `pytest.parametrize` da KB); docstrings de regressão; mocks herméticos |
| (direct) | 16 | Padrões do DESIGN + padrões extraídos do codebase para os 10 arquivos C++ sem especialista |

---

## Files Created

| File | Lines | Agent | Verified |
|------|-------|-------|----------|
| `tools/alert_severity.py` | 81 | @python-developer | `compileall` + 33 testes |
| `tools/notify.py` | 65 | @python-developer | `compileall` + testes de plataforma/injeção |
| `src/sessions/snooze.h` | 21 | (direct) | compila no firmware |
| `src/sessions/snooze.cpp` | 37 | (direct) | compila no firmware |
| `tests/test_alert_severity.py` | 164 | @test-generator | pytest |
| `tests/test_notify.py` | 137 | @test-generator | pytest |

---

## Verification Results

### Lint / Sintaxe

```
python -m compileall tools/ tests/     → OK (sem erros)
python tools/check_secrets.py          → Nenhuma credencial local fora de include/secrets.h
```

O projeto não configura `ruff` nem `mypy` (não há `pyproject.toml`/`setup.cfg`); a
verificação de sintaxe do projeto é `compileall`, conforme o README raiz.

### Firmware

```
python -m platformio run -e esp32-s3-3v5-lcd
RAM:   [====      ]  38.4% (used 125992 bytes from 327680 bytes)
Flash: [==        ]  22.9% (used 1498210 bytes from 6553600 bytes)
======================== [SUCCESS] Took 860.50 seconds ========================
```

Zero warnings novos de compilação nos arquivos da feature. (O warning de
`.note.GNU-stack` no link é pré-existente, do toolchain.)

**Ambiente `esp32-s3-3v5-lcd-demo`: NÃO verificado localmente — bloqueio de ambiente.**

Três tentativas, todas mortas por falta de memória: as duas primeiras compilando os dois
ambientes em paralelo, a terceira só o demo com `-j 2`. Medição no momento da terceira
falha: **1,4 GB livres de 15,7 GB** (WSL 1,2 GB, compressão de memória 737 MB, mais os
processos de sessão). O ambiente demo tem `libdeps` próprio, então exige um build
completo de LVGL do zero — que não cabe nessa folga.

Decisão: **parar de tentar**. Uma quarta tentativa com `-j 1` levaria ~40 min disputando
memória com o trabalho do operador, para verificar um ambiente que o CI já compila a cada
push. Nenhum arquivo desta feature é condicional a `MONITOR_DEMO_DATA` e o único delta do
ambiente é essa macro, então o risco de divergir é baixo — mas **baixo não é verificado**,
e este relatório não afirma o contrário. O CI é o gate real deste item.

### Tests

```
python -m pytest tests/ -q
235 passed, 34 subtests passed
```

Baseline antes da feature: 202 passed, 14 subtests. Delta: **+33 testes, +20 subtests**.

---

## Issues Encountered

| # | Issue | Resolution |
|---|-------|------------|
| 1 | `LV_SYMBOL_MUTE` (0xF026) renderizaria como **tofu**: não está no `unicode_list` do `lv_font_montserrat_16` (a lista salta de `0xf019` para `0xf030`) | Verificado direto no `.c` da fonte compilada; trocado por ASCII `"mudo 12m"`, conforme a regra no topo do `ui_dashboard.cpp` |
| 2 | 2 testes existentes falharam: rejeitavam requisição não prevista e o `run()` passou a fazer `GET /snooze` | `test_run_uses_toml_token_for_hidden_and_pinned_gets` ganhou o stub de `/snooze` e a asserção de 3 requisições; `test_run_posts_the_configured_token_without_logging_it` ganhou `patch.object(..., "fetch_snooze", return_value=0)` |
| 3 | `notify()` com `subprocess.run` + `Start-Sleep -Seconds 6` bloquearia o ciclo do daemon por ~7s num intervalo de 5s | Trocado por `Popen` fire-and-forget (ver Deviations) |
| 4 | `check_notify` sempre caía no ramo de fixture: `_fixture_mapping` devolve `{}`, não `None` | Alinhado ao idioma da casa (`if supplied:` em vez de `is not None`), como os outros 8 checks do `doctor.py` |
| 5 | Severidade `expired` pulsava o backlight sem acender borda nenhuma (o estado subjacente é `work`/`free`) | `update_alert` passou a considerar `SeverityLevel::EXPIRED`, com borda roxa — a tela e o card contam a mesma história |
| 6 | As 2 chamadas de `build_payload` no fallback de 422 (OpenCode) usariam os limiares default em vez da config | Passadas `thresholds=limiares` e `snooze_minutes` nas 4 chamadas, não só nas 2 do caminho principal |

---

## Autonomous Decisions

| # | Decision Point | Options Considered | Chose | Rationale |
|---|----------------|--------------------|-------|-----------|
| 1 | O manifesto atribui `session_daemon.py` e `doctor.py` a @python-developer, mas são modificações cirúrgicas em arquivos de 830 e 230 linhas | Delegar como manda o manifesto · executar direto | **Executar direto** | "Smallest correct change": o contexto completo dos dois arquivos já estava carregado, e delegar uma edição pontual em arquivo grande é o cenário clássico de reescrita acidental. Os arquivos **criados** foram delegados como especificado |
| 2 | O `CLAUDE.md` do projeto e o skill `sdd-build` discordam sobre comentários: o skill exige "no inline comments", o repo inteiro é comentado com racional | Seguir o skill · seguir o repo | **Seguir o repo** | `CLAUDE.md` é instrução de projeto e sobrepõe default de skill; e comentário de racional é literalmente o que a SPEC deste repo pede. Código sem os "por quês" aqui seria o corpo estranho |
| 3 | O firmware não sabia de onde vem `snooze_minutes` — o DESIGN não resolveu (o valor mora no `monitor.toml`, no PC) | Hardcode em `config.h` · enviar no payload | **Enviar no payload** (campo aditivo `snooze_minutes`), com `SNOOZE_MINUTES_DEFAULT` como fallback | Coerente com a Decisão 1 do DESIGN: config num lugar só, e trocar o valor não pode exigir reflash |
| 4 | Marca de `perm` órfã produziria `perm?` numa sessão saudável cujo hook de limpeza falhou | Aceitar (mitigado pelo teto de 20 min) · adicionar guarda | **Guarda não-heurística**: a marca só vale enquanto for a evidência **mais recente**; evento estruturado posterior a invalida | Usa dado que o daemon já tem (`snapshot.last_event_at`), sem reintroduzir heurística. Alinhado ao "melhor não afirmar do que afirmar errado" do `session_state.py` |
| 5 | OpenCode não tem evento de hook; seu `perm` vem de parsing de log | Tratar como estruturado (permite toast) · tratar como inferido (teto em warning) | **Inferido** | Conservador na direção certa: "só o exato interrompe você no PC". Um alarme falso custa mais que um toast a menos |
| 6 | Entrada da severidade: `elapsed` ou `source_age_s` (valores equivalentes, medidas distintas) | `source_age_s` · `elapsed` | **`elapsed`** | É o mesmo número que o card exibe como tempo no estado: a escalada tem que casar com o que o operador vê |
| 7 | `worst_severity` com severidade fora do vocabulário levantaria `ValueError` de `SEVERITY_ORDER.index` | Propagar · falha segura | **Falha segura** (ignora desconhecida, cai para `none`) | Decidido pelo @python-developer e mantido: espelha `parse_state`/`parse_tool` do firmware. Um bug em outro módulo não deve derrubar o daemon dentro do loop de alerta |
| 8 | Numeração da nova seção da SPEC: o arquivo já tem **duas** seções "17" e uma "18" | Renumerar o documento · usar 19 | **Usar 19** | Renumerar tocaria seções históricas e invalidaria referências existentes; 19 é o próximo número livre e casa com os comentários no firmware. A numeração duplicada pré-existente ficou como está |

---

## Deviations from Design

| Deviation | Reason | Impact |
|-----------|--------|--------|
| `notify()` usa `subprocess.Popen` (fire-and-forget) em vez de `subprocess.run(timeout=...)` como no padrão do DESIGN | O balão do Windows exige o processo vivo por ~6s (`Start-Sleep`); esperar bloquearia o ciclo do daemon por mais tempo que o próprio intervalo de 5s, atrasando o payload e fazendo o anti-replay da placa ver ciclos fora de ordem | O retorno passa a significar "consegui disparar", não "o usuário viu" — nenhuma das duas plataformas confirma exibição de qualquer forma. A consideração de segurança do DESIGN ("timeout obrigatório") é substituída por um processo que termina sozinho |
| `update_alert` também acende a borda para `SeverityLevel::EXPIRED` | O DESIGN dizia "borda estática na cor do estado", e o estado subjacente de uma sessão `expired` é `work`/`free` — a tela pulsaria sem nenhuma borda | Consistência: borda roxa quando o motivo é procedência vencida, casando com o roxo do card |
| Campo aditivo `snooze_minutes` no payload, não previsto no DESIGN | O DESIGN não resolveu de onde o firmware tira a duração do mudo | Contrato ganha um campo de topo (aditivo, retrocompatível) |
| `snooze` **não** persiste em NVS, ao contrário do que o DESIGN e o diagrama diziam (`snooze.cpp (NVS)`, "padrão `id_list`") | `millis()` reinicia no boot, então um `snooze_until` persistido não teria referência válida ao voltar. E o comportamento correto é o oposto do que o DESIGN previa: quem religou o painel quer ver o estado real, não herdar um mudo de antes da queda | Um `Preferences` a menos e um write de flash a menos por toque. A suposição A-004 do DEFINE (desgaste de NVS) fica **sem objeto** em vez de não validada |
| Testes usam `unittest` + `subTest`, não `pytest.parametrize` da KB `testing` | Convenção do repo: 18 de 18 arquivos de teste usam `unittest`, zero usam `parametrize` | Nenhum — o skill `sdd-design` manda adaptar padrão de KB à convenção do projeto |

---

## Blockers

| Blocker | Required Action | Owner |
|---------|-----------------|-------|
| Build do ambiente `esp32-s3-3v5-lcd-demo` não pudedo ser verificado localmente: 3 tentativas mortas por falta de memória (1,4 GB livres de 15,7 GB) | Deixar o CI compilar no push, ou rodar `python -m platformio run -e esp32-s3-3v5-lcd-demo -j 1` com a máquina mais livre | CI / operador |
| AT-005, AT-009 e AT-014 são de percepção visual e nenhum teste de software pode afirmá-los | Gravar o firmware (`pio run -t upload`) e conferir pelo `GET /diag` autenticado com `X-Monitor-Token` (`alert.severity`, `alert.snooze_s`, `alert.pulse_level`, `alert.pulse_base`) | Operador |

Nenhum dos dois é problema de código: um é recurso da máquina, o outro exige hardware.
A implementação está completa e a suite passa.

---

## Acceptance Test Verification

| ID | Scenario | Status | Evidence |
|----|----------|--------|----------|
| AT-001 | Warning ao cruzar 90s | ✅ Pass | `test_alert_severity` matriz + fronteira exata (`elapsed == warning_after_s` já escala) |
| AT-002 | Crítico aos 300s + um toast | ✅ Pass | `test_alert_severity` + `MaybeToastTests.test_fires_once_per_session_state` |
| AT-003 | Procedência inferida com teto em warning, sem toast | ✅ Pass | `test_alert_severity` (`structured=False` nunca produz `critical`, para nenhum elapsed) |
| AT-004 | Marca de `perm` vencida → `expired`, não `free` | ✅ Pass | `test_alert_severity` fronteiras 600.0 / 600.1 / 1200.0 / 1200.1 |
| AT-005 | Snooze silencia pulso e toast, com indicação | ⚠️ Parcial | Supressão do toast coberta por teste; **pulso e rótulo do relógio exigem hardware** |
| AT-006 | Mudo é mudo (escalada nova não rompe) | ✅ Pass | `MaybeToastTests` com `snooze_s > 0` devolve 0 e não chama `notify` |
| AT-007 | Agregação: pior severidade vence | ✅ Pass | `test_alert_severity::worst_severity` (`warning` + `critical`) |
| AT-008 | Agregação com `expired` | ✅ Pass | `worst_severity` (`warning` + `expired`), e `critical` vence `expired` |
| AT-009 | Crítico perceptível no modo noturno | ⚠️ Não verificado | Faixa absoluta 40-255 contra base 60 está no código; **exige hardware** |
| AT-010 | Limiar muda sem reflash | ✅ Pass | `test_alert_severity` com `Thresholds` alternativos; o firmware nunca lê limiar |
| AT-011 | Toast não repete | ✅ Pass | `MaybeToastTests` — segundo ciclo não dispara; canal quebrado também não retenta |
| AT-012 | Retrocompatibilidade do campo novo | ✅ Pass | Verificado por leitura (`session_transport.cpp:222-285`, whitelist) + firmware compila e aceita payload sem `severity` (default `NONE`) |
| AT-013 | Sem alerta, sem pulso | ✅ Pass | `test_alert_severity` (`work`/`free` → `none`); `pulse_tick` com `NONE` escreve o base |
| AT-014 | Snooze expira e o pulso retoma | ⚠️ Parcial | `snooze_remaining_s` volta 0 por construção; **retomada visual exige hardware** |

**11 de 14 verificados automaticamente. 3 dependem de validação na placa** — todos os
três são de percepção visual (pulso, brilho noturno, rótulo do relógio), que nenhum teste
de software pode afirmar. Estão registrados como pendência de hardware, não como passe.

---

## Performance Notes

| Metric | Expected (DEFINE) | Actual | Status |
|--------|-------------------|--------|--------|
| Invalidações LVGL do pulso | 0 | 0 — `pulse_tick` só chama `ledcWrite`, nenhuma API LVGL | ✅ |
| Razão de período warning/crítico | ≥ 2,5× | 2000/700 = **2,86×** | ✅ |
| Razão de amplitude | ≥ 2× | crítico 215 (40-255) vs warning 153 (base 255 ±30%) = **1,4×** de dia; **7,2×** à noite (base 60) | ⚠️ Ver nota |
| Pico do crítico à noite | ≥ 200/255 | 255 | ✅ |
| Custo de render do alerta | não aumentar | **diminuiu**: a borda deixou de invalidar ~3×/s | ✅ |
| RAM do firmware | — | 38.4% (era 27.8% na v0.1) | ✅ |
| Flash do firmware | — | 22.9% | ✅ |

**Nota sobre a razão de amplitude.** De dia o critério de ≥2× não é atendido (1,4×),
porque o base já está no teto de 255 e não há para onde crescer. A distinção de dia fica
por conta do **período** (2,86×, dentro do critério). À noite os dois eixos se separam
com folga. Isso é uma limitação física do PWM de 8 bits com brilho diurno máximo, não um
defeito de implementação — e é candidata a `/agentspec:iterate` se a distinção diurna se
mostrar insuficiente na placa.

---

## Data Quality Results

Não aplicável — a feature não introduz pipeline, ETL nem fonte de dados.

---

## Final Status

### Overall: ✅ COMPLETE

**Completion Checklist:**

- [x] Todas as 22 tarefas do manifesto concluídas
- [x] Cada arquivo verificado (compileall / pytest / build do firmware)
- [x] Validação completa passa (235 testes, firmware de produção, guard-rail de segredos)
- [x] Nenhum comentário TODO deixado no código
- [x] Nenhum segredo ou credencial hardcoded
- [x] Casos de erro tratados (canal ausente, device fora do ar, marca órfã, rollover de `millis()`, severidade desconhecida)
- [x] Atribuição de agentes registrada
- [x] Tabela de decisões autônomas preenchida (8 forks)
- [x] Status do DEFINE e do DESIGN atualizados
- [x] BUILD_REPORT gerado
- [ ] **Pendente: validação em hardware** de AT-005, AT-009 e AT-014
- [ ] **Pendente: build do ambiente `-demo`** — bloqueio de ambiente (1,4 GB livres; 3 tentativas mortas por OOM). Verificação delegada ao CI

---

## Next Step

**Antes de `/ship`:** gravar na placa (`pio run -t upload`) e confirmar os três testes de
aceitação de percepção visual — o pulso escalando, o crítico furando o modo noturno e o
rótulo de mudo no relógio. O `GET /diag` autenticado pelo header `X-Monitor-Token`
(`alert.severity`, `alert.snooze_s`,
`alert.pulse_level`, `alert.pulse_base`) permite conferir os três de fora, sem depender de
impressão visual.

**Depois:** `/ship .claude/sdd/features/DEFINE_ALERTA_ESCALONADO.md`
