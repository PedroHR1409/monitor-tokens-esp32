#include <Arduino.h>
#include <lvgl.h>
#include "display_driver.h"
#include "device_time.h"
#include "id_list.h"
#include "session_manager.h"
#include "session_transport.h"
#include "touch_driver.h"
#include "ui_dashboard.h"

static uint32_t lastUiTick = 0;
static uint32_t lastSlowTick = 0;
static uint32_t lastHeartbeat = 0;

void setup() {
    Serial.begin(115200);
    uint32_t waitStart = millis();
    while (!Serial && millis() - waitStart < 3000) delay(10);

    Serial.println();
    Serial.println("=== Monitor.AI ===");

    display_init();
    touch_init();               // segue sem toque se o controlador nao responder
    session_manager_init();
    id_lists_begin();
    session_transport_init();
    device_time_init();         // NTP: precisa do WiFi ja iniciado
    ui_dashboard_init();

    Serial.println("[main] setup concluido");
}

void loop() {
    const uint32_t loopT0 = millis();
    uiDiag.loops++;
    const uint32_t lvT0 = millis();
    lv_timer_handler();
    const uint32_t lvDt = millis() - lvT0;
    if (lvDt > uiDiag.maxLvglMs) uiDiag.maxLvglMs = lvDt;
    uiDiag.lastLvglMs = lvDt;
    const uint32_t trT0 = millis();
    session_transport_loop();
    const uint32_t trDt = millis() - trT0;
    if (trDt > uiDiag.maxTransportMs) uiDiag.maxTransportMs = trDt;

    const uint32_t now = millis();

    // UI a 1Hz. Nenhum valor de tempo e contado aqui: os cards derivam tudo do relogio
    // (millis() - ancora), entao um refresh atrasado nao vira relogio atrasado.
    //
    // A cadencia avanca em passos fixos de 1000ms em vez de `lastUiTick = now`: com
    // `= now` o overshoot de cada iteracao era descartado e os updates iam escorregando
    // (1,0s, 1,2s, 1,4s...), o que aparecia como o valor "andando em blocos". Se atrasar
    // demais (> 3 ciclos), ressincroniza em vez de tentar recuperar todos de uma vez.
    if (now - lastUiTick >= 1000) {
        lastUiTick += 1000;
        if (now - lastUiTick > 3000) lastUiTick = now;

        const uint32_t gap = now - uiDiag.lastUpdateAtMs;
        if (uiDiag.lastUpdateAtMs && gap > uiDiag.maxGapMs) uiDiag.maxGapMs = gap;
        uiDiag.lastUpdateAtMs = now;

        const uint32_t t0 = millis();
        session_transport_mark_stale();
        ui_dashboard_update();
        uiDiag.lastUpdateMs = millis() - t0;
        if (uiDiag.lastUpdateMs > uiDiag.maxUpdateMs) uiDiag.maxUpdateMs = uiDiag.lastUpdateMs;
        uiDiag.updates++;
    }

    // Tarefas de baixa frequencia.
    if (now - lastSlowTick >= 30000) {
        lastSlowTick = now;
        device_time_synced();
        device_backlight_apply_schedule();
    }

    if (now - lastHeartbeat >= 30000) {
        lastHeartbeat = now;
        const TransportDataStatus dataStatus = session_transport_data_status();
        Serial.printf("[main] t=%lus heap=%u IP=%s data=%s age=%lums touch=%s\n",
                      (unsigned long)(now / 1000), (unsigned)ESP.getFreeHeap(),
                      session_transport_ip_string().c_str(),
                      dataStatus.fresh ? "fresh" : dataStatus.hasPayload ? "stale" : "vazio",
                      (unsigned long)dataStatus.ageMillis,
                      touch_available() ? "ok" : "off");
    }

    const uint32_t loopDt = millis() - loopT0;
    if (loopDt > uiDiag.maxLoopMs) uiDiag.maxLoopMs = loopDt;

    delay(5);
}
