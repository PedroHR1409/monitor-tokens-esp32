#pragma once
#include <Arduino.h>
#include "session_model.h"   // SeverityLevel, para o pulso de alerta

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

// Define o NIVEL BASE conforme a hora (dia/noite). Nao escreve mais o PWM direto:
// quem escreve e o pulse_tick, que modula em torno deste base. Antes desta mudanca o
// tick de 30s do main.cpp atropelaria qualquer pulso em <=30s.
// Sem NTP, mantem o base de dia.
void device_backlight_apply_schedule();

// Base vigente do horario, para quem precisa saber onde o pulso esta centrado.
uint8_t device_backlight_base();

// Duty efetivo agora (base ou ponto do pulso). Exposto para o GET /diag provar
// o pulso de fora, sem depender de alguem olhando a tela.
uint8_t device_backlight_level();

// Modula o brilho em torno do base conforme a severidade. Chamado a cada
// PULSE_TICK_MS pelo loop principal. Onda triangular em inteiros — sem float, sem
// sin(), sem alocacao — e ZERO chamada LVGL: o alerta nao custa frame nenhum.
void device_backlight_pulse_tick(SeverityLevel severity, uint32_t nowMs);
