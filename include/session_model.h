#pragma once
#include <Arduino.h>
#include "config.h"

// Ver docs/SPEC.md secao 3.

enum class ToolType : uint8_t { CLAUDE = 0, CODEX = 1, UNKNOWN = 2 };

// Vocabulario fechado. Ver tools/session_state.py para como cada um e detectado.
enum class SessionState : uint8_t {
    WORK  = 0,  // modelo pensando/executando
    ASK   = 1,  // modelo perguntou (AskUserQuestion) e aguarda resposta
    PERM  = 2,  // aguarda autorizacao para rodar uma tool
    FREE  = 3,  // sessao existe e o modelo esta livre
    IDLE  = 4,  // slot sem sessao
    ERROR_STATE = 5
};

// UUIDs Claude/Codex completos cabem sem truncamento. IDs maiores sao rejeitados no
// transporte em vez de colidirem silenciosamente.
#define SESSION_ID_LEN 64
static_assert(SESSION_ID_LEN > 37, "ID precisa comportar UUID completo e terminador");

struct SessionData {
    char         id[SESSION_ID_LEN];
    char         projectName[24];   // truncado, exibido no card
    char         fullName[40];      // completo, exibido na tela de detalhe
    char         branch[22];        // git branch (detalhe)
    char         model[16];         // modelo em uso (detalhe)
    char         effort[10];        // nivel de esforco do turno (detalhe)
    uint32_t     tokensWindow;      // tokens desta sessao na janela (detalhe)
    uint16_t     ctxPct;            // % da janela de contexto ocupada; >= CTX_ALERT_PCT
                                    // faz o card piscar. 0 = desconhecido. Claude infere
                                    // o teto do historico, Codex le model_context_window.
    ToolType     tool;
    SessionState state;

    // Ancora do contador. O tempo exibido e SEMPRE (millis() - stateStartedAtMillis),
    // nunca um acumulador incrementado a cada refresh: refresh atrasado nao pode virar
    // relogio atrasado. Reancorado so quando o estado (ou a sessao) muda.
    // Ver docs/SPEC.md secao 8.
    uint32_t     stateStartedAtMillis;

    uint32_t     lastUpdateMillis;   // ultimo POST que tocou este slot -> staleness
    uint32_t     sourceAgeSeconds;   // idade da evidencia local no daemon
    bool         occupied;
    bool         sourceStale;        // daemon declarou a evidencia local desatualizada
    bool         stale;              // sourceStale OU transporte sem payload recente
};

// Sessoes que existem no PC mas nao estao no board. Alimentam o seletor que abre ao
// tocar num card vazio, para escolher o que colocar ali.
// 9 = quantas linhas de 38px+6 de gap cabem nos 428px da lista sem cortar a ultima.
#define CATALOG_MAX 9
struct CatalogEntry {
    char     id[SESSION_ID_LEN];
    char     name[26];
    ToolType tool;
    SessionState state;
};
extern CatalogEntry catalog[CATALOG_MAX];
extern uint8_t catalogCount;

// Cota de uso na janela de 5h, um dos dois cards que substituiram o Pomodoro.
//
// Os dois campos NAO tem o mesmo peso e a struct deixa isso explicito. O Codex publica
// `used_percent` no proprio rollout — e o numero que o servidor devolveu, oficial. O
// Claude nao publica cota em lugar nenhum do disco (so um `quotaLimits` que aparece
// DEPOIS de bloquear), entao sobra o consumo somado dos transcripts: `claudeTokens` e
// sempre verdade, e `claudePct` so existe se o usuario declarar o teto do plano em
// MONITOR_CLAUDE_5H_BUDGET. Ver tools/quota.py e docs/SPEC.md secao 15.
struct QuotaStats {
    bool     codexOk;         // achou rate_limits em algum rollout recente
    uint16_t codexH5Pct;      // janela de 300 min — OFICIAL
    uint16_t codexWeekPct;    // janela de 10080 min — OFICIAL
    // Ha quanto tempo essa LEITURA foi feita. Oficial nao quer dizer atual: o rollout
    // so cresce enquanto o Codex CLI roda, e dentro da mesma janela de 5h o percentual
    // anda rapido (medido 37% -> 100% em 3h). Sem expor a idade, o painel exibia com
    // toda a confianca um numero de tres horas atras. Ver docs/SPEC.md secao 16.
    uint32_t codexAgeS;
    char     codexPlan[10];
    bool     claudeOk;
    uint32_t claudeTokens;    // tokens na janela de 5h — ESTIMATIVA de consumo
    uint16_t claudePct;       // 0 = sem teto declarado -> a tela mostra tokens
    uint8_t  windowH;         // horas da janela; o rotulo sai daqui para nunca mentir
};

// Estatisticas agregadas que acompanham o POST /sessions (cards de tokens/sparkline).
#define SPARK_BUCKETS 12
struct UsageStats {
    uint32_t tokensToday;
    uint32_t spark[SPARK_BUCKETS];   // tokens por hora, mais antigo primeiro
    uint8_t  sparkEndHour;           // hora local do ULTIMO balde (0-23); os demais
                                     // sao derivados para tras, um por hora
    uint16_t active12h;              // sessoes com uso real nas ultimas 12h
    uint8_t  tokenWindowH;           // horas da janela de tokens por sessao; o rotulo
                                     // da tela e montado a partir daqui para nunca
                                     // discordar do valor exibido
    uint16_t totalSessions;          // quantas existem no PC (contexto, nao exibido)
    QuotaStats quota;                // cota de 5h dos dois agentes
    bool     valid;
    bool     stale;
    uint32_t lastUpdateMillis;
};
