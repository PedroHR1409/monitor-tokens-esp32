#include "device_time.h"
#include "config.h"
#include <time.h>

namespace {
bool s_synced = false;
// Comeca em 0 de proposito. Se o cache nascesse ja em BRIGHTNESS_DAY, o primeiro
// device_backlight_set(BRIGHTNESS_DAY) seria descartado pelo guard "valor igual" e o
// duty do PWM ficaria em 0 -> tela preta. Foi exatamente esse o bug no bring-up.
uint8_t s_level = 0;
bool s_backlightReady = false;

// A epoca do ESP comeca em 1970; sem NTP o ano fica em 1970. E o teste mais simples
// e confiavel de "ja sincronizou".
bool have_real_time(struct tm &out) {
    time_t now = time(nullptr);
    if (now < 1600000000) return false;      // < 2020 => relogio ainda nao veio
    localtime_r(&now, &out);
    return true;
}
} // namespace

void device_time_init() {
    // configTime ja aplica o offset; a sincronizacao acontece em background.
    configTime(TZ_OFFSET_HOURS * 3600, 0, NTP_SERVER_1, NTP_SERVER_2);
    Serial.printf("[time] NTP solicitado (%s, UTC%+d)\n", NTP_SERVER_1, TZ_OFFSET_HOURS);
}

bool device_time_synced() {
    struct tm t;
    if (have_real_time(t)) {
        if (!s_synced) {
            s_synced = true;
            Serial.printf("[time] sincronizado: %04d-%02d-%02d %02d:%02d local\n",
                          t.tm_year + 1900, t.tm_mon + 1, t.tm_mday, t.tm_hour, t.tm_min);
        }
        return true;
    }
    return false;
}

bool device_time_now(int &hour, int &minute) {
    struct tm t;
    if (!have_real_time(t)) return false;
    hour = t.tm_hour;
    minute = t.tm_min;
    return true;
}

void device_time_clock_str(char *buf, size_t len) {
    int h, m;
    if (device_time_now(h, m)) snprintf(buf, len, "%02d:%02d", h, m);
    else                       snprintf(buf, len, "--:--");
}

uint32_t device_time_local_day() {
    time_t now = time(nullptr);
    if (now < 1600000000) return 0;          // sem NTP nao ha "dia" confiavel
    return (uint32_t)(now / 86400);          // configTime ja deslocou para o fuso local
}

void device_backlight_init() {
    if (PIN_LCD_BACKLIGHT < 0) return;

    // LEDC em vez de digitalWrite: sem PWM nao ha como escurecer a tela a noite.
    if (!ledcAttach(PIN_LCD_BACKLIGHT, BACKLIGHT_PWM_FREQ, BACKLIGHT_PWM_BITS)) {
        // Se o PWM nao anexar, acende no braco: e melhor ter tela sem dim noturno do
        // que um painel preto.
        Serial.println("[light] ledcAttach FALHOU - fallback para digitalWrite(HIGH)");
        pinMode(PIN_LCD_BACKLIGHT, OUTPUT);
        digitalWrite(PIN_LCD_BACKLIGHT, HIGH);
        return;
    }

    s_backlightReady = true;
    // Escrita direta e incondicional: nao passa pelo guard de "valor igual".
    s_level = BRIGHTNESS_DAY;
    ledcWrite(PIN_LCD_BACKLIGHT, BRIGHTNESS_DAY);
    Serial.printf("[light] backlight PWM no pino %d, nivel=%d\n",
                  PIN_LCD_BACKLIGHT, BRIGHTNESS_DAY);
}

void device_backlight_set(uint8_t level) {
    if (!s_backlightReady) return;
    if (level == s_level) return;
    s_level = level;
    ledcWrite(PIN_LCD_BACKLIGHT, level);
}

void device_backlight_apply_schedule() {
    int h, m;
    if (!device_time_now(h, m)) return;      // sem relogio: fica no brilho de dia
    const bool night = (h >= NIGHT_START_HOUR) || (h < NIGHT_END_HOUR);
    device_backlight_set(night ? BRIGHTNESS_NIGHT : BRIGHTNESS_DAY);
}
