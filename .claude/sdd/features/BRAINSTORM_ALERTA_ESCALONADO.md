# BRAINSTORM: Alerta escalonado + snooze + toast no PC

> Sessão exploratória do item #1 do `docs/ROADMAP.md` — ligar os três parâmetros de
> alerta que já estão declarados em `monitor.toml` e nunca tiveram consumidor

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | ALERTA_ESCALONADO |
| **Date** | 2026-09-08 |
| **Author** | brainstorm-agent |
| **Status** | ✅ Complete (Defined) |
| **Origem** | Análise de features novas do repo (2026-09-07) → `docs/ROADMAP.md` item #1 |

---

## Initial Idea

**Raw Input:** "Escalada visual de alerta para sessões paradas em `ask`/`perm`, com
snooze por toque e notificação nativa no PC. Escopo single-machine, só software (sem
buzzer/LED novo)." Refinado na primeira pergunta para **"pulse a tela como um todo"**.

**Context Gathered:**

- O alerta hoje é **binário**: `update_alert()` (`src/ui/ui_dashboard.cpp:1142`) elege o
  pior estado (`PERM` > `ASK`) e pulsa uma borda de 4px em período fixo de 600ms
  (`theme::ALERT_PERIOD_MS`). Não existe nenhuma noção de *há quanto tempo* — um `perm`
  de 10s e um de 40min produzem o mesmo pixel.
- `AlertSettings` (`tools/monitor_config.py:78-82`) declara `warning_after_s = 90`,
  `critical_after_s = 300` e `snooze_minutes = 15`. Uma varredura no repo inteiro não
  encontrou **nenhum consumidor** dos três campos.
- O render do painel é **FULL**: a SPEC (seção "Performance: a causa raiz do drift")
  registra que invalidar a tela 1x/s custava um frame de 307KB por segundo e causava
  drift no timer; a fase 4 criou os guards `set_text_if`/`set_color_if` para evitá-lo.
- Os dois gestos de toque já têm dono: toque curto abre detalhe, toque longo esconde a
  sessão (`card_event_cb`, `ui_dashboard.cpp:347`).
- A tela de detalhe tem decisão explícita contra botões: *"Qualquer toque fecha: sem
  botao dedicado, que gastaria espaco e exigiria mira"* (`ui_dashboard.cpp:940`).
- `device_backlight_apply_schedule()` roda no tick lento de 30s (`src/main.cpp:76`) e
  escreve o brilho pelo relógio **sem condição** — atropelaria qualquer alerta que
  mexesse no backlight.
- `perm` **nunca** nasce de inferência: `session_state.py:49` é categórico — *"Sem hook
  ativo, `perm` simplesmente nao acontece — e melhor nao afirmar do que afirmar errado."*
- `PERM_MARKER_MAX_AGE_S = 600.0` (`session_state.py:58`) expira a marca do hook em 10
  minutos, para proteger o caso do Claude Code morrer com o diálogo aberto.
- O daemon **já sabe a procedência** de cada estado: `structured = snapshot.last_event_at
  is not None` (`session_daemon.py:271`) e `diagnostic = "no_structured_event"`
  (`session_daemon.py:355`) para sessões sem evento de hook.

**Technical Context Observed (for Define):**

| Aspect | Observation | Implication |
|--------|-------------|-------------|
| Likely Location | `tools/` (severidade, notify), `src/ui/` + `src/drivers/` + `src/sessions/` (pulso, snooze, endpoint) | Feature atravessa daemon e firmware |
| Relevant KB Domains | `python`, `testing` | Nenhuma das 27 domains cobre LVGL/embedded/UX de alerta — confiança vem do codebase, não de KB |
| IaC Patterns | N/A | Projeto sem infraestrutura de nuvem |

---

## Discovery Questions & Answers

| # | Question | Answer | Impact |
|---|----------|--------|--------|
| 1 | O que muda na tela ao cruzar warning e crítico? | **"Pulse a tela como um todo"** → pulso de **backlight**, escalando amplitude e frequência | Descarta borda e fundo LVGL; custo de render zero; resolve o modo noturno de graça |
| 2 | Qual gesto faz o snooze? | **Toque no header** — snooze global, relógio indica o mudo | Único alvo grande e inerte (320×34); não toca nos dois gestos existentes nem contraria a decisão de "sem botão dedicado" |
| 3 | Quando o toast do PC dispara? | **Uma vez, no crítico**, por sessão e por estado; sem repetição | Painel = canal ambiente; toast = canal de exceção. Segue o princípio de "aviso só quando o diagnóstico muda" (`session_daemon.py:797`) |
| 4 | O que acontece quando a marca de `perm` expira (600s) com a sessão ainda travada? | **Admitir que não sabe**: vira severidade `expired`, card roxo + `perm?`, alerta continua | Sem isso, o alerta desiste aos 10min justamente no caso que mais precisava dele. Segue o precedente do `stale` |
| 5 | A escalada exige procedência estruturada para chegar ao crítico? | **Sim** — estado inferido tem teto em `warning` e nunca dispara toast | Mesma cultura de procedência explícita da cota (oficial vs estimado). Evita toast falso de Codex sem hook, onde `ask` significa só "arquivo tocado há <90s" |
| 6 | Como fixar 90s/300s sem ground truth? | **Default configurável**, calibrar no uso | Os dois valores já moram em `monitor.toml`; travar a feature por uma semana de medição para escolher dois números editáveis é economia ruim |

**Minimum Questions:** 3 · **Asked:** 6

---

## Sample Data Inventory

| Type | Location | Count | Notes |
|------|----------|-------|-------|
| Event store real | `~/.claude/monitor-ai-events.json` | 27 sessões (7,4 KB) | Distribuição medida: `ended: 14, free: 9, work: 3, ask: 1`. **Guarda só o último evento de cada sessão** — não há histórico de transições |
| Ground truth de tempo de resposta | — | **0** | **Não existe.** Nenhum registro de quanto tempo permissões passadas levaram para ser respondidas |
| Fixtures de teste existentes | `tests/fixtures/doctor/` | 3 | Só do `doctor`; nada de alerta/severidade |
| Código de referência | `tools/agent_events.py` (reducer determinístico), `src/sessions/id_list.cpp` (NVS + ida-e-volta com o daemon) | — | Padrões a reusar |

**How samples will be used:**

- O event store real vira fixture da função de severidade (formato e campos verificados, não inventados).
- `agent_events.py` é o modelo de reducer puro e testável para a função `(estado, elapsed, procedência) → severity`.
- `id_list.cpp` + `GET /hidden` é o padrão a copiar para o snooze (NVS na placa, daemon lê a cada ciclo).

**Lacuna registrada:** a ausência de ground truth é o motivo da resposta 6. O **item #4 do
roadmap** (tempo de agente bloqueado) é exatamente a instrumentação que produziria esse
dado — as duas features se alimentam: #1 precisa dos limiares, #4 os mede.

---

## Approaches Explored

### Approach A: Daemon decide severidade, firmware decide estética ⭐ Recommended

**Description:** O daemon calcula `severity` (`none`/`warning`/`critical`/`expired`) a
partir de estado, `elapsed` e procedência, e envia como campo aditivo no `POST /sessions`.
O firmware traduz severidade em amplitude e período do pulso de backlight. O snooze nasce
no toque, mora em NVS (`Preferences`) e o daemon o lê por `GET /snooze` para suprimir o toast.

**Pros:**
- Limiar muda no `monitor.toml` sem reflash.
- A regra de severidade existe **uma vez**, em Python, coberta por pytest.
- O protocolo fala vocabulário de domínio, não de apresentação.
- Reusa o ida-e-volta de `hidden`/`pinned`, já em produção.

**Cons:**
- Um campo novo no protocolo (aditivo — dentro da regra 3 do `CLAUDE.md`).
- Um endpoint novo no firmware (`GET /snooze`).

**Why Recommended:** mantém a regra num só lugar testável e o firmware dono da
apresentação. **Confiança 0.80** — evidência é o padrão `hidden`/`pinned` do próprio
repo; nenhuma KB do projeto cobre este domínio.

---

### Approach B: Firmware calcula, limiares em `config.h`

**Description:** O firmware já recebe `elapsed`; compara com constantes compiladas.

**Pros:**
- Zero mudança de protocolo.

**Cons:**
- Trocar um limiar exige reflash.
- O toast nasce no PC, então o daemon recalcularia a mesma regra de qualquer forma: a
  regra passaria a existir **duas vezes**, em C++ e em Python, com metade coberta por teste.
- É a própria divergência config↔código que esta feature existe para corrigir.

**Why not recommended:** duplica a regra de negócio nas duas linguagens.

---

### Approach C: Daemon manda os parâmetros do pulso prontos

**Description:** O payload carrega amplitude e período; o firmware só executa.

**Pros:**
- Ajustar a estética do pulso sem reflash.

**Cons:**
- Acopla o protocolo à UI: o contrato falaria de brilho e milissegundos em vez de domínio,
  e toda mudança visual viraria mudança de protocolo. Contraria o espírito da regra 3.

**Why not recommended:** troca uma flexibilidade pequena por acoplamento permanente.

---

## Selected Approach

| Attribute | Value |
|-----------|-------|
| **Chosen** | Approach A |
| **User Confirmation** | 2026-09-08 ("Sim, Approach A") |
| **Reasoning** | Regra única em Python e testável; protocolo em vocabulário de domínio; firmware dono da apresentação; reusa padrão já em produção |

---

## Spec consolidada (validada)

### Pulso (firmware)

`device_backlight_apply_schedule()` deixa de escrever o PWM diretamente e passa a definir
um **nível base** (dia 255 / noite 60). Um tick novo de ~70ms no loop principal modula o
PWM em torno desse base. Custo de render: **zero** — nenhuma invalidação LVGL.

| Severidade | Período | Amplitude | Observação |
|---|---|---|---|
| `none` | — | estável no base | comportamento atual |
| `warning` | ~2000ms | base ± 30% | perceptível, não incômodo |
| `critical` | ~700ms | 40 ↔ 255 | **fura o base noturno** |
| `expired` | pulso duplo + pausa | base ± 30% | cadência reconhecível sem cor |

### Severidade (daemon)

Função pura `(estado, elapsed, procedência) → severity`. `perm` e `ask` usam os mesmos
limiares — ambos bloqueiam o agente. Procedência inferida tem **teto em `warning`**.
Quando a marca de `perm` expira aos 600s vindo de `critical`, o resultado é `expired` em
vez de queda para `free`; o card exibe roxo + `perm?`.

### Snooze

Toque no header grava `snooze_until` em NVS (`Preferences`, padrão `id_list`). Enquanto
ativo: pulso desligado e o relógio do header mostra `14:32 · mudo 12m`. O daemon lê
`GET /snooze` a cada ciclo e suprime o toast.

### Toast

`tools/notify.py` novo, stdlib puro: `subprocess` chamando PowerShell no Windows e
`notify-send` no Linux. Dispara **uma vez** ao cruzar `critical`, por sessão e por estado.

---

## Key Decisions Made

| # | Decision | Rationale | Alternative Rejected |
|---|----------|-----------|----------------------|
| 1 | Pulso de **backlight**, não de fundo LVGL | Único mecanismo que atinge 100% da tela com custo de render zero; fundo LVGL reintroduziria os frames de 307KB que a fase 4 eliminou, e só apareceria nas calhas de 8px entre cards | Fundo via LVGL; borda intensificada |
| 2 | Escalada por **amplitude + frequência** do pulso | Duas dimensões perceptíveis sem cor, que o backlight oferece de graça | Escalada só por frequência |
| 3 | Snooze pelo **header** | Única superfície grande e inerte (320×34); não colide com curto/longo nem contraria "sem botão dedicado" | Duplo toque no card (touch resistivo a falsos toques); abrir detalhe = "eu vi" (silencia por acidente); botão no detalhe |
| 4 | Snooze **global**, não por sessão | O pulso é global (backlight = tela toda); snooze por sessão seria semanticamente incoerente com o sinal | Snooze por sessão |
| 5 | Toast **uma vez, no crítico** | Painel é o canal ambiente, toast é o de exceção. Repetição treina o operador a ignorar — princípio já aplicado em `session_daemon.py:797` | Toast no warning; toast repetido |
| 6 | Marca de `perm` expirada → severidade **`expired`** | Sem isso o alerta desiste aos 10min no exato caso que mais precisava dele. Segue o precedente do `stale`: "o painel admite que nao sabe, em vez de mentir" | Alerta acompanha o estado e simplesmente para |
| 7 | **Não** renovar a marca de `perm` por heurística | Reintroduziria a inferência tool_use-sem-resultado que a fase 4 removeu por produzir `perm` falso (caso medido de 191 horas) | Estender a vida da marca |
| 8 | Crítico exige **procedência estruturada** | `ask` inferido significa "arquivo tocado há <90s", não "há pergunta esperando". Mesma cultura de procedência explícita da cota | Escalar todo estado igual; não alertar estado inferido |
| 9 | `ask` e `perm` com os **mesmos limiares** | Os dois bloqueiam o agente; o que difere entre eles é procedência, não urgência | Limiares distintos por estado |
| 10 | Limiares como **default configurável** | Não há ground truth para calibrar; os valores já moram em config e o item #4 do roadmap produzirá o dado | Medir uma semana antes de implementar |
| 11 | Severidade calculada no **daemon** | Regra única, em Python, testável; o toast nasce no PC e precisaria dela de qualquer forma | Firmware calcula (regra duplicada em duas linguagens) |
| 12 | `apply_schedule` passa a definir **base**, não PWM final | Hoje o tick de 30s atropelaria o pulso em ≤30s | Alerta que não mexe no backlight |

---

## Features Removed (YAGNI)

| Feature Suggested | Reason Removed | Can Add Later? |
|-------------------|----------------|----------------|
| Buzzer / LED de alerta | Fora do escopo decidido (só software) | Yes (exige GPIO novo e solda) |
| Snooze por sessão | Incoerente com um pulso global | Yes |
| Toast no warning | Dobra o volume de notificação; o de 90s vira ruído num dia com várias sessões | Yes |
| Toast repetido até resolver | Exatamente o padrão que o daemon evita de propósito | No |
| Renovar marca de `perm` por heurística | Reintroduz bug removido na fase 4 | No |
| Limiar por agente ou por projeto | Um limiar global responde; nenhum pedido real | Yes |
| Botão "silenciar" na tela de detalhe | Contraria decisão registrada em `ui_dashboard.cpp:940` | No |
| Terceiro degrau de escalada | Dois degraus + `expired` já cobrem o caso | Yes |
| Aprovar a permissão pelo próprio painel | Escopo muito maior e superfície de risco (painel passa a agir, não só mostrar) | Yes |
| Alerta agregado de várias máquinas | Fora do escopo single-machine | No (depende de multi-node, descartado) |
| Histórico de quantas vezes escalou | É o item #4 do roadmap, não desta feature | Yes |

---

## Incremental Validations

| Section | Presented | User Feedback | Adjusted? |
|---------|-----------|---------------|-----------|
| Mecanismo do pulso (backlight vs LVGL) | ✅ | Backlight confirmado após evidência de custo de frame | Yes — recomendação inicial era borda intensificada |
| 6 perguntas de descoberta | ✅ | Todas respondidas com a opção recomendada | No |
| Comparação das 3 abordagens | ✅ | "Sim, Approach A" | No |
| Spec consolidada (pulso, severidade, snooze, toast, YAGNI) | ✅ | "Sim, está certa" | No |

**Minimum Validations:** 2 · **Completed:** 4

---

## Suggested Requirements for /define

### Problem Statement (Draft)

O painel sinaliza que uma sessão depende de você, mas não que ela já espera demais — um
`perm` de 10 segundos e um de 40 minutos produzem exatamente o mesmo pixel — e não
sinaliza nada quando você não está olhando para a mesa.

### Target Users (Draft)

| User | Pain Point |
|------|------------|
| Operador do painel (single-machine) | Descobre tarde que um agente está travado esperando aprovação; perde tempo de agente sem perceber |
| Operador longe da mesa | Painel pulsa para ninguém; nenhum canal alcança quem saiu da mesa |
| Operador à noite | `BRIGHTNESS_NIGHT 60` torna o alerta atual quase invisível a partir das 22h |

### Success Criteria (Draft)

- [ ] Os três campos de `AlertSettings` passam a ter consumidor real e efeito observável.
- [ ] Warning e crítico são distinguíveis a olho, sem cor, a 2 metros do painel.
- [ ] Crítico é perceptível no modo noturno (fura o base de 60).
- [ ] Pulso não adiciona nenhuma invalidação LVGL — sem regressão em `maxUpdateMs` do `/diag`.
- [ ] Mudar `critical_after_s` no `monitor.toml` altera o comportamento **sem reflash**.
- [ ] Toque no header silencia o pulso e o toast por `snooze_minutes`, com indicação visível.
- [ ] Toast dispara uma vez por sessão/estado; nunca a partir de estado inferido.
- [ ] `perm` que atinge 600s ainda travado permanece sinalizado como `expired`, não volta a `free`.
- [ ] Função de severidade é pura e coberta por pytest, com fixture derivada do event store real.

### Constraints Identified

- Tools de PC: **só stdlib** (regra 2 do `CLAUDE.md`) — o toast sai por `subprocess`.
- `POST /sessions` **aditivo** (regra 3) — campo novo não quebra firmware antigo.
- Render FULL: nada de invalidação periódica de tela.
- Hooks em caminhos estáveis (regra 4) — `notify.py` é módulo do daemon, não hook.
- Escopo single-machine; sem hardware novo.
- `PERM_MARKER_MAX_AGE_S = 600s` é constante de segurança: a feature se adapta a ela, não o contrário.

### Out of Scope (Confirmed)

- Buzzer, LED ou qualquer hardware adicional.
- Snooze por sessão; toast no warning; toast repetido.
- Aprovar permissões pelo painel.
- Alerta agregado de múltiplas máquinas.
- Calibração empírica dos limiares (fica no item #4 do roadmap).

---

## Session Summary

| Metric | Value |
|--------|-------|
| Questions Asked | 6 |
| Approaches Explored | 3 |
| Features Removed (YAGNI) | 11 |
| Validations Completed | 4 |
| Key Decisions Recorded | 12 |

---

## Next Step

**Ready for:** `/define .claude/sdd/features/BRAINSTORM_ALERTA_ESCALONADO.md`
