# tools/ — mapa de módulos

Tudo aqui é **Python stdlib puro** (3.11+), sem `pip install`. Módulos planos de
propósito: a CLI unificada é `python tools/monitor.py` (ver README raiz).

## ⚠️ Caminhos estáveis — não mover sem migrar a instalação

Os hooks instalados no usuário (`~/.claude/settings.json`, `$CODEX_HOME/hooks.json`
ou `~/.codex/hooks.json` quando `CODEX_HOME` não está definido)
chamam estes scripts por **caminho absoluto**. Mover qualquer um deles quebra os
estados `work`/`ask`/`perm`/`free` no painel; se mover, rode
`python tools/install_hook.py` (e `install_codex_hook.py`) para regravar os paths.

| Arquivo | Papel |
|---|---|
| `session_hook.py` | entrypoint dos hooks (Claude/Codex/Command Code) — grava evento estruturado de estado |
| `perm_hook.py` | entrypoint do hook `PermissionRequest` (Claude) — marca `perm` |
| `dismiss.py` | entrypoint do hook de fim de turno — limpa marcas de `perm` |
| `install_hook.py` | instala/atualiza os hooks do Claude Code |
| `install_codex_hook.py` | instala/atualiza os hooks do Codex |
| `install_commandcode_hook.py` | instala/atualiza os hooks do Command Code (`~/.commandcode/settings.json`) |

O coletor e o hook do Codex usam o mesmo `$CODEX_HOME` que iniciou o agente.
Isso inclui homes isolados por hosts como o Orca. Sem essa variável, o padrão
é `~/.codex`; no Windows, o daemon reconhece o home do Orca quando o banco dele
é mais recente que o banco padrão.

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
| `quota.py` | cota 5h/semanal: oficial do Codex; estimada de Claude/OpenCode/Command Code |
| `opencode_sessions.py` | coletor OpenCode (SQLite local; provider/modelo/effort) |
| `commandcode_sessions.py` | coletor Command Code (transcripts JSONL; estado por hooks + inferência) |
| `protocol_v2.py` | contrato v2 (`/api/v2/snapshot`): envelope validável, sem segredos. **Reserva não-funcional** — o firmware serve só o v1; ver `docs/SPEC.md` |
| `monitor_config.py` | config tipada do `monitor.toml`; redige o token em qualquer saída |
| `alert_severity.py` | severidade do alerta (`none`/`warning`/`critical`/`expired`) — função pura |
| `notify.py` | toast nativo do SO por `subprocess` (PowerShell / `notify-send`) |

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
  inserem `tools/` no `sys.path` e o daemon roda daqui mesmo. Não criar subpacotes
  sem atualizar os testes e os hooks instalados.
- Qualquer saída de log/JSON que possa tocar em `api_token` usa `***redacted***`
  (padrão de `monitor_config.py`). Campo sensível **vazio** continua vazio — não há
  segredo a esconder, e mascarar o nada fazia `config show` discordar do `doctor`.
  `check_secrets.py` compara localmente os valores de `include/secrets.h`; no CI,
  Gitleaks faz a varredura genérica do histórico Git.
- `storage.retention_days` é o valor efetivo do prune: o daemon o repassa do config
  até `usage_history.prune`. `RETENTION_DAYS` (30) é só o default de chamadas diretas.

## Reservas declaradas (sem consumidor funcional)

Chaves do `monitor.toml` e artefatos que existem como **reserva explícita** — não
apague sem remover também a expectativa dos testes; não ligue sem uma feature:

| Item | Estado |
|---|---|
| `transport.prefer_websocket` | Reserva — HTTP simples é suficiente para ≤6 sessões |
| `daemon.role` | Reserva — escopo single-machine, sempre `standalone` |
| `storage.hourly_retention_days` | Reserva — o schema é diário `(day, tokens)`; destrava o item #2 do `docs/ROADMAP.md` |
| `--protocol 2` / `protocol_v2.py` | Reserva — o firmware serve só o v1; `--protocol 2` responde 404 |
