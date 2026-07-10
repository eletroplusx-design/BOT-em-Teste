from unittest.mock import MagicMock

import pandas as pd
import requests

import decisor


def _df_base(rows=210, close_start=60000, close_step=5, volume=1000):
    closes = [close_start + i * close_step for i in range(rows)]
    return pd.DataFrame(
        {
            "open": [valor - 2 for valor in closes],
            "high": [valor + 10 for valor in closes],
            "low": [valor - 10 for valor in closes],
            "close": closes,
            "volume": [volume + (i % 5) for i in range(rows)],
            "timestamp": pd.date_range("2026-01-01", periods=rows, freq="h"),
        }
    )


def _df_bull_signal():
    df = _df_base(rows=220, close_start=60000, close_step=20, volume=1500)
    df["high"] = df["close"] + 100
    df["low"] = df["close"] - 100
    return df


def _df_bear_signal():
    closes = [60000 - i * 20 for i in range(220)]
    df = pd.DataFrame(
        {
            "open": [valor + 2 for valor in closes],
            "high": [valor + 100 for valor in closes],
            "low": [valor - 100 for valor in closes],
            "close": closes,
            "volume": [1500 + (i % 5) for i in range(220)],
            "timestamp": pd.date_range("2026-01-01", periods=220, freq="h"),
        }
    )
    return df


def _df_fvg_bearish():
    return pd.DataFrame(
        {
            "open": [100, 98, 97, 96, 95],
            "high": [101, 99, 90, 89, 88],
            "low": [99, 97, 95, 94, 93],
            "close": [100, 98, 96, 95, 94],
            "volume": [1000, 1000, 1000, 1000, 1000],
        }
    )


def _df_fvg_bullish():
    return pd.DataFrame(
        {
            "open": [100, 102, 103, 104, 105],
            "high": [101, 103, 105, 106, 107],
            "low": [99, 101, 104, 107, 108],
            "close": [100, 102, 104, 105, 106],
            "volume": [1000, 1000, 1000, 1000, 1000],
        }
    )


def test_obter_funding_rate_sucesso_e_erro(monkeypatch):
    mock_ok = MagicMock()
    mock_ok.raise_for_status.return_value = None
    mock_ok.json.return_value = {"lastFundingRate": "0.0002"}
    monkeypatch.setattr(decisor.requests, "get", MagicMock(return_value=mock_ok))
    assert decisor.obter_funding_rate("BTCUSDT") == 0.0002

    monkeypatch.setattr(
        decisor.requests,
        "get",
        MagicMock(side_effect=requests.exceptions.RequestException("boom")),
    )
    assert decisor.obter_funding_rate("BTCUSDT") is None


def test_helpers_basicos_e_nulos():
    assert decisor.calcular_volume_medio(_df_base(), 20) is not None
    assert decisor.extrair_tendencia_direcao(_df_base(rows=100)) == "INDEFINIDO"

    df_na = _df_base(rows=200)
    df_na["close"] = [None] * 200
    assert decisor.extrair_tendencia_direcao(df_na) == "INDEFINIDO"

    topo, fundo = decisor.extrair_swing_high_low(_df_base(), 50)
    assert topo >= fundo

    atr = decisor.calcular_atr(_df_base(), 14)
    assert atr is not None

    assert decisor.calcular_rsi(pd.DataFrame(columns=["close"])) is None


def test_fvg_extracao_bearish_e_bullish():
    bearish = decisor.extrair_fvg_bearish_acima(_df_fvg_bearish(), 80)
    assert bearish is not None
    assert bearish[0] > 80

    bullish = decisor.extrair_fvg_bullish_abaixo(_df_fvg_bullish(), 120)
    assert bullish is not None
    assert bullish[1] < 120


def test_tomar_decisao_dados_insuficientes_e_regimes_iniciais(monkeypatch):
    vazio = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    resultado = decisor.tomar_decisao(vazio, symbol="BTCUSDT")
    assert resultado["decisao"] == "AGUARDAR"
    assert "insuficientes" in resultado["motivo"].lower()

    df = _df_base(rows=200)
    monkeypatch.setattr(decisor, "classificar_regime", lambda df: {"regime": "CHOP", "adx": 15, "volatilidade": "NORMAL"})
    resultado_chop = decisor.tomar_decisao(df, symbol="BTCUSDT", fonte_dados="BINANCE")
    assert resultado_chop["decisao"] == "AGUARDAR (MERCADO LATERAL)"

    monkeypatch.setattr(decisor, "classificar_regime", lambda df: {"regime": "INDEFINIDO", "adx": None, "volatilidade": "NORMAL"})
    resultado_ind = decisor.tomar_decisao(df, symbol="BTCUSDT", fonte_dados="BINANCE")
    assert resultado_ind["regime"] == "INDEFINIDO"
    assert "indefinid" in resultado_ind["motivo"].lower()


def test_tomar_decisao_bull_caminhos(monkeypatch):
    df = _df_bull_signal()
    monkeypatch.setattr(decisor, "obter_funding_rate", lambda symbol="BTCUSDT": 0.0002)
    monkeypatch.setattr(decisor, "classificar_regime", lambda df: {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"})
    monkeypatch.setattr(decisor, "calcular_volume_medio", lambda df, periodo=20: 1500)
    monkeypatch.setattr(decisor, "calcular_atr", lambda df, periodo=14: 10)
    monkeypatch.setattr(decisor, "calcular_rsi", lambda df, periodo=14: 50)
    monkeypatch.setattr(decisor, "extrair_swing_high_low", lambda df, periodo=50: (60500, 60300))

    monkeypatch.setattr(decisor, "extrair_fvg_bearish_acima", lambda df, preco_atual: None)
    resultado_sem_fvg = decisor.tomar_decisao(df, symbol="BTCUSDT", fonte_dados="BINANCE")
    assert "Nenhum FVG Bearish" in resultado_sem_fvg["motivo"]

    monkeypatch.setattr(decisor, "extrair_fvg_bearish_acima", lambda df, preco_atual: (60600, 60700))
    resultado_retracao = decisor.tomar_decisao(df, symbol="BTCUSDT", fonte_dados="BINANCE")
    assert resultado_retracao["decisao"] == "AGUARDAR RETRAÇÃO"

    df_timing = df.copy()
    df_timing.loc[df_timing.index[-1], "close"] = 60400
    monkeypatch.setattr(decisor, "extrair_swing_high_low", lambda df, periodo=50: (60500, 60300))
    monkeypatch.setattr(decisor, "calcular_rsi", lambda df, periodo=14: 60)
    monkeypatch.setattr(decisor, "calcular_volume_medio", lambda df, periodo=20: None)
    resultado_volume_ind = decisor.tomar_decisao(df_timing, symbol="BTCUSDT", fonte_dados="BINANCE")
    assert resultado_volume_ind["volume_status"] == "INDETERMINADO"

    monkeypatch.setattr(decisor, "calcular_volume_medio", lambda df, periodo=20: 1200)
    resultado_timing = decisor.tomar_decisao(df_timing, symbol="BTCUSDT", fonte_dados="BINANCE")
    assert resultado_timing["decisao"] == "AGUARDAR (TIMING RUIM)"

    monkeypatch.setattr(decisor, "calcular_rsi", lambda df, periodo=14: 50)
    monkeypatch.setattr(decisor, "calcular_volume_medio", lambda df, periodo=20: 1500)
    monkeypatch.setattr(decisor, "obter_funding_rate", lambda symbol="BTCUSDT": 0.0)
    monkeypatch.setattr(decisor, "extrair_fvg_bearish_acima", lambda df, preco_atual: (60420, 60440))
    monkeypatch.setattr(decisor, "calcular_atr", lambda df, periodo=14: 10)
    resultado_rr = decisor.tomar_decisao(df_timing, symbol="BTCUSDT", fonte_dados="BINANCE")
    assert resultado_rr["decisao"] == "AGUARDAR"
    assert "R/R abaixo" in resultado_rr["motivo"]

    monkeypatch.setattr(decisor, "calcular_atr", lambda df, periodo=14: 10)
    monkeypatch.setattr(decisor, "extrair_fvg_bearish_acima", lambda df, preco_atual: (61000, 62000))
    log_mock = MagicMock(return_value=True)
    monkeypatch.setattr(decisor, "log_decisao", log_mock)
    resultado_ok = decisor.tomar_decisao(df_timing, symbol="BTCUSDT", fonte_dados="BINANCE")
    assert resultado_ok["decisao"] == "COMPRA (Mercado BULL)"
    assert resultado_ok["direcao"] == "COMPRA"
    assert resultado_ok["rr"] >= 1.5
    assert log_mock.called


def test_tomar_decisao_bear_caminhos(monkeypatch):
    df = _df_bear_signal()
    monkeypatch.setattr(decisor, "obter_funding_rate", lambda symbol="BTCUSDT": -0.0002)
    monkeypatch.setattr(decisor, "classificar_regime", lambda df: {"regime": "BEAR", "adx": 30, "volatilidade": "NORMAL"})
    monkeypatch.setattr(decisor, "calcular_volume_medio", lambda df, periodo=20: 1500)
    monkeypatch.setattr(decisor, "calcular_atr", lambda df, periodo=14: 10)
    monkeypatch.setattr(decisor, "calcular_rsi", lambda df, periodo=14: 50)
    monkeypatch.setattr(decisor, "extrair_swing_high_low", lambda df, periodo=50: (60500, 60300))

    monkeypatch.setattr(decisor, "extrair_fvg_bullish_abaixo", lambda df, preco_atual: None)
    resultado_sem_fvg = decisor.tomar_decisao(df, symbol="BTCUSDT", fonte_dados="BINANCE")
    assert "Nenhum FVG Bullish" in resultado_sem_fvg["motivo"]

    monkeypatch.setattr(decisor, "extrair_fvg_bullish_abaixo", lambda df, preco_atual: (59000, 59100))
    resultado_retracao = decisor.tomar_decisao(df, symbol="BTCUSDT", fonte_dados="BINANCE")
    assert resultado_retracao["decisao"] == "AGUARDAR RETRAÇÃO"

    df_timing = df.copy()
    df_timing.loc[df_timing.index[-1], "close"] = 60400
    monkeypatch.setattr(decisor, "calcular_rsi", lambda df, periodo=14: 50)
    monkeypatch.setattr(decisor, "calcular_volume_medio", lambda df, periodo=20: 1500)
    monkeypatch.setattr(decisor, "extrair_fvg_bullish_abaixo", lambda df, preco_atual: (60390, 60395))
    monkeypatch.setattr(decisor, "calcular_atr", lambda df, periodo=14: 10)
    resultado_rr = decisor.tomar_decisao(df_timing, symbol="BTCUSDT", fonte_dados="BINANCE")
    assert resultado_rr["decisao"] == "AGUARDAR"

    monkeypatch.setattr(decisor, "calcular_atr", lambda df, periodo=14: 10)
    monkeypatch.setattr(decisor, "extrair_fvg_bullish_abaixo", lambda df, preco_atual: (58000, 58500))
    log_mock = MagicMock(return_value=True)
    monkeypatch.setattr(decisor, "log_decisao", log_mock)
    resultado_ok = decisor.tomar_decisao(df_timing, symbol="BTCUSDT", fonte_dados="BINANCE")
    assert resultado_ok["decisao"] == "VENDA (Mercado BEAR)"
    assert resultado_ok["direcao"] == "VENDA"
    assert resultado_ok["rr"] >= 1.5
    assert log_mock.called


def test_tomar_decisao_log_falha(monkeypatch):
    df = _df_bull_signal()
    df.loc[df.index[-1], "close"] = 60400
    monkeypatch.setattr(decisor, "obter_funding_rate", lambda symbol="BTCUSDT": None)
    monkeypatch.setattr(decisor, "classificar_regime", lambda df: {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"})
    monkeypatch.setattr(decisor, "calcular_volume_medio", lambda df, periodo=20: 1500)
    monkeypatch.setattr(decisor, "calcular_atr", lambda df, periodo=14: 10)
    monkeypatch.setattr(decisor, "calcular_rsi", lambda df, periodo=14: 50)
    monkeypatch.setattr(decisor, "extrair_swing_high_low", lambda df, periodo=50: (60500, 60300))
    monkeypatch.setattr(decisor, "extrair_fvg_bearish_acima", lambda df, preco_atual: (61000, 62000))
    monkeypatch.setattr(decisor, "log_decisao", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("falha")))

    resultado = decisor.tomar_decisao(df, symbol="BTCUSDT", fonte_dados="BINANCE")
    assert resultado["decisao"] == "COMPRA (Mercado BULL)"
