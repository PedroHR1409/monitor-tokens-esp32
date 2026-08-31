# CLAUDE.md — Monitor.AI

Painel ESP32-S3 (LVGL) + daemon/coletor Python (stdlib pura). Leia `docs/SPEC.md`
antes de mudar firmware ou protocolo — toda decisão de design tem um racional lá.

## Fluxo de desenvolvimento: AgentSpec SDD (Luan Moreno)

Este projeto usa o workflow de 5 fases com agentes especializados (`.claude/`):

```
/agentspec:brainstorm → /agentspec:define → /agentspec:design → /agentspec:build → /agentspec:ship
```

- Briefs de features em `.claude/sdd/features/`; templates em `.claude/sdd/templates/`
- Documentos de fase: `BRAINSTORM_*.md`, `DEFINE_*.md`, `DESIGN_*.md`,
  `BUILD_REPORT.md`, `SHIPPED_*.md` (em `.claude/sdd/features/{feature}/`)
- Idioma dos artefatos: **português (pt-BR)**
- Mudanças em fases anteriores: `/agentspec:iterate` (cascade-aware)
- Agentes disponíveis (18): workflow (brainstorm/define/design/build/ship/iterate),
  the-planner, ci-cd-specialist, codebase-explorer, prompt-crafter,
  shell-script-specialist, ai-prompt-specialist, code-cleaner, code-documenter,
  code-reviewer, llm-specialist, python-developer, test-generator
- Knowledge base em `.claude/kb/` (carregada on-demand pelos agentes)

## Comandos

```bash
python -m pytest tests/ -q         # testes — devem passar antes de qualquer commit
python tools/check_secrets.py      # nunca commitar sem passar
pio run -e esp32-s3-3v5-lcd        # compilar firmware (1o build é lento)
python tools/monitor.py doctor     # diagnóstico local
```

## Regras duras

1. **Segredos** só em `include/secrets.h` (gitignored); token nunca em logs/JSON
   (`***redacted***`). 
2. **Tools PC só stdlib** (`tools/*.py`, Python 3.10+).
3. **Protocolo `POST /sessions` aditivo** — sem quebrar contrato sem bump de versão.
4. **Hooks em caminhos estáveis** (`tools/session_hook.py`, `perm_hook.py`,
   `dismiss.py`) — não mover sem reinstalar.
5. **Commits**: curtos, um tema, estilo `feat:`/`fix:`/`docs:`/`chore:`; sem
   `--force`; sem push sem pedido explícito.
6. **Serviço** (`tools/service_manager.py`): só escopo de usuário.

## Estrutura

- `src/` por camada: `ui/`, `drivers/`, `sessions/`, `assets/`, `icons/` (gerados);
  headers em `include/`
- `tools/` — mapa completo em `tools/README.md`
- `tests/` — pytest/unittest + `fixtures/`
- `docs/SPEC.md` — fonte da verdade de design
- `.claude/` — AgentSpec SDD (agentes, comandos, skills, kb, sdd)
