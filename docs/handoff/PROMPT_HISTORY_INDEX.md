# Prompt History Index

Este índice resume as categorias de prompts usadas até aqui. Ele não substitui os contratos atuais.

## Implementação de fase

- Objetivo: criar artefatos e regras novas em passos pequenos.
- Princípios recorrentes: escopo mínimo, cadeia de fases, fail-closed, hashes e imutabilidade.
- Comandos recorrentes: `py_compile`, `pytest`, `git diff --check`, `git status --short`.
- Critérios de aprovação: testes relevantes passando, diff limitado, working tree limpa.
- Erros a evitar: ampliar escopo, tocar em Baseline A sem necessidade, habilitar operação.

## Auditoria de fase

- Objetivo: revisar PRs sem editar código.
- Princípios recorrentes: read-only, evidência técnica, comparação com a base real.
- Comandos recorrentes: `gh pr view`, `gh pr checks`, `git log`, inspeção de diff.
- Critérios de aprovação: PR coerente com a revisão, checks verdes, sem regressões.
- Erros a evitar: tratar draft como integrado, concluir sem CI, misturar revisão com correção.

## Merge e versionamento

- Objetivo: integrar PR aprovada em `main` e marcar tag quando cabível.
- Princípios recorrentes: merge normal, confirmação do head, tag anotada depois do merge.
- Comandos recorrentes: `git merge`, `git pull --ff-only`, `git tag`, `git push`.
- Critérios de aprovação: merge commit correto, working tree limpa, tag publicada.
- Erros a evitar: squash indevido, rebase, tag antes do merge, alterar escopo no merge.

## Investigação de dados

- Objetivo: preservar e qualificar artefatos históricos.
- Princípios recorrentes: fixtures canônicas, hashes, contratos, reprodutibilidade.
- Critérios de aprovação: artefato qualificado, referência persistente, rejeição de fontes temporárias.

## Baseline

- Objetivo: manter uma referência de engenharia estável.
- Princípios recorrentes: baseline A congelada, sem flexibilização sem fase própria.

## Executor

- Objetivo: consumir envelopes e produzir artefatos técnicos sem operação.
- Princípios recorrentes: neutralidade, isolamento, idempotência, limites e persistência append-only.

## Documentação

- Objetivo: permitir continuidade sem depender da conversa atual.
- Princípios recorrentes: estado real, fontes verificáveis, distinção entre integrado e draft.

## Padrão de prompt de implementação

1. confirmar estado real
2. criar branch separada
3. ler o código antes de editar
4. alterar somente o escopo autorizado
5. validar com testes e diff
6. commitar, push e abrir PR draft

## Padrão de prompt de auditoria

1. confirmar head/base reais
2. revisar diff e arquivos tocados
3. validar testes seguros
4. confirmar proteções e isolamento
5. emitir aprovação ou bloqueador objetivo

Prompts históricos não substituem os contratos atuais.
