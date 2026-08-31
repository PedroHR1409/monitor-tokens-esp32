# DESIGN: Dados do OpenCode — branch de worktree, contexto e nomenclatura por branch

> Technical design for implementing DADOS_OPENCODE_BRANCH_E_CONTEXTO

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | DADOS_OPENCODE_BRANCH_E_CONTEXTO |
| **Date** | 2026-08-31 |
| **Author** | design-agent |
| **DEFINE** | [DEFINE_DADOS_OPENCODE_BRANCH_E_CONTEXTO.md](./DEFINE_DADOS_OPENCODE_BRANCH_E_CONTEXTO.md) |
| **Status** | ✅ Shipped |
| **Design Confidence** | 0,95 (bug reproduzido no filesystem; correção no padrão existente) |

---

## Architecture Overview

```text
[worktree dir]                      [main repo dir]
  .git  (ARQUIVO)                     .git/ (pasta)
   └─ "gitdir: <repo>/.git/            └─ HEAD → refs/heads/...
        worktrees/<nome>"   ──┐
                           ▼
  read_git_branch(cwd):            (session_meta.py)
    .git pasta?  → .git/HEAD                       (como hoje)
    .git arquivo?→ parse "gitdir:" → <gitdir>/HEAD → branch do worktree  (NOVO)
                           │
                           ▼
  scan_* (session_daemon.py + opencode_sessions.py):
    display = branch se branch ∉ {main, master, ""} senão projeto   (NOVO)
    "project"/"full"/"name" = display
                           │
                           ▼
  opencode_sessions: ctxPct = tokens / (ctx_window ou DEFAULT 128k)  (NOVO)
```

---

## Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| `session_meta.read_git_branch` (modif.) | Suporte a worktree: `.git` arquivo → gitdir → HEAD | Python stdlib (`Path`) |
| `session_state.session_display_name` (novo) | Regra única de nome: branch não-principal vence o projeto | Python stdlib |
| `session_daemon.scan_*` (modif.) | Aplica a regra nas 3 fontes (Claude/Codex/OpenCode) | Python stdlib |
| `usage_top` (modif.) | Mesma regra nos nomes do pódio | Python stdlib |
| `opencode_sessions` (modif.) | Default de contexto 128000 quando config = 0 | Python stdlib |

---

## Key Decisions

### Decision 1: gitdir do worktree como fonte do HEAD

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-31 |

**Context:** Em worktrees, `.git` é um arquivo (`gitdir: <repo>/.git/worktrees/<nome>`);
`read_git_branch` hoje só lê `<dir>/.git/HEAD` (pasta) → "sem git".

**Choice:** Se `<dir>/.git` for arquivo: ler o conteúdo, extrair o caminho após
`gitdir:`, resolver (absoluto ou relativo ao dir) e ler `<gitdir>/HEAD`. Erros caem
nos fallbacks atuais ("sem git").

**Rationale:** É exatamente o mecanismo do próprio git; zero dependências; beneficia
Claude, Codex e OpenCode na mesma função.

**Alternatives Rejected:**
1. Rodar `git -C <dir> branch --show-current` — subprocess viola o perfil de custo do scan (5s)
2. Procurar worktrees no repo principal — frágil e desnecessário (o gitdir aponta direto)

**Consequences:**
- `read_git_branch` ganha ~10 linhas; fallbacks preservados (AT-002/003)

---

### Decision 2: Regra de nome centralizada em um helper único

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-31 |

**Context:** Cada scan monta o nome de forma própria (Claude: pasta do projeto;
Codex: thread_name; OpenCode: basename/title) — a regra de branch teria que ser
repetida 3x.

**Choice:** `session_display_name(project, branch)` em `session_state.py`:
`branch` (sem acentos) quando ∉ {"", "main", "master"} (case-insensitive); senão
`project`. Aplicada nas 3 scans e no `usage_top` (pódio herda a identidade).

**Rationale:** Regra única testável; pódio e cards nunca discordam.

**Alternatives Rejected:**
1. Regra inline em cada scan — 3 implementações para divergir com o tempo
2. Nome = projeto + sufixo de branch — truncamento em 10 chars viraria ruído

**Consequences:**
- Cards de trabalho em feature branch mostram a branch (ex.: `feat/27816-remo`)
- Detalhe continua mostrando branch e projeto completos

---

### Decision 3: Contexto OpenCode — 128000 como default quando config = 0

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-08-31 |

**Context:** `usage.opencode_context_window = 0` (não configurado) zera o ctxPct —
"desconhecido" de propósito, mas inútil na prática.

**Choice:** `DEFAULT_CONTEXT_WINDOW = 128000` em `opencode_sessions.py`; o scan usa
`ctx_window if ctx_window > 0 else DEFAULT`. Qualidade da métrica: `measured` com
config explícita, `estimated` com o default (honestidade do painel preservada).
`0` continua válido explicitamente? Não: 0 = "use default" (simplifica; override
positivo para casos específicos).

**Rationale:** O operador quer o % preenchido; 128k é a janela típica dos modelos
GLM/DeepSeek em uso; aproximado e ajustável sem deploy.

**Alternatives Rejected:**
1. Permanecer vazio até configurar — é exatamente o problema relatado
2. Tabela por modelo — sem fonte autoritativa local (YAGNI)

**Consequences:**
- `diagnostic` "no_context_window" desaparece dos payloads OpenCode

---

## File Manifest

| # | File | Action | Purpose | Agent | Dependencies |
|---|------|--------|---------|-------|--------------|
| 1 | `tools/session_meta.py` | Modify | `read_git_branch` worktree-aware (gitdir) | @python-developer | None |
| 2 | `tools/session_state.py` | Modify | `session_display_name(project, branch)` | @python-developer | None |
| 3 | `tools/session_daemon.py` | Modify | Aplica a regra nas scans Claude/Codex | @python-developer | 1, 2 |
| 4 | `tools/opencode_sessions.py` | Modify | Default de contexto 128k + regra de nome | @python-developer | 1, 2 |
| 5 | `tools/usage_top.py` | Modify | Regra de nome nos nomes do pódio | @python-developer | 1, 2, 3 |
| 6 | `tests/test_session_meta.py` (ou novo) | Modify/Create | AT-001..003 (worktree/gitdir fixtures) | @test-generator | 1 |
| 7 | `tests/test_opencode_sessions.py`, `tests/test_session_daemon.py` | Modify | AT-004..008 (contexto, regra de nome nas 3 fontes) | @test-generator | 2-4 |
| 8 | `docs/SPEC.md`, `README.md` | Modify | Default de contexto + regra de nome documentadas | @code-documenter | 1-5 |
| 9 | `pytest` + `pio run` + flash | Verify | ATs na placa (branch/contexto/nome) | @ci-cd-specialist | 1-8 |

**Total Files:** 5 código + 2 testes + 2 docs + 1 verificação

---

## Agent Assignment Rationale

| Agent | Files Assigned | Why This Agent |
|-------|----------------|----------------|
| @python-developer | 1-5 | Daemon stdlib; convenções já estabelecidas nas iterações anteriores |
| @test-generator | 6, 7 | Fixtures de worktree/gitdir e casos da regra de nome |
| @code-documenter | 8 | SPEC/README |
| @ci-cd-specialist | 9 | Build/flash/hardware |

---

## Code Patterns

### Pattern 1: Worktree via gitdir (stdlib)

```python
git_entry = base / ".git"
if git_entry.is_file():                      # worktree: aponta para o gitdir real
    raw = git_entry.read_text(errors="replace").strip()
    if raw.startswith("gitdir:"):
        gitdir = Path(raw.split(":", 1)[1].strip())
        if not gitdir.is_absolute():
            gitdir = base / gitdir
        head = gitdir / "HEAD"               # <repo>/.git/worktrees/<nome>/HEAD
```

### Pattern 2: Regra de nome única

```python
MAIN_BRANCHES = {"main", "master"}

def session_display_name(project: str, branch: str) -> str:
    b = strip_accents(branch or "").strip()
    if b and b.lower() not in MAIN_BRANCHES:
        return b                              # fix-28796-ajustes / feat/27816-...
    return project                            # monitor-tokens-esp32
```

### Pattern 3: Contexto com default honesto

```python
DEFAULT_CONTEXT_WINDOW = 128000
window = ctx_window if ctx_window > 0 else DEFAULT_CONTEXT_WINDOW
quality = "measured" if ctx_window > 0 else "estimated"   # metric_value
```

---

## Data Flow

```text
1. Sessão OpenCode no worktree → directory com `.git` arquivo
2. read_git_branch: gitdir → HEAD do worktree → "fix-28796-ajustes"
3. session_display_name(projeto, branch) → "fix-28796-ajustes" (não-principal)
4. Payload: name/project/full = display; branch = correta; ctxPct = tokens/128k
5. Placa: card com a branch; detalhe com branch + contexto
```

---

## Integration Points

Mesmos coletores; nenhuma dependência nova. O benefício se estende a Codex
(worktrees) e Claude automaticamente pela função compartilhada.

---

## Testing Strategy

| Test Type | Scope | Files | Tools | Coverage Goal |
|-----------|-------|-------|-------|---------------|
| Unit | read_git_branch: worktree (gitdir abs/rel), pasta, sem git, detached | `tests/test_session_meta.py` | pytest + fixtures tmp | AT-001..003 |
| Unit | session_display_name: branch main/master/vazia/normal | `tests/test_session_daemon.py` (ou session_state) | pytest | AT-006/007 |
| Unit | Contexto: default 128k, override, qualidade estimated/measured | `tests/test_opencode_sessions.py` | pytest + fixture db | AT-004/005 |
| Unit | Integração: scan OpenCode com directory=worktree → name=branch | `tests/test_opencode_sessions.py` | pytest | AT-008 |
| E2E Hardware | Cards fix/feat/monitor na placa; detalhe com branch+contexto | placa | manual | ATs visuais |
