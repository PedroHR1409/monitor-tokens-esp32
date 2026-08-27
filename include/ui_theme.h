#pragma once
#include <lvgl.h>
#include "config.h"

// Paleta e layout do Monitor.AI — ver docs/SPEC.md secoes 4 e 6.1.
namespace theme {

// --- Cores por estado ---
// Hierarquia de urgencia: so 'perm' e realmente chamativo (fundo tingido + borda),
// porque e o unico que bloqueia o agente esperando voce. 'ask' avisa sem gritar.
constexpr uint32_t COLOR_WORK  = 0x22C55E; // verde  — processando
constexpr uint32_t COLOR_ASK   = 0x3B82F6; // azul   — perguntou algo
constexpr uint32_t COLOR_PERM  = 0xF59E0B; // ambar  — travado esperando autorizacao
constexpr uint32_t COLOR_FREE  = 0x6B7280; // cinza  — livre
constexpr uint32_t COLOR_IDLE  = 0x2A2E38; // slot vazio
constexpr uint32_t COLOR_ERROR = 0xEF4444;
constexpr uint32_t COLOR_STALE = 0x7C3AED; // roxo   — dado velho, daemon nao responde

// Fundo tingido do card em 'perm' (mistura discreta do ambar com o fundo do card).
constexpr uint32_t COLOR_PERM_BG = 0x3A2E18;

// --- Marca ---
constexpr uint32_t COLOR_ACCENT = 0x60A5FA;  // ".AI" do titulo

// --- Fundo geral ---
constexpr uint32_t COLOR_BG          = 0x0D0F14;
constexpr uint32_t COLOR_CARD_BG     = 0x1C1F26;
constexpr uint32_t COLOR_CARD_BORDER = 0x2A2E38;
constexpr uint32_t COLOR_DIVIDER     = 0x22252C;
constexpr uint32_t COLOR_TEXT        = 0xF3F4F6;
constexpr uint32_t COLOR_TEXT_DIM    = 0x9CA3AF;
constexpr uint32_t COLOR_TEXT_FAINT  = 0x6B7280;

// =====================================================================================
// LAYOUT (portrait 320x480, sem rodape — o status virou um ponto no header)
//
//   +--------------------------------------+  0
//   |  Monitor.AI          12:34      o    |  header 34px
//   +------------+------------+------------+  42
//   |  sessao 1  |  sessao 2  |  sessao 3  |  96x96
//   +------------+------------+------------+  146
//   |  sessao 4  |  sessao 5  |  sessao 6  |
//   +------------+------------+------------+  250
//   |   tokens   | cota CODEX | cota CLAUDE|  3 x 96x96
//   +------------+------------+------------+  354
//   |        SPARKLINE 12h (304x118)       |
//   +--------------------------------------+  472 (+8 margem)
// =====================================================================================
constexpr int16_t HEADER_H    = 34;
constexpr int16_t MARGIN      = 8;
constexpr int16_t GUTTER      = 8;
constexpr int16_t GRID_COLS   = 3;
constexpr int16_t CARD_RADIUS = 12;
constexpr int16_t ICON_SIZE   = 40;   // bate com os PNGs gerados em src/icons/*.c

constexpr int SESSION_CARDS = MAX_SESSIONS;   // 6 cards de sessao (linhas 0 e 1)

constexpr int16_t CELL = (SCREEN_W - 2 * MARGIN - (GRID_COLS - 1) * GUTTER) / GRID_COLS; // 96
constexpr int16_t ROW_STEP = CELL + GUTTER;
constexpr int16_t GRID_TOP = HEADER_H + MARGIN;

constexpr int16_t ROW2_Y    = GRID_TOP + 2 * ROW_STEP;                 // tokens + as duas cotas
// A faixa que era do Pomodoro virou DOIS cards de 96px em vez de um largo: a cota do
// Codex e oficial e a do Claude e estimada, e separar fisicamente carrega essa
// diferenca melhor do que um rotulo miudo dentro de um card unico. Ver SPEC secao 15.
constexpr int16_t QUOTA_CX_X = MARGIN + 1 * (CELL + GUTTER);
constexpr int16_t QUOTA_CL_X = MARGIN + 2 * (CELL + GUTTER);
constexpr int16_t SPARK_Y   = GRID_TOP + 3 * ROW_STEP;
constexpr int16_t SPARK_W   = GRID_COLS * CELL + (GRID_COLS - 1) * GUTTER;  // 304
constexpr int16_t SPARK_H   = SCREEN_H - MARGIN - SPARK_Y;

// --- Heatmap de 12 horas (card inferior, 304x118) ---
// Sem titulo: o espaco foi para os rotulos de hora e de tokens. Medido: com pad 6 e
// gap 2 sobram 22px por celula, onde "2.7" em montserrat_12 (21px) cabe.
constexpr int16_t HM_PAD     = 6;
constexpr int16_t HM_GAP     = 2;
constexpr int16_t HM_VALUE_Y = 4;    // rotulo de tokens (acima)
constexpr int16_t HM_CELL_Y  = 22;   // bloco de intensidade
constexpr int16_t HM_CELL_H  = 46;
constexpr int16_t HM_HOUR_Y  = 72;   // rotulo de hora (abaixo)
// Piso de opacidade: com pico 10x o menor valor, escala linear pura sumiria com as
// horas de pouco uso.
constexpr uint32_t HM_MIN_OPA = 70;

// --- Alerta visual quando algo depende de voce (perm/ask) ---
constexpr uint32_t ALERT_PERIOD_MS = 600;
constexpr int16_t  ALERT_BORDER_W  = 4;

// --- Contexto quase cheio ---
// A 80% da janela o card pisca em vermelho ate a sessao ser aliviada. Periodo maior que
// o BLINK_PERIOD_MS de transicao de proposito: sao dois sinais diferentes e precisam ser
// distinguiveis de relance. A borda tambem engrossa, para funcionar de canto de olho.
constexpr uint16_t CTX_ALERT_PCT        = 80;
constexpr uint32_t CTX_BLINK_PERIOD_MS  = 500;
constexpr uint32_t COLOR_CTX_ALERT      = 0xEF4444;  // vermelho
constexpr uint32_t COLOR_CTX_ALERT_BG   = 0x4A1D1D;  // fundo tingido de vermelho

// --- Cota quase no teto ---
// So COR, sem piscar: a cota se esgota em horas, nao em segundos, e nao ha nada a
// fazer no instante em que ela cruza o limiar. Piscar aqui competiria com o `perm`,
// que e o unico sinal do painel que exige acao imediata.
constexpr uint16_t QUOTA_WARN_PCT  = 60;
constexpr uint16_t QUOTA_ALERT_PCT = 80;

// Ate quando uma leitura de cota do Codex pode ser apresentada como "agora".
// 5 min sao 1,7% da janela de 300 min — o erro maximo cabe no arredondamento. Passou
// disso, o card mostra a idade no lugar da semanal e pinta o numero de roxo: o dado
// continua sendo o ultimo oficial, mas deixa de se passar por atual.
constexpr uint32_t QUOTA_FRESH_S = 300;

// --- Feedback de transicao ---
constexpr uint32_t BLINK_MS       = 1200;   // card pisca ao mudar de estado
constexpr uint32_t BLINK_PERIOD_MS = 300;

// --- Formatacao de tempo: uma unidade so (5s, 32s, 2m, 14m, 1h) ---
constexpr uint32_t ELAPSED_MIN_THRESHOLD_S  = 60;
constexpr uint32_t ELAPSED_HOUR_THRESHOLD_S = 3600;

inline lv_color_t color(uint32_t hex) { return lv_color_hex(hex); }

} // namespace theme
