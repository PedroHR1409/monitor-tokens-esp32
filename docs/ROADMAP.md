# ROADMAP — Monitor.AI

> Planos de evolução. Decisões de design consolidadas vivem em [`SPEC.md`](SPEC.md);
> este documento diz **o que ainda vai ser feito, em que ordem e por quê**.
> Cada item vira um brief SDD em `.claude/sdd/features/` quando entra em execução.

Status: definido em 2026-09-07 · escopo **single-machine** · v0.3

---

## Como este roteiro nasceu

Uma varredura do repo procurando features novas encontrou, antes de qualquer ideia
nova, **capacidades já pagas pela arquitetura mas nunca ligadas**: campos declarados
em `monitor.toml` sem nenhum consumidor no código, um protocolo v2 completo e testado
sem endpoint no firmware, partições de OTA reservadas sem código de update. O roteiro
começa por fechar esses circuitos, e só depois adiciona dado novo.

## Decisões de escopo (2026-09-07)

| Decisão | Valor | Consequência |
|---|---|---|
| Topologia | **Single-machine** | Um PC, um painel. Multi-node sai do roteiro. |
| Alertas | **Só software** | Sem buzzer/LED novo; escalada usa display, cor e backlight. |
| Eixos priorizados | **Tier A (fechar circuitos) + Tier B (dado novo)** | Tier C (mais agentes, painel web) fica para depois. |

---

## Ordem de execução

| # | Item | Tier | Estado | Depende de |
|---|---|---|---|---|
| 1 | [Alerta escalonado + snooze](#1--alerta-escalonado--snooze-a1--b3) | A+B | 🟢 Construído (aguarda validação em hardware) | — |
| 2 | [Esquema de uso com grão horário e breakdown](#2--esquema-de-uso-com-grão-horário-e-breakdown-a4) | A | ⚪ Planejado | — |
| 3 | [Custo em R$/US$](#3--custo-em-rus-b1) | B | ⚪ Planejado | #2 |
| 4 | [Tempo de agente bloqueado](#4--tempo-de-agente-bloqueado-b2) | B | ⚪ Planejado | — |
| 5 | [Export do histórico](#5--export-do-histórico-b4) | B | ⚪ Planejado | #2, #4 |
| 6 | [OTA](#6--ota-a5) | A | ⚪ Planejado | — |
| 7 | [Protocolo v2: implementar ou arquivar](#7--protocolo-v2-implementar-ou-arquivar-a2) | A | 🔵 Arquivado como reserva (2026-09-19) | decisão #1 de escopo |
| 8 | [Command Code como quarto provedor](#8--command-code-como-quarto-provedor-tier-c) | C | 🟢 Construído | — |
| 9 | [Higiene: fechar circuitos](#9--higiene-fechar-circuitos-p0) | A | 🟢 Construído (aguarda `/ship`) | — |

Fora do roteiro atual: **multi-node (A3)** — descartado pelo escopo single-machine.
Adiado: **Tier C** — novos coletores (Gemini CLI, Cursor, Aider), painel web local
servido pelo daemon, foco de janela do terminal por toque no card. O Command Code
(item 8) saiu do Tier C por pedido direto e esta construido.

---

## 1 · Alerta escalonado + snooze (A1 + B3)

**Problema.** Um `perm` parado há 5 minutos é visualmente idêntico a um de 10 segundos.
O painel avisa que algo depende de você, mas não que já está esperando demais — e não
avisa nada se você não estiver olhando para a mesa.

**Evidência.** `tools/monitor_config.py:80-82` declara `warning_after_s = 90`,
`critical_after_s = 300` e `snooze_minutes = 15`. Nenhum consumidor no repo inteiro.
O firmware já tem `update_alert()` (`src/ui/ui_dashboard.cpp:1142`) e já recebe
`elapsed` por sessão.

**Escopo.** Escalada em níveis a partir dos limiares do `monitor.toml`; snooze por
toque; notificação nativa no PC (toast do Windows via PowerShell, `notify-send` no
Linux — ambos por `subprocess`, sem quebrar a regra de stdlib puro).

**Construído em 2026-09-08.** Artefatos: `.claude/sdd/features/{BRAINSTORM,DEFINE,DESIGN}_ALERTA_ESCALONADO.md`
e `.claude/sdd/reports/BUILD_REPORT_ALERTA_ESCALONADO.md`. Duas descobertas mudaram o
plano original: o alerta antigo **já** custava ~3 frames/s (a borda pulsava e invalidava
a tela), então a borda virou estática e o movimento migrou para o backlight; e a marca de
`perm` pode ficar órfã, então `expired` decai em 20 min para não virar pulso eterno.

**Decisões de design fixadas no brainstorm:**

- **Quem escalona é o daemon, não o firmware.** Se o firmware comparar `elapsed`
  contra limiares compilados, mudar `critical_after_s` passa a exigir reflash. O
  daemon calcula e envia um campo de severidade por sessão — aditivo ao contrato
  `POST /sessions`, respeitando a regra 3 do `CLAUDE.md`.
- **Modo noturno versus alerta crítico.** `BRIGHTNESS_NIGHT 60` escurece o painel a
  partir das 22h (`include/config.h:40-42`). Um `perm` crítico às 23h ficaria
  praticamente invisível: a escalada crítica precisa poder furar o dim.

## 2 · Esquema de uso com grão horário e breakdown (A4)

**Problema.** `usage_history` guarda apenas `(day, tokens)` — um total agregado por dia.
Isso impede qualquer análise mais fina que "quanto no dia inteiro".

**Evidência.** `tools/usage_history.py:29-30` (schema) e `storage.hourly_retention_days
= 365` declarado no config sem nenhum consumidor.

**Escopo.** Migração aditiva do schema para grão horário com breakdown por tipo de
token (input, output, reasoning, cache.write), preservando a semântica de consumo já
fixada no DEFINE. Destrava "hoje por hora" e comparação semana a semana no card 7.

**Nota de dívida encontrada:** `RETENTION_DAYS = 35` em `usage_history.py:26` contra
`retention_days: int = 30` no config — mesma família de desconexão config↔código do
item 1; corrigir junto.

## 3 · Custo em R$/US$ (B1)

**Problema.** O README promete mostrar "quanto eles custam em tokens", mas custo em
dinheiro é o número que as pessoas realmente entendem — e o painel nunca o mostra.

**Por que depende do item 2.** Input e output têm preços que diferem em ordem de
grandeza. Sobre o schema atual, que só guarda um total agregado, um custo histórico
seria um denominador inventado — exatamente o que `tools/quota.py` se recusa a fazer
com a cota do Claude. O breakdown persistido é pré-requisito, não conveniência.

**Escopo.** Tabela de preços por modelo declarada no `monitor.toml` (config, não
hardcoded — preço de modelo envelhece), custo por sessão, por dia e no pódio.
Encaixa no widget de consumo existente, sem UI nova.

## 4 · Tempo de agente bloqueado (B2)

**Problema.** O painel mede o custo dos agentes. Não mede o custo de **você** ser o
gargalo: quanto tempo por dia um agente ficou parado esperando sua resposta ou sua
aprovação.

**Por que é barato.** O daemon já observa todas as transições `ask`/`perm` a cada
ciclo. Falta apenas persistir a amostragem e agregar por dia.

**Escopo.** Série diária de "tempo bloqueado aguardando humano", por agente. Dado
inédito no projeto, e o mais original disponível no roteiro.

## 5 · Export do histórico (B4)

`python tools/monitor.py export` em CSV/JSON. Hoje todo o histórico morre dentro do
SQLite, sem caminho de saída. Faz mais sentido depois que houver grão horário (#2) e
tempo bloqueado (#4) para exportar.

## 6 · OTA (A5)

`partitions.csv` já reserva `ota_0`, `ota_1` e `otadata`, mas não existe nenhum código
de update no firmware — toda correção exige cabo USB. Invisível ao usuário final, mas
muda o custo de manter o projeto. Autenticação pelo mesmo `MONITOR_API_TOKEN`.

## 7 · Protocolo v2: implementar ou arquivar (A2)

**A situação.** `tools/protocol_v2.py` (233 linhas) mais `build_payload_v2` e a flag
`--protocol 2` existem e têm 175 linhas de teste, mas o firmware só registra
`/sessions`, `/health`, `/diag`, `/hidden` e `/pinned`
(`src/sessions/session_transport.cpp:539-545`). Rodar `--protocol 2` hoje bate em 404.

**Por que virou decisão.** A justificativa principal do envelope v2 era multi-node
(`nodes[]`, `node_id`), descartado pelo escopo single-machine. Restam `metric_quality`
e `composite_session_keys`, que não pagam sozinhos o custo do endpoint.

**As três saídas honestas:** implementar o endpoint no firmware; ou marcar o v2 na
SPEC como reserva versionada explícita, com a flag documentada como não-funcional; ou
remover. Deixar ambíguo é a pior das três — é código de produção que nada exercita
ponta a ponta.

**Decisão (2026-09-19, item #9): arquivar como reserva.** O `protocol_v2.py` e a flag
`--protocol 2` permanecem no repositório como reserva versionada, com os 175 linhas de
teste intactas; a SPEC §21 e o `tools/README.md` os declaram **sem consumidor funcional**
e o `doctor` deixou de sugerir uma verificação que não existe. Não foi implementado
(multi-node descartado) nem removido (perde a reserva e a documentação do contrato).

## 8 · Command Code como quarto provedor (Tier C)

**Problema.** O painel mostrava Claude, Codex e OpenCode — mas não o Command Code, que
roda na mesma máquina e já produz transcripts e hooks. Ele era invisível: nenhuma
sessão virava card, o consumo não entrava no heatmap e o total de tokens exibido ficava
incompleto.

**Escopo.** Paridade com os outros três: cards com estado, projeto/branch/modelo/effort,
tokens e contexto; cota estimada (consumo bruto); hooks instaláveis; ícone por provedor;
histórico e pódio.

**Construído em 2026-09-19.** Artefatos:
`.claude/sdd/features/{BRAINSTORM,DEFINE,DESIGN}_COMMANDCODE_INTEGRATION.md` e
`.claude/sdd/reports/BUILD_REPORT_COMMANDCODE_INTEGRATION.md`.

**Decisões de design fixadas no brainstorm/design:**

- **Hooks nativos + inferência de transcript.** O Command Code não tem
  `PermissionRequest`; `ask` vem de um `ask_user_question` pendente e `perm` da ausência
  de hook para um `tool_use` pendente (com teto de 600s). Um mod (`ModApi`) daria eventos
  mais ricos, mas exigiria um artefato e um caminho de install novos — ficou de fora.
- **Nunca lê `auth.json`.** O coletor só varre `projects/**/*.jsonl`; a API key do
  produto fica fora de qualquer caminho de código.
- **Fallback 422 generalizado.** O que antes só cobria `opencode` agora cobre qualquer
  `tool` fora de `{claude, codex}` — um provedor novo não repete o incidente.

**Resolvido em 2026-09-19** (a pedido do operador): o pódio do firmware passou de 3 para
4 colunas (`USAGE_PROVIDERS`), com o nome curto **"Command"**. O consumo dele já entrava
no heatmap e na cota.

## 9 · Higiene: fechar circuitos (P0)

**Problema.** O repositório prometia circuitos que o código não fechava e documentos
que descreviam um painel antigo: README e SPEC falavam de 3 provedores com alerta de
borda pulsante, enquanto `session_model.h` já tinha `COMMANDCODE`; o `doctor` avisava
que o protocolo v2 "não podia ser verificado" sem ter perguntado à placa; e
`usage_history.prune` ignorava `storage.retention_days`, decidindo o DELETE por uma
constante que divergia do `monitor.toml`.

**Escopo.** Docs de 4 provedores + alerta escalonado; Python unificado em 3.11+
(`tomllib` + `doctor` + CI já exigiam); `doctor` declara a reserva do v2 em vez de
fingir uma sonda; `hooks check` enxerga o Command Code; v2 e chaves órfãs documentadas
como reserva (sem apagar, sem ligar); `retention_days` passa a mandar no prune; token
vazio não é mais mascarado no `config show` (doctor e CLI contam a mesma história).
**Sem firmware, sem schema horário, sem endpoint v2.**

**Construído em 2026-09-19.** Artefatos:
`.claude/sdd/features/{BRAINSTORM,DEFINE,DESIGN}_HIGIENE_CIRCUITOS.md` e
`.claude/sdd/reports/BUILD_REPORT_HIGIENE_CIRCUITOS.md`.

**Decisões fixadas no design:**

- **Reserva, não remoção.** `protocol_v2.py` e as chaves órfãs permanecem; a SPEC §21 e
  o `tools/README.md` as declaram sem consumidor funcional.
- **Retenção encadeada.** `retention_days` viaja de `run(config)` por
  `build_payload_v1/v2` até `_record_daily_history` e `prune(keep_days=...)`; a
  constante `RETENTION_DAYS` caiu de 35 para 30, espelhando o default do config.
- **Dois canais, duas verdades.** `_redact` só mascara valor sensível não vazio.

**Fila priorizada (lotes seguintes).** P1: `/ship` das duas features construídas e a
verificação em hardware do alerta. P2: grão horário + breakdown (item #2). P3: custo
R$/US$ (#3), tempo de agente bloqueado (#4). P4: export (#5). P5: OTA (#6). Fora do
roteiro: WebSocket, `daemon.role` ligado, multi-node, painel web, Gemini/Cursor/Aider.
