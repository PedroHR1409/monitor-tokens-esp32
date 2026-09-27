# Política de Segurança

## Reportando uma vulnerabilidade

Abra uma issue marcada como `security` **sem detalhes exploráveis** ou entre em
contato direto pelo e-mail do perfil do GitHub. Respondo em até 72h.

## Modelo de ameaças deste projeto

O painel é um dispositivo **local**: o ESP32 fica na sua rede doméstica e o daemon
roda na sua máquina. Não há nuvem, telemetria nem dado que saia da rede local.

## Boas práticas embutidas

- **Segredos**: Wi-Fi e token ficam SOMENTE em `include/secrets.h` e
  `monitor.toml` — ambos gitignored. O exemplo (`secrets.example.h`) contém
  placeholders; o token de fallback é curto para rejeitar autenticação até que
  um token local seja configurado.
- **Guard-rail**: `python tools/check_secrets.py` compara os valores configurados
  em `include/secrets.h` com os arquivos locais. O CI também roda Gitleaks sobre
  o histórico Git; o verificador local informa quando não há segredo local para
  comparar.
- **Transporte**: o daemon autentica no painel com o header `X-Monitor-Token`
  (comparação constant-time); o servidor rejeita payloads repetidos (anti-replay)
  e corpos acima do limite. `/diag` também exige autenticação; `/health` só retorna
  o status do serviço. HTTP não cifra o token, então use apenas em uma rede local
  confiável e nunca exponha a placa à internet.
- **Redação**: qualquer saída de log/JSON que possa tocar no token o substitui
  por `***redacted***`.
- **Serviço**: instalado por usuário, sem direitos de administrador, sem tocar em
  diretórios de sistema.

## O que NUNCA fazer

- Commitar `include/secrets.h`, `monitor.toml` ou qualquer credencial real.
- Expor o painel para a internet (port forwarding) — o modelo de segurança é
  rede local confiável.
- Usar o firmware de fallback sem configurar `include/secrets.h` em produção;
  gere um token longo e aleatório e configure as redes locais.
