from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest

import backtester


def _fake_contextos(df, start=200, count=6):
    contextos = []
    for idx in range(start, min(start + count, len(df) - 1)):
        contexto = {
            "idx": idx,
            "preco_atual": float(df.iloc[idx]["close"]),
            "volume_atual": float(df.iloc[idx]["volume"]),
            "volume_medio": 10.0,
            "atr": 5.0,
            "regime": "BULL" if idx % 2 == 0 else "BEAR",
            "topo": float(df.iloc[idx]["close"]) + 50.0,
            "fundo": float(df.iloc[idx]["close"]) - 50.0,
            "amplitude": 100.0,
            "fvg_bearish": (float(df.iloc[idx]["close"]) + 10.0, float(df.iloc[idx]["close"]) + 200.0),
            "fvg_bullish": (float(df.iloc[idx]["close"]) - 200.0, float(df.iloc[idx]["close"]) - 10.0),
            "tail_highs": [float(df.iloc[idx]["high"]) for _ in range(20)],
            "tail_lows": [float(df.iloc[idx]["low"]) for _ in range(20)],
            "open_time": str(df.iloc[idx]["open_time"]),
            "close_time": str(df.iloc[idx]["close_time"]),
        }
        contextos.append(contexto)
    return contextos


def _trade_df_buy():
    rows = 210
    base = pd.DataFrame(
        {
            "open_time": pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC"),
            "close_time": pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC"),
            "open": [100.0] * rows,
            "high": [100.0] * rows,
            "low": [100.0] * rows,
            "close": [100.0] * rows,
            "volume": [1000.0] * rows,
        }
    )
    base.loc[201, ["open", "high", "low", "close"]] = [100.0, 120.0, 99.0, 115.0]
    base.loc[202, ["open", "high", "low", "close"]] = [115.0, 121.0, 100.0, 118.0]
    return base


def _trade_df_sell():
    rows = 210
    base = pd.DataFrame(
        {
            "open_time": pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC"),
            "close_time": pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC"),
            "open": [100.0] * rows,
            "high": [100.0] * rows,
            "low": [100.0] * rows,
            "close": [100.0] * rows,
            "volume": [1000.0] * rows,
        }
    )
    base.loc[201, ["open", "high", "low", "close"]] = [100.0, 101.0, 80.0, 90.0]
    base.loc[202, ["open", "high", "low", "close"]] = [90.0, 95.0, 79.0, 82.0]
    return base


def test_configurar_estrategia_variantes():
    assert backtester.configurar_estrategia("A") == {
        "stop_multiplier": 1.0,
        "tp_multiplier": 1.5,
        "tp_parcial": False,
        "trailing": False,
    }
    assert backtester.configurar_estrategia("B") == {
        "stop_multiplier": 1.5,
        "tp_multiplier": 2.0,
        "tp_parcial": False,
        "trailing": False,
    }
    assert backtester.configurar_estrategia("C") == {
        "stop_multiplier": 1.0,
        "tp_multiplier": 1.5,
        "tp_parcial": True,
        "trailing": True,
    }
    assert backtester.configurar_estrategia("D") == {
        "stop_multiplier": 1.5,
        "tp_multiplier": 1.5,
        "tp_parcial": False,
        "trailing": False,
    }
    assert backtester.configurar_estrategia("invalida") == backtester.configurar_estrategia("A")


def test_baixar_dados_historicos_sucesso(monkeypatch):
    payload = [
        [1700000000000, "100.0", "110.0", "90.0", "105.0", "1000.0", 1700003599999, "0", 0, "0", "0", "0"],
    ]

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    monkeypatch.setattr(backtester.requests, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(backtester, "datetime", SimpleNamespace(now=lambda tz=None: pd.Timestamp("2026-01-01", tz="UTC")))

    resultado = backtester.baixar_dados_historicos(symbol="BTCUSDT", intervalo="1h", limite=2)

    assert list(resultado.columns) == ["open_time", "close_time", "open", "high", "low", "close", "volume"]
    assert len(resultado) == 1
    assert resultado.attrs["fonte_dados"] == "BINANCE"
    assert resultado["open"].iloc[0] == 100.0


def test_baixar_dados_historicos_vazio(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return []

    monkeypatch.setattr(backtester.requests, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(backtester, "datetime", SimpleNamespace(now=lambda tz=None: pd.Timestamp("2026-01-01", tz="UTC")))

    resultado = backtester.baixar_dados_historicos(symbol="BTCUSDT", intervalo="1h", limite=2)
    assert resultado.empty
    assert list(resultado.columns) == ["open", "high", "low", "close", "volume"]


def test_helpers_basicos_backtester(sample_df):
    assert backtester._calcular_atr(sample_df, periodo=2) == pytest.approx(200.0)
    assert backtester._calcular_volume_medio(sample_df, periodo=3) == pytest.approx((120 + 130 + 140) / 3)
    assert backtester._fvg_foi_tocado(sample_df, 60250, 60350, candles=2) is True
    assert backtester._fvg_foi_tocado(sample_df, 70000, 70100, candles=2) is False
    assert backtester._calcular_preco_trailing_ativacao(100.0, 120.0) == pytest.approx(110.0)
    assert backtester._atualizar_stop_trailing("COMPRA", 120.0, 5.0) == pytest.approx(115.0)
    assert backtester._atualizar_stop_trailing("VENDA", 120.0, 5.0) == pytest.approx(125.0)
    assert backtester._aplicar_slippage(100.0, 0.01, "COMPRA", "entrada") == pytest.approx(101.0)
    assert backtester._aplicar_slippage(100.0, 0.01, "VENDA", "saida") == pytest.approx(101.0)
    assert backtester._resultado_saida(2.0, 100.0, 110.0, "COMPRA", 0.001) == pytest.approx(19.78)
    assert backtester._resultado_saida(2.0, 110.0, 100.0, "VENDA", 0.001) == pytest.approx(19.8)
    assert backtester._sequencia_maxima_perdas(["GANHO", "PERDA", "PERDA", "GANHO", "PERDA"]) == 2


def test_precomputar_contextos_otimizacao_valid(monkeypatch, trend_df):
    monkeypatch.setattr(backtester, "classificar_regime", lambda df: {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"})
    monkeypatch.setattr(backtester, "extrair_swing_high_low", lambda df, periodo=50: (float(df["high"].max()), float(df["low"].min())))
    monkeypatch.setattr(backtester, "extrair_fvg_bearish_acima", lambda df, preco_atual: (preco_atual + 10, preco_atual + 20))
    monkeypatch.setattr(backtester, "extrair_fvg_bullish_abaixo", lambda df, preco_atual: (preco_atual - 20, preco_atual - 10))

    contextos = backtester._precomputar_contextos_otimizacao(trend_df.iloc[:220].copy())

    assert isinstance(contextos, list)
    assert len(contextos) > 0
    assert {"idx", "preco_atual", "regime", "open_time", "close_time"} <= set(contextos[0].keys())


def test_precomputar_contextos_otimizacao_empty():
    vazio = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    assert backtester._precomputar_contextos_otimizacao(vazio) == {}


def test_precomputar_contextos_otimizacao_missing_cols():
    df = pd.DataFrame({"open": [1, 2, 3], "high": [2, 3, 4], "low": [1, 2, 3], "close": [1, 2, 3], "volume": [10, 20, 30]})
    assert backtester._precomputar_contextos_otimizacao(df) == {}


def test_precomputar_contextos_otimizacao_timestamp_fallback(monkeypatch, trend_df):
    monkeypatch.setattr(backtester, "classificar_regime", lambda df: {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"})
    monkeypatch.setattr(backtester, "extrair_swing_high_low", lambda df, periodo=50: (float(df["high"].max()), float(df["low"].min())))
    monkeypatch.setattr(backtester, "extrair_fvg_bearish_acima", lambda df, preco_atual: (preco_atual + 10, preco_atual + 20))
    monkeypatch.setattr(backtester, "extrair_fvg_bullish_abaixo", lambda df, preco_atual: (preco_atual - 20, preco_atual - 10))

    contextos = backtester._precomputar_contextos_otimizacao(trend_df.iloc[:220].copy())
    assert isinstance(contextos, list)
    assert len(contextos) > 0


def test_simular_decisao_bull_bear_chop(monkeypatch, trend_df):
    monkeypatch.setattr(backtester, "_calcular_atr", lambda df, periodo=14: 5.0)
    monkeypatch.setattr(backtester, "_calcular_volume_medio", lambda df, periodo=20: 10.0)
    monkeypatch.setattr(backtester, "_fvg_foi_tocado", lambda *args, **kwargs: False)
    monkeypatch.setattr(backtester, "extrair_swing_high_low", lambda df, periodo=50: (130.0, 80.0))

    monkeypatch.setattr(backtester, "classificar_regime", lambda df: {"regime": "BULL"})
    monkeypatch.setattr(backtester, "extrair_fvg_bearish_acima", lambda df, preco_atual: (preco_atual + 10.0, preco_atual + 200.0))
    monkeypatch.setattr(backtester, "extrair_fvg_bullish_abaixo", lambda df, preco_atual: (preco_atual - 200.0, preco_atual - 10.0))
    bull = backtester._simular_decisao(trend_df.iloc[:220].copy())
    assert bull["decisao"] == "COMPRA"
    assert bull["direcao"] == "COMPRA"
    assert bull["rr"] > 1.5

    monkeypatch.setattr(backtester, "classificar_regime", lambda df: {"regime": "BEAR"})
    monkeypatch.setattr(backtester, "extrair_fvg_bullish_abaixo", lambda df, preco_atual: (preco_atual - 300.0, preco_atual - 50.0))
    bear = backtester._simular_decisao(trend_df.iloc[:220].copy())
    assert bear["decisao"] == "VENDA"
    assert bear["direcao"] == "VENDA"
    assert bear["rr"] > 1.5

    monkeypatch.setattr(backtester, "classificar_regime", lambda df: {"regime": "CHOP"})
    chop = backtester._simular_decisao(trend_df.iloc[:220].copy(), regime_modo="qualquer")
    assert chop["decisao"] == "AGUARDAR"
    assert chop["regime"] == "CHOP"


def test_simular_decisao_contexto_e_fvg_contexto():
    contexto = {
        "regime": "CHOP",
        "atr": 5.0,
        "preco_atual": 100.0,
        "volume_atual": 200.0,
        "volume_medio": 100.0,
        "topo": 130.0,
        "fundo": 80.0,
        "amplitude": 50.0,
        "fvg_bearish": (110.0, 150.0),
        "fvg_bullish": (60.0, 90.0),
        "tail_highs": [100.0] * 20,
        "tail_lows": [99.0] * 20,
        "open_time": "2026-01-01T00:00:00+00:00",
        "close_time": "2026-01-01T00:00:00+00:00",
    }
    assert backtester._fvg_foi_tocado_em_contexto(contexto, 95.0, 105.0, candles=5) is True
    assert backtester._fvg_foi_tocado_em_contexto(contexto, 150.0, 160.0, candles=5) is False

    vencedor = backtester._simular_decisao_contexto(contexto, regime_modo="qualquer", exigir_rr_minimo=False)
    assert vencedor is not None
    assert vencedor["direcao"] in {"COMPRA", "VENDA"}

    contexto_bull = deepcopy(contexto)
    contexto_bull["regime"] = "BULL"
    buy = backtester._simular_decisao_contexto(contexto_bull, regime_modo="bull_only", exigir_rr_minimo=False)
    assert buy["direcao"] == "COMPRA"

    contexto_bear = deepcopy(contexto)
    contexto_bear["regime"] = "BEAR"
    sell = backtester._simular_decisao_contexto(contexto_bear, regime_modo="bear_only", exigir_rr_minimo=False)
    assert sell["direcao"] == "VENDA"


def test_simular_trade_variante_compra_venda_e_parcial(monkeypatch):
    monkeypatch.setattr(backtester, "_calcular_atr", lambda df, periodo=14: 5.0)
    monkeypatch.setattr(backtester, "calcular_tamanho_posicao", lambda capital, risco, entrada, stop: (1.0, 100.0))

    df_buy = _trade_df_buy()
    trade_buy, exit_idx_buy = backtester._simular_trade_variante(
        df_buy,
        200,
        {"direcao": "COMPRA", "regime": "BULL", "score": 8, "rr": 2.0, "volume_status": "ALTO", "fvg_target": 108.0},
        10000,
        1.0,
        backtester.configurar_estrategia("A"),
        0.0,
        0.0,
    )
    assert trade_buy["resultado"] == "GANHO"
    assert trade_buy["exit_reason"] == "TAKE_PROFIT"
    assert exit_idx_buy == 201

    df_sell = _trade_df_sell()
    trade_sell, exit_idx_sell = backtester._simular_trade_variante(
        df_sell,
        200,
        {"direcao": "VENDA", "regime": "BEAR", "score": 8, "rr": 2.0, "volume_status": "ALTO", "fvg_target": 92.0},
        10000,
        1.0,
        backtester.configurar_estrategia("A"),
        0.0,
        0.0,
    )
    assert trade_sell["resultado"] == "GANHO"
    assert trade_sell["exit_reason"] == "TAKE_PROFIT"
    assert exit_idx_sell == 201

    df_partial = _trade_df_buy()
    trade_partial, exit_idx_partial = backtester._simular_trade_variante(
        df_partial,
        200,
        {"direcao": "COMPRA", "regime": "BULL", "score": 8, "rr": 2.0, "volume_status": "ALTO", "fvg_target": 108.0},
        10000,
        1.0,
        backtester.configurar_estrategia("C"),
        0.0,
        0.0,
    )
    assert trade_partial["tp_parcial"] is True
    assert trade_partial["trailing"] is True
    assert trade_partial["partial_exit_reais"] != 0.0
    assert trade_partial["exit_reason"] in {"TRAILING_STOP", "STOP_AFTER_PARTIAL", "FINAL_CLOSE"}
    assert exit_idx_partial >= 201


def test_executar_backtest(monkeypatch, sample_btc_data):
    calls = {"signals": 0, "trades": 0}

    def fake_simular_decisao(df_slice, **kwargs):
        calls["signals"] += 1
        return {
            "direcao": "COMPRA" if calls["signals"] == 1 else "VENDA",
            "regime": "BULL" if calls["signals"] == 1 else "BEAR",
            "score": 8,
            "rr": 2.0,
            "volume_status": "ALTO",
            "take_profit": 100.0,
            "stop_loss": 90.0,
            "entrada": 95.0,
        }

    def fake_trade(df, start_idx, sinal, capital_atual, risco_percentual, estrategia, slippage, taxa):
        calls["trades"] += 1
        if calls["trades"] == 1:
            trade = {
                "data_entrada": str(df.iloc[start_idx + 1]["open_time"]),
                "direcao": sinal["direcao"],
                "regime": sinal["regime"],
                "entrada": 95.0,
                "stop": 90.0,
                "take": 105.0,
                "quantidade": 1.0,
                "valor_arriscado": 100.0,
                "net_pnl": 100.0,
                "resultado_percentual": 1.0,
                "resultado_reais": 100.0,
                "resultado": "GANHO",
                "realized_rr": 1.0,
            }
            return trade, start_idx + 1

        trade = {
            "data_entrada": str(df.iloc[start_idx + 1]["open_time"]),
            "direcao": sinal["direcao"],
            "regime": sinal["regime"],
            "entrada": 95.0,
            "stop": 100.0,
            "take": 85.0,
            "quantidade": 1.0,
            "valor_arriscado": 100.0,
            "net_pnl": -50.0,
            "resultado_percentual": -0.5,
            "resultado_reais": -50.0,
            "resultado": "PERDA",
            "realized_rr": -0.5,
        }
        return trade, len(df) - 1

    monkeypatch.setattr(backtester, "_simular_decisao", fake_simular_decisao)
    monkeypatch.setattr(backtester, "_simular_trade_variante", fake_trade)

    resultado = backtester.executar_backtest(sample_btc_data.iloc[:220].copy(), variante="A")

    assert resultado["variante"] == "A"
    assert resultado["summary"]["total_trades"] == 2
    assert resultado["summary"]["win_rate"] == 50.0
    assert resultado["summary"]["profit_factor"] == 2.0
    assert resultado["summary"]["sequencia_maxima_perdas"] == 1
    assert resultado["capital_final"] == pytest.approx(10050.0)
    assert len(resultado["trades"]) == 2


def test_executar_backtest_filtros_entrada(monkeypatch, sample_btc_data):
    calls = {"signals": 0, "trades": 0}

    def fake_simular_decisao(df_slice, **kwargs):
        calls["signals"] += 1
        return {
            "direcao": "COMPRA" if calls["signals"] == 1 else "VENDA",
            "regime": "BULL" if calls["signals"] == 1 else "BEAR",
            "score": 8,
            "rr": 2.0,
            "volume_status": "ALTO",
            "take_profit": 100.0,
            "stop_loss": 90.0,
            "entrada": 95.0,
        }

    def fake_trade(df, start_idx, sinal, capital_atual, risco_percentual, estrategia, slippage, taxa):
        calls["trades"] += 1
        trade = {
            "data_entrada": str(df.iloc[start_idx + 1]["open_time"]),
            "direcao": sinal["direcao"],
            "regime": sinal["regime"],
            "entrada": 95.0,
            "stop": 90.0,
            "take": 105.0,
            "quantidade": 1.0,
            "valor_arriscado": 100.0,
            "net_pnl": 25.0,
            "resultado_percentual": 0.25,
            "resultado_reais": 25.0,
            "resultado": "GANHO",
            "realized_rr": 0.25,
        }
        return trade, len(df) - 1

    monkeypatch.setattr(backtester, "_simular_decisao", fake_simular_decisao)
    monkeypatch.setattr(backtester, "_simular_trade_variante", fake_trade)

    resultado = backtester.executar_backtest_filtros_entrada(
        sample_btc_data.iloc[:220].copy(),
        symbol="BTCUSDT",
        regime_modo="bull_bear",
        exigir_rr_minimo=False,
    )

    assert resultado["symbol"] == "BTCUSDT"
    assert resultado["summary"]["total_trades"] == 1
    assert resultado["summary"]["profit_factor"] == "inf"
    assert resultado["summary"]["win_rate"] == 100.0


def test_executar_backtest_sem_dados():
    vazio = pd.DataFrame()
    resultado = backtester.executar_backtest(vazio)
    assert resultado["summary"]["total_trades"] == 0
    assert resultado["capital_final"] == 10000


def test_executar_backtests_variantes(monkeypatch, sample_btc_data):
    seen = []

    def fake_exec(df, capital_inicial=10000, risco_percentual=1.0, slippage=0.0005, taxa=0.0004, variante="A"):
        seen.append(variante)
        return {
            "summary": {
                "profit_factor": 1.0,
                "win_rate": 50.0,
                "media_rr": 1.0,
                "lucro_total_percent": 1.0,
                "drawdown_max_percent": 1.0,
                "expectativa_matematica_percentual": 1.0,
                "total_trades": 1,
                "regimes": {},
            },
            "estrategia": {"stop_multiplier": 1.0},
            "capital_final": 10001,
        }

    monkeypatch.setattr(backtester, "executar_backtest", fake_exec)
    resultados = backtester.executar_backtests_variantes(sample_btc_data.iloc[:220].copy())
    assert set(resultados.keys()) == {"A", "B", "C", "D"}
    assert seen == ["A", "B", "C", "D"]


def test_calcular_metricas_helper():
    trades = [
        {"data_entrada": "2026-01-01", "net_pnl": 100.0, "resultado": "GANHO", "resultado_percentual": 1.0, "realized_rr": 2.0, "regime": "BULL"},
        {"data_entrada": "2026-01-02", "net_pnl": -50.0, "resultado": "PERDA", "resultado_percentual": -0.5, "realized_rr": -1.0, "regime": "BEAR"},
    ]
    metricas = backtester._calcular_metricas(trades, capital_inicial=10000)
    assert metricas["total_trades"] == 2
    assert metricas["win_rate"] == 50.0
    assert metricas["profit_factor"] == 2.0
    assert metricas["media_rr"] == 0.5
    assert metricas["regimes"]["BULL"]["total_trades"] == 1


def test_calcular_metricas_helper_vazio():
    metricas = backtester._calcular_metricas([], capital_inicial=10000)
    assert metricas["total_trades"] == 0
    assert metricas["profit_factor"] == 0.0


def test_yahoo_para_backtester():
    yahoo_df = pd.DataFrame(
        {
            "Date": pd.date_range("2026-01-01", periods=3, freq="h"),
            "Open": [1, 2, 3],
            "High": [2, 3, 4],
            "Low": [0.5, 1.5, 2.5],
            "Close": [1.5, 2.5, 3.5],
            "Volume": [10, 20, 30],
        }
    )
    resultado = backtester._yahoo_para_backtester(yahoo_df)
    assert list(resultado.columns) == ["open_time", "close_time", "open", "high", "low", "close", "volume"]
    assert resultado.attrs["fonte_dados"] == "YAHOO"


def test_relatorios_comparativos():
    resultados_variantes = {
        "A": {
            "estrategia": {"stop_multiplier": 1.0},
            "capital_final": 10100,
            "summary": {
                "profit_factor": 1.2,
                "win_rate": 55.0,
                "media_rr": 1.1,
                "lucro_total_percent": 1.0,
                "lucro_total_valor": 100.0,
                "drawdown_max_percent": 2.0,
                "expectativa_matematica_percentual": 0.3,
                "total_trades": 10,
                "regimes": {},
            },
        },
        "B": {
            "estrategia": {"stop_multiplier": 1.5},
            "capital_final": 10200,
            "summary": {
                "profit_factor": 1.5,
                "win_rate": 60.0,
                "media_rr": 1.4,
                "lucro_total_percent": 2.0,
                "lucro_total_valor": 200.0,
                "drawdown_max_percent": 1.0,
                "expectativa_matematica_percentual": 0.5,
                "total_trades": 12,
                "regimes": {},
            },
        },
    }
    relatorio_variantes = backtester.construir_relatorio_variantes(resultados_variantes)
    assert relatorio_variantes["comparativo"]["melhor_profit_factor"] == "B"
    assert relatorio_variantes["variantes"]["B"]["profit_factor"] == 1.5

    resultados_filtros = {
        "cfg1": {
            "filtros_entrada": {"regime_modo": "bear_only"},
            "capital_final": 10050,
            "summary": {
                "profit_factor": 1.1,
                "win_rate": 50.0,
                "media_rr": 1.0,
                "lucro_total_percent": 0.5,
                "lucro_total_valor": 50.0,
                "drawdown_max_percent": 2.5,
                "expectativa_matematica_percentual": 0.2,
                "total_trades": 8,
                "regimes": {},
            },
        },
        "cfg2": {
            "filtros_entrada": {"regime_modo": "bull_bear"},
            "capital_final": 10150,
            "summary": {
                "profit_factor": 1.3,
                "win_rate": 52.0,
                "media_rr": 1.2,
                "lucro_total_percent": 1.5,
                "lucro_total_valor": 150.0,
                "drawdown_max_percent": 1.8,
                "expectativa_matematica_percentual": 0.4,
                "total_trades": 9,
                "regimes": {},
            },
        },
    }
    relatorio_filtros = backtester.construir_relatorio_filtros_entrada(resultados_filtros)
    assert relatorio_filtros["comparativo"]["melhor_profit_factor"] == "cfg2"

    resultados_por_ativo = {
        "BTCUSDT": resultados_filtros,
        "SOLUSDT": {
            "sol1": {
                "filtros_entrada": {"regime_modo": "qualquer"},
                "capital_final": 10200,
                "summary": {
                    "profit_factor": 1.6,
                    "win_rate": 58.0,
                    "media_rr": 1.5,
                    "lucro_total_percent": 2.2,
                    "lucro_total_valor": 220.0,
                    "drawdown_max_percent": 1.2,
                    "expectativa_matematica_percentual": 0.7,
                    "total_trades": 11,
                    "regimes": {},
                },
            }
        },
    }
    relatorio_multi = backtester.construir_relatorio_multi_ativos(resultados_por_ativo)
    assert relatorio_multi["comparativo"]["melhor_profit_factor"] == "SOLUSDT"
    assert relatorio_multi["ativos"]["SOLUSDT"]["profit_factor"] == 1.6


def test_chave_otimizacao_sol():
    config = {
        "regime_modo": "qualquer",
        "volume_minimo_multiplicador": 1.5,
        "exigir_fvg_nao_tocado": True,
        "lookback_fvg": 5,
        "exigir_rr_minimo": False,
    }
    assert backtester._chave_otimizacao_sol(config) == "regime=qualquer|volume=1.5|fvg=True|janela=5|rr_min=False"


def test_dividir_em_periodos_walkforward(sample_btc_data):
    periodos = backtester._dividir_em_periodos_walkforward(sample_btc_data.iloc[:360].copy(), periodos=3)
    assert len(periodos) == 3
    assert sum(len(segmento) for segmento in periodos) == 360

    pequeno = backtester._dividir_em_periodos_walkforward(sample_btc_data.iloc[:20].copy(), periodos=3)
    assert len(pequeno) == 1


def test_executar_otimizacao_sol(monkeypatch, sample_btc_data):
    monkeypatch.setattr(backtester, "_precomputar_contextos_otimizacao", lambda df: _fake_contextos(df))
    monkeypatch.setattr(
        backtester,
        "_simular_decisao_contexto",
        lambda contexto, **kwargs: {
            "direcao": "COMPRA" if contexto["regime"] == "BULL" else "VENDA",
            "regime": contexto["regime"],
            "score": 8,
            "rr": 2.0,
            "volume_status": "ALTO",
            "fvg_target": contexto["preco_atual"] + 20,
        },
    )
    monkeypatch.setattr(
        backtester,
        "_simular_trade_variante",
        lambda df, start_idx, sinal, capital_atual, risco_percentual, estrategia, slippage, taxa: (
            {
                "data_entrada": str(df.iloc[start_idx + 1]["open_time"]),
                "direcao": sinal["direcao"],
                "regime": sinal["regime"],
                "entrada": 95.0,
                "stop": 90.0,
                "take": 105.0,
                "quantidade": 1.0,
                "valor_arriscado": 100.0,
                "net_pnl": 50.0,
                "resultado_percentual": 0.5,
                "resultado_reais": 50.0,
                "resultado": "GANHO",
                "realized_rr": 1.0,
            },
            start_idx + 1,
        ),
    )
    resultado = backtester.executar_otimizacao_sol(sample_btc_data.iloc[:220].copy())
    assert resultado["symbol"] == "SOLUSDT"
    assert resultado["total_cenarios"] > 0
    assert resultado["melhor_configuracao"] is not None


def test_executar_otimizacao_sol_walkforward(monkeypatch, sample_btc_data):
    monkeypatch.setattr(backtester, "_precomputar_contextos_otimizacao", lambda df: _fake_contextos(df))
    monkeypatch.setattr(
        backtester,
        "_executar_backtest_com_contextos",
        lambda contextos, df, **kwargs: {
            "summary": {
                "profit_factor": 1.34,
                "total_trades": max(1, len(contextos)),
                "win_rate": 45.56,
                "drawdown_max_percent": 2.86,
                "lucro_total_percent": 1.5,
                "lucro_total_valor": 150.0,
                "media_rr": 1.2,
                "sequencia_maxima_perdas": 2,
            },
            "capital_final": 10150.0,
            "trades": [],
            "equity_curve": [10000.0, 10150.0],
        },
    )
    resultado = backtester.executar_otimizacao_sol_walkforward(sample_btc_data.iloc[:360].copy())
    assert resultado["symbol"] == "SOLUSDT"
    assert resultado["total_cenarios"] > 0
    assert resultado["melhor_configuracao"] is not None
    assert resultado["melhor_configuracao"]["resumo"]["media_profit_factor_teste"] == 1.34


def test_avaliar_out_of_sample_sol(monkeypatch, sample_btc_data):
    sequencia = [
        {
            "summary": {
                "profit_factor": 1.13,
                "total_trades": 57,
                "win_rate": 45.0,
                "drawdown_max_percent": 2.0,
                "lucro_total_percent": 1.0,
                "lucro_total_valor": 100.0,
                "media_rr": 1.2,
            },
            "capital_final": 10100,
        },
        {
            "summary": {
                "profit_factor": 1.05,
                "total_trades": 33,
                "win_rate": 41.0,
                "drawdown_max_percent": 3.0,
                "lucro_total_percent": 0.5,
                "lucro_total_valor": 50.0,
                "media_rr": 1.0,
            },
            "capital_final": 10050,
        },
    ]
    monkeypatch.setattr(backtester, "executar_backtest_filtros_entrada", lambda *args, **kwargs: sequencia.pop(0))

    resultado = backtester.avaliar_out_of_sample_sol(sample_btc_data.iloc[:360].copy())
    assert resultado["symbol"] == "SOLUSDT"
    assert resultado["comparacao"]["veredito"] in {"VALIDADA", "MISTA", "OVERFITTING_PROVAVEL"}
    assert "treino_obtido" in resultado["comparacao"]
    assert "teste" in resultado["comparacao"]


def test_salvar_relatorio_e_csv(tmp_path):
    relatorio_path = tmp_path / "relatorio.json"
    csv_path = tmp_path / "trades.csv"
    relatorio = {"summary": {"total_trades": 1}}
    backtester.salvar_relatorio(relatorio, caminho=relatorio_path)
    backtester.salvar_trades_csv(
        [
            {
                "data_entrada": "2026-01-01",
                "direcao": "COMPRA",
                "entrada": 100.0,
                "stop": 95.0,
                "take": 110.0,
                "resultado_percentual": 1.0,
                "resultado_reais": 100.0,
                "regime": "BULL",
            }
        ],
        caminho=csv_path,
    )
    assert relatorio_path.exists()
    assert csv_path.exists()


def test_gerar_relatorio_backtest():
    resultado = {
        "summary": {"total_trades": 1, "profit_factor": 2.0, "regimes": {}},
        "capital_inicial": 10000,
        "capital_final": 10100,
        "trades": [],
    }
    relatorio = backtester.gerar_relatorio_backtest(resultado)
    assert relatorio["summary"]["total_trades"] == 1
