# BRAINSTORM: Higiene — fechar circuitos

> Varredura do projeto (bugs, melhorias, features) transformada em backlog
> ranqueado. O próximo `/define` cobre só o lote 1 (higiene). Sem alteração
> de código nesta fase.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | HIGIENE_CIRCUITOS |
| **Date** | 2026-09-19 |
| **Author** | brainstorm-agent |
| **Status** | ✅ Complete (Defined) |
| **Origem** | `/workflow:brainstorm` — "análise do projeto, buscando melhorias, novas features e correção de erros. Etapa de planejamento, não faça alterações." |

---

## Initial Idea

**Raw Input:** "faça uma análise do projeto, buscando melhorias, novas features e correção de erros. Esta é uma etapa de planejamento, não faça alterações."

**Context Gathered:**

- O roteiro vigente (`docs/ROADMAP.md`, 2026-09-07, v0.3, single-machine) já nasceu de uma varredura igual a esta: capacidades pagas pela arquitetura e nunca ligadas. Dois itens saíram do papel desde então — alerta escalonado (2026-09-08) e Command Code (2026-09-19) — ambos 🟢 Construído, **sem `/ship`**.
- A máquina real está viva: daemon posta em `http://192.168.2.165:80/sessions`; `GET /health` responde; SQLite em `%APPDATA%/monitor-ai/monitor-ai.db` tem **35 linhas** `(day, tokens)` de 2026-08-15 a 2026-09-19 (soma 236.457.317).
- `python tools/monitor.py doctor` nesta sessão: config OK, device OK, notify OK, paths dos 4 provedores OK; WARNs em token, hook Command Code, PlatformIO no PATH, protocolo v2.
- Duas mentiras documentais gritantes: README ainda cita "Claude Code, Codex e OpenCode"; SPEC §3 ainda mostra `enum class ToolType : uint8_t { CLAUDE, CODEX, UNKNOWN }` — `include/session_model.h:7` já tem `COMMANDCODE = 3`.
- Três chaves de `monitor.toml` sem nenhum consumidor no repo: `transport.prefer_websocket`, `daemon.role`, `storage.hourly_retention_days`. `protocol_v2.py` (233 linhas) + testes existem; firmware só registra `/sessions`, `/health`, `/diag`, `/hidden`, `/pinned` — `--protocol 2` bate em 404.
- `usage_history.RETENTION_DAYS = 35` contra `storage.retention_days = 30` no config; o banco real tem exatamente 35 linhas.
- Features já no ROADMAP e **fora deste ciclo**: grão horário (#2), custo R$ (#3), tempo bloqueado (#4), export (#5), OTA (#6). Protocolo v2 implementar (#7) fica arquivado no papel (justificativa era multi-node, descartado).

**Technical Context Observed (for Define):**

| Aspect | Observation | Implication |
|--------|-------------|-------------|
| Likely Location | `README.md`, `docs/SPEC.md`, `docs/ROADMAP.md`, `tools/doctor.py`, `tools/monitor.py`, `tools/monitor_config.py`, `tools/usage_history.py`, `tests/fixtures/doctor/`, `tests/test_doctor.py`, `tests/test_usage_history.py` | Epic documental + doctor + um débito de prune. Sem firmware neste lote, salvo se a SPEC citar o enum (já está certo no `.h`) |
| Relevant KB Domains | `python`, `testing` | Nenhuma das 24 domains cobre LVGL/embedded/docs de produto; confiança vem do **codebase** e das amostras reais, não da KB |
| IaC Patterns | N/A | Projeto sem infraestrutura de nuvem |

---

## Discovery Questions & Answers

| # | Question | Answer | Impact |
|---|----------|--------|--------|
| 1 | Qual é o objetivo principal desta análise? | **Varredura completa** — bugs, melhorias e features, e só depois escolher o próximo ciclo SDD | O artefato é um backlog, não um recorte cego do ROADMAP nem uma caçada só a bugs |
| 2 | Como você vai usar o resultado? | **Backlog ranqueado** — lista priorizada, sem implementar nada agora | BRAINSTORM persiste o ranking; `/define` pega só o lote 1 |
| 3 | O que deve ficar no topo? | **Fechar circuitos** — capacidades já pagas / docs que mentem / config órfã | Features novas (grão horário, custo) não entram neste DEFINE |
| 4 | Quais evidências reais desta máquina? | **Tudo que existir** — doctor, config redigida, SQLite, event store, logs, transcripts CC | Ranking grounded em números observados, não em fixture |
| 5 | Abordagem? | **A — ciclo de higiene** (confirmada 2026-09-19) | Descarta pular para ROADMAP #2 e descarta o "tudo junto" |
| 6 | YAGNI: v2 e chaves mortas? | **Documentar e arquivar** — reserva explícita; sem implementar, sem apagar | `protocol_v2.py` e as chaves ficam; doctor para de fingir v2 na placa |
| 7 | Recorte do lote 1? | **Sim, segue** — docs, doctor, reservas, retention, hook CC + EXAMPLE_TOML | `/ship` e hardware ficam P1; grão horário P2 |
| 8 | Ranking P0→P5? | **Sim, escreve o BRAINSTORM** | Quality gate autorizado |

**Minimum Questions:** 3 · **Asked:** 8

---

## Sample Data Inventory

> Samples improve LLM accuracy through in-context learning and few-shot prompting.

| Type | Location | Count | Notes |
|------|----------|-------|-------|
| Doctor ao vivo | `python tools/monitor.py doctor` (2026-09-19) | 1 run | OK: config, 4 paths, hooks claude/codex, python, storage, device, notify. WARN: token, hooks.commandcode, platformio PATH, protocol v2 |
| Config redigida | `python tools/monitor.py config show` | 1 | `prefer_websocket=true`, `hourly_retention_days=365`, `retention_days=30`, `role=standalone`, `api_token="***redacted***"` (redact mascara até string vazia) |
| `monitor.toml` real | `%APPDATA%/monitor-ai/monitor.toml` | 1 | Quase tudo comentado; `api_token = ""` efetivo; daemon provavelmente autentica por env ou firmware aceita vazio |
| SQLite `usage_history` | `%APPDATA%/monitor-ai/monitor-ai.db` | 35 rows | Schema `(day TEXT PK, tokens INTEGER)`; min 2026-08-15, max 2026-09-19; soma 236.457.317. Pico 32.960.916 em 2026-09-15. **Sem tabela horária** |
| Event store Claude | `~/.claude/monitor-ai-events.json` | 62 sessões, 16.5 KB | `ended:16, free:40, work:4, ask:2`. Só último evento por sessão |
| Event store CC | `~/.commandcode/monitor-ai-events.json` | 0 | Não existe — casa com `hooks.commandcode not installed` |
| Transcripts CC | `~/.commandcode/projects/*/*.jsonl` | 5 projetos, 14 jsonl | Schema já groundado na feature COMMANDCODE_INTEGRATION |
| Daemon stdout | `tools/daemon.log` | 1342 linhas | Cards OK; trecho antigo com o **mesmo** projeto OpenCode 3× no grid (`fix_29672-...[OC:free]` ×3) |
| Daemon stderr | `tools/daemon.err.log` | timeouts + alerta | `alerta: warning` / `alerta encerrado` (feature ALERTA_ESCALONADO viva); rajadas de `urlopen error timed out` para a placa |
| Fixtures doctor | `tests/fixtures/doctor/{healthy,warning,failing}.json` | 3 | `healthy` já declara `protocols: [1,2]` e `commandcode: true` — o caminho live **nunca** preenche `protocols` |
| Código relacionado | `tools/doctor.py`, `monitor_config.py`, `usage_history.py`, `protocol_v2.py`, `include/session_model.h`, `docs/{SPEC,ROADMAP,README}` | — | Padrões a reusar: `CheckResult`, `_redact`, `unittest`+`subTest` |

**How samples will be used:**

- Doctor ao vivo + fixtures: regressão de `check_protocol` / `check_token` / `hooks.commandcode` no DEFINE/BUILD
- SQLite real: prova de que `hourly_retention_days` não tem tabela, e de que o prune em 35 (não 30) é o que está no disco
- Event store CC ausente: AT do installer de hook (não instalar no DEFINE — só exigir que doctor/hooks check reportem o quarto provedor)
- `config show` vs doctor token: o redact de campo vazio é um falso positivo visual; DEFINE deve decidir se `***redacted***` some quando length=0
- Totais de 16–32M/dia: **não** entram como bug neste ciclo — sem breakdown não dá para cravar inflação vs. uso real de 4 provedores

---

## Approaches Explored

### Approach A: Ciclo de higiene — fechar circuitos ⭐ Recommended

**Description:** Backlog ranqueado no BRAINSTORM; próximo `/define` é um epic curto só de circuitos já pagos e mentiras documentais. Sem feature nova de dado, sem firmware novo, sem apagar `protocol_v2.py`.

**Pros:**

- Casa com o critério explícito ("fechar circuitos no topo") e com a origem do próprio ROADMAP (2026-09-07)
- Risco baixo: docs, doctor, comentários de reserva, um default de prune
- Reusa módulos existentes (`CheckResult`, `MonitorConfig`, `usage_history.prune`)
- O painel, o doctor e o README passam a contar a mesma história (4 provedores, v2 não-funcional, config honesta)

**Cons:**

- Não entrega grão horário nem custo R$ neste ciclo
- Totais diários grandes ficam sem root-cause até P2

**Why Recommended:** Confiança **0.80** (codebase + amostras reais; sem KB de LVGL/embedded). Evidência cruzada: chaves sem grep de consumidor, schema SQLite observado, doctor live vs. `check_protocol` que só lê fixture (`tools/doctor.py:195-202`), README/SPEC vs. `session_model.h:7`. O ROADMAP já ensinou que ligar o que está pago rende mais que inventar eixo novo.

---

### Approach B: Pular higiene e abrir o item #2 do ROADMAP (grão horário)

**Description:** Migrar `usage_history` para grão horário com breakdown (input/output/reasoning/cache.write). Destrava custo e export.

**Pros:**

- Dado novo no card 7; é o próximo item ⚪ Planejado do ROADMAP
- Schema real `(day, tokens)` é exatamente o gargalo descrito em ROADMAP #2

**Cons:**

- Constrói em cima de `retention_days` que o código ignora
- Docs continuam mentindo (3 provedores, enum antigo) enquanto se mexe no SQLite
- Sem breakdown atual, migrar 236M agregados mistura dívida e feature

**Why not recommended:** Usuário escolheu circuitos no topo. Fazer #2 agora deixa `prefer_websocket`, v2 e README mentindo.

---

### Approach C: “Painel verdadeiro” num ciclo só (higiene + hardware + grão horário)

**Description:** Docs + doctor + flash na mesa + migração SQLite no mesmo BUILD.

**Pros:**

- Uma passagem; o painel ficaria alinhado ponta a ponta

**Cons:**

- Três naturezas distintas (documental, hardware, schema)
- Quebra YAGNI e o fluxo um-comando-por-vez do SDD
- AT de hardware do alerta já está bloqueada no BUILD_REPORT (precisa do operador na mesa)

**Why not recommended:** Recorte inchado. P1 (`/ship` + hardware) e P2 (grão horário) ficam escritos no ranking, cada um com o próprio ciclo.

---

## Data Engineering Context (if applicable)

> O lote 1 **não** é pipeline. Esta seção existe porque o template exige; o P2 (grão horário) é que a preenche de verdade.

### Source Systems

| Source | Type | Volume Estimate | Current Freshness |
|--------|------|-----------------|-------------------|
| `usage_history` SQLite | SQLite local | 35 linhas / ~236M tokens agregados (35 dias) | Por ciclo do daemon (~5s) no dia corrente; histórico diário |
| Transcripts / rollouts / OpenCode SQLite / CC JSONL | arquivos locais | 4 provedores nesta máquina | Polling 5s |
| Event stores | JSON por sessão (último evento) | 62 chaves Claude; 0 Command Code | Hook-driven |

### Data Flow Sketch

```text
[Claude JSONL] ─┐
[Codex rollout]─┼→ [session_daemon] → POST /sessions → [ESP32 LVGL]
[OpenCode SQLite]┤                      ↘ usage_history (day, tokens)
[CC JSONL]     ─┘
```

Lote 1 **não** mexe neste fluxo, salvo o prune honrar `retention_days`.

### Key Data Questions Explored

| # | Question | Answer | Impact |
|---|----------|--------|--------|
| 1 | Há tabela horária? | Não. Uma tabela, duas colunas | `hourly_retention_days=365` é reserva, não feature |
| 2 | Os 32M/dia são bug? | **Unknown** — sem breakdown | Fora do lote 1; investigar no P2 |
| 3 | Quem consome o histórico? | Heatmap + pódio do firmware, via payload v1 | Mudar prune (35→30) só corta 5 dias fora da janela de 30 do card 7 |

---

## Selected Approach

| Attribute | Value |
|-----------|-------|
| **Chosen** | Approach A — ciclo de higiene, fechar circuitos |
| **User Confirmation** | 2026-09-19 (pergunta de abordagem + dois checkpoints de recorte/ranking) |
| **Reasoning** | Circuitos no topo; v2/chaves como reserva explícita (não apagar, não implementar); lote 1 sem hardware e sem schema horário |

---

## Key Decisions Made

| # | Decision | Rationale | Alternative Rejected |
|---|----------|-----------|----------------------|
| 1 | Artefato = backlog ranqueado; `/define` só o lote 1 | Pedido era análise/planejamento, não um único item | Um ciclo SDD só cobrindo tudo · só diagnosticar bugs |
| 2 | Topo = fechar circuitos, não dado novo | Mesma tese do ROADMAP 2026-09-07; evidência de docs/config órfãos nesta máquina | Começar pelo grão horário · investigar 32M/dia como P0 |
| 3 | v2 e chaves mortas = documentar e arquivar | Justificativa do v2 era multi-node (fora de escopo); apagar perde a reserva versionada; ligar seria feature | Remover `protocol_v2.py` · implementar endpoint / WebSocket / `daemon.role` |
| 4 | Retention entra no lote 1 | É a única desconexão config↔código com efeito no disco (35 linhas reais vs. default 30) | Tratar prune como "dado" e adiar |
| 5 | `/ship` + AT hardware = P1, não lote 1 | BUILD_REPORT_ALERTA já lista AT-005/009/014 como percepção visual; não é código | Incluir flash da mesa neste DEFINE |
| 6 | Totais 16–32M/dia = unknown, não bug P0 | Semântica CC já foi corrigida hoje (input−cacheRead); sem grão horário o denominador continua agregado | Root-cause agora contra transcripts |
| 7 | Sem firmware neste lote | Enum/ícone CC já estão no `.h` e no widget; higiene é docs/doctor/config/prune | Mexer em LVGL "por via das dúvidas" |

---

## Features Removed (YAGNI)

| Feature Suggested | Reason Removed | Can Add Later? |
|-------------------|----------------|----------------|
| Grão horário + breakdown (ROADMAP #2) | Não é circuito; é feature de dado; schema atual ainda serve o card 7 | Sim — P2 |
| Custo R$/US$ (#3) | Depende do breakdown; senão o denominador é inventado (precedente `quota.py`) | Sim — P3 |
| Tempo de agente bloqueado (#4) | Daemon já observa `ask`/`perm`; persistir é dado novo | Sim — P3 |
| Export CSV/JSON (#5) | Histórico hoje é só diário agregado | Sim — P4 |
| OTA (#6) | Partições reservadas, zero código; cabo USB dói mas não é higiene documental | Sim — P5 |
| Implementar protocolo v2 / WebSocket / `daemon.role` | Multi-node descartado; `prefer_websocket` nunca teve cliente | Sim, se o escopo mudar |
| Apagar `protocol_v2.py` e as chaves | Perde a reserva versionada e os 175 linhas de teste que documentam o contrato | Não neste ranking (arquivar ≠ apagar) |
| Painel web, Gemini CLI, Cursor, Aider, multi-node | Tier C / fora do single-machine | Não no roteiro atual |
| Redesenhar pódio / cards | Pódio de 4 colunas já foi feito no build CC | Não |
| Investigar 32M tokens/dia como bug | Sem breakdown é chute; CC já teve inflação 40× corrigida hoje | Sim, como spike no P2 |
| Instalar o hook CC nesta máquina | Ação do operador, não do DEFINE; o lote 1 só faz doctor/hooks check enxergarem o quarto provedor | Sim — P1 operacional |
| `/ship` das duas features construídas | Fase SDD distinta; AT de hardware exige a mesa | Sim — P1 |

---

## Incremental Validations

| Section | Presented | User Feedback | Adjusted? |
|---------|-----------|---------------|-----------|
| Recorte do lote 1 (docs, doctor, reservas, retention, hook/exemplo) | ✅ | "Sim, segue" | No |
| Ranking P0 higiene → P1 ship/hardware → P2 grão horário → resto ROADMAP | ✅ | "Sim, escreve o BRAINSTORM" | No |
| Abordagem A vs B vs C | ✅ | Confirmou A | No |
| YAGNI v2/chaves = arquivar no papel | ✅ | "Documentar e arquivar" | No |

**Minimum Validations:** 2 · **Completed:** 4

---

## Suggested Requirements for /define

Based on this brainstorm session, the following should be captured in the DEFINE phase:

### Problem Statement (Draft)

O repositório promete circuitos que o código não fecha (config sem consumidor, protocolo v2 sem endpoint, prune que ignora o toml) e documentos que descrevem um painel de 3 provedores com alerta binário — enquanto a máquina real já corre 4 provedores, alerta escalonado e um doctor que mente sobre v2.

### Target Users (Draft)

| User | Pain Point |
|------|------------|
| Operador desta mesa | `doctor` sai WARN em token/v2/hook CC mesmo com a placa no ar; README não menciona o quarto agente que ele acabou de integrar |
| Agente SDD no próximo ciclo | SPEC §3 e ROADMAP desatualizados viram grounding falso |
| Quem clona o repo | `EXAMPLE_TOML` omite `commandcode_context_window`; `--protocol 2` parece opção real |

### Success Criteria (Draft)

- [ ] README e SPEC descrevem 4 provedores, alerta escalonado (não "borda pulsante") e o enum `ToolType` igual ao `session_model.h`
- [ ] `monitor.py doctor` em máquina sem fixture **não** afirma coisa que não mediu (v2); `hooks check` inclui Command Code
- [ ] SPEC + `EXAMPLE_TOML` marcam `prefer_websocket`, `daemon.role`, `hourly_retention_days` e `--protocol 2` como **reserva sem consumidor / não-funcional**
- [ ] `usage_history.prune` honra `storage.retention_days` (default 30); teste cobre o valor do config, não a constante solta
- [ ] `EXAMPLE_TOML` lista `commandcode_context_window`; CLAUDE.md/README e doctor concordam na versão mínima do Python (hoje: docs dizem 3.10+, `doctor.py` exige 3.11, e `tomllib` é 3.11+)
- [ ] Suite `pytest tests/ -q` verde; `check_secrets.py` intocado em comportamento
- [ ] ROADMAP atualizado: item de higiene como ciclo; v2 permanece 🟡 reserva explícita, não "decisão pendente" ambígua

### Constraints Identified

- Tools PC só stdlib (Python; versão mínima a unificar no DEFINE)
- Protocolo `POST /sessions` aditivo — lote 1 **não** muda o contrato
- Não mover hooks (`session_hook.py` etc.)
- Sem implementar WebSocket, OTA, endpoint v2, schema horário
- Sem flash de firmware neste lote
- Convenção de teste: `unittest.TestCase` + `subTest`, não `pytest.mark.parametrize`
- Segredos: `_redact` continua mascarando token; DEFINE decide o caso length=0 (config show hoje imprime `***redacted***` para string vazia, doctor WARN "no transport token" — as duas saídas discordam)

### Out of Scope (Confirmed)

- Grão horário, custo R$, tempo bloqueado, export, OTA
- Implementar ou apagar protocolo v2 / `prefer_websocket` / `daemon.role`
- `/ship` e AT de hardware do alerta e do Command Code (P1)
- Root-cause dos totais diários de 16–32M tokens
- Instalar hook CC no `~/.commandcode/settings.json` do operador
- Multi-node, painel web, novos coletores (Gemini/Cursor/Aider)
- Qualquer mudança LVGL / `session_transport.cpp`

### Backlog ranqueado (para o ROADMAP; só P0 entra no DEFINE)

| Pri | Item | Natureza | Evidência |
|-----|------|----------|-----------|
| **P0** | Docs mentirosos (README 3 provedores, SPEC §3 enum antigo, título SPEC "Claude/Codex", alerta "pulsante", Python 3.10 vs 3.11) | bug documental | README:1-25 · SPEC:1-49 · doctor.py:142 · CLAUDE.md |
| **P0** | Doctor honesto (`check_protocol` só lê fixture; `hooks check` help text ainda diz "Claude and Codex") | bug | doctor.py:195-202 · run live 2026-09-19 · monitor.py:43 |
| **P0** | Config/v2 como reserva explícita | dívida | `prefer_websocket`/`role`/`hourly_retention` — grep só em config+teste; firmware sem `/api/v2/snapshot` |
| **P0** | `retention_days` manda no prune | débito config↔código | usage_history.py:26 = 35; toml = 30; SQLite = 35 rows |
| **P0** | Hook CC visível no doctor/CLI + `EXAMPLE_TOML` com `commandcode_context_window` | paridade | doctor WARN live; monitor_config.py:184-188 (campo já no dataclass, exemplo agora inclui — verificar no DEFINE se o arquivo em disco do usuário é o antigo) |
| P1 | `/ship` + AT hardware ALERTA_ESCALONADO | validação | BUILD_REPORT: AT-005/009/014 parciais; `daemon.err.log` já mostra `alerta: warning` |
| P1 | `/ship` COMMANDCODE_INTEGRATION + instalar hook CC nesta máquina | validação | event store CC ausente; BUILD_REPORT 279 testes + smoke real |
| P2 | Grão horário + breakdown (ROADMAP #2) | feature | schema real `(day, tokens)`; `hourly_retention_days` órfão |
| P3 | Custo R$/US$ (#3) | feature | depende de P2 |
| P3 | Tempo de agente bloqueado (#4) | feature | daemon já vê transições |
| P4 | Export CSV/JSON (#5) | feature | depois de P2+P3 |
| P5 | OTA (#6) | infra | `partitions.csv` reserva `ota_0`/`ota_1`; zero código |
| Arquivado | Implementar protocolo v2 | decisão | justificativa multi-node morta; fica reserva até pedido explícito |
| Fora | WebSocket, `daemon.role` ligado, multi-node, painel web, Gemini/Cursor/Aider | YAGNI | escopo single-machine / Tier C |

**Nota P0 token:** doctor WARN "no transport token" com `api_token=""` no toml; `config show` imprime `***redacted***` mesmo assim (`_redact` chaveia pelo **nome** do campo). Device `/health` respondeu sem token. DEFINE deve: (a) não tratar isso como "token existe", (b) não logar o valor.

---

## Session Summary

| Metric | Value |
|--------|-------|
| Questions Asked | 8 |
| Approaches Explored | 3 (A recomendada e confirmada) |
| Features Removed (YAGNI) | 12 |
| Validations Completed | 4 |
| Duration | sessão 2026-09-19 |
| Confidence da recomendação | 0.80 (codebase + amostras reais) |

---

## Next Step

**Ready for:** `/define .claude/sdd/features/BRAINSTORM_HIGIENE_CIRCUITOS.md`

O DEFINE captura requisitos **somente do P0**. P1–P5 e o arquivado ficam neste documento e devem ser copiados para `docs/ROADMAP.md` no BUILD do lote 1 (atualização de status, não execução).
