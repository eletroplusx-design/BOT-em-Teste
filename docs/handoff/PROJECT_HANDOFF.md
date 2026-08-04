# Project Handoff

## 1. Identidade do projeto

- Nome: Bot-Trader / BOT-em-Teste
- Owner: `eletroplusx-design`
- Ambiente principal: Windows
- Caminho local conhecido: `C:\Users\Vitor\Desktop\meu_app_trading`

## 2. Objetivo real

O projeto busca construir um sistema de pesquisa algorítmica auditável, reproduzível, determinístico, fail-closed e research-only, com cadeia explícita de autorização e sem promoção automática para operação.

## 3. O que o projeto ainda não é

- Não é um sistema live.
- Não é um sistema paper aprovado.
- Não está autorizado a enviar ordens.
- Não possui prova de lucratividade.
- Não possui estratégia profissional final validada.
- Não possui validação completa fora da amostra.
- Não possui capital autorizado.
- Não possui promoção operacional.

## 4. Filosofia arquitetural

- fail-closed
- identidade canônica
- hash de conteúdo
- imutabilidade
- append-only
- persistência atômica
- validação na recarga
- autorização explícita
- separação entre pesquisa e operação
- nenhum efeito colateral implícito
- nenhuma confiança em objetos isolados sem validação da cadeia

## 5. Arquitetura atual resumida

```text
referência histórica
→ contrato do experimento
→ registro do experimento
→ tentativa
→ plano
→ evidência
→ autorização
→ envelope
→ executor neutro em desenvolvimento
```

Fases já documentadas e integradas: 38, 40, 41, 42, 43, 44, 45, 46.  
Fase em aberto no momento deste snapshot: 47.

## 6. Participantes e responsabilidades

- Vitor: dono do projeto e responsável pelas decisões finais
- ChatGPT: planejamento arquitetural, revisão, auditoria e elaboração de prompts
- Codex: implementação, testes, Git, branches, commits e PRs
- DeepSeek: apoio eventual de análise textual

## 7. Estado atual

Ver [CURRENT_STATE.md](./CURRENT_STATE.md).

## 8. Próxima ação obrigatória

A primeira tarefa do próximo desenvolvedor é verificar e auditar a Fase 47. Não iniciar a Fase 48 antes disso, salvo se o estado real já tiver mudado e isso estiver comprovado.
