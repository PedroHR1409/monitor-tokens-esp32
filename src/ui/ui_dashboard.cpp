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
lv_obj_t *g_tokValue = nullptr, *g_tokSessions = nullptr;
char g_cTok[12] = "", g_cTokSess[16] = "";

// cards de cota (ocuparam a faixa que era do Pomodoro)
lv_obj_t *g_qCxValue = nullptr, *g_qCxSub = nullptr, *g_qCxTitle = nullptr;
lv_obj_t *g_qClValue = nullptr, *g_qClSub = nullptr, *g_qClTitle = nullptr;
char g_cQCxValue[8] = "", g_cQCxSub[14] = "", g_cQCxTitle[12] = "";
char g_cQClValue[8] = "", g_cQClSub[14] = "", g_cQClTitle[12] = "";
uint32_t g_cQCxColor = 0, g_cQClColor = 0;
// Card de consumo rotativo: toque cicla claude -> opencode -> codex. 0-based no enum
// local QUOTA_ROT_*; o valor sobrevive ao refresh porque update_quota_cards le dele.
uint8_t g_quotaRot = 0;
enum : uint8_t { QUOTA_ROT_CLAUDE = 0, QUOTA_ROT_OPENCODE = 1, QUOTA_ROT_CODEX = 2 };

// Heatmap de 12 horas. Escolhido depois de medir o dado real: 10 dos 12 baldes sao
// zero e o pico chega a 10x o menor valor nao-nulo. Uso de tokens e esparso e em
// rajadas, entao linha/coluna vira "reta no chao + penhasco"; no heatmap a hora vazia
// e so um bloco apagado, que le bem. Ver docs/SPEC.md secao 11.
lv_obj_t *g_hmCell[SPARK_BUCKETS]  = {nullptr};   // bloco de intensidade
lv_obj_t *g_hmValue[SPARK_BUCKETS] = {nullptr};   // tokens da hora, em milhoes
lv_obj_t *g_hmHour[SPARK_BUCKETS]  = {nullptr};   // hora do balde
uint32_t  g_cHmValue[SPARK_BUCKETS] = {0};
uint32_t  g_cHmOpa[SPARK_BUCKETS]   = {0xFFFF};
char      g_cHmValueTxt[SPARK_BUCKETS][6] = {{0}};
char      g_cHmHourTxt[SPARK_BUCKETS][4]  = {{0}};
uint8_t   g_cHmEndHour = 255;

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
void update_quota_cards();
void quota_rot_cb(lv_event_t *e);
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

void build_tokens_card(lv_obj_t *parent) {
    lv_obj_t *card = make_card(parent, theme::MARGIN, theme::ROW2_Y, theme::CELL, theme::CELL);

    lv_obj_t *title = make_label(card, &lv_font_montserrat_14, theme::COLOR_TEXT_FAINT);
    lv_label_set_text(title, "tokens");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 0);

    g_tokValue = make_label(card, &lv_font_montserrat_20, theme::COLOR_ACCENT);
    lv_label_set_text(g_tokValue, "--");
    lv_obj_align(g_tokValue, LV_ALIGN_CENTER, 0, 0);

    g_tokSessions = make_label(card, &lv_font_montserrat_14, theme::COLOR_TEXT_FAINT);
    lv_label_set_text(g_tokSessions, "");
    lv_obj_align(g_tokSessions, LV_ALIGN_BOTTOM_MID, 0, 0);
}

// Os dois cards de cota tem a MESMA forma (titulo / numero / rodape) de proposito: a
// comparacao entre eles so funciona se a diferenca visivel for o conteudo, nao o
// desenho. O que separa oficial de estimado e o rodape ("5h oficial" x "estimado") e o
// til antes do numero do Claude.
lv_obj_t *build_quota_card(lv_obj_t *parent, int16_t x, const char *title,
                           lv_obj_t **titleOut, lv_obj_t **valueOut, lv_obj_t **subOut) {
    lv_obj_t *card = make_card(parent, x, theme::ROW2_Y, theme::CELL, theme::CELL);

    lv_obj_t *cap = make_label(card, &lv_font_montserrat_14, theme::COLOR_TEXT_FAINT);
    lv_label_set_text(cap, title);
    lv_obj_align(cap, LV_ALIGN_TOP_MID, 0, 0);
    if (titleOut) *titleOut = cap;

    *valueOut = make_label(card, &lv_font_montserrat_20, theme::COLOR_TEXT_DIM);
    lv_label_set_text(*valueOut, "--");
    lv_obj_align(*valueOut, LV_ALIGN_CENTER, 0, 0);

    *subOut = make_label(card, &lv_font_montserrat_12, theme::COLOR_TEXT_FAINT);
    lv_label_set_text(*subOut, "");
    lv_obj_align(*subOut, LV_ALIGN_BOTTOM_MID, 0, 0);
    return card;
}

void build_quota_cards(lv_obj_t *parent) {
    build_quota_card(parent, theme::QUOTA_CX_X, "codex",
                     &g_qCxTitle, &g_qCxValue, &g_qCxSub);
    lv_obj_t *rotCard = build_quota_card(parent, theme::QUOTA_CL_X, "claude",
                                         &g_qClTitle, &g_qClValue, &g_qClSub);
    lv_obj_add_flag(rotCard, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(rotCard, quota_rot_cb, LV_EVENT_SHORT_CLICKED, nullptr);
}

// Toque no card de consumo cicla a fonte exibida. Callback precisa ficar no card
// (nao nos labels), senao tocar no texto nao dispara — mesmo padrao dos cards de
// sessao, que recebem o clique no container.
void quota_rot_cb(lv_event_t *e) {
    (void)e;
    g_quotaRot = (g_quotaRot + 1) % 3;
    update_quota_cards();
}

void build_heatmap_card(lv_obj_t *parent) {
    lv_obj_t *card = make_card(parent, theme::MARGIN, theme::SPARK_Y, theme::SPARK_W, theme::SPARK_H);

    // Sem titulo: o espaco foi todo para os rotulos de hora e de tokens, que carregam
    // mais informacao que a legenda fixa.
    const int16_t inner = theme::SPARK_W - 2 * theme::HM_PAD;
    const int16_t cw = (inner - theme::HM_GAP * (SPARK_BUCKETS - 1)) / SPARK_BUCKETS;

    for (int i = 0; i < SPARK_BUCKETS; i++) {
        const int16_t x = i * (cw + theme::HM_GAP);

        // tokens da hora (em milhoes), acima do bloco
        g_hmValue[i] = make_label(card, &lv_font_montserrat_12, theme::COLOR_TEXT_FAINT);
        // Nao usar LONG_MODE_CLIP aqui: ele seta expand=1 no label, o que faz o widget
        // se dimensionar pelo texto e IGNORAR a largura definida — e sem largura o
        // TEXT_ALIGN_CENTER nao tem sobre o que centralizar, entao o rotulo encostava a
        // esquerda em vez de alinhar com a barra. O texto tem 3 caracteres e cabe em cw.
        lv_label_set_long_mode(g_hmValue[i], LV_LABEL_LONG_MODE_WRAP);
        lv_obj_set_width(g_hmValue[i], cw);
        lv_obj_set_style_text_align(g_hmValue[i], LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_align(g_hmValue[i], LV_ALIGN_TOP_LEFT, x, theme::HM_VALUE_Y);

        g_hmCell[i] = lv_obj_create(card);
        lv_obj_remove_style_all(g_hmCell[i]);
        lv_obj_set_size(g_hmCell[i], cw, theme::HM_CELL_H);
        lv_obj_set_style_radius(g_hmCell[i], 3, 0);
        lv_obj_set_style_bg_color(g_hmCell[i], theme::color(theme::COLOR_ACCENT), 0);
        lv_obj_set_style_bg_opa(g_hmCell[i], LV_OPA_COVER, 0);
        lv_obj_align(g_hmCell[i], LV_ALIGN_TOP_LEFT, x, theme::HM_CELL_Y);

        // hora do balde, abaixo do bloco
        g_hmHour[i] = make_label(card, &lv_font_montserrat_12, theme::COLOR_TEXT_FAINT);
        lv_label_set_long_mode(g_hmHour[i], LV_LABEL_LONG_MODE_WRAP);
        lv_obj_set_width(g_hmHour[i], cw);
        lv_obj_set_style_text_align(g_hmHour[i], LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_align(g_hmHour[i], LV_ALIGN_TOP_LEFT, x, theme::HM_HOUR_Y);
    }
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

void update_tokens_card() {
    char buf[16];
    if (usageStats.valid) format_tokens(usageStats.tokensToday, buf, sizeof(buf));
    else                  snprintf(buf, sizeof(buf), "--");
    set_text_if(g_tokValue, g_cTok, sizeof(g_cTok), buf);

    char sess[16];
    if (usageStats.valid && usageStats.stale) snprintf(sess, sizeof(sess), "dados stale");
    else if (usageStats.valid) snprintf(sess, sizeof(sess), "%u ativas 12h", usageStats.active12h);
    else                  sess[0] = '\0';
    set_text_if(g_tokSessions, g_cTokSess, sizeof(g_cTokSess), sess);
}

// Cor do percentual de cota. Tres significados que nao podem se confundir: apagado =
// nao ha dado, roxo = o dado existe mas esta velho (cota velha engana mais que a
// ausencia dela), ambar/vermelho = a cota esta subindo.
uint32_t quota_color(uint16_t pct, bool stale) {
    if (stale)                          return theme::COLOR_STALE;
    if (pct >= theme::QUOTA_ALERT_PCT)  return theme::COLOR_CTX_ALERT;
    if (pct >= theme::QUOTA_WARN_PCT)   return theme::COLOR_PERM;
    return theme::COLOR_TEXT;
}

void update_quota_cards() {
    const QuotaStats &q = usageStats.quota;
    const bool stale = usageStats.stale;
    const uint8_t win = q.windowH ? q.windowH : 5;
    // A janela vai no titulo dos DOIS cards. Rotular so um deixaria a duvida de se o
    // outro numero e da mesma janela — e a comparacao lado a lado depende disso.
    char title[12], value[8], sub[14];

    // --- Codex: numero oficial, com a janela semanal no rodape ---
    const bool cxOk = usageStats.valid && q.codexOk;
    snprintf(title, sizeof(title), "codex %uh", (unsigned)win);
    set_text_if(g_qCxTitle, g_cQCxTitle, sizeof(g_cQCxTitle), title);

    // "Oficial" nao implica "atual". O rollout so cresce enquanto o Codex CLI roda; se
    // o consumo acontece por outra superficie, o ultimo numero fica parado e envelhece
    // em silencio. Passada a janela de frescor, o rodape troca a semanal pela IDADE da
    // leitura — a pergunta que importa deixa de ser "quanto" e passa a ser "de quando".
    const bool cxAged = cxOk && q.codexAgeS > theme::QUOTA_FRESH_S;
    if (cxOk) {
        snprintf(value, sizeof(value), "%u%%", (unsigned)q.codexH5Pct);
        if (cxAged) {
            char idade[8];
            format_elapsed(q.codexAgeS, idade, sizeof(idade));
            snprintf(sub, sizeof(sub), "ha %s", idade);
        } else {
            snprintf(sub, sizeof(sub), "sem %u%%", (unsigned)q.codexWeekPct);
        }
    } else {
        snprintf(value, sizeof(value), "--");
        // Sem dado o rodape diz POR QUE, em vez de sumir: "sem rollout" aponta para o
        // Codex nao ter rodado nesta maquina, que e uma causa acionavel.
        snprintf(sub, sizeof(sub), "sem rollout");
    }
    set_text_if(g_qCxValue, g_cQCxValue, sizeof(g_cQCxValue), value);
    set_text_if(g_qCxSub, g_cQCxSub, sizeof(g_cQCxSub), sub);
    set_color_if(g_qCxValue, g_cQCxColor,
                 cxOk ? quota_color(q.codexH5Pct, stale || cxAged) : theme::COLOR_TEXT_DIM,
                 lv_obj_set_style_text_color);

    // --- Card de consumo ROTATIVO (toque cicla claude -> opencode -> codex) ---
    // Estimados mostram tokens crus (ou ~% com teto declarado, so Claude); o Codex
    // entra aqui na janela SEMANAL oficial, que o card fixo ao lado nao cobre —
    // assim a rotacao nao repete o mesmo numero duas vezes na tela.
    const bool clOk = usageStats.valid && q.claudeOk;
    const bool ocOk = usageStats.valid && q.opencodeOk;
    const bool cxRotOk = usageStats.valid && q.codexOk;
    uint32_t rotColor = theme::COLOR_TEXT_DIM;
    switch (g_quotaRot) {
        case QUOTA_ROT_OPENCODE: {
            snprintf(title, sizeof(title), "opencode %uh", (unsigned)win);
            if (ocOk) {
                format_tokens(q.opencodeTokens, value, sizeof(value));
                snprintf(sub, sizeof(sub), "estimado");
                rotColor = stale ? theme::COLOR_STALE : theme::COLOR_TEXT;
            } else {
                snprintf(value, sizeof(value), "--");
                snprintf(sub, sizeof(sub), "sem uso 5h");
            }
            break;
        }
        case QUOTA_ROT_CODEX: {
            snprintf(title, sizeof(title), "codex sem");
            if (cxRotOk) {
                snprintf(value, sizeof(value), "%u%%", (unsigned)q.codexWeekPct);
                // Mesma regra de frescor do card fixo: numero oficial parado e um
                // numero de outro dia; a idade no rodape evita a leitura errada.
                const bool aged = q.codexAgeS > theme::QUOTA_FRESH_S;
                if (aged) {
                    char idade[8];
                    format_elapsed(q.codexAgeS, idade, sizeof(idade));
                    snprintf(sub, sizeof(sub), "ha %s", idade);
                } else {
                    snprintf(sub, sizeof(sub), "oficial");
                }
                rotColor = quota_color(q.codexWeekPct, stale || aged);
            } else {
                snprintf(value, sizeof(value), "--");
                snprintf(sub, sizeof(sub), "sem rollout");
            }
            break;
        }
        default: {  // QUOTA_ROT_CLAUDE
            snprintf(title, sizeof(title), "claude %uh", (unsigned)win);
            if (clOk) {
                if (q.claudePct > 0) snprintf(value, sizeof(value), "~%u%%", (unsigned)q.claudePct);
                else                 format_tokens(q.claudeTokens, value, sizeof(value));
                snprintf(sub, sizeof(sub), "estimado");
                rotColor = (q.claudePct > 0) ? quota_color(q.claudePct, stale)
                           : (stale ? theme::COLOR_STALE : theme::COLOR_TEXT);
            } else {
                snprintf(value, sizeof(value), "--");
                sub[0] = '\0';
            }
            break;
        }
    }
    set_text_if(g_qClTitle, g_cQClTitle, sizeof(g_cQClTitle), title);
    set_text_if(g_qClValue, g_cQClValue, sizeof(g_cQClValue), value);
    set_text_if(g_qClSub, g_cQClSub, sizeof(g_cQClSub), sub);
    set_color_if(g_qClValue, g_cQClColor, rotColor, lv_obj_set_style_text_color);
}

void update_heatmap() {
    uint32_t peak = 1;
    for (int i = 0; i < SPARK_BUCKETS; i++)
        if (usageStats.spark[i] > peak) peak = usageStats.spark[i];

    const bool hourChanged = (usageStats.sparkEndHour != g_cHmEndHour);
    g_cHmEndHour = usageStats.sparkEndHour;

    for (int i = 0; i < SPARK_BUCKETS; i++) {
        const uint32_t v = usageStats.valid ? usageStats.spark[i] : 0;

        // Intensidade proporcional ao pico, com piso: com amplitude de 10x uma escala
        // linear pura deixaria as horas menores quase invisiveis. Hora sem uso vira um
        // bloco apagado, que e justamente o que faz o heatmap funcionar com dado esparso.
        uint32_t opa;
        uint32_t color;
        if (v == 0) {
            opa = LV_OPA_COVER;
            color = theme::COLOR_IDLE;
        } else {
            opa = theme::HM_MIN_OPA +
                  (uint32_t)((uint64_t)v * (LV_OPA_COVER - theme::HM_MIN_OPA) / peak);
            color = usageStats.stale ? theme::COLOR_STALE : theme::COLOR_ACCENT;
        }
        const uint32_t key = (color << 8) | (opa & 0xFF);
        if (key != g_cHmOpa[i]) {
            g_cHmOpa[i] = key;
            lv_obj_set_style_bg_color(g_hmCell[i], theme::color(color), 0);
            lv_obj_set_style_bg_opa(g_hmCell[i], (lv_opa_t)opa, 0);
        }

        // Rotulo em milhoes; hora sem uso vira "0" seco, nao "0.0" — a casa decimal so
        // existe para diferenciar valores, e nao ha o que diferenciar em zero.
        char val[6];
        if (v == 0) {
            snprintf(val, sizeof(val), "0");
        } else {
            snprintf(val, sizeof(val), "%lu.%lu",
                     (unsigned long)(v / 1000000UL),
                     (unsigned long)((v / 100000UL) % 10));
        }
        g_cHmValue[i] = v;
        set_text_if(g_hmValue[i], g_cHmValueTxt[i], sizeof(g_cHmValueTxt[i]), val);

        // Hora do balde: o ultimo e sparkEndHour, os anteriores voltam uma hora cada.
        if (hourChanged) {
            const int h = ((int)usageStats.sparkEndHour - (SPARK_BUCKETS - 1 - i) + 240) % 24;
            char hr[4];
            snprintf(hr, sizeof(hr), "%02d", h);
            set_text_if(g_hmHour[i], g_cHmHourTxt[i], sizeof(g_cHmHourTxt[i]), hr);
            // A hora corrente fica destacada para dar referencia temporal.
            lv_obj_set_style_text_color(g_hmHour[i],
                theme::color(i == SPARK_BUCKETS - 1 ? theme::COLOR_TEXT_DIM
                                                    : theme::COLOR_TEXT_FAINT), 0);
        }
    }
}

// Uma linha "rotulo   valor" da tela de detalhe.
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

    build_tokens_card(scr);
    build_quota_cards(scr);
    build_heatmap_card(scr);
    build_detail_screen(scr);
    build_picker(scr);

    ui_dashboard_update();
}

void ui_dashboard_update() {
    update_header();
    for (int i = 0; i < theme::SESSION_CARDS; i++) update_session_card(i);
    update_tokens_card();
    update_quota_cards();
    update_heatmap();
    update_alert();

    // Detalhe segue a identidade, nao o slot. Reordem atualiza a mesma sessao; remocao
    // fecha a tela para nunca mostrar dados do novo ocupante daquele indice.
    if (g_detailId[0]) {
        const int idx = find_session_by_id(g_detailId);
        if (idx < 0) detail_close_cb(nullptr);
        else render_detail(sessions[idx]);
    }
}
