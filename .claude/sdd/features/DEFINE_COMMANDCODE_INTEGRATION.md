# DEFINE: Integração com o Command Code

> O painel passa a mostrar também as sessões do Command Code — estado, projeto, modelo,
> tokens e consumo — como já faz com Claude, Codex e OpenCode

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | COMMANDCODE_INTEGRATION |
| **Date** | 2026-09-19 |
| **Author** | define-agent |
| **Status** | ✅ Complete (Built) |
| **Clarity Score** | 15/15 |
| **Input** | `.claude/sdd/features/BRAINSTORM_COMMANDCODE_INTEGRATION.md` (`brainstorm_document`) |

---

## Problem Statement

O painel mostra o que os agentes Claude, Codex e OpenCode estão fazendo, mas o Command
Code — que roda nesta máquina e já produz transcripts e hooks — é invisível: nenhuma de
suas sessões vira card, seu consumo não entra no heatmap e ele não aparece no pódio, de
modo que o operador não sabe quando ele pergunta, espera aprovação ou trava, e o total de
tokens exibido está incompleto.

---

## Target Users

| User | Role | Pain Point |
|------|------|------------|
| Operador do painel | Roda os 4 agentes em paralelo na mesma máquina | O Command Code não aparece na grade: se ele fizer uma pergunta ou esperar aprovação, o operador só descobre pela janela do terminal |
| Operador revisando consumo | Mesmo operador, olhando o heatmap/pódio | O consumo do Command Code não é contabilizado, distorcendo o total diário e o ranking de agentes |

> Escopo single-machine, como o restante do projeto: há **um** operador em dois contextos
> de uso. A ausência de outras personas é uma restrição decidida, não lacuna de requisito.

---

## Goals

| Priority | Goal |
|----------|------|
| **MUST** | Coletar sessões do Command Code de `~/.commandcode/projects/<slug>/<id>.jsonl` e publicá-las como cards no `POST /sessions`, com `tool="commandcode"` |
| **MUST** | Derivar estado `work`/`ask`/`perm`/`free` por hooks nativos + inferência de transcript, sem inventar `ask`/`perm` sem evidência |
| **MUST** | Extrair por sessão: projeto, branch, modelo, effort, tokens da janela e contexto |
| **MUST** | Contabilizar tokens no consumo (histórico diário, heatmap e pódio), sem duplicar |
| **MUST** | Instalar os hooks em `~/.commandcode/settings.json` de forma aditiva e idempotente, preservando hooks de terceiros |
| **MUST** | Adicionar `ToolType::COMMANDCODE` ao firmware e degradar via fallback 422 em firmware antigo |
| **SHOULD** | Reportar a saúde dos hooks e do caminho no `doctor` / `monitor.py hooks` |
| **SHOULD** | Participar do ranking de ativos 12h e do catálogo como os demais provedores |
| **COULD** | Cota de consumo bruto (sem %) no bloco `quota`, como o OpenCode |

**Nota de prioridade.** A cota é `COULD` porque o Command Code não publica número oficial
de servidor; mesmo sem o bloco `quota`, o valor principal (ver a sessão e contar tokens)
está entregue. Os tokens no heatmap/pódio são `MUST` porque integridade do total é um dos
dois problemas do usuário.

---

## Success Criteria

- [ ] Uma sessão real do Command Code aparece como card com `tool=="commandcode"` e estado correto em **100%** dos casos observados (`work`/`ask`/`perm`/`free`).
- [ ] `ask` é detectado quando há `tool_use` de `ask_user_question` sem `tool_result` correspondente; **0** falsos `ask` por ferramentas que não sejam `ask_user_question`.
- [ ] `perm` inferido não persiste além de **600s**; passado o teto, o estado deixa de afirmar `perm` (nunca `perm` eterno).
- [ ] Tokens da janela usam `inputTokens + outputTokens + cacheWriteTokens`, com `cacheReadTokens` **excluído**; soma idêntica à dos outros provedores para o mesmo turno.
- [ ] **0** duplicações de token por mensagem (dedup por `message.messageId`), com contagem estável em releituras do mesmo arquivo.
- [ ] Hooks instalados em `~/.commandcode/settings.json` preservando **100%** dos hooks pré-existentes; reinstalar **não** duplica entradas (idempotente).
- [ ] `python tools/monitor.py doctor` e `hooks check` reportam o Command Code como instalado/ausente corretamente.
- [ ] Firmware com `parse_tool("commandcode")` aceita o payload (**2xx**); firmware antigo recebe **422** e o daemon reenvia **sem** o provedor, mantendo o painel ativo.
- [ ] O daemon **nunca** abre `~/.commandcode/auth.json`; `python tools/check_secrets.py` passa.
- [ ] Suíte pytest em **100%** de aprovação, com fixtures derivadas dos transcripts reais.

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | Sessão ativa aparece | Transcript com última mensagem assistente recente | Ciclo do daemon | Card criado com `tool="commandcode"`, projeto/branch/modelo/effort corretos |
| AT-002 | Estado `work` por hook | Hook `PreToolUse` gravou `work` no event store | Ciclo do daemon | Card em `work` com `elapsed` desde o evento |
| AT-003 | Estado `ask` | Último turno tem `tool_use` de `ask_user_question` sem `tool_result` | Ciclo do daemon | Card em `ask` |
| AT-004 | Estado `perm` | Último assistente tem `tool_use` sem `tool_result` e sem `PreToolUse`/`PostToolUse` recente | Ciclo do daemon | Card em `perm` |
| AT-005 | `perm` não eterno | Mesmo cenário do AT-004 | Idade do `tool_use` pendente ultrapassa 600s | Estado deixa de afirmar `perm` (cai para inferência/recência, nunca `perm` eterno) |
| AT-006 | `free` por `Stop` | Hook `Stop` gravou `free` | Ciclo do daemon | Card em `free` enquanto a recência permitir |
| AT-007 | Sem hook, só recência | Transcript recente, event store vazio | Ciclo do daemon | Estado nunca é `ask`/`perm` por inferência; no máximo `work` por recência |
| AT-008 | Tokens da janela | Mensagens com `inputTokens`/`outputTokens`/`cacheWriteTokens` e `cacheReadTokens>0` | Ciclo do daemon | `tokensWin` inclui os três primeiros e ignora `cacheReadTokens` |
| AT-009 | Dedup de token | Uma mensagem com `messageId` repetido em mais de uma linha | Cálculo de tokens | Token contado **uma** vez |
| AT-010 | Contexto estimado | Transcript sem janela de modelo | Ciclo do daemon | `context.quality` é `estimated` (com tabela/config) ou `unknown`; **0** percentuais fabricados |
| AT-011 | Install aditivo | `~/.commandcode/settings.json` com hooks de terceiros | `install_commandcode_hook.py` | Hooks de terceiros preservados; entradas do Monitor.AI adicionadas uma vez |
| AT-012 | Install idempotente | Hooks do Monitor.AI já instalados | Reexecutar o installer | **0** entradas duplicadas |
| AT-013 | Health no doctor | Par (script, agent) presente em `settings.json` | `doctor` / `hooks check` | Reporta `commandcode` instalado; ausente quando removido |
| AT-014 | Firmware compatível | Firmware com `parse_tool("commandcode")` | `POST /sessions` com sessão CC | **2xx**; card renderizado com ícone do provider |
| AT-015 | Firmware antigo (422) | Firmware sem suporte a `commandcode` | `POST /sessions` com sessão CC | **422**; daemon reenvia sem CC; painel continua atualizando |
| AT-016 | Não lê segredo | `~/.commandcode/auth.json` presente com `apiKey` | Qualquer ciclo do daemon | Arquivo nunca é aberto; nenhum segredo em payload/log |
| AT-017 | Histórico/pódio | Transcrições CC com tokens no dia | Backfill do histórico e cache do pódio | Tokens CC somam no dia e aparecem no ranking por provedor |
| AT-018 | Sessão encerrada sumiu | Event store marca `ended` para a sessão | Ciclo do daemon | Sessão é removida dos cards (mesma regra dos demais provedores) |

---

## Out of Scope

- Mod TS do Command Code com eventos ricos (`ModApi`) — os hooks nativos + inferência cobrem os 4 estados.
- Custo em US$ (`usage.costUsd`) no card ou no detalhe.
- Cota oficial de servidor do Command Code — o produto não publica `used_percent`.
- Medição da janela de contexto — o transcript não traz o denominador; fica estimada ou desconhecida.
- Ícone de marca próprio do Command Code — o ícone por `provider` resolve.
- Instalação de hooks em escopo de projeto (`.commandcode/settings.json`) — apenas escopo de usuário (regra 6).
- Refatoração dos coletores para um registry de provedores (Approach B do brainstorm).
- Agregação multi-máquina.
- Leitura de `auth.json` ou qualquer credencial em **qualquer** circunstância.
- Migração/limpeza dos hooks de terceiros já presentes em `settings.json`.

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Technical | Tools de PC só com **stdlib** (regra 2 do `CLAUDE.md`) | Leitura JSONL com `json`/`pathlib`; nada de dependência externa |
| Technical | `POST /sessions` **aditivo** (regra 3) | `"commandcode"` é valor novo de `tool`; firmware antigo não quebra o contrato, é tratado pelo fallback 422 |
| Technical | Hooks em caminhos estáveis (regra 4) | Os entrypoints continuam sendo `session_hook.py`; o path do script não muda |
| Technical | `~/.commandcode/settings.json` já contém hooks de terceiros | O installer deve ser aditivo, idempotente e preservar o que existe |
| Technical | O transcript não traz a janela de contexto | Qualidade `estimated`/`unknown`, nunca percentual fabricado |
| Technical | `~/.commandcode/` contém `auth.json` com API key | O collector lê apenas `projects/**/*.jsonl`; `check_secrets.py` é o guard-rail |
| Technical | Datas no transcript em ISO/UTC; dias do painel em fuso local | Converter para o fuso do daemon antes de agregar por dia |
| Scope | Single-machine | Sem agregação entre nós |

---

## Technical Context

| Aspect | Value | Notes |
|--------|-------|-------|
| **Deployment Location** | `tools/` (collector + hook installer + wiring); `include/` e `src/sessions/`, `src/ui/` (enum/ícone) | Espelha o precedente do OpenCode: daemon + firmware |
| **KB Domains** | `python`, `testing` | Nenhuma das 24 domains cobre este domínio. A confiança vem do **codebase** (padrões de `opencode_sessions.py`, `install_codex_hook.py`, `session_hook.py`), não de KB — o Design não deve esperar padrão de KB aqui |
| **IaC Impact** | None | Projeto sem infraestrutura de nuvem |

---

## Data Contract (if applicable)

**Não aplicável.** A feature não introduz pipeline, ETL nem fonte de dados nova: lê
arquivos locais de transcript e eventos, como os três coletores existentes. As sub-seções
de source inventory, schema contract, freshness SLA, completeness e lineage não têm
conteúdo honesto a receber e foram deixadas vazias em vez de preenchidas com material
inventado.

**Inventário de entrada (não é contrato de dados):**

| Fonte | Tipo | Volume | Observação |
|-------|------|--------|------------|
| `~/.commandcode/projects/<slug>/<id>.jsonl` | JSONL local | 3 projetos hoje; 1 sessão/arquivo | Header `type:"session"` + entradas `type:"message"` |
| `~/.commandcode/monitor-ai-events.json` | JSON local (novo) | 1 registro/sessão | Event store dos hooks, mesmo schema dos demais provedores |
| `~/.commandcode/settings.json` | JSON local | 1 | Alvo do installer; já contém hooks de terceiros |

---

## Assumptions

| ID | Assumption | If Wrong, Impact | Validated? |
|----|------------|------------------|------------|
| A-001 | O schema do transcript (`type:"session"`/`type:"message"`, `usage`, `model`, `effort`) é estável | O collector para de reconhecer sessões; precisaria de adaptação de versão (`version:3`) | [x] **Sim** — verificado em 3 transcripts reais em 2026-09-19 |
| A-002 | Hooks de usuário vivem em `~/.commandcode/settings.json` e podem coexistir com os de terceiros (precedência usuário < projeto; acúmulo por evento) | O installer sobrescreveria config alheia | [x] **Sim** — arquivo real inspecionado; doc de hooks confirma escopo e precedência |
| A-003 | `PreToolUse`/`PostToolUse` **não** disparam enquanto a chamada aguarda aprovação, de modo que a ausência de hook recente com `tool_use` pendente significa `perm` | `perm` nunca seria detectado corretamente (marcaria `work`); a inferência precisaria de outro sinal | [ ] **Não** — é o principal risco e a razão do teto de 600s; calibrar em uso |
| A-004 | A ferramenta `ask_user_question` aparece como bloco `tool_use` no transcript quando o agente pergunta | `ask` não seria detectado pela via determinística | [x] **Sim** — documentado na referência de permissões/tools do produto |
| A-005 | Firmware sem `parse_tool("commandcode")` rejeita o POST inteiro com 422 | O daemon precisaria de outra estratégia de degradação | [x] **Sim** — `session_transport.cpp:355` rejeita `ToolType::UNKNOWN` com 422 |
| A-006 | Há no máximo uma linha por mensagem com `usage`, dispensando dedup complexa | Contagem de tokens inflaria | [ ] **Não** — a dedup por `messageId` é defensiva de baixo custo; validar contra os transcripts reais |
| A-007 | O Command Code não expõe cota oficial de servidor | Se expusesse, o bloco `quota` poderia ser oficial em vez de estimado | [x] **Sim** — referência de planos/modelos não publica `used_percent` |

**Nota:** A-003 e A-006 são os riscos vivos. A-003 não bloqueia o Design (a inferência e o
teto já estão definidos), mas deve ser validado em uso antes do `ship`.

---

## Clarity Score Breakdown

| Element | Score (0-3) | Notes |
|---------|-------------|-------|
| Problem | 3 | Uma frase, com quem sofre (operador que roda 4 agentes), o mecanismo (provedor invisível na grade e no total) e o impacto (pergunta/aprovação percebidas só no terminal) |
| Users | 3 | Um operador em dois contextos com dores distintas (sessão ao vivo vs. consumo); a persona única é restrição decidida e documentada |
| Goals | 3 | 9 metas com MoSCoW e a razão do `COULD` da cota explicitada |
| Success | 3 | 10 critérios, todos com número, contagem ou estado observável (100%, 0, 600s, 2xx/422) |
| Scope | 3 | 11 exclusões explícitas herdadas do YAGNI, incluindo a proibição total de ler credenciais |
| **Total** | **15/15** | |

**Por que 15 e não menos.** O input era um `brainstorm_document` com 8 decisões já
registradas e 3 validações do usuário; a nota reflete isso, não ausência de risco. O risco
está concentrado no registro de suposições — **A-003** (ausência de hook como sinal de
`perm`) segue não validada e é a única que pode reduzir a fidelidade de um estado.

---

## Open Questions

Nenhuma bloqueante para o Design. Para o Design resolver (decisões de arquitetura, não
lacunas de requisito):

- Onde vive a tabela de janela de contexto por modelo (`commandcode_context_window` em config vs. constante) e os valores iniciais.
- Nome exato do arquivo de event store e a forma como `session_hook._default_path` distingue `commandcode`.
- Como o installer reconcilia os hooks de terceiros por evento (append por evento vs. grupo único) mantendo idempotência.
- Se o `perm` inferido participa da severidade/alerta escalonado como os demais estados (`alert_severity.py`).
- Tag de log (`CC`) e rótulo de aviso de hook a usar em `format_summary`/`hook_warnings`.

---

## Contract Gate

`tools/spec-linter/` **não existe neste repositório** — o componente referenciado pelo
`contract_enforcement` do `WORKFLOW_CONTRACTS.yaml` e pelo skill `sdd-define` não está
presente. Conforme o `exit_code_contract` do próprio contrato, linter indisponível equivale
a **exit 2 (ERROR)**, cuja regra é *"record a VISIBLE skip and proceed — never assume PASS
on exit 2"*.

- **Verdict:** não obtido (linter ausente).
- **Ação:** skip registrado visivelmente; conformidade verificada manualmente contra as 12 seções obrigatórias do template — todas presentes.
- **Nunca assumido:** PASS.

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-09-19 | define-agent | Versão inicial, extraída de `BRAINSTORM_COMMANDCODE_INTEGRATION.md`; 6 suposições registradas (4 validadas contra código/produto, 2 abertas); sem lacunas de requisito a fechar |

---

## Next Step

**Ready for:** `/ship .claude/sdd/features/DEFINE_COMMANDCODE_INTEGRATION.md`
