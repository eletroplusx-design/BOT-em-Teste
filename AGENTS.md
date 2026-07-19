# Regras Permanentes do Bot-Trader

## Escopo e segurança

- Este projeto permanece voltado a analise, backtest, validacao, promocao controlada e paper trading monitorado.
- Nao existe autorizacao permanente para operacao real.
- Nao criar executor real, endpoints privados, ordens autenticadas ou movimentacao de saldo sem solicitacao explicita do proprietario.
- Uma aprovacao paper nunca significa aprovacao live.
- Nunca enfraquecer kill switch, switches de trading, autorizacao do Telegram ou gates fail-closed.

## Integridade estatistica

- Nunca fabricar trades, sinais, fills, metricas, regimes, aprovacoes ou proveniencia.
- Dados sinteticos, fixtures e seeds nunca podem virar evidencia operacional.
- Nunca reduzir politicas ou gates apenas para obter aprovacao.
- Reprovacoes legitimas devem ser preservadas e reportadas.
- Preservar no-lookahead, purge/embargo, custos, slippage, spread e contratos walk-forward.

## Operacao local

- Nao executar `-Prepare`, `-StartSession`, `bot_telegram.py` ou `/vigia` sem autorizacao explicita do usuario.
- Auditorias read-only nao autorizam mutacoes.
- Preservar `paper_data` e todos os bancos SQLite.
- Nunca apagar manualmente arquivos WAL ou SHM.
- Nao editar bancos ou JSONs operacionais manualmente.
- Backup e restore devem usar apenas fluxos administrativos validados.

## Segredos e privacidade

- Nunca imprimir tokens, chaves, secrets, passwords, headers Authorization/Bearer, mensagens privadas ou payloads sensiveis.
- Logs e erros devem ser sanitizados e limitados.
- Nao versionar `.env`.
- `.env.example` deve conter somente placeholders ficticios.
- Testes devem usar mocks e nao realizar chamadas autenticadas externas.

## Compatibilidade

- Usar a venv do projeto.
- Manter compatibilidade com a versao de Python suportada e com Windows PowerShell 5.1.
- Preservar compatibilidade com PowerShell 7 e Linux no CI.
- Usar parsing estrito e comportamento fail-closed.
- Timestamps operacionais devem possuir timezone e usar UTC canonico.

## Regras de desenvolvimento

- Ler o codigo e os testes relacionados antes de editar.
- Fazer alteracoes minimas e dentro do escopo.
- Nao refatorar modulos nao relacionados durante hotfixes.
- Preservar alteracoes existentes do usuario.
- Nao adicionar dependencias sem necessidade comprovada.
- Nao ocultar falhas com mocks tautologicos.
- Testes devem validar comportamento observavel.
- Diagnostico nao autoriza implementacao, salvo quando o pedido incluir correcao.

## Validacao obrigatoria

Antes de publicar alteracoes:

- executar testes focados;
- executar a suite completa;
- executar `python -m py_compile` nos arquivos Python alterados, quando aplicavel;
- validar scripts PowerShell quando alterados;
- executar `git diff --check`;
- executar `git status --short`;
- informar resultados e warnings exatamente;
- nao afirmar que CI passou sem confirmacao remota.

## Git e GitHub

- Nunca usar force push.
- Nunca reescrever historico.
- Trabalhar em branch especifica.
- Criar commits normais e PR draft.
- Nao marcar PR como ready, fazer merge ou criar tag sem autorizacao explicita.
- Confirmar hash local e remoto depois do push.
- Nao incluir arquivos operacionais ou credenciais no commit.

## Campanha paper

- Decisoes, referencias, coortes, campanhas, bindings e sessoes devem permanecer hash-anchored e write-once quando o contrato exigir.
- Retomadas devem ser idempotentes.
- Estados ausentes, divergentes ou adulterados bloqueiam.
- Nenhuma aprovacao paper autoriza operacao real.

## Relatorio

Ao concluir uma tarefa, informar:

- branch e commit;
- arquivos alterados;
- comportamento modificado;
- testes executados e resultados;
- CI e URL, se realmente confirmados;
- `git diff --check`;
- `git status --short`;
- limitacoes ou verificacoes nao realizadas;
- confirmacao de que nenhuma operacao real foi habilitada.

## Nao incluir no AGENTS.md

- hashes atuais;
- datas ou IDs de campanha;
- quantidade atual de testes;
- caminhos pessoais absolutos;
- nomes de branches temporarias;
- detalhes especificos de erros atuais;
- credenciais ou IDs.
