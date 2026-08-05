# Known Limitations

## 1. Dados historicos

- Ha historico no projeto de investigacao de anomalias em candles e lacunas de dados.
- As datas e hashes exatos dessas investigacoes devem ser confirmados no Git antes de uso como evidencia.
- O dataset confiavel continua sendo um tema critico.

## 2. Testes

- A suite completa pode exceder timeout em alguns ambientes.
- No Windows pode ser necessario redirecionar temporarios para isolamento quando testes especificos pedirem.
- `TMP`, `TEMP` e `TMPDIR` podem precisar ser ajustados em execucoes isoladas.
- Blocos deterministcos devem cobrir todos os testes exatamente uma vez quando houver necessidade de particionamento.
- Warnings conhecidos devem ser registrados, nao escondidos.

## 3. Fase 47

- O executor neutro da Fase 47 esta integrado e versionado em `v0.47.0`.
- A auditoria final foi concluida.
- A suite completa foi consolidada no ambiente padrao.

## 4. Fase 48

- O registro canonico de auditoria da execucao offline da Fase 48 esta integrado e versionado em `v0.48.0`.
- As protecoes cross-platform foram validadas em Windows e Linux no CI.
- Os testes podem ser longos em alguns ambientes, especialmente a validacao da cadeia de fases 45-47.

## 5. Estrategia

- Baseline A e simples e research-only.
- Nao ha prova de edge suficiente para promocao operacional.
- Estrategia B ainda nao esta formalizada.
- Nao ha promocao paper/live.

## 6. Ambiente

- Windows
- possivel warning de `credential-manager-core`
- `PytestCacheWarning`
- limitacoes de symlink
- evitar dependencias POSIX

## 7. Operacional

- sem rede
- sem corretora
- sem ordens
- sem capital real
- sem execucao operacional
