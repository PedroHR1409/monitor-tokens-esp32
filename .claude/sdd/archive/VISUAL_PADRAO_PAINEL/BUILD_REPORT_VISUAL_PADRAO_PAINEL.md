# BUILD REPORT: VISUAL_PADRAO_PAINEL

| Attribute | Value |
|-----------|-------|
| **Data** | 2026-08-31 |
| **Executor** | build-agent (via OpenCode) |
| **Status** | ✅ Shipped |

## Implementado

1. Card 7: gap 2px estilo GitHub (células 37x32, pitch 39x34, centralizadas);
   seta em container dedicado com símbolo centralizado (lv_obj_center);
   inspeção com fundo padrão do card (sem tonalidade verde); título
   CONSUMO DE TOKENS (EM MM).
2. Pódio em colunas 2º|1º|3º (altura por rank 120/88/64), degrade L4/L3/L2,
   rótulo centralizado acima da barra (ícone removido a pedido do operador),
   nome do agente abaixo.
3. Valores em MM com vírgula e sem sufixo (`uw_tokens_str`), unidade no título.
4. Nomenclatura OpenCode: `_project_name` prioriza basename(directory).

## Correções de percurso

- Janela de contexto por modelo (GLM ~1M — 584k tokens exibidos como 58% no
  OpenCode; deepseek 128k; override por config).
- Pódio sem ícone (descentralização relatada pelo operador).
- `pending` de tool é estado de pipeline, não permissão (falso "perm" medido).

## Verificação

- 198 testes; compileall; check_secrets; pio run; flash COM3; validação visual
  do operador (fotos da placa confirmaram os 3 blocos de AC).
