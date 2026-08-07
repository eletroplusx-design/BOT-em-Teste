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

## Fase 49 - registry offline de auditorias de execucao

Status:
- integrada

Branch:
- `codex/phase-49-offline-execution-audit-registry`

PR:
- `#65`

Commit principal:
- `07cb0856cfef460331d1944b4b0b7408d23fbd00`

Merge commit:
- `40cc86cc1fb60347211cb335f987cc28ea63a363`

Tag:
- `v0.49.0`

Objetivo:
- registrar multiplos audit records da Fase 48 em um registry append-only, idempotente e fail-closed

Garantias introduzidas:
- registry_entry_id deterministico
- registry_entry_hash deterministico
- registry_hash deterministico
- metadata material e profundamente imutavel
- cadeia linear com previous_entry_id e previous_entry_hash
- regra 1:1 para `execution_attempt_id`
- persistencia atomica e carregamento fail-closed
- protecao cross-platform para arquivos de registry

## Fase 50 - contrato de pesquisa de estrutura de mercado

Status:
- integrada

Branch:
- `codex/phase-50-market-structure-research-contract`

PR:
- `#66`

Commit principal:
- `bd9bb8a0765efc9ee0517772cd0a184b71347a6e`

Merge commit:
- `b991e2e254d2558da6513ff9d64361f273747eda`

Tag:
- `v0.50.0`

Objetivo:
- declarar um contrato de pesquisa de estrutura de mercado, deterministicamente canonico, profundamente imutavel e sem qualquer comportamento operacional

Garantias introduzidas:
- contract_id deterministico
- contract_hash deterministico
- created_at_utc fora da identidade
- metadata material e profundamente imutavel
- canonicalizacao estavel
- round-trip fail-closed
- ausencia de detector, classificacao automatica, sinais, entrada, stop, alvo, replay, backtest, walk-forward, paper, live, corretora, ordens e rede

## Fase 51 - detector offline de estrutura de mercado

Status:
- integrada

Branch:
- `codex/phase-51-offline-market-structure-detector`

PR:
- `#67`

Commit principal:
- `c62e32ce9e5fca1aec9776b57e327d6d393d4ddc`

Merge commit:
- `c4936dc98924c5d957489d1313786ab9d775e2f2`

Tag:
- `v0.51.0`

Objetivo:
- detectar estrutura de mercado de forma offline, deterministica, research-only e sem habilitar operacao

Garantias introduzidas:
- detection_result_id deterministico
- detection_result_hash deterministico
- event_id e event_hash deterministicos quando aplicaveis
- timestamp fora da identidade canonica
- ordenacao canonica dos eventos
- look-ahead controlado pela right_window declarada
- ambiguous e indeterminate como saidas legitimas
- deep freeze e round-trip fail-closed
- ausencia de sinais, replay, backtest, walk-forward, paper, live, corretora, ordens e rede

## Fase 53 - avaliacao de hipoteses de estrutura de mercado

Status:
- integrada

Branch:
- `codex/phase-53-market-structure-hypothesis-evaluation`

PR:
- `#69`

Commit principal:
- `d46fb88a71a13601c0d64b4d78bd9efaeeea603f`

Merge commit:
- `01d203c51500ad5b7c5af19d6bda1f91cd0a14c3`

Tag:
- `v0.53.0`

Objetivo:
- avaliar hipoteses de estrutura de mercado de forma offline, deterministica, explicavel e research-only, sem scoring nem promocao operacional

Garantias introduzidas:
- hypothesis_id deterministico
- hypothesis_hash deterministico
- evaluation_id deterministico
- evaluation_hash deterministico
- annotation_collection_hash persistido e validado
- supporting e contradicting evidence canonicos
- invalidation_reasons precedem quando aplicavel
- Unknown preservado como hipoteses legitima
- multi-timeframe explicito com contexto canonicalizado
- created_at_utc fora da identidade
- deep freeze e round-trip fail-closed
- ausencia de score, confidence, probability, ranking, BUY, SELL, LONG, SHORT, replay, backtest, walk-forward, paper, live, corretora, ordens e rede

## Fase 54 - avaliacao de evidencias de estrutura de mercado

Status:
- integrada

Branch:
- `codex/phase-54-market-structure-evidence-assessment`

PR:
- `#70`

Commit principal:
- `f3b521937f5b98697560967acf3147d0b36123ff`

Merge commit:
- `42ab3bbcaab6e05a32d14047d85a026ce5a86931`

Tag:
- `v0.54.0`

Objetivo:
- avaliar evidencias estruturais de forma offline, deterministica, explicavel e research-only, sem scoring, ranking ou promocao operacional

Garantias introduzidas:
- evidence_id deterministico
- assessment_id deterministico
- assessment_hash deterministico
- provenance_group_id deterministico
- evidence_matrix canonica com families observadas apenas
- families ausentes omitidas da matriz
- support, contradiction, ambiguity e invalidation preservados
- evidence_items, provenance_groups e evidence_matrix profundamente imutaveis
- assessment vazio canonico permitido
- ausencia de score, confidence, probability, ranking, BUY, SELL, LONG, SHORT, replay, backtest, walk-forward, paper, live, corretora, ordens e rede

## Fase 55 - consolidacao estrutural de hipoteses

Status:
- integrada

Branch:
- `codex/phase-55-market-structure-structural-assessment`

PR:
- `#71`

Commit principal:
- `76368e85364eb5f5f108ea83c789e8c29d9deecb`

Merge commit:
- `4f45a99e9fc3c3b69947937a1113286836606f98`

Tag:
- `v0.55.0`

Objetivo:
- consolidar evidencias estruturais em uma avaliacao por hipotese, deterministicamente canonica, profundamente imutavel e sem qualquer comportamento operacional

Garantias introduzidas:
- structural_state deterministico
- dimension summaries esparsos por dimensao observada
- absent omitido em vez de materializado como neutral
- supporting, contradicting, ambiguous, indeterminate, invalidated, neutral e empty preservados
- invalidation precedence preservada
- provenance preservada sem contagem implicita
- multi-timeframe sem escolha automatica de vencedor
- ausencia de score, confidence, probability, ranking, signal, replay, backtest, walk-forward, paper, live, corretora, ordens e rede
