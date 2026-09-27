# DESIGN: Multi-rede WiFi (REDE_PRINCIPAL + HOTSPOT_CELULAR)

> Duas credenciais com prioridade por ordem, orçamento de boot compartilhado e
> alternância não-bloqueante no retry — mais o SSID saindo do scanner de segredos

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | MULTI_REDE_WIFI |
| **Date** | 2026-09-21 |
| **Author** | design-agent |
| **DEFINE** | [DEFINE_MULTI_REDE_WIFI.md](./DEFINE_MULTI_REDE_WIFI.md) — clareza 15/15 |
| **Status** | Ready for Build |
| **Abordagem** | Approach A do brainstorm — tabela de credenciais + `WiFi.begin()` alternando |
| **Confiança** | **0.80** — nenhuma KB cobre embedded/C++/WiFi; os padrões vêm do **codebase** (`session_transport.cpp`, `config.h`) e da API do core ESP32-Arduino, citados por arquivo e linha |

---

## Architecture Overview

```text
┌───────────────────────────────────────────────────────────────────────────────┐
│                    ESCOPO: só firmware + docs + scanner                        │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  include/secrets.h (LOCAL, gitignored)                                         │
│    WIFI_SSID / WIFI_PASSWORD            <- rede primária (casa)                │
│    WIFI_SSID_2 / WIFI_PASSWORD_2        <- NOVO: rede secundária (hotspot)     │
│    MONITOR_API_TOKEN                    (intocado)                             │
│         │                                                                      │
│         ▼                                                                      │
│  session_transport.cpp                                                         │
│    WIFI_CREDENTIALS[] = { {SSID, PASS}, {SSID_2, PASS_2} }   ordem = prioridade │
│         │                                                                      │
│         ├── session_transport_init()   ORÇAMENTO ÚNICO de 15s                  │
│         │      tenta cred 0, depois cred 1, dentro do mesmo relógio            │
│         │      → total ≤ WIFI_CONNECT_TIMEOUT_MS (antes: 15s por rede = 30s)   │
│         │                                                                      │
│         └── session_transport_loop()   retry 20s, SEM scan                     │
│                alterna a credencial só depois de falhar na atual               │
│                                                                                │
│  tools/check_secrets.py                                                        │
│    regex: (PASSWORD|SECRET|TOKEN|API_KEY)   <- SSID removido                   │
│         │                                                                      │
│         └─ SSID é broadcast em beacon → não é credencial; mantê-lo no          │
│            padrão fazia o sobrenome do autor no README casar com a rede        │
│                                                                                │
│  ✗ NÃO TOCA: protocolo HTTP · payload · daemon (usa mDNS que já é default)     │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| `include/secrets.h` (mod., **local**) | Declarar a segunda rede ao lado da primeira | C header, gitignored |
| `include/secrets.example.h` (mod.) | Versionar o formato das duas redes com placeholders | C header |
| `src/sessions/session_transport.cpp` (mod.) | Tabela de credenciais, boot com orçamento único, retry alternando, log da rede vencedora | C++ / ESP32-Arduino (`WiFi.h`) |
| `tools/check_secrets.py` (mod.) | Parar de tratar SSID como segredo | Python stdlib |
| `docs/SPEC.md` (mod.) | §5: duas redes e política de prioridade | Markdown |
| `tests/test_production_contracts.py` (mod.) | Travar o novo contrato do scanner e as chaves `_2` do exemplo | unittest |

---

## Key Decisions

### Decision 1: Tabela de credenciais com prioridade por ordem, não `WiFiMulti`

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-21 |

**Context:** O firmware conecta com uma credencial fixa (`session_transport.cpp:609`).
É preciso suportar duas redes na ordem que o operador pediu (primária primeiro).

**Choice:** Um array `WIFI_CREDENTIALS[]` na ordem de prioridade e `WiFi.begin()` apontando
para a credencial corrente. O boot percorre o array até conectar.

**Rationale:** O `WiFiMulti` do core escolhe por **RSSI** — não obedece ordem — e seu
`run()` faz *scan*, que bloqueia. `session_transport_loop` é medido no `/diag`
(`maxTransportMs`) e o render é FULL; um scan no `loop()` é regressão de performance
que a SPEC já combateu antes (foi por isso que o alerta escalonado abandonou a borda
pulsante). A API usada já está no arquivo e não adiciona dependência.

**Alternatives Rejected:**

1. **`WiFiMulti`** — escolhe por sinal, contradiz a prioridade pedida; scan bloqueante.
2. **Credenciais em NVS + troca em runtime** — exige UI/comando novos; fora do YAGNI.

**Consequences:**

- Mais código que a alternativa idiomática; a política fica explícita e testável.
- Nenhuma dependência nova.

---

### Decision 2: Um orçamento de boot só, dividido entre as redes

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-21 |

**Context:** `session_transport_init()` roda **antes** de `ui_dashboard_init()`
(`main.cpp:31,33`) e bloqueia até `WIFI_CONNECT_TIMEOUT_MS` (15s) com a tela preta.
Tentar cada rede por 15s viraria 30s de espera.

**Choice:** Um único relógio iniciado no começo do init; o laço externo percorre as
credenciais enquanto `millis() - start < WIFI_CONNECT_TIMEOUT_MS`. Na prática cada
credencial recebe `WIFI_CONNECT_TIMEOUT_MS / WIFI_CREDENTIAL_COUNT` (≈7,5s com duas).

**Rationale:** Mantém a promessa do header (`session_transport.h:7`: *"Nao trava o boot"*)
sem introduzir constante nova: o divisor é derivado do tamanho do array, então o
orçamento total fica sempre ≤ 15s mesmo se uma terceira rede for adicionada.

**Alternatives Rejected:**

1. **15s por rede** — 30s de tela preta; regressão visível (AT-006).
2. **Encurtar `WIFI_CONNECT_TIMEOUT_MS`** — afetaria também o caso de uma rede só, que
   hoje funciona; mudaria um comportamento existente sem necessidade.

**Consequences:**

- Se a rede primária demora >7,5s para associar, o boot passa para a secundária — aceito,
  e o retry de 20s corrige depois.
- O total nunca excede o valor já documentado de 15s.

---

### Decision 3: Alternar a credencial só depois de uma falha na atual

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-21 |

**Context:** O retry roda a cada `WIFI_RETRY_INTERVAL_MS` (20s) enquanto desconectado.
Alternar a cada retry faria o painel pular de rede a cada 20s mesmo quando a rede atual
só piscou.

**Choice:** Um contador `s_failedRetries`; a credencial só avança quando já houve uma
falha na atual (`s_failedRetries > 0`), e zera ao conectar.

**Rationale:** Preserva o comportamento atual ("tenta a mesma rede de novo") e só então
migra. Atende AT-004 (migração para a primária quando ela reaparece) sem oscilação em
quedas curtas.

**Alternatives Rejected:**

1. **Alternar a cada retry** — oscilação desnecessária entre redes.
2. **Nunca alternar no loop** — o painel ficaria preso na rede que sumiu.

**Consequences:**

- A migração de volta à primária leva até ~40s (duas janelas de 20s) em vez de 20s.
- Aceito: é assintótico e não interrompe o serviço.

---

### Decision 4: SSID deixa de ser tratado como segredo

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-09-21 |

**Context:** `check_secrets.py:11` coleta valores de defines cujo nome case
`SSID|PASSWORD|SECRET|TOKEN|API_KEY` e falha se reaparecerem em qualquer arquivo. Com
duas redes, isso cria um falso positivo **insolúvel**: o nome da rede secundária
coincide com o **sobrenome do autor** no `README.md`, então o scanner acusaria o README
assim que `WIFI_SSID_2` existisse. O mesmo mecanismo já estava acusando os artefatos
SDD desta feature por citarem os nomes das redes.

**Choice:** Remover `SSID|` do padrão. O scanner passa a proteger
`PASSWORD|SECRET|TOKEN|API_KEY`. O SSID continua podendo aparecer em logs e docs.

**Rationale:** Um SSID é transmitido em claro em *beacon frames* por qualquer roteador —
não é credencial por natureza; quem autentica é a *passphrase*. Manter SSID no padrão
produzia falso positivo sem proteger nada que já não fosse público. O teste existente
(`test_production_contracts.py:13-28`) usa `WIFI_PASSWORD` como isca, então continua
válido e provando a proteção que importa.

**Alternatives Rejected:**

1. **Manter SSID e usar placeholders em todo doc versionado** — não resolve: o
   `README.md` continuaria casando pelo sobrenome do autor; exigiria exceção no scanner.
2. **Excluir o README do scan** — enfraquece o guard-rail no arquivo mais visível do repo.

**Consequences:**

- Os artefatos desta feature podem nomear as redes sem alarme falso.
- A proteção de senha e token permanece intacta (AT-013 trava as duas direções).
- O token placeholder ainda acusa enquanto o operador não puser um token real — condição
  **pré-existente**, já registrada nos BUILD_REPORTs anteriores.

---

## File Manifest

| # | File | Action | Purpose | Agent | Dependencies |
|---|------|--------|---------|-------|--------------|
| 1 | `include/secrets.h` | Modify | Adicionar a segunda rede (senha como placeholder para o operador preencher) | (direct) | None |
| 2 | `include/secrets.example.h` | Modify | Versionar o formato das duas redes com placeholders | (direct) | None |
| 3 | `src/sessions/session_transport.cpp` | Modify | Tabela de credenciais, boot com orçamento único, retry alternando, log da vencedora | (direct) | 1, 2 |
| 4 | `tools/check_secrets.py` | Modify | Remover `SSID` do padrão | (direct) | None |
| 5 | `tests/test_production_contracts.py` | Modify | Travar o contrato do scanner e as chaves `_2` do exemplo | @test-generator | 2, 4 |
| 6 | `docs/SPEC.md` | Modify | §5 documenta as duas redes e a prioridade | @code-documenter | 3 |

**Total Files:** 6 — **0 arquivos criados**.

---

## Agent Assignment Rationale

| Agent | Files | Why This Agent |
|-------|-------|----------------|
| (direct) | 1, 2, 3, 4 | Firmware C++ e edições cirúrgicas; **não existe agente C++/embedded** no projeto (18 agentes, nenhum de firmware) — confiança vem do codebase |
| @test-generator | 5 | Convenção `unittest` do repo; testes de scanner e de contrato |
| @code-documenter | 6 | Documentação de produto na fonte da verdade |

**Agent Discovery:** `.claude/agents/**/*.md` — 18 agentes; nenhum cobre ESP32/C++/WiFi.
Não há @python-developer no caminho crítico (as mudanças Python são 1 linha de regex).

**Nota de execução.** Sessões anteriores deste projeto não tinham o tool `Task`; se o
Build não tiver, executa direto e registra `(direct)`.

---

## Code Patterns

### Pattern 1: Tabela de credenciais (namespace anônimo)

```cpp
// src/sessions/session_transport.cpp — junto dos outros estaticos do arquivo
namespace {
struct WifiCredential {
    const char *ssid;
    const char *password;
};

// A ORDEM E A PRIORIDADE: a primeira rede que responder vence. Nao ha escolha por
// RSSI de proposito — o operador pediu previsibilidade, e um scan no loop() custaria
// um pico em maxTransportMs (render FULL).
const WifiCredential WIFI_CREDENTIALS[] = {
    {WIFI_SSID,   WIFI_PASSWORD},
    {WIFI_SSID_2, WIFI_PASSWORD_2},
};
constexpr uint8_t WIFI_CREDENTIAL_COUNT =
    sizeof(WIFI_CREDENTIALS) / sizeof(WIFI_CREDENTIALS[0]);

uint8_t s_wifiCredIndex = 0;    // credencial da tentativa atual
uint8_t s_failedRetries = 0;    // falhas consecutivas na credencial atual
} // namespace
```

### Pattern 2: Boot com orçamento único

```cpp
void session_transport_init() {
    Serial.println("[transport] conectando ao WiFi...");
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);

    // Um relogio so para as duas redes: ui_dashboard_init() roda DEPOIS daqui, entao
    // 15s por credencial seriam 30s de tela preta. O orcamento e dividido pelo numero
    // de credenciais, entao o total nunca passa de WIFI_CONNECT_TIMEOUT_MS.
    const uint32_t start = millis();
    const uint32_t perCredential = WIFI_CONNECT_TIMEOUT_MS / WIFI_CREDENTIAL_COUNT;
    while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_CONNECT_TIMEOUT_MS) {
        const WifiCredential &cred = WIFI_CREDENTIALS[s_wifiCredIndex];
        WiFi.begin(cred.ssid, cred.password);
        const uint32_t attemptStart = millis();
        while (WiFi.status() != WL_CONNECTED
               && millis() - start < WIFI_CONNECT_TIMEOUT_MS
               && millis() - attemptStart < perCredential) {
            delay(250);
            Serial.print(".");
        }
        if (WiFi.status() == WL_CONNECTED) break;
        s_wifiCredIndex = (s_wifiCredIndex + 1) % WIFI_CREDENTIAL_COUNT;
    }
    Serial.println();

    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[transport] nenhuma das redes respondeu (confira "
                       "include/secrets.h) — vai continuar tentando em background");
    } else {
        Serial.printf("[transport] WiFi OK, IP=%s, rede=\"%s\"\n",
                      WiFi.localIP().toString().c_str(),
                      WIFI_CREDENTIALS[s_wifiCredIndex].ssid);
        if (MDNS.begin(MDNS_HOSTNAME)) {
            MDNS.addService("http", "tcp", HTTP_SERVER_PORT);
            Serial.printf("[transport] mDNS: http://%s.local\n", MDNS_HOSTNAME);
        }
    }
    // ... handlers e server.begin() seguem iguais
}
```

### Pattern 3: Retry alternando, sem scan

```cpp
void session_transport_loop() {
    server.handleClient();

    static uint32_t lastRetry = 0;
    static bool wasConnected = true;
    const uint32_t now = millis();

    if (WiFi.status() != WL_CONNECTED) {
        if (wasConnected) {
            wasConnected = false;
            Serial.println("[transport] WiFi caiu — tentando reconectar");
        }
        if (now - lastRetry >= WIFI_RETRY_INTERVAL_MS) {
            lastRetry = now;
            // Alterna SO depois de uma falha na credencial atual: uma queda breve na
            // rede em que ja estavamos nao deve jogar o painel para a outra.
            if (s_failedRetries > 0) {
                s_wifiCredIndex = (s_wifiCredIndex + 1) % WIFI_CREDENTIAL_COUNT;
            }
            s_failedRetries++;
            WiFi.disconnect();
            WiFi.begin(WIFI_CREDENTIALS[s_wifiCredIndex].ssid,
                       WIFI_CREDENTIALS[s_wifiCredIndex].password);
        }
    } else if (!wasConnected) {
        wasConnected = true;
        s_failedRetries = 0;
        Serial.printf("[transport] WiFi reconectado, IP=%s, rede=\"%s\"\n",
                      WiFi.localIP().toString().c_str(),
                      WIFI_CREDENTIALS[s_wifiCredIndex].ssid);
        MDNS.begin(MDNS_HOSTNAME);
        MDNS.addService("http", "tcp", HTTP_SERVER_PORT);
    }
}
```

### Pattern 4: Segredos — SSID fora do padrão

```python
# tools/check_secrets.py
# SSID fica FORA de proposito: e transmitido em beacon pelo roteador, nao e credencial,
# e mante-lo aqui fazia o nome de uma rede colidir com o sobrenome do autor no README.
SECRET_DEFINE = re.compile(
    rb'^\s*#define\s+([A-Za-z0-9_]*(?:PASSWORD|SECRET|TOKEN|API_KEY)[A-Za-z0-9_]*)'
    rb'\s+"([^"]+)"', re.MULTILINE)
```

### Pattern 5: Exemplo versionado com as duas redes

```c
// include/secrets.example.h
#define WIFI_SSID     "NOME_DA_REDE"
#define WIFI_PASSWORD "SENHA_DA_REDE"
#define WIFI_SSID_2     "NOME_DA_REDE_2"
#define WIFI_PASSWORD_2 "SENHA_DA_REDE_2"
// MONITOR_API_TOKEN permanece como esta (nao tocado por esta feature).
```

### Pattern 6: Teste do novo contrato do scanner

```python
# tests/test_production_contracts.py
def test_secret_scanner_ignores_a_broadcast_ssid(self):
    """Um SSID e publico (vai em beacon); trata-lo como segredo causava falso
    positivo no nome de rede que coincide com o sobrenome do autor."""
    scanner = ROOT / "tools" / "check_secrets.py"
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "include").mkdir()
        (repo / "include" / "secrets.h").write_text(
            '#define WIFI_SSID "broadcast-test-network"\n'
            '#define WIFI_PASSWORD "private-test-value-8391"\n', encoding="utf-8")
        (repo / "shared.md").write_text("broadcast-test-network", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(scanner), "--root", str(repo)],
            text=True, capture_output=True, check=False)
    self.assertEqual(0, result.returncode)

def test_secret_scanner_still_detects_a_password_leak(self):
    scanner = ROOT / "tools" / "check_secrets.py"
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "include").mkdir()
        secret = "private-test-value-8391"
        (repo / "include" / "secrets.h").write_text(
            '#define WIFI_PASSWORD "{}"\n'.format(secret), encoding="utf-8")
        (repo / "shared.md").write_text(secret, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(scanner), "--root", str(repo)],
            text=True, capture_output=True, check=False)
    self.assertNotEqual(0, result.returncode)
    self.assertNotIn(secret, result.stdout + result.stderr)

def test_secrets_example_declares_two_networks(self):
    example = ROOT / "include" / "secrets.example.h"
    text = example.read_text(encoding="utf-8")
    self.assertIn("WIFI_SSID_2", text)
    self.assertIn("WIFI_PASSWORD_2", text)
```

---

## Data Flow

```text
1. Boot → session_transport_init()
   │
   ▼
2. relogio unico (≤15s): cred[0]=primaria por ~7,5s → se falhar, cred[1]=secundaria
   │
   ▼
3. conectou → loga IP + nome da rede → MDNS.begin("monitor-ai")
   │
   ▼
4. loop() → session_transport_loop(): retry a cada 20s
   │        (sem scan; alterna credencial so apos falhar na atual)
   ▼
5. PC: daemon resolve monitor-ai.local e faz POST /sessions (inalterado)
```

---

## Integration Points

| External System | Integration Type | Authentication |
|-----------------|-----------------|----------------|
| Roteador doméstico (rede primária) | WiFi STA associada por SSID/passphrase | WPA2, via `WiFi.begin` |
| Hotspot do iPhone (rede secundária) | idem | WPA2; **exige 2.4 GHz** ("Maximizar Compatibilidade") |
| Daemon (PC) | HTTP `POST /sessions`, inalterado | token no header (inalterado) |

---

## Testing Strategy

| Test Type | Scope | Files | Tools | Coverage Goal |
|-----------|-------|-------|-------|---------------|
| Unit (PC) | Scanner de segredos; exemplo versionado | `tests/test_production_contracts.py` | unittest + subprocess | AT-008, AT-011, AT-013 |
| Compilação | Firmware compila com 2 credenciais | `pio run -e esp32-s3-3v5-lcd` | PlatformIO | AT-009, AT-012 (compila) |
| Hardware (serial) | Boot na primária, fallback, prioridade, queda, orçamento | `pio device monitor -b 115200` | Serial 115200 | AT-001..AT-006 |
| Integração (PC) | mDNS + `/health` na rede ativa | `curl monitor-ai.local/health` | curl/navegador | AT-007 |

**Cobertura:** AT-001..AT-006 e AT-012 dependem de hardware e são **observados no serial**
(não automatizáveis no CI). AT-008..AT-011 e AT-013 têm teste automatizado.

---

## Error Handling

| Error Type | Handling Strategy | Retry? |
|------------|-------------------|--------|
| Nenhuma rede responde no boot | Log explícito "nenhuma das redes respondeu"; segue para o dashboard; retry em background | Sim (20s) |
| Rede cai em operação | Alterna a credencial após falhar na atual; sem reinício | Sim (20s) |
| Credencial errada numa das redes | Falha dentro do orçamento da credencial e passa para a seguinte | Sim |
| Hotspot em 5 GHz | O ESP32 nunca associa; o log mostra as duas tentativas falhando (diagnóstico: R-1) | Não (depende do iPhone) |

---

## Configuration

| Config Key | Type | Default | Description |
|------------|------|---------|-------------|
| `WIFI_SSID` / `WIFI_PASSWORD` | string | — (secrets.h) | Rede primária; inalterada |
| `WIFI_SSID_2` / `WIFI_PASSWORD_2` | string | — (secrets.h, **novo**) | Rede secundária; senha preenchida pelo operador |
| `WIFI_CONNECT_TIMEOUT_MS` | int | 15000 | Orçamento **total** de boot (inalterado; agora dividido entre N credenciais) |
| `WIFI_RETRY_INTERVAL_MS` | int | 20000 | Intervalo de retry (inalterado) |

---

## Security Considerations

- As senhas vivem **só** em `include/secrets.h` (gitignored); o exemplo traz placeholders.
- O log do serial imprime **apenas o SSID**, nunca a senha — e o serial não é arquivo.
- `check_secrets.py` continua protegendo `PASSWORD`/`SECRET`/`TOKEN`/`API_KEY`.
- Nenhuma mudança no token HTTP nem no anti-replay.
- SSID passa a ser considerado público (decisão 4), o que é factual: vai em beacon.

---

## Observability

| Aspect | Implementation |
|--------|----------------|
| Logging | Serial: `WiFi OK, IP=..., rede="..."` (rede vencedora, COULD satisfeito) e `nenhuma das redes respondeu` |
| Métricas | `GET /diag` mantém `maxTransportMs`/`maxLoopMs` — prova que o retry não bloqueia (AT-012) |
| Tracing | N/A |

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-09-21 | design-agent | Initial version a partir de `DEFINE_MULTI_REDE_WIFI.md`; inclui a decisão do SSID no scanner |

---

## Next Step

**Ready for:** `/build .claude/sdd/features/DESIGN_MULTI_REDE_WIFI.md`
