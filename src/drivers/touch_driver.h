#pragma once
#include <Arduino.h>

// Touch capacitivo integrado ao AXS15231B (mesmo CI do display), I2C 0x3B.
// NAO e GT911 — ver docs/SPEC.md secao 2.

// Contadores para validar um toque real de fora do device (GET /diag), sem depender de
// alguem estar lendo o log serial no instante exato do toque.
struct TouchDiag {
    bool     available;
    uint32_t reads;        // leituras I2C bem-sucedidas
    uint32_t touches;      // leituras que continham toque
    uint32_t i2cErrors;
    uint32_t shortReads;
    uint16_t lastX, lastY;
    uint32_t lastTouchMs;
    uint8_t  lastRaw[8];
    // Ultimos toques (x,y) e qual card recebeu evento. Sem isso nao da para separar
    // "tocou fora do card" de "tocou no card e o evento nao chegou".
    uint16_t recentX[6], recentY[6];
    uint8_t  recentN;      // quantos validos
    uint8_t  recentHead;
    uint32_t cardClicks[8];   // eventos por indice de card de sessao
    uint32_t cardLongs[8];
    uint32_t cardIgnoredEmpty; // toques em card sem sessao (ignorados de proposito)
};

bool touch_init();
bool touch_available();
void touch_set_debug(bool enabled);
const TouchDiag &touch_diag();

// Incrementado pelo callback do card de sessao: prova que o evento LVGL chegou ao
// objeto certo, nao so que o driver leu uma coordenada.
void touch_note_card(int idx, bool longPress, bool ignoredEmpty);
