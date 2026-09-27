#pragma once

// Copie para include/secrets.h e substitua somente os valores locais.
// include/secrets.h e ignorado pelo Git e nunca deve ser compartilhado.
#define WIFI_SSID     "NOME_DA_REDE"
#define WIFI_PASSWORD "SENHA_DA_REDE"
// Rede secundaria (opcional). A ordem acima e a prioridade da conexao.
#define WIFI_SSID_2     "NOME_DA_REDE_2"
#define WIFI_PASSWORD_2 "SENHA_DA_REDE_2"
// Curto de proposito: o fallback sem secrets.h nao aceita chamadas autenticadas.
#define MONITOR_API_TOKEN "CONFIGURE"
