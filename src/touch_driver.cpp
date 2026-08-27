#include "touch_driver.h"
#include "config.h"
#include <Wire.h>
#include <lvgl.h>

namespace {

// Sequencia de leitura do touchpad do AXS15231B.
//
// CAUSA RAIZ do "touch nao responde": esta sequencia tem 11 BYTES, nao 8. A
// implementacao de referencia declara `AXS_READ_TOUCHPAD[11]` inicializando so os 8
// primeiros valores — os 3 ultimos ficam zerados por regra do C, e `sizeof` devolve 11.
// Enviando apenas 8 bytes o controlador nao reconhece o comando e nunca devolve
// coordenada nenhuma; o indev do LVGL era registrado e lido normalmente, mas sempre com
// "sem toque", entao nenhum evento chegava aos objetos clicaveis.
const uint8_t AXS_READ_TOUCHPAD[11] = {
    0xB5, 0xAB, 0xA5, 0x5A, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00
};

bool s_available = false;
bool s_debug = false;

// Diagnostico exposto via GET /diag — permite validar um toque REAL de fora do device,
// sem depender de alguem lendo o log serial no momento exato.
TouchDiag s_diag = {};

bool read_raw(uint16_t &outX, uint16_t &outY) {
    if (!s_available) return false;

    Wire.beginTransmission(TOUCH_I2C_ADDR);
    Wire.write(AXS_READ_TOUCHPAD, sizeof(AXS_READ_TOUCHPAD));
    if (Wire.endTransmission() != 0) {
        s_diag.i2cErrors++;
        return false;
    }

    // O controlador precisa de um instante para preparar a resposta; sem esta pausa a
    // leitura sai truncada ou zerada.
    delayMicroseconds(50);

    uint8_t data[8] = {0};
    const uint8_t n = Wire.requestFrom((uint8_t)TOUCH_I2C_ADDR, (uint8_t)sizeof(data));
    if (n < sizeof(data)) {
        s_diag.shortReads++;
        return false;
    }
    for (uint8_t i = 0; i < sizeof(data) && Wire.available(); i++) data[i] = Wire.read();

    s_diag.reads++;
    memcpy(s_diag.lastRaw, data, sizeof(data));

    // Toque valido: data[0] == 0 e data[1] (numero de pontos) != 0.
    if (data[0] != 0 || data[1] == 0) return false;

    // 12 bits por eixo, ja na resolucao fisica do painel (320x480 portrait).
    uint16_t x = (uint16_t)(((data[2] & 0x0F) << 8) | data[3]);
    uint16_t y = (uint16_t)(((data[4] & 0x0F) << 8) | data[5]);

    if (x >= SCREEN_W) x = SCREEN_W - 1;
    if (y >= SCREEN_H) y = SCREEN_H - 1;

    outX = x;
    outY = y;

    s_diag.touches++;
    s_diag.lastX = x;
    s_diag.lastY = y;
    s_diag.lastTouchMs = millis();
    s_diag.recentX[s_diag.recentHead] = x;
    s_diag.recentY[s_diag.recentHead] = y;
    s_diag.recentHead = (s_diag.recentHead + 1) % 6;
    if (s_diag.recentN < 6) s_diag.recentN++;

    if (s_debug) {
        Serial.printf("[touch] x=%u y=%u (raw %02X %02X %02X %02X %02X %02X)\n",
                      x, y, data[0], data[1], data[2], data[3], data[4], data[5]);
    }
    return true;
}

void lvgl_touch_read_cb(lv_indev_t *, lv_indev_data_t *data) {
    static uint16_t lastX = 0, lastY = 0;
    uint16_t x, y;
    if (read_raw(x, y)) {
        lastX = x; lastY = y;
        data->point.x = x;
        data->point.y = y;
        data->state = LV_INDEV_STATE_PRESSED;
    } else {
        // Mantem a ultima coordenada no release: o LVGL usa esse ponto para decidir
        // sobre qual objeto o clique terminou.
        data->point.x = lastX;
        data->point.y = lastY;
        data->state = LV_INDEV_STATE_RELEASED;
    }
}

} // namespace

bool touch_available() { return s_available; }
void touch_set_debug(bool enabled) { s_debug = enabled; }
const TouchDiag &touch_diag() { return s_diag; }
void touch_note_card(int idx, bool longPress, bool ignoredEmpty) {
    if (ignoredEmpty) { s_diag.cardIgnoredEmpty++; return; }
    if (idx < 0 || idx >= 8) return;
    if (longPress) s_diag.cardLongs[idx]++;
    else           s_diag.cardClicks[idx]++;
}

bool touch_init() {
    Wire.begin(PIN_TOUCH_SDA, PIN_TOUCH_SCL);
    Wire.setClock(TOUCH_I2C_FREQ);

    Wire.beginTransmission(TOUCH_I2C_ADDR);
    s_available = (Wire.endTransmission() == 0);
    s_diag.available = s_available;

    Serial.printf("[touch] I2C SDA=%d SCL=%d addr=0x%02X -> %s\n",
                  PIN_TOUCH_SDA, PIN_TOUCH_SCL, TOUCH_I2C_ADDR,
                  s_available ? "OK" : "NAO RESPONDEU (UI segue sem toque)");
    if (!s_available) return false;

    lv_indev_t *indev = lv_indev_create();
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, lvgl_touch_read_cb);
    Serial.println("[touch] indev do LVGL registrado");
    return true;
}
