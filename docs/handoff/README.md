# Bot-Trader - Pacote de continuidade do projeto

Este pacote existe para permitir que outro desenvolvedor ou outra IA assuma o Bot-Trader sem depender desta conversa.

## Ordem obrigatoria de leitura

1. [CURRENT_STATE.md](./CURRENT_STATE.md)
2. [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md)
3. [ENGINEERING_GUARDRAILS.md](./ENGINEERING_GUARDRAILS.md)
4. [PHASE_HISTORY.md](./PHASE_HISTORY.md)
5. [TESTING_AND_RELEASE_PROCESS.md](./TESTING_AND_RELEASE_PROCESS.md)
6. [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md)
7. [STRATEGY_RESEARCH_NOTES.md](./STRATEGY_RESEARCH_NOTES.md)
8. [NEXT_DEVELOPER_PROMPT.md](./NEXT_DEVELOPER_PROMPT.md)

## Aviso central

Nao iniciar nova fase antes de verificar o estado real do GitHub.
Nao tratar PR draft como codigo integrado.
Nao habilitar paper, live, rede, corretora ou ordens.

## Estado resumido

- Ultima tag integrada: `v0.60.0`
- Commit de `main`: `08fea0a982dbc72054c4bc58243d664f5bdd6afd`
- Fase integrada mais recente: Fase 60 - Local Structural Transition Detector
- PR integrada: `#81`
- Branch: `codex/phase-60-local-structural-transition`
- Head: `1e466c22bd0c6774c1d6366cd20edf6a1920ef52`
- Merge commit: `08fea0a982dbc72054c4bc58243d664f5bdd6afd`
- Status: fase funcional integrada, validada empiricamente, CI verde e versionamento concluido via PR `#81`
- Proxima acao: manter a Fase 60 isolada ate existir consumidor real e autorizacao explicita para reavaliar integracao downstream
