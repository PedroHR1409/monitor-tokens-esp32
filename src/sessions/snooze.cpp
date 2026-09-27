#include "snooze.h"

namespace {
// millis() alvo. 0 = sem mudo. Guardado como instante, nao como contador
// decrescente: contador decrementado a cada tick vira relogio errado quando um tick
// atrasa, e o painel ja aprendeu isso no timer dos cards (docs/SPEC.md secao 8).
uint32_t s_untilMs = 0;
}

void snooze_begin() {
    s_untilMs = 0;
}

void snooze_arm(uint32_t minutes) {
    if (!minutes) { s_untilMs = 0; return; }
    const uint32_t target = millis() + minutes * 60000UL;
    // millis() rola a cada ~49 dias. Alvo 0 depois da soma seria lido como "sem mudo",
    // entao empurra 1ms: erro de 1ms uma vez por 49 dias, contra um mudo que nao arma.
    s_untilMs = target ? target : 1;
}

void snooze_clear() {
    s_untilMs = 0;
}

uint32_t snooze_remaining_s() {
    if (!s_untilMs) return 0;
    // Diferenca com sinal em vez de comparar `now < until`: e a unica forma de a conta
    // sobreviver ao rollover de millis().
    const int32_t left = (int32_t)(s_untilMs - millis());
    if (left <= 0) { s_untilMs = 0; return 0; }
    return (uint32_t)left / 1000UL;
}

bool snooze_active() {
    return snooze_remaining_s() > 0;
}
