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

// Nivel em torno do qual o pulso oscila. Escrito pelo apply_schedule (dia/noite) e
// lido pelo pulse_tick. Separar base de nivel efetivo e o que impede o tick de 30s do
// main.cpp de atropelar o pulso.
uint8_t s_base = BRIGHTNESS_DAY;

// Faixa e periodo de um degrau de severidade. periodMs == 0 significa "nao pulsa".
struct PulseSpec {
    uint16_t periodMs;
    uint8_t  low;
    uint8_t  high;
};

PulseSpec pulse_spec(SeverityLevel severity, uint8_t base) {
    switch (severity) {
        case SeverityLevel::WARNING:
        case SeverityLevel::EXPIRED: {
            const uint8_t delta = (uint8_t)((uint16_t)base * PULSE_WARN_AMPLITUDE_PCT / 100);
            const uint16_t period = (severity == SeverityLevel::EXPIRED)
                                  ? PULSE_EXPIRED_PERIOD_MS : PULSE_WARN_PERIOD_MS;
            const uint16_t high = (uint16_t)base + delta;
            return { period,
                     (uint8_t)(base > delta ? base - delta : 0),
                     (uint8_t)(high > 255 ? 255 : high) };
        }
        case SeverityLevel::CRITICAL:
            // Faixa absoluta, nao derivada do base: aos 23h o base e 60 e um pulso
            // relativo ficaria invisivel justamente no alerta que mais importa.
            return { PULSE_CRIT_PERIOD_MS, PULSE_CRIT_LOW, PULSE_CRIT_HIGH };
        default:
            return { 0, base, base };
    }
}

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
    if (!device_time_now(h, m)) return;      // sem relogio: fica no base de dia
    const bool night = (h >= NIGHT_START_HOUR) || (h < NIGHT_END_HOUR);
    s_base = night ? BRIGHTNESS_NIGHT : BRIGHTNESS_DAY;
}

uint8_t device_backlight_base() {
    return s_base;
}

uint8_t device_backlight_level() {
    return s_level;
}

void device_backlight_pulse_tick(SeverityLevel severity, uint32_t nowMs) {
    const PulseSpec spec = pulse_spec(severity, s_base);
    if (!spec.periodMs) {
        device_backlight_set(s_base);
        return;
    }
    // Onda triangular: sobe na primeira metade do periodo, desce na segunda. Inteiros
    // puros de proposito — float no caminho de um tick de 70ms nao se paga.
    const uint32_t half = spec.periodMs / 2;
    if (!half) { device_backlight_set(spec.high); return; }
    const uint32_t phase = nowMs % spec.periodMs;
    const uint32_t rise = (phase < half) ? phase : (spec.periodMs - phase);
    const uint32_t span = (uint32_t)(spec.high - spec.low);
    // device_backlight_set ja descarta valor repetido, entao o ledcWrite so acontece
    // quando o duty muda de verdade.
    device_backlight_set((uint8_t)(spec.low + (span * rise) / half));
}
