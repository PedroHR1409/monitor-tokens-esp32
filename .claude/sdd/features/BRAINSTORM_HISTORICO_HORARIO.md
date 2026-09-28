# BRAINSTORM: Histórico horário com breakdown

## Metadata

| Atributo | Valor |
|---|---|
| Feature | HISTORICO_HORARIO |
| Data | 2026-09-27 |
| Status | Complete |

## Ideia e contexto

O item #2 do `docs/ROADMAP.md` pede persistir uso por hora e separar input, output,
reasoning e cache.write. Hoje `usage_history` guarda somente `(day, tokens)`. Há uma
faixa efêmera de 12h para Claude/Codex, mas não há persistência horária nem cobertura
uniforme dos quatro provedores. `storage.hourly_retention_days = 365` já existe sem
consumidor.

## Descobertas

| Pergunta | Evidência/decisão | Impacto |
|---|---|---|
| Como preservar os dados atuais? | A tabela diária é consumida pelo firmware; manter intacta e criar uma tabela aditiva | Nenhuma migração destrutiva nem quebra do payload atual |
| Como tratar categorias não reportadas? | Armazenar `NULL`, não zero; total consumido continua conhecido | Evita inventar breakdown para fontes incompletas |
| Qual granularidade identifica um registro? | Hora UTC + provedor + modelo | Evita colisões por fuso/DST e permite custo por modelo no item #3 |
| Como preencher dados antigos? | Recalcular apenas de eventos brutos disponíveis; nunca repartir total diário entre horas | Histórico sem transcript preserva o total diário, mas não ganha horas fabricadas |

## Abordagens

### A — Tabela horária aditiva por provedor/modelo (recomendada)

Cria linhas por hora UTC, provedor e modelo, com componentes nullable e total
consumido. Reusa os coletores existentes, aplica retenção própria e deixa a tabela
diária e o firmware como estão.

**Vantagens:** contrato diário preservado; histórico útil para análise e custo por
modelo; pode ser desenvolvido e usado sem a placa conectada.

**Trade-offs:** fontes antigas podem não expor todos os componentes/modelo; a
reconstrução depende dos arquivos brutos ainda existentes.

### B — Substituir o schema diário pelo horário

**Rejeitada:** força alteração de todos os consumidores existentes e torna a migração
mais arriscada do que o necessário.

### C — Persistir só a série móvel de 12h

**Rejeitada:** não atende retenção de 365 dias, não cobre quatro provedores e não permite
comparação histórica.

## Decisões fixadas

- A tabela nova usa a chave `(hour_start_utc, provider, model)`.
- `consumed_tokens` usa exatamente a semântica já implementada por cada coletor.
- Componentes ausentes ficam `NULL`; `model` ausente fica `unknown`.
- A tabela diária e o endpoint v1 permanecem inalterados nesta etapa.
- Sem UI, novo endpoint, preços ou mudança de firmware nesta feature.

## Estado final

**Concluido: requisitos e design implementados em HISTORICO_HORARIO.**
