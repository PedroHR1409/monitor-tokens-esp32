# Monitor.AI — painel de sessões Claude/Codex (ESP32-S3)

Painel vertical (3.5" IPS, 320×480 portrait) que exibe até 6 sessões ativas de agentes de CLI
(Claude Code / Codex) em um grid 2×3. A build normal inicia vazia e recebe somente dados reais.

Arquitetura e decisões de design: **[`docs/SPEC.md`](docs/SPEC.md)**.

## Antes de compilar

1. **Placa confirmada**: Guition JC3248W535C/EN (pinos, init do painel e orientação já ajustados e
   testados em hardware real — ver `docs/SPEC.md` seção 2 e 8). Se sua placa for outra, reconfirme.
2. **Crie o arquivo local de Wi-Fi** a partir do exemplo:
   ```powershell
   Copy-Item include/secrets.example.h include/secrets.h
   ```
   Edite apenas `include/secrets.h`: Wi-Fi e `MONITOR_API_TOKEN` devem ser valores
   locais. O arquivo está no `.gitignore`; valide antes de compartilhar o projeto com
   `python tools/check_secrets.py`. O daemon lê o mesmo token sem imprimi-lo; a variável
   de ambiente `MONITOR_API_TOKEN` pode sobrescrevê-lo.

## Build & flash (PlatformIO)

```bash
# instalar o PlatformIO CLI, se ainda não tiver
pip install -U platformio

# compilar
pio run

# gravar (ajuste a porta se necessário: pio run -t upload --upload-port COM5)
pio run -t upload

# monitor serial
pio device monitor
```

> Não há Arduino IDE `.ino` neste projeto — a estrutura é PlatformIO (`platformio.ini` +
> `src/` + `include/`), ver racional em `docs/SPEC.md` seção 6.

> **Primeiro build lento?** A primeira compilação baixa e extrai ~300MB de libs pré-compiladas do core
> Arduino-ESP32 3.3.11 (milhares de arquivos pequenos) — se seu antivírus escaneia em tempo real, isso pode levar
> vários minutos parecendo travado. Builds seguintes são rápidos. Para acelerar de vez, exclua a pasta do
> PlatformIO da varredura do Defender (PowerShell como Administrador):
> ```powershell
> Add-MpPreference -ExclusionPath "$HOME\.platformio"
> ```

## Rodando com dados reais (fase 2)

1. Grave o firmware com o WiFi já preenchido em `secrets.h` (ver acima) e abra `pio device
   monitor` — confira a linha `[transport] WiFi OK, IP=...`.
2. No PC, rode o daemon (só Python padrão, sem `pip install`):
   ```powershell
   python tools/session_daemon.py
   ```
   Por padrão ele tenta `http://monitor-ai.local`. Se o mDNS não resolver na sua rede,
   passe o IP visto no passo 1: `python tools/session_daemon.py --host 192.168.2.165`.
3. O grid permanece vazio até o primeiro `POST /sessions` válido. Para demonstração
   visual isolada, compile o ambiente `esp32-s3-3v5-lcd-demo`.

Detalhes do protocolo, das heurísticas de estado (Claude vs Codex) e das limitações conhecidas:
`docs/SPEC.md` seção 5.

## Escondi um card sem querer

O toque longo esconde a sessão (a lista fica na NVS do ESP32). Para trazer todas de volta:

```powershell
curl -X POST http://192.168.2.165/hidden/clear
```
Para ver quais estão escondidas: `curl http://192.168.2.165/hidden`

## Personalizando e removendo sessões

Tabela completa de "o que dá pra mudar e onde": `docs/SPEC.md` seção 6.1. O mais usado no
dia a dia:

```powershell
# tirar um projeto do dashboard (ex: um antigo que não te interessa mais ver)
python tools/dismiss.py add "id-completo-da-sessao"

# devolver
python tools/dismiss.py remove "id-completo-da-sessao"

# ver o que está escondido agora
python tools/dismiss.py list
```
O valor deve ser o ID interno, nunca o nome visível/truncado. Não precisa reiniciar o
daemon nem o ESP32: a alteração aparece no próximo ciclo.

## Estado atual

**Layout** — grid 3x3 + faixa larga, portrait 320x480:

| | | |
|---|---|---|
| sessão 1 | sessão 2 | sessão 3 |
| sessão 4 | sessão 5 | sessão 6 |
| tokens hoje | cota **Codex** 5h | cota **Claude** 5h |
| **heatmap** 12h — tokens/hora + rótulo de hora |||

- ✅ Estados **determinísticos**: `work` / `ask` / `perm` / `free` — `ask` vem do sinal
  exato `AskUserQuestion`, `perm` do hook nativo do Claude Code.
- ✅ **1 card por sessão** (o mesmo projeto pode repetir), ordenado por urgência:
  `perm` > `ask` > `work` > `free`. Nome cortado em 10 caracteres, uma linha.
- ✅ Card de tokens mostra **sessões ativas nas últimas 12h** (janela móvel), não o
  total de sessões no disco.
- ✅ `GET /diag` expõe contadores de touch e tempos de loop para diagnóstico.
- ✅ Contador de tempo **ancorado no relógio** — não acumula erro de refresh.
- ✅ **Dado velho** (daemon fora do ar) fica roxo com `?` em vez de mentir.
- ✅ **Touch** (AXS15231B @ 0x3B): toque curto num card abre o detalhe, toque longo
  esconde a sessão; toque em card vazio abre o seletor.
- ✅ **Cota de 5h** dos dois agentes, com a assimetria explícita: o Codex é o
  `used_percent` **oficial** do servidor, o Claude é **consumo estimado** dos
  transcripts. Ver `docs/SPEC.md` seção 15.
- ✅ Relógio **NTP** no header, **dim noturno** automático (22h–7h).
- ✅ Card pisca na transição de estado; `perm` tinge o card inteiro; ícone de `free`
  dessaturado.
- ✅ Reconexão automática de Wi-Fi.

## Cota de uso (os dois cards ao lado de "tokens hoje")

Os dois números **não têm o mesmo peso**, e o painel assume isso em vez de esconder:

| | Codex | Claude |
|---|---|---|
| % da cota 5h / semanal | ✅ oficial (`used_percent` do servidor) | ❌ não existe no disco |
| horário do reset | ✅ oficial (`resets_at`) | ⚠️ só depois de já ter bloqueado |
| consumo de tokens | ✅ | ✅ (somado do transcript) |

> **"Oficial" não é "atual".** O rollout do Codex só cresce enquanto o **CLI** roda —
> consumo feito por outra superfície não aparece nele, e o último número envelhece
> parado. Passados 5 min da leitura, o card troca a semanal pela idade (`ha 3h`) e
> pinta o número de roxo. Não existe fonte local mais fresca (procurei em
> `.codex-global-state.json`, `state_5.sqlite`, `thread_history_1.sqlite` e
> `logs_2.sqlite`): ver `docs/SPEC.md` seção 16.

O card do Codex mostra `37%` com rodapé `sem 6%` (5h e semanal). O do Claude mostra
consumo com rodapé `estimado` — porque `~/.claude` não guarda cota em lugar nenhum:
o único campo do tipo é `quotaLimits`, que só aparece com `"status":"rejected"`, ou
seja, **depois** de você já ter sido bloqueado.

Sem teto declarado o card do Claude mostra os tokens crus (`3.2M`), que são verdade.
Para virar percentual, declare o teto que você calibrou para o seu plano:

```powershell
$env:MONITOR_CLAUDE_5H_BUDGET = "4000000"
python tools/session_daemon.py
```

Aí o card passa a exibir `~82%` — o til fica, porque um denominador escolhido por você
continua sendo estimativa. Cores: acima de 60% âmbar, acima de 80% vermelho (sem
piscar — piscar é reservado ao `perm`, o único sinal que exige ação imediata).

## Instalação dos hooks de estado

Os instaladores mesclam a configuração existente e aceitam `--dry-run`. Eles não são
executados automaticamente pelo projeto:

```powershell
python tools/install_hook.py --dry-run
python tools/install_hook.py
python tools/install_codex_hook.py --dry-run
python tools/install_codex_hook.py
```
Para conferir os dois de uma vez (sai 1 se faltar algum):

```powershell
python tools/install_hook.py --check
# claude   OK  (C:\Users\...\.claude\settings.json)
# codex    OK  (C:\Users\...\.codex\hooks.json)
```

O daemon também avisa sozinho: se houver sessão de um agente cujo hook não está
instalado, ele imprime `[daemon] AVISO: ...` em stderr — uma vez, e de novo só quando
o diagnóstico mudar.

> **Se o painel virar `?` em todas as sessões, suspeite do hook antes do firmware.**
> `~/.claude/settings.json` é global e outras ferramentas o editam — o Orca já
> substituiu todos os hooks por um handler próprio, deixando só o wrapper legado
> `perm_hook.py`, que marca `free` a cada `PostToolUse`. Sem eventos de `work`/`ask`
> a sessão fica stale em 90s e o card mostra `?`. Rodar os dois instaladores acima
> recoloca o ciclo completo preservando os hooks de terceiros. Diagnóstico:
> Diagnóstico: `python tools/install_hook.py --check`.

Reinicie as sessões depois. `PermissionRequest` é a única origem de `perm`;
`AskUserQuestion` é a origem exata de `ask` no Claude. Os hooks comuns do Codex não
expõem um evento equivalente de pergunta: nesse caso o daemon prefere `work`, `free` ou
dado stale em vez de classificar por idade. Integração futura com o App Server pode
fornecer `tool/requestUserInput` de forma exata.

## Freshness e modo de demonstração

Cada payload válido registra o instante local da recepção, sua idade e a última
comunicação bem-sucedida (`GET /diag`). Após 90 s sem payload válido, header, cards e
métricas deixam de parecer atuais; o último valor permanece apenas como histórico stale.
A API rejeita payload repetido, antigo, futuro ou maior que 16 KiB e exige o token local
nas rotas que recebem dados ou expõem/alteram IDs.
A produção inicia vazia. Dados fictícios só existem no ambiente opt-in:

```powershell
pio run -e esp32-s3-3v5-lcd-demo
```

## Validação local

```powershell
python -m unittest discover -s tests -v
python tools/check_secrets.py
pio run -e esp32-s3-3v5-lcd
```
