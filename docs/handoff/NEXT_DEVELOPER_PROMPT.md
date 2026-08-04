# Next Developer Prompt

Você está assumindo a continuidade do projeto Bot-Trader.

Antes de alterar qualquer arquivo, leia todos os documentos em `docs/handoff`.

Não confie cegamente no snapshot.
Confirme o estado real do GitHub, branches, tags, PRs, CI e working tree.

A primeira tarefa esperada é auditar a Fase 47 e a PR `#62`, caso ela ainda esteja aberta e não integrada.

Não inicie a Fase 48 antes de concluir:
- auditoria do diff;
- ampliação da cobertura específica;
- validação de determinismo;
- validação de limites;
- validação de idempotência;
- persistência fail-closed;
- isolamento;
- suíte completa;
- CI verde;
- merge;
- tag `v0.47.0`.

Não execute Baseline A.
Não gere sinais.
Não faça backtest.
Não habilite paper.
Não habilite live.
Não conecte corretora.
Não envie ordens.

Estado de referência do snapshot:
- Fase 47 em PR draft
- branch: `phase-47-neutral-offline-executor`
- head: `c67c7629c315dc97d3ab039bcb6d692e19525b5a`
- PR: `#62`
- CI: em andamento

Trate `CURRENT_STATE.md` como snapshot e não como verdade eterna.
