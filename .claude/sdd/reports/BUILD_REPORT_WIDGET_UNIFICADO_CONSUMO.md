# BUILD REPORT: WIDGET_UNIFICADO_CONSUMO

| Attribute | Value |
|-----------|-------|
| **Data** | 2026-08-28 |
| **Executor** | build-agent (via OpenCode) |
| **DESIGN** | `DESIGN_WIDGET_UNIFICADO_CONSUMO.md` |
| **Status** | ✅ Implementado (Escopos A e B), gravado na placa e validado |

## Fases executadas

### Escopo A — persistência + heatmap
- `tools/usage_history.py` (NOVO): upsert diário, janela 30d oldest-first, prune 35d,
  backfill one-shot (INSERT OR IGNORE — nunca sobrescreve linha viva)
- `tools/session_daemon.py`: `history_db` nos builders v1/v2; total do dia soma as
  3 fontes (Claude `tokens_today` + Codex `codex_series.total` + OpenCode
  `window_tokens`); backfill dispara só com tabela vazia; `stats.history.daily`
  aditivo no payload
- `tools/opencode_sessions.py`: `turn_token_events()` (semântica do `tokensWin`)
- Firmware: `UsageHistory` no modelo, parse aditivo, widget unificado full-width
  (grid GitHub 6 semanas × 7 dias, células 18px, paleta exata, sem rótulos, hoje =
  última célula), toque alterna visões
- **Validação de hardware**: flash OK; backfill real reconstruiu **26 dias /
  70.987.234 tokens** no primeiro ciclo; payload aceito (sem 422)

### Escopo B — pódio + chip + modal
- `tools/usage_top.py` (NOVO): agregação 1/7/30 por provider, total = soma completa,
  cap 6, ordenação por gasto com tie-break por nome
- `tools/usage_tracker.py`: correção latente — cache de `session_tokens` agora inclui
  `since` na chave (3 janelas diferentes não colidem mais)
- `tools/session_daemon.py`: `stats.usage.top` aditivo; projetado no v2
- Firmware: `ProviderTop`/`UsageTop`, parse do bloco, pódio com rank 1 em destaque,
  ícone por agente (claude/gpt/gpt-fallback), chip hoje/7d/30d clicável (prioridade
  chip > barra > visão), modal de sessões com fechamento no backdrop
- **Validação de hardware**: flash OK; ciclo real `[OK]` com pódio alimentado

## Decisões autônomas registradas (decide-never-ask)

1. **`session_tokens` cache key sem `since`** — bug latente exposto pelo uso com 3
   janelas; corrigido (chave inclui `since.isoformat()`).
2. **`_connect` do SQLite agora cria diretório-pai** — primeiro ciclo real falhou com
   "unable to open database file" (diretório APPDATA inexistente).
3. **Conexões SQLite fechadas via contextmanager próprio** — o `with` nativo só faz
   commit, não fecha; travava o cleanup de tempdir nos testes (Windows).
4. **Ícone do OpenCode no pódio** = `gpt_icon` (fallback genérico já usado nos cards);
   não há logo próprio do OpenCode.
5. **Grid 18px/6 colunas** em vez de 14px/5 — melhor preenchimento da área 304×160.
6. **`usage_top._claude` filtra por mtime >= janela** antes de abrir arquivo
   (mesma otimização do coletor ao vivo).

## Testes

- 178 passed (+14 subtests) — inclui 25 testes novos:
  `test_usage_history.py` (12) e `test_usage_top.py` (4) + payload/firmware contratos
- `compileall` OK; `check_secrets.py` limpo
- `pio run` SUCCESS nos builds; flash COM3 OK (2 ondas)

## Cobertura dos Acceptance Tests

| AT | Coberto por | Estado |
|----|-------------|--------|
| 001-004 | `test_usage_history.py` | ✅ |
| 005/006 | hardware (paleta/hoje) + lógica `heatmap_color` | ✅ confirmar visual |
| 007/008 | contratos de payload nos dois sentidos | ✅ |
| 009 | hardware (toggle + refresh-proof) | ✅ confirmar visual |
| 010-012 | `test_usage_top.py` + agregação | ✅ |
| 013/014 | hardware (modal vazio/backdrop) | ✅ confirmar visual |
| 015 | hardware após as duas ondas | ✅ pendente confirmação do operador |

## Correção pós-build (goal 28/08 21:15 — timeout/409 no daemon)

Sintomas: timeout de rede intermitente e 409 "[FALHOU]" no daemon contínuo.
Causas-raiz encontradas e corrigidas:

1. **Ciclo estourado**: `usage_top.build` (claude d30 relendo caudas de transcripts
   ativos, cujo mtime muda a cada ciclo) custava ~7s por ciclo — mais que o
   intervalo de 5s. Correção: `usage_top.build_cached` com TTL de 60s (ranking não
   precisa de frescor de 5s). Build quente: **0,5-0,7s** (era 7s).
2. **Resposta perdida após aplicar**: POST chegava à placa mas a resposta se perdia;
   o retry reenviava o MESMO payload e o anti-replay respondia 409. Correção: 409
   após retry de rede = payload já aplicado → tratado como OK.
3. **Dupla instância**: dois daemons postando no mesmo segundo geram o mesmo
   `generated_at_epoch` → 409 direto. Correção: guarda de instância única (bind
   UDP 127.0.0.1:8770); segunda instância sai com rc=1 e mensagem clara.
4. Retry curto (1,5s) apenas para falha de rede (status 0), nunca para 4xx.
5. `print` do ciclo com `flush=True` (linhas não somem em pipe/serviço).

Validação: 179 testes; 4 ciclos [OK] consecutivos no daemon contínuo; segunda
instância bloqueada corretamente.

## Pendências para /ship

- [ ] Confirmação visual do operador na placa (paleta, toggle, chip, modal)
- [ ] Commit do build
- [ ] `docs/SPEC.md` + README (deprecação das seções 12/15) — tarefa 4.1 do DESIGN
