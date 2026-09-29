# BUILD REPORT: Histórico horário com breakdown

## Metadata

| Atributo | Valor |
|---|---|
| Feature | HISTORICO_HORARIO |
| Data | 2026-09-27 |
| Autor | codex |
| DEFINE | [DEFINE_HISTORICO_HORARIO.md](../features/DEFINE_HISTORICO_HORARIO.md) |
| DESIGN | [DESIGN_HISTORICO_HORARIO.md](../features/DESIGN_HISTORICO_HORARIO.md) |
| Status | Implementação concluída; validação funcional aprovada no follow-up de 2026-09-29 |

## Resumo

Foi adicionada a tabela SQLite `usage_history_hourly`, com agregação UTC por provedor e
modelo e breakdown nullable. Os coletores de Claude, Codex, OpenCode e Command Code
fornecem eventos detalhados; o daemon atualiza a janela atual no máximo a cada minuto e
aplica `storage.hourly_retention_days`. A tabela diária, o payload HTTP e o firmware
permanecem compatíveis. Backfills de reinicialização preenchem períodos fechados
ausentes, mas não substituem dias ou horas já persistidos.

| Métrica | Resultado |
|---|---|
| Tarefas concluídas | 5/5 |
| Arquivos criados nesta feature | 4 (3 SDD + este relatório) |
| Arquivos existentes modificados | 9 |
| Agentes delegados | 0 |

## Execução

| # | Tarefa | Estado | Resultado |
|---:|---|---|---|
| 1 | Normalizar eventos detalhados dos quatro provedores | Concluída | Dedup, deltas cumulativos e campos disponíveis por fonte |
| 2 | Criar schema e operações horárias SQLite | Concluída | Upsert idempotente, consulta de faixa e prune UTC |
| 3 | Ligar atualização ao daemon e configuração de retenção | Concluída | Atualização limitada a 60s; erros da tabela não interrompem o payload |
| 4 | Atualizar SPEC, mapa de ferramentas e roadmap | Concluída | Contrato e status do item #2 documentados |
| 5 | Registrar resultado SDD | Concluída | Relatório criado; status dos artefatos atualizado |

## Arquivos modificados

| Arquivo | Mudança |
|---|---|
| `tools/usage_model.py` | Tipo imutável `UsageBreakdown` |
| `tools/usage_tracker.py` | Eventos detalhados Claude/Codex, dedup e deltas |
| `tools/opencode_sessions.py` | Eventos por turno sem alterar o contrato diário |
| `tools/commandcode_sessions.py` | Breakdown por mensagem com semântica de cache preservada |
| `tools/usage_history.py` | Tabela, backfill, consulta e retenção horária |
| `tools/session_daemon.py` | Atualização periódica e propagação de `hourly_retention_days` |
| `docs/SPEC.md` | Contrato do histórico horário |
| `tools/README.md` | Mapa da persistência e configuração ativa |
| `docs/ROADMAP.md` | Item #2 marcado como construído |

## Verificação

| Verificação | Resultado |
|---|---|
| Parse estático dos seis módulos Python alterados | Passou |
| `git diff --check` | Passou |
| Suíte funcional no build original | Não executada naquela etapa; follow-up posterior aprovado |
| Scanner de segredos no build original | Não executado naquela etapa; follow-up posterior aprovado |
| Firmware no build original | Fora do escopo daquela etapa; compilação posterior aprovada |

Validação posterior executada em 2026-09-29 neste ramo: `python -m pytest tests/ -q`
aprovou 309 testes e 36 subtestes; `python -m compileall -q tools tests` e
`python tools/check_secrets.py` também passaram. A compilação de firmware foi executada
com `python -m platformio run -e esp32-s3-3v5-lcd` e passou.

## Próximo uso

Os buckets horários podem seguir para o item #3 do roadmap (custo por modelo). A
validação acima cobre os contratos automatizados; não substitui a validação física do
painel.

## Correção de estabilidade após merge

O primeiro ciclo do daemon usava `replace_existing=True` no backfill diário. Como o
backfill parte apenas dos arquivos ainda disponíveis, reiniciar podia substituir os
totais de dias anteriores por uma leitura parcial. O daemon agora usa inserção apenas
para dias ausentes. No histórico horário, somente a hora UTC corrente é atualizada por
upsert; horas fechadas preservam os valores existentes.
