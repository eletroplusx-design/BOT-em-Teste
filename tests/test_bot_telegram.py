from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pandas as pd
import sqlite3
import pytest

import config

import bot_telegram


@pytest.fixture(autouse=True)
def _autorizar_chat_teste(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_AUTHORIZED_IDS", {123})
    monkeypatch.setattr(config, "TELEGRAM_AUTHORIZED_CHAT_IDS", {123})
    monkeypatch.setattr(config, "TELEGRAM_GROUPS_ENABLED", False)
    monkeypatch.setattr(bot_telegram, "TELEGRAM_AUTHORIZED_IDS", {123})
    monkeypatch.setattr(bot_telegram, "TELEGRAM_AUTHORIZED_CHAT_IDS", {123})
    monkeypatch.setattr(bot_telegram, "TELEGRAM_GROUPS_ENABLED", False)
    yield


class FakeMessage:
    def __init__(self, text=None):
        self.text = text
        self._status_message = SimpleNamespace(edit_text=AsyncMock())
        self.reply_text = AsyncMock(return_value=self._status_message)
        self.edit_text = AsyncMock()


class FakeUpdate:
    def __init__(self, text=None, callback_data=None, user_id=123, chat_id=123, chat_type="private"):
        self.message = FakeMessage(text=text)
        self.callback_query = FakeCallbackQuery(callback_data) if callback_data is not None else None
        self.effective_chat = SimpleNamespace(id=chat_id, type=chat_type)
        self.effective_user = SimpleNamespace(id=user_id)


class FakeCallbackQuery:
    def __init__(self, data):
        self.data = data
        self.answer = AsyncMock()
        self.edit_message_text = AsyncMock()


class FakeJob:
    def __init__(self, name):
        self.name = name
        self.removed = False

    def schedule_removal(self):
        self.removed = True


class FakeJobQueue:
    def __init__(self, jobs=None):
        self.jobs = jobs or {}
        self.calls = []

    def get_jobs_by_name(self, name):
        return self.jobs.get(name, [])

    def run_repeating(self, callback, interval, first, name, data):
        self.calls.append(
            {
                "callback": callback,
                "interval": interval,
                "first": first,
                "name": name,
                "data": data,
            }
        )
        job = FakeJob(name)
        self.jobs.setdefault(name, []).append(job)
        return job


class FakeContext:
    def __init__(self, job_queue=None, chat_id=123, user_id=123, chat_type="private"):
        self.job_queue = job_queue or FakeJobQueue()
        self.job = SimpleNamespace(data={"chat_id": chat_id, "user_id": user_id, "chat_type": chat_type})
        self.bot = SimpleNamespace(send_message=AsyncMock())
        self.user_data = {}


def _df_market(rows=220, regime="BULL"):
    import pandas as pd

    base = pd.DataFrame(
        {
            "open": [100 + i * 0.1 for i in range(rows)],
            "high": [101 + i * 0.1 for i in range(rows)],
            "low": [99 + i * 0.1 for i in range(rows)],
            "close": [100.5 + i * 0.1 for i in range(rows)],
            "volume": [1000 + i for i in range(rows)],
            "timestamp": pd.date_range("2026-01-01", periods=rows, freq="h"),
        }
    )
    base.attrs["fonte_dados"] = "BINANCE"
    return base


def test_start_exibe_observabilidade():
    update = FakeUpdate()
    context = FakeContext()

    import asyncio

    asyncio.run(bot_telegram.start(update, context))

    mensagem = update.message.reply_text.await_args.args[0]
    assert "/paper_status" in mensagem
    assert "/paper_log" in mensagem
    assert "/mestre" in mensagem


def test_autorizacao_privada_grupo_callback_e_job(monkeypatch):
    import asyncio

    update_privado_bloqueado = FakeUpdate(user_id=999)
    contexto = FakeContext(user_id=999)
    asyncio.run(bot_telegram.analisa(update_privado_bloqueado, contexto))
    assert "Acesso negado" in update_privado_bloqueado.message.reply_text.await_args_list[-1].args[0]

    update_chat_bloqueado = FakeUpdate(user_id=123, chat_id=123, chat_type="group")
    asyncio.run(bot_telegram.analisa(update_chat_bloqueado, contexto))
    assert "Acesso negado" in update_chat_bloqueado.message.reply_text.await_args_list[-1].args[0]

    update_callback_bloqueado = FakeUpdate(callback_data="COMPRA", user_id=999)
    asyncio.run(bot_telegram.trade_direcao(update_callback_bloqueado, contexto))
    assert "Acesso negado" in update_callback_bloqueado.callback_query.edit_message_text.await_args_list[-1].args[0]

    monkeypatch.setattr(bot_telegram, "baixar_dados_btc", lambda: (_ for _ in ()).throw(RuntimeError("nao deve chamar")))
    contexto_job = FakeContext(user_id=999)
    asyncio.run(bot_telegram.monitorar_preco(contexto_job))
    assert contexto_job.bot.send_message.await_count == 0


def test_vigia_grupo_desativado_por_padrao(monkeypatch):
    import asyncio

    update = FakeUpdate(user_id=123, chat_id=777, chat_type="group")
    context = FakeContext(user_id=123, chat_id=777, chat_type="group")
    asyncio.run(bot_telegram.ativar_vigia(update, context))
    assert "Acesso negado" in update.message.reply_text.await_args_list[-1].args[0]


def test_analisa_sucesso_e_erro(monkeypatch):
    update = FakeUpdate()
    context = FakeContext()
    monkeypatch.setattr(bot_telegram, "obter_analise", lambda: "RELATORIO FINAL")

    import asyncio

    asyncio.run(bot_telegram.analisa(update, context))
    assert update.message.reply_text.await_count == 2
    assert update.message.reply_text.await_args_list[-1].args[0] == "RELATORIO FINAL"

    update_erro = FakeUpdate()
    monkeypatch.setattr(bot_telegram, "obter_analise", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    asyncio.run(bot_telegram.analisa(update_erro, context))
    assert "Erro durante a análise" in update_erro.message.reply_text.await_args_list[-1].args[0]


def test_comando_ia_sucesso_e_sem_dados(monkeypatch):
    update = FakeUpdate()
    context = FakeContext()
    monkeypatch.setattr(bot_telegram, "obter_dados_resumidos", lambda: {"ok": True})
    monkeypatch.setattr(bot_telegram, "obter_analise", lambda: "ANALISE")
    monkeypatch.setattr(bot_telegram, "gerar_comentario_ia", lambda dados: "COMENTARIO IA")

    import asyncio

    asyncio.run(bot_telegram.comando_ia(update, context))
    assert "ANALISE" in update.message.reply_text.await_args_list[-1].args[0]
    assert "COMENTARIO IA" in update.message.reply_text.await_args_list[-1].args[0]

    update_nd = FakeUpdate()
    monkeypatch.setattr(bot_telegram, "obter_dados_resumidos", lambda: None)
    asyncio.run(bot_telegram.comando_ia(update_nd, context))
    assert "Não foi possível obter os dados" in update_nd.message.reply_text.await_args_list[-1].args[0]


def test_obter_dados_resumidos_e_analise(monkeypatch):
    df = _df_market()
    monkeypatch.setattr(bot_telegram, "baixar_dados_btc", lambda: df)
    monkeypatch.setattr(bot_telegram, "tomar_decisao", lambda d: {
        "decisao": "COMPRA",
        "score": 8,
        "rr": 2.0,
        "volume_status": "ALTO",
        "motivo": "ok",
        "zona_entrada_ideal": 100.0,
        "direcao": "COMPRA",
        "entrada": 101.0,
        "stop_loss": 99.0,
        "take_profit": 105.0,
        "rsi": 50,
        "rsi_status": "Neutro",
    })
    monkeypatch.setattr(bot_telegram, "classificar_regime", lambda d: {"regime": "BULL", "adx": 25, "volatilidade": "NORMAL"})
    monkeypatch.setattr(bot_telegram, "tendencia_geral", lambda d: "TREND OK")
    monkeypatch.setattr(bot_telegram, "identificar_fvg", lambda d: "FVG OK")
    monkeypatch.setattr(bot_telegram, "calcular_atr", lambda d, p: df["close"].rolling(14).mean().fillna(0))
    monkeypatch.setattr(bot_telegram, "obter_funding_info", lambda: "0.01%")
    monkeypatch.setattr(bot_telegram, "aplicar_bloqueio_risco", lambda decisao_info, capital=10000, risco_percentual=1.0: {"risco_percentual": 1.0, "valor_arriscado": 100.0, "quantidade": 0.01, "limite_diario_atingido": False, "sequencia_perdas_atingida": False})

    dados = bot_telegram.obter_dados_resumidos()
    assert dados["regime"] == "BULL"
    assert dados["veredito"] == "COMPRA"

    analise = bot_telegram.obter_analise()
    assert "Análise BTC/USDT" in analise
    assert "Direção" in analise

    monkeypatch.setattr(bot_telegram, "baixar_dados_btc", lambda: pd.DataFrame())
    assert "Não foi possível obter os dados" in bot_telegram.obter_analise()


def test_paper_status_monta_resumo(monkeypatch):
    update = FakeUpdate()
    context = FakeContext()

    monkeypatch.setattr(
        bot_telegram,
        "buscar_ultimo_decision_log",
        lambda modos=None: {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "decisao": "AGUARDAR",
            "motivo": "sem sinal",
            "preco": 123.45,
            "fonte_dados": "BINANCE",
            "modo": "PAPER_SOL",
            "symbol": "SOLUSDT",
        },
    )
    monkeypatch.setattr(bot_telegram, "contar_trades_abertos_paper", lambda symbol: 2)
    monkeypatch.setattr(bot_telegram, "contar_trades_fechados_hoje", lambda symbol: 1)
    monkeypatch.setattr(
        bot_telegram,
        "_obter_preco_atual_referencia",
        lambda symbol: (123.45, "BINANCE"),
    )
    monkeypatch.setattr(
        bot_telegram,
        "obter_resumo_risco",
        lambda: {"ultimo_bloqueio": {"motivo": "Stop apertado", "timestamp": "2026-01-01T00:01:00+00:00"}},
    )
    monkeypatch.setattr(bot_telegram, "vigia_ativo", True)
    monkeypatch.setattr(bot_telegram, "PAPER_TRADING_ATIVO", True)
    monkeypatch.setattr(bot_telegram, "ULTIMO_LOG_CACHE", {})

    import asyncio

    asyncio.run(bot_telegram.paper_status(update, context))

    assert update.message.reply_text.await_count == 1
    assert update.message._status_message.edit_text.await_count == 1
    mensagem = update.message._status_message.edit_text.await_args.args[0]
    assert "Paper ativo: SIM" in mensagem
    assert "Vigia ativo: SIM" in mensagem
    assert "Último bloqueio do risk manager" in mensagem or "Ãšltimo bloqueio do risk manager" in mensagem


def test_paper_log_retorna_logs(monkeypatch):
    update = FakeUpdate()
    context = FakeContext()
    monkeypatch.setattr(
        bot_telegram,
        "buscar_ultimos_decision_logs",
        lambda limite=10: [
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "symbol": "SOLUSDT",
                "decisao": "TRADE_ABERTO",
                "motivo": "abriu",
                "bloqueado_por": "N/A",
                "fonte_dados": "BINANCE",
            }
        ],
    )

    import asyncio

    asyncio.run(bot_telegram.paper_log(update, context))

    mensagem = update.message.reply_text.await_args.args[0]
    assert "Últimos 10 Decision Logs" in mensagem or "Ãšltimos 10 Decision Logs" in mensagem
    assert "TRADE_ABERTO" in mensagem


def test_mestre_retorna_resumo(monkeypatch):
    update = FakeUpdate()
    context = FakeContext()
    monkeypatch.setattr(bot_telegram, "gerar_resumo_mestre", lambda: "resumo mestre")

    import asyncio

    asyncio.run(bot_telegram.mestre(update, context))

    mensagem = update.message.reply_text.await_args.args[0]
    assert mensagem == "resumo mestre"


def test_validar_sol_fluxos(monkeypatch):
    update = FakeUpdate()
    context = FakeContext()
    monkeypatch.setattr(bot_telegram, "obter_ultimos_trades_paper", lambda symbol, limite=30: [])

    import asyncio

    asyncio.run(bot_telegram.validar_sol(update, context))
    assert "Ainda não há trades paper fechados suficientes" in update.message.reply_text.await_args_list[-1].args[0]

    update_ok = FakeUpdate()
    monkeypatch.setattr(
        bot_telegram,
        "obter_ultimos_trades_paper",
        lambda symbol, limite=30: [
            {"timestamp": "2026-01-01", "resultado": "GANHO", "lucro_percent": 2.0, "lucro_reais": 20.0, "filtros_aplicados": True}
        ],
    )
    monkeypatch.setattr(bot_telegram, "calcular_metricas_trade_history", lambda trades: {"profit_factor": 1.5, "win_rate": 60.0, "drawdown_max": 2.0, "total": 1})
    from unittest.mock import MagicMock

    reg_mock = MagicMock(return_value=True)
    monkeypatch.setattr(bot_telegram, "registrar_validacao_sol", reg_mock)
    asyncio.run(bot_telegram.validar_sol(update_ok, context))
    assert "SOL validada" in update_ok.message.reply_text.await_args_list[-1].args[0]
    assert reg_mock.called


def test_stats_e_reset(monkeypatch):
    update = FakeUpdate()
    context = FakeContext()
    monkeypatch.setattr(bot_telegram, "obter_estatisticas", lambda: None)

    import asyncio

    asyncio.run(bot_telegram.stats(update, context))
    assert "Nenhum trade registrado" in update.message.reply_text.await_args_list[-1].args[0]

    update_ok = FakeUpdate()
    monkeypatch.setattr(
        bot_telegram,
        "obter_estatisticas",
        lambda: {
            "total": 2,
            "win_rate": 50.0,
            "lucro_total": 1.5,
            "score_vencedores": 8.0,
            "score_perdedores": 4.0,
            "chance_alto": 75.0,
        },
    )
    asyncio.run(bot_telegram.stats(update_ok, context))
    assert "Estatísticas do Trader" in update_ok.message.reply_text.await_args_list[-1].args[0]

    update_reset = FakeUpdate()
    asyncio.run(bot_telegram.reset_stats(update_reset, context))
    assert "Tem certeza" in update_reset.message.reply_text.await_args_list[-1].args[0]

    query_confirm = SimpleNamespace(callback_query=FakeCallbackQuery("confirm_reset"))
    from unittest.mock import MagicMock

    reset_mock = MagicMock(return_value=True)
    monkeypatch.setattr(bot_telegram, "reset_db", reset_mock)
    asyncio.run(bot_telegram.reset_stats_callback(query_confirm, context))
    assert query_confirm.callback_query.edit_message_text.await_count == 1

    query_cancel = SimpleNamespace(callback_query=FakeCallbackQuery("cancel_reset"))
    asyncio.run(bot_telegram.reset_stats_callback(query_cancel, context))
    assert query_cancel.callback_query.edit_message_text.await_count == 1


def test_paper_stats_abertos_trades_log_mestre(monkeypatch):
    update = FakeUpdate()
    context = FakeContext()
    monkeypatch.setattr(bot_telegram, "obter_paper_stats", lambda symbol: None)

    import asyncio

    asyncio.run(bot_telegram.paper_stats(update, context))
    assert "Nenhum trade paper encerrado" in update.message.reply_text.await_args_list[-1].args[0]

    monkeypatch.setattr(
        bot_telegram,
        "obter_paper_stats",
        lambda symbol: {
            "todas": {
                "profit_factor": 1.2,
                "win_rate": 55.0,
                "lucro_total_percent": 3.0,
                "lucro_total_reais": 30.0,
                "total": 10,
                "rr_medio": 1.1,
            },
            "filtradas": {
                "profit_factor": 1.4,
                "win_rate": 60.0,
                "lucro_total_percent": 4.0,
                "lucro_total_reais": 40.0,
                "total": 6,
                "rr_medio": 1.3,
            },
        },
    )
    update_ok = FakeUpdate()
    asyncio.run(bot_telegram.paper_stats(update_ok, context))
    assert "Performance com Filtros" in update_ok.message.reply_text.await_args_list[-1].args[0]

    monkeypatch.setattr(bot_telegram, "buscar_trades_paper", lambda limite=10, symbol=None: [])
    update_trades = FakeUpdate()
    asyncio.run(bot_telegram.paper_trades(update_trades, context))
    assert "Nenhum trade paper encontrado" in update_trades.message.reply_text.await_args_list[-1].args[0]

    monkeypatch.setattr(
        bot_telegram,
        "buscar_trades_paper",
        lambda limite=10, symbol=None: [
            {
                "id": 1,
                "symbol": "SOLUSDT",
                "direcao": "COMPRA",
                "entrada": 100.0,
                "saida": 110.0,
                "lucro_percent": 10.0,
                "status": "closed",
            }
        ],
    )
    update_trades_ok = FakeUpdate()
    asyncio.run(bot_telegram.paper_trades(update_trades_ok, context))
    assert "Últimos 10 Trades Paper" in update_trades_ok.message.reply_text.await_args_list[-1].args[0]

    monkeypatch.setattr(bot_telegram, "buscar_ultimos_decision_logs", lambda limite=10: [])
    update_log = FakeUpdate()
    asyncio.run(bot_telegram.paper_log(update_log, context))
    assert "Nenhum registro de decisão" in update_log.message.reply_text.await_args_list[-1].args[0]

    monkeypatch.setattr(
        bot_telegram,
        "buscar_ultimos_decision_logs",
        lambda limite=10: [
            {
                "timestamp": "2026-01-01",
                "symbol": "SOLUSDT",
                "decisao": "TRADE_ABERTO",
                "motivo": "abriu",
                "bloqueado_por": "N/A",
                "fonte_dados": "BINANCE",
            }
        ],
    )
    update_log_ok = FakeUpdate()
    asyncio.run(bot_telegram.paper_log(update_log_ok, context))
    assert "TRADE_ABERTO" in update_log_ok.message.reply_text.await_args_list[-1].args[0]

    monkeypatch.setattr(bot_telegram, "gerar_resumo_mestre", lambda: "resumo mestre")
    update_mestre = FakeUpdate()
    asyncio.run(bot_telegram.mestre(update_mestre, context))
    assert update_mestre.message.reply_text.await_args_list[-1].args[0] == "resumo mestre"


def test_comando_backtest_e_paper_abertos(monkeypatch):
    import asyncio
    import sys

    fake_backtester = SimpleNamespace(
        baixar_dados_historicos=lambda: _df_market(),
        executar_backtest=lambda df: {"summary": {"total_trades": 1, "win_rate": 50.0, "lucro_total_percent": 1.0, "lucro_total_valor": 10.0, "profit_factor": 1.2, "drawdown_max_percent": 2.0, "media_rr": 1.0, "sequencia_maxima_perdas": 1}},
        gerar_relatorio_backtest=lambda resultado: resultado,
        salvar_relatorio=lambda resultado, caminho=None: True,
    )
    monkeypatch.setitem(sys.modules, "backtester", fake_backtester)
    update = FakeUpdate()
    context = FakeContext()
    asyncio.run(bot_telegram.comando_backtest(update, context))
    assert "Backtest concluído" in update.message.reply_text.await_args_list[-1].args[0]

    monkeypatch.setattr(bot_telegram, "obter_trades_paper_abertos", lambda symbol: [])
    update_abertos = FakeUpdate()
    asyncio.run(bot_telegram.paper_abertos(update_abertos, context))
    assert "Não há trades paper abertos" in update_abertos.message.reply_text.await_args_list[-1].args[0]

    monkeypatch.setattr(
        bot_telegram,
        "obter_trades_paper_abertos",
        lambda symbol: [
            {
                "id": 1,
                "symbol": "SOLUSDT",
                "direcao": "COMPRA",
                "entrada": 100.0,
                "stop_loss": 95.0,
                "take_profit": 110.0,
                "quantidade": 1.0,
                "valor_arriscado": 10.0,
                "aberto_em": "2026-01-01T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr(bot_telegram, "_obter_preco_atual_referencia", lambda symbol: (105.0, "BINANCE"))
    update_abertos_ok = FakeUpdate()
    asyncio.run(bot_telegram.paper_abertos(update_abertos_ok, context))
    assert "Trades Paper Abertos" in update_abertos_ok.message.reply_text.await_args_list[-1].args[0]


def test_trade_flow_completo(monkeypatch):
    import asyncio

    update = FakeUpdate()
    context = FakeContext()
    asyncio.run(bot_telegram.trade_start(update, context))
    assert update.message.reply_text.await_count == 1
    assert "compra" in update.message.reply_text.await_args_list[-1].kwargs["reply_markup"].inline_keyboard[0][0].text.lower()

    query_update = FakeUpdate(callback_data="COMPRA")
    asyncio.run(bot_telegram.trade_direcao(query_update, context))
    assert context.user_data["direcao"] == "COMPRA"
    assert query_update.callback_query.edit_message_text.await_count == 1

    query_update2 = FakeUpdate(callback_data="GANHO")
    asyncio.run(bot_telegram.trade_resultado(query_update2, context))
    assert context.user_data["resultado"] == "GANHO"

    score_update_invalid = FakeUpdate(text="abc")
    asyncio.run(bot_telegram.trade_score(score_update_invalid, context))
    assert "Valor inválido" in score_update_invalid.message.reply_text.await_args_list[-1].args[0]

    score_update = FakeUpdate(text="8")
    asyncio.run(bot_telegram.trade_score(score_update, context))
    assert context.user_data["score"] == 8

    lucro_update_invalid = FakeUpdate(text="x")
    asyncio.run(bot_telegram.trade_lucro(lucro_update_invalid, context))
    assert "Valor inválido" in lucro_update_invalid.message.reply_text.await_args_list[-1].args[0]

    lucro_update = FakeUpdate(text="1.5")
    asyncio.run(bot_telegram.trade_lucro(lucro_update, context))
    assert context.user_data["lucro_percent"] == 1.5

    from unittest.mock import MagicMock

    salvar_mock = MagicMock(return_value=True)
    monkeypatch.setattr(bot_telegram, "salvar_trade", salvar_mock)
    rr_update = FakeUpdate(text="2.0")
    asyncio.run(bot_telegram.trade_rr(rr_update, context))
    assert salvar_mock.await_count == 1 or salvar_mock.called
    assert "Trade registrado com sucesso" in rr_update.message.reply_text.await_args_list[-1].args[0]

    cancel_update = FakeUpdate()
    asyncio.run(bot_telegram.trade_cancel(cancel_update, context))
    assert "Registro cancelado" in cancel_update.message.reply_text.await_args_list[-1].args[0]


def test_vigia_status_parar_monitorar_preco(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    df = pd.DataFrame(
        {
            "open": [100.0, 100.0],
            "high": [100.0, 100.0],
            "low": [100.0, 100.0],
            "close": [100.0, 100.0],
            "volume": [1000.0, 1000.0],
            "timestamp": pd.date_range("2026-01-01", periods=2, freq="h"),
        }
    )
    df.attrs["fonte_dados"] = "BINANCE"
    job_queue = FakeJobQueue()
    context = FakeContext(job_queue=job_queue)
    update = FakeUpdate()

    monkeypatch.setattr(bot_telegram, "baixar_dados_btc", lambda: df)
    monkeypatch.setattr(bot_telegram, "classificar_regime", lambda d: {"regime": "BULL", "adx": 25, "volatilidade": "NORMAL"})
    monkeypatch.setattr(bot_telegram, "extrair_swing_high_low", lambda d, p: (100.0, 100.0))
    monkeypatch.setattr(bot_telegram, "obter_funding_info", lambda: "0.01%")
    monkeypatch.setattr(bot_telegram, "tomar_decisao", lambda d: {"rsi": 50, "volume_status": "NEUTRO", "motivo": "ok", "take_profit": 121.0, "rr": 2.0, "direcao": "COMPRA", "entrada": 100.0, "stop_loss": 95.0, "zona_entrada_ideal": 100.0, "decisao": "COMPRA", "score": 8})
    monkeypatch.setattr(bot_telegram, "extrair_fvg_bearish_acima", lambda d, p: (121.0, 125.0))
    monkeypatch.setattr(bot_telegram, "aplicar_bloqueio_risco", lambda decisao_info, capital=10000, risco_percentual=1.0: {"limite_diario_atingido": False, "sequencia_perdas_atingida": False, "risco_percentual": 1.0, "valor_arriscado": 100.0, "quantidade": 0.01})
    monkeypatch.setattr(bot_telegram, "esta_em_killzone", lambda: True)
    monkeypatch.setattr(bot_telegram, "KILLZONE_BTC", False)
    monkeypatch.setattr(bot_telegram, "contexto_tempo", lambda dist, df: "15m")
    dec_mock = MagicMock()
    monkeypatch.setattr(bot_telegram, "registrar_decisao_observabilidade", dec_mock)
    bot_telegram.vigia_ativo = False
    bot_telegram.ultimo_regime_vigia = None
    bot_telegram.ultimo_alerta_timestamp = None

    asyncio.run(bot_telegram.ativar_vigia(update, context))
    assert job_queue.calls
    assert bot_telegram.vigia_ativo is True

    status_update = FakeUpdate()
    asyncio.run(bot_telegram.status_vigia(status_update, context))
    assert "Vigia" in status_update.message.reply_text.await_args_list[-1].args[0]

    asyncio.run(bot_telegram.monitorar_preco(context))
    assert context.bot.send_message.await_count == 1

    asyncio.run(bot_telegram.monitorar_preco(context))
    assert context.bot.send_message.await_count == 1

    par_update = FakeUpdate()
    asyncio.run(bot_telegram.parar_vigia(par_update, context))
    assert "Monitoramento parado" in par_update.message.reply_text.await_args_list[-1].args[0]


def test_monitorar_preco_regime_change_killzone_e_estrutura(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    df = _df_market()
    job_queue = FakeJobQueue({"vigia_btc": [FakeJob("vigia_btc")]})
    context = FakeContext(job_queue=job_queue)
    monkeypatch.setattr(bot_telegram, "baixar_dados_btc", lambda: df)
    monkeypatch.setattr(bot_telegram, "classificar_regime", lambda d: {"regime": "BEAR", "adx": 22, "volatilidade": "NORMAL"})
    monkeypatch.setattr(bot_telegram, "extrair_swing_high_low", lambda d, p: (120.0, 80.0))
    monkeypatch.setattr(bot_telegram, "KILLZONE_BTC", True)
    monkeypatch.setattr(bot_telegram, "esta_em_killzone", lambda: False)
    monkeypatch.setattr(bot_telegram, "vigia_ativo", True)
    bot_telegram.ultimo_regime_vigia = "BULL"
    bot_telegram.ultimo_alerta_timestamp = None
    dec_mock = MagicMock()
    monkeypatch.setattr(bot_telegram, "registrar_decisao_observabilidade", dec_mock)

    asyncio.run(bot_telegram.monitorar_preco(context))
    assert job_queue.jobs["vigia_btc"][0].removed is True
    assert len(job_queue.calls) == 1

    requeued = job_queue.calls[0]
    assert requeued["name"] == "vigia_btc"
    assert requeued["data"] == {
        "chat_id": context.job.data["chat_id"],
        "user_id": context.job.data["user_id"],
        "chat_type": context.job.data["chat_type"],
    }

    novo_contexto = FakeContext(
        job_queue=job_queue,
        chat_id=requeued["data"]["chat_id"],
        user_id=requeued["data"]["user_id"],
        chat_type=requeued["data"]["chat_type"],
    )
    monkeypatch.setattr(bot_telegram, "KILLZONE_BTC", False)
    fetch_requeued = MagicMock(return_value=df)
    monkeypatch.setattr(bot_telegram, "baixar_dados_btc", fetch_requeued)
    asyncio.run(bot_telegram.monitorar_preco(novo_contexto))
    assert fetch_requeued.called
    assert dec_mock.call_args_list

    job_queue_bloqueado = FakeJobQueue({"vigia_btc": [FakeJob("vigia_btc")]})
    contexto_bloqueado = FakeContext(job_queue=job_queue_bloqueado, user_id=999, chat_id=123, chat_type="private")
    fetch_mock = MagicMock(return_value=df)
    monkeypatch.setattr(bot_telegram, "baixar_dados_btc", fetch_mock)
    asyncio.run(bot_telegram.monitorar_preco(contexto_bloqueado))
    fetch_mock.assert_not_called()


def test_obter_contexto_risco_aplicar_e_formatadores(monkeypatch, temp_db_path):
    monkeypatch.setattr(bot_telegram, "DB_NAME", temp_db_path, raising=False)
    with sqlite3.connect(temp_db_path) as conn:
        conn.execute("CREATE TABLE trades (resultado TEXT, lucro_percent REAL, timestamp TEXT)")
        conn.execute("INSERT INTO trades VALUES (?, ?, ?)", ("GANHO", 10.0, "2026-01-01T00:00:00+00:00"))
        conn.execute("INSERT INTO trades VALUES (?, ?, ?)", ("PERDA", -5.0, "2026-01-01T00:00:00+00:00"))
        conn.commit()

    monkeypatch.setattr(bot_telegram, "calcular_tamanho_posicao", lambda capital, risco_percentual, entrada, stop: (0.5, 50.0))
    monkeypatch.setattr(bot_telegram, "verificar_limite_diario", lambda capital, perdas_hoje: False)
    monkeypatch.setattr(bot_telegram, "verificar_sequencia_perdas", lambda historico: False)
    monkeypatch.setattr(bot_telegram, "validar_e_calcular", None)
    contexto = bot_telegram.obter_contexto_risco({"entrada": 100.0, "stop_loss": 95.0, "symbol": "SOLUSDT", "regime": "BULL", "adx": 25, "volume_status": "NEUTRO", "fonte_dados": "BINANCE"})
    assert contexto["quantidade"] == 0.5
    assert contexto["valor_arriscado"] == 50.0
    decisao_sem_bloqueio = {"entrada": 100.0, "stop_loss": 95.0, "symbol": "SOLUSDT"}
    contexto_aplicado = bot_telegram.aplicar_bloqueio_risco(decisao_sem_bloqueio)
    assert contexto_aplicado is not None
    assert contexto_aplicado["quantidade"] == contexto["quantidade"]
    assert contexto_aplicado["valor_arriscado"] == contexto["valor_arriscado"]
    assert "decisao" not in decisao_sem_bloqueio

    monkeypatch.setattr(bot_telegram, "validar_e_calcular", lambda **kwargs: {"aprovado": False, "valor_arriscado": 10.0, "motivo": "bloqueado"})
    contexto_bloq = bot_telegram.obter_contexto_risco({"entrada": 100.0, "stop_loss": 95.0, "symbol": "SOLUSDT", "regime": "BULL", "adx": 25, "volume_status": "NEUTRO", "fonte_dados": "BINANCE"})
    assert contexto_bloq["bloqueado"] is True

    assert bot_telegram.formatar_linha_risco({"risco_percentual": 1.0, "valor_arriscado": 100.0, "quantidade": 0.123456}) is not None
    assert "ADX" in bot_telegram.formatar_adx_linha({"adx": 22, "regime": "CHOP"})
    assert "RSI" in bot_telegram.formatar_rsi_linha(50, "Neutro")


def test_obter_dados_risco_historico(monkeypatch, temp_db_path):
    monkeypatch.setattr(bot_telegram, "DB_NAME", temp_db_path, raising=False)
    with sqlite3.connect(temp_db_path) as conn:
        conn.execute("CREATE TABLE trades (resultado TEXT, lucro_percent REAL, timestamp TEXT)")
        hoje = bot_telegram.datetime.now().isoformat()
        conn.execute("INSERT INTO trades VALUES (?, ?, ?)", ("PERDA", -10.0, hoje))
        conn.execute("INSERT INTO trades VALUES (?, ?, ?)", ("GANHO", 5.0, hoje))
        conn.commit()

    perdas, historico = bot_telegram.obter_dados_risco_historico(10000)
    assert perdas > 0
    assert historico == ["PERDA", "GANHO"]


def test_main_registra_handlers_e_reconecta(monkeypatch):
    calls = {}

    class FakeApp:
        def __init__(self):
            self.handlers = []
            self.run_calls = 0

        def add_handler(self, handler):
            self.handlers.append(handler)

        def run_polling(self):
            self.run_calls += 1
            if self.run_calls == 1:
                raise httpx.ConnectError("boom", request=None)
            if self.run_calls == 2:
                raise RuntimeError("boom2")

    class FakeBuilder:
        def __init__(self):
            self._app = FakeApp()

        def token(self, value):
            calls["token"] = value
            return self

        def request(self, value):
            calls["request"] = value
            return self

        def job_queue(self, value):
            calls["job_queue"] = value
            return self

        def build(self):
            return self._app

    fake_builder = FakeBuilder()
    monkeypatch.setattr(bot_telegram.Application, "builder", lambda: fake_builder)
    monkeypatch.setattr(bot_telegram, "JobQueue", lambda: object())
    monkeypatch.setattr(bot_telegram, "init_db", lambda: True)
    monkeypatch.setattr(bot_telegram.time, "sleep", lambda s: None)
    monkeypatch.setattr(bot_telegram.logging, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(bot_telegram.logging, "info", lambda *args, **kwargs: None)
    import config as bot_config

    monkeypatch.setattr(bot_telegram, "TELEGRAM_AUTHORIZED_IDS", {123})
    monkeypatch.setattr(bot_config, "TELEGRAM_BOT_TOKEN", "token-teste")
    monkeypatch.setattr(bot_config, "TELEGRAM_AUTHORIZED_IDS", {123})
    monkeypatch.setattr(bot_telegram, "TELEGRAM_BOT_TOKEN", "token-teste")

    bot_telegram.main()

    assert calls["token"] == "token-teste"
    assert len(fake_builder._app.handlers) >= 10
    assert fake_builder._app.run_calls >= 2


def test_obter_funding_info_e_analise_spot_sem_short(monkeypatch):
    df = _df_market()
    monkeypatch.setattr(bot_telegram, "obter_funding_rate", lambda: None)
    assert bot_telegram.obter_funding_info() == "Indisponível"

    monkeypatch.setattr(bot_telegram, "baixar_dados_btc", lambda: df)
    monkeypatch.setattr(
        bot_telegram,
        "tomar_decisao",
        lambda d: {
            "decisao": "VENDA",
            "score": 7,
            "rr": 1.8,
            "volume_status": "ALTO",
            "motivo": "short",
            "zona_entrada_ideal": 100.0,
            "direcao": "VENDA",
            "entrada": 99.5,
            "stop_loss": 101.0,
            "take_profit": 95.0,
            "rsi": 42,
            "rsi_status": "Neutro",
            "regime": "BEAR",
        },
    )
    monkeypatch.setattr(bot_telegram, "aplicar_bloqueio_risco", lambda decisao_info, capital=10000, risco_percentual=1.0: None)
    monkeypatch.setattr(bot_telegram, "classificar_regime", lambda d: {"regime": "BEAR", "adx": 26, "volatilidade": "NORMAL"})
    monkeypatch.setattr(bot_telegram, "tendencia_geral", lambda d: "TREND")
    monkeypatch.setattr(bot_telegram, "ultimos_swings", lambda d: "SWINGS")
    monkeypatch.setattr(bot_telegram, "identificar_fvg", lambda d: "FVG")
    monkeypatch.setattr(bot_telegram, "MODO_OPERACAO", "SPOT")

    mensagem = bot_telegram.obter_analise()
    assert "Modo Spot ativo" in mensagem
    assert "*Entrada Sugerida:* N/A" in mensagem
    assert "*Stop Loss:* N/A" in mensagem


def test_obter_dados_resumidos_chop(monkeypatch):
    df = _df_market()
    monkeypatch.setattr(bot_telegram, "baixar_dados_btc", lambda: df)
    monkeypatch.setattr(
        bot_telegram,
        "tomar_decisao",
        lambda d: {
            "decisao": "AGUARDAR",
            "score": 0,
            "rr": None,
            "volume_status": "NEUTRO",
            "motivo": "lateral",
            "zona_entrada_ideal": None,
            "direcao": None,
            "entrada": None,
            "stop_loss": None,
            "take_profit": None,
            "rsi": None,
            "rsi_status": None,
            "regime": "CHOP",
        },
    )
    monkeypatch.setattr(bot_telegram, "classificar_regime", lambda d: {"regime": "CHOP", "adx": 18, "volatilidade": "LATERAL"})
    monkeypatch.setattr(bot_telegram, "tendencia_geral", lambda d: "TREND")
    monkeypatch.setattr(bot_telegram, "identificar_fvg", lambda d: "FVG")
    monkeypatch.setattr(bot_telegram, "obter_funding_rate", lambda: None)

    dados = bot_telegram.obter_dados_resumidos()
    assert dados["veredito"] == "AGUARDAR (MERCADO LATERAL)"
    assert dados["funding_rate"] == "Indisponível"


def test_comando_backtest_falha(monkeypatch):
    import asyncio
    import sys

    fake_backtester = SimpleNamespace(
        baixar_dados_historicos=lambda: (_ for _ in ()).throw(RuntimeError("falha download")),
        executar_backtest=lambda df: {},
        gerar_relatorio_backtest=lambda resultado: resultado,
        salvar_relatorio=lambda resultado, caminho=None: True,
    )
    monkeypatch.setitem(sys.modules, "backtester", fake_backtester)
    update = FakeUpdate()
    context = FakeContext()

    asyncio.run(bot_telegram.comando_backtest(update, context))
    assert "Falha ao executar o backtest" in update.message.reply_text.await_args_list[-1].args[0]


def test_monitorar_preco_bloqueios_de_risco_killzone_e_cooldown(monkeypatch):
    import asyncio

    df = pd.DataFrame(
        {
            "open": [100.0, 100.0],
            "high": [100.2, 100.2],
            "low": [99.8, 99.8],
            "close": [100.0, 100.0],
            "volume": [1000.0, 1000.0],
            "timestamp": pd.date_range("2026-01-01", periods=2, freq="h"),
        }
    )
    df.attrs["fonte_dados"] = "BINANCE"
    context = FakeContext(job_queue=FakeJobQueue({"vigia_btc": [FakeJob("vigia_btc")]}))
    monkeypatch.setattr(bot_telegram, "baixar_dados_btc", lambda: df)
    monkeypatch.setattr(bot_telegram, "classificar_regime", lambda d: {"regime": "BULL", "adx": 25, "volatilidade": "NORMAL"})
    monkeypatch.setattr(bot_telegram, "extrair_swing_high_low", lambda d, p: (100.3, 99.7))
    monkeypatch.setattr(bot_telegram, "extrair_fvg_bearish_acima", lambda d, p: (101.0, 102.0))
    monkeypatch.setattr(bot_telegram, "tomar_decisao", lambda d: {"rsi": 50, "rsi_status": "Neutro", "volume_status": "ALTO", "motivo": "ok", "take_profit": 101.0, "rr": 2.0, "direcao": "COMPRA", "entrada": 100.0, "stop_loss": 99.0, "zona_entrada_ideal": 100.0, "decisao": "COMPRA", "score": 8})
    monkeypatch.setattr(bot_telegram, "contexto_tempo", lambda dist, d: "15m")
    monkeypatch.setattr(bot_telegram, "obter_funding_info", lambda: "0.01%")
    monkeypatch.setattr(bot_telegram, "vigia_ativo", True)
    monkeypatch.setattr(bot_telegram, "ultimo_regime_vigia", "BULL")
    monkeypatch.setattr(bot_telegram, "KILLZONE_BTC", True)
    monkeypatch.setattr(bot_telegram, "esta_em_killzone", lambda: False)
    monkeypatch.setattr(bot_telegram, "ultimo_alerta_timestamp", None)
    from unittest.mock import MagicMock

    log_mock = MagicMock()
    monkeypatch.setattr(bot_telegram, "registrar_decisao_observabilidade", log_mock)

    risco_state = {"modo": "daily"}

    def _aplicar_risco(*args, **kwargs):
        if risco_state["modo"] == "daily":
            return {
                "limite_diario_atingido": True,
                "sequencia_perdas_atingida": False,
                "risco_percentual": 1.0,
                "valor_arriscado": 100.0,
                "quantidade": 0.01,
            }
        if risco_state["modo"] == "seq":
            return {
                "limite_diario_atingido": False,
                "sequencia_perdas_atingida": True,
                "risco_percentual": 1.0,
                "valor_arriscado": 100.0,
                "quantidade": 0.01,
            }
        return {
            "limite_diario_atingido": False,
            "sequencia_perdas_atingida": False,
            "risco_percentual": 1.0,
            "valor_arriscado": 100.0,
            "quantidade": 0.01,
        }

    monkeypatch.setattr(bot_telegram, "aplicar_bloqueio_risco", _aplicar_risco)

    asyncio.run(bot_telegram.monitorar_preco(context))
    assert context.bot.send_message.await_count == 0

    risco_state["modo"] = "seq"
    asyncio.run(bot_telegram.monitorar_preco(context))
    assert context.bot.send_message.await_count == 0

    risco_state["modo"] = "ok"
    asyncio.run(bot_telegram.monitorar_preco(context))
    assert context.bot.send_message.await_count == 0

    monkeypatch.setattr(bot_telegram, "KILLZONE_BTC", False)
    bot_telegram.ultimo_alerta_timestamp = bot_telegram.datetime.now(bot_telegram.timezone.utc).timestamp()
    asyncio.run(bot_telegram.monitorar_preco(context))
    assert context.bot.send_message.await_count == 0


def test_vigia_status_parar_e_ativar_com_estado_inativo(monkeypatch):
    import asyncio

    job_queue = FakeJobQueue({"vigia_btc": [FakeJob("vigia_btc")]})
    context = FakeContext(job_queue=job_queue)
    update = FakeUpdate()
    monkeypatch.setattr(bot_telegram, "vigia_ativo", False)

    asyncio.run(bot_telegram.ativar_vigia(update, context))
    assert "Vigia já está ativo" in update.message.reply_text.await_args_list[-1].args[0]

    update_status = FakeUpdate()
    monkeypatch.setattr(bot_telegram, "vigia_ativo", False)
    monkeypatch.setattr(bot_telegram, "baixar_dados_btc", lambda: pd.DataFrame())
    asyncio.run(bot_telegram.status_vigia(update_status, context))
    assert "DESATIVADO" in update_status.message.reply_text.await_args_list[-1].args[0]

    update_parar = FakeUpdate()
    empty_context = FakeContext(job_queue=FakeJobQueue())
    asyncio.run(bot_telegram.parar_vigia(update_parar, empty_context))
    assert "Nenhum monitoramento ativo" in update_parar.message.reply_text.await_args_list[-1].args[0]


def test_trade_fluxos_invalidos_e_paper_abertos_sem_preco(monkeypatch):
    import asyncio

    update_score = FakeUpdate(text="11")
    context = FakeContext()
    asyncio.run(bot_telegram.trade_score(update_score, context))
    assert "número entre 0 e 10" in update_score.message.reply_text.await_args_list[-1].args[0]

    context.user_data.update({"direcao": "COMPRA", "resultado": "GANHO", "score": 8, "lucro_percent": 1.5})
    update_rr = FakeUpdate(text="abc")
    asyncio.run(bot_telegram.trade_rr(update_rr, context))
    assert "Valor inválido" in update_rr.message.reply_text.await_args_list[-1].args[0]

    monkeypatch.setattr(
        bot_telegram,
        "obter_trades_paper_abertos",
        lambda symbol: [
            {
                "id": 2,
                "symbol": "SOLUSDT",
                "direcao": "VENDA",
                "entrada": None,
                "stop_loss": None,
                "take_profit": None,
                "aberto_em": None,
            }
        ],
    )
    monkeypatch.setattr(bot_telegram, "_obter_preco_atual_referencia", lambda symbol: (None, "N/D"))
    update_abertos = FakeUpdate()
    asyncio.run(bot_telegram.paper_abertos(update_abertos, context))
    assert "N/D" in update_abertos.message.reply_text.await_args_list[-1].args[0]


def test_paper_status_erro_e_resumo_vazio(monkeypatch):
    import asyncio

    update = FakeUpdate()
    context = FakeContext()
    monkeypatch.setattr(bot_telegram, "ULTIMO_LOG_CACHE", {})
    monkeypatch.setattr(bot_telegram, "buscar_ultimo_decision_log", lambda modos=None: {"timestamp": "2026-01-01T00:00:00+00:00", "decisao": "AGUARDAR", "motivo": "ok", "preco": 123.0, "fonte_dados": "BINANCE"})
    monkeypatch.setattr(bot_telegram, "_obter_preco_atual_referencia", lambda symbol: (123.0, "BINANCE"))
    monkeypatch.setattr(bot_telegram, "contar_trades_abertos_paper", lambda symbol: 0)
    monkeypatch.setattr(bot_telegram, "contar_trades_fechados_hoje", lambda symbol: 0)
    monkeypatch.setattr(bot_telegram, "obter_resumo_risco", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    asyncio.run(bot_telegram.paper_status(update, context))
    assert "Falha ao montar o status do paper trading" in update.message._status_message.edit_text.await_args_list[-1].args[0]
