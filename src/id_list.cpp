#include "id_list.h"
#include <Preferences.h>
#include <string.h>

namespace {
Preferences prefs;
const char *NVS_NS = "monitorai";
}

// Chaves versionadas: valores antigos continham IDs truncados e nao sao identidades
// validas. Ignora-los evita aplicar hide/pin a outra sessao por colisao de prefixo.
IdList hiddenList("hidden2");
IdList pinnedList("pinned2");

void id_lists_begin() {
    hiddenList.begin();
    pinnedList.begin();
}

void IdList::begin() {
    prefs.begin(NVS_NS, true);
    String raw = prefs.getString(_key, "");
    prefs.end();

    _count = 0;
    int start = 0;
    while (start < (int)raw.length() && _count < IDLIST_MAX) {
        int sep = raw.indexOf(';', start);
        if (sep < 0) sep = raw.length();
        String piece = raw.substring(start, sep);
        if (piece.length()) {
            strncpy(_ids[_count], piece.c_str(), IDLIST_ID_LEN - 1);
            _ids[_count][IDLIST_ID_LEN - 1] = '\0';
            _count++;
        }
        start = sep + 1;
    }
    Serial.printf("[idlist] %s: %u item(ns)\n", _key, _count);
}

void IdList::persist() {
    // Uma string separada por ';' — mais barato em NVS que uma chave por item, e a
    // lista e pequena por definicao.
    char buf[IDLIST_MAX * IDLIST_ID_LEN + 1] = {0};
    for (uint8_t i = 0; i < _count; i++) {
        strncat(buf, _ids[i], sizeof(buf) - strlen(buf) - 2);
        if (i + 1 < _count) strncat(buf, ";", sizeof(buf) - strlen(buf) - 1);
    }
    prefs.begin(NVS_NS, false);
    prefs.putString(_key, buf);
    prefs.end();
}

bool IdList::contains(const char *id) const {
    if (!id || !*id) return false;
    for (uint8_t i = 0; i < _count; i++)
        if (!strcmp(_ids[i], id)) return true;
    return false;
}

void IdList::add(const char *id) {
    if (!id || !*id || strlen(id) >= IDLIST_ID_LEN || contains(id)) return;
    if (_count >= IDLIST_MAX) {
        // Cheia: descarta a mais antiga em vez de recusar o gesto do usuario.
        memmove(_ids[0], _ids[1], IDLIST_ID_LEN * (IDLIST_MAX - 1));
        _count = IDLIST_MAX - 1;
    }
    strncpy(_ids[_count], id, IDLIST_ID_LEN - 1);
    _ids[_count][IDLIST_ID_LEN - 1] = '\0';
    _count++;
    persist();
    Serial.printf("[idlist] %s += %s (total %u)\n", _key, id, _count);
}

void IdList::remove(const char *id) {
    for (uint8_t i = 0; i < _count; i++) {
        if (!strcmp(_ids[i], id)) {
            for (uint8_t j = i; j + 1 < _count; j++)
                memcpy(_ids[j], _ids[j + 1], IDLIST_ID_LEN);
            _count--;
            persist();
            Serial.printf("[idlist] %s -= %s\n", _key, id);
            return;
        }
    }
}

void IdList::clear() {
    _count = 0;
    persist();
    Serial.printf("[idlist] %s limpa\n", _key);
}
