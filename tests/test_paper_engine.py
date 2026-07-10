import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

import config

import paper_engine


@pytest.fixture(autouse=True)
def _autorizar_chat_teste(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_AUTHORIZED_IDS", {123})
    monkeypatch.setattr(config, "TELEGRAM_AUTHORIZED_CHAT_IDS", {123})
    monkeypatch.setattr(config, "TELEGRAM_GROUPS_ENABLED", False)
    yield


class FakeContext:
    def __init__(self, chat_id=123, user_id=123, chat_type="private"):
        self.job = SimpleNamespace(data={"chat_id": chat_id, "user_id": user_id, "chat_type": chat_type})
        self.bot = SimpleNamespace(send_message=AsyncMock())


def _df_monitoramento_compra():
    df = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [102.0, 103.0, 110.0],
            "low": [99.0, 100.0, 95.0],
            "close": [101.0, 102.0, 104.0],
            "volume": [1000.0, 1000.0, 1000.0],
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="h"),
        }
    )
    df.attrs["fonte_dados"] = "BINANCE"
    return df


def _df_monitoramento_venda():
    df = pd.DataFrame(
        {
            "open": [100.0, 99.0, 98.0],
            "high": [101.0, 100.0, 103.0],
            "low": [99.0, 96.0, 90.0],
            "close": [99.0, 98.0, 97.0],
            "volume": [1000.0, 1000.0, 1000.0],
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="h"),
        }
    )
    df.attrs["fonte_dados"] = "BINANCE"
    return df


def test_fmt_num_and_caches(monkeypatch):
    assert paper_engine.fmt_num(None) == "N/A"
    assert paper_engine.fmt_num("abc") == "N/A"
    assert paper_engine.fmt_num(12.3456, ".1f") == "12.3"

    paper_engine.ULTIMO_PRECO_CACHE.clear()
    paper_engine.ULTIMO_LOG_CACHE.clear()
    paper_engine.atualizar_cache_preco("SOLUSDT", 100.5, "BINANCE", "PAPER_SOL")
    paper_engine.atualizar_cache_log({"modo": "PAPER_SOL", "symbol": "SOLUSDT", "decisao": "AGUARDAR"})

    assert "SOLUSDT" in paper_engine.ULTIMO_PRECO_CACHE
    assert "PAPER_SOL" in paper_engine.ULTIMO_LOG_CACHE
    assert paper_engine.ULTIMO_LOG_CACHE["SOLUSDT"]["decisao"] == "AGUARDAR"


def test_atualizar_cache_preco_e_log_nulos():
    paper_engine.ULTIMO_PRECO_CACHE.clear()
    paper_engine.ULTIMO_LOG_CACHE.clear()
    paper_engine.atualizar_cache_preco("SOLUSDT", None, "BINANCE", "PAPER_SOL")
    paper_engine.atualizar_cache_log(None)
    assert paper_engine.ULTIMO_PRECO_CACHE == {}
    assert paper_engine.ULTIMO_LOG_CACHE == {}


def test_obter_fonte_dados_df():
    vazio = pd.DataFrame()
    assert paper_engine.obter_fonte_dados_df(None) == "N/D"
    assert paper_engine.obter_fonte_dados_df(vazio) == "N/D"
    df = pd.DataFrame({"close": [1]})
    assert paper_engine.obter_fonte_dados_df(df) == "BINANCE"
    df.attrs["fonte_dados"] = "YAHOO"
    assert paper_engine.obter_fonte_dados_df(df) == "YAHOO"


def test_registrar_decisao_observabilidade_sucesso_e_falha(monkeypatch):
    log_calls = []

    def fake_log_decisao(**kwargs):
        log_calls.append(kwargs)
        return True

    monkeypatch.setattr(paper_engine, "log_decisao", fake_log_decisao)
    paper_engine.ULTIMO_LOG_CACHE.clear()

    paper_engine.registrar_decisao_observabilidade(symbol="SOLUSDT", modo="PAPER_SOL", decisao="AGUARDAR")
    assert log_calls[0]["strategy_version"] == "v2_risk_safe"
    assert paper_engine.ULTIMO_LOG_CACHE["PAPER_SOL"]["symbol"] == "SOLUSDT"

    monkeypatch.setattr(paper_engine, "log_decisao", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("falha")))
    paper_engine.registrar_decisao_observabilidade(symbol="SOLUSDT", modo="PAPER_SOL", decisao="ERRO")


def test_esta_em_killzone(monkeypatch):
    class FakeDateTime:
        @staticmethod
        def now(tz=None):
            return pd.Timestamp("2026-01-01 08:30:00", tz="UTC")

    monkeypatch.setattr(paper_engine, "datetime", FakeDateTime)
    assert paper_engine.esta_em_killzone() is True

    class FakeDateTimeLate:
        @staticmethod
        def now(tz=None):
            return pd.Timestamp("2026-01-01 18:30:00", tz="UTC")

    monkeypatch.setattr(paper_engine, "datetime", FakeDateTimeLate)
    assert paper_engine.esta_em_killzone() is False


def test_avaliar_filtros_paper_compra_e_venda(monkeypatch):
    monkeypatch.setattr(paper_engine, "esta_em_killzone", lambda: True)
    aprovado, detalhes = paper_engine._avaliar_filtros_paper(
        {"direcao": "COMPRA"}, {"rsi": 50}, {"adx": 25}
    )
    assert aprovado is True
    assert detalhes == {"killzone_ok": True, "adx_ok": True, "rsi_ok": True}

    aprovado_venda, detalhes_venda = paper_engine._avaliar_filtros_paper(
        {"direcao": "VENDA"}, {"rsi": 50}, {"adx": 25}
    )
    assert aprovado_venda is True
    assert detalhes_venda["rsi_ok"] is True

    monkeypatch.setattr(paper_engine, "esta_em_killzone", lambda: False)
    aprovado_bloq, detalhes_bloq = paper_engine._avaliar_filtros_paper(
        {"direcao": "COMPRA"}, {"rsi": 50}, {"adx": 25}
    )
    assert aprovado_bloq is False
    assert detalhes_bloq["killzone_ok"] is False


def test_obter_sinal_paper_sol_sem_backtester(monkeypatch):
    monkeypatch.setattr(paper_engine, "backtester", None)
    assert paper_engine._obter_sinal_paper_sol() is None


def test_obter_sinal_paper_sol_sem_dados_e_com_erro(monkeypatch):
    fake_backtester = MagicMock()
    fake_backtester.baixar_dados_historicos.return_value = pd.DataFrame()
    monkeypatch.setattr(paper_engine, "backtester", fake_backtester)
    assert paper_engine._obter_sinal_paper_sol() is None

    fake_backtester.baixar_dados_historicos.return_value = pd.DataFrame(
        {
            "open": [1] * 220,
            "high": [2] * 220,
            "low": [0.5] * 220,
            "close": [1.5] * 220,
            "volume": [10] * 220,
            "timestamp": pd.date_range("2026-01-01", periods=220, freq="h"),
        }
    )
    fake_backtester._precomputar_contextos_otimizacao.side_effect = RuntimeError("boom")
    assert paper_engine._obter_sinal_paper_sol() is None


def test_obter_sinal_paper_sol_sucesso(monkeypatch, sample_btc_data):
    fake_backtester = MagicMock()
    fake_backtester.baixar_dados_historicos.return_value = sample_btc_data
    fake_backtester._precomputar_contextos_otimizacao.return_value = [
        {"idx": 200, "regime": "BULL", "preco_atual": 10.0, "volume_atual": 20.0, "volume_medio": 10.0, "atr": 1.0,
         "topo": 12.0, "fundo": 8.0, "amplitude": 4.0, "fvg_bearish": (11.0, 13.0), "fvg_bullish": (7.0, 9.0),
         "tail_highs": [12.0] * 20, "tail_lows": [8.0] * 20, "open_time": "2026-01-01", "close_time": "2026-01-01"}
    ]
    fake_backtester._simular_decisao_contexto.return_value = {
        "direcao": "COMPRA",
        "entrada": 10.0,
        "stop_loss": 9.0,
        "take_profit": 13.0,
        "rr": 2.0,
        "motivo": "ok",
    }
    monkeypatch.setattr(paper_engine, "backtester", fake_backtester)

    sinal = paper_engine._obter_sinal_paper_sol()
    assert sinal["direcao"] == "COMPRA"
    fake_backtester._simular_decisao_contexto.assert_called_once()


def test_obter_sinal_paper_sol_contextos_vazios_e_erro_fetch(monkeypatch, sample_btc_data):
    fake_backtester = MagicMock()
    fake_backtester.baixar_dados_historicos.return_value = sample_btc_data
    fake_backtester._precomputar_contextos_otimizacao.return_value = []
    monkeypatch.setattr(paper_engine, "backtester", fake_backtester)
    assert paper_engine._obter_sinal_paper_sol() is None

    fake_backtester.baixar_dados_historicos.side_effect = RuntimeError("boom")
    assert paper_engine._obter_sinal_paper_sol() is None


def test_monitorar_paper_sol_sem_acao(monkeypatch):
    monkeypatch.setattr(paper_engine, "PAPER_TRADING_ATIVO", False)
    contexto = FakeContext()
    asyncio.run(paper_engine.monitorar_paper_sol(contexto))
    assert contexto.bot.send_message.await_count == 0
    monkeypatch.setattr(paper_engine, "PAPER_TRADING_ATIVO", True)


def test_monitorar_paper_sol_backtester_indisponivel(monkeypatch):
    monkeypatch.setattr(paper_engine, "backtester", None)
    decisao_mock = MagicMock()
    monkeypatch.setattr(paper_engine, "registrar_decisao_observabilidade", decisao_mock)
    contexto = FakeContext()
    asyncio.run(paper_engine.monitorar_paper_sol(contexto))
    assert any(call.kwargs.get("decisao") == "ERRO" for call in decisao_mock.call_args_list)


def test_monitorar_paper_sol_sem_dados(monkeypatch):
    fake_backtester = MagicMock()
    fake_backtester.baixar_dados_historicos.return_value = pd.DataFrame()
    monkeypatch.setattr(paper_engine, "backtester", fake_backtester)
    decisao_mock = MagicMock()
    monkeypatch.setattr(paper_engine, "registrar_decisao_observabilidade", decisao_mock)
    contexto = FakeContext()
    asyncio.run(paper_engine.monitorar_paper_sol(contexto))
    assert any(call.kwargs.get("decisao") == "AGUARDAR" for call in decisao_mock.call_args_list)


def test_monitorar_paper_sol_abre_trade(monkeypatch, sample_btc_data):
    fake_backtester = MagicMock()
    fake_backtester.baixar_dados_historicos.return_value = sample_btc_data
    monkeypatch.setattr(paper_engine, "backtester", fake_backtester)
    monkeypatch.setattr(paper_engine, "obter_trades_paper_abertos", lambda symbol: [])
    monkeypatch.setattr(paper_engine, "classificar_regime", lambda df: {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"})
    monkeypatch.setattr(
        paper_engine,
        "_obter_sinal_paper_sol",
        lambda: {"direcao": "COMPRA", "entrada": 60450, "stop_loss": 60300, "take_profit": 60800, "rr": 2.0, "motivo": "teste"},
    )
    monkeypatch.setattr(paper_engine, "tomar_decisao", lambda *args, **kwargs: {"rsi": 50, "volume_status": "NEUTRO", "motivo": "ok"})
    monkeypatch.setattr(paper_engine, "esta_em_killzone", lambda: True)
    monkeypatch.setattr(paper_engine, "calcular_tamanho_posicao", lambda capital, risco_percentual, entrada, stop: (1.0, 100.0))
    registrar_trade_mock = MagicMock(return_value=321)
    decisao_mock = MagicMock()
    monkeypatch.setattr(paper_engine, "registrar_trade_paper", registrar_trade_mock)
    monkeypatch.setattr(paper_engine, "registrar_decisao_observabilidade", decisao_mock)

    contexto = FakeContext()
    asyncio.run(paper_engine.monitorar_paper_sol(contexto))

    assert registrar_trade_mock.called
    assert contexto.bot.send_message.await_count == 1
    assert any(call.kwargs.get("decisao") == "TRADE_ABERTO" for call in decisao_mock.call_args_list)


def test_monitorar_paper_sol_bloqueios_e_erros(monkeypatch, sample_btc_data):
    fake_backtester = MagicMock()
    fake_backtester.baixar_dados_historicos.return_value = sample_btc_data
    monkeypatch.setattr(paper_engine, "backtester", fake_backtester)
    monkeypatch.setattr(paper_engine, "obter_trades_paper_abertos", lambda symbol: [])
    monkeypatch.setattr(paper_engine, "classificar_regime", lambda df: {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"})
    monkeypatch.setattr(paper_engine, "tomar_decisao", lambda *args, **kwargs: {"rsi": 50, "volume_status": "NEUTRO", "motivo": "ok"})
    monkeypatch.setattr(paper_engine, "esta_em_killzone", lambda: False)
    monkeypatch.setattr(
        paper_engine,
        "_obter_sinal_paper_sol",
        lambda: {"direcao": "COMPRA", "entrada": 60450, "stop_loss": 60300, "take_profit": 60800, "rr": 2.0, "motivo": "teste"},
    )
    decisao_mock = MagicMock()
    monkeypatch.setattr(paper_engine, "registrar_decisao_observabilidade", decisao_mock)

    contexto = FakeContext()
    asyncio.run(paper_engine.monitorar_paper_sol(contexto))
    assert any(call.kwargs.get("decisao") == "BLOQUEADO_KILLZONE" for call in decisao_mock.call_args_list)

    monkeypatch.setattr(paper_engine, "esta_em_killzone", lambda: True)
    monkeypatch.setattr(paper_engine, "calcular_tamanho_posicao", lambda capital, risco_percentual, entrada, stop: (0.0, 100.0))
    decisao_mock.reset_mock()
    asyncio.run(paper_engine.monitorar_paper_sol(contexto))
    assert any(call.kwargs.get("decisao") == "BLOQUEADO_FILTRO" for call in decisao_mock.call_args_list)

    monkeypatch.setattr(paper_engine, "calcular_tamanho_posicao", lambda capital, risco_percentual, entrada, stop: (1.0, 100.0))
    monkeypatch.setattr(paper_engine, "tomar_decisao", lambda *args, **kwargs: {"rsi": 10, "volume_status": "NEUTRO", "motivo": "ok"})
    asyncio.run(paper_engine.monitorar_paper_sol(contexto))


def test_monitorar_paper_sol_trade_aberto_take_e_stop_e_filtros(monkeypatch):
    fake_backtester = MagicMock()
    fake_backtester.baixar_dados_historicos.return_value = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [102.0, 103.0, 110.0],
            "low": [99.0, 98.0, 96.0],
            "close": [101.0, 102.0, 104.0],
            "volume": [1000.0, 1000.0, 1000.0],
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="h"),
        }
    )
    monkeypatch.setattr(paper_engine, "backtester", fake_backtester)
    monkeypatch.setattr(paper_engine, "classificar_regime", lambda df: {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"})
    monkeypatch.setattr(paper_engine, "registrar_decisao_observabilidade", MagicMock())
    send_mock = AsyncMock()
    contexto = FakeContext()
    contexto.bot.send_message = send_mock

    monkeypatch.setattr(
        paper_engine,
        "obter_trades_paper_abertos",
        lambda symbol: [
            {
                "id": 1,
                "timestamp": "2026-01-01T00:00:00+00:00",
                "symbol": "SOLUSDT",
                "direcao": "COMPRA",
                "entrada": 100.0,
                "stop_loss": 95.0,
                "take_profit": 109.0,
                "quantidade": 1.0,
                "valor_arriscado": 100.0,
                "aberto_em": "2026-01-01T00:00:00+00:00",
            },
            {
                "id": 2,
                "timestamp": "2026-01-01T00:00:00+00:00",
                "symbol": "SOLUSDT",
                "direcao": "VENDA",
                "entrada": 100.0,
                "stop_loss": 105.0,
                "take_profit": 91.0,
                "quantidade": 1.0,
                "valor_arriscado": 100.0,
                "aberto_em": "2026-01-01T00:00:00+00:00",
            },
        ],
    )
    finalizar_mock = MagicMock(return_value=True)
    monkeypatch.setattr(paper_engine, "finalizar_trade_paper", finalizar_mock)
    monkeypatch.setattr(paper_engine, "esta_em_killzone", lambda: True)

    asyncio.run(paper_engine.monitorar_paper_sol(contexto))
    assert finalizar_mock.call_count == 2
    assert send_mock.await_count == 2

    fake_backtester.baixar_dados_historicos.return_value = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [102.0, 103.0, 106.0],
            "low": [99.0, 98.0, 96.0],
            "close": [101.0, 102.0, 104.0],
            "volume": [1000.0, 1000.0, 1000.0],
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="h"),
        }
    )
    monkeypatch.setattr(paper_engine, "obter_trades_paper_abertos", lambda symbol: [])
    monkeypatch.setattr(
        paper_engine,
        "_obter_sinal_paper_sol",
        lambda: {"direcao": "COMPRA", "entrada": 100.0, "stop_loss": 98.0, "take_profit": 104.0, "rr": 2.0, "motivo": "teste"},
    )
    monkeypatch.setattr(paper_engine, "tomar_decisao", lambda *args, **kwargs: {"rsi": 50, "volume_status": "NEUTRO", "motivo": "ok"})
    monkeypatch.setattr(paper_engine, "calcular_tamanho_posicao", lambda capital, risco_percentual, entrada, stop: (1.0, 100.0))
    monkeypatch.setattr(paper_engine, "_avaliar_filtros_paper", lambda sinal, decisao_info, regime_info: (False, {"killzone_ok": False, "adx_ok": True, "rsi_ok": True}))
    decisao_mock = MagicMock()
    monkeypatch.setattr(paper_engine, "registrar_decisao_observabilidade", decisao_mock)

    asyncio.run(paper_engine.monitorar_paper_sol(FakeContext()))
    assert any(call.kwargs.get("decisao") == "BLOQUEADO_FILTRO" for call in decisao_mock.call_args_list)


def test_monitorar_paper_sol_rr_baixo_e_risk_manager_indisponivel(monkeypatch, sample_btc_data):
    fake_backtester = MagicMock()
    fake_backtester.baixar_dados_historicos.return_value = sample_btc_data
    monkeypatch.setattr(paper_engine, "backtester", fake_backtester)
    monkeypatch.setattr(paper_engine, "obter_trades_paper_abertos", lambda symbol: [])
    monkeypatch.setattr(paper_engine, "classificar_regime", lambda df: {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"})
    monkeypatch.setattr(paper_engine, "esta_em_killzone", lambda: True)
    monkeypatch.setattr(
        paper_engine,
        "_obter_sinal_paper_sol",
        lambda: {"direcao": "COMPRA", "entrada": 100.0, "stop_loss": 99.5, "take_profit": 100.2, "rr": 0.4, "motivo": "teste"},
    )
    monkeypatch.setattr(paper_engine, "tomar_decisao", lambda *args, **kwargs: {"rsi": 50, "volume_status": "NEUTRO", "motivo": "ok"})
    decisao_mock = MagicMock()
    monkeypatch.setattr(paper_engine, "registrar_decisao_observabilidade", decisao_mock)

    asyncio.run(paper_engine.monitorar_paper_sol(FakeContext()))
    assert any("R/R muito baixo" in str(call.kwargs.get("motivo", "")) for call in decisao_mock.call_args_list)

    monkeypatch.setattr(paper_engine, "calcular_tamanho_posicao", None)
    fake_backtester.baixar_dados_historicos.return_value = sample_btc_data
    monkeypatch.setattr(
        paper_engine,
        "_obter_sinal_paper_sol",
        lambda: {"direcao": "COMPRA", "entrada": 100.0, "stop_loss": 98.0, "take_profit": 104.0, "rr": 2.0, "motivo": "teste"},
    )
    decisao_mock.reset_mock()
    asyncio.run(paper_engine.monitorar_paper_sol(FakeContext()))
    assert any(call.kwargs.get("decisao") == "ERRO" for call in decisao_mock.call_args_list)


def test_monitorar_paper_sol_fecha_trade_compra_e_venda(monkeypatch):
    fake_backtester = MagicMock()
    fake_backtester.baixar_dados_historicos.return_value = _df_monitoramento_compra()
    monkeypatch.setattr(paper_engine, "backtester", fake_backtester)
    monkeypatch.setattr(
        paper_engine,
        "obter_trades_paper_abertos",
        lambda symbol: [
            {
                "id": 1,
                "timestamp": "2026-01-01T00:00:00+00:00",
                "symbol": "SOLUSDT",
                "direcao": "COMPRA",
                "entrada": 100.0,
                "stop_loss": 95.0,
                "take_profit": 109.0,
                "quantidade": 1.0,
                "valor_arriscado": 100.0,
                "aberto_em": "2026-01-01T00:00:00+00:00",
            }
        ],
    )
    finalizar_mock = MagicMock(return_value=True)
    decisao_mock = MagicMock()
    monkeypatch.setattr(paper_engine, "finalizar_trade_paper", finalizar_mock)
    monkeypatch.setattr(paper_engine, "registrar_decisao_observabilidade", decisao_mock)
    monkeypatch.setattr(paper_engine, "classificar_regime", lambda df: {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"})

    contexto = FakeContext()
    asyncio.run(paper_engine.monitorar_paper_sol(contexto))
    assert finalizar_mock.called
    assert any(call.kwargs.get("decisao") == "TRADE_FECHADO" for call in decisao_mock.call_args_list)

    fake_backtester.baixar_dados_historicos.return_value = _df_monitoramento_venda()
    monkeypatch.setattr(
        paper_engine,
        "obter_trades_paper_abertos",
        lambda symbol: [
            {
                "id": 2,
                "timestamp": "2026-01-01T00:00:00+00:00",
                "symbol": "SOLUSDT",
                "direcao": "VENDA",
                "entrada": 100.0,
                "stop_loss": 105.0,
                "take_profit": 91.0,
                "quantidade": 1.0,
                "valor_arriscado": 100.0,
                "aberto_em": "2026-01-01T00:00:00+00:00",
            }
        ],
    )
    decisao_mock.reset_mock()
    asyncio.run(paper_engine.monitorar_paper_sol(contexto))
    assert any(call.kwargs.get("decisao") == "TRADE_FECHADO" for call in decisao_mock.call_args_list)


def test_monitorar_paper_sol_backtester_erro_generico(monkeypatch):
    class FakeBacktester:
        @staticmethod
        def baixar_dados_historicos(symbol):
            raise RuntimeError("boom")

    monkeypatch.setattr(paper_engine, "backtester", FakeBacktester())
    decisao_mock = MagicMock()
    monkeypatch.setattr(paper_engine, "registrar_decisao_observabilidade", decisao_mock)
    contexto = FakeContext()
    asyncio.run(paper_engine.monitorar_paper_sol(contexto))
    assert any(call.kwargs.get("decisao") == "ERRO" for call in decisao_mock.call_args_list)


def test_monitorar_paper_sol_bloqueia_usuario_nao_autorizado(monkeypatch):
    fake_backtester = MagicMock()
    fake_backtester.baixar_dados_historicos.return_value = _df_monitoramento_compra()
    monkeypatch.setattr(paper_engine, "backtester", fake_backtester)
    decisao_mock = MagicMock()
    monkeypatch.setattr(paper_engine, "registrar_decisao_observabilidade", decisao_mock)

    contexto = FakeContext(user_id=999)
    asyncio.run(paper_engine.monitorar_paper_sol(contexto))

    assert decisao_mock.call_count == 0
