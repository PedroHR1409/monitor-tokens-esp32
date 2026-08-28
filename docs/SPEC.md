# SPEC — Monitor de Sessões Claude/Codex (ESP32-S3)

Status: dados reais em produção · UI grid 3x3 + retângulo · v0.3

> **Contrato vigente desde 2026-08-27:** produção inicia vazia; mocks só existem no
> ambiente `esp32-s3-3v5-lcd-demo`. Estados são reduzidos de eventos estruturados:
> `PermissionRequest` é a única origem de `perm`; `ask` exige uma pergunta estruturada
> real e nunca nasce de timeout. A idade do evento representa freshness, não estado.
> IDs completos identificam, ordenam e persistem sessões; o corte de 10 caracteres é
> exclusivo da renderização. Trechos abaixo que descrevem heurísticas antigas ou mocks
> permanentes são registro histórico, não o comportamento atual.

## 1. Referência de arquitetura

Baseado em [`benevid/claude-usage-stick-SVGL`](https://github.com/benevid/claude-usage-stick-SVGL), que roda em
ESP32-S3 (16 MB Flash / 8 MB PSRAM OPI) com display IPS QSPI 480×320 controlado por **AXS15231B**, renderizado com
**LVGL 9.2.x** sobre **GFX Library for Arduino**. Reaproveitamos essa base de hardware/software; o que muda é o
domínio: em vez de % de uso de rate-limit da API Anthropic, este projeto mostra **sessões ativas de agentes de CLI
(Claude Code / Codex)** — até 6 simultâneas, em grid.

Diferenças deliberadas em relação ao repo de referência:
- Orientação **portrait** (320×480 lógico, painel físico 480×320 rotacionado), não landscape com tileview de swipe.
- Sem contas/criptografia NVS/OAuth — o ESP32 é um **display passivo** que recebe eventos de um daemon local no PC.
- Sem chamada direta à API da Anthropic a partir do firmware.

## 2. Hardware confirmado

Placa real identificada (link do usuário): **Guition JC3248W535C/EN**, "ESP32-S3 3.5-inch capacitive touch IPS
module, 8M PSRAM, 16M FLASH" — AliExpress item `1005007566332450`.

| Item | Valor |
|---|---|
| MCU | ESP32-S3, 16 MB Flash, 8 MB PSRAM **OPI** (obrigatório — buffer LVGL não cabe na RAM interna) |
| Display | IPS 3.5", controlador AXS15231B, barramento **QSPI**, **320×480 físico nativo (já portrait)** |
| Orientação | Portrait, rotação 0 — sem rotação de software (painel não é landscape+rotate) |
| Touch | GT911 via I²C (SDA=4, SCL=8, INT=3) — **não** é o touch nativo do AXS15231B como presumido inicialmente; presente no painel, **não usado no MVP** — reservado para fase 2 |

Pinos QSPI/backlight/reset confirmados via `PINS_JC3248W535.h` do repositório oficial de pinouts do autor da
GFX Library (`moononournation/Dev_Device_Pins`) — mesmos valores já usados em `include/config.h`, ver seção 8
para o bug de inicialização que isso revelou e corrigiu.

> Se sua placa for de outro vendedor/modelo (não a Guition JC3248W535), reconfirme pinos e a tabela de
> `init_operations` do AXS15231B contra o exemplo específico dela — ver aviso na seção 8.

## 3. Modelo de dados da sessão

```cpp
enum class ToolType : uint8_t { CLAUDE, CODEX, UNKNOWN };

// Vocabulário fechado — ver secção 6.1 para o significado de cada um.
enum class SessionState : uint8_t { WORK, ASK, PERM, FREE, IDLE, ERROR_STATE };

struct SessionData {
    char     id[16];            // id estável (session id do transcript)
    char     projectName[24];   // nome exibido, truncado na UI com "..."
    ToolType tool;
    SessionState state;
    uint32_t elapsedSeconds;    // tempo decorrido no estado atual
    uint32_t lastUpdateMillis;  // millis() do último evento recebido -> detecta staleness
    bool     occupied;          // false = card vazio
};

#define MAX_SESSIONS 6
```

Regras:
- `elapsedSeconds` conta a partir da última transição de estado, não da sessão inteira —
  reflete "há quanto tempo está `work`/`perm`". Quem calcula é o daemon (a partir da idade
  do evento atual), então o contador reinicia sozinho quando o estado muda.
- **Staleness**: se `millis() - lastUpdateMillis > STALE_TIMEOUT_MS` (padrão 90 s), o card
  cai para `FREE` mesmo sem novo evento — cobre o daemon do PC cair ou perder rede.
- `ERROR_STATE` reservado (ex.: hook mal configurado) — não usado ainda, cor já no tema.

## 4. Layout de UI (histórico)

> **Superado.** O layout atual é o grid 3x3 + card retangular descrito na **secção 6.1**.
> Esta secção documentava o grid 3x2 original do MVP e ficou aqui só como registro da
> evolução: header 32px, 2 colunas x 3 linhas de cards, badge de estado no canto inferior
> direito, footer reservado.

## 5. Protocolo de comunicação (fase 2 — implementada)

- **Transporte**: `WebServer` (síncrono, builtin do core Arduino-ESP32 — trocado de `AsyncWebServer` para não
  adicionar mais uma lib externa) + mDNS (`agents-monitor.local`), no mesmo espírito do `token_bridge.py` do
  repo de referência.
- **Contrato `POST /sessions`**: corpo JSON, até `MAX_SESSIONS` itens:
  ```json
  {"sessions": [
    {"id": "sess-01", "project": "monitor-tokens-esp32", "tool": "claude", "state": "work", "elapsed": 12}
  ]}
  ```
  `tool`: `"claude"` | `"codex"` | `"opencode"`. `state`: `"work"` | `"ask"` | `"perm"` | `"free"` (mapeados para
  `SessionState` em `session_transport.cpp`). Slots não enviados numa atualização voltam a `occupied=false`
  (sessão encerrada no PC). `elapsed` é a idade em segundos calculada pelo daemon — o firmware não soma mais
  localmente em modo de dados reais, só exibe o último valor recebido (evita deriva de relógio entre PC e ESP32).
- **Campo `provider` (opcional, por sessão)**: o dono do modelo (`"zai"`, `"deepseek"`, ...), preenchido
  hoje só pelo coletor OpenCode. O firmware usa `provider` para escolher o ícone (GLM → Z.AI,
  DeepSeek → DeepSeek) e cai no ícone clássico da ferramenta quando vem vazio — Claude/Codex
  continuam sem o campo, então o contrato é retrocompatível (ver seção 6.2).
- `GET /health` — heartbeat simples.
- **Direção PC → ESP32**: `tools/session_daemon.py` (só biblioteca padrão do Python, sem `pip install`) faz
  *polling* — não há hooks instalados por padrão (ver justificativa abaixo) — a cada `--interval` segundos
  (padrão 5s) e dá `POST /sessions`.
- **Fontes de dados**:
  - **Claude Code**: varre `~/.claude/projects/*/*.jsonl`, pega o `.jsonl` mais recente de cada projeto
    (1 slot por projeto, não por sessão histórica). Lê só o final do arquivo (não o arquivo inteiro — alguns
    transcripts passam de vários MB). Nome do projeto vem do campo `cwd` das linhas do transcript (não da
    pasta sanitizada, que é ilegível). Estado inferido do `type`/`stop_reason` da última linha:
    `type:"user"` → `work`; `type:"assistant"` com `stop_reason:"tool_use"` muito recente → `work`, senão
    `perm` (provável prompt de permissão parado); `assistant` com turno concluído → `ask`; sem atividade
    por > 90s → `free`.
  - **Codex CLI**: lê `~/.codex/session_index.jsonl` (log append-only; dedup por `id`, mantém a última
    ocorrência). Nome = `thread_name`. Estado só por recência de `updated_at` (`work` < 30s,
    `ask` < 90s, senão `free`) — **menos preciso que o Claude**, e nunca produz `perm`, porque esse
    índice não expõe conteúdo de turno, só um timestamp de toque.
  - As duas listas são unidas e ordenadas por recência; os `MAX_SESSIONS` mais recentes ganham um card.
- **Por que polling e não hooks**: Claude Code suporta hooks nativos (`PermissionRequest`, `Stop`, etc. — já
  usados por outra automação nesta máquina) que dariam estado exato de "aguardando permissão". Optei por
  **não** mexer no `~/.claude/settings.json` do usuário automaticamente (arquivo grande, já orquestra outra
  automação em produção) — mexer nisso é uma mudança de configuração viva, fora do escopo de "instalar
  dependências e rodar o firmware". Fica como upgrade opcional documentado abaixo, não aplicado.
- **Staleness/timeout**: `STALE_TIMEOUT_MS` (seção 3) ainda protege o firmware se o daemon parar de rodar —
  os cards recebidos na última atualização não ficam "congelados" para sempre.
- **Por que não WebSocket**: HTTP simples é suficiente para 6 sessões atualizando a cada poucos segundos.

> **Upgrade opcional (mais preciso, não aplicado)**: adicionar um hook `PermissionRequest`/`Stop`/
> `UserPromptSubmit` próprio em `~/.claude/settings.json` (Claude Code aceita múltiplos hooks por evento —
> não precisa substituir os que já existem) que grave `{"event", "ts"}` num arquivo por sessão; o daemon leria
> esse arquivo em vez de inferir estado do transcript. Não implementado aqui de propósito, para não editar a
> configuração viva do Claude Code sem pedido explícito.

## 5.1. Deteccao de estado — a reescrita determinística (fase 4)

**O bug.** A versao anterior decidia o estado olhando `objs[-1]` (a ultima linha bruta do
transcript) e a `mtime` do arquivo. Medindo os 15 transcripts reais da maquina do usuario:
**nenhum termina com linha `user` ou `assistant`** — todos terminam em bookkeeping
(`last-prompt`, `mode`, `attachment`, `atis-latch`, `system`). Ou seja, os ramos que
tratavam conversa eram **codigo morto**, e tudo caia no fallback por idade:

```python
return "work" if age <= 15 else "ask"     # o que realmente rodava
```

Na pratica: `work` = arquivo tocado ha <15s, `ask` = tocado entre 15s e 90s, `free` =
mais que isso, e `perm` **inalcancavel**. `ask` nao tinha nenhuma relacao com "existe
pergunta aguardando" — era so uma faixa de tempo.

**A correcao** (`tools/session_state.py`):

1. Varre de tras pra frente ate o ultimo evento **conversacional** (`user`/`assistant`),
   ignorando bookkeeping e `isSidechain` (para um subagente nao mascarar a sessao mae).
2. Usa o **`timestamp` do proprio evento**, nao a mtime — qualquer escrita de bookkeeping
   bumpa a mtime, o timestamp do evento nao mente.
3. Deriva o estado do par de eventos:

| Sinal | Estado |
|---|---|
| hook `PermissionRequest` ativo | **perm** (exato) |
| ultimo evento = `user` | **work** |
| `tool_use` de `AskUserQuestion` sem `tool_result` | **ask** |
| outro `tool_use` sem `tool_result`, parado >8s | **perm** (heuristica) |
| `tool_use` ja respondido, ou turno concluido | **work** / **free** |

`AskUserQuestion` foi a descoberta que fechou a definicao do usuario ("ask so quando
depende de resposta a uma pergunta do modelo") num sinal exato, sem heuristica de tempo.

**Segundo falso positivo, medido e corrigido:** uma sessao cujo terminal foi fechado no
meio de um `tool_use` ficava em `perm` para sempre — medi um caso real de **191 horas** —
e, com a ordenacao por urgencia, entupia o topo da lista. `PERM_MAX_AGE_S` (30min) faz o
`perm` inferido decair para `free`: uma permissao de verdade se responde em minutos.

**Hook** (`tools/perm_hook.py`, instalado por `tools/install_hook.py`): `PermissionRequest`
marca a sessao, `PostToolUse`/`Stop` limpam. O installer faz backup, **acrescenta** aos
arrays existentes (a config do usuario ja orquestra outra automacao), e e idempotente.

## 6. Bibliotecas e arquitetura de arquivos

| Escolha | Motivo |
|---|---|
| **PlatformIO** (não Arduino IDE) | Gestão de deps/versão reprodutível (`platformio.ini`), `partitions.csv` versionado. |
| **pioarduino** como `platform` (não o `espressif32` oficial do registry) | O `espressif32` oficial do PlatformIO ainda empacota Arduino-ESP32 2.0.17 (IDF 4.4), sem `esp32-hal-periman.h` — exigido pela GFX Library p/ o driver AXS15231B. pioarduino empacota o core **3.3.11** (IDF 5.5), a mesma versão usada no repo de referência. Confirmado via build real (ver seção 8). |
| **LVGL 9.2.x** | Mesma versão do repo de referência; widgets prontos (label, obj, pill) resolvem o grid de cards sem desenhar pixel a pixel. |
| **GFX Library for Arduino** (`Arduino_GFX`) | Já tem driver `Arduino_AXS15231B` sobre barramento QSPI — evita escrever driver do zero. |
| *(descartado)* TFT_eSPI | Sem suporte nativo a QSPI/AXS15231B neste painel; repo de referência migrou para longe dele pelo mesmo motivo. |

```
monitor-tokens-esp32/
├── platformio.ini
├── partitions.csv
├── docs/SPEC.md
├── include/
│   ├── config.h          # pinos QSPI, dimensões, timings, WiFi/mDNS/porta HTTP
│   ├── secrets.h          # credenciais WiFi (EDITAR — não sobe com valores reais)
│   ├── lv_conf.h          # config mínima do LVGL (resto cai no default interno)
│   ├── session_model.h    # struct/enums da seção 3
│   └── ui_theme.h         # paleta de cores e constantes de layout da seção 4
├── src/
│   ├── display_driver.h/.cpp    # init do Arduino_GFX + ponte LVGL (flush/tick)
│   ├── session_manager.h/.cpp   # array de sessões + mock updater (boot/fallback)
│   ├── session_transport.h/.cpp # WiFi + servidor HTTP (POST /sessions), seção 5
│   ├── ui_dashboard.h/.cpp      # monta o grid de 6 cards e expõe update_dashboard()
│   └── main.cpp                  # setup()/loop()
└── tools/
    └── session_daemon.py     # daemon do PC — lê Claude Code + Codex e faz POST /sessions
```

## 6.1. Visualizacao: grid 3x3 + card retangular (fase 3 — implementada)

Layout remodelado a partir de referencia visual estilo Stream Deck fornecida pelo usuario.

### Grade

```
+-----+-----+-----+   9 cards quadrados de 96x96px (3 col x 3 lin)
|  1  |  2  |  3  |   + 1 card retangular 304x92px (largura das 3 colunas)
+-----+-----+-----+
|  4  |  5  |  6  |   Cards 1-6  -> sessoes reais (SESSION_CARDS)
+-----+-----+-----+   Cards 7-9  -> placeholders vazios
|  7  |  8  |  9  |   Card 10    -> placeholder vazio, retangular
+-----------------+
|       10        |
+-----------------+
```

Constantes em `include/ui_theme.h` (`GRID_COLS`, `GRID_SQ_ROWS`, `MARGIN`, `GUTTER`,
`SESSION_CARDS`, `TOTAL_CARDS`). Todos os cards compartilham `build_card_shell()`; so os
de sessao recebem conteudo, via `build_session_card()`. Nao ha codigo especifico por
indice de card.

### Conteudo do card de sessao

```
+-------------------------+
| 32s               perm  |   tempo (topo-esq) / estado (topo-dir)
|                         |
|         [icone]         |   40x40px, PNG real do provider
|                         |
|      nome-do-projeto    |   rodape, centralizado, ellipsis
+-------------------------+
```

- **Icone**: PNG real fornecido pelo usuario (`src/claude.png`, `src/gpt.png`), nao mais
  forma geometrica desenhada. Pipeline de geracao na secao 6.2.
- **Tempo**: `format_elapsed()` — `Ns` < 1min, `Mm` < 1h, `Hh` acima. Reinicia quando o
  estado muda porque o daemon recalcula `elapsed` a partir da idade do evento atual.
- **Estado**: vocabulario fechado de 4 valores, definido em `include/session_model.h`
  (`SessionState`) e mapeado em uma unica funcao (`color_for_state`/`label_for_state`),
  sem condicionais espalhadas pela UI:

| Estado | Cor | Significado |
|---|---|---|
| `work` | verde `#22C55E` | modelo processando/executando |
| `ask` | azul `#3B82F6` | esperando a proxima mensagem do usuario |
| `perm` | ambar `#F59E0B` | esperando autorizacao de uma tool |
| `free` | cinza `#6B7280` | sessao existe mas ociosa |

- **Nome**: `LV_LABEL_LONG_MODE_DOTS` com largura fixa (`cell - 12`) — nomes longos
  truncam com reticencias em vez de quebrar o layout. O daemon ja corta em 23 chars
  (buffer C de 24 em `SessionData::projectName`).
- **Borda do card** muda de cor com o estado (2px quando precisa de atencao, 1px quando
  `free`) — status reconhecivel num relance, sem depender so do texto pequeno.

### Slots vazios

Um card de sessao sem dados (`occupied == false`) esconde tempo/estado/icone/nome e volta
a borda neutra, ficando visualmente identico aos placeholders 7-10 — o grid nunca "perde"
uma celula.

## 6.2. Pipeline dos icones PNG

Os PNGs originais do usuario ficam em `src/assets/` e os gerados em `src/icons/` (o `src/`
raiz agora tem so codigo, organizado por camada: `src/ui/`, `src/drivers/`, `src/sessions/`;
os includes resolvem pelos `-Isrc/...` no `platformio.ini`). O pipeline atual, todo stdlib:

1. **Conversao direta**: `python tools/icon_convert.py src/assets/<marca>.png
   src/icons/<marca>_icon.c` — decodificador PNG proprio (bit depth 8, types 2/3/6,
   sem interlace), resize de media de area pre-multiplicada por alfa, centralizado num
   canvas transparente de 40x40, saida no formato `lv_image_dsc_t` ARGB8888 (bytes
   B,G,R,A por pixel) que a LVGLImage.py oficial produz.
2. **Declaracao**: adicionar o `extern` em `src/ui/icons.h` e mapear o provider em
   `icon_for_provider()` (`src/ui/ui_dashboard.cpp`).

Historico: os icones claude/gpt originais passaram por pre-processamento com PIL
(color-key do branco, recorte, recolorida do GPT para branco) e depois pela
`LVGLImage.py` oficial da LVGL; os `.c` gerados seguem em `src/icons/` sem precisar
regenerar. Novos icones nao precisam desse passo — `icon_convert.py` ja trata
transparencia nativa (o DeepSeek e o Z.AI entraram por aqui).

O icone do card e escolhido pelo `provider` do modelo, nao pela ferramenta: GLM no
OpenCode mostra a Z.AI (`zai`), DeepSeek mostra o logo da DeepSeek. Claude/Codex nao
mandam provider e caem no icone classico.

## 7. Escopo do MVP (o que este código entrega)

- Boot do display em portrait, grid 3×2 renderizado com LVGL.
- 6 `SessionData` mockados no `session_manager.cpp`, cobrindo os 3 estados visuais + 1 card vazio.
- `lv_timer` de 1s incrementando `elapsedSeconds` das sessões ativas/aguardando, e um timer de 15s que alterna o
  estado de uma sessão para validar que o card re-renderiza (cor do badge, texto) sem rebuild de layout — prova de
  fluidez pedida no escopo.
- **Fora do escopo**: Wi-Fi, servidor HTTP, touch, ícones bitmap, footer funcional — todos com espaço já reservado
  no layout para entrarem sem retrabalho.

## 8. Validação de build

`pio run` executado com sucesso (v0.1): `firmware.bin` gerado sem erros.

```
RAM:   [===       ]  27.8% (used 91248 bytes from 327680 bytes)
Flash: [=         ]  10.7% (used 698584 bytes from 6553600 bytes)
```

Bugs reais encontrados e corrigidos durante essa validação (além da troca de `platform` na seção 6):
- `LV_LABEL_LONG_MODE_DOT` não existe no LVGL 9.5 — corrigido para `LV_LABEL_LONG_MODE_DOTS` em `ui_dashboard.cpp`.
- `BLACK` não é uma macro definida pela GFX Library for Arduino (diferente do Adafruit_GFX) — `display_driver.cpp`
  usa `0x0000` (preto em RGB565) diretamente em `gfx->fillScreen(...)`.

**Bring-up em hardware real (Guition JC3248W535)**: primeiro flash resultou em tela preta com upload OK. Causa:
o construtor de 6 argumentos de `Arduino_AXS15231B` (sem `init_operations` explícito) usa por padrão a
sequência de inicialização de **outro** painel AXS15231B (variante 180×640) — o painel nunca recebe os
comandos de registro corretos para a variante 320×480 "type1" desta placa, então fica preto mesmo com os
pinos QSPI certos. Corrigido usando o construtor de 11 argumentos com
`axs15231b_320480_type1_init_operations` (definida em `Arduino_AXS15231B.h` da própria GFX Library), e
resolução/rotação nativas do painel (320×480, rotação 0 — sem rotação de software, ver seção 2).

> **Se você usa outra placa AXS15231B** (não a Guition JC3248W535): confira se o exemplo dela também passa uma
> `init_operations` explícita — usar o construtor "simples" de 6 argumentos é a causa mais provável de tela
> preta com upload bem-sucedido nesse controlador.

Segundo bug encontrado no bring-up (após a tela deixar de ficar preta): o conteúdo aparecia comprimido numa
faixa vertical estreita na borda direita da tela, com cores erradas. Causa: este painel AXS15231B via QSPI não
lida bem com escritas de **área parcial pequena** — o `LV_DISPLAY_RENDER_MODE_PARTIAL` original do MVP manda
várias atualizações pequenas por frame (uma por card/label que mudou), e isso corrompe o endereçamento no
controlador. Confirmado contra outro exemplo funcional desta mesma placa (`carlosmsx/JC3248W535`), que só
funciona porque envolve o painel num `Arduino_Canvas` que sempre transfere o frame inteiro de uma vez.

Corrigido trocando para **um buffer de tela cheia (320×480×2 bytes ≈ 300KB) em PSRAM com
`LV_DISPLAY_RENDER_MODE_FULL`** — cada flush do LVGL manda a tela inteira numa única escrita QSPI, em vez de
pequenos retângulos. Custo: mais RAM (2×300KB em vez de 2×30KB) e uma transferência SPI maior por frame — sem
problema dado o orçamento de PSRAM (seção 2) e a taxa de atualização baixa deste dashboard (1x/segundo).

> **Se você usa outra placa AXS15231B**: se a imagem aparecer cortada, deslocada ou numa faixa estreita mesmo
> com os pinos e a `init_operations` certos, o suspeito nº 1 é este — troque para
> `LV_DISPLAY_RENDER_MODE_FULL` com buffer de tela cheia.

Terceiro bug encontrado (grid já renderizando certo, mas com cores erradas): fundo quase preto (`#111318`)
aparecia como rosa pastel, e o badge âmbar (`#F59E0B`, estado `WAITING_INPUT`) aparecia magenta/rosa vivo.
Verde sobrevivia quase intacto. Reproduzindo o cálculo RGB565 manualmente, isso bate exatamente com **1 troca
de bytes a mais do que o necessário** na cor de cada pixel — `LV_COLOR_16_SWAP` estava setado como `1` em
`include/lv_conf.h`, mas o `Arduino_GFX` já lida com a ordem de bytes correta para o barramento QSPI
internamente. Corrigido para `LV_COLOR_16_SWAP 0`.

> **Se as cores saírem trocadas/lavadas** (preto virando rosa/roxo pastel, ou qualquer cor com tom
> claramente errado mas ainda "no mesmo bairro" de matiz): inverta o valor de `LV_COLOR_16_SWAP` em
> `lv_conf.h` — é byte order duplicado ou faltando, não um problema de paleta.

> Nota de ambiente: extrair o pacote de libs pré-compiladas do core 3.3.11 (~300MB, milhares de arquivos) é lento
> em máquinas com antivírus escaneando cada arquivo em tempo real. Se a primeira `pio run` "travar" por vários
> minutos nesse passo, é esperado — normalmente é só isso, não uma falha real. Excluir a pasta `.platformio` da
> varredura em tempo real do Defender resolve para as próximas compilações.

### Timer: dois bugs distintos (fase 4)

**Modo mock:** `elapsedSeconds++` a cada tick de 1s, com `lastTickSecond = now`
descartando o overshoot. Como cada iteracao do loop custava caro (frame cheio de 307KB
por QSPI + sombras + `delay(5)`), o tick caia a cada ~1,1-1,3s: contador **10-25% lento,
com erro acumulando**. **Modo live:** `session_manager_tick()` nem era chamado — o valor
so mudava a cada POST (5s), entao congelava e pulava.

**Correcao:** `SessionData::stateStartedAtMillis`. O tempo exibido e sempre
`(millis() - stateStartedAtMillis)`, calculado na hora de desenhar. Nao ha contador
acumulado, logo nao ha deriva possivel. A ancora e reescrita **so quando o estado ou a
sessao mudam** — reancorar a cada POST faria o numero saltar com o arredondamento do
daemon.

### Performance: a causa raiz do drift

`ui_dashboard_update()` rodava 1x/s e chamava ~49 `set_text`/`set_style`
incondicionalmente. Como todo `lv_label_set_text` invalida a tela e o render e FULL, isso
custava um frame de 307KB por segundo. Agora toda escrita passa por um guard que compara
com o ultimo valor (`set_text_if`, `set_color_if`, `set_flag_if`): em regime, so os
poucos textos que mudaram sao redesenhados.

### Staleness: regra documentada que nunca existiu

`STALE_TIMEOUT_MS` estava definido em `config.h` e descrito na spec, mas **nao era usado
em lugar nenhum do firmware**. Se o daemon morresse, os cards congelavam no ultimo estado
para sempre, sem sinalizar nada. Agora `session_transport_mark_stale()` roda a cada
segundo e o card passa a exibir cor roxa + "?" — o painel admite que nao sabe, em vez de
mentir que o estado ainda vale.

## 9. Correcoes da fase 5

### Touch: comando I2C truncado (causa raiz)

A sequencia de leitura do AXS15231B tem **11 bytes**, nao 8. A implementacao de
referencia declara `AXS_READ_TOUCHPAD[11]` inicializando so os 8 primeiros valores — os
3 restantes ficam zerados por regra do C, e `sizeof` devolve 11. Enviando apenas 8 bytes
o controlador nao reconhece o comando e nunca devolve coordenada: o `indev` do LVGL era
criado e lido normalmente, mas sempre com "sem toque", entao nenhum evento chegava aos
objetos clicaveis. Faltava tambem o `delayMicroseconds(50)` entre comando e leitura, e a
condicao de toque valido correta (`data[0] == 0 && data[1] != 0`).

### GET /diag

Validar "um toque real gera o evento esperado" pelo log serial exige alguem lendo o
monitor no instante do toque. O endpoint expoe contadores que permitem confirmar de
fora: `touches` sobe => o driver leu o hardware; `pomo_clicks` sobe => o evento chegou ao
objeto certo. Se o primeiro sobe e o segundo nao, o problema e mapeamento de coordenada
ou hit-testing, nao o driver. Tambem expoe tempos de loop/render, que foi como se mediu
a cadencia real da UI em vez de confiar em impressao visual.

Medicao apos a correcao, em regime: **1,00 update/s**, 124 iteracoes de loop/s, 21
leituras de touch/s, render maximo 128ms, flush QSPI medio 48ms.

> Armadilha de medicao: amostrar o `/diag` logo apos o boot da numeros alarmantes
> (`loops=2` em 42s) porque o `setup()` — WiFi, NTP, montagem da UI — ainda esta rodando.
> Compare duas amostras espacadas em vez de olhar valores absolutos.

### Cadencia do tick de 1s

O tick usava `lastUiTick = now`, descartando o overshoot de cada iteracao: os updates
escorregavam (1,0s, 1,2s, 1,4s...) e o valor parecia "andar em blocos". Agora avanca em
passos fixos de 1000ms, com ressincronizacao se atrasar mais de 3 ciclos.

### Nome da sessao: corte no valor, nao no visual

Antes o limite era so visual (`LONG_MODE_DOTS` cortava por largura). Agora o corte e no
valor efetivamente renderizado: o daemon envia no maximo `NAME_MAX` (10) caracteres e o
firmware repete o corte em `NAME_LIMIT` antes de passar ao LVGL, com `LONG_MODE_CLIP`.
Nao ha como quebrar linha nem invadir os elementos do card.

### Sparkline: linha, nao barras

Era um conjunto de 12 retangulos com altura variavel — grafico de colunas. Agora e um
`lv_chart` em `LV_CHART_TYPE_LINE`, sem grade, sem eixos, sem moldura e com os
marcadores de ponto zerados (`lv_obj_set_style_size(..., LV_PART_INDICATOR)`). Os dados
sao os mesmos; so a escala do eixo Y acompanha o pico.

### Metrica do card: sessoes ativas em 12h

Exibia `total_sessions` — 74, contando tudo que existe no disco, inclusive sessao parada
ha dias. Agora e `count_active_12h()`: janela movel `[agora-12h, agora]`, deduplicada por
id de sessao (um `set`, entao N eventos de uma sessao contam uma vez). A `mtime` serve so
como filtro barato (mtime velha => impossivel ter atividade na janela); nos arquivos que
passam, confirma-se com o timestamp do ultimo evento **conversacional**, porque
bookkeeping bumpa a mtime sem ter havido turno. Codex usa `updated_at`. Medido: 2 na
janela de 12h contra 74 do disco, e a contagem cresce ao alargar a janela (2 / 4 / 13
para 12h / 24h / 72h).

## 10. Correcao do falso `perm` (fase 6)

**Causa raiz.** Existia a heuristica: "tool_use sem tool_result ha mais de 8s =>
provavelmente travado num prompt de permissao". Ela e errada por construcao. No
transcript, uma ferramenta EXECUTANDO e uma ferramenta BLOQUEADA aguardando autorizacao
produzem exatamente o mesmo registro — um `tool_use` sem `tool_result`. O limiar de 8
segundos nao separava os dois casos, apenas classificava como `perm` qualquer comando
mais demorado que isso: um build, um `timeout 40 python3 ...`, uma captura de serial.

**Solucao.** A heuristica de tempo foi removida por completo. `perm` passa a vir
exclusivamente do hook `PermissionRequest` do proprio Claude Code — o unico sinal que
sabe que o harness abriu o dialogo e travou a execucao. Um `tool_use` sem resposta agora
significa `work` (ferramenta rodando), com `WORK_MAX_AGE_S` ampliado para 30 min para
nao derrubar build/teste longo. Sem hook ativo, `perm` simplesmente nao ocorre — melhor
nao afirmar do que afirmar errado.

Complemento: o daemon descarta marcas do hook mais velhas que `PERM_MARKER_MAX_AGE_S`
(10 min), cobrindo o caso do Claude Code morrer com um dialogo aberto — sem isso a marca
ficaria no arquivo sem ninguem para limpa-la e a sessao ficaria presa em `perm`.

**Validacao.** 18 casos automatizados, incluindo o cenario reportado (Bash de 14s e de
40s => `work`), build de 20 min => `work`, e as transicoes `work -> perm -> work`,
`work -> ask -> work`, `work -> free`. Em dados reais: 0 sessoes em `perm` (correto, sem
dialogo aberto) e a sessao que roda comandos agora aparece corretamente como `work`.

## 11. Formato do dado do grafico (medido)

O card do grafico mostra 12 baldes de 1 hora de tokens. Medicao real: **10 dos 12 baldes
sao zero**, e a razao entre o pico e o menor valor nao-nulo chega a 10x. Uso de tokens e
esparso e em rajadas — trabalha-se em blocos, entao a maioria das horas e genuinamente
zero. Uma linha continua sobre esse dado vira uma reta colada no chao seguida de um
penhasco vertical. Isso nao e defeito de renderizacao: e incompatibilidade entre o
formato do dado e a forma escolhida para representa-lo. Qualquer proposta de UX para
esse card precisa partir dessa medicao.

## 12. Heatmap de 12 horas (substitui o grafico de linha)

Escolhido pelo usuario entre 5 alternativas propostas, a partir da medicao da secao 11.

Layout no card de 304x118, **sem titulo** — o espaco foi para os rotulos, que carregam
mais informacao que uma legenda fixa:

```
 2.6  0.5  0.0                      <- tokens da hora, sempre em milhoes
 [##] [# ] [# ] [  ] [  ] ...       <- 12 blocos de intensidade (22x46px)
  08   09   10   11   12  ...       <- hora local do balde
```

Decisoes de implementacao:

* **22px por celula** (pad 6, gap 2): medido para caber "2.7" em montserrat_12 (21px).
  A fonte 12 foi habilitada no `lv_conf.h` so para estes rotulos.
* **Hora zerada fica com o rotulo em branco.** Doze "0.0" seriam ruido visual, e o bloco
  apagado ja comunica ausencia de uso.
* **Piso de opacidade** (`HM_MIN_OPA = 70`): com pico ate 10x o menor valor nao-nulo,
  uma escala linear pura deixaria as horas de pouco uso praticamente invisiveis.
* **Hora corrente destacada** (texto mais claro) para dar referencia temporal.
* A hora de cada balde vem de `spark_end_hour` (hora local do ultimo balde, enviada pelo
  daemon); as demais sao derivadas para tras, uma por hora.

> Nota: um valor real porem pequeno (ex.: 28 mil tokens) aparece como "0.0", porque a
> unidade pedida foi sempre milhoes. A celula acesa continua indicando que houve uso.

## 13. Modelo e branch na tela de detalhe

**Branch.** Vinha do campo `gitBranch` do transcript, que vale `"HEAD"` quando o
diretorio nem e repositorio git — e isso aparecia na tela como se fosse nome de branch.
Agora `session_meta.read_git_branch()` le `<cwd>/.git/HEAD` direto do disco, o que
resolve dois problemas: da a branch **atual** (nao um retrato de quando o turno rodou) e
separa os casos: nome da branch, `detached`, `sem git` (diretorio existe, sem `.git`) ou
vazio (nem sabemos o diretorio).

**Modelo do Codex.** O `session_index.jsonl` so tem id/thread_name/updated_at, entao
modelo e branch vinham vazios. Os arquivos `~/.codex/sessions/AAAA/MM/DD/rollout-*.jsonl`
trazem `payload.model` e `payload.cwd`, e o UUID no nome do arquivo e o mesmo id do
indice — da para casar sem abrir todos. O indice de nomes e montado uma vez e reusado; de
cada rollout le-se so o inicio (96KB), onde model/cwd aparecem.

**Limitacao medida:** apenas 36 rollouts existem para 52 ids do indice, entao sessoes
antigas do Codex ficam sem modelo (exibem `-`). Verifiquei o `thread_history_1.sqlite`
como fonte alternativa: das 1254 linhas de `thread_items`, **nenhuma** tem campo `model`.
Nao ha outra fonte local — melhor exibir `-` do que inventar.

O nome do modelo e encurtado (`short_model`): `claude-haiku-4-5-20251001` vira
`haiku-4-5`, descartando a data de release, que nao cabe e nao informa nada.

## 14. Metadados do Codex (correcao)

Eu havia registrado que "o Codex nao expoe effort nem uso de tokens em nenhuma fonte
local" e preenchido esses campos com vazio. **Estava errado, e por nao ter procurado.**
Na primeira investigacao dos rollouts eu busquei apenas `model` e `cwd`; ao varrer todos
os campos, os tres estao la:

| Campo | Caminho no rollout |
|---|---|
| modelo | `turn_context.model` |
| effort | `turn_context.effort` |
| tokens | `event_msg.info.total_token_usage.total_tokens` |

**Tokens na janela.** O total e ACUMULATIVO ao longo da sessao e cada linha tem
`timestamp`, entao os tokens da janela sao `(ultimo total) - (ultimo total anterior ao
inicio da janela)`. Isso evita somar turno a turno e nao conta duas vezes caso um evento
se repita.

**Custo.** Os 36 rollouts somam 13 MB (mediana 167 KB, maior 2 MB). Ler inteiro e
viavel, mas ha cache por (caminho, tamanho, janela): arquivo que nao cresceu nao e
reparseado. Medido: 0,03s para tres sessoes, 0,80s para o payload completo.

**Limitacao que permanece:** existem 36 rollouts para 52 ids do indice, entao sessoes
antigas do Codex seguem sem metadado (exibem `-`). O `thread_history_1.sqlite` foi
verificado e nao tem `model` em nenhuma das 1254 linhas.

## 15. Cota de uso: um numero oficial e um estimado (fase 7)

O Pomodoro saiu do painel (nao era usado) e a faixa de 200x96 que ele ocupava virou
DOIS cards de 96x96: cota do Codex e cota do Claude. A divisao nao e estetica — os
dois numeros tem procedencias diferentes e separa-los fisicamente carrega essa
diferenca melhor do que um rotulo miudo dentro de um card unico.

### Codex: oficial

Cada evento `token_count` do rollout carrega o bloco que o SERVIDOR devolveu:

```json
"rate_limits": {"primary":   {"used_percent": 7.0,  "window_minutes": 300,   "resets_at": ...},
                "secondary": {"used_percent": 61.0, "window_minutes": 10080, "resets_at": ...},
                "credits": {"balance": "93.8120090000"}, "plan_type": "plus"}
```

**A janela e classificada por `window_minutes`, nunca pela posicao.** Medido nos
rollouts reais: a semanal apareceu ora em `primary`, ora em `secondary`, e o outro
bucket as vezes vem `null`. Ler pela posicao troca 5h por semanal sem erro visivel —
o mesmo cuidado que o parser do `codex-usage-stick` ja tinha exigido. As duas janelas
sao resolvidas de forma independente, cada uma ficando com o evento de maior timestamp
que a contenha.

**Custo.** A cota e global da conta e reescrita a cada turno, entao nao ha motivo para
varrer os 37 rollouts: sao lidos os 128 KB finais dos 3 arquivos de mtime mais recente,
com filtro por substring antes do `json.loads`.

### Claude: estimado, e por que nao da para ser melhor

Varredura de `~/.claude` inteiro: nao existe `used_percent`, `utilization` nem
`five_hour` em disco fora dos transcripts. O unico campo de cota e `quotaLimits`:

```json
{"status": "rejected", "rateLimitType": "five_hour", "resetsAt": 1787076000}
```

Note o `"status": "rejected"` — ele so aparece DEPOIS do bloqueio. Serve para dizer
"quando volta", nunca para avisar "esta acabando".

**Armadilha encontrada na investigacao:** uma busca inicial acusou `five_hour` e
`resets_at` no transcript e quase virou implementacao. A origem real eram as buscas da
propria sessao que investigava — o monitor contaminando o que monitorava. Confirmar a
procedencia antes de tratar um campo como fonte foi o que evitou o falso positivo.

Entao o maximo honesto e o CONSUMO somado dos transcripts na janela de 5h (a mesma
janela curta do Codex, para os cards ficarem comparaveis). Consumo nao e cota: sem o
teto do plano, um percentual teria denominador inventado. Por isso `pct` so e
preenchido se `MONITOR_CLAUDE_5H_BUDGET` estiver declarado; sem ele o card mostra
tokens absolutos. Com ele, o til de `~82%` permanece.

### Sinalizacao

`QUOTA_WARN_PCT` 60 (ambar) e `QUOTA_ALERT_PCT` 80 (vermelho), so COR. Piscar foi
descartado de proposito: a cota se esgota em horas e nao ha nada a fazer no instante em
que cruza o limiar — piscar aqui competiria com o `perm`, que e o unico sinal do painel
que exige acao imediata. Dado stale pinta o numero de roxo como o resto do painel:
cota velha engana mais do que a ausencia dela.

## 16. Dois bugs da fase 7, relatados em hardware

### "?" em todas as sessoes: o Orca tomou os hooks do Claude

Sintoma: `work`/`ask`/`perm`/`free` sumiram do painel; todo card virou `?` (o marcador
de dado velho). Nao era regressao do codigo — era o ambiente.

Todos os hooks de `~/.claude/settings.json` tinham sido substituidos por um unico
handler do Orca (`.orca\agent-hooks\claude-hook.cmd`, em `-EncodedCommand`). Do
Monitor.AI so restaram duas entradas antigas apontando para `tools/perm_hook.py`, que
e um wrapper de compatibilidade: ele mapeia qualquer acao que nao seja
`permission_request` para **`free`**. E estava ligado ao `PostToolUse`.

O resultado encadeia:

1. nenhum evento de `work` ou `ask` chegava mais ao daemon;
2. cada tool concluida marcava a sessao como `free`;
3. passados os 90s de `SOURCE_STALE_AFTER_S` sem evento novo, a sessao virava stale;
4. stale substitui o rotulo de estado por `?` — corretamente, alias: o painel preferiu
   dizer "nao sei" a exibir um `free` que nao tinha evidencia.

Em paralelo, `~/.codex/hooks.json` nao existia: o hook do Codex nunca fora instalado,
entao toda sessao do Codex saia com `no_structured_event` e caia no mesmo `?`.

Correcao: rodar `tools/install_hook.py` e `tools/install_codex_hook.py`. O instalador
do Claude faz merge — recolocou os 7 eventos do Monitor.AI **preservando** o grupo do
Orca em cada um, e substituiu as entradas do `perm_hook.py` pelo `session_hook.py`, que
distingue `PostToolUse` (work) de `Stop` (free).

**Licao operacional:** os hooks vivem num arquivo global que outros produtos tambem
editam. Sumir estado no painel deve levantar primeiro a hipotese de hook, nao de
firmware — e vale reconferir depois de instalar qualquer ferramenta que mexa em
`~/.claude/settings.json`.

### Cota do Codex com tres horas de atraso

Sintoma: o painel exibia 37% da janela de 5h e 6% da semanal; o consumo real era 100%
e 16%.

Os numeros nao estavam errados — estavam velhos. O ultimo `rate_limits` gravado no
rollout era das 18:04 UTC e a leitura aconteceu as 21:11 UTC. O rollout so cresce
enquanto o **Codex CLI** roda; consumo feito por outra superficie nao aparece ali. Nao
ha fonte local mais fresca: `.codex-global-state.json` nao tem `used_percent`,
`state_5.sqlite` e `thread_history_1.sqlite` tambem nao, e as 7 linhas de
`logs_2.sqlite` com o campo sao de 25/08.

A guarda `_window_is_current` nao pegou isso, e nao deveria mesmo: ela responde "a
janela ja virou?", e a janela seguia valida (`resets_at` as 18:25 local, no futuro).
A pergunta que faltava era outra — "de quando e essa leitura?". Dentro da MESMA janela
de 5h o percentual anda rapido: 37% -> 100% em tres horas.

Correcao: `codex_quota` passou a devolver `age_s`, a idade da leitura. Acima de
`QUOTA_FRESH_S` (300s = 1,7% da janela de 300 min, erro que cabe no arredondamento) o
card troca a semanal pela idade no rodape (`ha 3h`) e pinta o numero de roxo. O dado
continua sendo o ultimo oficial que existe; ele so para de se passar por atual.

## 17. Rodada de melhorias apos a fase 7

Quatro itens, todos com medicao ou incidente por tras.

### 17.1. A reindexacao de rollouts era O(ids sem rollout)

`codex_meta` tinha este fallback, com um comentario que se enganava sozinho:

```python
path = _cache.get(session_id)
if path is None:
    _cache = _rollout_index()   # "sessao nova: reindexa uma vez"
```

"Uma vez" por CHAMADA, nao por ciclo — e a falha nunca era memorizada. Medido:

```
ids no session_index : 53
rollouts indexados   : 37
ids SEM rollout      : 48        <- cada um refazia o rglob inteiro
custo de 1 _rollout_index: 17,2ms  ->  48 x = 0,83s por ciclo
```

O detalhe que fecha o raciocinio: a secao 14 ja registrava "36 rollouts para 52 ids do
indice" como limitacao de exibicao. Era a mesma coisa vista pelo outro lado — o id
ausente e o caso NORMAL, nao a excecao, e o codigo o tratava como excecao cara.

Correcao: `_rollout_for()` revarre no maximo a cada `REINDEX_MIN_INTERVAL_S` (10s). A
varredura passou a ser do INDICE e nao do id: se ela acabou de rodar, o id continua
ausente e nao ha o que reprocurar. Ciclo quente **1,275s -> 0,544s (-57%)**, com zero
reindexacoes em regime. Sessao nova aparece com metadado em ate 10s, folgadamente
abaixo dos 90s de `SOURCE_STALE_AFTER_S`.

### 17.2. O painel ficava cego sem dizer

O incidente da secao 16 custou uma sessao de diagnostico, e o daemon **ja tinha o
dado**: toda sessao saia com `source_stale: True` e as do Codex com
`diagnostic: "no_structured_event"`. Mas a linha impressa era so contagem de cards e
tokens. Nada denunciava que 100% das sessoes estavam sem evidencia.

Correcao em duas pontas:

* `session_hook.hook_installed(path, agent)` responde se algum grupo do arquivo chama
  `session_hook.py` para aquele agente — mesmo criterio que os instaladores usam para
  reconhecer os proprios grupos, entao o wrapper legado `perm_hook.py` corretamente
  **nao** conta como instalado.
* `hook_warnings(sessions, health)` cruza as duas condicoes. Nao basta o hook faltar
  (sem sessao daquele agente nao ha o que avisar) nem a sessao existir (com hook, o
  silencio e informacao legitima). O aviso e a interseccao — exatamente o caso em que o
  painel exibiria `?` para tudo sem explicar.

O daemon rele a saude a cada ciclo, de proposito: os arquivos sao globais e outra
ferramenta pode reescreve-los com o daemon ja no ar, que foi o que aconteceu. E so
imprime quando o diagnostico MUDA — repetir a cada 5s vira ruido e o operador para de
ler justamente a linha que importa. Fecha com `install_hook.py --check`, para rodar
depois de instalar qualquer coisa que edite `~/.claude/settings.json`.

### 17.3. A guarda de 16 KiB media depois de alocar

```cpp
DeserializationError err = deserializeJson(doc, server.arg("plain"));  // DOM ja alocado
if (server.arg("plain").length() > HTTP_MAX_BODY_BYTES) { ... }        // so agora
```

O limite existe para conter memoria e era conferido depois de gasta-la. Alem disso,
`String arg(const String&) const` (WebServer.h:187) devolve **por valor**: as duas
chamadas faziam duas copias completas do corpo. Agora o teto vem primeiro e o corpo e
lido uma vez so, por referencia const a um temporario.

Ressalva: o WebServer ja bufferiza o corpo antes do handler, entao isto nunca foi vetor
de exaustao remota — era uma guarda que nao cumpria o que prometia, mais duas copias.

### 17.4. `fetch_hidden` removido

23 linhas substituidas por `fetch_id_list`, que atende `/hidden` e `/pinned`. As duas
tinham docstrings divergentes sobre a MESMA decisao de design (por que a lista mora no
device). A hora de apagar e antes de alguem editar a copia errada.

## 18. Contagem de tokens do Claude inflada 2,3x (uma mensagem, varias linhas)

Relatado pelo usuario como "a estimativa do Claude esta errada". Estava — e nao so a
estimativa nova: o card **tokens hoje** e o **heatmap** carregavam o mesmo erro desde
que existem.

### O que acontece no transcript

Uma resposta do assistant nao vira uma linha. Vira uma linha por BLOCO de conteudo —
`thinking`, `text`, um `tool_use` por ferramenta chamada — e **todas repetem o mesmo
objeto `usage`**, porque o `usage` pertence a mensagem, nao ao bloco:

```
18:46:49  msg_011CeTk...  blocos=['thinking']  usage={input:2, output:615, cache_creation:338}
18:46:50  msg_011CeTk...  blocos=['text']      usage={input:2, output:615, cache_creation:338}
18:46:52  msg_011CeTk...  blocos=['tool_use']  usage={input:2, output:615, cache_creation:338}
18:46:53  msg_011CeTk...  blocos=['tool_use']  usage={input:2, output:615, cache_creation:338}
```

`_tokens_of` era chamado por evento e somado direto. Uma resposta com quatro blocos
era cobrada quatro vezes.

### Medicao

```
janela de 5h : 1117 entradas para 522 message.id distintos
               373 ids repetidos, 595 repeticoes
               3.714.894 -> 1.540.194 tokens   (2,41x)
tokens hoje  : 8.486.888 -> 3.706.304          (2,29x)  = 4,8M de tokens fantasma
```

O que fechou o diagnostico: **373 de 373** grupos repetidos tinham `usage` byte a byte
identico E viviam no mesmo arquivo. Isso descarta as hipoteses concorrentes (retry com
cobranca nova, sessao contada em dois projetos) e prova repeticao de serializacao.

### Correcao

`_tokens_of` virou `_usage_of`, devolvendo `(message.id, tokens)`, e a soma passa por
`dedup_tokens(vistos, obj)`. Aplicado nos tres acumuladores que existiam:
`usage_tracker.collect` (card do dia + heatmap), `usage_tracker.session_tokens`
(tokens por sessao na tela de detalhe) e `quota.claude_consumption` (estimativa de 5h).

Dois detalhes que a implementacao precisa respeitar:

* O conjunto de vistos e **global a janela**, nao por arquivo — a mesma mensagem pode
  aparecer em transcripts diferentes, e ha teste para isso.
* Evento **sem** `message.id` e contado sem deduplicar. Nao da para saber se repete, e
  descartar por precaucao subestimaria o consumo real — errar para baixo tambem e
  errar.

O balde do heatmap recebe o token na PRIMEIRA ocorrencia da mensagem, entao a hora
atribuida e a do inicio da resposta.
