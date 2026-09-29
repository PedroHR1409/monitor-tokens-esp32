# BUILD REPORT: correções da revisão geral

## Metadata

| Atributo | Valor |
|---|---|
| Feature | REVIEW_FINDINGS |
| Data | 2026-09-29 |
| Autor | codex |
| Status | Concluído e validado |
| Branch | `fix/project-review-findings` |

## Correções

| Área | Ajuste |
|---|---|
| Wi-Fi | Macros da rede secundária agora são opcionais para `secrets.h` local antigo; SSID vazio não reduz o orçamento de boot. |
| Command Code | Mensagem de transcript posterior ao último hook substitui `free`/`ended` antigo; hooks posteriores, `ask` e `perm` continuam preservados. |
| Pódio histórico | OpenCode e Command Code agrupam também sessões antigas; OpenCode mantém sessões arquivadas no detalhamento histórico. |
| Codex | O diretório passado por `--codex-rollouts` chega aos metadados, histórico diário, séries v2, cota e pódio. |
| Configuração | Fuso, limite de contexto Claude e orçamento Claude agora são consumidos pelo daemon. As variáveis legadas de contexto/cota prevalecem quando definidas. |
| Snooze | Config aceita 0–240 minutos; zero desativa. Firmware aceita zero e preserva o fallback quando o campo não existe. |
| Limite de sessões | CLI e builder limitam `--max-sessions` a 1–6, o que o firmware aceita. |
| Heatmap | Cálculo percentual promove para 64 bits antes da multiplicação. |
| SDD | Status Wi-Fi e validação posterior do histórico horário foram atualizados. |

## Verificação

| Comando | Resultado |
|---|---|
| `python -m pytest tests/ -q` | 309 testes e 36 subtestes aprovados |
| `python -m compileall -q tools tests` | Aprovado |
| `python tools/check_secrets.py` | Aprovado; nenhuma credencial local fora de `include/secrets.h` |
| `git diff --check` | Aprovado |
| `python -m platformio run -e esp32-s3-3v5-lcd` | Aprovado; RAM 38,6%, flash 22,9% |

Compilação e testes cobrem o código e os contratos locais. O comportamento Wi-Fi e o
toque de snooze ainda dependem de validação física na placa.
