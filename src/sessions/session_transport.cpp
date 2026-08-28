#include "session_transport.h"
#include "config.h"
#include "secrets.h"
#include "session_manager.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include <WebServer.h>
#include <ArduinoJson.h>
#include "touch_driver.h"
#include "display_driver.h"
#include "id_list.h"
#include "session_freshness.h"
#include <time.h>

static WebServer server(HTTP_SERVER_PORT);
static bool s_liveDataReceived = false;
static uint32_t s_lastValidPayloadMillis = 0;
static uint32_t s_lastSuccessfulCommunicationMillis = 0;
static uint64_t s_lastSuccessfulCommunicationEpoch = 0;
static uint64_t s_lastPayloadGeneratedEpoch = 0;
UsageStats usageStats = {};
UiDiag uiDiag = {};
CatalogEntry catalog[CATALOG_MAX];
uint8_t catalogCount = 0;

TransportDataStatus session_transport_data_status() {
    const uint32_t now = millis();
    TransportDataStatus status = {};
    status.hasPayload = s_liveDataReceived;
    status.fresh = monitor_data_is_fresh(
        s_liveDataReceived, s_lastValidPayloadMillis, now, STALE_TIMEOUT_MS);
    status.wifiConnected = WiFi.status() == WL_CONNECTED;
    status.ageMillis = s_liveDataReceived ? (uint32_t)(now - s_lastValidPayloadMillis) : 0;
    status.lastPayloadMillis = s_lastValidPayloadMillis;
    status.lastSuccessfulCommunicationMillis = s_lastSuccessfulCommunicationMillis;
    status.lastSuccessfulCommunicationEpoch = s_lastSuccessfulCommunicationEpoch;
    return status;
}

bool session_transport_has_live_data() { return session_transport_data_status().fresh; }

String session_transport_ip_string() {
    if (WiFi.status() != WL_CONNECTED) return "sem WiFi";
    return WiFi.localIP().toString();
}

namespace {

bool constant_time_token_match(const String &provided) {
    const size_t expectedLen = strlen(MONITOR_API_TOKEN);
    const size_t providedLen = provided.length();
    size_t comparedLen = expectedLen > providedLen ? expectedLen : providedLen;
    uint8_t different = (uint8_t)(expectedLen ^ providedLen);
    for (size_t i = 0; i < comparedLen; i++) {
        const uint8_t a = i < expectedLen ? (uint8_t)MONITOR_API_TOKEN[i] : 0;
        const uint8_t b = i < providedLen ? (uint8_t)provided[i] : 0;
        different |= a ^ b;
    }
    return expectedLen >= 16 && different == 0;
}

bool require_auth() {
    if (constant_time_token_match(server.header("X-Monitor-Token"))) return true;
    server.send(401, "application/json", "{\"error\":\"nao autorizado\"}");
    return false;
}

SessionState parse_state(const char *s) {
    if (!strcmp(s, "work")) return SessionState::WORK;
    if (!strcmp(s, "ask"))  return SessionState::ASK;
    if (!strcmp(s, "perm")) return SessionState::PERM;
    if (!strcmp(s, "free")) return SessionState::FREE;
    if (!strcmp(s, "error")) return SessionState::ERROR_STATE;
    return SessionState::IDLE;
}

ToolType parse_tool(const char *s) {
    if (!strcmp(s, "codex"))  return ToolType::CODEX;
    if (!strcmp(s, "claude")) return ToolType::CLAUDE;
    if (!strcmp(s, "opencode")) return ToolType::OPENCODE;
    return ToolType::UNKNOWN;
}

void handle_health() {
    server.send(200, "application/json", "{\"status\":\"ok\"}");
}

// GET /diag — diagnostico do touch e do loop.
// Existe porque validar "um toque REAL gera o evento esperado" olhando o log serial
// exige alguem lendo o monitor no instante do toque. Com estes contadores da para
// confirmar de fora: se `touches` sobe, o driver leu; se `card_clicks` sobe, o evento
// chegou ao objeto certo. Se `touches` sobe e `card_clicks` nao, o problema e mapeamento
// de coordenada ou hit-testing, nao o driver.
void handle_diag() {
    const TouchDiag &t = touch_diag();
    JsonDocument doc;
    JsonObject to = doc["touch"].to<JsonObject>();
    to["available"]   = t.available;
    to["reads"]       = t.reads;
    to["touches"]     = t.touches;
    to["i2c_errors"]  = t.i2cErrors;
    to["short_reads"] = t.shortReads;
    to["last_x"]      = t.lastX;
    to["last_y"]      = t.lastY;
    to["ms_since_touch"] = t.lastTouchMs ? (millis() - t.lastTouchMs) : 0;
    JsonArray raw = to["last_raw"].to<JsonArray>();
    for (uint8_t i = 0; i < 8; i++) raw.add(t.lastRaw[i]);

    JsonArray pts = to["recent"].to<JsonArray>();
    for (uint8_t i = 0; i < t.recentN; i++) {
        JsonObject o = pts.add<JsonObject>();
        o["x"] = t.recentX[i];
        o["y"] = t.recentY[i];
    }
    JsonArray cc = to["card_clicks"].to<JsonArray>();
    JsonArray cl = to["card_longs"].to<JsonArray>();
    for (uint8_t i = 0; i < MAX_SESSIONS; i++) { cc.add(t.cardClicks[i]); cl.add(t.cardLongs[i]); }
    to["card_ignored_empty"] = t.cardIgnoredEmpty;

    JsonObject lo = doc["loop"].to<JsonObject>();
    lo["ui_updates"]     = uiDiag.updates;
    lo["last_update_ms"] = uiDiag.lastUpdateMs;
    lo["max_update_ms"]  = uiDiag.maxUpdateMs;
    lo["max_gap_ms"]     = uiDiag.maxGapMs;
    lo["last_lvgl_ms"]   = uiDiag.lastLvglMs;
    lo["max_lvgl_ms"]    = uiDiag.maxLvglMs;
    lo["flushes"]        = g_flushCount;
    lo["flush_avg_ms"]   = g_flushCount ? (g_flushTotalMs / g_flushCount) : 0;
    lo["flush_max_ms"]   = g_flushMaxMs;
    lo["loops"]          = uiDiag.loops;
    lo["max_loop_ms"]    = uiDiag.maxLoopMs;
    lo["max_transport_ms"] = uiDiag.maxTransportMs;
    lo["uptime_s"]       = millis() / 1000;
    lo["heap"]           = ESP.getFreeHeap();

    const TransportDataStatus dataStatus = session_transport_data_status();
    JsonObject freshness = doc["data"].to<JsonObject>();
    freshness["has_payload"] = dataStatus.hasPayload;
    freshness["fresh"] = dataStatus.fresh;
    freshness["age_ms"] = dataStatus.ageMillis;
    freshness["last_payload_ms"] = dataStatus.lastPayloadMillis;
    freshness["last_success_ms"] = dataStatus.lastSuccessfulCommunicationMillis;
    freshness["last_success_epoch"] = dataStatus.lastSuccessfulCommunicationEpoch;
    freshness["last_payload_epoch"] = s_lastPayloadGeneratedEpoch;
    freshness["wifi_connected"] = dataStatus.wifiConnected;

    String out;
    serializeJson(doc, out);
    server.send(200, "application/json", out);
}

// GET /hidden — sessoes escondidas por toque longo no painel. O daemon le isto antes
// de montar o payload e deixa de enviar essas sessoes, liberando o card para a proxima.
void send_list(const IdList &list, const char *key) {
    JsonDocument doc;
    JsonArray arr = doc[key].to<JsonArray>();
    for (uint8_t i = 0; i < list.count(); i++) arr.add(list.at(i));
    String out;
    serializeJson(doc, out);
    server.send(200, "application/json", out);
}

void handle_hidden() { if (require_auth()) send_list(hiddenList, "hidden"); }

// GET /pinned — sessoes fixadas pelo seletor do painel. O daemon envia essas mesmo que
// estejam fora da janela de 4h, para o card escolhido realmente aparecer.
void handle_pinned() { if (require_auth()) send_list(pinnedList, "pinned"); }

// POST /hidden/clear — volta a exibir tudo (util para desfazer sem mexer no device).
void handle_hidden_clear() {
    if (!require_auth()) return;
    hiddenList.clear();
    server.send(200, "application/json", "{\"status\":\"ok\"}");
}

void handle_pinned_clear() {
    if (!require_auth()) return;
    pinnedList.clear();
    server.send(200, "application/json", "{\"status\":\"ok\"}");
}

// Corpo esperado (ver docs/SPEC.md secao 5):
//   {"sessions":[{"id","project","tool","state","elapsed"}, ...],
//    "stats":{"tokens_today":N,"spark":[12],"total_sessions":N,
//             "quota":{"codex":{"ok","h5_pct","week_pct","plan"},
//                      "claude":{"ok","tokens","pct"}}}}
void handle_sessions_post() {
    if (!require_auth()) return;
    if (!server.hasArg("plain")) {
        server.send(400, "application/json", "{\"error\":\"corpo vazio\"}");
        return;
    }

    // Uma referencia const a UM temporario: `String arg(const String&) const` devolve
    // por valor, entao cada chamada copiava o corpo inteiro. Eram duas copias — uma
    // para o parse, outra so para medir o tamanho.
    const String &body = server.arg("plain");

    // O teto vem ANTES do parse. Media-lo depois de `deserializeJson` era medir o
    // cavalo depois de fechada a porteira: o DOM ja estava alocado, que e justamente
    // a memoria que o limite existe para conter.
    if (body.length() > HTTP_MAX_BODY_BYTES) {
        server.send(413, "application/json", "{\"error\":\"payload muito grande\"}");
        return;
    }

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, body);
    if (err) {
        Serial.printf("[transport] JSON invalido: %s\n", err.c_str());
        server.send(400, "application/json", "{\"error\":\"json invalido\"}");
        return;
    }

    if (!doc["sessions"].is<JsonArray>()) {
        server.send(422, "application/json", "{\"error\":\"sessions ausente\"}");
        return;
    }

    JsonArray arr = doc["sessions"].as<JsonArray>();
    if (arr.size() > MAX_SESSIONS) {
        server.send(422, "application/json", "{\"error\":\"sessoes demais\"}");
        return;
    }
    const char *seenIds[MAX_SESSIONS] = {nullptr};
    size_t seenCount = 0;
    for (JsonVariant item : arr) {
        if (!item.is<JsonObject>()) {
            server.send(422, "application/json", "{\"error\":\"sessao invalida\"}");
            return;
        }
        JsonObject obj = item.as<JsonObject>();
        const char *id = obj["id"] | "";
        const SessionState state = parse_state(obj["state"] | "");
        const ToolType tool = parse_tool(obj["tool"] | "");
        if (!id[0] || strlen(id) >= SESSION_ID_LEN || state == SessionState::IDLE ||
            state == SessionState::ERROR_STATE ||
            tool == ToolType::UNKNOWN ||
            (!obj["elapsed"].isNull() && !obj["elapsed"].is<uint64_t>())) {
            server.send(422, "application/json", "{\"error\":\"campos de sessao invalidos\"}");
            return;
        }
        for (size_t seen = 0; seen < seenCount; seen++) {
            if (!strcmp(seenIds[seen], id)) {
                server.send(422, "application/json", "{\"error\":\"id duplicado\"}");
                return;
            }
        }
        seenIds[seenCount++] = id;
    }

    if (!doc["catalog"].isNull() && !doc["catalog"].is<JsonArray>()) {
        server.send(422, "application/json", "{\"error\":\"catalogo invalido\"}");
        return;
    }
    JsonArray incomingCatalog = doc["catalog"].as<JsonArray>();
    if (incomingCatalog.size() > CATALOG_MAX) {
        server.send(422, "application/json", "{\"error\":\"catalogo grande demais\"}");
        return;
    }
    for (JsonVariant item : incomingCatalog) {
        if (!item.is<JsonObject>()) {
            server.send(422, "application/json", "{\"error\":\"entrada de catalogo invalida\"}");
            return;
        }
        JsonObject entry = item.as<JsonObject>();
        const char *id = entry["id"] | "";
        const SessionState state = parse_state(entry["state"] | "");
        if (!id[0] || strlen(id) >= SESSION_ID_LEN ||
            parse_tool(entry["tool"] | "") == ToolType::UNKNOWN ||
            state == SessionState::IDLE || state == SessionState::ERROR_STATE) {
            server.send(422, "application/json", "{\"error\":\"campos de catalogo invalidos\"}");
            return;
        }
    }
    if (!doc["stats"].isNull() && !doc["stats"].is<JsonObject>()) {
        server.send(422, "application/json", "{\"error\":\"metricas invalidas\"}");
        return;
    }

    if (!doc["generated_at_epoch"].is<uint64_t>()) {
        server.send(422, "application/json", "{\"error\":\"timestamp do payload invalido\"}");
        return;
    }
    const uint64_t generatedEpoch = doc["generated_at_epoch"].as<uint64_t>();
    const time_t wallNowRaw = time(nullptr);
    const uint64_t wallNow = wallNowRaw > 1000000000 ? (uint64_t)wallNowRaw : 0;
    if (!monitor_payload_epoch_is_acceptable(
            generatedEpoch, s_lastPayloadGeneratedEpoch, wallNow,
            STALE_TIMEOUT_MS / 1000ULL, PAYLOAD_FUTURE_SKEW_S)) {
        server.send(409, "application/json", "{\"error\":\"payload stale ou repetido\"}");
        return;
    }

    const uint32_t now = millis();
    int count = 0;
    for (JsonObject obj : arr) {
        if (count >= MAX_SESSIONS) break;
        SessionData &s = sessions[count];

        const char *id      = obj["id"]      | "";
        const char *project = obj["project"] | "?";
        if (!id[0] || strlen(id) >= SESSION_ID_LEN) {
            Serial.println("[transport] sessao ignorada: id ausente ou longo demais");
            continue;
        }
        bool duplicate = false;
        for (int previous = 0; previous < count; previous++) {
            if (!strcmp(sessions[previous].id, id)) { duplicate = true; break; }
        }
        if (duplicate) {
            Serial.println("[transport] sessao duplicada ignorada");
            continue;
        }
        const SessionState newState = parse_state(obj["state"] | "free");
        uint64_t elapsedRaw = obj["elapsed"] | 0ULL;
        const uint32_t elapsed = elapsedRaw > UINT32_MAX / 1000ULL
            ? UINT32_MAX / 1000UL : (uint32_t)elapsedRaw;

        // Reancorar o contador SO quando a sessao ou o estado mudam. Se reancorasse a
        // cada POST, o contador daria pequenos saltos para tras/frente a cada ciclo por
        // causa do arredondamento do daemon; ancorando uma vez, ele corre liso entre
        // os POSTs. Ver docs/SPEC.md secao 8.
        const bool sameSession = s.occupied && !strcmp(s.id, id);
        if (!sameSession || s.state != newState) {
            s.stateStartedAtMillis = now - elapsed * 1000UL;
        }

        strncpy(s.id, id, sizeof(s.id) - 1);
        s.id[sizeof(s.id) - 1] = '\0';
        strncpy(s.projectName, project, sizeof(s.projectName) - 1);
        s.projectName[sizeof(s.projectName) - 1] = '\0';

        // Campos exibidos apenas na tela de detalhe (nao cabem no card de 96px).
        strncpy(s.fullName, obj["full"] | project, sizeof(s.fullName) - 1);
        s.fullName[sizeof(s.fullName) - 1] = '\0';
        strncpy(s.branch, obj["branch"] | "", sizeof(s.branch) - 1);
        s.branch[sizeof(s.branch) - 1] = '\0';
        strncpy(s.model, obj["model"] | "", sizeof(s.model) - 1);
        s.model[sizeof(s.model) - 1] = '\0';
        strncpy(s.effort, obj["effort"] | "", sizeof(s.effort) - 1);
        s.effort[sizeof(s.effort) - 1] = '\0';
        strncpy(s.provider, obj["provider"] | "", sizeof(s.provider) - 1);
        s.provider[sizeof(s.provider) - 1] = '\0';
        s.tokensWindow = obj["tokensWin"] | 0UL;
        s.ctxPct       = obj["ctxPct"] | 0U;

        s.tool  = parse_tool(obj["tool"] | "");
        s.state = newState;
        s.lastUpdateMillis = now;
        s.sourceAgeSeconds = obj["source_age_s"] | elapsed;
        s.occupied = true;
        s.sourceStale = obj["source_stale"] | false;
        s.stale = s.sourceStale;
        count++;
    }
    // Slots ausentes nesta atualizacao = sessao encerrada no PC -> card volta a vazio.
    for (int i = count; i < MAX_SESSIONS; i++) sessions[i].occupied = false;

    JsonArray cat = doc["catalog"].as<JsonArray>();
    catalogCount = 0;
    for (JsonObject o : cat) {
        if (catalogCount >= CATALOG_MAX) break;
        const char *catalogId = o["id"] | "";
        if (!catalogId[0] || strlen(catalogId) >= SESSION_ID_LEN) continue;
        CatalogEntry &e = catalog[catalogCount];
        strncpy(e.id, catalogId, sizeof(e.id) - 1);
        e.id[sizeof(e.id) - 1] = 0;
        strncpy(e.name, o["name"] | "?", sizeof(e.name) - 1);
        e.name[sizeof(e.name) - 1] = 0;
        strncpy(e.provider, o["provider"] | "", sizeof(e.provider) - 1);
        e.provider[sizeof(e.provider) - 1] = 0;
        e.tool  = parse_tool(o["tool"] | "");
        e.state = parse_state(o["state"] | "free");
        catalogCount++;
    }

    JsonObject st = doc["stats"].as<JsonObject>();
    if (!st.isNull()) {
        usageStats.tokensToday   = st["tokens_today"]   | 0UL;
        usageStats.active12h     = st["active_12h"]     | 0;
        usageStats.sparkEndHour  = st["spark_end_hour"] | 0;
        usageStats.tokenWindowH  = st["token_window_h"] | 12;
        usageStats.totalSessions = st["total_sessions"] | 0;
        JsonArray spark = st["spark"].as<JsonArray>();
        int i = 0;
        for (JsonVariant v : spark) {
            if (i >= SPARK_BUCKETS) break;
            usageStats.spark[i++] = v.as<uint32_t>();
        }
        for (; i < SPARK_BUCKETS; i++) usageStats.spark[i] = 0;

        // Cota: bloco opcional. Se o daemon for antigo (ou a leitura local falhar) os
        // flags ficam false e os cards mostram "--" em vez de um zero que passaria por
        // "voce nao usou nada" — que e justamente a leitura errada.
        QuotaStats &q = usageStats.quota;
        q = QuotaStats{};
        JsonObject qt = st["quota"].as<JsonObject>();
        if (!qt.isNull()) {
            q.windowH = qt["window_h"] | 5;
            JsonObject cx = qt["codex"].as<JsonObject>();
            if (!cx.isNull()) {
                q.codexOk      = cx["ok"] | false;
                q.codexH5Pct   = cx["h5_pct"]   | 0;
                q.codexWeekPct = cx["week_pct"] | 0;
                q.codexAgeS    = cx["age_s"]    | 0UL;
                strncpy(q.codexPlan, cx["plan"] | "", sizeof(q.codexPlan) - 1);
                q.codexPlan[sizeof(q.codexPlan) - 1] = 0;
            }
            JsonObject cl = qt["claude"].as<JsonObject>();
            if (!cl.isNull()) {
                q.claudeOk     = cl["ok"] | false;
                q.claudeTokens = cl["tokens"] | 0UL;
                q.claudePct    = cl["pct"]    | 0;
            }
        }

        usageStats.valid = true;
        usageStats.stale = false;
        usageStats.lastUpdateMillis = now;
    }

    s_liveDataReceived = true;
    s_lastValidPayloadMillis = now;
    s_lastSuccessfulCommunicationMillis = now;
    s_lastPayloadGeneratedEpoch = generatedEpoch;
    if (wallNow) s_lastSuccessfulCommunicationEpoch = wallNow;
    server.send(200, "application/json", "{\"status\":\"ok\"}");
}

} // namespace

void session_transport_init() {
    Serial.println("[transport] conectando ao WiFi...");
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_CONNECT_TIMEOUT_MS) {
        delay(250);
        Serial.print(".");
    }
    Serial.println();

    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[transport] nao conectou agora (confira include/secrets.h) — "
                       "vai continuar tentando em background");
    } else {
        Serial.printf("[transport] WiFi OK, IP=%s\n", WiFi.localIP().toString().c_str());
        if (MDNS.begin(MDNS_HOSTNAME)) {
            MDNS.addService("http", "tcp", HTTP_SERVER_PORT);
            Serial.printf("[transport] mDNS: http://%s.local\n", MDNS_HOSTNAME);
        }
    }

    server.on("/health", HTTP_GET, handle_health);
    server.on("/sessions", HTTP_POST, handle_sessions_post);
    server.on("/diag", HTTP_GET, handle_diag);
    server.on("/hidden", HTTP_GET, handle_hidden);
    server.on("/hidden/clear", HTTP_POST, handle_hidden_clear);
    server.on("/pinned", HTTP_GET, handle_pinned);
    server.on("/pinned/clear", HTTP_POST, handle_pinned_clear);
    const char *authHeaders[] = {"X-Monitor-Token"};
    server.collectHeaders(authHeaders, 1);
    server.begin();
    Serial.printf("[transport] HTTP na porta %d\n", HTTP_SERVER_PORT);
}

void session_transport_loop() {
    server.handleClient();

    // Reconexao: sem isso, uma queda de WiFi deixava o painel mudo ate reiniciar na mao.
    static uint32_t lastRetry = 0;
    static bool wasConnected = true;
    const uint32_t now = millis();

    if (WiFi.status() != WL_CONNECTED) {
        if (wasConnected) {
            wasConnected = false;
            Serial.println("[transport] WiFi caiu — tentando reconectar");
        }
        if (now - lastRetry >= WIFI_RETRY_INTERVAL_MS) {
            lastRetry = now;
            WiFi.disconnect();
            WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
        }
    } else if (!wasConnected) {
        wasConnected = true;
        Serial.printf("[transport] WiFi reconectado, IP=%s\n", WiFi.localIP().toString().c_str());
        MDNS.begin(MDNS_HOSTNAME);   // o servico se perde no reconnect
        MDNS.addService("http", "tcp", HTTP_SERVER_PORT);
    }
}

void session_transport_mark_stale() {
    const uint32_t now = millis();
    const bool transportFresh = monitor_data_is_fresh(
        s_liveDataReceived, s_lastValidPayloadMillis, now, STALE_TIMEOUT_MS);
    for (int i = 0; i < MAX_SESSIONS; i++) {
        SessionData &s = sessions[i];
        if (!s.occupied) continue;
        const bool slotFresh = (uint32_t)(now - s.lastUpdateMillis) <= STALE_TIMEOUT_MS;
        s.stale = monitor_session_is_stale(s.sourceStale,
                                           transportFresh && slotFresh);
    }
    if (usageStats.valid) {
        const bool statsFresh = (uint32_t)(now - usageStats.lastUpdateMillis)
                                <= STALE_TIMEOUT_MS;
        usageStats.stale = !(transportFresh && statsFresh);
    }
}
