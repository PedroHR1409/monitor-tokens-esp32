# BRAINSTORM: Integração com o Command Code

> Sessão exploratória para adicionar o Command Code como quarto provedor do painel,
> com paridade de funcionalidades em relação a Claude, Codex e OpenCode

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | COMMANDCODE_INTEGRATION |
| **Date** | 2026-09-19 |
| **Author** | brainstorm-agent |
| **Status** | ✅ Complete (Defined) |
| **Origem** | Pedido direto do usuário — "as mesmas funcionalidades que temos atualmente no Claude, Codex e OpenCode" |

---

## Initial Idea

**Raw Input:** "Crie a integração com o CommandCode também. Preciso que tenha as mesmas
funcionalidades que temos atualmente no Claude, Codex e OpenCode."

**Context Gathered:**

- O daemon hoje conhece **três** provedores, cada um com uma fonte de dados distinta:
  Claude por transcript JSONL + hooks (`scan_claude_sessions`, `session_daemon.py:246`),
  Codex por índice/rollouts + hooks com **cota oficial do servidor**
  (`scan_codex_sessions`, `session_daemon.py:346`), OpenCode por **SQLite local** sem hooks
  (`scan_opencode_sessions`, `tools/opencode_sessions.py:244`).
- O pipeline comum é estável: `build_payload_v1` concatena os coletores
  (`session_daemon.py:607-613`), resolve estado por `session_state.infer_state` +
  `agent_events.reduce_session_events`, monta ranking/severidade/catálogo e publica
  `POST /sessions`. `build_payload_v2` deriva de v1.
- O **Command Code** é a ferramenta em que esta sessão roda; a máquina já tem dados reais
  em `~/.commandcode/`.
- O Command Code guarda sessões em **JSONL por projeto**, sem SQLite:
  `~/.commandcode/projects/<slug>/<session-id>.jsonl` (+ `<id>.meta.json` e
  `<id>.checkpoints.jsonl`). Estrutura observada: header `{"type":"session","version":3,
  "id","timestamp","cwd"}` e entradas `{"type":"message","id","parentId","timestamp",
  "message":{"role","content[]"},"usage":{"inputTokens","outputTokens","cacheReadTokens",
  "cacheWriteTokens","costUsd"},"model","effort"}`.
- O Command Code **tem hooks nativos** em `~/.commandcode/settings.json`, com os eventos
  `SessionStart`, `PreToolUse`, `PostToolUse`, `Stop` — **não existe `PermissionRequest`**
  (é a diferença estrutural que mais afeta o estado `perm`).
- O Command Code tem a ferramenta de controle `ask_user_question` (sempre isenta de
  prompt) — sinal direto e determinístico de `ask`.
- O Command Code **não expõe cota oficial de servidor** (só o Codex expõe); cada mensagem
  traz `usage.costUsd`, mas o produto não publica um `used_percent`.
- O Command Code tem **mods** (plugins TS via `ModApi`) com catálogo de eventos
  (`tool_running`, `tool_completed`, `turn_end`, …) — alternativa mais rica, porém com
  artefato e caminho de instalação novos.

**Technical Context Observed (for Define):**

| Aspect | Observation | Implication |
|--------|-------------|-------------|
| Likely Location | `tools/` (collector + hook installer), `include/` + `src/sessions/` + `src/ui/` (enum/ícone) | Feature atravessa daemon e firmware, como o OpenCode |
| Relevant KB Domains | `python`, `testing` | Nenhuma das 24 domains cobre este domínio; a confiança vem do **codebase** (padrão OpenCode/Claude), não de KB |
| IaC Patterns | N/A | Projeto sem infraestrutura de nuvem |

---

## Discovery Questions & Answers

| # | Question | Answer | Impact |
|---|----------|--------|--------|
| 1 | O que conta como "mesmas funcionalidades"? | **Paridade total** — cards (estado/projeto/branch/modelo/effort/tokens/contexto), cota, hooks instaláveis, ícone, histórico e pódio | Define o escopo como espelho dos 3 provedores, não um coletor parcial |
| 2 | Como determinar `work`/`ask`/`perm`/`free` sem `PermissionRequest`? | **Hooks nativos + inferência de transcript** reusando `session_hook.py` + `agent_events` | Fixa a arquitetura de estado; `ask` vem de `ask_user_question`, `perm` por `tool_use` sem resultado e sem hook recente |
| 3 | Como representar a cota, se não há número oficial? | **Só consumo bruto, sem %** (igual OpenCode) | Reusa o bloco `quota` estimado; nada de percentual fabricado |
| 4 | De onde vêm as amostras? | **Fixtures dos transcripts reais** de `~/.commandcode/projects`, sanitizadas | Grounding do schema verdadeiro para o collector e os testes |

**Minimum Questions:** 3 · **Asked:** 4

---

## Sample Data Inventory

| Type | Location | Count | Notes |
|------|----------|-------|-------|
| Transcripts reais | `~/.commandcode/projects/<slug>/<id>.jsonl` | 3 projetos | Schema confirmado: header `type:"session"` + entradas `type:"message"` com `usage`/`model`/`effort`. Sessão mais recente: 88 linhas |
| Sidecars | `~/.commandcode/projects/<slug>/<id>.meta.json` / `<id>.checkpoints.jsonl` | por sessão | `meta.json` traz `title`/`traceIds`/`model`; checkpoints são do `/rewind` (fora de escopo) |
| Audit de hooks | `~/.commandcode/sessions/hooks-audit-<id>.jsonl` | 3 arquivos | Prova que hooks já disparam nesta máquina; formato `{timestamp, eventName, hookType, exitCode, toolName, ...}` |
| Config de hooks | `~/.commandcode/settings.json` | 1 | Já contém `hooks` (PreToolUse/PostToolUse/Stop) apontando para um wrapper PowerShell de terceiros — o installer precisa ser aditivo e idempotente |
| Código de referência | `tools/opencode_sessions.py`, `tools/session_hook.py`, `tools/agent_events.py`, `tools/session_state.py`, `tools/session_meta.py` | — | Padrões a reusar (collector puro, reducer determinístico, install idempotente) |
| Ground truth de transições | — | **0** | Não há histórico de transições de estado; a validação de `perm` será feita em uso |

**How samples will be used:**

- Cada transcript real vira fixture do collector (schema verificado, não inventado):
  um em `work`, um em `ask`, um com `usage` parcial (`cacheReadTokens=0`).
- `hooks-audit-*.jsonl` confirma o formato real do evento de hook para o teste de
  `hook_health`.
- `tools/opencode_sessions.py` é o modelo de collector puro e testável (`@dataclass` +
  leitura read-only); `agent_events.reduce_session_events` é reusado **sem alteração**.

**Lacuna registrada:** não há registro de quanto tempo uma permissão levou para ser
respondida — o mesmo vazio que o `ROADMAP.md` item #4 instrumenta. O tempo de `perm`
inferido será calibrado no uso, não medido de antemão.

---

## Approaches Explored

### Approach A: Espelhar o padrão do OpenCode (collector dedicado + hook installer) ⭐ Recommended

**Description:** Cria `tools/commandcode_sessions.py` (collector puro), estende
`tools/session_hook.py` para aceitar `provider=commandcode`, cria
`tools/install_commandcode_hook.py` (escreve em `~/.commandcode/settings.json`), adiciona
`ToolType::COMMANDCODE` + ícone e liga tudo em `build_payload_v1/v2`, histórico, pódio e cota.

**Pros:**
- Diff localizado; cada peça já tem um teste-espelho nos outros provedores.
- Reusa `session_hook.py`, `agent_events`, `session_state`, `session_meta`, `usage_model`.
- Respeita as regras duras (hooks em caminhos estáveis, tools stdlib, protocolo aditivo).

**Cons:**
- Mais um bloco quase-duplicado entre coletores; o daemon passa a conhecer 4 provedores hardcoded.

**Why Recommended:** menor risco e maior consistência com o repo. **Confiança 0.80** —
evidência é o padrão `opencode_sessions.py` + `install_codex_hook.py` do próprio repo;
nenhuma KB cobre este domínio.

---

### Approach B: Refatorar para um registry de provedores + Command Code como plugin

**Description:** Extrai uma interface comum (`scan`/`meta`/`usage`/`quota`/`hooks`) e
registra Claude/Codex/OpenCode/CommandCode.

**Pros:**
- Elimina a duplicação entre coletores; o 5º provedor vira configuração.

**Cons:**
- Refatora os 3 coletores existentes e mexe em ~13 arquivos de teste + os hooks já
  instalados; risco de regressão em provedores que funcionam.
- Over-engineering para o pedido (adicionar **um** provedor).

**Why not recommended:** paga dívida de arquitetura não solicitada dentro de uma feature de
integração.

---

### Approach C: Mod do Command Code postando direto no painel

**Description:** Um mod TS fala HTTP com a placa, sem o daemon.

**Pros:**
- Eventos ricos em tempo real (`tool_running`/`tool_completed`/`turn_end`).

**Cons:**
- Quebra a agregação do painel: ranking, dedup de token, anti-replay, histórico SQLite,
  cota, `hidden`/`pinned` e o guarda de instância única do daemon.
- Fragmenta a fonte de verdade.

**Why not recommended:** perde todo o histórico/pódio e duplica o escritor do painel.

---

## Data Engineering Context (if applicable)

**Não aplicável.** A feature não introduz pipeline, ETL nem fonte de dados nova: lê
arquivos locais de transcript e eventos, exatamente como os três coletores existentes. As
sub-seções de source systems/DAG/freshness não têm conteúdo honesto a receber e foram
deixadas vazias em vez de preenchidas com material inventado.

---

## Selected Approach

| Attribute | Value |
|-----------|-------|
| **Chosen** | Approach A |
| **User Confirmation** | 2026-09-19 ("Approach A (Recomendado)") |
| **Reasoning** | Menor risco, consistente com o padrão do repo; reusa a infraestrutura de hooks/estado/uso já testada |

---

## Spec consolidada (validada)

### Estados (daemon)

- **Hooks** (`~/.commandcode/settings.json`, via `session_hook.py commandcode <ação>`):
  `SessionStart→free`, `PreToolUse→work`, `PostToolUse→work`, `Stop→free`. Event store
  `~/.commandcode/monitor-ai-events.json` no mesmo schema dos demais
  (`{session_id, state, timestamp, event, tool, cwd}`).
- **`ask`**: último turno do assistente tem `tool_use` de `ask_user_question` sem
  `tool_result` correspondente (`QUESTION_TOOLS` estendido com `ask_user_question`).
- **`perm`**: último assistente com `tool_use` **sem** `tool_result` e **sem**
  `PreToolUse`/`PostToolUse` recente → aguardando aprovação; validade máxima de 600s
  (mesma cultura de `PERM_MARKER_MAX_AGE_S`). Passou disso, não afirma.
- **`work`/`free`**: evento estruturado manda; sem evento, recência
  (`WORK_MAX_AGE_S=1800`). Reusa `agent_events.reduce_session_events` sem alteração.

### Coletor (`tools/commandcode_sessions.py`)

Lê `~/.commandcode/projects/<slug>/<id>.jsonl`. O header `type:"session"` dá `id` e `cwd`;
as entradas `type:"message"` dão `model`, `effort` e `usage`. Produz o mesmo dicionário
dos outros coletores: `id, project, full, branch, model, effort, tokensWin, context,
context_tokens, tool="commandcode", state, elapsed, source_stale, diagnostic`.
Nome de exibição por `session_display_name`, branch por `read_git_branch(cwd)`, modelo por
`short_model`.

### Tokens e contexto

- **Tokens**: `inputTokens + outputTokens + cacheWriteTokens` (exclui `cacheReadTokens`, a
  mesma semântica de Claude e OpenCode), com dedup por `message.messageId`.
- **Contexto**: o transcript não traz a janela do modelo → `quality="estimated"` por
  tabela de modelo/config, ou `"unknown"` sem denominador.

### Cota

Consumo bruto na janela de 5h, `pct` fixo em 0 — idêntico ao bloco OpenCode
(`quota.py:259-263`).

### Firmware

`ToolType::COMMANDCODE` em `include/session_model.h`; `parse_tool` aceita `"commandcode"`;
ícone resolvido pelo `provider` (ex.: `deepseek` → ícone deepseek), com fallback no ícone
padrão. Firmware antigo rejeita com 422 → o daemon degrada (mesmo fallback já usado para
OpenCode).

### Ligação

`build_payload_v1/v2`, `collect_series`, backfill do histórico, `usage_top`,
`count_active_12h`, branch em `quota.collect`, checagem de path no `doctor`, arg CLI
`--commandcode-dir` (default `~/.commandcode/projects`), tag `CC` no `format_summary` e
rótulo em `hook_warnings`.

### Segurança

O collector lê **apenas** `projects/**/*.jsonl` — nunca `auth.json` (que contém a API key).
O installer de hooks é aditivo/idempotente e preserva os hooks de terceiros já presentes em
`settings.json`; `check_secrets.py` segue como guard-rail.

---

## Key Decisions Made

| # | Decision | Rationale | Alternative Rejected |
|---|----------|-----------|----------------------|
| 1 | Paridade total com os 3 provedores | Foi o pedido explícito do usuário | Coletor parcial (só tokens) |
| 2 | Estados por **hooks nativos + inferência de transcript** | Reusa `session_hook.py`/`agent_events`; sem artefato novo | Mod TS (artefato + trust novos); só transcript (perde `perm`) |
| 3 | `ask` por `ask_user_question` pendente | É o sinal determinístico que o produto oferece | Inferir `ask` por heurística de texto (frágil) |
| 4 | `perm` por ausência de `PreToolUse`/`PostToolUse` recente, com teto de 600s | Não há `PermissionRequest`; o teto segue o precedente de segurança do repo | Estender a marca indefinidamente (risco de `perm` eterno) |
| 5 | Tokens excluem `cacheReadTokens` | Mesma semântica já usada em Claude/OpenCode (evita inflação de re-leitura) | Somar tudo (infla o número) |
| 6 | Cota = consumo bruto, `pct=0` | O produto não publica número oficial; não fabricar percentual | Estimativa com orçamento (exigiria config nova) |
| 7 | Ícone pelo `provider`/fallback | O firmware já resolve ícone por provider | Gerar asset de marca novo (fora do MVP) |
| 8 | Coletor espelha o do OpenCode | Menor risco; consistência com o repo | Refatorar para registry de provedores |

---

## Features Removed (YAGNI)

| Feature Suggested | Reason Removed | Can Add Later? |
|-------------------|----------------|----------------|
| Mod TS com eventos ricos | Hooks nativos + inferência já cobrem os 4 estados | Yes |
| Custo (`costUsd`) no card/detalhe | Usuário escolheu só consumo; evita escopo novo de UI | Yes |
| Cota oficial de servidor | Não existe no produto (só Codex tem) | No |
| Janela de contexto medida | Transcript não traz a janela; fica estimada/unknown | Yes |
| Ícone de marca próprio | Provider/fallback resolve; exige asset PNG | Yes |
| Hooks em escopo de projeto | Regra 6: só escopo de usuário | No |
| Registry de provedores (Approach B) | Refatoração não solicitada, risco nos 3 atuais | Yes |
| Multi-máquina | Fora do escopo single-machine do projeto | No |
| Gerar token/credencial | O daemon nunca lê `auth.json` | No |

---

## Incremental Validations

| Section | Presented | User Feedback | Adjusted? |
|---------|-----------|---------------|-----------|
| Perguntas de descoberta (escopo, estados, cota, amostras) | ✅ | Paridade total, hooks+inferência, só consumo, fixtures reais | No |
| Seção 1 — Estados + coletor + cota | ✅ | "Sim, está certo" | No |
| Seção 2 — Firmware + ligação + YAGNI | ✅ | "Sim, está certo" | No |

**Minimum Validations:** 2 · **Completed:** 3

---

## Suggested Requirements for /define

### Problem Statement (Draft)

O painel mostra o que os agentes Claude, Codex e OpenCode estão fazendo, mas o Command
Code — que roda nesta máquina e já produz transcripts e hooks — é invisível: nem cards de
sessão, nem consumo no heatmap, nem posição no pódio.

### Target Users (Draft)

| User | Pain Point |
|------|------------|
| Operador do painel | Usa o Command Code e não vê suas sessões no painel, embora veja as dos outros agentes |
| Mesmo operador | O consumo do Command Code não entra no heatmap nem no pódio, distorcendo o total |

### Success Criteria (Draft)

- [ ] Uma sessão real do Command Code aparece como card com estado correto dentre `work`/`ask`/`perm`/`free`.
- [ ] O card mostra projeto, branch, modelo e effort conforme o transcript.
- [ ] `ask` é detectado quando há `ask_user_question` pendente; `perm` é detectado enquanto o `tool_use` está sem resultado e sem hook recente, e não persiste além de 600s.
- [ ] Hooks instalados por `install_commandcode_hook.py` em `~/.commandcode/settings.json`, de forma aditiva e idempotente, preservando hooks de terceiros; `doctor` e `hooks check` reportam saúde.
- [ ] Tokens do Command Code entram no consumo/histórico/pódio, sem duplicar (`cacheReadTokens` excluído, dedup por `messageId`).
- [ ] Firmware com `parse_tool("commandcode")` aceita o payload (2xx); firmware antigo degrada via fallback 422 sem derrubar o painel.
- [ ] O daemon nunca abre `~/.commandcode/auth.json`; `check_secrets.py` passa.
- [ ] Suíte pytest 100% verde, com fixtures derivadas dos transcripts reais.

### Constraints Identified

- Tools de PC: **só stdlib** (regra 2 do `CLAUDE.md`).
- `POST /sessions` **aditivo** (regra 3): enum novo só quebra firmware antigo, que é tratado pelo fallback.
- Hooks em caminhos estáveis (regra 4); installer deve preservar hooks existentes em `settings.json`.
- Serviço só em escopo de usuário (regra 6).
- Sem número oficial de cota — não inventar percentual.

### Out of Scope (Confirmed)

- Mod TS do Command Code; custo em US$; cota oficial; janela de contexto medida; ícone de marca próprio; hooks em escopo de projeto; refatoração para registry; multi-máquina; leitura de `auth.json`.

---

## Session Summary

| Metric | Value |
|--------|-------|
| Questions Asked | 4 |
| Approaches Explored | 3 |
| Features Removed (YAGNI) | 9 |
| Validations Completed | 3 |
| Key Decisions Recorded | 8 |

---

## Next Step

**Ready for:** `/define .claude/sdd/features/BRAINSTORM_COMMANDCODE_INTEGRATION.md`
