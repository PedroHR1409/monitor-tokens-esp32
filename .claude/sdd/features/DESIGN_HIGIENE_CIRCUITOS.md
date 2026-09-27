# DESIGN: Higiene — fechar circuitos

> Alinhamento de documentação, doctor, config e retenção ao painel real — sem
> tocar firmware, contrato HTTP ou schema; só o que o repo afirma sobre si mesmo.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | HIGIENE_CIRCUITOS |
| **Date** | 2026-09-19 |
| **Author** | design-agent |
| **DEFINE** | [DEFINE_HIGIENE_CIRCUITOS.md](./DEFINE_HIGIENE_CIRCUITOS.md) — clareza 15/15 |
| **Status** | ✅ Complete (Built) |
| **Abordagem** | Approach A do brainstorm — ciclo de higiene, P0 do backlog |
| **Confiança** | **0.80** — KB `python` + `testing` carregadas; nenhum padrão de KB cobre docs de produto nem o doctor. Os padrões vêm do **codebase** (`CheckResult`, `_redact`, `unittest`+`subTest`), citados por arquivo e linha |

---

## Architecture Overview

```text
┌───────────────────────────────────────────────────────────────────────────────┐
│                    ESCOPO: nada cruza a fronteira HTTP                         │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  ┌─────────────────────── DOCS (fonte para humanos e agentes) ──────────────┐  │
│  │  README.md          CLAUDE.md        tools/README.md                     │  │
│  │  docs/SPEC.md       docs/ROADMAP.md                                      │  │
│  │      │                  │                  │                             │  │
│  │      └──── 4 provedores · alerta escalonado · Python 3.11 · v2 reserva ──┘ │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
│  ┌─────────────────────── CÓDIGO PC (sem rede, sem firmware) ────────────────┐  │
│  │                                                                            │  │
│  │  monitor.py ── hooks check ──▶ help text inclui Command Code               │  │
│  │      │                                                                     │  │
│  │      ▼                                                                     │  │
│  │  doctor.py                                                                 │  │
│  │    check_protocol ── fixture? ──▶ mantém leitura de protocols[]            │  │
│  │                       live     ──▶ declara v2 RESERVA (não "cannot verify")│  │
│  │    check_token    ── length 0 ──▶ WARN (inalterado)                        │  │
│  │                                                                            │  │
│  │  monitor_config.py                                                         │  │
│  │    _redact(value, field) ── vazio? ──▶ ""  (não mascara o nada)            │  │
│  │                            não vazio ─▶ "***redacted***"                   │  │
│  │                                                                            │  │
│  │  session_daemon._record_daily_history                                      │  │
│  │    usage_history.prune(..., keep_days=config.storage.retention_days)       │  │
│  │                                    │                                       │  │
│  │                                    ▼                                       │  │
│  │  usage_history.RETENTION_DAYS = 30 (default alinhado ao StorageSettings)   │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
│  ✗ NÃO TOCA: src/ · include/ (comportamento) · protocol_v2.py · POST /sessions  │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| `README.md` (mod.) | Lead, tabela "O painel mostra" e badges com 4 provedores; alerta descrito como escalonado; Python 3.11+; contagem de testes atualizada | Markdown |
| `docs/SPEC.md` (mod.) | §3 com os 5 `ToolType`; título "Monitor.AI"; notas de reserva para `prefer_websocket`, `daemon.role`, `hourly_retention_days` e `--protocol 2` | Markdown |
| `docs/ROADMAP.md` (mod.) | Lote P0 como ciclo desta feature; item 7 (v2) deixa de ser "decisão pendente" e vira reserva | Markdown |
| `CLAUDE.md` (mod.) | Python 3.11+ (hoje "3.10+") | Markdown |
| `tools/README.md` (mod.) | Python 3.11+ (hoje "3.10+") | Markdown |
| `tools/doctor.py` (mod.) | `check_protocol` deixa de afirmar v2 não verificado no caminho live | Python stdlib |
| `tools/monitor.py` (mod.) | Help do subcomando `hooks check` menciona Command Code | Python stdlib |
| `tools/monitor_config.py` (mod.) | `_redact` não mascara valor vazio | Python stdlib |
| `tools/session_daemon.py` (mod.) | Passa `keep_days=config.storage.retention_days` ao `prune` | Python stdlib |
| `tools/usage_history.py` (mod.) | `RETENTION_DAYS` default 30, alinhado a `StorageSettings.retention_days` | Python stdlib |
| `tests/test_doctor.py` (mod.) | Cobre o novo texto/status de `check_protocol` (live e fixture) | unittest + subTest |
| `tests/test_monitor_config.py` (mod.) | Cobre `_redact` com valor vazio vs. valor presente | unittest + subTest |
| `tests/test_usage_history.py` (mod.) | Cobre `prune` com `keep_days` explícito e default 30 | unittest + subTest |

---

## Key Decisions

### Decision 1: `check_protocol` no caminho live declara reserva, não ignorância

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-19 |

**Context:** `check_protocol` (`tools/doctor.py:195-202`) só produz veredito real quando
recebe `protocols` por fixture. Sem fixture, `supplied` é `{}`, `protocols` é `None`, e
cai sempre no `WARN "protocol v2 compatibility cannot be verified"` — mesmo com a placa
respondendo `/health` (medido em 2026-09-19). O DEFINE decidiu arquivar o v2 como reserva;
o doctor continua sugerindo que a verificação **poderia** existir.

**Choice:** Manter o ramo de fixture **intacto** (ele permite `protocols: [1,2]` no
`healthy.json` e sustenta o teste existente). No ramo live — `supplied` vazio — trocar a
mensagem por uma que declare o estado real: v2 é reserva e o firmware serve apenas o
contrato v1 (`/sessions`). Status continua `warn` (nunca `ok`), porque nada foi medido.

**Rationale:** O doctor existe para não mentir. "Cannot be verified" implica uma sonda que
não foi feita e um futuro em que ela existirá; "v2 é reserva, firmware serve v1" é o fato
decidido e é acionável. Manter `warn` preserva `exit_code` e a distinção de `ok`.

**Alternatives Rejected:**

1. **Sondar a placa de verdade** (`GET /diag` ou similar para descobrir `protocols`) — rejeitado: adiciona uma sonda de rede ao doctor por uma capacidade arquivada; e o firmware não expõe `protocols` hoje, então a sonda também não mediria nada.
2. **Remover `check_protocol` de `run_checks`** — rejeitado: quebraria `test_healthy_fixture_has_only_successful_checks` (`test_doctor.py:32-36`), que exige `protocol` presente e `ok` sob fixture, e perderia a checagem determinística.
3. **Deixar como está** — rejeitado: é exatamente a mentira que o DEFINE abriu como P0.

**Consequences:**

- O doctor live passa a ser honesto sobre o v2; o item `protocol` continua visível.
- Nenhuma chamada de rede nova; nenhum contrato HTTP do firmware tocado.
- O texto live vira dependente da decisão de arquivamento — se o v2 for implementado um dia, este AT muda de propósito.

---

### Decision 2: Retenção vem do config; a constante vira default alinhado

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-19 |

**Context:** `usage_history.RETENTION_DAYS = 35` (`usage_history.py:26`) é o default de
`prune`, mas `session_daemon.py:745` chama `prune(history_db, tz=tz, now=now)` **sem**
`keep_days`, então a constante sempre venceu. `StorageSettings.retention_days` é 30, e o
SQLite real tem 35 linhas (medido) — as 5 excedentes ficam fora da janela de 30 do card 7.

**Choice:** O valor precisa ser **encadeado** até o `prune` — o caller real não é o `run()`:

```text
run(args, config)                                    # session_daemon.py:867, tem config
  └─ build_payload_v1(...) / build_payload_v2(...)   # :946 / :961 e fallback :990 / :997
       └─ _record_daily_history(...)                 # :690  ← chama o prune em :745
            └─ usage_history.prune(keep_days=...)
```

Mudanças coordenadas:

1. `build_payload_v1` e `build_payload_v2` ganham `retention_days: int = RETENTION_DAYS` (default do módulo, para os testes herméticos que não passam nada), e repassam o parâmetro; `build_payload_v2` encaminha ao `build_payload_v1` interno (`:769-777`).
2. `_record_daily_history` ganha `retention_days: int = RETENTION_DAYS` e passa `keep_days=retention_days` ao `prune` (`:745`).
3. Os **quatro** call sites em `run()` (`:946`, `:961`, `:990`, `:997`) passam `retention_days=config.storage.retention_days` — o `config` já está no escopo de `run`.
4. `usage_history.RETENTION_DAYS` passa de 35 para **30**, para que o default do módulo e o default do `StorageSettings` coincidam e o valor do config seja a única fonte operacional.

**Rationale:** O DEFINE exige que mudar `retention_days` no toml mude a retenção sem
recompilar nada; hoje o config é decorativo para esse eixo. Alinhar o default elimina a
divergência que o ROADMAP já registrava como "mesma família de desconexão config↔código".
A janela visível (`WINDOW_DAYS = 30`) não muda; só o DELETE passa a respeitar o config.

**Alternatives Rejected:**

1. **Só alinhar a constante para 30, sem passar o config** — rejeitado: continua ignorando o toml; o operador muda para 14 e nada acontece.
2. **Só passar o config, deixando `RETENTION_DAYS = 35`** — rejeitado: deixa um default morto e divergente que o próximo leitor vai assumir como verdade.
3. **Apagar a constante** — rejeitado: `prune` é API pública do módulo e os testes a chamam; um default explícito é mais claro que um `keep_days` obrigatório que quebra chamadas.

**Consequences:**

- Apagar as 5 linhas além de 30 na primeira execução após a mudança (efeito esperado e coberto por AT-008).
- `test_prune_removes_only_days_beyond_retention` (`test_usage_history.py:85-94`) continua
  válido: insere 58 dias e 8 dias, espera 1 remoção — 8 < 30 e 58 > 30 em qualquer default
  razoável; o teste passa a **também** exercitar `keep_days` explícito.
- O daemon ganha um parâmetro; nenhum outro chamador de `prune` existe (grep confirmou só `session_daemon` e os testes).

---

### Decision 3: `_redact` distingue "sem token" de "token configurado"

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-19 |

**Context:** `_redact` (`monitor_config.py:237-247`) mascara pelo **nome do campo**: qualquer
chave contendo `token`/`secret`/`password`/`api_key` vira `***redacted***`, inclusive quando
o valor é `""`. Resultado medido: `config show` imprime `api_token: "***redacted***"` para
uma config vazia, enquanto `doctor.check_token` no mesmo snapshot diz `WARN "no transport
token configured"`. O DEFINE decidiu "dois canais, duas verdades".

**Choice:** Em `_redact`, quando o valor de um campo sensível é uma string vazia (ou `None`),
retornar o valor como está (`""`), sem a marca de redação. Valor não vazio continua
`***redacted***`. Nenhum outro campo sensível muda de comportamento.

**Rationale:** Mascarar o vazio não protege nada — não há segredo — e cria a única
discordância visível entre dois comandos do mesmo produto. `test_redacted_dict_never_exposes_a_configured_token`
(`test_monitor_config.py:191-202`) continua passando: lá o token é não vazio.

**Alternatives Rejected:**

1. **Redigir sempre** — rejeitado: é a discordância atual; `config show` sugere um token que não existe.
2. **Omitir a chave quando vazia** — rejeitado: quebra a forma do dicionário redigido e torna `config show` imprevisível para quem consome o JSON; `""` é um valor honesto.
3. **Fazer o doctor ignorar token vazio** — rejeitado: o WARN é correto e útil; o problema é o outro canal.

**Consequences:**

- `config show` e `doctor` passam a contar a mesma história sobre o token.
- O guard-rail de não vazar valor real permanece: só o caso vazio deixa de ser mascarado.
- `check_secrets.py` não muda: ele varre arquivos, não o dicionário redigido.

---

### Decision 4: v2 e chaves órfãs são reserva documentada, não remoção

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-19 |

**Context:** `protocol_v2.py` (233 linhas) + 175 linhas de teste existem e documentam um
contrato que o firmware não serve; `prefer_websocket`, `daemon.role` e
`hourly_retention_days` têm zero consumidores funcionais (grep confirmado). O YAGNI do
brainstorm escolheu "documentar e arquivar".

**Choice:** Nenhum arquivo de código morto é apagado. A SPEC ganha uma nota curta que
declara cada item como reserva sem consumidor / não-funcional, e `docs/ROADMAP.md` move o
item 7 de "decisão pendente" para "arquivado como reserva". `EXAMPLE_TOML` mantém as chaves
comentadas com o mesmo esclarecimento.

**Rationale:** A justificativa original do v2 era multi-node, descartado — mas o contrato
tem valor como registro versionado e os testes o protegem. Apagar é irreversível e perde a
reserva; ligar seria feature nova (fora do YAGNI). O ROADMAP já diz que "deixar ambíguo é a
pior das três".

**Alternatives Rejected:**

1. **Remover `protocol_v2.py`, a flag e as chaves** — rejeitado pelo usuário ("documentar e arquivar"); perde a reserva e os testes que documentam o contrato.
2. **Implementar o endpoint no firmware** — rejeitado: multi-node descartado, e firmware está fora do escopo deste lote.
3. **Deixar como está** — rejeitado: `--protocol 2` continua parecendo opção real.

**Consequences:**

- Nenhum binário muda; nenhum teste de `test_protocol_v2.py` é removido.
- O `EXAMPLE_TOML` e a SPEC carregam a explicação — o próximo leitor não confunde reserva com bug.

---

## File Manifest

| # | File | Action | Purpose | Agent | Dependencies |
|---|------|--------|---------|-------|--------------|
| 1 | `tools/doctor.py` | Modify | `check_protocol`: live declara reserva; fixture intacta | @python-developer | None |
| 2 | `tools/monitor.py` | Modify | Help de `hooks check` menciona Command Code | @python-developer | None |
| 3 | `tools/monitor_config.py` | Modify | `_redact` não mascara valor vazio | @python-developer | None |
| 4 | `tools/usage_history.py` | Modify | `RETENTION_DAYS = 30` | @python-developer | None |
| 5 | `tools/session_daemon.py` | Modify | Passar `keep_days` do config ao `prune` | @python-developer | 4 |
| 6 | `README.md` | Modify | 4 provedores, alerta escalonado, Python 3.11, contagem de testes | @code-documenter | None |
| 7 | `docs/SPEC.md` | Modify | §3 com 5 `ToolType`; título; notas de reserva v2/chaves | @code-documenter | None |
| 8 | `docs/ROADMAP.md` | Modify | Lote P0 como ciclo; item 7 vira reserva | @code-documenter | None |
| 9 | `CLAUDE.md` | Modify | Python 3.11+ | @code-documenter | None |
| 10 | `tools/README.md` | Modify | Python 3.11+; nota de reserva das chaves | @code-documenter | None |
| 11 | `tests/test_doctor.py` | Modify | AT-004/AT-005: protocolo live vs. fixture | @test-generator | 1 |
| 12 | `tests/test_monitor_config.py` | Modify | AT-010/AT-011/AT-012: `_redact` vazio vs. presente | @test-generator | 3 |
| 13 | `tests/test_usage_history.py` | Modify | AT-008/AT-009: `keep_days` explícito e default 30 | @test-generator | 4, 5 |

**Total Files:** 13 (5 modificações de código, 5 de documentação, 3 de teste) — **0 arquivos criados**.

**Conflito de arquivo no manifesto:** `tools/monitor.py` (item 2) e `tools/doctor.py`
(item 1) não compartilham escrita; `tools/README.md` (item 10) e `tools/README.md` do
`README.md` raiz são arquivos distintos. Não há dois agentes no mesmo arquivo.

---

## Agent Assignment Rationale

> Agentes descobertos de `.claude/agents/**/*.md` (18 arquivos).

| Agent | Files Assigned | Why This Agent |
|-------|----------------|----------------|
| @python-developer | 1, 2, 3, 4, 5 | Edições Python cirúrgicas; KB `python`/`testing`; é o agente das features anteriores do daemon |
| @code-documenter | 6, 7, 8, 9, 10 | Especialista em documentação de produto; o lote é majoritariamente docs |
| @test-generator | 11, 12, 13 | Testes de regressão para os comportamentos alterados; convenção `unittest`+`subTest` do repo |
| @code-reviewer | (revisão) | Sugerido no BUILD_REPORT para revisar `doctor.py` e `monitor_config.py` — os dois pontos de maior risco |

**Agent Discovery:**
- Scanned: `.claude/agents/**/*.md` — 18 agentes em 6 categorias
- Matched by: tipo de arquivo (`.py`/`.md`), palavras-chave de propósito (doc, test, parser), path patterns (`tools/`, `tests/`, `docs/`)
- Nenhum agente C++/firmware é necessário — o manifesto não toca `src/`/`include/`

**Nota de execução.** No build do Command Code (2026-09-19) o executor não tinha o tool
`Task` e tudo rodou `(direct)`. Este manifesto mantém a atribuição como referência; se o
Build tiver `Task`, delega; se não, executa direto seguindo os padrões KB e registra a
atribuição real no BUILD_REPORT.

---

## Code Patterns

### Pattern 1: `check_protocol` — fixture intacta, live honesto

```python
# tools/doctor.py — substitui o corpo de check_protocol (linhas 195-202)
def check_protocol(fixture: Mapping[str, Any]) -> CheckResult:
    """O v2 e reserva: o firmware serve apenas o contrato v1 de /sessions.

    O ramo de fixture continua aceitando um device que reporte protocols[]; sem
    fixture nao ha sonda e o veredito e explicito sobre o estado decidido, nunca
    um "cannot be verified" que sugere uma medicao que nao existe.
    """
    supplied = _fixture_mapping(fixture, "device")
    protocols = supplied.get("protocols") if supplied else None
    if isinstance(protocols, list) and 2 in protocols:
        return _result("protocol", OK, "device reports protocol v2 compatibility")
    if isinstance(protocols, list) and 1 in protocols:
        return _result("protocol", WARN, "device reports legacy protocol v1 only")
    return _result("protocol", WARN,
                   "protocol v2 is a reserved, non-functional contract; "
                   "the firmware serves the v1 /sessions endpoint")
```

### Pattern 2: `_redact` — vazio permanece vazio

```python
# tools/monitor_config.py — substitui _redact (linhas 237-247)
def _redact(value: Any, field_name: str = "") -> Any:
    normalized = field_name.lower().replace("-", "_")
    if any(marker in normalized for marker in ("token", "secret", "password", "api_key")):
        # Um campo sensivel vazio nao esconde segredo nenhum: devolve-lo como ""
        # mantem config show e doctor contando a mesma historia. Valores reais
        # nunca aparecem.
        if value is None or value == "":
            return value
        return "***redacted***"
    if isinstance(value, dict):
        return {str(key): _redact(item, str(key)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
```

### Pattern 3: `prune` honra o config

```python
# tools/usage_history.py — default alinhado a StorageSettings.retention_days
RETENTION_DAYS = 30
WINDOW_DAYS = 30
```

```python
# tools/session_daemon.py — _record_daily_history ganha o parametro
def _record_daily_history(history_db: Path, claude_dir: Path, tz: timezone,
                          now: datetime, claude_today: int, *,
                          opencode_db: Path | None,
                          force_backfill: bool = False,
                          rollouts_dir: Path | None = None,
                          commandcode_dir: Path | None = None,
                          retention_days: int = usage_history.RETENTION_DAYS) -> dict:
    ...
    usage_history.prune(history_db, keep_days=retention_days, tz=tz, now=now)
    return {"daily": usage_history.daily_window(history_db, tz, now=now)}
```

```python
# tools/session_daemon.py — build_payload_v1/v2 repassam o valor (default do modulo
# mantem os testes hermeticos, que nao passam nada, no comportamento atual)
def build_payload_v1(..., retention_days: int = usage_history.RETENTION_DAYS) -> dict:
    ...
    stats["history"] = _record_daily_history(..., retention_days=retention_days)
```

Os quatro call sites em `run()` (`session_daemon.py:946`, `:961`, `:990`, `:997`) passam
`retention_days=config.storage.retention_days`; o `config` já está no escopo de `run`. O
`build_payload_v2` encaminha o parâmetro ao `build_payload_v1` interno (`:769-777`).

### Pattern 4: Teste com `subTest`, convenção do repo

```python
# tests/test_monitor_config.py — regressao de _redact
def test_redacted_dict_keeps_an_unconfigured_token_empty(self):
    from monitor_config import MonitorConfig

    config = MonitorConfig.load(path=Path("does-not-exist.toml"), environ={})
    redacted = config.redacted_dict()

    self.assertEqual("", redacted["transport"]["api_token"])


def test_redacted_dict_still_hides_any_configured_token(self):
    from monitor_config import MonitorConfig

    for token in ("short", "configured-token-must-never-appear"):
        with self.subTest(token=token):
            config = MonitorConfig.load(path=Path("does-not-exist.toml"),
                                        environ={"MONITOR_API_TOKEN": token})
            redacted = config.redacted_dict()
            self.assertEqual("***redacted***", redacted["transport"]["api_token"])
            self.assertNotIn(token, repr(redacted))
```

### Pattern 5: Reserva documentada na SPEC (formato)

```markdown
## <n>. Reservas declaradas (sem consumidor)

As chaves abaixo existem no `monitor.toml` e/ou no PC **como reserva explicita**. Nenhuma
tem consumidor funcional hoje; nao apague sem remover tambem a expectativa dos testes.

| Item | Onde mora | Estado |
|---|---|---|
| `transport.prefer_websocket` | `monitor.toml` / `TransportSettings` | Reserva — HTTP simples e suficiente |
| `daemon.role` | `monitor.toml` / `DaemonSettings` | Reserva — single-machine, sempre `standalone` |
| `storage.hourly_retention_days` | `monitor.toml` / `StorageSettings` | Reserva — o schema e diario (`(day, tokens)`); destrava o item #2 do ROADMAP |
| `--protocol 2` / `tools/protocol_v2.py` | CLI + modulo | Reserva — o firmware serve so o v1; rodar `--protocol 2` responde 404 |
```

---

## Data Flow

```text
1. `python tools/monitor.py doctor` (sem fixture)
   │
   ▼
2. doctor.run_checks(config, fixture=None)  →  check_protocol({})
   │                                              │
   │                                              └─▶ "v2 is a reserved ... v1 /sessions" (WARN)
   │
3. `python tools/monitor.py config show`
   │
   ▼
4. config.redacted_dict() → _redact: token "" fica "" · token real vira ***redacted***
   │
   ▼
5. Ciclo do daemon → _record_daily_history(..., retention_days=config.storage.retention_days)
   │
   ▼
6. usage_history.prune(keep_days=retention_days) → DELETE day < today-30 (default)
```

---

## Integration Points

| External System | Integration Type | Authentication |
|-----------------|-----------------|----------------|
| ESP32 `/health` | já existente, **inalterada** | token no header (inalterado) |
| Nenhuma nova | — | — |

O lote **não** adiciona chamada de rede: `check_protocol` no caminho live não sonda a placa.

---

## Testing Strategy

| Test Type | Scope | Files | Tools | Coverage Goal |
|-----------|-------|-------|-------|---------------|
| Unit | `_redact` vazio/presente; `prune` `keep_days`; `check_protocol` live/fixture | `tests/test_monitor_config.py`, `tests/test_usage_history.py`, `tests/test_doctor.py` | unittest + subTest | Todos os ATs de comportamento |
| Integration | daemon → prune com config; doctor CLI live/fixture | `tests/test_doctor.py` | unittest + stubs (padrão da casa) | AT-004, AT-008, AT-009, AT-010 |
| Docs (grep) | 4 provedores, 3.11, reservas, enum na SPEC | inspeção no BUILD | grep | AT-001, AT-002, AT-003, AT-006, AT-007, AT-013, AT-014 |

**Cobertura dos acceptance tests:** AT-001..AT-015 mapeados — AT de docs são verificados
por grep no BUILD (sem teste automatizado para prosa), AT de comportamento têm teste.

---

## Error Handling

| Error Type | Handling Strategy | Retry? |
|------------|-------------------|--------|
| `_redact` recebe `None` | Retorna `None` sem mascarar (campo sem valor) | Não |
| `prune` com `keep_days` inválido (negativo) | Mantém comportamento atual do `timedelta`; sem validação nova (YAGNI) | Não |
| `doctor` sem fixture e sem device | Já tratado: `check_device` WARN; `check_protocol` declara reserva independentemente | Não |
| Fixture ausente/inválida | `_load_fixture` já levanta `ValueError`; inalterado | Não |

---

## Configuration

| Config Key | Type | Default | Description |
|------------|------|---------|-------------|
| `storage.retention_days` | int | 30 | Agora **efetivo** no prune (era decorativo) |
| `storage.hourly_retention_days` | int | 365 | Reserva — sem consumidor (documentado) |
| `transport.prefer_websocket` | bool | true | Reserva — sem consumidor (documentado) |
| `daemon.role` | str | "standalone" | Reserva — sem consumidor (documentado) |
| `usage.commandcode_context_window` | int | 0 | Já presente no `EXAMPLE_TOML`; AT-013 trava regressão |

---

## Security Considerations

- `_redact` continua mascarando **todo** valor sensível não vazio; a única mudança é não marcar o vazio. O valor real nunca entra em stdout — AT-011 cobre.
- Nenhum novo caminho lê `secrets.h`, `auth.json` ou o token.
- `check_protocol` deixa de sugerir uma sonda que não existe; não abre porta nem autenticação.
- `check_secrets.py` intocado (mesmo conjunto de arquivos, mesma redação).

---

## Observability

| Aspect | Implementation |
|--------|----------------|
| Logging | Inalterado. `doctor` mantém o formato `STATUS code message` |
| Metrics | N/A — projeto local, sem métricas |
| Tracing | N/A |

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-09-19 | design-agent | Initial version a partir de `DEFINE_HIGIENE_CIRCUITOS.md`; três decisões em aberto fechadas |

---

## Next Step

**Ready for:** `/ship .claude/sdd/features/DEFINE_HIGIENE_CIRCUITOS.md`
