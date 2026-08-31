# FEATURE: widget-unificado-consumo

> Brief de origem: sessão OpenCode de 28/08/2026 (ECOs `heatmap-consumo-diario` e
> `podio-agentes-modal` do AgentSpec ECO — migradas para o SDD do Luan Moreno).
> Status: aguardando fase BRAINSTORM/DEFINE.

## Ideia original (mensagem do usuário)

"Ao invés dos cards 7, 8, 9, 10 (retângulo), vamos desenvolver um scroll que ocupa o
espaço dos 4 cards. 1. Tela inicial: heatmap estilo GitHub, porém capturando consumo
de tokens em cada dia. Janela de 30 dias, cada dia é um quadrado, cores verdes
exatamente iguais ao GitHub. Nesse caso, pode remover os rótulos, apenas o heatmap.
2. Ao apertar, troca para uma segunda visualização: visão unificada do consumo de cada
agente (Claude, Codex, OpenCode) como um pódio top 3 — o 1º é o que mais gastou. Cada
barra com identificador do agente e rótulo de tokens. Ao clicar na barra, abre um modal
com as sessões ordenadas por gasto. Visualização diária por padrão, com botão para
mudar para 7 dias e 30 dias."

## Restrições do projeto (não negociáveis)

- Ferramentas PC: só stdlib Python (sem pip install)
- Protocolo `POST /sessions`: mudanças aditivas (campo novo, nunca renomear)
- LVGL 9 / ArduinoJson 7 no firmware; área alvo ~304x160 px (portrait 320x480)
- Segredos só em `include/secrets.h`; `tools/check_secrets.py` antes de commit
- Hooks em caminhos estáveis (`tools/session_hook.py` etc.)

## Escopo A — heatmap de consumo diário (30 dias)

- Widget unificado full-width no lugar dos 4 widgets; visão 1 = heatmap 30 dias
- Paleta GitHub dark exata: `#161B22`, `#0E4429`, `#006D32`, `#26A641`, `#39D353`
- Intensidade relativa ao pico da janela (0 / 1-25% / 26-50% / 51-75% / >75%)
- Grid GitHub: colunas = semanas, linhas = dias da semana (~14px, gap 2px), sem rótulos
- Daemon persiste total diário (todas as fontes) em SQLite, retenção ≥ 35 dias,
  sobrevive a restart; prune horário
- Payload: `stats.history.daily` (30 ints, oldest-first) — aditivo; firmware antigo ignora
- Toque alterna visões; escolha do operador sobrevive ao refresh

## Escopo B — pódio de agentes + modal (visão 2)

- Pódio top 3 por consumo no período; rank 1 em destaque (largura/fonte)
- Ícone por provider (GLM→Z.AI, DeepSeek→DeepSeek, fallback por tool) + rótulo tokens
- Chip de período: hoje (padrão) → 7d → 30d, ciclado por toque, à prova de refresh
- Tocar na barra → modal com as sessões do provider ordenadas por gasto (top 6,
  nome truncado 25, estado vazio explícito, fecha no backdrop)
- Payload: `stats.usage.top` aditivo — 3 períodos × 3 providers × (total + 6 sessões);
  total sempre é a soma completa (cap não altera ranking)
- Empate: ordem estável (tie-break por nome); provider zerado aparece com "0"

## Lacuna aceita

Entre a remoção dos cards atuais e a entrega do escopo B, os números de cota
(Codex 5h/semanal, consumo rotativo) ficam fora da tela principal.

## Critérios de aceite (resumo)

1. pytest 100% (incl. novos testes de histórico/agregação); check_secrets limpo
2. pio run OK nos envs `esp32-s3-3v5-lcd` e `-demo`; flash na placa validado
3. Heatmap: paleta bate com GitHub dark; hoje = último quadrado; dias vazios na cor base
4. Toque alterna visões; refresh não reverte visão nem período
5. Pódio: ordem correta por período; modal lista desc. e fecha no backdrop
6. Payload sem campos novos não quebra firmware novo; campos novos não quebram firmware antigo
