#pragma once
#include <Arduino.h>

// Inicializa o painel (Arduino_GFX sobre QSPI) e o LVGL (buffers em PSRAM, flush, tick).
// Deve ser chamado uma vez em setup(), antes de montar qualquer tela LVGL.
void display_init();

// Custo da transferencia QSPI (preenchido pelo flush do LVGL), exposto em GET /diag.
extern volatile uint32_t g_flushCount;
extern volatile uint32_t g_flushTotalMs;
extern volatile uint32_t g_flushMaxMs;
