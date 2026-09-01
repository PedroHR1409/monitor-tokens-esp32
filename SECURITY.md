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
  apenas placeholders.
- **Guard-rail**: `python tools/check_secrets.py` varre o repositório por
  credenciais fora do lugar certo — roda localmente e no CI.
- **Transporte**: o daemon autentica no painel com o header `X-Monitor-Token`
  (comparação constant-time); o servidor rejeita payloads repetidos (anti-replay)
  e corpos acima do limite.
- **Redação**: qualquer saída de log/JSON que possa tocar no token o substitui
  por `***redacted***`.
- **Serviço**: instalado por usuário, sem direitos de administrador, sem tocar em
  diretórios de sistema.

## O que NUNCA fazer

- Commitar `include/secrets.h`, `monitor.toml` ou qualquer credencial real.
- Expor o painel para a internet (port forwarding) — o modelo de segurança é
  rede local confiável.
- Usar o token de exemplo do `secrets.example.h` em produção: gere um token
  longo e aleatório.
