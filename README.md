# meu_app_trading

Bot de trading com analise, vigia, paper trading e observabilidade.

## Modo seguro e seguranca

- Operacao real vem bloqueada por padrao.
- `TRADING_ENABLED=false`
- `LIVE_TRADING_ENABLED=false`
- `GLOBAL_KILL_SWITCH=true`
- O bot so responde a chats/usuarios listados em `TELEGRAM_AUTHORIZED_IDS`.
- Se alguma credencial estiver ausente, o componente correspondente entra em modo seguro.

## Preparar ambiente

Copie `.env.example` para `.env` e preencha as variaveis necessarias:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_AUTHORIZED_IDS`
- `GROQ_API_KEY`
- `NVIDIA_API_KEY`

## Executar o bot

```bash
python bot_telegram.py
```

## Executar testes

Instale as dependencias de desenvolvimento:

```bash
pip install -r requirements-dev.txt
```

Rode a suite:

```bash
pytest -q
```

Para cobertura:

```bash
pytest --cov=. --cov-report=html
```

## Operacao real

Esta versao foi preparada com bloqueios de seguranca e nao deve ser usada para ordem real sem revisao humana e habilitacao explicita dos switches de operacao.

## Revalidacao de segredo vazado

Se alguma chave antiga tiver aparecido em historico, revogue-a no provedor e gere uma nova antes de operar.
