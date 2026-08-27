#pragma once
#include <Arduino.h>
#include "session_model.h"

// Conecta ao WiFi (credenciais em include/secrets.h) e sobe o servidor HTTP que recebe
// as atualizacoes do daemon do PC (tools/session_daemon.py). Ver docs/SPEC.md secao 5.
// Nao trava o boot: se o WiFi nao subir a tempo, segue e tenta reconectar em background.
void session_transport_init();

// Chamar a cada iteracao do loop: atende requisicoes e cuida da reconexao do WiFi.
void session_transport_loop();

// Aplica a regra de staleness (STALE_TIMEOUT_MS) marcando cards com dado velho.
void session_transport_mark_stale();

// true somente enquanto o ultimo POST valido ainda esta dentro da janela de freshness.
bool session_transport_has_live_data();

struct TransportDataStatus {
    bool hasPayload;
    bool fresh;
    bool wifiConnected;
    uint32_t ageMillis;
    uint32_t lastPayloadMillis;
    uint32_t lastSuccessfulCommunicationMillis;
    uint64_t lastSuccessfulCommunicationEpoch;
};

// Snapshot da validade do canal. `hasPayload` preserva historico; `fresh` diz se ele
// ainda pode ser apresentado como atual.
TransportDataStatus session_transport_data_status();

// IP atual, ou "sem WiFi". Aparece no heartbeat para nao se perder no log de boot.
String session_transport_ip_string();

// Estatisticas agregadas do ultimo POST (cards de tokens e sparkline).
extern UsageStats usageStats;

// Tempos do ciclo de UI, expostos em GET /diag. Servem para provar (ou refutar) que a
// interface esta mesmo atualizando a cada 1s, em vez de depender de impressao visual.
struct UiDiag {
    uint32_t updates;        // quantos ui_dashboard_update() rodaram
    uint32_t lastUpdateMs;   // duracao do ultimo
    uint32_t maxUpdateMs;    // pior duracao observada
    uint32_t maxGapMs;       // maior intervalo entre dois updates (deveria ficar ~1000)
    uint32_t lastUpdateAtMs; // millis() do ultimo update, para medir o intervalo
    uint32_t lastLvglMs;     // duracao do ultimo lv_timer_handler (render)
    uint32_t maxLvglMs;      // pior duracao do lv_timer_handler
    uint32_t loops;          // iteracoes do loop(): diz se ele gira ou esta bloqueado
    uint32_t maxLoopMs;      // pior iteracao completa
    uint32_t maxTransportMs; // pior session_transport_loop (handleClient pode bloquear)
};
extern UiDiag uiDiag;
