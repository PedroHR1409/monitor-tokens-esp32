# Monitor.AI

> Um painel de mesa com ESP32-S3 e tela touch que mostra, em tempo real, **o que seus agentes de IA (Claude Code, Codex e OpenCode) estão fazendo** — e quanto eles custam em tokens.

![CI](https://github.com/PedroHR1409/monitor-tokens-esp32/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/Licen%C3%A7a-MIT-blue.svg)
![PlatformIO](https://img.shields.io/badge/PlatformIO-ESP32--S3-orange)
![Python](https://img.shields.io/badge/Python-3.10%2B%20std--only-blue)

---

## O que é

Uma "boleira de status" física para quem trabalha com vários agentes de IA ao mesmo
tempo. Um **ESP32-S3** com display IPS touch de 3.5" mostra um grid com as sessões
ativas do seu computador — estado, tempo, tokens — enquanto um **daemon em Python**
(no PC, apenas biblioteca padrão) coleta evidências dos transcripts, rollouts e
hooks, e empurra tudo para a placa por HTTP.

| O painel mostra | Fonte |
|---|---|
| **Cards 1-6** — sessões ativas (Claude, Codex, OpenCode) com estado, tempo e modelo | Hooks + transcripts + rollouts + banco local do OpenCode |
| **Card 7** — heatmap estilo GitHub do consumo diário de tokens (30 dias) + inspeção por dia | Histórico persistido no daemon (SQLite) |
| **Pódio** — top 3 agentes por consumo, com chip de período (hoje/7d/30d) e modal de sessões | idem |
| **Relógio NTP**, alerta pulsante em `ask`/`perm`, modo noturno automático | — |

Estados por sessão: **work** (executando), **ask** (perguntou, aguarda você),
**perm** (aguarda sua aprovação) e **free** (livre) — detectados por eventos
estruturados de hooks, com inferência por transcript como fallback.

## Destaques técnicos

- **Firmware**: LVGL 9 + GFX (driver AXS15231B QSPI), Arduino core 3.3.11 via
  pioarduino; HTTP server com token e anti-replay; touch resistivo a falsos
  toques; reconexão automática de Wi-Fi; NTP.
- **Daemon**: Python 3.10+ **100% stdlib** — sem `pip install`; coleta com caches
  por mtime (reler tudo a cada ciclo nunca é necessário); payload versionado e
  aditivo (`v1`/`v2`) com deduplicação de tokens e redação de segredos.
- **Segurança**: token compartilhado em header com comparação constant-time,
  segredos só em arquivo gitignored, varredura anti-vazamento no CI.
- **Instalação como serviço por usuário** (Agendador de Tarefas / `systemd --user`),
  sem direitos de administrador.
- **Processo SDD** com especificações versionadas (`.claude/sdd/`) e CI que roda
  testes, varredura de segredos e compila os dois firmwares a cada push.

## Demonstração

> 📷 *Fotos e vídeo do painel em operação — adicionar aqui.*

## Hardware

| Item | Detalhe |
|---|---|
| Placa | Guition JC3248W535C/EN (ESP32-S3, 16MB flash, 8MB PSRAM OPI) |
| Display | IPS 3.5" 320×480 touch (AXS15231B, QSPI) — pinos já configurados em `include/config.h` |
| PC | Windows ou Linux, Python 3.10+ (só stdlib), PlatformIO CLI |

Outras placas com ESP32-S3 + display QSPI funcionam com ajuste de pinos — ver
`include/config.h` e `docs/SPEC.md`.

## Começando

### 1. Firmware

```bash
pip install -U platformio          # CLI do PlatformIO
cp include/secrets.example.h include/secrets.h   # Windows: Copy-Item
# edite include/secrets.h: Wi-Fi + MONITOR_API_TOKEN (token longo e aleatório)

pio run -e esp32-s3-3v5-lcd        # compilar (o 1º build baixa ~300MB de libs)
pio run -e esp32-s3-3v5-lcd -t upload --upload-port COM5
```

> **Primeiro build lento?** Normal — antivírus escaneando milhares de arquivos.
> Ver dica no fim do README.

### 2. Daemon (PC)

```bash
python tools/session_daemon.py                 # usa mDNS (monitor-ai.local)
python tools/session_daemon.py --host 192.168.0.50   # ou o IP do painel
```

O daemon lê `monitor.toml` (config por usuário). Gere um exemplo seguro com
`python tools/monitor.py config init` e veja a config ativa (token sempre
redigido) com `config show`. O token do daemon é o mesmo `MONITOR_API_TOKEN` do
`secrets.h` — e pode ser injetado por variável de ambiente.

### 3. Hooks de estado (opcional, recomendado)

```bash
python tools/install_hook.py          # hooks do Claude Code
python tools/install_codex_hook.py    # hooks do Codex
```

Sem hooks o painel funciona com inferência por transcript; com hooks os estados
`ask`/`perm` ficam determinísticos.

### 4. Serviço (opcional)

```bash
python tools/monitor.py service install --dry-run   # pré-visualizar
python tools/monitor.py service install             # serviço por usuário, sem admin
```

## CLI unificada

```bash
python tools/monitor.py run            # daemon contínuo
python tools/monitor.py once           # um ciclo (teste)
python tools/monitor.py doctor         # diagnóstico completo do setup
python tools/monitor.py config init    # exemplo de monitor.toml
python tools/monitor.py hooks check    # saúde dos hooks
python tools/monitor.py service status # estado do serviço
```

## Uso no dia a dia

- **Toque curto** num card → detalhes (branch, modelo, contexto, tokens da sessão)
- **Toque longo** → esconde a sessão · toque num card vazio → seletor
  (recuperar escondidas: `curl -X POST http://IP_DO_PAINEL/hidden/clear`)
- **Toque no card de consumo** → alterna heatmap ↔ pódio; toque num dia do heatmap
  mostra o consumo daquele dia; toque numa barra do pódio abre o ranking de sessões
- Cotas com procedência explícita: a do Codex é o número **oficial do servidor**;
  a do Claude/OpenCode é **estimativa** de consumo

## Segurança

- `include/secrets.h` (Wi-Fi + token) é **gitignored e nunca compartilhado** —
  valide com `python tools/check_secrets.py`
- O token viaja no header `X-Monitor-Token` com comparação constant-time; logs e
  JSON redigem segredos como `***redacted***`
- O servidor rejeita payloads repetidos (anti-replay) e corpos acima do limite
- `monitor.toml` pode conter o token — também gitignored

Para reportar uma vulnerabilidade, ver [SECURITY.md](SECURITY.md).

## Estrutura do repositório

```
├── src/                 # firmware por camada (ui/, drivers/, sessions/, assets/, icons/)
├── include/             # headers compartilhados + secrets.example.h
├── tools/               # daemon, hooks, CLI, coletores, protocolo, serviço (stdlib only)
├── tests/               # pytest/unittest + fixtures
├── docs/SPEC.md         # fonte da verdade de design (seções numeradas)
├── docs/superpowers/    # planos e especificações de evolução
├── .claude/             # processo SDD (agentes, specs, archives) + KBs
└── .github/workflows/   # CI: testes, segredos e build dos 2 firmwares
```

## Desenvolvimento

```bash
python -m pytest tests/ -q        # suíte completa (202 testes)
python -m compileall tools tests  # verificação de sintaxe
python tools/check_secrets.py     # guard-rail de segredos
pio run -e esp32-s3-3v5-lcd       # firmware de produção
pio run -e esp32-s3-3v5-lcd-demo  # variante com dados de demonstração
```

O CI roda tudo isso a cada push/PR. Para contribuir, leia
[AGENTS.md](AGENTS.md) — o projeto é desenvolvido com um workflow
spec-driven ([CLAUDE.md](CLAUDE.md)) e as decisões de design estão em
[docs/SPEC.md](docs/SPEC.md).

## Licença

[MIT](LICENSE) © Pedro Henrique Roque Florentino
