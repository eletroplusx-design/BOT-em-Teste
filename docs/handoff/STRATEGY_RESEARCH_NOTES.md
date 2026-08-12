# Strategy Research Notes

## 1. Baseline A — implementada

Arquivo: [strategies/baseline_a_okx_btc_usdt_research.py](../../strategies/baseline_a_okx_btc_usdt_research.py)

### Regra real observada no código

- Mercado: OKX spot BTC-USDT
- Intervalo: `1H`
- Direção: long only
- Indicadores: EMA20, EMA50, EMA200, ATR14
- Histórico mínimo: 201 candles
- Alinhamento: EMA50 > EMA200
- Reforço de tendência: close > EMA200 e EMA50 crescente
- Pullback: mínima toca EMA20 nos últimos 3 candles
- Confirmação: close atual > EMA20 e close atual > máxima anterior
- Entrada: close atual
- Stop: entrada - 1,5 ATR
- Alvo: entrada + 2 vezes o risco
- Saídas de decisão: `long_setup_detected` e `no_setup`

### Garantias

- research-only
- sem paper
- sem live
- sem ordens
- usada como controle de engenharia
- não é uma estratégia profissional final

## 2. Estrategia B — ainda não implementada

Conceitos discutidos:

- estrutura de mercado
- liquidez
- POI 1-2-3
- rompimento de microtopo ou microfundo
- deslocamento
- mitigação
- CHoCH
- BOS
- FVG
- sessões
- Wyckoff
- acumulação
- distribuição
- SC
- BC
- AR
- ST
- Spring
- UT
- UTAD
- LPS
- LPSY
- teste após Spring ou UTAD

Definição discutida de POI:

```text
O POI não é simplesmente uma zona antiga de oferta ou demanda.

No modelo discutido, o POI nasce de uma sequência estrutural 1-2-3 em que
o preço rompe ou toma a liquidez do extremo oposto relevante e depois
retoma a direção principal.
```

Esses conceitos ainda não constituem uma especificação programável completa.
Não implementar a Estrategia B sem regras objetivas, exemplos, invalidações, testes e critérios de aceitação.

## 3. Wyckoff

- ST pode aparecer perto do fundo em acumulação.
- ST pode aparecer perto do topo em distribuição.
- Primeiro ST costuma ajudar a encerrar Fase A.
- Múltiplos STs podem aparecer na Fase B.
- Na Fase C, movimentos de teste normalmente recebem nomes mais específicos.
- Não marcar todo toque como ST.
- Contexto e evento testado são obrigatórios.

## 4. Regra de ouro

Nenhuma observação discricionária deve ser convertida em código sem uma especificação objetiva e testável.
