# DEFINE: Alerta escalonado + snooze + toast no PC

> O painel passa a dizer **há quanto tempo** uma sessão espera por você, não apenas que
> alguma espera — e alcança você quando não está olhando para a mesa

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | ALERTA_ESCALONADO |
| **Date** | 2026-09-08 |
| **Author** | define-agent |
| **Status** | ✅ Complete (Built) |
| **Clarity Score** | 15/15 |
| **Input** | `.claude/sdd/features/BRAINSTORM_ALERTA_ESCALONADO.md` (`brainstorm_document`) |
| **Roadmap** | `docs/ROADMAP.md` item #1 |

---

## Problem Statement

O painel sinaliza que uma sessão depende de você, mas não que ela já espera demais: um
`perm` de 10 segundos e um de 40 minutos produzem exatamente o mesmo pixel — e nada
sinaliza quando você não está olhando para a mesa. O custo é tempo de agente parado sem
ninguém perceber, agravado à noite, quando `BRIGHTNESS_NIGHT 60` torna o alerta atual
quase invisível.

---

## Target Users

| User | Role | Pain Point |
|------|------|------------|
| Operador na mesa | Dono do painel, roda 3 agentes em paralelo | Vê que *algo* espera, mas não distingue urgência; descobre tarde que um agente está travado há minutos |
| Operador longe da mesa | Mesmo operador, fora da sala | O painel pulsa para ninguém; nenhum canal alcança quem saiu |
| Operador à noite | Mesmo operador, após as 22h | O modo noturno reduz o brilho a 60/255 e o alerta se dissolve no escuro |

> Escopo single-machine decidido em 2026-09-07: há **um** operador, em três contextos de
> uso com dores distintas. A ausência de outras personas é uma restrição decidida, não
> uma lacuna de requisito.

---

## Goals

| Priority | Goal |
|----------|------|
| **MUST** | Derivar severidade (`none`/`warning`/`critical`/`expired`) no daemon, a partir dos três campos de `AlertSettings`, e enviá-la como campo aditivo do `POST /sessions` |
| **MUST** | Agregar severidades concorrentes pela **pior** (`critical` > `expired` > `warning` > `none`), espelhando o `STATE_PRIORITY` existente |
| **MUST** | Escalar o pulso de backlight por amplitude e frequência, com **zero invalidação LVGL** |
| **MUST** | Tornar o crítico perceptível no modo noturno (furar o nível base de 60) |
| **MUST** | Limitar procedência inferida ao teto `warning`, sem nunca disparar toast |
| **MUST** | Sinalizar `perm` cuja marca expirou aos 600s como `expired`, nunca deixá-lo cair para `free` em silêncio |
| **MUST** | Silenciar pulso e toast por `snooze_minutes` ao toque no header, cobrindo a janela inteira sem exceção |
| **SHOULD** | Disparar toast nativo uma vez ao cruzar `critical` (PowerShell no Windows, `notify-send` no Linux) |
| **SHOULD** | Indicar o mudo no relógio do header (`14:32 · mudo 12m`) |
| **COULD** | Distinguir `expired` por cadência de pulso duplo, sem depender de cor |

**Nota de prioridade.** O toast é `SHOULD`, não `MUST`, apesar de responder à segunda
metade do problema: é a única parte com superfície dependente de SO e o painel entrega
valor sem ela — existe workaround (o próprio painel). Seu comportamento foi confirmado na
pergunta 3 do brainstorm, então está **em escopo**; apenas não bloqueia o MVP.

---

## Success Criteria

- [ ] Os **3** campos de `AlertSettings` (`warning_after_s`, `critical_after_s`, `snooze_minutes`) passam de zero para ≥1 consumidor cada, com efeito observável no painel.
- [ ] Razão de período entre `warning` e `critical` ≥ **2,5×** e razão de amplitude ≥ **2×** — proxy numérico da distinguibilidade a olho, sem cor, a 2 metros.
- [ ] No modo noturno, o pico do pulso `critical` atinge ≥ **200/255**, contra o base de 60.
- [ ] `maxUpdateMs` reportado por `GET /diag` **não aumenta** em relação à medição pré-feature (pulso não invalida tela).
- [ ] Alterar `critical_after_s` no `monitor.toml` muda o comportamento em ≤ **1 ciclo do daemon** (~5s), com **0** reflash.
- [ ] Toque no header silencia pulso e toast por exatamente `snooze_minutes`, com indicação visível durante **100%** da janela.
- [ ] Toast dispara **exatamente 1×** por par (sessão, estado) que cruza `critical`; **0** toasts originados de procedência inferida.
- [ ] `perm` que atinge 600s ainda travado permanece sinalizado (`expired`) em **100%** dos casos; **0** quedas silenciosas para `free`.
- [ ] Função de severidade é pura e coberta por pytest, com fixture derivada do event store real; suíte segue em **100%** de aprovação.
- [ ] Firmware sem suporte ao campo novo continua aceitando o payload (**0** respostas 422 por causa de `severity`).

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | Warning (happy path) | Sessão `perm` de procedência estruturada, `elapsed = 0` | `elapsed` cruza `warning_after_s` (90s) | Severidade vira `warning`; pulso passa a ~2000ms com amplitude base ±30%; nenhum toast |
| AT-002 | Crítico + toast | Sessão em `warning` estruturado | `elapsed` cruza `critical_after_s` (300s) | Severidade vira `critical`; pulso ~700ms entre 40 e 255; **um** toast disparado no PC |
| AT-003 | Teto de procedência | Sessão Codex sem hook, `diagnostic = "no_structured_event"`, estado `ask` | `elapsed` cruza 300s | Severidade permanece `warning`; **nenhum** toast |
| AT-004 | Marca de `perm` expirada | Sessão em `critical` por marca de hook | `elapsed` atinge `PERM_MARKER_MAX_AGE_S` (600s) | Severidade vira `expired`; card exibe roxo + `perm?`; pulso continua; estado **não** vira `free` |
| AT-005 | Snooze silencia | Pulso ativo em `critical`; relógio marcando 14:00 | Toque no header | Pulso desliga; relógio mostra `14:00 · mudo 15m`; daemon lê `GET /snooze` e suprime toast |
| AT-006 | Mudo é mudo | Snooze ativo desde 14:00, janela de 15min | Sessão diferente cruza `critical` às 14:02 | Pulso permanece desligado e nenhum toast dispara até 14:15 |
| AT-007 | Agregação pela pior | Sessão A em `warning`, sessão B em `critical` | Ciclo de update do painel | Pulso usa os parâmetros de `critical` |
| AT-008 | Agregação com `expired` | Sessão A em `warning`, sessão B em `expired` | Ciclo de update | Pulso usa os parâmetros de `expired` (que perde para `critical`, ganha de `warning`) |
| AT-009 | Crítico no escuro | Hora local 23:00, base noturno 60 | Sessão cruza `critical` | Pico do pulso ≥ 200/255; o tick de 30s de `apply_schedule` **não** derruba o pulso |
| AT-010 | Limiar sem reflash | Painel em operação, firmware inalterado | `critical_after_s` muda para 120 no `monitor.toml` e o daemon relê | Escalada passa a ocorrer aos 120s, sem regravar firmware |
| AT-011 | Toast não repete | Toast já disparado para (sessão X, `perm`) | Sessão X segue em `critical` por 10 minutos | Nenhum toast adicional para o mesmo par |
| AT-012 | Retrocompatibilidade | Firmware antigo, sem conhecimento de `severity` | Daemon envia payload com o campo novo | Payload aceito (2xx); campo ignorado; **nenhum** 422 |
| AT-013 | Sem alerta, sem pulso | Nenhuma sessão em `ask`/`perm` | Ciclo de update | Backlight estável no nível base do horário; comportamento idêntico ao atual |
| AT-014 | Snooze expira | Snooze ativo, sessão segue em `critical` | Janela de `snooze_minutes` termina | Pulso retoma no nível de severidade vigente; indicação de mudo desaparece do relógio |

---

## Out of Scope

- Buzzer, LED RGB ou qualquer hardware adicional (decidido: só software).
- Snooze por sessão — o pulso é global, o snooze acompanha.
- Toast no `warning`; toast repetido; toast rompendo o snooze.
- Renovar a marca de `perm` por heurística de transcript.
- Limiar por agente ou por projeto.
- Botão "silenciar" na tela de detalhe.
- Aprovar permissões pelo próprio painel (painel mostra, não age).
- Alerta agregado de múltiplas máquinas (multi-node descartado pelo escopo).
- Histórico de quantas vezes cada sessão escalou — é o item #4 do roadmap.
- Calibração empírica dos limiares — depende do item #4.
- Correção da divergência `RETENTION_DAYS` (35) vs `retention_days` (30) — dívida vizinha, pertence ao item #2 do roadmap.

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Technical | Tools de PC só com **stdlib** (regra 2 do `CLAUDE.md`) | O toast sai por `subprocess` chamando PowerShell / `notify-send`; nada de dependência externa |
| Technical | `POST /sessions` **aditivo** (regra 3) | `severity` é campo novo opcional; firmware antigo precisa continuar aceitando |
| Technical | Render **FULL** — invalidar a tela custa um frame de 307KB | O pulso não pode passar por LVGL; vai por PWM do backlight |
| Technical | `PERM_MARKER_MAX_AGE_S = 600s` é constante de segurança | A feature se adapta a ela (severidade `expired`); a constante não muda |
| Technical | `HTTP_MAX_BODY_BYTES = 16384` | O campo novo (~25 B × ≤6 sessões) cabe com folga, mas o orçamento existe |
| Technical | Hooks em caminhos estáveis (regra 4) | `notify.py` é módulo do daemon, **não** hook — nenhum caminho instalado muda |
| Resource | Sem hardware novo; sem admin no PC | Escalada usa só display e PWM; toast roda em escopo de usuário |
| Scope | Single-machine | Nenhuma agregação entre nós |

---

## Technical Context

| Aspect | Value | Notes |
|--------|-------|-------|
| **Deployment Location** | `tools/` (severidade + `notify.py`); `src/drivers/` (base + pulso PWM); `src/ui/` (toque no header, indicação de mudo, card `expired`); `src/sessions/` (`GET /snooze`, NVS) | Feature atravessa daemon e firmware; `tools/README.md` precisa da linha do módulo novo |
| **KB Domains** | `python`, `testing` | Nenhuma das 27 domains de `.claude/kb/` cobre LVGL, embedded ou UX de alerta. A confiança das decisões vem do **codebase** (0.80), não de KB — o Design não deve esperar padrão de KB para o lado do firmware |
| **IaC Impact** | None | Projeto sem infraestrutura de nuvem |

---

## Data Contract (if applicable)

Não aplicável. A feature não introduz pipeline, ETL nem fonte de dados nova: consome
campos que o daemon já calcula (`state`, `elapsed`, procedência) e persiste um único
escalar na placa (`snooze_until`, em NVS).

---

## Assumptions

| ID | Assumption | If Wrong, Impact | Validated? |
|----|------------|------------------|------------|
| A-001 | 90s e 300s são limiares úteis na prática | Alerta vira ruído (cedo demais) ou chega tarde. Correção é editar `monitor.toml`, sem código | [ ] Não — **não existe ground truth**; o event store guarda só o último evento por sessão. Item #4 do roadmap produzirá o dado |
| A-002 | Pulso de PWM a ~70ms é perceptível, não causa flicker desagradável nem estresse no LEDC | Rever período e amplitude; possivelmente subir o passo | [ ] Não — exige validação em hardware |
| A-003 | PowerShell está disponível e permitido para toast no Windows 11; `notify-send` presente no Linux alvo | Toast falha em silêncio; precisaria de fallback e de uma checagem no `doctor` | [ ] Não |
| A-004 | Uma escrita de NVS por toque de snooze não gera desgaste relevante | Mover `snooze_until` para RAM e aceitar perder o mudo no reboot | [ ] Não |
| A-005 | Firmware antigo ignora campo desconhecido no payload sem rejeitar | Quebra de retrocompatibilidade; daemon precisaria negociar versão | [x] **Sim** — `handle_sessions_post` (`session_transport.cpp:222-285`) valida apenas `id`, `state`, `tool` e `elapsed` por whitelist e ignora campos extras |
| A-006 | O toque no header não conflita com nenhum gesto existente | Redesenhar o alvo do snooze | [x] **Sim** — `build_header` (`ui_dashboard.cpp:264-301`) não registra nenhum event callback |

---

## Clarity Score Breakdown

| Element | Score (0-3) | Notes |
|---------|-------------|-------|
| Problem | 3 | Uma frase, com quem sofre, o mecanismo (mesmo pixel para 10s e 40min) e o agravante medido (`BRIGHTNESS_NIGHT 60`) |
| Users | 3 | Três contextos de uso com dores distintas; a existência de um único operador é restrição decidida, documentada |
| Goals | 3 | 10 metas com MoSCoW atribuído e a razão do `SHOULD` do toast explicitada |
| Success | 3 | 10 critérios, todos com número ou contagem; a distinguibilidade perceptual ganhou proxy numérico (2,5× período, 2× amplitude) |
| Scope | 3 | 11 exclusões explícitas herdadas do YAGNI, mais os 2 vãos fechados nesta fase (agregação, snooze vs escalada nova) |
| **Total** | **15/15** | |

**Por que 15 e não menos.** O input era um `brainstorm_document` com 12 decisões já
registradas e 4 validações do usuário; a nota alta reflete isso, não ausência de risco.
O risco desta feature está no registro de suposições — quatro delas seguem **não
validadas**, com A-001 (limiares sem ground truth) como a mais consequente.

---

## Open Questions

Nenhuma bloqueante para o Design. Os dois vãos abertos pelo brainstorm foram fechados
nesta fase:

- **Agregação de severidade** → pior severidade vence, na ordem `critical` > `expired` > `warning` > `none`. `critical` supera `expired` porque é sinal exato vivo, e uma admissão de ignorância não deve gritar mais alto que um sinal válido.
- **Snooze versus escalada nova** → "mudo é mudo": o silêncio cobre a janela inteira, sem exceção. Mantém a decisão nº 6 do brainstorm (snooze global) sem bookkeeping por sessão, ao custo aceito de até 15 minutos de cegueira.

Para o Design resolver (não são lacunas de requisito):

- Nome e vocabulário exatos do campo novo no payload.
- Onde vive o tick de ~70ms do pulso: `loop()` do `main.cpp` ou timer dedicado.
- Como o `doctor` passa a checar a disponibilidade do canal de toast (A-003).

---

## Contract Gate

`tools/spec-linter/` **não existe neste repositório** — o componente referenciado pelo
`contract_enforcement` do `WORKFLOW_CONTRACTS.yaml` e pelo skill `sdd-define` não está
presente. Conforme o `exit_code_contract` do próprio contrato, linter indisponível
equivale a **exit 2 (ERROR)**, cuja regra é *"record a VISIBLE skip and proceed — never
assume PASS on exit 2"*.

- **Verdict:** não obtido (linter ausente).
- **Ação:** skip registrado visivelmente; conformidade verificada manualmente contra as 12 seções obrigatórias do template — todas presentes.
- **Nunca assumido:** PASS.

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-09-08 | define-agent | Versão inicial, extraída de `BRAINSTORM_ALERTA_ESCALONADO.md`; 2 vãos de requisito fechados (agregação de severidade, snooze vs escalada nova); A-005 e A-006 validados contra o código |
| 1.1 | 2026-09-08 | design-agent | Status → `✅ Complete (Designed)`. A fase Design registrou **tensão** com o critério de `expired`: a Decisão 2 do `DESIGN_ALERTA_ESCALONADO.md` limita `expired` a 20 min (marca órfã produziria pulso eterno), então "0 quedas silenciosas para `free`" passa a valer *enquanto a evidência é utilizável*. Se o recorte não servir, rode `/agentspec:iterate` neste documento |

---

## Next Step

**Ready for:** `/ship .claude/sdd/features/DEFINE_ALERTA_ESCALONADO.md`

> Antes do ship: validar em hardware AT-005, AT-009 e AT-014 (percepcao
> visual do pulso, do critico no modo noturno e do rotulo de mudo). Ver
> `.claude/sdd/reports/BUILD_REPORT_ALERTA_ESCALONADO.md`.
