# BRAINSTORM: Multi-rede WiFi (REDE_PRINCIPAL + HOTSPOT_CELULAR)

> O painel passa a conhecer duas redes e alterna entre elas por prioridade, em vez
> de exigir reflash para trocar de Wi-Fi

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | MULTI_REDE_WIFI |
| **Date** | 2026-09-21 |
| **Author** | brainstorm-agent |
| **Status** | Ready for Define |
| **Origem** | Pedido direto do operador — "Quero manter o do REDE_PRINCIPAL e poder alternar entre o REDE_PRINCIPAL e HOTSPOT_CELULAR (Acesso Pessoal)" |

---

## Initial Idea

**Raw Input:** "Conectei o computador na minha rede de Acesso Pessoal do iPhone. Como
fazemos a configuração? Quero manter o do REDE_PRINCIPAL e poder alternar entre o REDE_PRINCIPAL e
HOTSPOT_CELULAR (Acesso Pessoal)."

**Context Gathered:**

- O firmware conhece **uma** rede: `WiFi.begin(WIFI_SSID, WIFI_PASSWORD)`
  (`src/sessions/session_transport.cpp:609`), com credenciais em `include/secrets.h`
  (gitignored). Trocar de rede hoje exige **reflash**.
- `WIFI_SSID` atual = `"REDE_PRINCIPAL"` (medido em `include/secrets.h`); a placa respondia em
  `192.168.2.165` nessa rede.
- O PC agora está no hotspot do iPhone: SSID **`HOTSPOT_CELULAR`**, IPv4 `172.20.10.3`,
  gateway link-local. A sub-rede do hotspot é `172.20.10.0/28`.
- **COM3** existe como "USB Serial Device" — provável painel ligado por USB, o que
  permite gravar e ler o serial.
- O boot bloqueia até `WIFI_CONNECT_TIMEOUT_MS = 15000` esperando o WiFi
  (`config.h:76`), e `session_transport_init()` roda **antes** de
  `ui_dashboard_init()` (`main.cpp:31,33`) — ou seja, a tela fica preta durante a
  espera. Duas redes ingênuas virariam 30s de tela preta.
- `session_transport.h:7` já documenta a intenção: *"Nao trava o boot: se o WiFi nao
  subir a tempo, segue e tenta reconectar em background."* O retry é de
  `WIFI_RETRY_INTERVAL_MS = 20000` (`session_transport.cpp:657-661`).
- O daemon tem host configurável e o **default já é `monitor-ai.local`**
  (`MonitorConfig.load`), o que dispensa editar config ao trocar de rede.
- `tools/check_secrets.py` varre `secrets.h` por defines que casem
  `SSID|PASSWORD|SECRET|TOKEN|API_KEY` e falha se o valor reaparecer em outro arquivo
  — as chaves novas entram na proteção automaticamente.
- `tests/test_production_contracts.py:30-35` exige `WIFI_SSID`/`WIFI_PASSWORD` em
  `secrets.example.h`; as chaves novas mantêm esses substrings.

**Technical Context Observed (for Define):**

| Aspect | Observation | Implication |
|--------|-------------|-------------|
| Likely Location | `include/secrets.h` + `include/secrets.example.h` (credenciais); `src/sessions/session_transport.cpp` (conexão e retry); `docs/SPEC.md` §5 | Sem daemon novo; firmware + docs |
| Relevant KB Domains | `python`, `testing` (para as verificações no PC) | **Nenhuma** das 24 domains cobre WiFi/embedded/C++ — a confiança vem do **codebase** (0.80) e da API do core ESP32, não de KB |
| IaC Patterns | N/A | Projeto sem nuvem |

---

## Discovery Questions & Answers

| # | Question | Answer | Impact |
|---|----------|--------|--------|
| 1 | Com as duas redes no alcance, em qual conectar? | **REDE_PRINCIPAL primeiro** (ordem de prioridade) | Fixa a política: a ordem do array manda, não o RSSI. Descarta `WiFiMulti` puro |
| 2 | Como o daemon acha o painel, que muda de IP? | **mDNS `monitor-ai.local`** (já é o default do toml) | Zero edição no PC ao trocar de rede; sem varredura |
| 3 | Quantas redes configuráveis? | **Exatamente 2** (REDE_PRINCIPAL + HOTSPOT_CELULAR) | Dois pares de defines; sem array genérico, sem NVS |
| 4 | Como provar que a alternância funciona? | **Gravar e ler o serial** (`pio device monitor`) | O critério de aceite é observável no log do firmware, não só "compila" |
| 5 | Abordagem e orçamento de boot? | **A** — tabela de 2 credenciais, boot **≤15s** | Mantém o não-bloqueante e evita tela preta dobrada |
| 6 | Critérios de aceite AT-001..AT-010? | **Sim** | Base do DEFINE |

**Minimum Questions:** 3 · **Asked:** 6

---

## Sample Data Inventory

| Type | Location | Count | Notes |
|------|----------|-------|-------|
| Credenciais atuais | `include/secrets.h` (gitignored) | 1 par | `WIFI_SSID "REDE_PRINCIPAL"`, `WIFI_PASSWORD` (valor não lido); `MONITOR_API_TOKEN` presente |
| Exemplo versionado | `include/secrets.example.h` | 1 par | Placeholders `NOME_DA_REDE`/`SENHA_DA_REDE`; base do teste de contrato |
| Rede ativa (PC) | `netsh wlan show interfaces` | 1 | SSID `HOTSPOT_CELULAR`; IPv4 `172.20.10.3`; gateway link-local |
| Rede alvo (REDE_PRINCIPAL) | `docs/ROADMAP.md` / logs antigos | — | Painel respondia em `192.168.2.165` |
| Porta serial | `COM3` ("USB Serial Device") | 1 | Candidata ao painel; **não confirmada** — a identificar no BUILD |
| Guard-rail | `tools/check_secrets.py` | — | Vai cobrir `WIFI_SSID_2`/`WIFI_PASSWORD_2` pelo regex |
| Teste de contrato | `tests/test_production_contracts.py:30-35` | 1 | Exige `WIFI_SSID`/`WIFI_PASSWORD` no exemplo |

**How samples will be used:**

- `secrets.h` real: base para adicionar o segundo par sem perder o primeiro
- Serial do firmware: **única** prova de AT-001/002/003/004/006 (o IP conectado é impresso)
- `check_secrets.py` e o teste de contrato: regressão de que nada vazou e o exemplo continua válido
- Rede `HOTSPOT_CELULAR` ativa: permite testar o fallback sem depender do REDE_PRINCIPAL estar no ar

---

## Approaches Explored

### Approach A: Tabela de credenciais + `WiFi.begin()` alternando ⭐ Recommended

**Description:** `secrets.h` ganha `WIFI_SSID_2`/`WIFI_PASSWORD_2`. O firmware guarda um
array de 2 credenciais na ordem de prioridade e usa `WiFi.begin()` (não-bloqueante)
apontando para a credencial atual; no retry de 20s, avança o índice quando a tentativa
falha. No boot, tenta REDE_PRINCIPAL dentro do orçamento e usa o restante para o HOTSPOT_CELULAR.

**Pros:**

- Nenhuma biblioteca nova — `WiFi.h` já está incluído
- Preserva o design não-bloqueante que a SPEC exige (render FULL não tolera travar o `loop()`)
- Implementa literalmente "REDE_PRINCIPAL primeiro" (o `WiFiMulti` escolheria por sinal)
- Orçamento de boot controlável (≤15s), sem regressão de tela preta

**Cons:**

- Mais código que o `WiFiMulti`
- A política de prioridade e a alternância são implementadas à mão, e precisam de teste em hardware

**Why Recommended:** confiança **0.80** — codebase + API do core, sem KB de embedded
(vide "Relevant KB Domains"). É a única das três que obedece à decisão nº 1 (prioridade
por ordem) sem trocar o comportamento de conexão por um `scan` bloqueante.

---

### Approach B: `WiFiMulti` do core

**Description:** `WiFiMulti wifiMulti; addAP(REDE_PRINCIPAL); addAP(HOTSPOT_CELULAR); wifiMulti.run(timeout)`.

**Pros:**

- Idiomático no ESP32-Arduino; menos linhas
- Conhecido por lidar bem com múltiplos APs

**Cons:**

- Escolhe por **sinal mais forte**, não por prioridade — contradiz a decisão nº 1
- `run()` faz *scan*, que bloqueia; no `loop()` isso arrisca hitch no render FULL
- No boot, mantém o comportamento bloqueante

**Why not recommended:** não obedece à ordem pedida e reintroduz o risco de travar o loop.

---

### Approach C: Credenciais em NVS + troca em runtime

**Description:** guardar as redes em NVS e trocar por comando serial ou portal cativo.

**Pros:**

- Troca de rede sem reflash; escala para N redes

**Cons:**

- Exige UI ou comando novo, e um caminho de configuração a manter
- Muito além do pedido ("alternar entre REDE_PRINCIPAL e HOTSPOT_CELULAR")

**Why not recommended:** YAGNI. Duas redes fixas resolvem o problema atual; virar N ou
NVS depois é evolução, não pré-requisito.

---

## Data Engineering Context

Não aplicável. A feature não toca pipeline, ETL ou fonte de dados: muda apenas como o
firmware escolhe a rede e como o daemon a encontra.

---

## Selected Approach

| Attribute | Value |
|-----------|-------|
| **Chosen** | Approach A — tabela de credenciais + `WiFi.begin()` alternando |
| **User Confirmation** | 2026-09-21 (pergunta de abordagem + checkpoints 1 e 2) |
| **Reasoning** | REDE_PRINCIPAL primeiro, sem lib nova, sem bloquear o loop, boot ≤15s |

---

## Key Decisions Made

| # | Decision | Rationale | Alternative Rejected |
|---|----------|-----------|----------------------|
| 1 | Prioridade por ordem (REDE_PRINCIPAL → HOTSPOT_CELULAR) | Pedido explícito; previsível | Sinal mais forte (`WiFiMulti`) · última que funcionou (sticky) |
| 2 | Daemon usa mDNS `monitor-ai.local` | Já é o default; resolve nas duas redes sem editar config | Lista de IPs por rede · varredura da sub-rede |
| 3 | Exatamente 2 redes | YAGNI; atende o pedido | Array de N · NVS/portal |
| 4 | Orçamento de boot ≤15s no total | `session_transport_init` roda antes do dashboard; 2×15s = tela preta dobrada | 15s por rede (30s) |
| 5 | Manter `WiFi.begin()` não-bloqueante | O render FULL e os guards da SPEC não toleram travar o `loop()` | `WiFiMulti.run()` com scan |
| 6 | Confirmar a COM3 antes de gravar | Gravar no dispositivo errado é risco evitável | Assumir que COM3 é o painel |

---

## Features Removed (YAGNI)

| Feature Suggested | Reason Removed | Can Add Later? |
|-------------------|----------------|----------------|
| Lista de N redes / array genérico | Duas bastam; generalizar sem necessidade | Sim |
| Credenciais em NVS + troca em runtime | Exige UI/comando novo; fora do pedido | Sim |
| Portal cativo de configuração | Infra nova inteira para um problema de 2 redes | Sim |
| Varredura de rede pelo daemon | mDNS resolve; varredura adiciona ruído e código | Sim |
| UI para escolher rede no painel | O painel não é terminal de configuração | Sim |
| Trocar `WiFi.begin` por `WiFiMulti` | Contradiz a prioridade e bloqueia o loop | Não (decisão fixada) |
| Alterar o protocolo HTTP / payload | Nada a ver com a escolha de rede | Não |
| `--host` novo no daemon | O default mDNS já cobre as duas redes | Não |
| Reconexão por `RSSI`/handoff entre APs | Fora do escopo; duas redes distintas, não mesh | Sim |

---

## Incremental Validations

| Section | Presented | User Feedback | Adjusted? |
|---------|-----------|---------------|-----------|
| Abordagem (A vs B vs C) + orçamento de boot + YAGNI | ✅ | "Sim, segue" | No |
| Critérios de aceite AT-001..AT-010 | ✅ | "Sim, escreve o BRAINSTORM" | No |
| Política de escolha da rede | ✅ | "REDE_PRINCIPAL primeiro" | No |
| Descoberta do painel pelo daemon | ✅ | "mDNS" | No |

**Minimum Validations:** 2 · **Completed:** 4

---

## Suggested Requirements for /define

### Problem Statement (Draft)

O painel conhece uma única rede Wi-Fi compilada em `secrets.h`, então mudar de rede
(REDE_PRINCIPAL para o hotspot do iPhone, e voltar) exige reflash e cabo USB a cada troca.

### Target Users (Draft)

| User | Pain Point |
|------|------------|
| Operador na mesa | Troca entre a rede de casa e o hotspot do celular; hoje cada troca pede reflash |
| Operador viajando | Leva o painel para outra rede sem notebook/PlatformIO à mão |

### Success Criteria (Draft)

- [ ] Com as duas redes no alcance, o painel conecta na **REDE_PRINCIPAL** em 100% dos boots
- [ ] Com só o **HOTSPOT_CELULAR** no alcance, conecta no hotspot; serial imprime IP `172.20.10.x`
- [ ] Sem nenhuma rede, o dashboard sobe em **≤15s** (medido no serial), sem regressão para 30s
- [ ] Queda de rede: reconecta sozinho em ≤ **20s** (intervalo de retry), alternando
- [ ] `monitor-ai.local` resolve nas duas redes; `GET /health` responde sem editar o `monitor.toml`
- [ ] `check_secrets.py` protege os **4** valores; **0** senhas em arquivos versionados
- [ ] Build sem `secrets.h` (CI) continua SUCCESS; suíte `pytest` verde

### Constraints Identified

- Firmware C++/ESP32-Arduino; nenhuma KB cobre embedded — confiança vem do codebase
- Não bloquear o `loop()` (render FULL; `session_transport_loop` é medido no `/diag`)
- `secrets.h` é gitignored: as credenciais **nunca** entram em arquivo versionado
- `session_transport.h` promete não travar o boot — a feature não pode quebrar isso
- Regra de segredos do `CLAUDE.md`: nada de senha em logs (o firmware não imprime senha)
- ESP32 é **2.4 GHz apenas** — o hotspot do iPhone precisa de "Maximizar Compatibilidade"

### Out of Scope (Confirmed)

- NVS / portal cativo / troca em runtime
- Mais de 2 redes
- Varredura de rede pelo daemon
- `WiFiMulti` e qualquer scan bloqueante
- UI de seleção de rede
- Mudanças no protocolo HTTP ou no payload
- Reflash automático / OTA

### Riscos identificados no brainstorm

| # | Risco | Mitigação |
|---|-------|-----------|
| R-1 | Hotspot do iPhone em **5 GHz** — o ESP32 não conecta de jeito nenhum | Pré-requisito: "Maximizar Compatibilidade" ligado; se falhar, é isso primeiro |
| R-2 | COM3 pode não ser o painel | Confirmar o dispositivo antes de gravar |
| R-3 | Boot mais lento por causa da segunda rede | Orçamento total ≤15s (AT-006) |
| R-4 | mDNS do Windows pode não resolver `.local` | Fallback documentado: `--host <ip>` do dia |

---

## Session Summary

| Metric | Value |
|--------|-------|
| Questions Asked | 6 |
| Approaches Explored | 3 (A recomendada e confirmada) |
| Features Removed (YAGNI) | 9 |
| Validations Completed | 4 |
| Confidence da recomendação | 0.80 (codebase + API do core; sem KB de embedded) |

---

## Next Step

**Ready for:** `/define .claude/sdd/features/BRAINSTORM_MULTI_REDE_WIFI.md`
