# Testing and Release Process

## Antes de iniciar uma fase

```powershell
git fetch origin
git checkout main
git pull --ff-only origin main
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

## Branch

Use um nome claro no formato `phase-XX-description`.

## Validações mínimas

- `py_compile`
- testes específicos
- integração das fases relacionadas
- regressão da cadeia
- suíte completa
- `git diff --check`
- `git status --short`
- CI remoto

## Timeout da suíte

Se a suíte completa exceder o limite normal:

1. configurar `.pytest_tmp`
2. tentar a suíte completa
3. dividir em blocos determinísticos
4. registrar todos os arquivos
5. executar cada arquivo exatamente uma vez
6. consolidar passes, failures, warnings e skips
7. qualquer falha bloqueia merge

## Revisão do diff

```powershell
git diff --stat
git diff origin/main...HEAD
git diff --check
```

## PR

- abrir como draft
- descrever escopo, fases e validações
- não fazer merge no mesmo trabalho de implementação
- auditoria separada
- confirmar head SHA
- confirmar CI

## Merge

- marcar pronta para revisão
- confirmar head
- merge normal
- não squash
- não rebase
- usar expected head SHA quando possível

## Tag

- apenas depois do merge
- tag anotada
- mensagem da fase
- confirmar tag local
- confirmar tag remota
- confirmar commit resolvido

## Relatório final

Incluir branch, commit, PR, validações, CI, `git diff --check`, `git status --short` e confirmação de que nenhuma operação real foi habilitada.
