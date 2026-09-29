# DEFINE: Histórico horário com breakdown

> Persiste o consumo horário por provedor e modelo, com componentes de tokens e total compatível com os números atuais.

## Metadata

| Atributo | Valor |
|---|---|
| Feature | HISTORICO_HORARIO |
| Data | 2026-09-27 |
| Autor | codex |
| Status | Implemented |
| Clarity Score | 14/15 |

## Problema

O SQLite guarda apenas um total agregado por dia. Isso impede consultas por hora e
separação confiável de tokens por modelo/tipo, que são pré-requisitos para a comparação
horária e o custo do item #3 do roadmap.

## Usuários

| Usuário | Papel | Necessidade |
|---|---|---|
| Operador | Usa o painel e o daemon | Consultar depois quanto foi consumido em cada hora/modelo |
| Mantenedor | Mantém coletores e schema | Evoluir os dados sem quebrar o histórico diário já exibido |

## Metas

| Prioridade | Meta |
|---|---|
| MUST | Persistir buckets por hora UTC, provedor e modelo em tabela nova e aditiva |
| MUST | Guardar input, output, reasoning, cache.write e total, preservando a semântica atual de consumo por provedor |
| MUST | Representar categoria não observável como `NULL`; total consumido permanece inteiro não negativo |
| MUST | Aplicar `storage.hourly_retention_days` (default 365) sem alterar `storage.retention_days` da tabela diária |
| MUST | Reprocessar eventos de forma idempotente e manter intactos a tabela diária e o payload atual |
| MUST | Backfill automático só preenche dias/buckets fechados ausentes; registros existentes são imutáveis e somente o período corrente é recalculado |
| SHOULD | Expor uma consulta Python ordenada por hora para consumidores futuros |

## Critérios de sucesso

- Cada chave `(hora UTC, provedor, modelo)` tem no máximo uma linha.
- Reprocessar os mesmos eventos produz os mesmos valores, sem duplicação.
- Reiniciar o daemon não altera registros de dias/horas fechados que já estavam persistidos.
- Soma dos `consumed_tokens` dos eventos reproduz o total atual por provedor, sem contar cache.read como consumo novo.
- Uma categoria ausente na fonte aparece como `NULL`, nunca como zero inventado.
- Prune remove buckets mais antigos que a retenção configurada; o prune diário continua obedecendo sua configuração atual.
- Buckets anteriores só são criados quando há timestamp de evento bruto; totais diários existentes não são distribuídos artificialmente.
- Nenhuma mudança no firmware, em `/sessions` ou em hardware é necessária para gravar/consultar o schema.

## Contrato de dados

| Coluna | Tipo | Regra |
|---|---|---|
| `hour_start_utc` | TEXT | ISO-8601 UTC, minuto/segundo zero |
| `provider` | TEXT | `claude`, `codex`, `opencode`, `commandcode` |
| `model` | TEXT | Identificador completo ou `unknown` |
| `input_tokens` | INTEGER nullable | Input consumido, sem cache.read; cache.write é separado quando mensurável |
| `output_tokens` | INTEGER nullable | Output conhecido pela fonte |
| `reasoning_tokens` | INTEGER nullable | Reasoning separado quando a fonte o reporta |
| `cache_write_tokens` | INTEGER nullable | Tokens de escrita em cache quando reportados |
| `consumed_tokens` | INTEGER NOT NULL | Semântica existente do provedor; não inclui releitura de cache |

Chave primária: `(hour_start_utc, provider, model)`. Valores conhecidos são não
negativos. Componentes podem não somar o total quando a fonte não expõe a separação;
`consumed_tokens` é a medida de compatibilidade.

## Escopo

**Inclui:** schema SQLite aditivo, normalização dos eventos disponíveis dos quatro
provedores, reprocessamento idempotente, retenção horária configurável e consulta
Python para faixa horária.

**Fora:** UI no painel, alteração do JSON HTTP, exportação, custo em dinheiro e
recuperação de eventos que já foram apagados da fonte.

## Restrições e contexto técnico

| Aspecto | Valor |
|---|---|
| Local | `tools/usage_history.py`, coletores em `tools/`, daemon e `docs/SPEC.md` |
| Runtime | Python 3.11+, stdlib; SQLite local |
| Hardware | Não necessário; sem alteração de firmware/protocolo |
| Retenção | `storage.hourly_retention_days`, default 365 |
| Semântica | Claude: input + output + cache.write; Codex: input não cacheado + output + reasoning + cache.write; OpenCode: input + output + reasoning + cache.write; Command Code: input sem cache.read + output, reclassificando cache.write sem dupla contagem quando houver campo |

## Assunções

| ID | Assunção | Impacto se falsa |
|---|---|---|
| A-001 | IDs/timestamps de evento atuais bastam para deduplicar cada fonte | Reprocessamento poderia inflar buckets |
| A-002 | Eventos sem componente separado permitem persistir o total sem inferir categoria | Breakdown incompleto, mas total permanece confiável |
| A-003 | Model ausente pode ser agrupado em `unknown` | Custo futuro não poderá atribuir esse bucket a uma tabela de preço |

## Clarity score

| Elemento | Nota | Observação |
|---|---:|---|
| Problema | 3 | Schema diário não sustenta análise horária |
| Usuários | 3 | Operador e mantenedor definidos |
| Metas | 3 | Retenção, chave e semântica mensuráveis |
| Sucesso | 3 | Idempotência e compatibilidade verificáveis |
| Escopo | 2 | A separação de algumas fontes depende dos campos reais disponíveis |
| **Total** | **14/15** | |

## Questões abertas

Nenhuma bloqueante. Campos ausentes permanecem `NULL`; não se tenta inferir uso que a
fonte não mediu.

## Revision History

| Versão | Data | Autor | Mudança |
|---|---|---|---|
| 1.0 | 2026-09-27 | codex | Requisitos derivados do item #2 do roadmap e do contrato existente de consumo |

## Estado final

**Implementacao concluida; veja DESIGN e o relatorio de build.**
