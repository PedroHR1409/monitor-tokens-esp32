#pragma once
#include <Arduino.h>

// Mudo do alerta, armado por toque no header.
//
// Vive na placa porque quem silenciou foi o dedo do operador, no painel — mesmo
// racional do id_list (escondidas/fixadas). O daemon le por GET /snooze e para de
// disparar toast enquanto durar.
//
// O valor que sai daqui e SEMPRE "segundos restantes", nunca um timestamp: os dois
// lados tem relogios independentes e duracao relativa nao tem fuso nem skew. E a
// mesma escolha que a SPEC secao 5 justifica para `elapsed`.
//
// Nao persiste em NVS de proposito: millis() reinicia no boot, e quem religou o
// painel quer ver o estado real, nao um mudo herdado de antes da queda.

void snooze_begin();
void snooze_arm(uint32_t minutes);
void snooze_clear();
bool snooze_active();
uint32_t snooze_remaining_s();
