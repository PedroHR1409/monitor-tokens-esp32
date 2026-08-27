#pragma once
#include <Arduino.h>

// =====================================================================================
// PINOS DO PAINEL QSPI (AXS15231B) — placa: Guition JC3248W535C/EN
//
// Confirmado via exemplo oficial (moononournation/Dev_Device_Pins, PINS_JC3248W535.h),
// do mesmo autor da GFX Library for Arduino. Se sua placa for outro modelo/vendedor,
// reconfirme estes valores contra o exemplo dela antes de compilar.
// =====================================================================================
#define PIN_LCD_QSPI_CS   45
#define PIN_LCD_QSPI_SCK  47
#define PIN_LCD_QSPI_D0   21
#define PIN_LCD_QSPI_D1   48
#define PIN_LCD_QSPI_D2   40
#define PIN_LCD_QSPI_D3   39
#define PIN_LCD_RST       -1   // GFX_NOT_DEFINED — sem pino de reset dedicado nesta placa
#define PIN_LCD_BACKLIGHT  1   // GPIO direto (PWM via LEDC — ver brilho/dim abaixo)

// Touch: NAO e GT911 (por isso vem comentado no arquivo de pinos oficial). E o touch
// integrado do proprio AXS15231B, no mesmo I2C, endereco 0x3B.
#define PIN_TOUCH_SDA      4
#define PIN_TOUCH_SCL      8
#define PIN_TOUCH_INT      3
#define TOUCH_I2C_ADDR     0x3B
#define TOUCH_I2C_FREQ     400000UL

// =====================================================================================
// DISPLAY
// =====================================================================================
// Painel e nativamente portrait 320x480, rotacao 0, sem rotacao de software.
#define SCREEN_W          320
#define SCREEN_H          480
#define SCREEN_ROTATION   0

// --- Brilho / dim noturno (LEDC PWM no backlight) ---
#define BACKLIGHT_PWM_FREQ   5000
#define BACKLIGHT_PWM_BITS   8
#define BRIGHTNESS_DAY       255   // 0-255
#define BRIGHTNESS_NIGHT      60
#define NIGHT_START_HOUR      22   // >= 22h  -> escurece
#define NIGHT_END_HOUR         7   // <  7h   -> ainda escuro

// =====================================================================================
// GRID / SESSOES
// =====================================================================================
#define MAX_SESSIONS        6
// Limite apenas de renderizacao. Identidade, selecao e persistencia usam SessionData.id.
// O payload preserva o nome completo; o card mostra uma linha, sem reticencias.
#define NAME_LIMIT          10
// Sem update por esse tempo -> o card e marcado como stale (dado velho). Cobre o daemon
// cair, o PC hibernar ou o WiFi sumir sem o dashboard mentir que o estado ainda vale.
#define STALE_TIMEOUT_MS     90000UL

// =====================================================================================
// REDE
// =====================================================================================
#define WIFI_CONNECT_TIMEOUT_MS  15000UL
#define WIFI_RETRY_INTERVAL_MS   20000UL   // tentativa de reconexao quando cai
#define HTTP_SERVER_PORT         80
#define HTTP_MAX_BODY_BYTES      16384U
#define PAYLOAD_FUTURE_SKEW_S    30ULL
#define MDNS_HOSTNAME             "monitor-ai"   // http://monitor-ai.local

// --- Relogio (NTP) ---
// Necessario para o corte do dia das metricas (00:00-23:59) e para o dim noturno.
#define NTP_SERVER_1     "pool.ntp.org"
#define NTP_SERVER_2     "time.nist.gov"
#define TZ_OFFSET_HOURS  (-3)    // horario de Brasilia

// Dados de demonstracao sao opt-in. A build normal sempre inicia vazia.
#ifndef MONITOR_DEMO_DATA
#define MONITOR_DEMO_DATA 0
#endif
