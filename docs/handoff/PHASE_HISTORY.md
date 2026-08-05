# Phase History

## Fases 9A, 9B, 9C e 10A

Status:
- integrada

Tag:
- `v0.9.0-trusted-historical-data`
- `v0.9.1-historical-replay-validation`
- `v0.9.2-historical-experiment-contract`
- `v0.10.0-baseline-trend-pullback`

Objetivo:
- estabelecer dados historicos confiaveis, validacao de replay e a primeira baseline trend/pullback

## Fases 11-22

Status:
- integrada

Tag:
- `v0.11.0-historical-provider-qualification`
- `v0.11.1-kucoin-spot-historical-provider`
- `v0.12.0-kucoin-multitimeframe-qualification`
- `v0.12.1-historical-multitimeframe-alignment`

## Fase 24 - rastreamento auditavel dos gates entre sinal e trade simulado

Status:
- integrada

Tag:
- `v0.26.0` e a base posterior de referencia do subciclo atual

## Fase 26 - diagnostico historico da divergencia entre setup e Signal

Status:
- integrada

Branch:
- `codex/phase-26-signal-gap-diagnostic-research`

PR:
- `#51`

Commit principal:
- `1cc3ca9b01568b4c91cf0d2dc51cc878beb79624`

## Fase 30 - correcao da confiabilidade do diagnostico setup -> Signal

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

## Fase 34 - resolvedor seguro de artefato historico persistente

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

## Fase 38 - ponto de entrada offline qualificado

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

## Fase 40 - contrato de experimento historico offline reproduzivel

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

## Fase 41 - Registro Central de Experimentos Offline

Status:
- integrada

Branch:
- `phase-41-offline-experiment-registry`

PR:
- `#56`

Merge commit:
- `9a0764a`

## Fase 42 - registro imutavel de tentativas de execucao offline

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

## Fase 43 - plano imutavel de execucao offline

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

## Fase 44 - pacote canonico de evidencias e fixtures offline

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

## Fase 45 - autorizacao imutavel de execucao offline

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

## Fase 46 - envelope canonico de execucao offline

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

## Fase 47 - executor offline neutro e deterministico

Status:
- integrada

Branch:
- `phase-47-neutral-offline-executor`

PR:
- `#62`

Commit principal:
- `c67c7629c315dc97d3ab039bcb6d692e19525b5a`

Merge commit:
- `abf3d31cf51f9ebcd0321e3281e7b75e28c5a41b`

Tag:
- `v0.47.0`

Objetivo:
- consumir envelope da Fase 46 e produzir resultado tecnico neutro sem executar estrategia

Garantias introduzidas:
- nao executa Baseline A
- nao gera sinais
- nao calcula metricas financeiras
- registry append-only
- idempotencia
- determinismo de resultado e persistencia

## Fase 48 - registro canonico de auditoria da execucao offline

Status:
- integrada

Branch:
- `codex/phase-48-offline-execution-audit-record`

PR:
- `#64`

Commit principal:
- `ba1cf11474d817bb55138086fbd68adf3346a912`

Merge commit:
- `838eb0706b2d3dc35aeef8ea6926e4b7775d14af`

Tag:
- `v0.48.0`

Objetivo:
- registrar auditoria offline de execucao com identidade canonica, persistencia atomica e protecoes cross-platform

Garantias introduzidas:
- audit_record_hash deterministico
- lineage_hash deterministico
- created_at_utc fora da identidade
- freeze e thaw profundos
- rejeicao de Windows absolute, Unix absolute, UNC, traversal, home expansion e `.pytest_tmp`
