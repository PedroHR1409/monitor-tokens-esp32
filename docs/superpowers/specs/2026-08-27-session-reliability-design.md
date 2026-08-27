# Session Reliability Design

## Objetivo

Estabilizar o monitor sem inventar precisão: estados vêm de eventos estruturados,
identidade vem do ID completo da sessão e qualquer dado sem evidência recente é
apresentado como histórico/stale, nunca como estado atual.

## Causas-raiz confirmadas

- O Codex classifica `work`, `ask` e `free` apenas pela idade de `updated_at`.
- O Claude aceita timestamp sem timezone e transforma timestamp inválido em idade zero.
- O marcador de permissão é um mapa separado e expira por tempo, sem registrar a
  transição completa nem distinguir freshness do estado.
- IDs são truncados para 15 bytes no daemon, nos structs do firmware e na NVS.
- O ranking declara prioridade, mas ordena somente por `_age`.
- A tela de detalhes guarda o índice físico do slot, não a identidade da sessão.
- `s_liveDataReceived` nunca volta a falso e `UsageStats.valid` nunca expira.
- Cada POST renova o card mesmo quando a fonte local da sessão já está velha.
- A build de produção inicializa cinco sessões mockadas sem flag de demonstração.
- O segredo local já está separado em `include/secrets.h`, mas falta um exemplo
  versionável e uma verificação automatizada contra vazamento.

## Contrato de estados

- `work`: evento explícito de início/continuação de turno ou ferramenta em execução.
- `ask`: solicitação estruturada e pendente de input do usuário. Para Claude,
  `AskUserQuestion` sem `tool_result`; para Codex, somente um evento explícito do App
  Server ou integração equivalente. Hooks comuns não oferecem esse evento.
- `perm`: somente `PermissionRequest` explícito e ainda não resolvido.
- `free`: `Stop`, `SessionEnd`, turno concluído ou sessão sem trabalho pendente.
- `stale`: atributo ortogonal. Mantém o último estado como histórico, mas retira dele
  a validade operacional e visual.

O reducer rejeita eventos fora de ordem. Timestamp ausente, inválido ou sem timezone
não gera idade zero: produz diagnóstico por sessão e estado degradado/stale. Não há
timeout que converta trabalho em `ask` ou execução normal em `perm`.

## Fontes estruturadas

Claude preserva transcripts conversacionais para `AskUserQuestion` e usa hooks para
`PermissionRequest`, retorno de ferramenta e fim de turno. Codex usa hooks oficiais
`UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `Stop` e
`SessionEnd`, todos com `session_id`. O App Server expõe `tool/requestUserInput`, mas
adotá-lo como runtime completo nesta etapa seria uma mudança de integração ampla;
portanto Codex não anunciará `ask` sem essa evidência explícita.

## Persistência e concorrência

Um único event store por agente registra, por ID completo, estado, timestamp do evento,
sequência e encerramento. Escritas são atômicas. Eventos antigos não sobrescrevem os
novos. O daemon lê esse store defensivamente; dados corrompidos afetam somente a sessão
correspondente.

## Freshness

O payload registra `generated_at`, freshness por sessão e idade da fonte. O ESP32
registra último payload válido e última comunicação bem-sucedida. Após
`STALE_TIMEOUT_MS`, header, métricas e cards passam para stale/offline. O último valor
permanece visível como histórico, com rotulagem/cor inequívoca.

## Identidade e UI

IDs suportam UUIDs completos no daemon, payload, structs e NVS. Nome curto existe
somente em `update_session_card`. Ranking é `perm > ask > work > free`, depois recência,
com ordem anterior apenas como desempate. Detalhes guardam o ID; a cada atualização a
sessão é reencontrada. Se sumir, a tela fecha.

## Segurança e produção

`include/secrets.h` continua local e ignorado; `include/secrets.example.h` documenta
somente valores fictícios. Uma verificação compara valores sensíveis locais sem
imprimi-los e falha se aparecerem em arquivos versionáveis. Produção começa vazia;
mocks só existem com `MONITOR_DEMO_DATA=1` numa configuração de demo explícita.

## Limitações conscientes

- Sem consumir eventos do App Server, o Codex não produz `ask`; isso é degradação
  honesta, não uma regressão para heurística.
- Hooks precisam ser instalados/configurados pelo usuário para precisão máxima. O
  projeto fornece instalação idempotente, mas a execução de testes não altera a
  configuração viva do usuário.
- Testes automatizam o núcleo Python e contratos observáveis. A UI LVGL é validada por
  build e inspeção do fluxo porque o snapshot não possui harness nativo de display.
