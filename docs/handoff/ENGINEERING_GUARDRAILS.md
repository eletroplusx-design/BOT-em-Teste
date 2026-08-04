# Engineering Guardrails

## Regras permanentes

1. fail-closed por padrão
2. campos obrigatórios ausentes causam erro
3. recarga nunca preenche silenciosamente campos materiais
4. `bool` não é aceito como inteiro
5. datetime deve ter timezone
6. datetime deve ser normalizado para UTC
7. `NaN` e infinitos são rejeitados
8. serialização não usa `str(obj)` como fallback
9. objetos materiais possuem identidade e hash
10. registros persistidos são append-only
11. escrita deve ser atômica
12. falha de persistência preserva estado anterior
13. mesma entrada deve gerar mesma identidade quando o contrato exigir determinismo
14. rede negada em fases offline
15. corretora negada em fases offline
16. paper negado sem promoção explícita
17. live negado sem promoção explícita
18. ordens negadas sem autorização operacional
19. nenhum backtest positivo promove automaticamente estratégia
20. nenhum teste positivo prova lucratividade
21. PR permanece draft até auditoria
22. CI verde é obrigatório antes do merge
23. merge normal é o padrão adotado
24. tag somente após merge confirmado
25. branch de fase não deve misturar alterações não relacionadas
26. não modificar fase anterior sem necessidade comprovada
27. nenhuma fase recebe poderes além do seu escopo
28. testes não podem ser enfraquecidos para passar
29. skip não pode esconder falha essencial
30. working tree deve terminar limpa

## Regras temporárias

- Baseline A usada apenas como baseline de engenharia
- fixture sintética
- executor neutro antes da estratégia
- sem monitoramento portátil efetivo de memória, se isso ainda for verdade
- sem Estrategia B implementada

## Decisões que podem ser revistas

- limiares operacionais futuros
- formato de snapshot do handoff
- política de monitoramento de memória quando houver implementação portátil confiável
- desenho de uma eventual Estrategia B formalizada
