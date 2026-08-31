#include "ui_dashboard.h"
#include "session_manager.h"
#include "session_transport.h"
#include "device_time.h"
#include "ui_theme.h"
#include "config.h"
#include "icons.h"
#include "touch_driver.h"
#include "id_list.h"
#include <lvgl.h>
#include <stdio.h>
#include <string.h>

// IMPORTANTE: nenhuma string exibida na tela pode ter caractere nao-ASCII. A fonte
// compilada nao tem esses glyphs e eles viram um quadrado ("tofu") no painel — ver
// docs/SPEC.md secao 8. Comentarios podem ter acento; textos de tela, nao.
//
// PERFORMANCE: todo lv_label_set_text/set_style invalida a tela, e o modo de render e
// FULL (frame inteiro de 307KB por QSPI). Antes isso acontecia ~49x por segundo
// incondicionalmente, o que atrasava o loop e fazia o contador de tempo andar devagar.
// Aqui toda escrita passa por um guard que compara com o ultimo valor: em regime, um
// segundo tipico so redesenha os poucos textos que realmente mudaram.

namespace {

// ---------------------------------------------------------------- helpers de escrita

// Só escreve (e invalida a tela) se o texto realmente mudou.
void set_text_if(lv_obj_t *label, char *cache, size_t cacheLen, const char *value) {
    if (!strncmp(cache, value, cacheLen - 1)) return;
    strncpy(cache, value, cacheLen - 1);
    cache[cacheLen - 1] = '\0';
    lv_label_set_text(label, value);
}

void set_color_if(lv_obj_t *obj, uint32_t &cache, uint32_t hex,
                  void (*setter)(lv_obj_t *, lv_color_t, lv_style_selector_t)) {
    if (cache == hex) return;
    cache = hex;
    setter(obj, theme::color(hex), 0);
}

void set_flag_if(lv_obj_t *obj, bool &cache, bool hidden) {
    if (cache == hidden) return;
    cache = hidden;
    if (hidden) lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
    else        lv_obj_clear_flag(obj, LV_OBJ_FLAG_HIDDEN);
}

// ---------------------------------------------------------------- estado/cor/texto

uint32_t color_for_state(SessionState s) {
    switch (s) {
        case SessionState::WORK: return theme::COLOR_WORK;
        case SessionState::ASK:  return theme::COLOR_ASK;
        case SessionState::PERM: return theme::COLOR_PERM;
        case SessionState::FREE: return theme::COLOR_FREE;
        case SessionState::ERROR_STATE: return theme::COLOR_ERROR;
        default: return theme::COLOR_IDLE;
    }
}

const char *label_for_state(SessionState s) {
    switch (s) {
        case SessionState::WORK: return "work";
        case SessionState::ASK:  return "ask";
        case SessionState::PERM: return "perm";
        case SessionState::FREE: return "free";
        case SessionState::ERROR_STATE: return "erro";
        default: return "";
    }
}

// O provider (zai, deepseek...) vence quando presente; sem provider, o icone e o
// classico da ferramenta. OpenCode sem provider conhecido usa o GPT como generico.
const lv_image_dsc_t *icon_for_provider(const char *provider, ToolType t) {
    if (provider && provider[0]) {
        if (!strcmp(provider, "zai"))      return &zai_icon;
        if (!strcmp(provider, "deepseek")) return &deepseek_icon;
    }
    switch (t) {
        case ToolType::CLAUDE:   return &claude_icon;
        case ToolType::OPENCODE: return &gpt_icon;
        default:                 return &gpt_icon;
    }
}

// Uma unidade so: 5s, 32s, 2m, 14m, 1h.
void format_elapsed(uint32_t sec, char *buf, size_t len) {
    if (sec < theme::ELAPSED_MIN_THRESHOLD_S)       snprintf(buf, len, "%lus", (unsigned long)sec);
    else if (sec < theme::ELAPSED_HOUR_THRESHOLD_S) snprintf(buf, len, "%lum", (unsigned long)(sec / 60));
    else                                            snprintf(buf, len, "%luh", (unsigned long)(sec / 3600));
}

// 8757403 -> "8.7M" (o card tem 96px; o numero cru nao cabe)
void format_tokens(uint32_t n, char *buf, size_t len) {
    if (n >= 1000000UL)   snprintf(buf, len, "%lu.%luM", (unsigned long)(n / 1000000UL),
                                                          (unsigned long)((n / 100000UL) % 10));
    else if (n >= 1000UL) snprintf(buf, len, "%luk", (unsigned long)(n / 1000UL));
    else                  snprintf(buf, len, "%lu", (unsigned long)n);
}

// ---------------------------------------------------------------- widgets

struct CardWidgets {
    lv_obj_t *container;
    lv_obj_t *timeLabel;      // topo-esquerda: tempo no estado
    lv_obj_t *statusLabel;    // topo-direita: work/ask/perm/free (info de acao)
    lv_obj_t *icon;
    lv_obj_t *nameLabel;      // rodape, centralizado, corta por largura

    char  cTime[12], cStatus[10], cName[24];
    uint32_t cBorder, cBg, cStatusColor;
    bool  cHidden;
    const lv_image_dsc_t *cIcon;
    bool  cIconDim;

    SessionState prevState;
    bool         hadSession;
    uint32_t     blinkUntil;   // pisca ao trocar de estado
    bool         blinkOn;
};

CardWidgets cards[theme::SESSION_CARDS];

// Indices estaveis para o user_data dos eventos. Passar &s_cardIndex[i] em vez de
// (void*)(intptr_t)i e deliberado: o cast de inteiro para ponteiro aceita qualquer
// simbolo que exista, e foi exatamente assim que a funcao index() do POSIX entrou no
// lugar do indice do card sem o compilador reclamar. Com indexacao de array, um nome
// errado vira erro de compilacao.
int s_cardIndex[theme::SESSION_CARDS];
char g_cardRenderedId[theme::SESSION_CARDS][SESSION_ID_LEN] = {{0}};

lv_obj_t *g_headerDot = nullptr;
lv_obj_t *g_clockLabel = nullptr;
uint32_t  g_cHeaderDot = 0;
char      g_cClock[8] = "";

// card de tokens
// Widget unificado de consumo: substitui os cards de tokens/cota e a faixa 12h.
// Duas visoes alternadas por toque; a escolha e do OPERADOR, nao do daemon, e
// sobrevive ao refresh (mesma regra do antigo card rotativo).
lv_obj_t *g_uwCard = nullptr;
lv_obj_t *g_uwHeatmap = nullptr, *g_uwPodio = nullptr;
lv_obj_t *g_uwCell[USAGE_DAYS] = {nullptr};
uint32_t g_cUwCell[USAGE_DAYS] = {0};
bool g_uwHeatOn = true, g_uwPodioOn = false;
uint8_t g_uwView = 0;              // 0 = heatmap, 1 = podio (Escopo B)
bool g_uwBuilt = false;            // grade criada 1x; refresh so troca cores
lv_obj_t *g_uwArrow = nullptr;     // faixa da seta: unica via heatmap <-> podio
lv_obj_t *g_uwArrowLbl = nullptr;
char g_cUwArrow[4] = "";
// Modo inspecao: -1 = repouso; 0..29 = dia tocado (barra full-width).
int8_t g_uwInspectDay = -1;
lv_obj_t *g_uwInspect = nullptr, *g_uwInspectL1 = nullptr, *g_uwInspectL2 = nullptr;
char g_cUwInspect1[40] = "", g_cUwInspect2[40] = "";
int16_t g_cUwY0 = -1;              // ultimo offset vertical aplicado (evita realinhar)

// Podio: 3 barras rankeadas pelo total do periodo; chip cicla hoje/7d/30d; tocar
// numa barra abre o modal com as sessoes do provider (top 6 do payload).
lv_obj_t *g_uwChip = nullptr;
lv_obj_t *g_uwBar[3] = {nullptr};
lv_obj_t *g_uwBarName[3] = {nullptr};
lv_obj_t *g_uwBarValue[3] = {nullptr};
char g_cUwChip[6] = "";
char g_cUwBarName[3][12] = {{0}};
char g_cUwBarValue[3][8] = {{0}};
uint8_t g_uwPeriod = 0;            // 0 = hoje, 1 = 7d, 2 = 30d
int8_t g_uwOrder[3] = {0, 1, 2};   // provider idx em ordem de rank

// Modal de drill-down (reaproveita o padrao do seletor de sessoes).
lv_obj_t *g_uwModal = nullptr, *g_uwModalTitle = nullptr;
lv_obj_t *g_uwModalName[TOP_SESSIONS] = {nullptr};
lv_obj_t *g_uwModalTok[TOP_SESSIONS] = {nullptr};
char g_cUwModalTitle[24] = "";
char g_cUwModalName[TOP_SESSIONS][28] = {{0}};
char g_cUwModalTok[TOP_SESSIONS][8] = {{0}};
int8_t g_uwModalProvider = -1;

// --- Tela de detalhe (toque curto num card) ---
// Padrao minimo: cobre a tela inteira, mostra o que nao cabe no card de 96px (nome
// completo, branch, modelo) e fecha com qualquer toque.
lv_obj_t *g_detail = nullptr;
lv_obj_t *g_dtIcon = nullptr, *g_dtName = nullptr, *g_dtState = nullptr,
         *g_dtBranch = nullptr, *g_dtModel = nullptr, *g_dtTool = nullptr,
         *g_dtElapsed = nullptr, *g_dtEffort = nullptr, *g_dtTokens = nullptr,
         *g_dtTokensCap = nullptr, *g_dtCtx = nullptr;
char g_detailId[SESSION_ID_LEN] = "";

// --- Seletor (toque num card VAZIO) ---
// Lista as sessoes que existem no PC mas nao estao no board; tocar numa delas fixa a
// sessao, e o daemon passa a envia-la mesmo fora da janela de 4h.
lv_obj_t *g_picker = nullptr;
lv_obj_t *g_pickerList = nullptr;
lv_obj_t *g_pickerEmpty = nullptr;
int g_pickerSlot[CATALOG_MAX];
char g_pickerRenderedId[CATALOG_MAX][SESSION_ID_LEN] = {{0}};

// --- Alerta visual quando algo depende de voce ---
// Pulsa a borda da TELA (nao um objeto sobreposto): overlay cobrindo tudo interceptaria
// o touch e mataria os gestos dos cards.
bool     g_alertOn = false;
uint32_t g_cScreenBorder = 0;

// Definidos mais abaixo (precisam de show_detail, que depende dos widgets do detalhe),
// mas usados ja em build_session_card.
void card_event_cb(lv_event_t *e);
void update_usage_widget();
void usage_widget_toggle_cb(lv_event_t *e);
void usage_widget_chip_cb(lv_event_t *e);
void usage_widget_bar_cb(lv_event_t *e);
void usage_card_cb(lv_event_t *e);
void usage_arrow_cb(lv_event_t *e);
void usage_exit_inspection();
void usage_cell_cb(lv_event_t *e);
void layout_usage_podio();
void render_usage_podio();
void usage_modal_close_cb(lv_event_t *e);
static const char *usage_period_label();
void picker_open();
void picker_close_cb(lv_event_t *e);
void picker_pick_cb(lv_event_t *e);
void detail_close_cb(lv_event_t *e);
void show_detail(int idx);
void render_detail(const SessionData &s);

int find_session_by_id(const char *id) {
    if (!id || !id[0]) return -1;
    for (int i = 0; i < theme::SESSION_CARDS; i++) {
        if (sessions[i].occupied && !strcmp(sessions[i].id, id)) return i;
    }
    return -1;
}

// ---------------------------------------------------------------- construcao

lv_obj_t *make_card(lv_obj_t *parent, int16_t x, int16_t y, int16_t w, int16_t h) {
    lv_obj_t *c = lv_obj_create(parent);
    lv_obj_remove_style_all(c);
    lv_obj_set_size(c, w, h);
    lv_obj_set_pos(c, x, y);
    lv_obj_set_style_bg_color(c, theme::color(theme::COLOR_CARD_BG), 0);
    lv_obj_set_style_bg_opa(c, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(c, theme::color(theme::COLOR_CARD_BORDER), 0);
    lv_obj_set_style_border_width(c, 1, 0);
    lv_obj_set_style_radius(c, theme::CARD_RADIUS, 0);
    lv_obj_set_style_pad_all(c, 6, 0);
    lv_obj_clear_flag(c, LV_OBJ_FLAG_SCROLLABLE);
    return c;
}

lv_obj_t *make_label(lv_obj_t *parent, const lv_font_t *font, uint32_t color) {
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, theme::color(color), 0);
    // O LVGL cria o label com o texto padrao "Text". Os caches de set_text_if() comecam
    // vazios, entao uma primeira escrita de string vazia seria descartada pelo guard
    // "valor igual" e o "Text" ficaria visivel na tela. Zerar aqui elimina a classe
    // inteira desse bug, nao so o caso que apareceu no heatmap.
    lv_label_set_text(l, "");
    return l;
}

void build_header(lv_obj_t *parent) {
    lv_obj_t *h = lv_obj_create(parent);
    lv_obj_remove_style_all(h);
    lv_obj_set_size(h, SCREEN_W, theme::HEADER_H);
    lv_obj_set_pos(h, 0, 0);
    lv_obj_set_style_bg_color(h, theme::color(theme::COLOR_BG), 0);
    lv_obj_set_style_bg_opa(h, LV_OPA_COVER, 0);

    lv_obj_t *brand = make_label(h, &lv_font_montserrat_20, theme::COLOR_TEXT);
    lv_label_set_text(brand, "Monitor");
    lv_obj_align(brand, LV_ALIGN_LEFT_MID, theme::MARGIN, 0);

    lv_obj_t *ai = make_label(h, &lv_font_montserrat_20, theme::COLOR_ACCENT);
    lv_label_set_text(ai, ".AI");
    lv_obj_align_to(ai, brand, LV_ALIGN_OUT_RIGHT_MID, 0, 0);

    // Relogio (NTP). O rodape antigo gastava uma faixa inteira so para dizer "ao vivo";
    // virou este ponto discreto e liberou espaco para o sparkline.
    g_clockLabel = make_label(h, &lv_font_montserrat_16, theme::COLOR_TEXT_DIM);
    lv_label_set_text(g_clockLabel, "--:--");
    lv_obj_align(g_clockLabel, LV_ALIGN_RIGHT_MID, -theme::MARGIN - 16, 0);

    g_headerDot = lv_obj_create(h);
    lv_obj_remove_style_all(g_headerDot);
    lv_obj_set_size(g_headerDot, 9, 9);
    lv_obj_set_style_radius(g_headerDot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(g_headerDot, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(g_headerDot, theme::color(theme::COLOR_FREE), 0);
    lv_obj_align(g_headerDot, LV_ALIGN_RIGHT_MID, -theme::MARGIN, 0);

    lv_obj_t *div = lv_obj_create(parent);
    lv_obj_remove_style_all(div);
    lv_obj_set_size(div, SCREEN_W, 1);
    lv_obj_set_pos(div, 0, theme::HEADER_H - 1);
    lv_obj_set_style_bg_color(div, theme::color(theme::COLOR_DIVIDER), 0);
    lv_obj_set_style_bg_opa(div, LV_OPA_COVER, 0);
}

void build_session_card(lv_obj_t *parent, int i, int16_t x, int16_t y) {
    CardWidgets &c = cards[i];
    memset(c.cTime, 0, sizeof(c.cTime));
    memset(c.cStatus, 0, sizeof(c.cStatus));
    memset(c.cName, 0, sizeof(c.cName));
    c.cBorder = c.cBg = c.cStatusColor = 0xFFFFFFFF;
    c.cHidden = false;
    c.cIcon = nullptr;
    c.cIconDim = false;
    c.prevState = SessionState::IDLE;
    c.hadSession = false;
    c.blinkUntil = 0;
    c.blinkOn = false;

    c.container = make_card(parent, x, y, theme::CELL, theme::CELL);
    lv_obj_add_flag(c.container, LV_OBJ_FLAG_CLICKABLE);
    s_cardIndex[i] = i;
    lv_obj_add_event_cb(c.container, card_event_cb, LV_EVENT_SHORT_CLICKED, &s_cardIndex[i]);
    lv_obj_add_event_cb(c.container, card_event_cb, LV_EVENT_LONG_PRESSED, &s_cardIndex[i]);

    // Hierarquia: o STATUS e a informacao de acao, entao vai em fonte maior e colorida.
    // O tempo e contexto e fica menor/apagado.
    c.timeLabel = make_label(c.container, &lv_font_montserrat_14, theme::COLOR_TEXT_FAINT);
    lv_obj_align(c.timeLabel, LV_ALIGN_TOP_LEFT, 0, 0);

    c.statusLabel = make_label(c.container, &lv_font_montserrat_16, theme::COLOR_FREE);
    lv_obj_align(c.statusLabel, LV_ALIGN_TOP_RIGHT, 0, -1);

    c.icon = lv_image_create(c.container);
    lv_obj_align(c.icon, LV_ALIGN_TOP_MID, 0, 22);

    c.nameLabel = make_label(c.container, &lv_font_montserrat_14, theme::COLOR_TEXT);
    lv_obj_set_style_text_align(c.nameLabel, LV_TEXT_ALIGN_CENTER, 0);
    // O valor ja chega cortado em NAME_LIMIT; CLIP garante uma linha unica mesmo num
    // caso extremo de fonte larga, sem nunca quebrar linha nem crescer o card.
    lv_label_set_long_mode(c.nameLabel, LV_LABEL_LONG_MODE_CLIP);
    lv_obj_set_width(c.nameLabel, theme::CELL - 12);
    lv_obj_align(c.nameLabel, LV_ALIGN_BOTTOM_MID, 0, 0);
}

void detail_close_cb(lv_event_t *) {
    lv_obj_add_flag(g_detail, LV_OBJ_FLAG_HIDDEN);
    g_detailId[0] = '\0';
}

void card_event_cb(lv_event_t *e) {
    const int *slot = (const int *)lv_event_get_user_data(e);
    if (!slot) return;
    const int idx = *slot;
    if (idx < 0 || idx >= theme::SESSION_CARDS) return;
    const bool isLong = (lv_event_get_code(e) == LV_EVENT_LONG_PRESSED);
    const char *selectedId = g_cardRenderedId[idx];
    const int liveIdx = find_session_by_id(selectedId);

    // Registra ANTES de decidir ignorar: assim o /diag distingue "o evento nem chegou
    // ao card" de "chegou, mas o card estava vazio".
    touch_note_card(idx, isLong, liveIdx < 0);
    if (!selectedId[0]) {
        // Card vazio: em vez de ser inerte, oferece escolher qual sessao colocar ali.
        if (!isLong) picker_open();
        return;
    }
    // O card mudou desde o ultimo frame: falha seguro em vez de agir no novo ocupante.
    if (liveIdx < 0) return;

    if (isLong) {
        // Esconde a sessao. O daemon le GET /hidden no proximo ciclo e para de envia-la,
        // liberando o card para a proxima da fila.
        hiddenList.add(selectedId);
        sessions[liveIdx].occupied = false;
    } else {
        show_detail(liveIdx);
    }
}

// ---------------------------------------------------------------- widget unificado

// Nivel de intensidade do dia, relativo ao pico da janela (mesma leitura do GitHub
// em qualquer escala: 50k ou 5M de pico produzem o mesmo degrau de cor).
uint32_t heatmap_color(uint32_t tokens, uint32_t peak) {
    if (tokens == 0 || peak == 0) return theme::HM_EMPTY;
    const uint32_t pct = tokens * 100UL / peak;
    if (pct > 75) return theme::HM_L4;
    if (pct > 50) return theme::HM_L3;
    if (pct > 25) return theme::HM_L2;
    return theme::HM_L1;
}

// Grid estilo GitHub: colunas = semanas, linhas = dias da semana (domingo no topo),
// 30 dias terminando hoje. Sem rotulos - exigencia do usuario; o formato ja le.
// Celulas criadas 1x; o refresh apenas recolore (e realinha so quando o mes vira).
constexpr int16_t UW_H = SCREEN_H - theme::MARGIN - theme::ROW2_Y;
constexpr int16_t UW_TITLE_H = 20;                       // linha do titulo
constexpr int16_t UW_GRID_W = theme::SPARK_W - 28;       // grade = card - faixa da seta
constexpr int16_t UW_CSX = 36, UW_CSY = 29;              // celulas com gap 2 (pitch 38x31)
constexpr int16_t UW_Y0 = UW_TITLE_H + 2;                // topo da grade

// Escurece 75% (mantem 25% do brilho por canal) — modo inspecao, sem overlay.
uint32_t uw_dim(uint32_t hex) {
    const uint32_t r = ((hex >> 16) & 0xFF) / 4;
    const uint32_t g = ((hex >> 8) & 0xFF) / 4;
    const uint32_t b = (hex & 0xFF) / 4;
    return (r << 16) | (g << 8) | b;
}

const char *uw_weekday_full(int wday) {
    static const char *NAMES[7] = {"Domingo", "Segunda-feira", "Terca-feira",
                                   "Quarta-feira", "Quinta-feira", "Sexta-feira",
                                   "Sabado"};
    return NAMES[wday % 7];
}

void uw_tokens_str(uint32_t v, char *buf, size_t len) {
    // Sempre em MM, 1 casa decimal, virgula pt-BR, SEM sufixo (unidade no titulo).
    snprintf(buf, len, "%lu,%lu", v / 1000000UL, (v % 1000000UL) / 100000UL);
}

void build_usage_widget(lv_obj_t *parent) {
    g_uwCard = make_card(parent, theme::MARGIN, theme::ROW2_Y,
                         theme::SPARK_W, UW_H);
    // Fundo mais escuro que o padrao dos cards: a celula vazia (#161B22, paleta
    // GitHub) precisa contrastar para o "dia sem uso" nao sumir no card.
    lv_obj_set_style_bg_color(g_uwCard, theme::color(theme::COLOR_BG), 0);
    // Toque no card (vaos/titulo) SAI da inspecao; em repouso nao faz nada.
    // O long-press foi REMOVIDO: o podio agora e acionado so pela seta lateral.
    lv_obj_add_flag(g_uwCard, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(g_uwCard, usage_card_cb, LV_EVENT_SHORT_CLICKED, nullptr);

    // Titulo permanente do card (linha propria de ~20px).
    lv_obj_t *title = make_label(g_uwCard, &lv_font_montserrat_12, theme::COLOR_TEXT_FAINT);
    lv_label_set_text(title, "CONSUMO DE TOKENS (EM MM)");
    lv_obj_align(title, LV_ALIGN_TOP_LEFT, 8, 3);

    g_uwHeatmap = lv_obj_create(g_uwCard);
    lv_obj_remove_style_all(g_uwHeatmap);
    lv_obj_set_size(g_uwHeatmap, theme::SPARK_W, UW_H);
    // lv_obj nasce CLICKABLE mesmo sem estilo: sem isto, o container engole o toque
    // e o toggle do card nunca dispara (diagnosticado via /diag, usage_cell_click).
    lv_obj_clear_flag(g_uwHeatmap, LV_OBJ_FLAG_CLICKABLE);

    // Grade HORIZONTAL com o GAP FINO do GitHub (2px): celulas 37x32, pitch 39x34.
    // Abaixo da linha do titulo. Clicavel de proposito: abre a inspecao do dia.
    constexpr int16_t CSX = 37, CSY = 32, GAP = 2;
    for (int d = 0; d < USAGE_DAYS; d++) {
        g_uwCell[d] = lv_obj_create(g_uwHeatmap);
        lv_obj_remove_style_all(g_uwCell[d]);
        lv_obj_set_size(g_uwCell[d], CSX, CSY);
        lv_obj_set_style_bg_color(g_uwCell[d], theme::color(theme::HM_EMPTY), 0);
        lv_obj_set_style_bg_opa(g_uwCell[d], LV_OPA_COVER, 0);
        lv_obj_add_flag(g_uwCell[d], LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(g_uwCell[d], usage_cell_cb, LV_EVENT_SHORT_CLICKED,
                            (void *)(intptr_t)d);
    }

    // Barra de inspecao: dia tocado esticado para a LARGURA TODA da grade, criada
    // 1x e oculta. Toque nela sai do modo inspecao (mesma regra do card).
    g_uwInspect = lv_obj_create(g_uwHeatmap);
    lv_obj_remove_style_all(g_uwInspect);
    lv_obj_set_size(g_uwInspect, UW_GRID_W, 56);
    lv_obj_set_style_radius(g_uwInspect, 6, 0);
    lv_obj_set_style_bg_color(g_uwInspect, theme::color(theme::COLOR_BG), 0);
    lv_obj_set_style_bg_opa(g_uwInspect, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(g_uwInspect, 2, 0);
    lv_obj_set_style_border_color(g_uwInspect, theme::color(theme::COLOR_TEXT), 0);
    lv_obj_add_flag(g_uwInspect, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(g_uwInspect, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_event_cb(g_uwInspect, usage_card_cb, LV_EVENT_SHORT_CLICKED, nullptr);

    g_uwInspectL1 = make_label(g_uwInspect, &lv_font_montserrat_14, theme::COLOR_TEXT);
    lv_obj_set_width(g_uwInspectL1, UW_GRID_W - 12);
    lv_obj_set_style_text_align(g_uwInspectL1, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(g_uwInspectL1, LV_ALIGN_TOP_MID, 0, 7);
    g_uwInspectL2 = make_label(g_uwInspect, &lv_font_montserrat_12, theme::COLOR_TEXT_DIM);
    lv_obj_set_width(g_uwInspectL2, UW_GRID_W - 12);
    lv_obj_set_style_text_align(g_uwInspectL2, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(g_uwInspectL2, LV_ALIGN_BOTTOM_MID, 0, -6);

    // Faixa da seta: UNICA via heatmap <-> podio. Container clicavel 28px com o
    // simbolo CENTRALIZADO pelo LVGL (lv_obj_center) — centralizacao garantida.
    g_uwArrow = lv_obj_create(g_uwCard);
    lv_obj_remove_style_all(g_uwArrow);
    lv_obj_set_size(g_uwArrow, 28, UW_H - UW_TITLE_H);
    lv_obj_align(g_uwArrow, LV_ALIGN_TOP_RIGHT, 0, UW_TITLE_H);
    lv_obj_clear_flag(g_uwArrow, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(g_uwArrow, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(g_uwArrow, usage_arrow_cb, LV_EVENT_SHORT_CLICKED, nullptr);

    g_uwArrowLbl = make_label(g_uwArrow, &lv_font_montserrat_16, theme::COLOR_TEXT_DIM);
    lv_label_set_text(g_uwArrowLbl, LV_SYMBOL_RIGHT);
    lv_obj_center(g_uwArrowLbl);

    // --- Visao 2: podio + chip de periodo (Escopo B) ---
    g_uwPodio = lv_obj_create(g_uwCard);
    lv_obj_remove_style_all(g_uwPodio);
    lv_obj_set_size(g_uwPodio, theme::SPARK_W, UW_H);
    lv_obj_clear_flag(g_uwPodio, LV_OBJ_FLAG_CLICKABLE);

    // Chip: pequeno, canto superior direito, tap cicla o periodo. Clicavel nele
    // mesmo: toque no chip NAO alterna a visao (prioridade chip > barra > visao).
    g_uwChip = make_label(g_uwPodio, &lv_font_montserrat_12, theme::COLOR_STALE);
    lv_label_set_text(g_uwChip, "hoje");
    lv_obj_align(g_uwChip, LV_ALIGN_TOP_RIGHT, -34, 4);   // dentro do card, ao lado da seta
    lv_obj_add_flag(g_uwChip, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(g_uwChip, usage_widget_chip_cb, LV_EVENT_SHORT_CLICKED, nullptr);

    // Podio em COLUNAS: 2o (esq) | 1o (centro) | 3o (dir). Barra vertical com
    // altura por rank; icone + valor acima; nome abaixo. Criados como filhos do
    // podio (NAO da barra): a barra muda de altura, o header/nome ficam fixos.
    constexpr int16_t PB_W = 72, PB_H = 88;
    for (int i = 0; i < 3; i++) {
        lv_obj_t *bar = lv_obj_create(g_uwPodio);
        lv_obj_remove_style_all(bar);
        lv_obj_set_size(bar, PB_W, PB_H);
        lv_obj_set_style_radius(bar, 6, 0);
        lv_obj_set_style_bg_color(bar, theme::color(theme::COLOR_CARD_BG), 0);
        lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(bar, 1, 0);
        lv_obj_set_style_border_color(bar, theme::color(theme::COLOR_CARD_BORDER), 0);
        lv_obj_add_flag(bar, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(bar, usage_widget_bar_cb, LV_EVENT_SHORT_CLICKED,
                            (void *)(intptr_t)i);
        g_uwBar[i] = bar;


        g_uwBarValue[i] = make_label(g_uwPodio, &lv_font_montserrat_14, theme::COLOR_TEXT);
        lv_obj_set_width(g_uwBarValue[i], 72);
        lv_obj_set_style_text_align(g_uwBarValue[i], LV_TEXT_ALIGN_CENTER, 0);

        g_uwBarName[i] = make_label(g_uwPodio, &lv_font_montserrat_12, theme::COLOR_TEXT_DIM);
        lv_obj_set_width(g_uwBarName[i], PB_W);
        lv_obj_set_style_text_align(g_uwBarName[i], LV_TEXT_ALIGN_CENTER, 0);
    }
    layout_usage_podio();

    // --- Modal de drill-down: padrao do seletor de sessoes (backdrop + linhas) ---
    g_uwModal = lv_obj_create(parent);
    lv_obj_remove_style_all(g_uwModal);
    lv_obj_set_size(g_uwModal, SCREEN_W, SCREEN_H);
    lv_obj_set_pos(g_uwModal, 0, 0);
    lv_obj_set_style_bg_color(g_uwModal, theme::color(theme::COLOR_BG), 0);
    lv_obj_set_style_bg_opa(g_uwModal, LV_OPA_90, 0);
    lv_obj_add_flag(g_uwModal, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(g_uwModal, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_event_cb(g_uwModal, usage_modal_close_cb, LV_EVENT_SHORT_CLICKED, nullptr);

    g_uwModalTitle = make_label(g_uwModal, &lv_font_montserrat_14, theme::COLOR_TEXT);
    lv_obj_align(g_uwModalTitle, LV_ALIGN_TOP_MID, 0, 24);

    for (int i = 0; i < TOP_SESSIONS; i++) {
        g_uwModalName[i] = make_label(g_uwModal, &lv_font_montserrat_14, theme::COLOR_TEXT);
        lv_obj_set_width(g_uwModalName[i], SCREEN_W - 120);
        lv_label_set_long_mode(g_uwModalName[i], LV_LABEL_LONG_MODE_DOTS);
        lv_obj_align(g_uwModalName[i], LV_ALIGN_TOP_LEFT, 16, 60 + i * 32);

        g_uwModalTok[i] = make_label(g_uwModal, &lv_font_montserrat_14,
                                     theme::COLOR_TEXT_DIM);
        lv_obj_align(g_uwModalTok[i], LV_ALIGN_TOP_RIGHT, -16, 60 + i * 32);
    }

    g_uwBuilt = true;
}

static const char *usage_period_label() {
    static const char *LABELS[3] = {"hoje", "7d", "30d"};
    return LABELS[g_uwPeriod];
}

// Ordem de rank estavel: total desc, empate resolve por indice (nome do provider
// em PROVIDERS e alfabetico: claude < codex < opencode).
void layout_usage_podio() {
    const UsageTop &top = usageTop;
    int8_t order[3] = {0, 1, 2};
    if (top.valid) {
        for (int i = 1; i < 3; i++)
            for (int j = i; j > 0; j--) {
                const uint32_t a = top.providers[g_uwPeriod][order[j - 1]].total;
                const uint32_t b = top.providers[g_uwPeriod][order[j]].total;
                if (b > a) { const int8_t tmp = order[j - 1]; order[j - 1] = order[j]; order[j] = tmp; }
                else break;
            }
    }
    for (int i = 0; i < 3; i++) g_uwOrder[i] = order[i];
}

// Rótulos/valores/ícones por rank; hierarquia por largura e posicao, nao por cor.
void render_usage_podio() {
    static const char *NAMES[3] = {"Claude", "Codex", "OpenCode"};

    set_text_if(g_uwChip, g_cUwChip, sizeof(g_cUwChip), usage_period_label());

    // Colunas fixas: rank 0 (1o) -> centro, rank 1 (2o) -> esquerda,
    // rank 2 (3o) -> direita. Altura da barra por rank; cor degrau L4/L3/L2.
    constexpr int16_t COL_X[3] = {22, 102, 182};         // esq, centro, dir
    constexpr int16_t BAR_W = 72, BASE_Y = 190;
    constexpr int16_t BAR_H[3] = {120, 88, 64};          // altura por rank
    constexpr uint32_t BAR_C[3] = {theme::HM_L4, theme::HM_L3, theme::HM_L2};

    for (int rank = 0; rank < 3; rank++) {
        const int8_t provider = g_uwOrder[rank];
        const int16_t col_x = COL_X[(rank == 0) ? 1 : (rank == 1 ? 0 : 2)];
        const int16_t bh = BAR_H[rank];
        const int16_t top = BASE_Y - bh;

        lv_obj_t *bar = g_uwBar[rank];
        lv_obj_set_size(bar, BAR_W, bh);
        lv_obj_align(bar, LV_ALIGN_TOP_LEFT, col_x, top);


        char val[10];
        if (usageTop.valid) {
            uw_tokens_str(usageTop.providers[g_uwPeriod][provider].total, val, sizeof(val));
        } else {
            snprintf(val, sizeof(val), "--");
        }
        set_text_if(g_uwBarValue[rank], g_cUwBarValue[rank], 8, val);
        lv_obj_align(g_uwBarValue[rank], LV_ALIGN_TOP_LEFT, col_x, top - 23);

        set_text_if(g_uwBarName[rank], g_cUwBarName[rank], 12, NAMES[provider]);
        lv_obj_align(g_uwBarName[rank], LV_ALIGN_TOP_LEFT, col_x, BASE_Y + 4);
    }
}

void usage_widget_chip_cb(lv_event_t *e) {
    (void)e;
    g_uwPeriod = (g_uwPeriod + 1) % 3;
    layout_usage_podio();
    render_usage_podio();
}

void usage_widget_bar_cb(lv_event_t *e) {
    if (!usageTop.valid) return;
    const int8_t provider = g_uwOrder[(int)(intptr_t)lv_event_get_user_data(e)];
    const ProviderTop &pt = usageTop.providers[g_uwPeriod][provider];
    static const char *NAMES[3] = {"Claude", "Codex", "OpenCode"};

    char title[24];
    snprintf(title, sizeof(title), "%s - %s", NAMES[provider], usage_period_label());
    set_text_if(g_uwModalTitle, g_cUwModalTitle, sizeof(g_cUwModalTitle), title);

    char line[30];
    for (int i = 0; i < TOP_SESSIONS; i++) {
        if (i < pt.count) {
            snprintf(line, sizeof(line), "%d. %s", i + 1, pt.names[i]);
            set_text_if(g_uwModalName[i], g_cUwModalName[i], 28, line);
            char tok[8];
            uint32_t t = pt.tokens[i];
            if (t >= 1000000UL) snprintf(tok, sizeof(tok), "%lu.%luM",
                (unsigned long)(t / 1000000UL), (unsigned long)((t / 100000UL) % 10));
            else if (t >= 1000UL) snprintf(tok, sizeof(tok), "%luk", (unsigned long)(t / 1000UL));
            else snprintf(tok, sizeof(tok), "%lu", (unsigned long)t);
            set_text_if(g_uwModalTok[i], g_cUwModalTok[i], 8, tok);
        } else {
            set_text_if(g_uwModalName[i], g_cUwModalName[i], 28, "");
            set_text_if(g_uwModalTok[i], g_cUwModalTok[i], 8, "");
        }
    }
    g_uwModalProvider = provider;
    lv_obj_clear_flag(g_uwModal, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(g_uwModal);
}

// Toque em qualquer lugar do backdrop fecha; a escolha de periodo fica intacta.
void usage_modal_close_cb(lv_event_t *e) {
    (void)e;
    lv_obj_add_flag(g_uwModal, LV_OBJ_FLAG_HIDDEN);
}

void usage_widget_toggle_cb(lv_event_t *e) {
    (void)e;
    if (!g_uwBuilt) return;
    g_uwView = (g_uwView + 1) % 2;
    update_usage_widget();
}

void update_usage_widget() {
    if (!g_uwBuilt) return;

    const bool heat = (g_uwView == 0);
    set_flag_if(g_uwHeatmap, g_uwHeatOn, !heat);
    set_flag_if(g_uwPodio, g_uwPodioOn, heat);
    // Seta aponta para onde a proxima acao leva: ▸ no repouso, ◂ no podio.
    // g_uwArrow e o CONTAINER (faixa); o texto fica no label filho — lv_label_set_text
    // no container causava StoreProhibited (backtrace: lv_label_revert_dots).
    set_text_if(g_uwArrowLbl, g_cUwArrow, sizeof(g_cUwArrow),
                heat ? LV_SYMBOL_RIGHT : LV_SYMBOL_LEFT);
    if (!heat) {
        layout_usage_podio();
        render_usage_podio();
        return;
    }

    // Dia 0 = mais antigo; linha = semana, coluna = dia da semana (dom..sab).
    // Grade ENCOSTADA: x = col*39, y = titulo + row*33 (+2 de respiro).
    time_t nowT = time(nullptr);
    struct tm todayTm, startTm;
    localtime_r(&nowT, &todayTm);
    startTm = todayTm;
    startTm.tm_mday -= (USAGE_DAYS - 1);
    time_t startT = mktime(&startTm);
    localtime_r(&startT, &startTm);
    const int slot0 = startTm.tm_wday;                  // domingo = 0
    const int rows = (slot0 + USAGE_DAYS + 6) / 7;
    // Largura util 276 (card - faixa da seta): grade centralizada, SEM invadir a
    // seta. Altura: 6 linhas de 29 + gaps cabem com folga acima da borda.
    constexpr int16_t GRID_W = UW_GRID_W - 2;
    const int16_t x0 = (GRID_W - (7 * UW_CSX + 6 * 2)) / 2;
    const int16_t y0 = UW_TITLE_H + 2 + (UW_H - UW_TITLE_H - 2 - (rows * (UW_CSY + 2) - 2)) / 2;
    if (y0 != g_cUwY0) {
        g_cUwY0 = y0;
        for (int d = 0; d < USAGE_DAYS; d++) {
            const int slot = slot0 + d;
            lv_obj_align(g_uwCell[d], LV_ALIGN_TOP_LEFT,
                         x0 + (slot % 7) * (UW_CSX + 2),
                         y0 + (slot / 7) * (UW_CSY + 2));
        }
    }

    uint32_t peak = 1;
    for (int d = 0; d < USAGE_DAYS; d++) {
        const uint32_t v = usageHistory.valid ? usageHistory.daily[d] : 0;
        if (v > peak) peak = v;
    }

    const bool inspecting = (g_uwInspectDay >= 0);
    for (int d = 0; d < USAGE_DAYS; d++) {
        const uint32_t v = usageHistory.valid ? usageHistory.daily[d] : 0;
        uint32_t c = heatmap_color(v, peak);
        if (inspecting && d != g_uwInspectDay) c = uw_dim(c);
        set_color_if(g_uwCell[d], g_cUwCell[d], c, lv_obj_set_style_bg_color);
    }

    // Barra de inspecao: so existe com dia selecionado e historico valido.
    if (!inspecting || !usageHistory.valid) {
        lv_obj_add_flag(g_uwInspect, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    const int d = g_uwInspectDay;
    const uint32_t v = usageHistory.daily[d];
    char val[10];
    uw_tokens_str(v, val, sizeof(val));
    struct tm dayTm;
    localtime_r(&nowT, &dayTm);
    dayTm.tm_mday -= (USAGE_DAYS - 1 - d);
    time_t dayT = mktime(&dayTm);
    localtime_r(&dayT, &dayTm);
    char line1[48];
    snprintf(line1, sizeof(line1), "%s, %02d/%02d - %s tokens",
             uw_weekday_full(dayTm.tm_wday), dayTm.tm_mday, dayTm.tm_mon + 1, val);
    set_text_if(g_uwInspectL1, g_cUwInspect1, sizeof(g_cUwInspect1), line1);

    const int slot = slot0 + d;
    const int first = (slot / 7) * 7 - slot0;
    const int last = first + 6;
    uint32_t wk = 0;
    for (int k = first; k <= last; k++) {
        if (k < 0 || k >= USAGE_DAYS) continue;
        wk += usageHistory.daily[k];
    }
    char wkval[10];
    uw_tokens_str(wk, wkval, sizeof(wkval));
    struct tm a = dayTm, b = dayTm;
    a.tm_mday += (first - d);
    b.tm_mday += (last - d);
    time_t aT = mktime(&a), bT = mktime(&b);
    localtime_r(&aT, &a); localtime_r(&bT, &b);
    char line2[48];
    snprintf(line2, sizeof(line2), "%lu%% do pico - semana %02d-%02d: %s",
             (unsigned long)(peak ? v * 100UL / peak : 0), a.tm_mday, b.tm_mday, wkval);
    set_text_if(g_uwInspectL2, g_cUwInspect2, sizeof(g_cUwInspect2), line2);

    lv_obj_align(g_uwInspect, LV_ALIGN_TOP_MID, 0, y0 + (UW_H - UW_TITLE_H - 56) / 2);
    lv_obj_clear_flag(g_uwInspect, LV_OBJ_FLAG_HIDDEN);
}

// Toque num quadrado: repouso -> abre a inspecao do dia; inspecao -> sai
// (navegar entre dias sai e toca de novo, decisao do DEFINE).
void usage_cell_cb(lv_event_t *e) {
    if (!g_uwBuilt) return;
    const int d = (int)(intptr_t)lv_event_get_user_data(e);
    if (g_uwInspectDay >= 0) {
        usage_exit_inspection();
        return;
    }
    g_uwInspectDay = (int8_t)d;
    update_usage_widget();
}

// Toque no card (vaos/titulo) ou na barra: sai da inspecao. Repouso: nada.
void usage_card_cb(lv_event_t *e) {
    (void)e;
    if (g_uwInspectDay >= 0) usage_exit_inspection();
}

void usage_exit_inspection() {
    g_uwInspectDay = -1;
    lv_obj_add_flag(g_uwInspect, LV_OBJ_FLAG_HIDDEN);
    update_usage_widget();
}

// Seta: unica via entre heatmap e podio; sai da inspecao ao trocar.
void usage_arrow_cb(lv_event_t *e) {
    (void)e;
    if (!g_uwBuilt) return;
    g_uwInspectDay = -1;
    g_uwView = (g_uwView + 1) % 2;
    update_usage_widget();
}

// ---------------------------------------------------------------- updates

void update_header() {
    const TransportDataStatus status = session_transport_data_status();
    const uint32_t color = status.fresh ? theme::COLOR_WORK
                           : status.hasPayload ? theme::COLOR_STALE
                                               : theme::COLOR_FREE;
    set_color_if(g_headerDot, g_cHeaderDot,
                 color, lv_obj_set_style_bg_color);

    char clock[8];
    device_time_clock_str(clock, sizeof(clock));
    set_text_if(g_clockLabel, g_cClock, sizeof(g_cClock), clock);
}

void update_session_card(int i) {
    const SessionData &s = sessions[i];
    CardWidgets &c = cards[i];
    const uint32_t now = millis();

    if (!s.occupied) {
        g_cardRenderedId[i][0] = '\0';
        set_flag_if(c.timeLabel, c.cHidden, true);
        lv_obj_add_flag(c.statusLabel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(c.icon, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(c.nameLabel, LV_OBJ_FLAG_HIDDEN);
        set_color_if(c.container, c.cBorder, theme::COLOR_CARD_BORDER, lv_obj_set_style_border_color);
        set_color_if(c.container, c.cBg, theme::COLOR_CARD_BG, lv_obj_set_style_bg_color);
        c.hadSession = false;
        return;
    }

    strncpy(g_cardRenderedId[i], s.id, SESSION_ID_LEN - 1);
    g_cardRenderedId[i][SESSION_ID_LEN - 1] = '\0';

    if (c.cHidden) {
        set_flag_if(c.timeLabel, c.cHidden, false);
        lv_obj_clear_flag(c.statusLabel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(c.icon, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(c.nameLabel, LV_OBJ_FLAG_HIDDEN);
    }

    // Transicao de estado -> pisca por um instante. Sem isso a troca era silenciosa e
    // passava despercebida num painel que fica no canto da mesa.
    if (c.hadSession && s.state != c.prevState) c.blinkUntil = now + theme::BLINK_MS;
    c.prevState = s.state;
    c.hadSession = true;

    const bool blinking = now < c.blinkUntil;
    const bool blinkPhase = blinking && ((now / theme::BLINK_PERIOD_MS) % 2 == 0);

    // Contexto quase cheio: pisca em vermelho de forma CONTINUA, ao contrario do blink
    // de transicao acima, que dura BLINK_MS e some. O risco aqui nao passa sozinho — a
    // sessao vai ser compactada e perder historico — entao o aviso fica ate voce agir.
    // Dado velho nao pisca: um ctxPct de minutos atras nao justifica alarme.
    const bool ctxAlert = !s.stale && s.ctxPct >= theme::CTX_ALERT_PCT;
    const bool ctxPhase = ctxAlert && ((now / theme::CTX_BLINK_PERIOD_MS) % 2 == 0);

    // Dado velho tem cor propria: nao pode continuar exibindo o ultimo estado como se
    // ainda valesse (regra STALE_TIMEOUT_MS, ver docs/SPEC.md secao 3).
    const uint32_t stateColor = s.stale ? theme::COLOR_STALE : color_for_state(s.state);

    // Tempo (contexto, fonte menor)
    char buf[16];
    const uint32_t elapsed = (now - s.stateStartedAtMillis) / 1000UL;
    format_elapsed(elapsed, buf, sizeof(buf));
    set_text_if(c.timeLabel, c.cTime, sizeof(c.cTime), buf);

    // Status (acao, fonte maior e colorida)
    set_text_if(c.statusLabel, c.cStatus, sizeof(c.cStatus),
                s.stale ? "?" : label_for_state(s.state));
    set_color_if(c.statusLabel, c.cStatusColor, stateColor, lv_obj_set_style_text_color);

    // Borda + fundo. So 'perm' tinge o card inteiro: e o unico estado que bloqueia o
    // agente esperando voce, entao e o unico que merece gritar.
    uint32_t border = stateColor;
    uint32_t bg = theme::COLOR_CARD_BG;
    if (s.state == SessionState::PERM && !s.stale) bg = theme::COLOR_PERM_BG;
    if (blinkPhase) { border = theme::COLOR_TEXT; bg = theme::COLOR_PERM_BG; }
    // Vem por ULTIMO: contexto estourando supera qualquer cor de estado, inclusive
    // 'perm'. Perder o historico da sessao e o dano mais caro que o painel sinaliza.
    if (ctxPhase) { border = theme::COLOR_CTX_ALERT; bg = theme::COLOR_CTX_ALERT_BG; }
    set_color_if(c.container, c.cBorder, border, lv_obj_set_style_border_color);
    set_color_if(c.container, c.cBg, bg, lv_obj_set_style_bg_color);
    lv_obj_set_style_border_width(c.container,
        ctxAlert ? theme::ALERT_BORDER_W
                 : ((s.state == SessionState::FREE && !blinking) ? 1 : 2), 0);

    // Icone: dessaturado quando a sessao esta ociosa, para as ativas saltarem.
    const lv_image_dsc_t *ic = icon_for_provider(s.provider, s.tool);
    if (c.cIcon != ic) { c.cIcon = ic; lv_image_set_src(c.icon, ic); }
    const bool dim = (s.state == SessionState::FREE) || s.stale;
    if (c.cIconDim != dim) {
        c.cIconDim = dim;
        lv_obj_set_style_image_opa(c.icon, dim ? LV_OPA_40 : LV_OPA_COVER, 0);
        lv_obj_set_style_image_recolor_opa(c.icon, dim ? LV_OPA_60 : LV_OPA_TRANSP, 0);
        lv_obj_set_style_image_recolor(c.icon, theme::color(theme::COLOR_FREE), 0);
    }

    // Corte DURO no valor renderizado (nao apenas no tamanho visual do label): o texto
    // que vai para o LVGL ja tem no maximo NAME_LIMIT caracteres, entao nao ha como
    // quebrar linha nem invadir os elementos de cima.
    char shortName[NAME_LIMIT + 1];
    strncpy(shortName, s.projectName, NAME_LIMIT);
    shortName[NAME_LIMIT] = '\0';
    set_text_if(c.nameLabel, c.cName, sizeof(c.cName), shortName);
}

lv_obj_t *detail_row(lv_obj_t *parent, const char *caption, int16_t y,
                     lv_obj_t **capOut = nullptr) {
    lv_obj_t *cap = make_label(parent, &lv_font_montserrat_14, theme::COLOR_TEXT_FAINT);
    lv_label_set_text(cap, caption);
    if (capOut) *capOut = cap;
    lv_obj_align(cap, LV_ALIGN_TOP_LEFT, 24, y);

    lv_obj_t *val = make_label(parent, &lv_font_montserrat_16, theme::COLOR_TEXT);
    lv_obj_set_width(val, SCREEN_W - 24 - 110);
    lv_label_set_long_mode(val, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_align(val, LV_ALIGN_TOP_LEFT, 110, y - 2);
    return val;
}

void build_detail_screen(lv_obj_t *parent) {
    g_detail = lv_obj_create(parent);
    lv_obj_remove_style_all(g_detail);
    lv_obj_set_size(g_detail, SCREEN_W, SCREEN_H);
    lv_obj_set_pos(g_detail, 0, 0);
    lv_obj_set_style_bg_color(g_detail, theme::color(theme::COLOR_BG), 0);
    lv_obj_set_style_bg_opa(g_detail, LV_OPA_COVER, 0);
    lv_obj_clear_flag(g_detail, LV_OBJ_FLAG_SCROLLABLE);
    // Qualquer toque fecha: sem botao dedicado, que gastaria espaco e exigiria mira.
    lv_obj_add_flag(g_detail, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(g_detail, detail_close_cb, LV_EVENT_SHORT_CLICKED, nullptr);
    lv_obj_add_flag(g_detail, LV_OBJ_FLAG_HIDDEN);

    lv_obj_t *hint = make_label(g_detail, &lv_font_montserrat_14, theme::COLOR_TEXT_FAINT);
    lv_label_set_text(hint, "toque para voltar");
    lv_obj_align(hint, LV_ALIGN_TOP_MID, 0, 12);

    g_dtIcon = lv_image_create(g_detail);
    lv_obj_align(g_dtIcon, LV_ALIGN_TOP_MID, 0, 46);

    g_dtName = make_label(g_detail, &lv_font_montserrat_20, theme::COLOR_TEXT);
    lv_obj_set_width(g_dtName, SCREEN_W - 32);
    lv_obj_set_style_text_align(g_dtName, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_long_mode(g_dtName, LV_LABEL_LONG_MODE_WRAP);   // aqui o nome cabe inteiro
    lv_obj_align(g_dtName, LV_ALIGN_TOP_MID, 0, 100);

    g_dtState = make_label(g_detail, &lv_font_montserrat_20, theme::COLOR_WORK);
    lv_obj_align(g_dtState, LV_ALIGN_TOP_MID, 0, 158);

    // 6 linhas em passo de 32px: cabem entre o estado (y=158) e a dica do rodape.
    g_dtElapsed = detail_row(g_detail, "no estado",  200);
    g_dtTool    = detail_row(g_detail, "agente",     232);
    g_dtModel   = detail_row(g_detail, "modelo",     264);
    g_dtEffort  = detail_row(g_detail, "effort",     296);
    // Legenda vazia: o texto e escrito em show_detail() a partir da janela que o
    // daemon informou, para nao existir "tokens 24h" mostrando 12h.
    g_dtTokensCap = nullptr;
    g_dtTokens  = detail_row(g_detail, "", 328, &g_dtTokensCap);
    g_dtBranch  = detail_row(g_detail, "branch",     360);
    g_dtCtx     = detail_row(g_detail, "contexto",   392);

    lv_obj_t *tip = make_label(g_detail, &lv_font_montserrat_14, theme::COLOR_TEXT_FAINT);
    lv_label_set_text(tip, "toque longo no card: esconder");
    lv_obj_align(tip, LV_ALIGN_BOTTOM_MID, 0, -16);
}

void render_detail(const SessionData &s) {
    lv_image_set_src(g_dtIcon, icon_for_provider(s.provider, s.tool));
    lv_label_set_text(g_dtName, s.fullName[0] ? s.fullName : s.projectName);

    lv_label_set_text(g_dtState, s.stale ? "stale" : label_for_state(s.state));
    lv_obj_set_style_text_color(g_dtState,
        theme::color(s.stale ? theme::COLOR_STALE : color_for_state(s.state)), 0);

    char buf[16];
    format_elapsed((millis() - s.stateStartedAtMillis) / 1000UL, buf, sizeof(buf));
    lv_label_set_text(g_dtElapsed, buf);
    switch (s.tool) {
        case ToolType::CLAUDE:   lv_label_set_text(g_dtTool, "Claude");   break;
        case ToolType::OPENCODE: lv_label_set_text(g_dtTool, "OpenCode"); break;
        default:                 lv_label_set_text(g_dtTool, "Codex");    break;
    }
    lv_label_set_text(g_dtModel, s.model[0] ? s.model : "-");
    lv_label_set_text(g_dtEffort, s.effort[0] ? s.effort : "-");
    lv_label_set_text(g_dtBranch, s.branch[0] ? s.branch : "-");

    // Explica o card piscando: sem este numero o alerta vermelho seria um enigma.
    char ctx[24];
    if (s.ctxPct == 0) snprintf(ctx, sizeof(ctx), "-");
    else snprintf(ctx, sizeof(ctx), "%u%%%s", (unsigned)s.ctxPct,
                  s.ctxPct >= theme::CTX_ALERT_PCT ? " (alerta)" : "");
    lv_label_set_text(g_dtCtx, ctx);
    lv_obj_set_style_text_color(g_dtCtx,
        theme::color(s.ctxPct >= theme::CTX_ALERT_PCT ? theme::COLOR_CTX_ALERT
                                                      : theme::COLOR_TEXT), 0);

    char cap[16];
    snprintf(cap, sizeof(cap), "tokens %uh",
             usageStats.tokenWindowH ? usageStats.tokenWindowH : 12);
    lv_label_set_text(g_dtTokensCap, cap);

    if (s.tokensWindow) {
        char tk[16];
        format_tokens(s.tokensWindow, tk, sizeof(tk));
        lv_label_set_text(g_dtTokens, tk);
    } else {
        lv_label_set_text(g_dtTokens, "-");
    }

}

void show_detail(int idx) {
    if (idx < 0 || idx >= theme::SESSION_CARDS || !sessions[idx].occupied) return;
    strncpy(g_detailId, sessions[idx].id, sizeof(g_detailId) - 1);
    g_detailId[sizeof(g_detailId) - 1] = '\0';
    render_detail(sessions[idx]);
    lv_obj_clear_flag(g_detail, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(g_detail);
}

void picker_close_cb(lv_event_t *) {
    lv_obj_add_flag(g_picker, LV_OBJ_FLAG_HIDDEN);
}

void picker_pick_cb(lv_event_t *e) {
    const int *slot = (const int *)lv_event_get_user_data(e);
    if (!slot) return;
    const int i = *slot;
    if (i < 0 || i >= CATALOG_MAX) return;
    const char *selectedId = g_pickerRenderedId[i];
    if (!selectedId[0]) return;
    bool stillExists = false;
    for (uint8_t current = 0; current < catalogCount; current++) {
        if (!strcmp(catalog[current].id, selectedId)) { stillExists = true; break; }
    }
    if (!stillExists) return;

    // Escolher no seletor faz as duas coisas: desfaz um "esconder" acidental e fixa a
    // sessao, para ela aparecer mesmo estando fora da janela de 4h.
    hiddenList.remove(selectedId);
    pinnedList.add(selectedId);
    lv_obj_add_flag(g_picker, LV_OBJ_FLAG_HIDDEN);
}

void build_picker(lv_obj_t *parent) {
    g_picker = lv_obj_create(parent);
    lv_obj_remove_style_all(g_picker);
    lv_obj_set_size(g_picker, SCREEN_W, SCREEN_H);
    lv_obj_set_pos(g_picker, 0, 0);
    lv_obj_set_style_bg_color(g_picker, theme::color(theme::COLOR_BG), 0);
    lv_obj_set_style_bg_opa(g_picker, LV_OPA_COVER, 0);
    lv_obj_clear_flag(g_picker, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(g_picker, LV_OBJ_FLAG_HIDDEN);

    lv_obj_t *title = make_label(g_picker, &lv_font_montserrat_16, theme::COLOR_TEXT);
    lv_label_set_text(title, "escolher sessao");
    lv_obj_align(title, LV_ALIGN_TOP_LEFT, theme::MARGIN, 10);

    // Botao de voltar explicito: aqui o toque em qualquer lugar nao pode fechar, senao
    // seria impossivel tocar numa linha da lista sem fechar antes.
    lv_obj_t *back = make_card(g_picker, SCREEN_W - 78, 6, 70, 26);
    lv_obj_add_flag(back, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(back, picker_close_cb, LV_EVENT_SHORT_CLICKED, nullptr);
    lv_obj_t *bl = make_label(back, &lv_font_montserrat_14, theme::COLOR_TEXT_DIM);
    lv_label_set_text(bl, "voltar");
    lv_obj_center(bl);

    g_pickerEmpty = make_label(g_picker, &lv_font_montserrat_14, theme::COLOR_TEXT_FAINT);
    lv_label_set_text(g_pickerEmpty, "nenhuma outra sessao disponivel");
    lv_obj_align(g_pickerEmpty, LV_ALIGN_TOP_MID, 0, 60);
    lv_obj_add_flag(g_pickerEmpty, LV_OBJ_FLAG_HIDDEN);

    g_pickerList = lv_obj_create(g_picker);
    lv_obj_remove_style_all(g_pickerList);
    lv_obj_set_size(g_pickerList, SCREEN_W - 2 * theme::MARGIN, SCREEN_H - 52);
    lv_obj_set_pos(g_pickerList, theme::MARGIN, 44);
    lv_obj_set_flex_flow(g_pickerList, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(g_pickerList, 6, 0);
    lv_obj_set_style_bg_opa(g_pickerList, LV_OPA_TRANSP, 0);
}

// Monta as linhas na hora de abrir: o catalogo muda a cada POST, entao construir uma
// vez no boot mostraria dado velho.
void picker_open() {
    lv_obj_clean(g_pickerList);

    if (catalogCount == 0) {
        lv_obj_clear_flag(g_pickerEmpty, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(g_pickerEmpty, LV_OBJ_FLAG_HIDDEN);
        for (uint8_t i = 0; i < catalogCount; i++) {
            g_pickerSlot[i] = i;
            strncpy(g_pickerRenderedId[i], catalog[i].id, SESSION_ID_LEN - 1);
            g_pickerRenderedId[i][SESSION_ID_LEN - 1] = '\0';

            lv_obj_t *row = lv_obj_create(g_pickerList);
            lv_obj_remove_style_all(row);
            lv_obj_set_size(row, lv_pct(100), 38);
            lv_obj_set_style_bg_color(row, theme::color(theme::COLOR_CARD_BG), 0);
            lv_obj_set_style_bg_opa(row, LV_OPA_COVER, 0);
            lv_obj_set_style_radius(row, 8, 0);
            lv_obj_set_style_pad_all(row, 6, 0);
            lv_obj_clear_flag(row, LV_OBJ_FLAG_SCROLLABLE);
            lv_obj_add_flag(row, LV_OBJ_FLAG_CLICKABLE);
            lv_obj_add_event_cb(row, picker_pick_cb, LV_EVENT_SHORT_CLICKED, &g_pickerSlot[i]);

            lv_obj_t *ic = lv_image_create(row);
            lv_image_set_src(ic, icon_for_provider(catalog[i].provider, catalog[i].tool));
            lv_image_set_scale(ic, 128);            // 40px -> 20px
            lv_obj_align(ic, LV_ALIGN_LEFT_MID, -8, 0);

            lv_obj_t *nm = make_label(row, &lv_font_montserrat_14, theme::COLOR_TEXT);
            lv_label_set_text(nm, catalog[i].name);
            lv_obj_set_width(nm, SCREEN_W - 130);
            lv_label_set_long_mode(nm, LV_LABEL_LONG_MODE_DOTS);
            lv_obj_align(nm, LV_ALIGN_LEFT_MID, 28, 0);

            lv_obj_t *stt = make_label(row, &lv_font_montserrat_14,
                                       color_for_state(catalog[i].state));
            lv_label_set_text(stt, label_for_state(catalog[i].state));
            lv_obj_align(stt, LV_ALIGN_RIGHT_MID, -4, 0);
        }
    }

    lv_obj_clear_flag(g_picker, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(g_picker);
}

// Alerta: enquanto houver sessao em perm/ask, a borda da tela pulsa na cor do estado
// mais urgente. O painel passa a te chamar em vez de esperar voce olhar.
void update_alert() {
    SessionState worst = SessionState::IDLE;
    for (int i = 0; i < theme::SESSION_CARDS; i++) {
        const SessionData &s = sessions[i];
        if (!s.occupied || s.stale) continue;
        if (s.state == SessionState::PERM) { worst = SessionState::PERM; break; }
        if (s.state == SessionState::ASK)  worst = SessionState::ASK;
    }

    const bool alert = (worst == SessionState::PERM || worst == SessionState::ASK);
    lv_obj_t *scr = lv_scr_act();

    if (!alert) {
        if (g_alertOn) {
            g_alertOn = false;
            lv_obj_set_style_border_width(scr, 0, 0);
            g_cScreenBorder = 0;
        }
        return;
    }

    g_alertOn = true;
    const bool on = (millis() / theme::ALERT_PERIOD_MS) % 2 == 0;
    const uint32_t c = on ? color_for_state(worst) : theme::COLOR_BG;
    if (c != g_cScreenBorder) {
        g_cScreenBorder = c;
        lv_obj_set_style_border_color(scr, theme::color(c), 0);
        lv_obj_set_style_border_width(scr, theme::ALERT_BORDER_W, 0);
    }
}

} // namespace

// Exposto para o GET /diag (session_transport): prova que o historico chegou e
// qual visao esta ativa, sem depender de impressao visual na tela.
uint8_t ui_dashboard_usage_view() { return g_uwView; }

void ui_dashboard_usage_debug(int *built, int *x, int *y, uint32_t *color) {
    *built = g_uwBuilt ? 1 : 0;
    *x = g_uwCell[USAGE_DAYS - 1] ? lv_obj_get_x(g_uwCell[USAGE_DAYS - 1]) : -1;
    *y = g_uwCell[USAGE_DAYS - 1] ? lv_obj_get_y(g_uwCell[USAGE_DAYS - 1]) : -1;
    *color = g_cUwCell[USAGE_DAYS - 1];
}

// Estado REAL no LVGL da celula de hoje: coords absolutas de tela, cor efetiva,
// flags de visibilidade e clicabilidade (diagnostico do card "vazio").
void ui_dashboard_usage_debug2(int *heatVisible, int *podioVisible, int *absX,
                               int *absY, uint32_t *realColor, int *cellClickable) {
    lv_obj_t *cell = g_uwCell[USAGE_DAYS - 1];
    if (!cell || !g_uwBuilt) {
        *heatVisible = *podioVisible = *absX = *absY = *cellClickable = -1;
        *realColor = 0;
        return;
    }
    *heatVisible = lv_obj_has_flag(g_uwHeatmap, LV_OBJ_FLAG_HIDDEN) ? 0 : 1;
    *podioVisible = lv_obj_has_flag(g_uwPodio, LV_OBJ_FLAG_HIDDEN) ? 0 : 1;
    lv_area_t a;
    lv_obj_get_coords(cell, &a);
    *absX = a.x1;
    *absY = a.y1;
    lv_color_t c = lv_obj_get_style_bg_color(cell, LV_PART_MAIN);
    *realColor = lv_color_to_u32(c);
    *cellClickable = lv_obj_has_flag(cell, LV_OBJ_FLAG_CLICKABLE) ? 1 : 0;
}

void ui_dashboard_init() {
    lv_obj_t *scr = lv_scr_act();
    lv_obj_set_style_bg_color(scr, theme::color(theme::COLOR_BG), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);

    build_header(scr);

    for (int i = 0; i < theme::SESSION_CARDS; i++) {
        const int col = i % theme::GRID_COLS;
        const int row = i / theme::GRID_COLS;
        build_session_card(scr, i,
                           theme::MARGIN + col * (theme::CELL + theme::GUTTER),
                           theme::GRID_TOP + row * theme::ROW_STEP);
    }

    build_usage_widget(scr);
    build_detail_screen(scr);
    build_picker(scr);

    ui_dashboard_update();
}

void ui_dashboard_update() {
    update_header();
    for (int i = 0; i < theme::SESSION_CARDS; i++) update_session_card(i);
    update_usage_widget();
    update_alert();

    // Detalhe segue a identidade, nao o slot. Reordem atualiza a mesma sessao; remocao
    // fecha a tela para nunca mostrar dados do novo ocupante daquele indice.
    if (g_detailId[0]) {
        const int idx = find_session_by_id(g_detailId);
        if (idx < 0) detail_close_cb(nullptr);
        else render_detail(sessions[idx]);
    }
}
