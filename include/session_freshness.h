#pragma once
#include <stdint.h>

// Subtracao unsigned preserva o comportamento correto quando millis() faz wrap.
constexpr bool monitor_data_is_fresh(bool hasPayload, uint32_t lastPayloadMillis,
                                     uint32_t now, uint32_t timeoutMillis) {
    return hasPayload && (uint32_t)(now - lastPayloadMillis) <= timeoutMillis;
}

constexpr bool monitor_session_is_stale(bool sourceStale, bool transportFresh) {
    return sourceStale || !transportFresh;
}

constexpr bool monitor_payload_epoch_is_acceptable(uint64_t candidate,
                                                    uint64_t previous,
                                                    uint64_t wallNow,
                                                    uint64_t maxAgeS,
                                                    uint64_t futureSkewS) {
    if (!candidate || (previous && candidate <= previous)) return false;
    if (!wallNow) return true;  // sem NTP: ainda protege ordem/replay apos o primeiro
    if (candidate > wallNow + futureSkewS) return false;
    return candidate + maxAgeS >= wallNow;
}

static_assert(!monitor_data_is_fresh(false, 0, 0, 90), "sem payload nunca e fresh");
static_assert(monitor_data_is_fresh(true, 0xFFFFFFF0u, 0x10u, 0x20u),
              "freshness deve sobreviver ao wrap de millis");
static_assert(monitor_session_is_stale(true, true), "fonte stale vence transporte");
static_assert(monitor_session_is_stale(false, false), "transporte offline invalida sessao");
static_assert(!monitor_payload_epoch_is_acceptable(90, 90, 100, 90, 30),
              "replay nao pode renovar freshness");
static_assert(!monitor_payload_epoch_is_acceptable(200, 0, 100, 90, 30),
              "payload futuro demais deve ser rejeitado");
static_assert(!monitor_payload_epoch_is_acceptable(1, 0, 1000, 90, 30),
              "payload velho deve ser rejeitado");
static_assert(monitor_payload_epoch_is_acceptable(95, 0, 100, 90, 30),
              "payload atual deve ser aceito");
