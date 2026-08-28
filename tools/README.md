# tools/ — mapa de módulos

Tudo aqui é **Python stdlib puro** (3.10+), sem `pip install`. Módulos planos de
propósito: a CLI unificada é `python tools/monitor.py` (ver README raiz).

## ⚠️ Caminhos estáveis — não mover sem migrar a instalação

Os hooks instalados no usuário (`~/.claude/settings.json`, `~/.codex/hooks.json`)
chamam estes scripts por **caminho absoluto**. Mover qualquer um deles quebra os
estados `work`/`ask`/`perm`/`free` no painel; se mover, rode
`python tools/install_hook.py` (e `install_codex_hook.py`) para regravar os paths.

| Arquivo | Papel |
|---|---|
| `session_hook.py` | entrypoint dos hooks (Claude/Codex) — grava evento estruturado de estado |
| `perm_hook.py` | entrypoint do hook `PermissionRequest` (Claude) — marca `perm` |
| `dismiss.py` | entrypoint do hook de fim de turno — limpa marcas de `perm` |
| `install_hook.py` | instala/atualiza os hooks do Claude Code |
| `install_codex_hook.py` | instala/atualiza os hooks do Codex |

## Núcleo do daemon (biblioteca, sem entrypoint próprio)

| Arquivo | Papel |
|---|---|
| `session_daemon.py` | orquestrador: varre fontes, monta payload, posta no painel |
| `session_state.py` | vocabulário de estados e inferência por transcript (Claude) |
| `session_meta.py` | metadados por sessão: modelo, branch, cwd, contexto (Codex/Claude) |
| `agent_events.py` | redução dos eventos estruturados dos hooks em estado por sessão |
| `session_hook.py` (biblioteca) | `hook_health`/`load_event_store` usados pelo daemon |
| `usage_tracker.py` | tokens por sessão e séries históricas (transcripts Claude) |
| `usage_model.py` | tipos de série de uso e combinação entre provedores |
| `quota.py` | cota 5h/semanal: oficial do Codex, estimada do Claude |
| `opencode_sessions.py` | coletor OpenCode (SQLite local; provider/modelo/effort) |
| `protocol_v2.py` | contrato v2 (`/api/v2/snapshot`): envelope validável, sem segredos |
| `monitor_config.py` | config tipada do `monitor.toml`; redige o token em qualquer saída |

## Entrypoints de operação

| Arquivo | Uso |
|---|---|
| `monitor.py` | CLI unificada: `run`/`once`/`doctor`/`config`/`hooks`/`service` |
| `doctor.py` | checagens composáveis do setup local (usado por `monitor.py doctor`) |
| `service_manager.py` | daemon como serviço **por usuário** (Task Scheduler / systemd --user) |

## Utilitários avulsos

| Arquivo | Uso |
|---|---|
| `check_secrets.py` | garante que nada sensível saiu de `include/secrets.h`/`monitor.toml` |
| `icon_convert.py` | PNG de marca → ícone LVGL ARGB8888 40x40 (ver `docs/SPEC.md` 6.2) |

## Convenções

- Imports entre módulos são **planos** (`from session_meta import ...`): os testes
  inserem `tools/` no `sys.path` e o daemon roga daqui mesmo. Não criar subpacotes
  sem atualizar os 13 arquivos de teste e os hooks instalados.
- Qualquer saída de log/JSON que possa tocar em `api_token` usa `***redacted***`
  (padrão de `monitor_config.py`). `check_secrets.py` é o guard-rail.
