# DEFINE: Higiene — fechar circuitos

> Docs, doctor e config passam a descrever o painel que de fato corre nesta
> máquina — 4 provedores, alerta escalonado, v2 como reserva, prune honrando o toml —
> sem ligar feature nova nem apagar código morto.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | HIGIENE_CIRCUITOS |
| **Date** | 2026-09-19 |
| **Author** | define-agent |
| **Status** | ✅ Complete (Built) |
| **Clarity Score** | 15/15 |
| **Input** | `.claude/sdd/features/BRAINSTORM_HIGIENE_CIRCUITOS.md` (`brainstorm_document`) |
| **Roadmap** | lote 1 (P0) da varredura 2026-09-19; itens P1–P5 ficam no BRAINSTORM |

---

## Problem Statement

O repositório promete circuitos que o código não fecha e documentos que descrevem
um painel antigo: README e SPEC falam de 3 provedores com alerta de borda pulsante,
enquanto `session_model.h` já tem `COMMANDCODE`, o doctor nesta máquina avisa que
o protocolo v2 "não pode ser verificado" sem ter perguntado à placa, e
`usage_history.prune` ignora `storage.retention_days=30` (constante 35; SQLite real
com 35 linhas). Quem lê o repo, quem roda `doctor` e quem olha o painel não vê a
mesma história.

---

## Target Users

| User | Role | Pain Point |
|------|------|------------|
| Operador nesta mesa | Dono do painel, 4 agentes no ar | `doctor` sai WARN de token/v2/hook CC com a placa respondendo `/health`; README não cita o quarto agente que ele acabou de integrar |
| Agente SDD no próximo ciclo | Consome SPEC/ROADMAP como grounding | SPEC §3 ainda mostra `ToolType { CLAUDE, CODEX, UNKNOWN }`; ROADMAP deixa v2 como "decisão pendente" ambígua |
| Quem clona o repo | Instala pelo README | `Python 3.10+` nos docs contra `tomllib` + doctor + CI em 3.11; `--protocol 2` parece opção real (404 no firmware) |

> Escopo single-machine (ROADMAP 2026-09-07): um operador. As três filas acima são
> o mesmo humano em papéis distintos, mais o clone futuro. Não há persona de
> multi-node.

---

## Goals

| Priority | Goal |
|----------|------|
| **MUST** | README, SPEC e `CLAUDE.md` / `tools/README.md` descrevem **4** provedores (Claude, Codex, OpenCode, Command Code), alerta **escalonado** (não "borda pulsante") e o `ToolType` igual a `include/session_model.h` (`CLAUDE, CODEX, OPENCODE, COMMANDCODE, UNKNOWN`) |
| **MUST** | Unificar a versão mínima de Python em **3.11+** em todo doc de produto (README, CLAUDE.md, tools/README). Fonte da verdade: `tomllib` (3.11), `doctor.check_python` (`pair < (3, 11)` → FAIL) e CI (`python-version: "3.11"`) |
| **MUST** | `python tools/monitor.py doctor` **sem fixture** nunca afirma compatibilidade v2 que não mediu. Com a decisão de arquivar v2, a checagem live reporta o v2 como **reserva / não implementado no firmware**, não como "cannot be verified" |
| **MUST** | `python tools/monitor.py hooks check` inclui Command Code (help text hoje: "report Claude and Codex hook health") e o JSON de `hook_health()` já cobre os três; a CLI não pode parecer que só existem dois |
| **MUST** | SPEC + `EXAMPLE_TOML` marcam `transport.prefer_websocket`, `daemon.role`, `storage.hourly_retention_days` e a flag `--protocol 2` como **reserva sem consumidor / não-funcional**. Sem implementar, sem apagar `protocol_v2.py` |
| **MUST** | `usage_history.prune` honra `storage.retention_days` (default **30**). O daemon hoje chama `prune(history_db, tz=tz, now=now)` em `session_daemon.py:745` e cai na constante `RETENTION_DAYS = 35` |
| **MUST** | Token vazio: **dois canais, duas verdades** (confirmado 2026-09-19). Doctor WARN se `len(api_token)==0`. `config show` só mascara quando `len>0`; vazio aparece como `""`. Nunca o valor real |
| **MUST** | ROADMAP: lote P0 deste ciclo como item executado/em execução; protocolo v2 deixa de ser "🟡 Decisão pendente" e vira **reserva explícita** (não-funcional até pedido) |
| **SHOULD** | `EXAMPLE_TOML` declara `usage.commandcode_context_window` (o dataclass já tem o campo; o exemplo no repo já lista a linha — o AT trava regressão) |
| **SHOULD** | Fixture `tests/fixtures/doctor/healthy.json` continua podendo simular `protocols: [1, 2]` — o caminho com fixture **não** some; só o caminho live deixa de mentir |
| **COULD** | Título da SPEC ("Monitor de Sessões Claude/Codex") passar a "Monitor.AI"; numeração duplicada de seções 17 na SPEC **não** entra (precedente do build ALERTA: não renumerar histórico) |

**Nota de prioridade.** O prune é MUST apesar de ser um DELETE no SQLite: é a única
desconexão config↔código com efeito no disco (35 linhas reais vs. default 30), e o
card 7 só mostra 30 dias (`WINDOW_DAYS`). Apagar `protocol_v2.py` é YAGNI inverso —
fica reserva.

---

## Success Criteria

- [ ] **0** menções de "3 provedores" / "Claude, Codex e OpenCode" (sem Command Code) no README, na SPEC vigente (fora de seções históricas explicitamente marcadas) e em `tools/README.md`.
- [ ] SPEC §3 cita o `ToolType` com **5** enumeradores, idêntico a `include/session_model.h:7`.
- [ ] **100%** dos docs de produto que declaram versão de Python dizem **3.11+** (hoje: README badge + "Python 3.10+", CLAUDE.md "3.10+", tools/README "3.10+").
- [ ] `doctor` live (fixture ausente, placa no ar como em 2026-09-19) **não** emite a mensagem `protocol v2 compatibility cannot be verified`. A checagem de protocolo ou some do caminho live, ou reporta reserva/não-implementado, com status que **não** é `ok`.
- [ ] `monitor.py hooks check --help` (ou o help do subcomando) menciona Command Code; a saída JSON inclui a chave `commandcode`.
- [ ] Grep de `prefer_websocket` / `daemon.role` / `hourly_retention_days` no repo, fora de config/teste/SPEC-como-reserva, continua **0 consumidores funcionais** — e a SPEC o declara assim em 1 parágrafo.
- [ ] `session_daemon` passa `keep_days=config.storage.retention_days` (ou equivalente) a `prune`; com default 30, um banco de 35 dias perde as **5** linhas anteriores a `today-30`. Teste cobre o valor do **config**, não só a constante.
- [ ] `config show` com `api_token=""` imprime `""` (ou omite o valor), **nunca** `***redacted***` para length 0; com token de ≥1 caractere imprime `***redacted***` e o valor real **0** vezes na stdout.
- [ ] Doctor com length 0 continua WARN `no transport token configured` (não FAIL, não OK).
- [ ] `python -m pytest tests/ -q` **100%** verde; `python tools/check_secrets.py` não muda de comportamento (mesmo conjunto de arquivos, mesma redação).
- [ ] ROADMAP item 7 (v2) deixa de dizer só "decisão pendente" e registra a decisão: **arquivar como reserva**.

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | README de 4 provedores | README atual cita Claude/Codex/OpenCode no lead e nos cards | Docs atualizados | Lead, tabela "O painel mostra" e qualquer lista de agentes incluem Command Code; alerta não é descrito como "borda pulsante" |
| AT-002 | SPEC §3 = header | `include/session_model.h` tem 5 `ToolType` | SPEC §3 é lida | O bloco de código da §3 contém os mesmos 5 enumeradores, na mesma ordem |
| AT-003 | Python 3.11 nos docs | README/CLAUDE.md/tools/README dizem 3.10+ | Docs atualizados | Nenhuma dessas três fontes afirma 3.10 como piso; doctor e CI permanecem em 3.11 |
| AT-004 | Doctor live não finge v2 | Sem `--fixture`; placa responde `/health` (como 2026-09-19) | `python tools/monitor.py doctor` | Nenhuma linha `protocol v2 compatibility cannot be verified`; se a checagem existir, a mensagem admite reserva/não-implementado e o status **não** é `ok` |
| AT-005 | Fixture v2 intacta | `tests/fixtures/doctor/healthy.json` tem `"protocols": [1, 2]` | `doctor.run_checks(..., fixture=healthy.json)` | Continua só `ok` (incluindo `protocol`); o caminho determinístico dos testes não quebra |
| AT-006 | Hooks check cita CC | Help do subcomando `hooks check` | `python tools/monitor.py hooks check -h` (ou help equivalente) | Texto menciona Command Code; JSON de `hook_health()` tem chave `commandcode` (já verdadeira — o AT trava regressão da CLI) |
| AT-007 | Reservas na SPEC | Chaves `prefer_websocket`, `daemon.role`, `hourly_retention_days` e flag `--protocol 2` existem no código | SPEC + EXAMPLE_TOML atualizados | Cada uma aparece como reserva/não-funcional; `protocol_v2.py` **não** é apagado; testes de `test_protocol_v2.py` continuam coletados |
| AT-008 | Prune honra o toml | Banco com linhas em `today-34` e `today-8`; `storage.retention_days = 30` | Um ciclo que chama `prune` com o config | Linha `today-34` some; `today-8` fica; `daily_window` de 30 dias inalterado na ponta recente |
| AT-009 | Default 30, não 35 | Chamada de `prune` **sem** `keep_days` explícito *depois* da mudança, **ou** o daemon sempre passa o config | Teste com config default | Retenção efetiva é 30. O teste de `test_prune_removes_only_days_beyond_retention` deixa de assumir 35 se o default mudar |
| AT-010 | Token vazio no `config show` | `MonitorConfig` com `api_token=""` | `python tools/monitor.py config show` | JSON tem `api_token` igual a `""` (não `***redacted***`); nenhum outro campo secreto vaza |
| AT-011 | Token presente no `config show` | `api_token` com ≥16 caracteres (ou env `MONITOR_API_TOKEN`) | `config show` | `api_token` é `***redacted***`; o valor real aparece **0** vezes na stdout |
| AT-012 | Doctor token vazio | Mesmo snapshot de AT-010 | `doctor.check_token` | Status `warn`, mensagem `no transport token configured` |
| AT-013 | EXAMPLE_TOML tem CC | `EXAMPLE_TOML` em `monitor_config.py` | Teste ou grep de aceite | Contém `commandcode_context_window` |
| AT-014 | ROADMAP honesto | Item 7 diz "Decisão pendente" | Docs atualizados | Item 7 registra **reserva explícita / não-funcional**; lote P0 aparece como ciclo desta feature |
| AT-015 | Suite e segredos | Suite verde antes da mudança | `pytest tests/ -q` e `check_secrets.py` | 100% pass; `check_secrets` não amplia nem estreita o conjunto de arquivos |

---

## Out of Scope

- Grão horário, breakdown, custo R$/US$, tempo de agente bloqueado, export, OTA (P2–P5 do BRAINSTORM).
- Implementar endpoint v2, WebSocket, `daemon.role`, ou **apagar** `protocol_v2.py` / as chaves mortas.
- `/ship` e AT de hardware do alerta escalonado e do Command Code (P1).
- Instalar o hook CC em `~/.commandcode/settings.json` desta máquina (ação do operador).
- Root-cause dos totais de 16–32M tokens/dia no SQLite.
- Qualquer mudança em firmware (`src/`, `include/` de comportamento). SPEC §3 apenas **cita** o enum que o `.h` já tem.
- Renumerar seções históricas da SPEC.
- Multi-node, painel web, coletores Gemini/Cursor/Aider.
- Trocar `***redacted***` por omissão do campo quando o token existe — só o caso length=0 muda.
- Alterar `WINDOW_DAYS = 30` (janela do card 7). Só a retenção no disco (prune) muda.

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Technical | Tools PC só stdlib (regra 2 do `CLAUDE.md`) | Doctor/config/prune não ganham dependência |
| Technical | `POST /sessions` aditivo (regra 3) | Lote 1 **não** mexe no contrato; v2 continua código morto no PC |
| Technical | Hooks em caminhos estáveis (regra 4) | Nenhum `install_*.py` muda de path; o lote não instala hook, só faz a CLI enxergar o quarto |
| Technical | `tomllib` exige Python 3.11 | Docs 3.10+ estão **errados**; o piso sobe nos docs, o código já recusa 3.10 |
| Technical | Convenção de teste `unittest.TestCase` + `subTest` | Novos testes de doctor/prune/redact seguem a casa, não `pytest.mark.parametrize` da KB |
| Technical | `_redact` chaveia pelo **nome** do campo | `config show` precisa de exceção **só** para token de length 0; outros campos `token`/`secret` continuam mascarados |
| Resource | Sem flash de firmware neste lote | SPEC alinha ao `.h`; o binário na placa não muda |
| Scope | Single-machine; YAGNI "documentar e arquivar" | v2 e chaves mortas não viram feature |

---

## Technical Context

| Aspect | Value | Notes |
|--------|-------|-------|
| **Deployment Location** | `README.md`, `docs/SPEC.md`, `docs/ROADMAP.md`, `CLAUDE.md`, `tools/README.md`; `tools/doctor.py`, `tools/monitor.py`, `tools/monitor_config.py`, `tools/session_daemon.py`, `tools/usage_history.py`; `tests/test_doctor.py`, `tests/test_usage_history.py`, `tests/test_monitor_config.py`; fixtures `tests/fixtures/doctor/*.json` **só se** a mensagem live mudar o contrato dos testes | Sem `src/` / `include/` de comportamento. `protocol_v2.py` intocado |
| **KB Domains** | `python`, `testing` | Nenhuma domain cobre docs de produto nem LVGL. Confiança 0.80 do **codebase** (padrão `CheckResult`, `_redact`, `unittest`+`subTest`). Design não deve puxar dbt/airflow |
| **IaC Impact** | None | Sem nuvem. CI já usa 3.11 — não muda o workflow, só os docs que mentem o piso |

**Why This Matters:**

- **Location** → Design não abre firmware "por via das dúvidas"
- **KB Domains** → `python` (dataclasses/stdlib) e `testing` (fixtures doctor); o resto da KB é ruído
- **IaC Impact** → nenhum job novo; `python-version: "3.11"` já é o gate

---

## Data Contract (if applicable)

O lote **não** cria pipeline. Há um efeito de retenção no SQLite existente:

### Source Inventory

| Source | Type | Volume | Freshness | Owner |
|--------|------|--------|-----------|-------|
| `%APPDATA%/monitor-ai/monitor-ai.db` → `usage_history` | SQLite local | 35 linhas observadas (2026-08-15 … 2026-09-19), soma 236.457.317 tokens | UPSERT do dia a cada ciclo (~5s) | daemon |

### Schema Contract

| Column | Type | Constraints | PII? |
|--------|------|-------------|------|
| day | TEXT | PRIMARY KEY, ISO `YYYY-MM-DD` | No |
| tokens | INTEGER | NOT NULL | No |

**Sem alteração de schema.** Sem tabela horária (`hourly_retention_days` permanece reserva).

### Freshness SLAs

Não aplicável — prune é DELETE de linhas já escritas, não ingestão.

### Completeness Metrics

- Card 7 continua com exatamente `WINDOW_DAYS` (30) inteiros, oldest-first; dias ausentes = 0.
- Após prune com `retention_days=30`, **0** linhas com `day < today-30`.
- As 5 linhas extras hoje (retenção 35) estão **fora** da janela do card; apagá-las não muda o heatmap visível.

### Lineage Requirements

- `session_daemon` é o único caller de `prune` (`session_daemon.py:745`).
- Default de config (`StorageSettings.retention_days = 30`) é a fonte; a constante `RETENTION_DAYS = 35` deixa de ser o número efetivo.

---

## Assumptions

| ID | Assumption | If Wrong, Impact | Validated? |
|----|------------|------------------|------------|
| A-001 | Apagar as 5 linhas além de 30 dias no SQLite desta máquina não perde nada que o card 7 mostre | Operador que consultasse o banco cru pelos dias 31–35 perderia esses totais; não há UI para eles | [x] **Sim** — `WINDOW_DAYS = 30` e `daily_window` só lê essa janela; medido 35 linhas no disco |
| A-002 | O WARN de token vazio do doctor (2026-09-19) reflete o snapshot que o doctor carregou (`api_token=""` no toml, sem `MONITOR_API_TOKEN` nesse processo). O daemon em serviço pode ter outro env | Doctor "certo" e daemon autenticado ao mesmo tempo — aceitável: doctor diagnostica **o config que ele vê** | [x] **Parcial** — `MonitorConfig.load` aplica `MONITOR_API_TOKEN`; o WARN implica que aquele processo não tinha env. Não investigamos o serviço |
| A-003 | `/health` sem token (device OK no doctor) não implica que `POST /sessions` também aceite vazio | Fora deste lote: não vamos "consertar" auth | [x] **Sim o bastante** — higiene não mexe em auth; AT-012 só trava o WARN |
| A-004 | `EXAMPLE_TOML` no repo **já** contém `commandcode_context_window` (lido em `monitor_config.py` nesta sessão) | AT-013 é regressão, não trabalho novo | [x] **Sim** — linha presente no fonte; o `monitor.toml` **do usuário** é que está velho, e não é nosso para reescrever |
| A-005 | Firmware na placa não precisa de reflash para este lote | SPEC §3 desatualizada é só papel; o `.h` compilado já tem `COMMANDCODE` | [x] **Sim** — BUILD_REPORT_COMMANDCODE compilou `parse_tool("commandcode")` |
| A-006 | Caminho com `--fixture` do doctor deve continuar mentindo *de propósito* (dados injetados), inclusive `protocols: [1,2]` | Se o Design remover a checagem `protocol` de vez, `healthy.json` e `test_healthy_fixture_has_only_successful_checks` quebram | [ ] Não — Design escolhe: manter a checagem só sob fixture, ou trocar a mensagem live e ajustar o fixture se o código da checagem unificar |
| A-007 | Unificar docs em 3.11 **não** exige subir o `python-version` do CI (já é 3.11) | Se alguém ainda roda 3.10 local, `tomllib` já quebra — o doc mentia | [x] **Sim** — `ci.yml:21` e `doctor.py:142-143` |

---

## Clarity Score Breakdown

| Element | Score (0-3) | Notes |
|---------|-------------|-------|
| Problem | 3 | Quem sofre, o quê mente (README/SPEC/doctor/prune) e evidência medida (35 linhas, doctor live, enum no `.h`) |
| Users | 3 | Três papéis com dor distinta; single-machine explícito |
| Goals | 3 | 8 MUST + 2 SHOULD + 1 COULD; prune e token com decisão do usuário (2026-09-19) |
| Success | 3 | 11 critérios com contagem (0 menções, 5 enumeradores, 5 linhas, 0 vazamentos, 100% pytest) |
| Scope | 3 | 11 exclusões herdadas do YAGNI + firmware + schema horário + instalar hook |
| **Total** | **15/15** | |

**Por que 15.** Input era `brainstorm_document` com 8 perguntas, abordagem A confirmada,
4 validações incrementais e o vão do token fechado nesta fase ("dois canais, duas
verdades"). O risco residual está em A-006 (forma exata da checagem `protocol` no
caminho live vs. fixture) — é decisão de Design, não lacuna de requisito.

---

## Open Questions

Nenhuma bloqueante para o Design.

Fechado nesta fase:

- **Token vazio** → doctor WARN se length=0; `config show` imprime `""` quando length=0 e `***redacted***` quando length>0. Nunca o valor real.

Para o Design resolver (não são lacunas de requisito):

- Forma da checagem `protocol` no caminho live: remover o check, ou emitir WARN/INFO de "v2 reservado / firmware só v1", preservando o ramo de fixture (A-006).
- `RETENTION_DAYS = 35`: apagar a constante, alias para 30, ou deixar só como fallback morto — o MUST é o daemon passar o valor do config.
- Onde o parágrafo de "reserva" mora na SPEC (seção nova vs. nota na 5 / protocolo). Não renumerar as seções 17 duplicadas.

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-09-19 | define-agent | Initial version a partir de `BRAINSTORM_HIGIENE_CIRCUITOS.md`; token vazio decidido com o operador |

---

## Next Step

**Ready for:** `/build .claude/sdd/features/DESIGN_HIGIENE_CIRCUITOS.md`
