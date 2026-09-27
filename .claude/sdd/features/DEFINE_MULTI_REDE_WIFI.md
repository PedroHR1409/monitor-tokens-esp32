# DEFINE: Multi-rede WiFi (REDE_PRINCIPAL + HOTSPOT_CELULAR)

> O painel alterna entre duas redes por prioridade, sem reflash a cada troca de Wi-Fi

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | MULTI_REDE_WIFI |
| **Date** | 2026-09-21 |
| **Author** | define-agent |
| **Status** | ✅ Complete (Designed) |
| **Clarity Score** | 15/15 |
| **Input** | `.claude/sdd/features/BRAINSTORM_MULTI_REDE_WIFI.md` (`brainstorm_document`) |
| **Roadmap** | fora do `docs/ROADMAP.md`; infraestrutura de bancada, não item de produto |

---

## Problem Statement

O painel conhece uma única rede Wi-Fi compilada em `include/secrets.h`
(`WiFi.begin(WIFI_SSID, WIFI_PASSWORD)`, `session_transport.cpp:609`), então cada troca
entre a rede de casa (REDE_PRINCIPAL) e o hotspot do celular (HOTSPOT_CELULAR) exige reflash por USB; o
operador fica sem painel sempre que muda de rede.

---

## Target Users

| User | Role | Pain Point |
|------|------|------------|
| Operador na mesa | Dono do painel | Alterna entre a rede de casa e o hotspot do iPhone; hoje cada troca pede cabo + PlatformIO |
| Operador em trânsito | Mesmo operador, fora de casa | Leva o painel para outra rede sem notebook à mão para regravar |

> Escopo single-machine (ROADMAP 2026-09-07): um operador, dois contextos de rede.

---

## Goals

| Priority | Goal |
|----------|------|
| **MUST** | `secrets.h` (local) e `secrets.example.h` (versionado) declaram **duas** redes: `WIFI_SSID`/`WIFI_PASSWORD` (REDE_PRINCIPAL) e `WIFI_SSID_2`/`WIFI_PASSWORD_2` (HOTSPOT_CELULAR), sem remover o par existente |
| **MUST** | O firmware tenta as redes **na ordem de prioridade** (REDE_PRINCIPAL primeiro) e conecta na primeira disponível |
| **MUST** | O retry de `WIFI_RETRY_INTERVAL_MS` alterna a credencial tentada quando a conexão falha, e reconecta sozinho após queda |
| **MUST** | O boot **não** dobra o tempo de tela preta: o orçamento total de espera de WiFi segue ≤ `WIFI_CONNECT_TIMEOUT_MS` (15s), não 30s |
| **MUST** | O `loop()` continua **não-bloqueante** — nenhuma varredura (`scan`) no caminho de reconexão, preservando o render FULL e o `maxTransportMs` do `/diag` |
| **MUST** | O daemon encontra o painel nas duas redes pelo **mDNS** `monitor-ai.local` (default atual do `monitor.toml`), sem editar config |
| **MUST** | Nenhuma senha em arquivo versionado; `check_secrets.py` cobre as duas senhas (`WIFI_PASSWORD`, `WIFI_PASSWORD_2`) e o token |
| **MUST** | `check_secrets.py` deixa de tratar **SSID como segredo**: um SSID é transmitido em beacon pelo roteador, então não é credencial — e mantê-lo no padrão faz o sobrenome do autor no README colidir com o nome da rede secundária. O scanner passa a proteger `PASSWORD`/`SECRET`/`TOKEN`/`API_KEY` |
| **SHOULD** | Erro/log do firmware distingue "nenhuma rede disponível" de "sem WiFi", legível no serial |
| **SHOULD** | `docs/SPEC.md` §5 documenta as duas redes e a política de prioridade |
| **COULD** | O log de boot informa **qual** credencial venceu (útil no diagnóstico em bancada) |

**Nota de prioridade.** O orçamento de boot é MUST porque é regressão visível: hoje a
tela espera 15s; uma implementação ingênua de duas redes a levaria a 30s. E o
não-bloqueante é MUST por precedente da SPEC (o alerta escalonado existiu justamente
para não invalidar tela).

---

## Success Criteria

- [ ] Com as duas redes no alcance, o painel conecta na **REDE_PRINCIPAL** em 100% dos boots (serial prova o IP `192.168.2.x`)
- [ ] Com só o **HOTSPOT_CELULAR** no alcance, conecta no hotspot; serial imprime IP na faixa `172.20.10.x`
- [ ] Sem nenhuma rede no alcance, o dashboard sobe em **≤15s**; o serial imprime `IP=sem WiFi`
- [ ] Após queda de rede, reconecta sozinho em ≤ **20s** (`WIFI_RETRY_INTERVAL_MS`), alternando entre as duas
- [ ] `monitor-ai.local` resolve na rede ativa e `GET /health` responde **sem** editar `monitor.toml`
- [ ] `python tools/check_secrets.py` cobre os **4** valores; **0** senhas em arquivos rastreados
- [ ] Build com `secrets.example.h` (sem `secrets.h`) segue **SUCCESS** — o CI não quebra
- [ ] `python -m pytest tests/ -q` verde, incluindo `test_production_contracts`
- [ ] `GET /diag` não mostra regressão em `maxTransportMs`/`maxLoopMs` em relação ao valor anterior

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | Boot na REDE_PRINCIPAL | REDE_PRINCIPAL no alcance | Painel liga | Conecta na REDE_PRINCIPAL; serial `[transport] WiFi OK, IP=192.168.2.x` |
| AT-002 | Fallback para o HOTSPOT_CELULAR | REDE_PRINCIPAL fora de alcance, HOTSPOT_CELULAR no alcance | Painel liga | Conecta no HOTSPOT_CELULAR; serial imprime IP `172.20.10.x` |
| AT-003 | Prioridade | As duas no alcance | Painel liga | Conecta na **REDE_PRINCIPAL** (primeira da tabela), não no HOTSPOT_CELULAR |
| AT-004 | Migração de volta | Painel conectado ao HOTSPOT_CELULAR; REDE_PRINCIPAL passa a existir | Próximo retry (≤20s) | Migra para a REDE_PRINCIPAL e o serial registra a troca |
| AT-005 | Queda de rede | Painel conectado | A rede cai | Reconecta sozinho em ≤20s, alternando; **sem** reiniciar |
| AT-006 | Nenhuma rede | Nenhuma das duas no alcance | Painel liga | `ui_dashboard_init` roda em ≤15s; heartbeat imprime `IP=sem WiFi` |
| AT-007 | mDNS nas duas redes | Painel conectado em qualquer das redes | PC resolve `monitor-ai.local` | Host resolve; `GET /health` responde 200 |
| AT-008 | Segredos | `secrets.h` com as senhas reais | `python tools/check_secrets.py` | Protege as duas senhas e o token; **não** trata o SSID como segredo; o teste do scanner (`WIFI_PASSWORD`) segue verde |
| AT-009 | Build sem segredos | Sem `include/secrets.h` (como no CI) | `pio run -e esp32-s3-3v5-lcd` | SUCCESS com os placeholders do exemplo |
| AT-010 | Sem regressão | Suíte atual verde | `pytest tests/ -q` | 100% verde, incluindo `test_production_contracts` |
| AT-011 | Contrato do exemplo | `secrets.example.h` | Teste de contrato lê o arquivo | Contém `WIFI_SSID`, `WIFI_PASSWORD` **e** os `_2` correspondentes, com placeholders |
| AT-012 | Não-bloqueante | Painel em operação | Circulação normal do `loop()` | Nenhuma varredura de rede no caminho de reconexão; `/diag` sem pico novo |
| AT-013 | SSID não é segredo | Um arquivo compartilhável contém o **valor do SSID** | `check_secrets.py` roda | **Não** aponta vazamento (SSID é público); o mesmo arquivo com a **senha** continua sendo apontado |

---

## Out of Scope

- Mais de duas redes; array genérico; NVS; portal cativo; troca em runtime
- `WiFiMulti` e qualquer `scan` bloqueante
- Varredura de rede pelo daemon; `--host` novo
- UI/terminal de seleção de rede no painel
- Mudanças no protocolo HTTP, payload ou no contrato `POST /sessions`
- OTA / reflash remoto
- Handoff entre APs do mesmo SSID (mesh), `RSSI` como critério
- Configurar o hotspot do iPhone (ação do operador)

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Technical | Firmware ESP32-Arduino; `platform` pioarduino, core 3.3.11 | Usar `WiFi.h` do core; sem lib de terceiros |
| Technical | Render FULL + guards de performance (SPEC) | Proibido `scan`/bloqueio no `loop()` |
| Technical | `session_transport_init()` roda antes de `ui_dashboard_init()` (`main.cpp:31,33`) | O orçamento de boot precisa ser compartilhado entre as duas tentativas |
| Technical | `secrets.h` é gitignored | Só `secrets.example.h` vai para o repo; senha real nunca versionada |
| Technical | ESP32 é **2.4 GHz apenas** | Hotspot do iPhone precisa de "Maximizar Compatibilidade" (risco R-1) |
| Technical | `check_secrets.py` casa `SSID|PASSWORD|...` | As chaves novas entram na proteção sem alterar o scanner |
| Resource | Sem admin; sem hardware novo | Só reflash por USB na bancada |
| Scope | Single-machine | Sem agregação de nós |

---

## Technical Context

| Aspect | Value | Notes |
|--------|-------|-------|
| **Deployment Location** | `include/secrets.h` + `include/secrets.example.h` (credenciais); `src/sessions/session_transport.cpp` (conexão/retry, `session_transport_init` e `session_transport_loop`); `docs/SPEC.md` §5 | Firmware; nenhuma mudança de daemon é necessária |
| **KB Domains** | `python`, `testing` | **Nenhuma** domain cobre WiFi/embedded/C++. A confiança (0.80) vem do codebase e da API do core, não de KB — o Design não deve esperar padrão de KB para o lado do firmware |
| **IaC Impact** | None | Sem nuvem |

---

## Data Contract (if applicable)

Não aplicável. A feature não toca `usage_history`, payload, nem fonte de dados. O
contrato `POST /sessions` permanece intacto — muda apenas *por onde* o painel é
alcançado.

---

## Assumptions

| ID | Assumption | If Wrong, Impact | Validated? |
|----|------------|------------------|------------|
| A-001 | O hotspot do iPhone (`HOTSPOT_CELULAR`) está acessível em **2.4 GHz** | O ESP32 **nunca** conecta no HOTSPOT_CELULAR, independente do código — a feature pareceria quebrada | [ ] Não — depende do "Maximizar Compatibilidade" ligado; **verificar primeiro** |
| A-002 | `COM3` é o painel (ESP32) | Gravar firmware no dispositivo errado — risco evitável | [ ] Não — confirmar com o serial/descrição antes do upload |
| A-003 | O Windows resolve `monitor-ai.local` (mDNS) na rede ativa | Daemon não acha o painel sem `--host`; fallback documentado | [ ] Não — testável em AT-007 |
| A-004 | `WiFi.begin()` com credencial errada falha em tempo curto o bastante para caber no orçamento de 15s | Boot passaria de 15s (AT-006 falha) | [ ] Não — medir no serial |
| A-005 | Uma única chamada `WiFi.begin()` por credencial, sem `scan`, é suficiente para achar redes conhecidas | Se não achar, precisaríamos de scan (e aí o requisito não-bloqueante muda) | [x] **Parcialmente** — é o comportamento atual com uma rede, que funciona |
| A-006 | O teste de contrato (`test_production_contracts.py:30-35`) continua válido com chaves `_2` novas | O CI quebraria | [x] **Sim** — ele só exige os substrings `WIFI_SSID`/`WIFI_PASSWORD`, que permanecem |
| A-007 | `check_secrets.py` cobre as chaves novas sem alteração | Falso-negativo de vazamento | [x] **Sim** — regex em `tools/check_secrets.py:11` casa qualquer nome com `SSID`/`PASSWORD` |

---

## Clarity Score Breakdown

| Element | Score (0-3) | Notes |
|---------|-------------|-------|
| Problem | 3 | Uma frase, com o mecanismo (credencial única compilada) e o custo (reflash por troca) |
| Users | 3 | Dois contextos de rede, com dor distinta; single-machine explícito |
| Goals | 3 | 7 MUST + 2 SHOULD + 1 COULD, com a razão do orçamento de boot explicitada |
| Success | 3 | 9 critérios com número/faixa de IP e limites de tempo |
| Scope | 3 | 11 exclusões herdadas do YAGNI + riscos com mitigação |
| **Total** | **15/15** | |

**Por que 15.** Input era `brainstorm_document` com 6 perguntas, abordagem A confirmada,
4 validações e YAGNI aplicado. O risco residual está nas suposições **não validadas**
(A-001 hotspot 2.4 GHz, A-002 COM3, A-003 mDNS, A-004 tempo de falha) — todas
verificáveis em bancada, nenhuma é lacuna de requisito.

---

## Open Questions

Nenhuma bloqueante para o Design.

Para o Design resolver (não são lacunas de requisito):

- Como repartir o orçamento de 15s entre as duas credenciais (ex.: 15s no total, tentando a segunda com o que sobrar).
- Onde guardar o índice da credencial atual (estático no módulo é suficiente).
- Como o log informa qual credencial venceu sem imprimir a senha (COULD).
- Se `WiFi.disconnect()` antes do `begin()` no retry deve ser mantido (hoje é mantido).

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-09-21 | define-agent | Initial version a partir de `BRAINSTORM_MULTI_REDE_WIFI.md` |

---

## Next Step

**Ready for:** `/build .claude/sdd/features/DESIGN_MULTI_REDE_WIFI.md`
