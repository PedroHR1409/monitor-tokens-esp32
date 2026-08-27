# Session Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar estados e dados falsos, proteger credenciais, usar IDs estáveis e degradar corretamente dados stale/offline.

**Architecture:** Um reducer puro consome eventos estruturados e produz estado + freshness por ID completo. O daemon monta um payload defensivo e priorizado; o firmware preserva o último snapshot como histórico, mas controla validade global e por sessão separadamente.

**Tech Stack:** Python 3 stdlib/unittest, Codex e Claude hooks JSON, PlatformIO, Arduino ESP32-S3, ArduinoJson, LVGL 9.

**Spec:** `docs/superpowers/specs/2026-08-27-session-reliability-design.md`

## Global Constraints

- Não inferir `ask` ou `perm` por texto ou idade.
- `perm` exige evento explícito `PermissionRequest`.
- Timestamp inválido, ausente ou sem timezone degrada por sessão e gera diagnóstico.
- ID completo é identidade; limite de 10 caracteres existe somente na renderização.
- Produção inicia sem mocks; demo exige `MONITOR_DEMO_DATA=1` explícito.
- Não imprimir nem copiar valores reais de credenciais.
- Preservar touch, Pomodoro e fluxos LVGL fora do escopo.

---

### Task 1: Segurança de credenciais e modo de produção

**Files:**
- Create: `include/secrets.example.h`
- Modify: `.gitignore`, `platformio.ini`, `include/config.h`, `src/session_manager.cpp`, `src/session_manager.h`, `README.md`
- Test: `tests/test_production_contracts.py`

**Interfaces:**
- Consumes: macros `WIFI_SSID` e `WIFI_PASSWORD` de `secrets.h`.
- Produces: build padrão vazia e ambiente demo explícito.

- [ ] Criar testes que executam a verificação de segredos e validam boot vazio por padrão.
- [ ] Executar `python -m unittest tests.test_production_contracts -v` e confirmar falha pela ausência do exemplo e mocks ativos.
- [ ] Adicionar exemplo fictício, flag demo e inicialização vazia padrão.
- [ ] Reexecutar o teste até passar.

### Task 2: Reducer de eventos e timestamps defensivos

**Files:**
- Create: `tools/agent_events.py`, `tests/test_agent_events.py`
- Modify: `tools/session_state.py`, `tools/session_meta.py`

**Interfaces:**
- Produces: `parse_timestamp(value) -> ParseResult`, `reduce_events(events, now) -> SessionSnapshot` e rejeição de eventos fora de ordem.
- Consumes: eventos normalizados `work`, `ask`, `perm`, `free`, `ended` com ID e timestamp aware.

- [ ] Criar casos `work→perm→work`, `work→ask→work`, `work→free`, `perm→free`, encerramento, stale, fora de ordem e timestamps inválidos.
- [ ] Confirmar que falham contra a implementação atual.
- [ ] Implementar reducer puro e adaptar o Claude sem alterar a detecção exata de `AskUserQuestion`.
- [ ] Confirmar todos os testes verdes.

### Task 3: Hooks estruturados Claude/Codex

**Files:**
- Create: `tools/session_hook.py`, `tools/install_codex_hook.py`, `tests/test_session_hook.py`
- Modify: `tools/install_hook.py`, `tools/perm_hook.py`, `README.md`

**Interfaces:**
- Produces: store atômico por agente e sessão; actions `work`, `permission_request`, `ask`, `free`, `ended`.
- Consumes: JSON de stdin com `session_id`, `hook_event_name`, `tool_name` e timestamps locais aware.

- [ ] Testar eventos explícitos, limpeza, escrita atômica e proteção contra evento antigo.
- [ ] Confirmar falhas antes da implementação.
- [ ] Implementar hook comum e instaladores idempotentes sem alterar configurações vivas nos testes.
- [ ] Manter `perm_hook.py` como compatibilidade fina ou migrar sem duplicar estado.
- [ ] Executar testes dos hooks.

### Task 4: Daemon sem heurística e payload confiável

**Files:**
- Modify: `tools/session_daemon.py`, `tools/dismiss.py`
- Test: `tests/test_session_daemon.py`

**Interfaces:**
- Consumes: snapshots do store, transcripts Claude e índice/metadata Codex.
- Produces: sessões com ID completo, `source_stale`, `source_age_s`, `diagnostic`; payload com `generated_at`.

- [ ] Testar comando Codex longo, ausência de falso `ask`/`perm`, stale, ID completo e nomes/prefixos iguais.
- [ ] Testar ranking `perm > ask > work > free`, recência e desempate estável.
- [ ] Confirmar falhas.
- [ ] Remover constantes/faixas temporais do Codex e classificar apenas por eventos; fallback sem hook é `free` degradado.
- [ ] Filtrar dismiss por ID completo e preservar catálogo por identidade.
- [ ] Executar testes do daemon.

### Task 5: Firmware com identidade e freshness explícitos

**Files:**
- Modify: `include/session_model.h`, `src/id_list.h`, `src/id_list.cpp`, `src/session_transport.h`, `src/session_transport.cpp`, `src/ui_dashboard.cpp`, `src/main.cpp`

**Interfaces:**
- Produces: `session_transport_data_status()` com presença, freshness, idade e último sucesso; IDs completos no array/NVS; detalhes por ID.
- Consumes: `source_stale`, `source_age_s`, `generated_at` do payload.

- [ ] Aumentar buffers de ID e versionar chaves NVS para não reutilizar IDs truncados.
- [ ] Separar stale da fonte e stale do transporte; invalidar header/métricas após timeout.
- [ ] Expor freshness em `/diag` e no heartbeat sem revelar credenciais.
- [ ] Guardar `g_detailId`, reencontrar slot por ID a cada refresh e fechar se ausente.
- [ ] Manter truncamento de nome somente no render do card.
- [ ] Compilar firmware de produção.

### Task 6: Verificação integrada e documentação

**Files:**
- Modify: `README.md`, `docs/SPEC.md`

**Interfaces:**
- Consumes: todos os contratos anteriores.
- Produces: instruções atuais, checklist e limitações explícitas.

- [ ] Executar toda a suíte `python -m unittest discover -s tests -v`.
- [ ] Executar compilação PlatformIO de produção e demo.
- [ ] Executar varredura de segredo que relata apenas contagem/caminhos, nunca valores.
- [ ] Verificar sintaxe Python e dry-run dos instaladores em fixtures temporárias.
- [ ] Revisar cada item do checklist do usuário e registrar limitações remanescentes.

## Self-review

- Cobertura: todos os 13 itens da validação obrigatória estão associados às Tasks 1–6.
- Placeholders: nenhuma ação depende de `TODO`/`TBD`; cada teste nomeia uma falha observável.
- Tipos: o ID completo flui como `str` no Python e buffer único dimensionado no C++; freshness permanece atributo ortogonal ao enum de estado.
- Limite: a instalação de hooks reais é documentada e testada por fixture, não aplicada silenciosamente à configuração do usuário.
