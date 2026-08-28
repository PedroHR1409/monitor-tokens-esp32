# AGENTS.md — regras para agentes (Codex, OpenCode, Claude) neste repositório

Painel ESP32-S3 (LVGL) + daemon/coletor Python puro. Leia `docs/SPEC.md` antes de
mudar firmware ou protocolo — toda decisão de design tem um racional lá.

## Comandos

```bash
python -m pytest tests/ -q         # 152 testes — devem passar antes de qualquer commit
python tools/check_secrets.py      # never commit without this passing
pio run -e esp32-s3-3v5-lcd        # compilar firmware (demora no primeiro build)
python tools/monitor.py doctor     # diagnóstico local
```

Testes rodam com `pytest` **ou** `python -m unittest discover -s tests -v`.

## Regras duras

1. **Nada de segredos fora de `include/secrets.h`** (gitignored). Nunca imprima o
   token; em logs/JSON redija como `***redacted***`. Se criar código que toque em
   `api_token`, siga o padrão de `tools/monitor_config.py`.
2. **Ferramentas PC são só stdlib** (`tools/*.py`, Python 3.10+): nada de
   `requirements.txt`, `pip install` ou imports de terceiros.
3. Firmware segue o estilo existente em `src/` (C++ Arduino, LVGL 9, GFX):
   componentizar por arquivo, sem globals soltos quando couber em struct.
4. `tools/service_manager.py` só opera em escopo de **usuário** — nunca escrever em
   `/etc/systemd/system` ou registrar tarefas elevadas. Mudanças lá exigem testes
   com runner injetado (veja `tests/test_service_manager.py`).
5. Protocolo: versões são explícitas (`tools/protocol_v2.py`, `versioned` fields).
   Não quebre o contrato `POST /sessions` sem bump de versão e nota em SPEC.md.
6. Commits: mensagens curtas em inglês no estilo existente (`feat:`, `fix:`,
   `docs:`, `chore:`). Um tema por commit.
7. Sem `--force`, sem push sem pedido explícito do usuário.

## Estrutura

- `src/` + `include/` — firmware (PlatformIO, env `esp32-s3-3v5-lcd`)
- `tools/` — daemon, hooks, CLI (`monitor.py`), protocolo, serviço
- `tests/` — pytest/unittest, fixtures em `tests/fixtures/`
- `docs/SPEC.md` — fonte da verdade de design; `docs/superpowers/` — planos/specs
  de evolução (SDD)
- `monitor.toml` — config de runtime do daemon (gitignored; pode conter token)

## Ao terminar uma tarefa

Rode `pytest` + `check_secrets.py`, e `pio run` se mexeu em `src/`/`include/`/
`platformio.ini`. Relate o que mudou e o que testou.
