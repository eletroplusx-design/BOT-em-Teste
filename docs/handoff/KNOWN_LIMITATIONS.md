# Known Limitations

## 1. Dados históricos

- Há histórico no projeto de investigação de anomalias em candles e lacunas de dados.
- As datas e hashes exatos dessas investigações devem ser confirmados no Git antes de uso como evidência.
- O dataset confiável continua sendo um tema crítico.

## 2. Testes

- A suíte completa pode exceder timeout.
- No Windows pode ser necessário redirecionar `.pytest_tmp`.
- `TMP`, `TEMP` e `TMPDIR` podem precisar ser ajustados.
- Blocos determinísticos devem cobrir todos os testes exatamente uma vez.
- Warnings conhecidos devem ser registrados, não escondidos.

## 3. Fase 47

- O executor neutro está publicado em branch, mas ainda está em PR draft.
- A auditoria final ainda precisa ser concluída.
- A suíte completa ainda não estava consolidada no momento do snapshot.

## 4. Estratégia

- Baseline A é simples e research-only.
- Não há prova de edge suficiente para promoção operacional.
- Estrategia B ainda não está formalizada.
- Não há promoção paper/live.

## 5. Ambiente

- Windows
- possível warning de `credential-manager-core`
- `PytestCacheWarning`
- limitações de symlink
- evitar dependências POSIX

## 6. Operacional

- sem rede
- sem corretora
- sem ordens
- sem capital real
- sem execução operacional
