# Contributing

## Ambiente

- Use a venv do projeto.
- Mantenha compatibilidade com Windows PowerShell 5.1 e CI em Linux.

## Branches

- Use uma branch específica por fase ou por documentação.
- Não misture escopos não relacionados.

## Testes

- Execute testes focados antes de ampliar a validação.
- Depois execute a suíte completa quando o tempo permitir.
- Sempre rode `python -m py_compile` nos arquivos Python alterados.
- Sempre rode `git diff --check` e `git status --short`.

## PR

- Abra PR draft para mudanças em andamento.
- Não marque como pronta sem auditoria e CI.
- Não faça merge no mesmo trabalho de implementação.

## Segurança

- Não versionar secrets, tokens, chaves, cookies ou `.env`.
- Não habilitar paper, live, corretora ou ordens sem fase dedicada.
- Leia [docs/handoff/TESTING_AND_RELEASE_PROCESS.md](docs/handoff/TESTING_AND_RELEASE_PROCESS.md) antes de publicar.

## Processo

- Confira o estado real do GitHub antes de assumir qualquer snapshot.
- Documentação de continuidade deve apontar para fontes verificáveis.
