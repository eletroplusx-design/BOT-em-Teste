# Phase History

## Fases 9A, 9B, 9C e 10A

Status:
- integrada

Branch:
- Não confirmado

PR:
- Não confirmado

Commit principal:
- Não confirmado

Merge commit:
- Não confirmado

Tag:
- `v0.9.0-trusted-historical-data`
- `v0.9.1-historical-replay-validation`
- `v0.9.2-historical-experiment-contract`
- `v0.10.0-baseline-trend-pullback`

Arquivos principais:
- contratos históricos iniciais e base da pesquisa

Objetivo:
- estabelecer dados históricos confiáveis, validação de replay e a primeira baseline trend/pullback

Garantias introduzidas:
- pesquisa histórica confiável
- primeiros contratos e validações

O que deliberadamente não foi implementado:
- paper live
- execução operacional
- promoção automática

Testes ou validações relevantes:
- validações históricas iniciais

Limitações conhecidas:
- detalhes finos de branch/PR não confirmados neste snapshot

## Fases 11–22

Status:
- integrada

Branch:
- Não confirmado

PR:
- Não confirmado

Commit principal:
- Não confirmado

Merge commit:
- Não confirmado

Tag:
- `v0.11.0-historical-provider-qualification`
- `v0.11.1-kucoin-spot-historical-provider`
- `v0.12.0-kucoin-multitimeframe-qualification`
- `v0.12.1-historical-multitimeframe-alignment`
- demais fases 13–22: ver histórico Git local para confirmação fina

Arquivos principais:
- provedores históricos
- validações de múltiplos timeframes
- análises e experimentos

Objetivo:
- ampliar a infraestrutura de dados e pesquisa sem promoção operacional

Garantias introduzidas:
- providers históricos
- alinhamento multi-timeframe

O que deliberadamente não foi implementado:
- operação ao vivo
- promoção automática

Testes ou validações relevantes:
- regressões históricas e validações de contrato

Limitações conhecidas:
- sequência exata de branches/PRs das fases 13–22 requer consulta adicional se necessária

## Fase 24 — rastreamento auditável dos gates entre sinal e trade simulado

Status:
- integrada

Tag:
- `v0.26.0` é a base posterior de referência do subciclo atual

Objetivo:
- rastrear os gates entre sinal e trade simulado

Garantias introduzidas:
- rastreamento dos gates
- base para o diagnóstico posterior

## Fase 26 — diagnóstico histórico da divergência entre setup e Signal

Status:
- integrada

Branch:
- `codex/phase-26-signal-gap-diagnostic-research`

PR:
- `#51`

Commit principal:
- `1cc3ca9b01568b4c91cf0d2dc51cc878beb79624` é a base congelada anterior ao bloco posterior

Objetivo:
- diagnosticar divergências entre setup e Signal

Garantias introduzidas:
- diagnóstico histórico
- contagem de gates e warm-up

## Fase 30 — correção da confiabilidade do diagnóstico setup → Signal

Status:
- integrada

Branch:
- `codex/phase-30-signal-gap-diagnostic-parity`

PR:
- `#52`

Commit principal:
- `274a9c2c20f1e1d37390ecfa8379ed2dfd7f1e0b`

Merge commit:
- `093726c9406f01a4b14fa95dd42796664a0e39a1`

Tag:
- `v0.26.0` permanece a base histórica de referência do bloco

Objetivo:
- alinhar o diagnóstico histórico com a Baseline A sem alterar a estratégia

Garantias introduzidas:
- warm-up alinhado
- gates com `passed`, `failed` e `not_reached`
- regressão para não contar gate não alcançado como pass

## Fase 34 — resolvedor seguro de artefato histórico persistente

Status:
- integrada

Branch:
- `codex/phase-34-safe-persistent-artifact-resolver`

PR:
- `#53`

Commit principal:
- `51c7dd3f44d216c6cb20e29479c887d2662c6b2e`

Merge commit:
- `8c2ccb6a10fd205dc859c4c925ebd81e9302bdf3`

Objetivo:
- resolver artefato persistente qualificado sem usar `.pytest_tmp`

Garantias introduzidas:
- read-only
- rejeição explícita de `.pytest_tmp`
- normalização de `external_artifact_ref`

## Fase 38 — ponto de entrada offline qualificado

Status:
- integrada

Branch:
- `codex/phase-38-offline-qualified-artifact-entrypoint`

PR:
- `#54`

Commit principal:
- `37eb3ed23bf9d89d34ccebd1f330fd06498b00ec`

Merge commit:
- `f4d9cac6b347fc34ee5b5cba502d7f3d3847516a`

Tag:
- `v0.38.0`

Objetivo:
- criar ponto de entrada read-only para artefato OKX qualificado

## Fase 40 — contrato de experimento histórico offline reproduzível

Status:
- integrada

Branch:
- `phase-40-offline-experiment-contract`

PR:
- `#55`

Commit principal:
- `95c48fe8e7dbb4d54f298caa82e98476b70a93a1`

Merge commit:
- `c2fbe4fddfd72e9d91bfbbf9aed178dba49fc85b`

Tag:
- `v0.40.0`

Objetivo:
- declarar contrato de experimento com fingerprint reproduzível

## Fase 41 — Registro Central de Experimentos Offline

Status:
- integrada

Branch:
- `phase-41-offline-experiment-registry`

PR:
- `#56`

Merge commit:
- `9a0764a`

Objetivo:
- registry central append-only e deterministicamente verificável

## Fase 42 — registro imutável de tentativas de execução offline

Status:
- integrada

Branch:
- `phase-42-offline-experiment-execution-registry`

PR:
- `#57`

Merge commit:
- `c5843ac613973cc55052fadeb17d524a0dd30d30`

Tag:
- `v0.42.0`

Objetivo:
- registrar tentativas de execução offline sem atividade operacional

## Fase 43 — plano imutável de execução offline

Status:
- integrada

Branch:
- `phase-43-offline-experiment-execution-plan`

PR:
- `#58`

Merge commit:
- `805dddb`

Tag:
- `v0.43.0`

Objetivo:
- congelar o plano de execução offline do experimento

## Fase 44 — pacote canônico de evidências e fixtures offline

Status:
- integrada

Branch:
- `phase-44-canonical-offline-evidence-fixtures`

PR:
- `#59`

Merge commit:
- `98c1aca`

Tag:
- `v0.44.0`

Objetivo:
- fornecer fixtures e evidência canônica offline

## Fase 45 — autorização imutável de execução offline

Status:
- integrada

Branch:
- `phase-45-offline-execution-authorization`

PR:
- `#60`

Merge commit:
- `81ee9e5`

Tag:
- `v0.45.0`

Objetivo:
- registrar autorização offline futura, research-only, sem execução

## Fase 46 — envelope canônico de execução offline

Status:
- integrada

Branch:
- `phase-46-offline-execution-envelope`

PR:
- `#61`

Merge commit:
- `6b3f9ed5feadb5b2207f1f452ea94159eec72e33`

Tag:
- `v0.46.0`

Objetivo:
- congelar o envelope canônico com ambiente deny-all e permissões explícitas

Garantias:
- parâmetros congelados
- seed congelada
- registry append-only
- autorização efetiva obrigatória

## Fase 47 — executor offline neutro e determinístico

Status:
- em desenvolvimento

Branch:
- `phase-47-neutral-offline-executor`

PR:
- `#62`

Commit principal:
- `c67c7629c315dc97d3ab039bcb6d692e19525b5a`

Merge commit:
- Não confirmado

Tag:
- Não confirmado

Arquivos principais:
- `market_data/offline_research_neutral_executor.py`
- `tests/test_offline_research_neutral_executor_phase47.py`

Objetivo:
- consumir envelope da Fase 46 e produzir resultado técnico neutro

Garantias introduzidas:
- não executa Baseline A
- não gera sinais
- não calcula métricas financeiras
- registry append-only
- idempotência

O que deliberadamente não foi implementado:
- estratégia
- replay
- backtest
- walk-forward
- paper
- live
- ordens

Testes ou validações relevantes:
- 7 testes específicos da Fase 47
- fases 38, 40, 41, 42, 43, 44, 45 e 46 validadas em blocos

Limitações conhecidas:
- suíte completa não consolidada no snapshot
- auditoria final pendente
