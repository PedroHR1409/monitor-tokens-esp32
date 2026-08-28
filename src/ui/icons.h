#pragma once
#include <lvgl.h>

// Icones reais (PNG fornecido pelo usuario -> convertido pra formato LVGL). O
// gerador e tools/icon_convert.py (stdlib, sem PIL) e o pipeline e: logo original
// em src/assets/<marca>.png -> 40x40 ARGB8888 centralizado sobre canvas
// transparente -> src/icons/<marca>_icon.c. Ver docs/SPEC.md secao 6.1.
//
// O icone do card e escolhido pelo PROVIDER do modelo (daemon manda "provider" por
// sessao: zai, deepseek...), nao pela ferramenta — GLM no OpenCode mostra a Z.AI,
// nao um icone de CLI. Claude/Codex nao mandam provider e caem no icone classico.
extern const lv_image_dsc_t claude_icon;   // src/assets/claude.png
extern const lv_image_dsc_t gpt_icon;      // src/assets/gpt.png
extern const lv_image_dsc_t zai_icon;      // src/assets/zai.png      (GLM)
extern const lv_image_dsc_t deepseek_icon; // src/assets/deepseek.png (DeepSeek)
