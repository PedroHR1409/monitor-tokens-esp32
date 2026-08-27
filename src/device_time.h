#pragma once
#include <Arduino.h>

// Relogio real (NTP) e brilho do painel.
//
// O firmware so tinha millis(), que nao sabe que horas sao nem quando vira o dia. Isso
// e necessario para duas coisas: o corte diario das metricas do dia (00:00-23:59
// no fuso local) e o dim noturno.

void device_time_init();          // dispara a sincronizacao NTP (nao bloqueia o boot)
bool device_time_synced();        // true depois que o NTP respondeu ao menos uma vez

// Preenche hora/minuto locais. Retorna false enquanto o NTP nao sincronizou.
bool device_time_now(int &hour, int &minute);

// "HH:MM" local, ou "--:--" sem sincronia. Buffer com pelo menos 6 bytes.
void device_time_clock_str(char *buf, size_t len);

// Numero do dia local (dias desde a epoca). Muda a meia-noite do fuso configurado —
// e o gatilho para zerar os contadores do dia.
uint32_t device_time_local_day();

// --- Brilho ---
void device_backlight_init();
void device_backlight_set(uint8_t level);   // 0-255
// Aplica dia/noite conforme a hora. Sem NTP, mantem o brilho de dia.
void device_backlight_apply_schedule();
