# BUILD REPORT: DADOS_OPENCODE_BRANCH_E_CONTEXTO

| Attribute | Value |
|-----------|-------|
| **Data** | 2026-08-31 |
| **Executor** | build-agent (via OpenCode) |
| **DESIGN** | `DESIGN_DADOS_OPENCODE_BRANCH_E_CONTEXTO.md` |
| **Status** | ✅ Shipped |

## Implementado

1. **`session_meta.read_git_branch` worktree-aware**: `.git` arquivo → parse `gitdir:`
   (absoluto ou relativo) → HEAD do worktree. Corrige "sem git" em worktrees
   (beneficia Claude/Codex/OpenCode).
2. **`session_state.session_display_name`**: regra única de nomenclatura — branch
   fora de main/master vence o projeto (case-insensitive, sem acentos).
3. **Scans aplicam a regra**: Claude (`meta_of` branch), Codex (`cwd` → branch),
   OpenCode (`directory` → branch); `usage_top` (pódio) herda.
4. **Contexto OpenCode**: default 128000 (`estimated`) com override
   `usage.opencode_context_window` (`measured`); ctxPct limitado a 100.
5. **Documentação**: SPEC seção 17 + README.

## Correções de percurso

1. `usage_top._claude`: shadowing da variável de loop `project` (Path → str) —
   `project.name` quebrava na 2ª iteração do loop.
2. Testes de contexto atualizados: default 128k muda o comportamento
   ("unknown" → "estimated" com valor 0 para 900 tokens).
3. `run()`: testes (SimpleNamespace) agora ficam herméticos do banco real
   (`hasattr(args, "opencode_db")`), que antes vazava sessões reais no payload
   dos testes (e agora com contexto >100% quebrava a validação v2).

## Verificação

- 190 passed (+9: worktree/gitdir ×3, display_name ×3, contexto ×2, nome ×1)
- compileall OK; check_secrets limpo
- Validação ao vivo (`--once`): cards exibindo `27816-remover-monoli[OC:work]`
  (feat/27816), `28796-ajustes[OC:work]` ×2 (worktree) e
  `monitor-tokens-esp32[OC:work]` (master → projeto)

## Cobertura dos ATs

| AT | Verificação |
|----|-------------|
| 001/002/003 | `tests/test_session_meta.py` (gitdir abs/rel, pasta, sem git) |
| 004/005 | `tests/test_opencode_sessions.py` (default 128k com clamp, override 600k) |
| 006/007 | `tests/test_session_state.py` + `test_session_daemon.py` |
| 008 | integração: scan OpenCode com directory=worktree → name=branch |
| 009 | pytest/compileall/secrets verdes |

## Pendências

- [ ] Confirmação visual do operador (branch no detalhe, contexto %)
- [ ] Commit
- [ ] Ship de VISUAL_PADRAO_PAINEL + DADOS_OPENCODE_BRANCH_E_CONTEXTO
