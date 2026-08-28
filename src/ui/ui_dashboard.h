#pragma once

// Monta o grid 2x3 (6 cards) uma única vez. Chamar após display_init().
void ui_dashboard_init();

// Repassa o conteúdo atual de `sessions[]` (session_manager.h) para os widgets já
// criados — não recria layout, só atualiza texto/cor. Chamar a cada tick do loop.
void ui_dashboard_update();
