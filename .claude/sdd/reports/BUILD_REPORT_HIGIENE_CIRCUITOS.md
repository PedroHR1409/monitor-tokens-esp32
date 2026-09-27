# BUILD REPORT: Higiene — fechar circuitos

> Relatório de implementação da feature HIGIENE_CIRCUITOS (lote P0 do
> `.claude/sdd/features/BRAINSTORM_HIGIENE_CIRCUITOS.md`)

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | HIGIENE_CIRCUITOS |
| **Date** | 2026-09-19 |
| **Author** | build-agent |
| **DEFINE** | [DEFINE_HIGIENE_CIRCUITOS.md](../features/DEFINE_HIGIENE_CIRCUITOS.md) |
| **DESIGN** | [DESIGN_HIGIENE_CIRCUITOS.md](../features/DESIGN_HIGIENE_CIRCUITOS.md) |
| **Status** | Complete |

---

## Summary

| Metric | Value |
|--------|-------|
| **Tasks Completed** | 14/14 (13 do manifesto + 1 desvio) |
| **Files Created** | 0 |
| **Files Modified** | 14 |
| **Lines of Code** | ~+26 / -7 (código) · ~+50 / -1 (testes) · ~+101 / -17 (docs) |
| **Nota de medição** | Vários arquivos tocados já tinham mudanças **não commitadas** de features anteriores (Command Code, alerta), então `git diff` não isola este build. Os números acima contam as edições desta sessão, arquivo a arquivo |
| **Build Time** | — (sem firmware neste lote) |
| **Tests Passing** | 285/285 + 34 subtests (baseline: 278/279 + 1 falha pré-existente) |
| **Agents Used** | 0 delegados (execução direta — ver nota) |

**Nota sobre agentes.** O DESIGN atribuiu @python-developer, @code-documenter e
@test-generator. O executor desta sessão não tem o tool `Task` disponível para
despachar subagentes, então as 14 tarefas foram executadas **diretamente** pelo
build-agent, seguindo os padrões do DESIGN, da KB e do codebase. A atribuição do
manifesto permanece como referência; `@code-reviewer` nos dois pontos de maior risco
(`doctor.py` e `monitor_config.py`) segue como sugestão registrada.

---

## Task Execution with Agent Attribution

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 1 | `tools/usage_history.py` — `RETENTION_DAYS = 30` | (direct) | ✅ Complete | Comentário diz que o config é a fonte efetiva |
| 2 | `tools/session_daemon.py` — encadear `retention_days` | (direct) | ✅ Complete | 2 assinaturas + 1 chamada interna + 4 call sites |
| 3 | `tools/doctor.py` — `check_protocol` live declara reserva | (direct) | ✅ Complete | Docstring explica por que "cannot be verified" saiu |
| 4 | `tools/monitor_config.py` — `_redact` não mascara vazio | (direct) | ✅ Complete | `None` e `""` passam direto |
| 5 | `tools/monitor.py` — help de `hooks check` | (direct) | ✅ Complete | "report Claude, Codex and Command Code hook health" |
| 6 | `tests/test_doctor.py` — `DoctorProtocolTests` | (direct) | ✅ Complete | 3 testes: live reserva, fixture `[1,2]`, fixture `[1]` |
| 7 | `tests/test_monitor_config.py` — token vazio | (direct) | ✅ Complete | 1 teste: `api_token` fica `""` |
| 8 | `tests/test_usage_history.py` — prune | (direct) | ✅ Complete | 2 testes: `keep_days` explícito, default = config |
| 9 | `README.md` — 4 provedores, alerta, Pythons | (direct) | ✅ Complete | Lead, tabela, hooks, cotas, hardware, badges, contagem |
| 10 | `docs/SPEC.md` — título, enum, tools, §21 | (direct) | ✅ Complete | §21 "Reservas declaradas"; §3 alinhada ao `.h` |
| 11 | `docs/ROADMAP.md` — item 9 + v2 arquivado | (direct) | ✅ Complete | Item 9 (higiene) + item 7 virou reserva + pódio 4 col. atualizado |
| 12 | `CLAUDE.md` — Python 3.11+ | (direct) | ✅ Complete | Regra dura 2 |
| 13 | `tools/README.md` — 3.11, reservas, prune | (direct) | ✅ Complete | Nova seção "Reservas declaradas" |
| 14 | `tests/test_production_contracts.py` — asserção obsoleta | (direct) | ✅ Complete | **Desvio** — ver Deviations; corrige falha pré-existente |

**Legenda:** ✅ Complete · `@agente` = delegado via Task · `(direct)` = executado pelo build

---

## Agent Contributions

| Agent | Files | Specialization Applied |
|-------|-------|------------------------|
| (direct) | 14 | Padrões do DESIGN + KB `python`/`testing` + convenções do codebase (`unittest`+`subTest`, `CheckResult`, `_redact`) |

Nenhum agente especialista foi despachado (sem tool `Task` nesta sessão). Os padrões
da KB `python` (`@dataclass(frozen=True, slots=True)`, type hints) e da KB `testing`
já estavam materializados no código tocado.

---

## Files Created

Nenhum arquivo criado neste lote — o manifesto é 100% de modificação, como planejado.

---

## Files Modified

| File | +/- (desta sessão) | Verified | Notes |
| ---- | --- | -------- | ----- |
| `tools/usage_history.py` | +3/-1 | ✅ | `RETENTION_DAYS` 35→30 |
| `tools/session_daemon.py` | +8/-1 | ✅ | `retention_days` encadeado até o prune |
| `tools/doctor.py` | +10/-3 | ✅ | Mensagem live de reserva + docstring |
| `tools/monitor_config.py` | +4/-0 | ✅ | `_redact` preserva vazio |
| `tools/monitor.py` | +1/-1 | ✅ | Help do subcomando |
| `tests/test_doctor.py` | +19/-0 | ✅ | `DoctorProtocolTests` |
| `tests/test_monitor_config.py` | +9/-0 | ✅ | Token vazio |
| `tests/test_usage_history.py` | +21/-0 | ✅ | `keep_days` + default |
| `README.md` | +9/-8 | ✅ | 4 provedores, alerta, 3.11 |
| `docs/SPEC.md` | +22/-3 | ✅ | Título, enum, tools, §21 |
| `docs/ROADMAP.md` | +42/-1 | ✅ | Item 9, v2 arquivado, pódio |
| `CLAUDE.md` | +1/-1 | ✅ | 3.11 |
| `tools/README.md` | +17/-2 | ✅ | 3.11 + reservas + prune |
| `tests/test_production_contracts.py` | +1/-1 | ✅ | **Desvio** — asserção stale do pódio |

---

## Verification Results

### Lint / Sintaxe

```text
python -m compileall -q tools tests   → OK (sem saída)
```

O projeto não configura `ruff`/`mypy` (não há `pyproject.toml`/`setup.cfg`); a
verificação de sintaxe do projeto é `compileall`, conforme o README raiz.

**Status:** ✅ Pass

### Type Check

```text
N/A - o projeto não configura mypy/pyright
```

**Status:** ⏭️ Skipped

### Tests

```text
python -m pytest tests/ -q
285 passed, 34 subtests passed in 43.61s
```

Baseline antes da feature: **278 passed + 1 falha pré-existente** (`279` coletados).
Delta: **+6 testes** (3 doctor, 1 config, 2 usage_history), **+0 subtests**, e a falha
pré-existente corrigida pelo desvio #14.

**Status:** ✅ 285/285 Pass

### Smoke real (dados do operador)

```text
python tools/monitor.py doctor                       → protocol v2 is a reserved,
                                                       non-functional contract; the
                                                       firmware serves the v1 /sessions endpoint
python tools/monitor.py config show                  → "api_token": ""
python tools/monitor.py hooks -h                     → "report Claude, Codex and Command Code hook health"
python tools/monitor.py hooks check                  → {"claude": true, "codex": true, "commandcode": false}
```

`config show` e `doctor` agora contam a mesma história sobre o token vazio (ambos
"sem token"), e o doctor não afirma mais uma verificação que não fez.

**Status:** ✅ Pass

### Segredos

```text
python tools/check_secrets.py   → exit 1
- include\secrets.example.h
```

**Status:** ❌ Falha — **pré-existente, não relacionada ao build.** O token local ainda é
o **placeholder** do exemplo (não um valor real), então o scanner acusa
`secrets.example.h`. A correção é o operador definir um token real. Nenhum arquivo deste
build toca segredos; `check_secrets.py` não mudou de comportamento.

**Acompanhamento da revisão (2026-09-25):** o placeholder do template agora é excluído
do scan exato, e o verificador informa explicitamente quando `include/secrets.h` não
existe. A verificação local passou nesta revisão. O CI ganhou uma varredura Gitleaks do
histórico; o resultado dela ainda depende da próxima execução do workflow.

### Firmware

**Não aplicável** — o lote não toca `src/` nem `include/` de comportamento, conforme o
DESIGN (`Out of Scope`). Nenhuma recompilação necessária.

---

## Issues Encountered

| # | Issue | Resolution |
|---|-------|------------|
| 1 | Uma imprecisão do DESIGN: ele afirmava que o `run()` chamava o `prune` diretamente | Corrigido no próprio DESIGN antes do build: a cadeia real é `run` → `build_payload_v1/v2` → `_record_daily_history` → `prune`. O parâmetro foi encadeado por todas as camadas |
| 2 | `test_production_contracts.py::test_usage_widget_has_title_arrow_and_no_card_longpress` falhava **antes** deste build | Asserção alinhada à realidade (pódio de 4 colunas) — ver Deviations #14 |
| 3 | `hooks check` sai com exit 1 | Comportamento pré-existente e correto: retorna 0 só quando todos os hooks estão instalados; o hook do Command Code não está nesta máquina (AT-006 cobre só a presença da chave) |

---

## Autonomous Decisions

| # | Decision Point | Options Considered | Chose | Rationale |
|---|----------------|--------------------|-------|-----------|
| 1 | Passar `retention_days` nos 2 call sites de fallback 422, onde `history_db` não é enviado | Passar (uniforme) vs omitir (não tem efeito hoje) | **Passar nos 4** | O DESIGN dizia "quatro call sites"; e se o fallback um dia incluir `history_db`, omitir faria o prune cair no default 30 em vez do config do operador (ex.: 14). Um kwarg a mais é mais barato que um bug silencioso futuro |
| 2 | Default do parâmetro nas assinaturas | `30` literal vs `usage_history.RETENTION_DAYS` | **`usage_history.RETENTION_DAYS`** | Uma fonte só: se o default do módulo mudar, as assinaturas acompanham sem edição |
| 3 | Corrigir a asserção do contrato do pódio (falha pré-existente) | Deixar vermelho e reportar como blocker vs corrigir a asserção | **Corrigir** | A asserção descrevia um layout de 3 colunas que o firmware (já construído, não commitado) abandonou; mantê-la deixaria a suíte vermelha e o CI quebrado no próximo commit. É alinhamento de verdade, não relaxamento de teste — a nova asserção trava o contrato de 4 colunas |
| 4 | Onde colocar a SPEC §21 (reservas) | Renumerar as seções 17 duplicadas vs anexar como §21 | **§21 ao final** | Precedente do build ALERTA: não renumerar seções históricas nem invalidar referências. A DEFINE marcou renumerar como fora de escopo |
| 5 | Onde posicionar a seção 9 do ROADMAP | Antes da 7 (posição inicial) vs ao final | **Ao final, após a 8** | A ordem documental do arquivo é numérica; 9 depois de 8 é consistente. Reordenado durante o build |
| 6 | Atualizar a "Limitação conhecida" do item 8 (pódio de 3 colunas) | Deixar vs marcar resolvido | **Marcar resolvido** | A limitação deixou de existir quando o pódio virou 4 colunas; mantê-la seria nova mentira documental — exatamente o que a feature combate |
| 7 | Incluir `install_commandcode_hook.py` no README §3 | Deixar só Claude/Codex vs incluir o terceiro installer | **Incluir** | Paridade de 4 provedores pedida pela DEFINE; `tools/README.md` já listava o script |
| 8 | Adicionar a seção "Reservas declaradas" também no `tools/README.md` | Só na SPEC vs nos dois | **Nos dois** | Quem lê o mapa das ferramentas é quem mais precisa saber que `prefer_websocket`/`role`/`hourly_retention` são reserva |

---

## Deviations from Design

| Deviation | Reason | Impact |
|-----------|--------|--------|
| `tests/test_production_contracts.py` modificado (não estava no manifesto) | A asserção `COL_X[3] = {22, 102, 182}` descrevia o pódio de 3 colunas; o `ui_dashboard.cpp` (modificado localmente pela feature Command Code, ainda não commitada) passou a `COL_X[USAGE_PROVIDERS] = {8, 82, 156, 230}`. A suíte estava vermelha **antes** deste build | Restaura a suíte verde; trava o contrato de 4 colunas. Fora do escopo documental/firmware declarado, mas necessário para o quality gate ("todos os testes passam") |
| `README.md` ganhou o installer de hook do Command Code e a seção de hooks foi além do "4 provedores" estrito | Paridade do quarto provedor era o objetivo do AT-001; `tools/README.md` já listava o script | Documentação mais completa; nenhum código |
| `tools/README.md` ganhou a seção "Reservas declaradas" (o DESIGN previa só SPEC + EXAMPLE_TOML) | Mesma informação no mapa de módulos, onde o leitor de ferramentas procura | Duplicação intencional de uma tabela curta |
| `docs/ROADMAP.md` item 8 teve a "Limitação conhecida" reescrita | Era falsa após o pódio de 4 colunas | Correção de verdade documental |

Nenhum desvio de código de produção: `tools/*.py` foi implementado exatamente como o
DESIGN especificou (4 ADRs, patterns 1–5).

---

## Blockers

| Blocker | Required Action | Owner |
|---------|-----------------|-------|
| Nenhum bloqueante de código | — | — |
| `secrets.example.h` com token placeholder | definir token real (pré-existente, herdado do build Command Code) | operador |
| Hook do Command Code não instalado nesta máquina | `python tools/install_commandcode_hook.py` (P1 operacional; fora deste lote) | operador |

---

## Acceptance Test Verification

| ID | Scenario | Status | Evidence |
|----|----------|--------|----------|
| AT-001 | README de 4 provedores | ✅ Pass | Lead, tabela "O painel mostra", instaladores de hook e cotas citam Command Code; alerta descrito como escalonado |
| AT-002 | SPEC §3 = header | ✅ Pass | §3 contém `{ CLAUDE, CODEX, OPENCODE, COMMANDCODE, UNKNOWN }`, idêntico a `include/session_model.h:7` |
| AT-003 | Python 3.11 nos docs | ✅ Pass | README (badge + 2 menções), CLAUDE.md, tools/README dizem 3.11+; `doctor.py:142` e `ci.yml:21` já eram 3.11 |
| AT-004 | Doctor live não finge v2 | ✅ Pass | Smoke real: `protocol v2 is a reserved, non-functional contract; the firmware serves the v1 /sessions endpoint`, status WARN |
| AT-005 | Fixture v2 intacta | ✅ Pass | `DoctorFixtureTests.test_healthy_fixture_has_only_successful_checks` verde; `DoctorProtocolTests` cobre `[1,2]`→OK e `[1]`→legacy |
| AT-006 | Hooks check cita CC | ✅ Pass | `hooks -h` mostra o texto novo; `hooks check` devolve `{"claude":…,"codex":…,"commandcode":…}` |
| AT-007 | Reservas na SPEC | ✅ Pass | SPEC §21 + `tools/README.md`; `protocol_v2.py` e `test_protocol_v2.py` intactos (suíte coletou os testes) |
| AT-008 | Prune honra o toml | ✅ Pass | `test_prune_honours_an_explicit_retention_from_config` (keep_days=10 remove 13 dias, mantém 8) |
| AT-009 | Default 30, não 35 | ✅ Pass | `test_default_retention_matches_the_config_default` compara `StorageSettings().retention_days` com `RETENTION_DAYS` |
| AT-010 | Token vazio no `config show` | ✅ Pass | `test_redacted_dict_keeps_an_unconfigured_token_empty` + smoke real (`"api_token": ""`) |
| AT-011 | Token presente no `config show` | ✅ Pass | `test_redacted_dict_never_exposes_a_configured_token` (pré-existente, ainda verde) |
| AT-012 | Doctor token vazio | ✅ Pass | Smoke real: `WARN token no transport token configured` |
| AT-013 | EXAMPLE_TOML tem CC | ✅ Pass | `monitor_config.py:188` contém `commandcode_context_window` |
| AT-014 | ROADMAP honesto | ✅ Pass | Item 7 "🔵 Arquivado como reserva (2026-09-19)"; item 9 registra o ciclo P0 |
| AT-015 | Suite e segredos | ⚠️ Parcial | Suíte 285/285 verde; `check_secrets.py` continua falhando por motivo **pré-existente** (`secrets.example.h`), sem relação com o build |

---

## Performance Notes

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| Reflash de firmware | 0 (fora de escopo) | 0 | ✅ |
| Mudança no contrato `POST /sessions` | 0 | 0 | ✅ |
| Testes verdes | 100% | 285/285 + 34 subtests | ✅ |

---

## Final Status

### Overall: ✅ COMPLETE

**Completion Checklist:**

- [x] All tasks from manifest completed (13/13) + 1 desvio documentado
- [x] All verification checks pass (compileall, smoke real)
- [x] All tests pass (285/285 + 34 subtests)
- [x] No blocking issues de código
- [x] Acceptance tests verified (AT-015 parcial por `check_secrets` pré-existente)
- [ ] Ready for /ship — sim, com a ressalva de AT-015 e o hook CC não instalado

---

## Next Step

**If Complete:** `/ship .claude/sdd/features/DEFINE_HIGIENE_CIRCUITOS.md`
