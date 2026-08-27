#pragma once
#include <lvgl.h>

// Ícones reais (PNG fornecido pelo usuário -> convertido pra formato LVGL via
// scripts/LVGLImage.py oficial da própria lib). Ver docs/SPEC.md seção 6.1 pro pipeline
// completo de geração (src/claude.png, src/gpt.png -> processados com transparência e
// recorte via PIL -> src/claude_icon.png, src/gpt_icon.png -> convertidos para
// src/icons/*_icon.c via LVGLImage.py). 40x40px, ARGB8888.
extern const lv_image_dsc_t claude_icon;
extern const lv_image_dsc_t gpt_icon;
