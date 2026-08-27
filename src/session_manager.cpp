#include "session_manager.h"
#include <Arduino.h>
#include <string.h>

SessionData sessions[MAX_SESSIONS];

namespace {
#if MONITOR_DEMO_DATA
void set_session(int idx, const char *id, const char *name, ToolType tool,
                 SessionState state, uint32_t elapsed) {
    SessionData &s = sessions[idx];
    strncpy(s.id, id, sizeof(s.id) - 1);
    s.id[sizeof(s.id) - 1] = '\0';
    strncpy(s.projectName, name, sizeof(s.projectName) - 1);
    s.projectName[sizeof(s.projectName) - 1] = '\0';
    s.tool = tool;
    s.state = state;
    // Mesmo esquema de ancora dos dados reais: o mock nao incrementa contador nenhum,
    // so define quando o estado comecou. Ver docs/SPEC.md secao 8.
    s.stateStartedAtMillis = millis() - elapsed * 1000UL;
    s.lastUpdateMillis = millis();
    s.sourceAgeSeconds = elapsed;
    s.occupied = true;
    s.sourceStale = false;
    s.stale = false;
}
#endif
} // namespace

void session_manager_init() {
    memset(sessions, 0, sizeof(sessions));
#if MONITOR_DEMO_DATA
    // Somente a build de demo explicita cobre os quatro estados visuais.
    set_session(0, "mock-01", "monitor-tokens-esp32", ToolType::CLAUDE, SessionState::WORK, 12);
    set_session(1, "mock-02", "lakehouse-fabric",     ToolType::CODEX,  SessionState::PERM, 45);
    set_session(2, "mock-03", "curso-ia",             ToolType::CLAUDE, SessionState::ASK, 8);
    set_session(3, "mock-04", "api-refactor",         ToolType::CODEX,  SessionState::FREE, 900);
    set_session(4, "mock-05", "docs-writer",          ToolType::CLAUDE, SessionState::FREE, 3600);
#endif
}

void session_manager_tick() {
    // Sem trabalho: nao ha contador para incrementar. O tempo exibido e derivado de
    // stateStartedAtMillis na hora de desenhar, entao nao existe deriva possivel.
    // Reservada para uma futura simulacao exclusiva da build de demo.
}
