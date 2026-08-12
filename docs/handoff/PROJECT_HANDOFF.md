# Project Handoff

## 1. Identidade do projeto

- Nome: Bot-Trader / BOT-em-Teste
- Owner: `eletroplusx-design`
- Ambiente principal: Windows
- Caminho local conhecido: `C:\Users\Vitor\Desktop\meu_app_trading`

## 2. Objetivo real

O projeto busca construir um sistema de pesquisa algoritimica auditavel, reproduzivel, deterministico, fail-closed e research-only, com cadeia explicita de autorizacao e sem promocao automatica para operacao.

## 3. O que o projeto ainda nao e

- Nao e um sistema live.
- Nao e um sistema paper aprovado.
- Nao esta autorizado a enviar ordens.
- Nao possui prova de lucratividade.
- Nao possui estrategia profissional final validada.
- Nao possui validacao completa fora da amostra.
- Nao possui capital autorizado.
- Nao possui promocao operacional.

## 4. Filosofia arquitetural

- fail-closed
- identidade canonica
- hash de conteudo
- imutabilidade
- append-only
- persistencia atomica
- validacao na recarga
- autorizacao explicita
- separacao entre pesquisa e operacao
- nenhum efeito colateral implicito
- nenhuma confianca em objetos isolados sem validacao da cadeia

## 5. Arquitetura atual resumida

```text
referencia historica
→ contrato do experimento
→ registro do experimento
→ tentativa
→ plano
→ evidencia
→ autorizacao
→ envelope
→ executor neutro integrado
→ registry de auditoria offline
→ persistencia canonica da structural assessment history
→ lineage temporal canonica de hypotheses
```

Fases ja documentadas e integradas: 38, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 53, 54, 55, 56, 57, 58, 59.
Fase 60 tambem foi integrada, validada empiricamente e versionada em `v0.60.0`.
Nao ha fase de produto em aberto neste snapshot.

## 6. Participantes e responsabilidades

- Vitor: dono do projeto e responsavel pelas decisoes finais
- ChatGPT: planejamento arquitetural, revisao, auditoria e elaboracao de prompts
- Codex: implementacao, testes, Git, branches, commits e PRs
- DeepSeek: apoio eventual de analise textual

## 7. Estado atual

Ver [CURRENT_STATE.md](./CURRENT_STATE.md).

A Fase 59 foi integrada em `main` por meio da PR `#79` e versionada em `v0.59.0`.
A PR `#80` integrou em `main` o bugfix da Fase 53 para deduplicar `Unknown` redundantes sem alterar `known hypotheses` e sem criar nova tag.
A Fase 60 foi integrada em `main` por meio da PR `#81`, validada empiricamente e versionada em `v0.60.0`.
Esse merge nao altera a arquitetura funcional do bot.
Os fluxos de pesquisa, validacao e seguranca permanecem research-only e fail-closed.
O pacote de continuidade segue com o branch de documentacao separado do branch de produto.

## 8. Proxima acao obrigatoria

A primeira tarefa do proximo desenvolvedor e verificar o estado real do GitHub antes de iniciar qualquer nova fase.

A Fase 60 ja foi concluida, integrada, validada empiricamente e versionada.
Nao iniciar a Fase 61 automaticamente.
Nao iniciar nova fase sem autorizacao explicita e sem confirmar novamente o estado real.
