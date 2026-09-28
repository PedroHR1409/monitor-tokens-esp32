# DESIGN: Histórico horário com breakdown

> Persistência aditiva de eventos de consumo por hora, provedor, modelo e componente.

## Metadata

| Atributo | Valor |
|---|---|
| Feature | HISTORICO_HORARIO |
| Data | 2026-09-27 |
| Autor | codex |
| DEFINE | [DEFINE_HISTORICO_HORARIO.md](./DEFINE_HISTORICO_HORARIO.md) |
| Status | Build Complete |

## Arquitetura

```text
transcripts Claude ─┐
rollouts Codex ──────┤  eventos normalizados  ┌──────────────────────┐
SQLite OpenCode ────┼────────────────────────►│ usage_history_hourly │
JSONL Command Code ─┘                          └──────────┬───────────┘
                                                         │
                                            hourly_range(start, end)

usage_history(day, tokens) e payload v1 permanecem inalterados.
```

## Componentes

| Componente | Responsabilidade |
|---|---|
| `usage_model.py` | Tipo imutável de breakdown normalizado por evento |
| `usage_tracker.py` | Eventos detalhados de Claude/Codex, dedup e deltas cumulativos |
| `opencode_sessions.py` | Eventos por turno e campos `input/output/reasoning/cache.write` |
| `commandcode_sessions.py` | Eventos por mensagem, respeitando cache.read e cache.write |
| `usage_history.py` | Schema, upsert, backfill, consulta e prune horários |
| `session_daemon.py` | Integra retenção e gravação periódica sem alterar payload |

## Decisões

### 1. Tabela separada e compatível

`usage_history_hourly` tem colunas `hour_start_utc`, `provider`, `model`, `input_tokens`,
`output_tokens`, `reasoning_tokens`, `cache_write_tokens` e `consumed_tokens`.
`PRIMARY KEY(hour_start_utc, provider, model)`. Componentes aceitam `NULL`; o total é
sempre inteiro não negativo. Um índice em `hour_start_utc` atende janela e prune.

### 2. Hora canônica UTC

Eventos são convertidos para o início UTC da hora. A camada que apresentar os dados
converte para o fuso configurado. Isso evita chaves ambíguas quando o offset local
muda.

### 3. Breakdown sem alterar o total

Cada coletor calcula `consumed_tokens` com a mesma regra já usada nos cards/histórico.
Codex calcula deltas dos contadores cumulativos, incluindo reset. Claude deduplica por
`message.id`; OpenCode por linha de mensagem; Command Code por `messageId`. Cache.read
não vira consumo. Categorias indisponíveis são `NULL`. Quando Command Code fornece
cacheWrite como subconjunto de input, o breakdown separa essa parte de input e a soma
novamente em `cache_write_tokens`, sem alterar o total legado.

### 4. Backfill e atualização idempotentes

Backfill inicial/forçado percorre até 30 dias (`min(hourly_retention_days,
usage_history.WINDOW_DAYS)`) e agrupa eventos por chave horária. Isso preserva a janela
já usada pelo backfill diário e evita uma varredura anual no startup. No daemon ativo,
a janela do dia corrente é recalculada no máximo a cada 60s. Um `UPSERT` substitui o
agregado daquela chave, em vez de somar novamente o resultado de cada varredura.
Buckets persistidos sem evento retornado não são apagados, para que rotação de
transcripts não destrua histórico já gravado. As linhas se acumulam até a retenção
configurada, limitada a 365 dias por default.

### 5. Retenção própria

`hourly_retention_days` chega ao prune horário sem reutilizar o limite diário de
`retention_days`. O default direto do módulo espelha `StorageSettings`.

## Fluxo

1. Cada coletor produz evento `{at, provider, model, input, output, reasoning, cache_write, consumed}`.
2. A camada de histórico valida/clampa valores e arredonda `at` ao início UTC da hora.
3. Eventos são agregados por `(hour_start_utc, provider, model)`.
4. SQLite faz upsert em transação; o daily table segue o caminho atual.
5. O daemon atualiza o dia no máximo a cada 60s, aplica prune com `hourly_retention_days`
   e encerra a conexão.

## Manifesto de arquivos

| # | Arquivo | Ação | Propósito |
|---:|---|---|---|
| 1 | `tools/usage_model.py` | Modificar | Tipo normalizado de evento de breakdown |
| 2 | `tools/usage_tracker.py` | Modificar | Eventos Claude e deltas Codex por componente |
| 3 | `tools/opencode_sessions.py` | Modificar | Eventos detalhados por turno |
| 4 | `tools/commandcode_sessions.py` | Modificar | Eventos detalhados por mensagem |
| 5 | `tools/usage_history.py` | Modificar | Tabela, backfill, consulta, retenção |
| 6 | `tools/session_daemon.py` | Modificar | Agendar escrita horária e propagar config |
| 7 | `docs/SPEC.md` / `tools/README.md` | Modificar | Registrar contrato e consumidor Python |

**Fora do manifesto:** firmware, `POST /sessions`, UI, testes novos. A validação de
hardware não se aplica a esta etapa.

## Tratamento de erros

| Erro | Tratamento |
|---|---|
| Transcript/DB de origem ausente | Ignorar essa fonte e manter buckets persistidos |
| JSON inválido ou linha parcial | Ignorar evento inválido conforme coletores existentes |
| Timestamp/model ausente | Evento sem timestamp é descartado; modelo vira `unknown` |
| Campo de token inválido/negativo | Usar zero somente para campo medido inválido; campo não reportado fica `NULL` |
| Banco ocupado | Respeitar timeout SQLite curto e falhar sem interromper o payload atual |

## Estratégia de validação

- A analise estatica de sintaxe passou para os seis modulos Python alterados.
- `git diff --check` passou.
- A suite funcional e o scanner de segredos nao foram executados nesta etapa.
- Sem upload, painel ou validacao visual nesta feature.

## Revisões

| Versão | Data | Autor | Mudança |
|---|---|---|---|
| 1.0 | 2026-09-27 | codex | Design aditivo a partir do DEFINE |

## Estado final

**Build concluido; detalhes em `../reports/BUILD_REPORT_HISTORICO_HORARIO.md`.**
