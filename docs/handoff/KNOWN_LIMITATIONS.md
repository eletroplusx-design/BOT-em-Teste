# Known Limitations

## Resolvido recentemente

- A multiplicidade redundante de `Unknown` da Fase 53 foi resolvida e integrada em `main` pela PR `#80`.
- O ajuste preserva `known hypotheses` e nao introduz nova fase nem nova tag.

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

## 5. Fase 49

- O registry offline de auditorias de execucao da Fase 49 esta integrado e versionado em `v0.49.0`.
- A cadeia append-only, a metadata material e a regra 1:1 de `execution_attempt_id` foram validadas.
- As regressoes das Fases 41-48 foram executadas com sucesso no ambiente local.

## 6. Fase 50

- O MarketStructureResearchContract da Fase 50 esta integrado e versionado em `v0.50.0`.
- O contrato e declarativo, research-only e profundamente imutavel.
- A metadata material continua sendo parte da identidade canonica e suporta estruturas aninhadas congeladas.
- As regressoes das Fases 38-49 foram executadas com sucesso no ambiente local.

## 7. Fase 51

- O detector offline de estrutura de mercado da Fase 51 esta integrado e versionado em `v0.51.0`.
- A identidade canonica do resultado depende da cadeia de validacao e da ordem canonica dos eventos.
- Look-ahead, ambiguidade e indeterminacao continuam tratados de forma fail-closed.
- As regressoes das Fases 48-50 foram executadas com sucesso no ambiente local.

## 8. Fase 53

- A avaliacao de hipoteses de estrutura de mercado da Fase 53 esta integrada e versionada em `v0.53.0`.
- Hipoteses concorrentes continuam permitidas quando sustentadas por evidencias canonicas diferentes.
- `Unknown` permanece uma saida valida e nao implica sinal, score, probabilidade ou ranking.
- As regressoes das Fases 50-52 foram executadas com sucesso no ambiente local.

## 9. Estrategia

- Baseline A e simples e research-only.
- Nao ha prova de edge suficiente para promocao operacional.
- Estrategia B ainda nao esta formalizada.
- Nao ha promocao paper/live.

## 10. Fase 55

- A Fase 55 esta integrada e versionada em `v0.55.0`.
- A consolidacao estrutural por hipotese preserva absent != neutral, conflito, invalidacao e provenance sem scoring.
- A ausencia de majority voting, signal e promocao operacional permanece obrigatoria.
- As regressoes das Fases 53-54 foram aprovadas no ambiente local.

## 11. Fase 56

- A Fase 56 esta integrada e versionada em `v0.56.0`.
- A validacao temporal entre assessments da Fase 55 preserva identidade deterministica, deep freeze/thaw e rejeicao fail-closed.
- `created_at_utc` permanece fora da identidade canonica.
- Nao ha scoring, signal, replay ou operacao.

## 12. Fase 57

- A Fase 57 esta integrada e versionada em `v0.57.0`.
- A history canonica por hypothesis lineage preserva cadeia linear, append puro, prefix integrity e rejeicao fail-closed de reorder, chain break, duplicate conflict, fork, cycle, self-reference e cross-hypothesis.
- `created_at_utc` permanece fora da identidade canonica.
- Nao ha filesystem, scoring, signal, replay ou operacao.

## 13. Fase 58

- A Fase 58 esta integrada e versionada em `v0.58.0`.
- A persistent structural assessment history preserva save/load/verify canonicos com JSON canonico, atomic write e safe paths.
- `created_at_utc` permanece fora da identidade canonica.
- Nao ha registry, replay, scoring, ranking, signal ou operacao.

## 14. Fase 59

- A Fase 59 esta integrada e versionada em `v0.59.0`.
- A HypothesisTemporalLineage preserva identidade temporal conceitual separada de `hypothesis_id` e `hypothesis_hash`.
- Nao existe persistencia propria da lineage nesta fase.
- Fork e merge globais exigiriam contexto externo adicional; o contrato atual verifica apenas a lineage isolada recebida.
- A semantic key e deterministica, mas pode precisar evoluir se surgirem colisoes semanticas reais em futuro escopo maior.
- O Golden Corpus V3 temporal pode ser retomado com a Fase 59 como contrato de continuidade.

## 15. Fase 60

- A Fase 60 esta integrada, validada empiricamente e versionada em `v0.60.0`.
- O detector local de transicao estrutural nao possui consumidor downstream nesta entrega.
- A validacao empirica cross-asset foi concluida como checkpoint de pesquisa; `UNIUSDT` permaneceu fail-closed sem bug confirmado.
- A integracao com annotations/hypotheses continua sendo uma decisao posterior e foi deferida neste checkpoint.
- `failed_sweep` continua separado.
- A Fase 60 nao deve ser transformada em um segundo classificador global.

## 16. Ambiente

- Windows
- possivel warning de `credential-manager-core`
- `PytestCacheWarning`
- limitacoes de symlink
- evitar dependencias POSIX

## 17. Operacional

- sem rede
- sem corretora
- sem ordens
- sem capital real
- sem execucao operacional
