#pragma once

#include <stdint.h>

// Monta o grid 2x3 (6 cards) uma única vez. Chamar após display_init().
void ui_dashboard_init();

// Repassa o conteúdo atual de `sessions[]` (session_manager.h) para os widgets já
// criados — não recria layout, só atualiza texto/cor. Chamar a cada tick do loop.
void ui_dashboard_update();

// Visao ativa do widget unificado (0 = heatmap, 1 = podio) — para o GET /diag.
uint8_t ui_dashboard_usage_view();

// Debug do widget unificado para o /diag: built, x/y da celula de hoje e cor calculada.
void ui_dashboard_usage_debug(int *built, int *x, int *y, uint32_t *color);
void ui_dashboard_usage_debug2(int *heatVisible, int *podioVisible, int *absX, int *absY, uint32_t *realColor, int *cellClickable);
