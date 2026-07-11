from unittest.mock import MagicMock
from types import SimpleNamespace

import pandas as pd
import requests

import data_fetcher


def test_baixar_dados_btc_retorna_dataframe(monkeypatch):
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 200
    now_ms = int(pd.Timestamp.now("UTC").timestamp() * 1000)
    mock_response.json.return_value = [
        [now_ms - 7200000, "60000", "60100", "59900", "60050", "100", now_ms - 3600001, 0, 0, 0, 0, 0],
        [now_ms - 3600000, "60050", "60200", "60000", "60150", "110", now_ms - 1, 0, 0, 0, 0, 0],
    ]
    mock_get = MagicMock(return_value=mock_response)
    monkeypatch.setattr(data_fetcher.trusted_market_data_service.provider.session, "get", mock_get)

    df = data_fetcher.baixar_dados_btc("BTCUSDT", "1h", 2)

    assert not df.empty
    assert list(df.columns[:6]) == ["open_time", "close_time", "datetime", "open", "high", "low"]
    assert df.attrs["fonte_dados"] == "BINANCE"
    assert mock_get.call_args.kwargs["timeout"] == (5.0, 10.0)
    assert mock_get.call_args.kwargs["params"]["symbol"] == "BTCUSDT"


def test_baixar_dados_btc_trata_erro(monkeypatch):
    data_fetcher.trusted_market_data_service.cache.clear()
    monkeypatch.setattr(
        data_fetcher.trusted_market_data_service.provider.session,
        "get",
        MagicMock(side_effect=requests.exceptions.RequestException("boom")),
    )

    df = data_fetcher.baixar_dados_btc("BTCUSDT", "1h", 2)

    assert isinstance(df, pd.DataFrame)
    assert df.empty
