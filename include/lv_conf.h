// Config mínima do LVGL 9.2.x para este projeto.
// Macros não definidas aqui caem no default de lv_conf_internal.h — não é necessário
// (nem recomendado) copiar o lv_conf_template.h inteiro para um MVP deste tamanho.
#pragma once

#define LV_COLOR_DEPTH        16
// Bug real de bring-up: com valor 1, cores saem trocadas (preto quase puro -> rosa pastel,
// âmbar -> magenta) — ver docs/SPEC.md seção 8. Arduino_GFX já lida com a ordem de bytes
// certa para o barramento QSPI internamente, então aqui tem que ser 0.
#define LV_COLOR_16_SWAP       0

// Heap interno do LVGL (widgets, estilos) — 6 cards simples cabem folgado em 64KB.
#define LV_MEM_SIZE            (64U * 1024U)

// Log útil durante o bring-up; reduza para LV_LOG_LEVEL_WARN depois de validar.
#define LV_USE_LOG              1
#define LV_LOG_LEVEL             LV_LOG_LEVEL_INFO
#define LV_LOG_PRINTF            1

// Fontes usadas nos cards (nome do projeto, badge de estado, header).
#define LV_FONT_MONTSERRAT_12   1   // rotulos do heatmap (hora / tokens)
#define LV_FONT_MONTSERRAT_14   1
#define LV_FONT_MONTSERRAT_16   1
#define LV_FONT_MONTSERRAT_20   1
#define LV_FONT_DEFAULT         &lv_font_montserrat_14

#define LV_USE_FLEX              1
#define LV_USE_GRID               1
