#pragma once
#include "session_model.h"

// Fonte de verdade das sessões exibidas. No MVP é populada com mock e evolui via
// timer local (session_manager_tick); na fase 2, session_transport.h escreve aqui
// a partir do POST /sessions vindo do daemon do PC (ver docs/SPEC.md secção 5).
// Fonte de verdade do dashboard. Producao inicia vazia e so aceita payload real.
// Identidade e persistencia sempre usam SessionData.id, nunca o nome renderizado.
extern SessionData sessions[MAX_SESSIONS];

// Popula `sessions` com dados mockados representativos dos estados suportados.
// Zera os slots; mocks existem apenas na build explicita MONITOR_DEMO_DATA=1.
void session_manager_init();

// Chamado a cada ~1s pelo loop principal: avança elapsedSeconds e, periodicamente,
// alterna o estado de uma sessão — só para provar que a UI reage a mudanças de dado.
// Atualiza exclusivamente a simulacao opt-in da build de demonstracao.
void session_manager_tick();
