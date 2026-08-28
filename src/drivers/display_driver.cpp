#include "display_driver.h"
#include "config.h"
#include <Arduino.h>
#include <Arduino_GFX_Library.h>
#include <lvgl.h>
#include <esp_heap_caps.h>
#include "device_time.h"

// --- Arduino_GFX: barramento QSPI + painel AXS15231B -----------------------------------
// Pinos vêm de include/config.h (TODO: confirmar antes de compilar — ver comentário lá).
static Arduino_DataBus *bus = new Arduino_ESP32QSPI(
    PIN_LCD_QSPI_CS, PIN_LCD_QSPI_SCK,
    PIN_LCD_QSPI_D0, PIN_LCD_QSPI_D1, PIN_LCD_QSPI_D2, PIN_LCD_QSPI_D3);

// IMPORTANTE: o construtor de 6 argumentos (sem init_operations) usa por padrão a
// sequência de inicialização de OUTRO painel AXS15231B (180x640) — resulta em tela
// preta neste painel 320x480. É preciso passar explicitamente
// axs15231b_320480_type1_init_operations (definida em Arduino_AXS15231B.h), conforme
// o exemplo oficial da Guition JC3248W535 (moononournation/Dev_Device_Pins).
static Arduino_GFX *gfx = new Arduino_AXS15231B(
    bus, PIN_LCD_RST, SCREEN_ROTATION, false /* IPS */,
    SCREEN_W, SCREEN_H,
    0 /* col offset 1 */, 0 /* row offset 1 */, 0 /* col offset 2 */, 0 /* row offset 2 */,
    axs15231b_320480_type1_init_operations, sizeof(axs15231b_320480_type1_init_operations));

// --- LVGL: buffer de tela cheia em PSRAM -------------------------------------------------
// Este painel AXS15231B (QSPI) não lida bem com escritas de área parcial pequena — resulta
// em imagem cortada/deslocada numa faixa estreita da tela (bug real encontrado no bring-up,
// ver docs/SPEC.md seção 8). A correção é sempre mandar o frame inteiro de uma vez
// (LV_DISPLAY_RENDER_MODE_FULL), do mesmo jeito que exemplos funcionais desta placa fazem
// com um Arduino_Canvas por baixo. 320x480x2 bytes = 300KB por buffer — folga grande na
// PSRAM de 8MB, então usamos double-buffer para permitir desenhar o próximo frame enquanto
// o anterior ainda está sendo transferido.
static lv_color_t *draw_buf1 = nullptr;
static lv_color_t *draw_buf2 = nullptr;

static lv_display_t *lvgl_display = nullptr;

// Instrumentacao: separa o custo de DESENHAR (LVGL, software) do custo de TRANSFERIR
// (QSPI). Sem isso nao da para saber qual dos dois esta segurando o loop.
volatile uint32_t g_flushCount = 0;
volatile uint32_t g_flushTotalMs = 0;
volatile uint32_t g_flushMaxMs = 0;

static void lvgl_flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map) {
    const uint32_t w = area->x2 - area->x1 + 1;
    const uint32_t h = area->y2 - area->y1 + 1;

    const uint32_t t0 = millis();
    gfx->draw16bitRGBBitmap(area->x1, area->y1, reinterpret_cast<uint16_t *>(px_map), w, h);
    const uint32_t dt = millis() - t0;
    g_flushCount++;
    g_flushTotalMs += dt;
    if (dt > g_flushMaxMs) g_flushMaxMs = dt;

    lv_display_flush_ready(disp);
}

static uint32_t lvgl_tick_cb() {
    return millis();
}

void display_init() {
    Serial.println("[display] init: iniciando...");
    Serial.printf("[display] pinos QSPI -> CS=%d SCK=%d D0=%d D1=%d D2=%d D3=%d RST=%d BL=%d\n",
                   PIN_LCD_QSPI_CS, PIN_LCD_QSPI_SCK, PIN_LCD_QSPI_D0, PIN_LCD_QSPI_D1,
                   PIN_LCD_QSPI_D2, PIN_LCD_QSPI_D3, PIN_LCD_RST, PIN_LCD_BACKLIGHT);
    Serial.printf("[display] PSRAM: %s, total=%u bytes, livre=%u bytes\n",
                   psramFound() ? "OK" : "NAO ENCONTRADA",
                   (unsigned)ESP.getPsramSize(), (unsigned)ESP.getFreePsram());

    // Backlight ligado antes de qualquer desenho, para não expor o boot "apagado".
    // Se sua placa controlar o backlight por um IO-expander I2C (comum em clones baratos
    // AXS15231B), este pinMode/digitalWrite não faz nada — a tela fica preta mesmo com o
    // resto certo. Ver docs/SPEC.md seção 2.
    // Backlight via LEDC (PWM) em vez de digitalWrite: sem PWM nao havia como
    // escurecer a tela a noite (ver device_time.cpp).
    device_backlight_init();
    Serial.println("[display] backlight PWM inicializado");

    if (!gfx->begin()) {
        Serial.println("[display] ERRO: gfx->begin() falhou — confira os pinos QSPI em config.h");
    } else {
        Serial.println("[display] gfx->begin() OK");
    }
    gfx->fillScreen(0x0000); // preto (RGB565) — GFX Library for Arduino não define macro BLACK
    Serial.println("[display] fillScreen(preto) enviado ao painel");

    lv_init();
    lv_tick_set_cb(lvgl_tick_cb);

    const size_t buf_px = static_cast<size_t>(SCREEN_W) * SCREEN_H; // tela cheia
    draw_buf1 = static_cast<lv_color_t *>(heap_caps_malloc(buf_px * sizeof(lv_color_t), MALLOC_CAP_SPIRAM));
    draw_buf2 = static_cast<lv_color_t *>(heap_caps_malloc(buf_px * sizeof(lv_color_t), MALLOC_CAP_SPIRAM));
    if (!draw_buf1 || !draw_buf2) {
        Serial.println("[display] ERRO: falha ao alocar draw buffers em PSRAM — PSRAM OPI está habilitada no build?");
    } else {
        Serial.println("[display] draw buffers de tela cheia alocados em PSRAM OK");
    }

    lvgl_display = lv_display_create(SCREEN_W, SCREEN_H);
    lv_display_set_flush_cb(lvgl_display, lvgl_flush_cb);
    lv_display_set_buffers(lvgl_display, draw_buf1, draw_buf2,
                            buf_px * sizeof(lv_color_t), LV_DISPLAY_RENDER_MODE_FULL);
    Serial.println("[display] LVGL display criado, init concluído");
}
