#pragma once
#include <Arduino.h>
#include "session_model.h"

// Lista pequena de ids de sessao persistida em NVS.
//
// Serve para os dois lados do controle manual do board, que sao simetricos:
//   * escondidas (toque longo)  -> o daemon para de enviar
//   * fixadas    (seletor)      -> o daemon envia mesmo fora da janela de 4h
// Generalizado para nao ter duas copias da mesma logica de NVS/parsing.

#define IDLIST_MAX 12
#define IDLIST_ID_LEN SESSION_ID_LEN

class IdList {
public:
    explicit IdList(const char *nvsKey) : _key(nvsKey), _count(0) {}

    void begin();                       // carrega da NVS
    bool contains(const char *id) const;
    void add(const char *id);           // idempotente; persiste
    void remove(const char *id);        // persiste
    void clear();
    uint8_t count() const { return _count; }
    const char *at(uint8_t i) const { return i < _count ? _ids[i] : ""; }

private:
    void persist();
    const char *_key;
    char _ids[IDLIST_MAX][IDLIST_ID_LEN];
    uint8_t _count;
};

extern IdList hiddenList;   // sessoes escondidas por toque longo
extern IdList pinnedList;   // sessoes fixadas pelo seletor
void id_lists_begin();
